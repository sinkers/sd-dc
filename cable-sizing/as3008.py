"""
AS/NZS 3008.1.1 calculation primitives.

This module implements the *calculations* of AS/NZS 3008.1.1 (Australian /
New Zealand cable selection standard) from first principles. It deliberately
contains no reproduction of the copyrighted rating tables from the standard --
current-carrying capacities come from the manufacturer catalogue in
`../cables/cable_catalog.json`, which is published Nexans Australia data
derived from the same standard.

Where the standard publishes a lookup table that is really a closed-form
physical relationship, the relationship is implemented directly and validated
against published values. See README.md for the validation evidence.

Reference: AS/NZS 3008.1.1:2017 (Tables 4-21, 30-31, 34-37, 52) and
AS/NZS 3008.1.1:2025 (Tables 3.9-3.26, 4.1-4.11, 5.1).
"""

import json
import math

import as3008_2025
import tables
import os
from dataclasses import dataclass

#: Provenance, clause numbers and units for the AS/NZS 3000 tables. This half
#: is publishable and is tracked in git, so it loads at import and the
#: verification report works on a checkout with no licensed data at all.
PUBLIC_TABLES = tables.load("reference_public")


def _merged_tables():
    """Public metadata joined to the private table bodies.

    Callers see one mapping with the shape they always had --
    TABLES[key]["data"] and TABLES[key]["verified"] both work -- but the
    bodies come from the gitignored file and are read only on first use.
    Before this, `TABLES = _load_tables()` ran at module scope, so a checkout
    without the licensed data could not even `import as3008`. See tables.py.
    """
    private = tables.load("reference")
    out = {}
    for key, meta in PUBLIC_TABLES.items():
        if key.startswith("_") or not isinstance(meta, dict):
            continue
        merged = {k: v for k, v in meta.items()
                  if k not in ("data_location", "data_entries")}
        body = private.get(key, {})
        if "data" in meta:                       # released body, e.g. clause 3.6.2
            merged["data"] = meta["data"]
        elif "data" in body:
            merged.update(body)
        out[key] = merged
    return out


TABLES = tables.LazyMapping(_merged_tables)

#: Kept for callers that want the path; no longer read at import.
TABLES_PATH = tables.path_for("reference")


def _numeric_data(table_key):
    """Return a table's `data` block with numeric keys."""
    return {float(k): v for k, v in TABLES[table_key]["data"].items()}


def verification_report():
    """Provenance and verification status of every reference table.

    Returns a list of dicts, one per table. Use this before issuing a design:
    any table with verified=False has not been read from the printed standard.
    """
    out = []
    for key, block in PUBLIC_TABLES.items():
        if key.startswith("_") or not isinstance(block, dict):
            continue
        out.append({
            "table": key,
            "title": block.get("title", ""),
            "standard": block.get("standard", ""),
            "verified": bool(block.get("verified", False)),
            "source": block.get("source", ""),
            "note": block.get("note", ""),
            # The public half records the body's size rather than
            # carrying it, so "populated" means the body exists,
            # not that it is loaded.
            "populated": bool(block.get("data")
                              or block.get("data_entries")),
            "superseded_by": block.get("superseded_by"),
        })
    # AS/NZS 3008.1.1:2025 Sections 4 and 5, read from the printed standard on
    # 2026-09-04. Separate files because they are a different standard from the
    # AS/NZS 3000 data above, and licensed, so they may legitimately be absent.
    # The report says so rather than raising -- provenance has to be readable on
    # a checkout that has no licensed data at all.
    for file_id, getter, title in (
        ("impedance", lambda: as3008_2025.IMPEDANCE,
         "AS/NZS 3008.1.1:2025 Tables 4.1-4.13 (reactance and resistance)"),
        ("vc", lambda: as3008_2025.VC,
         "AS/NZS 3008.1.1:2025 Tables 4.14-4.31 (voltage drop)"),
        ("short_circuit", lambda: as3008_2025.SHORT_CIRCUIT,
         "AS/NZS 3008.1.1:2025 Table 5.2 (short-circuit limit temperatures)"),
    ):
        spec = tables.MANIFEST_BY_ID[file_id]
        present = tables.available(file_id)
        out.append({
            "table": spec.filename,
            "title": (f"{title} -- {len(getter())} tables" if present
                      else f"{title} -- NOT PRESENT"),
            "standard": "AS/NZS 3008.1.1:2025",
            "verified": present,
            "source": ("read from the printed standard 2026-09-04" if present
                       else f"licensed, fetch from {spec.fetch}"),
            "note": "" if present else "absent from this checkout",
            "populated": present,
            "superseded_by": None,
        })
    return out


def unverified_tables():
    """Names of the reference tables not yet verified against the printed standard."""
    return [t["table"] for t in verification_report() if not t["verified"]]

