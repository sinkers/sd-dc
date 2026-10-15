"""Section 6 of the spec - short-circuit temperature rise.

The adiabatic check:

    I^2 * t <= k^2 * S^2         equivalently     S >= sqrt(I^2 * t) / k

with k derived from the conductor's thermal and electrical constants and the
initial and final temperatures the standard permits:

    k = sqrt( (Qc * (beta + 20) / rho_20) * ln((beta + theta_f)/(beta + theta_i)) )

Qc      volumetric heat capacity at 20 C, J/(K.mm^3)
beta    reciprocal of the temperature coefficient of resistivity at 0 C, K
rho_20  electrical resistivity at 20 C, ohm.mm

Reproduces the familiar values: Cu thermoplastic 115, Cu thermosetting 143,
Al thermoplastic 76, Al thermosetting 95. The verification suite asserts them.

Validity: the adiabatic assumption holds for clearing times up to about 5 s.
Beyond that heat leaves the conductor during the fault and the adiabatic
result is conservative but increasingly meaningless; `check` raises rather
than returning a number it cannot stand behind.

The 300 mm^2 thermoplastic break
--------------------------------
Table 5.2 permits a lower short-circuit final temperature for thermoplastic
insulation above 300 mm^2 than at or below it. So k is NOT a constant of the
cable type: it is a function of the candidate conductor size, and it steps
DOWN as the size steps up across the break.

The rule this module enforces, and the one the spec should state explicitly:

    k is resolved inside the size iteration, once per candidate size, from
    that candidate's own Table 5.2 row. It is never resolved once before the
    loop from the starting size.

Getting this wrong is quietly unconservative. A run that resolves k=115 from a
240 mm^2 starting point and then iterates up to 400 mm^2 will credit the
400 mm^2 conductor with 115 when the standard allows it only the reduced
value, and will report a withstand roughly 25 % higher than the cable has.

Because k falls at the break while S rises, the withstand k*S is in principle
non-monotonic in size. `withstand_is_monotonic` checks the actual loaded data
rather than assuming; `minimum_size` scans ascending and does not binary
search, so it is correct either way.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import log, sqrt

from .errors import NoCompliantSize, OpenItem
from .schema import Cable, CheckResult, ConductorMaterial, Insulation, Protection
from .tables.registry import TableStore

#: Volumetric heat capacity at 20 C, J/(K.mm^3)
QC = {ConductorMaterial.COPPER: 3.45e-3, ConductorMaterial.ALUMINIUM: 2.5e-3}
#: Reciprocal of temperature coefficient of resistivity at 0 C, K
BETA = {ConductorMaterial.COPPER: 234.5, ConductorMaterial.ALUMINIUM: 228.0}
#: Electrical resistivity at 20 C, ohm.mm
RHO_20 = {ConductorMaterial.COPPER: 17.241e-6, ConductorMaterial.ALUMINIUM: 28.264e-6}

ADIABATIC_VALIDITY_LIMIT_S = 5.0


def k_factor(material: ConductorMaterial,
             initial_c: float, final_c: float) -> float:
    """k in A.s^0.5/mm^2."""
    if final_c <= initial_c:
        raise ValueError(
            f"final temperature {final_c} must exceed initial {initial_c}"
        )
    beta = BETA[material]
    coeff = QC[material] * (beta + 20.0) / RHO_20[material]
    return sqrt(coeff * log((beta + final_c) / (beta + initial_c)))


@dataclass(frozen=True)
class ThermalLimits:
    initial_c: float
    final_c: float
    source: str
    size_band_upper_mm2: float


def limits_for(store: TableStore, insulation: Insulation,
               size_mm2: float) -> ThermalLimits:
    """Table 5.2 row for this insulation AND this conductor size.

    The size argument is not optional and is not cached across sizes. That is
    the whole point of this function.
    """
    row = store.row("sc_limits", insulation=insulation, size_max_mm2=size_mm2)
    return ThermalLimits(
        initial_c=float(row["initial_temperature_c"]),
        final_c=float(row["final_temperature_c"]),
        source="AS/NZS 3008.1.1:2025 Table 5.2",
        size_band_upper_mm2=float(row["size_max_mm2"]),
    )


def k_for_size(store: TableStore, cable: Cable, size_mm2: float) -> tuple[float, ThermalLimits]:
    lim = limits_for(store, cable.insulation, size_mm2)
    return k_factor(cable.material, lim.initial_c, lim.final_c), lim


def withstand_i2t(store: TableStore, cable: Cable, size_mm2: float) -> float:
    """Permissible I^2.t in A^2.s for one cable of this size, including
    the benefit of parallel sets (each set carries I/n, so the assembly
    withstands n^2 times a single set)."""
    k, _ = k_for_size(store, cable, size_mm2)
    return (cable.parallel_sets ** 2) * (k * size_mm2) ** 2


def withstand_is_monotonic(store: TableStore, cable: Cable,
                           sizes: list[float]) -> tuple[bool, list[float]]:
    """Does withstand actually increase with size across the Table 5.2 break?

    Returns (monotonic, withstand values). Checked rather than assumed, so
    that a future edition that moves the break cannot silently invalidate a
    search strategy that relies on monotonicity.
    """
    values = [withstand_i2t(store, cable, s) for s in sorted(sizes)]
    monotonic = all(b >= a for a, b in zip(values, values[1:]))
    return monotonic, values


def minimum_size(store: TableStore, cable: Cable, protection: Protection,
                 candidate_sizes: list[float]) -> float:
    """Smallest candidate size whose withstand covers the let-through energy.

    Ascending linear scan. Deliberately not a binary search: k steps down at
    the Table 5.2 size break, so monotonicity of the withstand is a property
    of the data, not a guarantee of the method.
    """
    let_through = fault_energy_a2s(protection)
    for size in sorted(candidate_sizes):
        if withstand_i2t(store, cable, size) >= let_through:
            return size
    raise NoCompliantSize(
        "No candidate size withstands the prospective fault energy "
        f"{let_through:.4g} A^2.s",
        blocking={"largest_considered_mm2": max(candidate_sizes),
                  "let_through_a2s": let_through},
    )


def fault_energy_a2s(protection: Protection) -> float:
    i = protection.prospective_fault_current_a
    return i * i * protection.clearing_time_s


def check(store: TableStore, cable: Cable, protection: Protection) -> CheckResult:
    """Short-circuit withstand of the cable as actually sized."""
    if protection.clearing_time_s > ADIABATIC_VALIDITY_LIMIT_S:
        raise OpenItem(
            f"Clearing time {protection.clearing_time_s} s exceeds the "
            f"{ADIABATIC_VALIDITY_LIMIT_S} s validity limit of the adiabatic "
            "method. A non-adiabatic assessment is required and is not "
            "implemented; this is a recorded open item, not a default."
        )

    k, lim = k_for_size(store, cable, cable.size_mm2)
    permitted = withstand_i2t(store, cable, cable.size_mm2)
    let_through = fault_energy_a2s(protection)

    return CheckResult(
        name="short-circuit withstand",
        passed=let_through <= permitted,
        governing_value=let_through,
        limit=permitted,
        units="A^2.s",
        detail={
            "k": k,
            "initial_temperature_c": lim.initial_c,
            "final_temperature_c": lim.final_c,
            "table_5_2_band_upper_mm2": lim.size_band_upper_mm2,
            "size_mm2": cable.size_mm2,
            "parallel_sets": cable.parallel_sets,
            "minimum_size_mm2": sqrt(let_through) / (k * cable.parallel_sets),
            "source": lim.source,
        },
    )
