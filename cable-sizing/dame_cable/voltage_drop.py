"""Section 5 of the spec - voltage drop.

This is the one module that can be checked against the standard's own answer,
because the standard publishes both the inputs (a.c. resistance and reactance)
and the result (mV/A/m). `cross_check_mv_per_a_m` does exactly that and the
verification suite asserts agreement to better than 1 %.

Method
------
For a route factor m (2 for d.c. and single-phase, sqrt(3) for three-phase):

    mV/A/m  = m * (R*cos(phi) + X*sin(phi))          R, X in ohm/km == mohm/m
    V_drop  = mV/A/m * I * L / 1000                  L in metres, result volts

The bracket is the standard's approximation: it takes the in-phase component
of the phasor drop and discards the quadrature component, which is
conservative-to-negligible at the power factors of real installations. The
second-order term is available via `exact=True`:

    V_exact = V_approx + (I*(X*cos(phi) - R*sin(phi)))^2 / (2 * V_receiving)

and is worth switching on only for long runs at leading power factor, where
the discarded term stops being negligible.

Resistance temperature correction
---------------------------------
The resistance table is published at discrete operating temperatures. A value
at an arbitrary temperature is obtained by the alpha-20 correction from the
nearest tabulated temperature, NOT by interpolating between table rows:

    R(theta) = R(theta_t) * (1 + a20*(theta   - 20)) / (1 + a20*(theta_t - 20))

Conductor operating temperature is itself load dependent. A cable carrying
half its rating does not sit at 90 C, and pretending it does inflates the
computed drop. With `operating_temperature_from_load=True` the module uses

    theta = theta_ambient + (theta_max - theta_ambient) * (I_b / I_z)^2

This is a refinement, and it is OFF by default: the conservative assumption is
that the conductor is at its maximum continuous temperature. Turning it on
requires an I_z, and the caller must have computed one for the same segment.
"""

from __future__ import annotations

import math

from dataclasses import dataclass, field

from .errors import MissingTableData, OpenItem
from .schema import (
    Cable,
    CableConstruction,
    CheckResult,
    ConductorForm,
    ConductorMaterial,
    Insulation,
    Load,
    Route,
    RouteSegment,
    SystemType,
)
from .tables.registry import TableStore

#: Temperature coefficient of resistance at 20 C, per kelvin.
ALPHA_20 = {
    ConductorMaterial.COPPER: 3.93e-3,
    ConductorMaterial.ALUMINIUM: 4.03e-3,
}


#: Table 4.1/4.5-4.9 cover fixed wiring; 4.2/4.10 cover flexible cords and
#: flexible cables. The split is a real axis of the standard, not a modelling
#: choice, and the tinned-copper factor differs between them too.
def _form_class(cable: Cable) -> str:
    return "flexible" if cable.form is ConductorForm.FLEXIBLE else "fixed"


#: a.c. resistance is tabulated per construction: 4.5 single-core, 4.7
#: multicore with circular conductors, 4.9 multicore with shaped conductors.
#: Formation does not enter it, so all three single-core formations share a
#: row.
_RESISTANCE_CONSTRUCTION = {
    CableConstruction.SINGLE_CORE_TREFOIL: "single-core",
    CableConstruction.SINGLE_CORE_FLAT_TOUCHING: "single-core",
    CableConstruction.SINGLE_CORE_FLAT_SPACED: "single-core",
    # OI-4.14: CableConstruction.MULTICORE does not say whether the conductors
    # are circular (4.7) or shaped (4.9), and the two tables differ. Both are
    # present in resistance.csv. Circular is assumed here because it is the
    # commoner construction; a shaped-conductor cable will read slightly low.
    CableConstruction.MULTICORE: "multicore-circular",
}

#: Reactance is tabulated per formation for single-core and per conductor
#: profile for multicore.
_REACTANCE_CONSTRUCTION = {
    CableConstruction.SINGLE_CORE_TREFOIL: "trefoil",
    CableConstruction.SINGLE_CORE_FLAT_TOUCHING: "flat_touching",
    CableConstruction.MULTICORE: "circular",
}

#: Tables 4.1 and 4.2 use a three-way insulation axis, coarser than the
#: Insulation enum: one class serves several enum members.
_INSULATION_CLASS = {
    Insulation.THERMOPLASTIC_75: "PVC",
    Insulation.THERMOPLASTIC_90: "PVC",
    Insulation.THERMOSETTING_90: "XLPE",
    Insulation.THERMOSETTING_110: "Elastomer",
}


def resistance_at(store: TableStore, cable: Cable, temperature_c: float) -> float:
    """A.c. resistance in ohm/km at an arbitrary conductor temperature."""
    table = store.tables["resistance"]
    form_class = _form_class(cable)
    construction = _RESISTANCE_CONSTRUCTION[cable.construction]
    key = {
        "form_class": form_class,
        "construction": construction,
        "material": cable.material.value,
        "size_mm2": cable.size_mm2,
    }
    temps = sorted({
        row["temperature_c"]
        for row in table.rows
        if all(row.get(k) == v for k, v in key.items())
    })
    if not temps:
        raise MissingTableData("resistance", key, table.spec.source)
    base_t = min(temps, key=lambda t: abs(t - temperature_c))
    r_base = store.value("resistance", temperature_c=base_t, **key)
    a = ALPHA_20[cable.material]
    return r_base * (1 + a * (temperature_c - 20.0)) / (1 + a * (base_t - 20.0))