# ---------------------------------------------------------------------------
# Conductor physical properties
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ConductorProps:
    """Physical constants for a conductor material.

    Qc    -- volumetric heat capacity at 20 C (J/(K.mm^3))
    beta  -- reciprocal of temperature coefficient of resistivity at 0 C (K)
    rho20 -- electrical resistivity at 20 C (ohm.mm)
    alpha -- temperature coefficient of resistance at 20 C (1/K)
    """
    name: str
    Qc: float
    beta: float
    rho20: float
    alpha: float


COPPER = ConductorProps("Copper", Qc=3.45e-3, beta=234.5, rho20=17.241e-6, alpha=0.00393)
ALUMINIUM = ConductorProps("Aluminium", Qc=2.50e-3, beta=228.0, rho20=28.264e-6, alpha=0.00403)

CONDUCTORS = {"Copper": COPPER, "Aluminium": ALUMINIUM, "Cu": COPPER, "Al": ALUMINIUM}


# ---------------------------------------------------------------------------
# Insulation properties
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Insulation:
    """Temperature limits for a cable insulation type.

    normal_use_c      -- the rating basis. Current-carrying capacities in
                         AS/NZS 3008 are derived at this temperature, so it is
                         the ceiling used for derating and operating temperature.
    max_permissible_c -- higher limit allowed for V-90 and V-90HT only where the
                         cable is protected against severe mechanical damage.
                         Recorded, but never applied automatically.
    min_ambient_c     -- lowest ambient the insulation is rated for, or None
                         meaning refer to manufacturer's information.
    sc_limit_temp_c   -- permitted final conductor temperature under short
                         circuit. From AS/NZS 3008, NOT from Table 3.2.
    """
    code: str
    normal_use_c: float
    max_permissible_c: float
    min_ambient_c: float
    sc_limit_temp_c: float
    family: str = ""

    @property
    def max_temp_c(self):
        """The rating basis temperature. See normal_use_c."""
        return self.normal_use_c

    def sc_limit_c(self, area_mm2):
        """Final short-circuit temperature at `area_mm2`, AS/NZS 3008 Table 5.2.

        Size-dependent for thermoplastic: 160 C at or below 300 mm2, 140 C
        above it. `sc_limit_temp_c` holds the at-or-below-300 value and is kept
        for callers that predate the size dependence.
        """
        return sc_limit_temp(self, area_mm2)[0]

    def sc_limit_is_verified(self):
        """Whether Table 5.2 names this insulation, or a family guess was used."""
        return as3008_2025.sc_limit_is_tabulated(self.code)


# Permitted final short-circuit temperature.
#
# VERIFIED against AS/NZS 3008.1.1:2025 Table 5.2, read from the printed
# standard on 2026-09-04 and held in as3008_short_circuit.json. Two things the
# previous by-family assumption got wrong:
#
#   * thermoplastic is 160 C only at or below 300 mm2; above 300 mm2 it is
#     140 C. Ignoring that overstates k by 11 % and undersizes a large PVC
#     conductor against fault by about 13 %.
#   * R-S-150 and Type 150 fibrous are 350 C, not the 250 C that assigning by
#     the elastomeric family produced. The old value was conservative.
#
# The by-family map is retained only for insulations Table 5.2 does not name --
# MIMS is the one that arises in practice, and it stays unverified.
SC_LIMIT_BY_FAMILY = {
    "thermoplastic": 160.0,
    "elastomeric": 250.0,
    "xlpe": 250.0,
    "mims": 250.0,      # UNVERIFIED: not named in Table 5.2
    "other": 160.0,
}

SC_LIMIT_UNVERIFIED_FAMILIES = ("mims",)


def sc_limit_temp(insulation, area_mm2):
    """Final short-circuit temperature for `insulation` at `area_mm2`, Table 5.2.

    Falls back to the family assumption only where Table 5.2 does not name the
    material. Returns (temperature_c, verified).
    """
    limit = as3008_2025.sc_limit_temp_c(insulation.code, area_mm2)
    if limit is not None:
        return limit, True
    return SC_LIMIT_BY_FAMILY[insulation.family], False


def _build_insulations():
    """Assemble the insulation table from AS/NZS 3000 Table 3.2."""
    out = {}
    for code, row in TABLES["limiting_temperatures_as3000_table_3_2"]["data"].items():
        family = row["family"]
        out[code] = Insulation(
            code=code,
            normal_use_c=float(row["normal_use_c"]),
            max_permissible_c=float(row["max_permissible_c"]),
            min_ambient_c=(None if row["min_ambient_c"] is None
                           else float(row["min_ambient_c"])),
            sc_limit_temp_c=(as3008_2025.sc_limit_temp_c(code, 300.0)
                             or SC_LIMIT_BY_FAMILY[family]),
            family=family,
        )
    return out


INSULATIONS = tables.LazyMapping(_build_insulations)

# "X-110" is not an AS/NZS 3000 Table 3.2 designation, but it appears in cable
# sizing tools and catalogues. Treat it as X-HF-110.
INSULATION_ALIASES = {"X-110": "X-HF-110"}


def resolve_insulation(code):
    """Look up an insulation by code, tolerating catalogue strings like 'X-90 XLPE'."""
    if code in INSULATIONS:
        return INSULATIONS[code]
    if code in INSULATION_ALIASES:
        return INSULATIONS[INSULATION_ALIASES[code]]
    for token in str(code).replace("/", " ").split():
        if token in INSULATIONS:
            return INSULATIONS[token]
        if token in INSULATION_ALIASES:
            return INSULATIONS[INSULATION_ALIASES[token]]
    raise KeyError(f"Unknown insulation code: {code!r}")


# Tabulated conductor-temperature columns. AS/NZS 3008.1.1:2025 Clause 4.4 names
# six, and 80 C was missing here -- Table 4.5(A) and Table 4.14(B) both carry it.
#
# Capacity does not reach voltage drop through a continuous resistance. It
# reaches it through this six-valued band, so a small change in capacity can
# move the band and produce a step change in the computed drop. That is the
# mechanism, not a rounding nicety.
TEMP_COLUMNS = (45.0, 60.0, 75.0, 80.0, 90.0, 110.0)


# Ambient reference conditions (AS/NZS 3008.1.1 Australian vs NZ basis).
AMBIENT_BASIS = {
    "AU": {"air_c": 40.0, "soil_c": 25.0},
    "NZ": {"air_c": 30.0, "soil_c": 15.0},
}


# ---------------------------------------------------------------------------
# Design current
# ---------------------------------------------------------------------------

PHASE_MODES = ("3-phase", "1-phase", "DC", "2-phase-120", "2-phase-180")

# Voltage-drop multiplier: Vd = factor * I * L * Zc / 1000
VD_FACTOR = {
    "3-phase": math.sqrt(3.0),
    "1-phase": 2.0,
    "DC": 2.0,
    "2-phase-120": 2.0,
    "2-phase-180": 2.0,
}

# Balanced-mains variants use reduced multipliers (AS/NZS 3008 clause 4.5).
VD_FACTOR_BALANCED = {
    "3-phase": math.sqrt(3.0),
    "1-phase": 2.0,
    "DC": 2.0,
    "2-phase-120": 1.5,
    "2-phase-180": 1.0,
}


def design_current(phase_mode, voltage_v, kw=None, kva=None, amps=None, hp=None,
                   power_factor=None, efficiency=1.0):
    """Return the per-phase design current in amperes.

    Exactly one of kw / kva / amps / hp must be supplied. `power_factor` is
    required for kw and hp ratings.
    """
    if phase_mode not in PHASE_MODES:
        raise ValueError(f"phase_mode must be one of {PHASE_MODES}")
    supplied = [x is not None for x in (kw, kva, amps, hp)]
    if sum(supplied) != 1:
        raise ValueError("supply exactly one of kw, kva, amps, hp")
    if amps is not None:
        return float(amps)

    if hp is not None:
        kw = hp * 0.7457 / efficiency
    if kw is not None:
        if not power_factor:
            raise ValueError("power_factor is required for a kW or hp rating")
        va = kw * 1000.0 / power_factor
    else:
        va = kva * 1000.0

    if phase_mode == "3-phase":
        return va / (math.sqrt(3.0) * voltage_v)
    if phase_mode == "DC":
        # Power factor does not apply to DC; treat the rating as real power.
        return (kw * 1000.0 if kw is not None else va) / voltage_v
    # Single phase and both two-phase arrangements draw line current over V.
    return va / voltage_v


# ---------------------------------------------------------------------------
# Derating (rating factors)
# ---------------------------------------------------------------------------

# Tabulated air ambient rating factors carried in the repo cable catalogue,
# for 90 C XLPE on a 40 C air basis. These are measured/tabulated values and
# are more conservative than the closed form below, so they win where they
# apply. Keyed by ambient temperature (C).
AMBIENT_FACTORS_XLPE90_AIR40 = tables.LazyMapping(
    lambda: _numeric_data("ambient_rating_factors_air"))


def _interpolate(table, x):
    """Linear interpolation over a {x: y} table. Returns None if x is outside."""
    keys = sorted(table)
    if x < keys[0] or x > keys[-1]:
        return None
    if x in table:
        return table[x]
    for lo, hi in zip(keys, keys[1:]):
        if lo <= x <= hi:
            span = hi - lo
            return table[lo] + (table[hi] - table[lo]) * (x - lo) / span
    return None


def ambient_factor_is_tabulated(max_temp_c, base_ambient_c, medium="air"):
    """Whether a tabulated ambient factor exists to check the closed form against.

    Only one tabulated set is held: 90 C XLPE on a 40 C air basis, which is the
    Australian part of AS/NZS 3008. On any other basis -- the NZ part at 30 C,
    IEC and BS 7671 at 30 C, the NEC -- the closed form stands alone, and it
    runs optimistic. Callers should say so rather than let it pass silently.
    """
    return bool(medium == "air" and max_temp_c == 90.0
                and base_ambient_c == 40.0)