def reactance(store: TableStore, cable: Cable) -> float:
    """Reactance in ohm/km. Zero for d.c.

    Tables 4.1 and 4.2 are tabulated for TOUCHING formation only. NOTE 1 of
    each gives an additive correction for spaced single-core, keyed on the
    spacing in conductor diameters -- which `Cable` does not carry. Rather
    than return the touching value for a spaced arrangement, which
    understates the reactance and so understates the voltage drop, this
    raises.
    """
    if cable.construction is CableConstruction.SINGLE_CORE_FLAT_SPACED:
        raise OpenItem(
            "reactance for spaced single-core needs the spacing in conductor "
            "diameters (Tables 4.1/4.2 NOTE 1: add 0.0254, 0.0435 or 0.0690 "
            "ohm/km at 0.5D, 1D or 2D). Cable carries no spacing field. "
            "Returning the touching value would understate the drop."
        )
    return store.value("reactance",
                       form_class=_form_class(cable),
                       construction=_REACTANCE_CONSTRUCTION[cable.construction],
                       insulation_class=_INSULATION_CLASS[cable.insulation],
                       size_mm2=cable.size_mm2)


def operating_temperature_c(cable: Cable, ambient_c: float,
                            ib_a: float, iz_a: float) -> float:
    """Steady-state conductor temperature at partial load.

        theta = theta_a + (theta_max - theta_a) * (I_b / I_z)^2

    Clamped at theta_max: a circuit loaded beyond its capacity is a failed
    capacity check, not a licence to extrapolate the temperature rise.
    """
    if iz_a <= 0:
        raise ValueError("iz_a must be > 0 to derive an operating temperature")
    ratio = min(ib_a / iz_a, 1.0)
    theta_max = cable.insulation.max_continuous_c
    return ambient_c + (theta_max - ambient_c) * ratio * ratio


def mv_per_a_m(r_ohm_per_km: float, x_ohm_per_km: float,
               system: SystemType, power_factor: float) -> float:
    """The standard's mV/A/m figure, computed from R and X."""
    cos_phi = power_factor
    sin_phi = (1.0 - cos_phi ** 2) ** 0.5
    x = 0.0 if system is SystemType.DC else x_ohm_per_km
    return system.voltage_drop_multiplier * (r_ohm_per_km * cos_phi + x * sin_phi)


@dataclass
class SegmentDrop:
    segment: RouteSegment
    r_ohm_per_km: float
    x_ohm_per_km: float
    conductor_temperature_c: float
    mv_per_a_m: float
    drop_v: float

    def __str__(self) -> str:
        tag = self.segment.label or "segment"
        return (f"{tag}: {self.segment.length_m:g} m at "
                f"{self.conductor_temperature_c:.1f} C, "
                f"{self.mv_per_a_m:.4g} mV/A/m -> {self.drop_v:.3f} V")


@dataclass
class VoltageDropResult:
    cable: Cable
    per_segment: list[SegmentDrop]
    total_drop_v: float
    drop_fraction: float
    exact: bool
    detail: dict = field(default_factory=dict)

    @property
    def drop_percent(self) -> float:
        return 100.0 * self.drop_fraction


def voltage_drop(
    store: TableStore,
    cable: Cable,
    route: Route,
    load: Load,
    *,
    exact: bool = False,
    operating_temperature_from_load: bool = False,
    iz_a: float | None = None,
) -> VoltageDropResult:
    """Total voltage drop over a route, summed segment by segment.

    Each segment gets its own conductor temperature, because ambient varies
    along a route - a riser in a hot plant room and a buried run to a
    switchroom do not sit at the same temperature and should not share an R.
    """
    if operating_temperature_from_load and iz_a is None:
        raise ValueError(
            "operating_temperature_from_load=True requires iz_a for the same "
            "cable and route"
        )

    cos_phi = load.power_factor
    sin_phi = load.sin_phi
    n = cable.parallel_sets
    i = load.design_current_a

    per_segment: list[SegmentDrop] = []
    total = 0.0
    for seg in route.segments:
        if operating_temperature_from_load:
            theta = operating_temperature_c(cable, seg.method.ambient_c, i, iz_a)
        else:
            theta = cable.insulation.max_continuous_c

        r = resistance_at(store, cable, theta) / n
        x = (0.0 if load.system is SystemType.DC else reactance(store, cable) / n)

        mvam = mv_per_a_m(r, x, load.system, cos_phi)
        drop = mvam * i * seg.length_m / 1000.0

        if exact and load.system is not SystemType.DC:
            m = load.system.voltage_drop_multiplier
            quad = m * i * (x * cos_phi - r * sin_phi) * seg.length_m / 1000.0
            v_recv = max(load.nominal_voltage_v - total - drop, 1.0)
            drop += quad * quad / (2.0 * v_recv)

        per_segment.append(SegmentDrop(
            segment=seg, r_ohm_per_km=r, x_ohm_per_km=x,
            conductor_temperature_c=theta, mv_per_a_m=mvam, drop_v=drop,
        ))
        total += drop

    return VoltageDropResult(
        cable=cable,
        per_segment=per_segment,
        total_drop_v=total,
        drop_fraction=total / load.nominal_voltage_v,
        exact=exact,
        detail={"route_length_m": route.total_length_m,
                "power_factor": cos_phi,
                "parallel_sets": n},
    )