def ambient_rating_factor(max_temp_c, ambient_c, base_ambient_c, medium="air"):
    """Rating factor for an ambient temperature other than the tabulated base.

    Cable rating is limited by the temperature rise available above ambient,
    and I^2 R losses scale with the square of current, so

        k = sqrt( (theta_max - theta_ambient) / (theta_max - theta_base) )

    This closed form reproduces the shape of the AS/NZS 3008 correction
    tables, but it runs *optimistic* against the tabulated values (up to about
    +6.5% at 60 C ambient) because it ignores the temperature dependence of
    conductor resistivity and of the thermal resistances. Optimistic factors
    undersize cable, so where a tabulated factor applies it is used, and the
    more conservative of the two is always returned.
    """
    if ambient_c >= max_temp_c:
        raise ValueError(
            f"ambient {ambient_c} C is at or above the conductor limit {max_temp_c} C"
        )
    headroom_new = max_temp_c - ambient_c
    headroom_base = max_temp_c - base_ambient_c
    analytic = math.sqrt(headroom_new / headroom_base)

    # The tabulated set applies only on its own basis: 90 C conductor, 40 C air.
    if ambient_factor_is_tabulated(max_temp_c, base_ambient_c, medium):
        tabulated = _interpolate(AMBIENT_FACTORS_XLPE90_AIR40, ambient_c)
        if tabulated is not None:
            return min(analytic, tabulated)
    return analytic


# Grouping factors are empirically derived in the standard and have no closed
# form. These are the values carried in the repo cable catalogue (single layer,
# touching, on a perforated tray or ladder in air).
GROUPING_FACTORS = tables.LazyMapping(
    lambda: {int(k): v for k, v in
             _numeric_data("grouping_rating_factors").items()})


def grouping_rating_factor(n_circuits):
    """Rating factor for `n_circuits` grouped circuits."""
    if n_circuits < 1:
        raise ValueError("n_circuits must be >= 1")
    if n_circuits in GROUPING_FACTORS:
        return GROUPING_FACTORS[n_circuits]
    # Beyond the tabulated range the factor flattens out; hold the last value.
    return GROUPING_FACTORS[max(GROUPING_FACTORS)]


# ---------------------------------------------------------------------------
# Operating temperature and resistance
# ---------------------------------------------------------------------------

def operating_temperature(ambient_c, max_temp_c, current_a, rated_current_a):
    """Estimated steady-state conductor temperature at partial load.

        theta_op = theta_ambient + (theta_max - theta_ambient) * (I / I_rated)^2

    Losses scale with I^2, so temperature rise above ambient scales with the
    square of the load ratio. AS/NZS 3008 clause 4.4.
    """
    if rated_current_a <= 0:
        raise ValueError("rated_current_a must be positive")
    ratio = current_a / rated_current_a
    return ambient_c + (max_temp_c - ambient_c) * ratio ** 2


#: Clause 4.4's banding list. NOT every table carries every one of these, so it
#: is a target set to intersect with the table in use, never a lookup key on its
#: own. See round_to_temp_column().
CLAUSE_4_4_BANDS = (45.0, 60.0, 75.0, 80.0, 90.0, 110.0)


def round_to_temp_column(temp_c, available=None):
    """Round an operating temperature to the NEAREST tabulated column.

    AS/NZS 3008.1.1:2025 Clause 4.4: the calculated operating temperature "is
    then raised to the nearest temperature 45, 60, 75, 80, 90 or 110 C" for use
    with the voltage drop tables, and the same value is used for resistance.

    The clause wording is ambiguous between "raised to" and "to the nearest".
    Round-to-nearest is used because it is the only one of the three readings
    that reproduces the observed gap against an independent calculator, and it
    fits both published worked examples (which happen to round downward, so they
    do not separate nearest from down on their own). Recorded as OI-5.3 in
    spec-exchange/ANS-001.

    R-VD-11: the candidate set is the INTERSECTION of Clause 4.4's list with the
    columns the table in use actually carries. Pass `available` -- the table's
    own temperatures -- whenever it is known. Without it the full Clause 4.4 list
    is used, which is right only for tables carrying all six.

    Why it matters: 80 C exists on only four of the eighteen Vc tables and two of
    the six resistance tables, and on no multicore table at all. A multicore
    cable at 82 C bands to 75 C, not 80 and not 90, because the candidate set is
    {45, 60, 75, 90, 110} and |82-75| = 7 beats |82-90| = 8. Banding it to 90
    would be 5.9 % high on copper resistance; banding to 80 would name a column
    that does not exist.

    Ties go to the higher temperature. Below the lowest candidate it clamps --
    Clause 4.4 omits the 25 and 30 C columns deliberately, as those are for a
    conductor temperature known by other means rather than banding targets.
    Above the highest it clamps too, but that state is a capacity failure to be
    caught in M4, not a lookup problem.

    Confirmed by the standard's own three worked examples: A.6(a) 60.4 -> 60,
    A.6(b) 45.3 -> 45, and A.10.3 54 -> 60. A.6 excludes raise-up and A.10.3
    excludes round-down, so only round-to-nearest reproduces all three.

    OI-6.1 DECIDED, 8 September 2026 by Andrew: follow the standard. No
    conservative departure. R-VD-11 is non-conservative roughly half the time --
    82 C on a multicore table bands DOWN to 75 C -- and a variant that always
    banded upward was available and defensible. It was not taken. The standard's
    own convention governs, and a departure would have to be declared explicitly
    rather than reached by preference.

    This previously rounded UP unconditionally against a fixed global set, which
    both pushed a 95 C conductor onto the 110 C column and ignored the table.
    """
    candidates = sorted(set(CLAUSE_4_4_BANDS) & set(available)) if available \
        else list(CLAUSE_4_4_BANDS)
    if not candidates:
        raise ValueError(
            f"no Clause 4.4 band is available on this table; it carries "
            f"{sorted(available)} and Clause 4.4 names {list(CLAUSE_4_4_BANDS)}")
    # ties to the higher temperature: negate the value in the sort key
    return min(candidates, key=lambda col: (abs(col - temp_c), -col))


def resistance_at_temp(r_20_ohm_km, conductor, temp_c):
    """Scale a 20 C conductor resistance to `temp_c`.

        R_theta = R_20 * (1 + alpha * (theta - 20))
    """
    return r_20_ohm_km * (1.0 + conductor.alpha * (temp_c - 20.0))


# AC/DC resistance ratio at 50 Hz.
#
# VERIFIED. Previously derived from a manufacturer catalogue, and
# EXTRACTED-TABLES.md recorded an unresolved "1.252 vs 1.120 at 630 mm2"
# disagreement. AS/NZS 3008.1.1:2025 Tables 4.5 and 4.6 tabulate R_ac and R_dc
# directly, and their ratio at 90 C copper is 1.197 at 630 mm2 -- neither of the
# two figures previously in dispute. The ratio is now computed from the printed
# tables rather than assumed.
#
# Prefer resistance_ac_ohm_km(): it reads R_ac straight from the standard, so no
# ratio needs applying at all. ac_dc_ratio() remains for the case where only a
# DC resistance is in hand.
AC_DC_RATIO = tables.LazyMapping(
    lambda: _numeric_data("ac_dc_resistance_ratio"))


def ac_dc_ratio(area_mm2, temp_c=90.0, conductor="Copper",
                construction="single_core"):
    """AC/DC resistance ratio at 50 Hz, from AS/NZS 3008 Tables 4.5 and 4.6."""
    return as3008_2025.ac_dc_ratio(area_mm2, temp_c, conductor, construction)


def resistance_ac_ohm_km(area_mm2, temp_c, conductor="Copper",
                         construction="single_core"):
    """a.c. resistance at temperature, read from AS/NZS 3008 Tables 4.5 to 4.13.

    Skin and proximity effect are already in the tabulated value, so nothing
    further is applied on top of it.
    """
    return as3008_2025.resistance_ohm_km(area_mm2, temp_c, conductor,
                                         construction, "ac")


def reactance_ohm_km(area_mm2, **kw):
    """Reactance from AS/NZS 3008 Tables 4.1 to 4.4. See as3008_2025."""
    return as3008_2025.reactance_ohm_km(area_mm2, **kw)


# Retained so existing call sites keep working; the printed tables now cover
# every size, so no size threshold triggers a manual review any more.
LARGE_CONDUCTOR_REVIEW_MM2 = float("inf")


# ---------------------------------------------------------------------------
# Voltage drop
# ---------------------------------------------------------------------------

def cable_impedance(r_ohm_km, x_ohm_km, power_factor=None):
    """Effective impedance used for voltage drop, in ohm/km.

    With a known load power factor the in-phase projection is used:
        Zc = R cos(phi) + X sin(phi)
    Otherwise the worst case magnitude is used:
        Zc = sqrt(R^2 + X^2)
    """
    if power_factor is None:
        return math.hypot(r_ohm_km, x_ohm_km)
    if not 0.0 < power_factor <= 1.0:
        raise ValueError("power_factor must be in (0, 1]")
    sin_phi = math.sqrt(max(0.0, 1.0 - power_factor ** 2))
    return r_ohm_km * power_factor + x_ohm_km * sin_phi


def voltage_drop(phase_mode, current_a, length_m, z_ohm_km, parallel=1,
                 balanced_mains=False):
    """Voltage drop in volts over `length_m` of cable.

        Vd = factor * I * L * Zc / 1000 / parallel

    Parallel runs share the current, which divides the effective impedance.
    """
    table = VD_FACTOR_BALANCED if balanced_mains else VD_FACTOR
    if phase_mode not in table:
        raise ValueError(f"unknown phase_mode {phase_mode!r}")
    factor = table[phase_mode]
    return factor * current_a * length_m * z_ohm_km / 1000.0 / parallel