def check_voltage_drop(result: VoltageDropResult, load: Load) -> CheckResult:
    limit_v = load.max_voltage_drop_fraction * load.nominal_voltage_v
    return CheckResult(
        name="voltage drop",
        passed=result.total_drop_v <= limit_v,
        governing_value=result.total_drop_v,
        limit=limit_v,
        units="V",
        detail={"percent": result.drop_percent,
                "limit_percent": 100 * load.max_voltage_drop_fraction,
                "segments": [str(s) for s in result.per_segment]},
    )


def mv_per_a_m_max(r_ohm_per_km: float, x_ohm_per_km: float,
                   system: SystemType) -> float:
    """The standard's "Max" column: m x Zc, per Clause 4.3.3.

    Clause 4.3.1 gives the condition -- the maximum drop occurs when the load
    power factor equals the cable power factor -- and 4.3.3 states the tabulated
    three-phase values represent sqrt(3)Zc.
    """
    return system.voltage_drop_multiplier * math.hypot(r_ohm_per_km, x_ohm_per_km)


def mv_per_a_m_08_column(r_ohm_per_km: float, x_ohm_per_km: float,
                         system: SystemType) -> tuple[float, str]:
    """The standard's "0.8 p.f." column, which is NOT a 0.8 p.f. value.

    R-VD-2. The column is the worst case over load power factors in the closed
    range 0.8 lagging to unity:

        Vc = m * max{ R.cos(th) + X.sin(th) : cos(th) in [0.8, 1.0] }

    R.cos(th) + X.sin(th) peaks at cos(th) = R/Z, the cable's own power factor.
    While that lies inside [0.8, 1.0] the peak is interior and the worst case is
    Zc -- identical to the Max column. Once the cable power factor drops below
    0.8 the function decreases across the whole range and the worst case sits at
    the 0.8 end.

    So the branch point is set by the CABLE, not by a fixed conductor size. It
    lands at 185, 240 and 300 mm2 on Tables 4.15(B), 4.14(B) and 4.17(B)
    respectively. Reading it off the printed columns understates it, because the
    two branches agree to three significant figures for a size or two either
    side of the switch.

    Returns (value, branch) where branch is "max" or "0.8".
    """
    m = system.voltage_drop_multiplier
    z = math.hypot(r_ohm_per_km, x_ohm_per_km)
    if z == 0.0:
        return 0.0, "max"
    if r_ohm_per_km / z >= 0.8:
        return m * z, "max"
    return m * (0.8 * r_ohm_per_km + 0.6 * x_ohm_per_km), "0.8"


def cross_check_mv_per_a_m(
    store: TableStore, cable: Cable, load: Load, power_factor: float,
) -> dict:
    """Compare the computed mV/A/m against the standard's own tabulated value.

    Returns the two figures and their relative difference. The verification
    suite asserts this stays under 1 %. Raises MissingTableData if the
    mV/A/m table has not been transcribed - there is nothing to check against.
    """
    theta = cable.insulation.max_continuous_c
    r = resistance_at(store, cable, theta)
    x = 0.0 if load.system is SystemType.DC else reactance(store, cable)
    # R-VD-5/R-VD-6. The tabulated "0.8 p.f." column is a Clause 4.2 worst case
    # over the range 0.8..1.0, NOT the Clause 4.5 drop at exactly 0.8. Comparing
    # the latter against the former is a category error, not a tolerance
    # problem: both values are correct and they are different quantities.
    if abs(power_factor - 0.8) < 1e-9:
        computed, branch = mv_per_a_m_08_column(r, x, load.system)
    else:
        computed, branch = mv_per_a_m(r, x, load.system, power_factor), "clause_4.5"
    tabulated = store.value(
        "mv_per_a_m",
        system=load.system,
        material=cable.material,
        insulation=cable.insulation,
        construction=cable.construction,
        size_mm2=cable.size_mm2,
        power_factor=power_factor,
    )
    return {
        "computed": computed,
        "tabulated": tabulated,
        "relative_difference": abs(computed - tabulated) / tabulated,
        "r_ohm_per_km": r,
        "x_ohm_per_km": x,
        "conductor_temperature_c": theta,
        "branch": branch,
        "cable_power_factor": (r / math.hypot(r, x)) if (r or x) else None,
    }