# ---------------------------------------------------------------------------
# Short-circuit withstand
# ---------------------------------------------------------------------------

def k_constant(conductor, initial_temp_c, final_temp_c):
    """Adiabatic short-circuit constant K (A.s^0.5/mm^2).

    Derived from the adiabatic heat balance rather than read from Table 52
    (2017) / Table 5.1 (2025):

        K = sqrt( Qc * (beta + 20) / rho20 * ln( (beta + theta_f)/(beta + theta_i) ) )

    Validated against published values -- see README.
    """
    if final_temp_c <= initial_temp_c:
        raise ValueError("final temperature must exceed initial temperature")
    coeff = conductor.Qc * (conductor.beta + 20.0) / conductor.rho20
    ratio = (conductor.beta + final_temp_c) / (conductor.beta + initial_temp_c)
    return math.sqrt(coeff * math.log(ratio))


def min_area_for_fault(fault_current_a, clearing_time_s, k):
    """Minimum conductor area (mm^2) to survive a fault, from I^2 t = K^2 S^2.

        S_min = I * sqrt(t) / K
    """
    if clearing_time_s < 0:
        raise ValueError("clearing_time_s must be >= 0")
    return fault_current_a * math.sqrt(clearing_time_s) / k


def prospective_fault_current(phase_voltage_v, source_impedance_ohm, cable_impedance_ohm):
    """Symmetrical fault current at the far end of the cable (amperes)."""
    total = source_impedance_ohm + cable_impedance_ohm
    if total <= 0:
        raise ValueError("total impedance must be positive")
    return phase_voltage_v / total


# ---------------------------------------------------------------------------
# Earth fault loop impedance
# ---------------------------------------------------------------------------

# MCB instantaneous trip multiples of rated current (upper limit of the band).
MCB_TRIP_MULTIPLE = {"B": 5.0, "C": 10.0, "D": 20.0}


def mcb_trip_current(curve, rating_a):
    """Minimum current guaranteeing instantaneous MCB operation."""
    curve = str(curve).upper()
    if curve not in MCB_TRIP_MULTIPLE:
        raise ValueError(f"MCB curve must be one of {sorted(MCB_TRIP_MULTIPLE)}")
    return MCB_TRIP_MULTIPLE[curve] * rating_a


def max_length_estimated(phase_voltage_v, trip_current_a, zp_ohm_km, ze_ohm_km):
    """Maximum route length by the estimated-impedance method (MCB only).

        L_max = 0.8 * V_phase * 1000 / (I_min * (Zp + Ze))

    The 0.8 factor allows for source impedance upstream of the cable.
    """
    denom = trip_current_a * (zp_ohm_km + ze_ohm_km)
    if denom <= 0:
        raise ValueError("trip current and impedances must be positive")
    return 0.8 * phase_voltage_v * 1000.0 / denom


def max_length_calculated(phase_voltage_v, trip_current_a, source_impedance_ohm,
                          zp_ohm_km, ze_ohm_km):
    """Maximum route length by the calculated-impedance method.

        Z_max = V_phase / I_min
        L_max = (Z_max - Z_source) * 1000 / (Zp + Ze)
    """
    z_max = phase_voltage_v / trip_current_a
    denom = zp_ohm_km + ze_ohm_km
    if denom <= 0:
        raise ValueError("impedances must be positive")
    return (z_max - source_impedance_ohm) * 1000.0 / denom


# ---------------------------------------------------------------------------
# Minimum conductor size (AS/NZS 3000 Table 3.3)
# ---------------------------------------------------------------------------

MIN_CONDUCTOR_SIZE = tables.LazyMapping(lambda: {
    k: v["area_mm2"]
    for k, v in TABLES["min_conductor_size_as3000_table_3_3"]["data"].items()
})


def min_conductor_area(circuit_use="other_circuits"):
    """Absolute minimum conductor area (mm^2) per AS/NZS 3000 Table 3.3.

    A floor independent of current and voltage drop. Valid keys are those of
    MIN_CONDUCTOR_SIZE, e.g. "socket_outlets", "other_circuits",
    "signal_relay_control", "flexible", "aerial_copper".
    """
    if circuit_use not in MIN_CONDUCTOR_SIZE:
        raise ValueError(
            f"circuit_use must be one of {sorted(MIN_CONDUCTOR_SIZE)}")
    return MIN_CONDUCTOR_SIZE[circuit_use]


# ---------------------------------------------------------------------------
# Voltage drop limits (AS/NZS 3000 clause 3.6.2)
# ---------------------------------------------------------------------------

# Three published figures, released in the public half, so these stay plain
# module constants and are available without the licensed data.
_VD = PUBLIC_TABLES["voltage_drop_limits_as3000_clause_3_6_2"]["data"]
VD_LIMIT_STANDARD_PCT = _VD["standard_supply_pct"]
VD_LIMIT_DEDICATED_SUBSTATION_PCT = _VD["dedicated_onsite_substation_pct"]
VD_LIMIT_STANDALONE_TOTAL_PCT = _VD["standalone_system_total_pct"]


def voltage_drop_limit_pct(dedicated_onsite_substation=False):
    """Permissible voltage drop, in percent of nominal supply voltage.

    5% from the point of supply to any point in the installation, rising to 7%
    where the point of supply is the low voltage terminals of a substation on
    the premises and dedicated to the installation (clause 3.6.2 Exception 3).
    """
    return (VD_LIMIT_DEDICATED_SUBSTATION_PCT if dedicated_onsite_substation
            else VD_LIMIT_STANDARD_PCT)


# ---------------------------------------------------------------------------
# Conductor colours (AS/NZS 3000 Table 3.4)
# ---------------------------------------------------------------------------

CONDUCTOR_COLOURS = tables.LazyMapping(
    lambda: TABLES["conductor_colours_as3000_table_3_4"]["data"])


def conductor_colour(function, phase_mode="3-phase"):
    """Recommended insulation colour for a conductor function.

    `function` is one of CONDUCTOR_COLOURS. For actives the recommended colours
    depend on whether the circuit is single or multiphase.
    """
    if function not in CONDUCTOR_COLOURS:
        raise ValueError(f"function must be one of {sorted(CONDUCTOR_COLOURS)}")
    row = CONDUCTOR_COLOURS[function]
    if function == "active":
        key = ("recommended_single_phase" if phase_mode == "1-phase"
               else "recommended_multiphase")
        return row[key][0]
    return row["colours"][0]


# ---------------------------------------------------------------------------
# Neutral conductor sizing (AS/NZS 3000 clause 3.5.2)
# ---------------------------------------------------------------------------

# A harmonic load at or above this share of the total load on any single phase
# is "substantial" and triggers the harmonic neutral rule (clause 3.5.2(b)(i)
# NOTE 1).
SUBSTANTIAL_HARMONIC_PCT = 40.0


def neutral_design_current(phase_mode, phase_current_a, out_of_balance_pct=100.0,
                           harmonic_content_pct=0.0):
    """Design current for the neutral conductor, in amperes.

    Per AS/NZS 3000 clause 3.5.2:

    - Single-phase two-wire: the neutral carries the full active current.
    - Multiphase: the neutral carries the maximum out-of-balance current, plus
      100% of the highest third-and-higher-order harmonic current on any phase
      where the harmonic load is substantial.

    `out_of_balance_pct` and `harmonic_content_pct` are percentages of the phase
    current. Third harmonics are additive to the fundamental in the neutral, so
    the neutral current can exceed the phase current.
    """
    if phase_mode in ("1-phase", "DC"):
        return phase_current_a
    out_of_balance = phase_current_a * out_of_balance_pct / 100.0
    if harmonic_content_pct >= SUBSTANTIAL_HARMONIC_PCT:
        return out_of_balance + phase_current_a * harmonic_content_pct / 100.0
    return out_of_balance


def is_substantial_harmonic(harmonic_content_pct):
    """True if the harmonic load triggers clause 3.5.2(b)(i)."""
    return harmonic_content_pct >= SUBSTANTIAL_HARMONIC_PCT


# ---------------------------------------------------------------------------
# Conduit sizing (AS/NZS 3000:2018 Tables C10, C11, C12)
# ---------------------------------------------------------------------------

CONDUIT_TABLES = {
    "single_core": "conduit_fill_as3000_table_c10",
    "2c_earth": "conduit_fill_as3000_table_c11",
    "4c_earth": "conduit_fill_as3000_table_c12",
}


def _fill_count(value):
    """Interpret a conduit fill cell. '>100' is treated as 100 (conservative)."""
    if isinstance(value, str):
        return 100 if value.startswith(">") else float(value)
    return float(value)


def conduit_families(cable_form="single_core"):
    """Cable insulation families available for a conduit table."""
    if cable_form not in CONDUIT_TABLES:
        raise ValueError(f"cable_form must be one of {sorted(CONDUIT_TABLES)}")
    return sorted(TABLES[CONDUIT_TABLES[cable_form]]["data"])


def min_conduit_size(area_mm2, n_cables, cable_form="single_core",
                     family="XLPE/PVC", conduit_type="heavy_duty_rigid_upvc",
                     region="AUS"):
    """Smallest conduit nominal size (mm) that takes `n_cables` of `area_mm2`.

    Tables C10 (single-core sheathed), C11 (two-core and earth) and C12
    (four-core and earth) of AS/NZS 3000:2018. Returns None if no tabulated
    conduit in that type is large enough.

    Only the heavy duty rigid UPVC and Corflo columns were captured; the medium
    duty columns were cut off in the source. `region` selects between the AUS and
    NZ variants of the 80 and 100 mm columns.
    """
    if cable_form not in CONDUIT_TABLES:
        raise ValueError(f"cable_form must be one of {sorted(CONDUIT_TABLES)}")
    block = TABLES[CONDUIT_TABLES[cable_form]]
    if family not in block["data"]:
        raise ValueError(
            f"family must be one of {sorted(block['data'])} for {cable_form}")
    rows = block["data"][family]
    key = _nearest_size_key(rows, area_mm2)
    if key is None:
        return None
    row = rows[key]
    if conduit_type not in row:
        raise ValueError(f"conduit_type must be one of {sorted(row)}")
    columns = block["conduit_columns"][conduit_type]
    best = None
    for col, cell in zip(columns, row[conduit_type]):
        # Skip the variant that does not apply to this region.
        if col.endswith("_NZ") and region != "NZ":
            continue
        if col.endswith("_AUS") and region != "AUS":
            continue
        if _fill_count(cell) >= n_cables:
            size = float(col.split("_")[0])
            if best is None or size < best:
                best = size
    return best


def _nearest_size_key(rows, area_mm2):
    """Exact size key in a conduit table, or the next larger tabulated size."""
    area = float(area_mm2)
    keys = sorted(rows, key=float)
    for k in keys:
        if float(k) >= area:
            return k
    return None


# ---------------------------------------------------------------------------
# Aluminium earthing conductors (AS/NZS 3000:2018 clause 5.3.2.1.2)
# ---------------------------------------------------------------------------

_AL_EARTH = tables.LazyMapping(
    lambda: TABLES["aluminium_earthing_as3000_clause_5_3_2_1_2"]["data"])


def check_aluminium_earth(area_mm2, is_main_earthing=False, underground_or_damp=False,
                          designed_for_damp=False):
    """Compliance of an aluminium earthing conductor with clause 5.3.2.1.2.

    Returns a list of violation strings; empty means compliant.
    """
    problems = []
    area = float(area_mm2)
    if area <= _AL_EARTH["solid_required_at_or_below_mm2"]:
        problems.append(
            f"{area:g} mm2 aluminium earth must be a solid conductor "
            f"(clause 5.3.2.1.2(a), applies at or below "
            f"{_AL_EARTH['solid_required_at_or_below_mm2']:g} mm2)")
    if is_main_earthing and area < _AL_EARTH["min_main_earthing_conductor_mm2"]:
        problems.append(
            f"a main earthing conductor in aluminium must be at least "
            f"{_AL_EARTH['min_main_earthing_conductor_mm2']:g} mm2, not "
            f"{area:g} mm2 (clause 5.3.2.1.2(b))")
    if underground_or_damp and not designed_for_damp:
        problems.append(
            "aluminium earthing conductors must not be installed underground or "
            "in damp situations unless designed and suitable for such use "
            "(clause 5.3.2.1.2(e) and its Exception)")
    return problems


# ---------------------------------------------------------------------------
# Earth conductor sizing
# ---------------------------------------------------------------------------

# AS/NZS 3000 Table 5.1 -- minimum earthing conductor size (mm^2) for a given
# active conductor size (mm^2). Loaded from reference_tables.json; check
# verification_report() for provenance before issuing a design.
MIN_EARTH_SIZE = tables.LazySequence(
    lambda: sorted(_numeric_data("earth_sizes_as3000_table_5_1").items()))

# Above 630 mm^2 combined active area the earth is a proportion of the actives.
# `large_conductor_fraction` rides with the private body: it is a rule read off
# the standard, and whether that is publishable is a call for a human, not one
# to make silently here.
_EARTH_LARGE = tables.LazyMapping(
    lambda: TABLES["earth_sizes_as3000_table_5_1"]["large_conductor_fraction"])
LARGE_EARTH_FRACTION = tables.LazyMapping(
    lambda: {"Copper": _EARTH_LARGE["Copper"],
             "Aluminium": _EARTH_LARGE["Aluminium"]})


def large_earth_threshold_mm2():
    """Area above which the earth is a fraction of the active, not tabulated."""
    return float(_EARTH_LARGE["applies_above_mm2"])


def min_earth_area(active_area_mm2, n_active=1, n_earth=1, conductor_name="Copper"):
    """Minimum earth conductor area (mm^2) for the given active configuration.

    For parallel single-core runs the actives are combined and shared across
    the available earth cores:

        S_active_combined = S_active * m / n
    """
    combined = active_area_mm2 * n_active / n_earth
    if combined > large_earth_threshold_mm2():
        fraction = LARGE_EARTH_FRACTION[conductor_name]
        return combined * fraction
    for size, earth in MIN_EARTH_SIZE:
        if combined <= size:
            return earth
    return combined * LARGE_EARTH_FRACTION[conductor_name]
