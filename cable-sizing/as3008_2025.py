"""AS/NZS 3008.1.1:2025 Section 4 and 5 tables, read from the printed standard.

Every value here was transcribed from the licensed copy on 2026-09-04 and is
marked verified in its source file. This module supersedes three things the
engine previously guessed:

  * reactance          -- reference_tables.json carried "NOT POPULATED -- engine
                          falls back to a single nominal value" (0.08 ohm/km).
                          Tables 4.1 to 4.4 now give it per construction,
                          formation and insulation, with the spacing correction.
  * a.c. resistance    -- was a ratio derived from a manufacturer catalogue.
                          Tables 4.5 to 4.13 tabulate R_ac directly against
                          conductor temperature.
  * short-circuit      -- as3008.SC_LIMIT_BY_FAMILY assigned theta_f by family
    limit temperature     with no size dependence. Table 5.2 makes thermoplastic
                          160 C at or below 300 mm2 and 140 C above it, and puts
                          R-S-150 at 350 C rather than 250 C.

Data files:
    as3008_impedance_tables.json   Tables 4.1-4.13
    as3008_vc_tables.json          Tables 4.14-4.31
    as3008_short_circuit.json      Table 5.2
"""

import math

import tables
from tables import LazyMapping

# Loaded on first use, not at import. A checkout without the licensed data
# imports cleanly and fails only where a table is actually needed. See
# tables.py for why.
IMPEDANCE = LazyMapping(lambda: tables.load("impedance")["tables"])
VC = LazyMapping(lambda: tables.load("vc")["tables"])
SHORT_CIRCUIT = LazyMapping(lambda: tables.load("short_circuit")["tables"])

# Spacing corrections, NOTE 1 to Tables 4.1 and 4.2. Add to the tabulated
# reactance where single-core cables are spaced apart; D is the cable diameter.
SPACING_CF_OHM_KM = LazyMapping(
    lambda: IMPEDANCE["4.1"]["single_core"]["spacing_correction_ohm_km"])

# NOTE 3 to the same tables: below this size a spacing correction is not
# required for separations up to 5D, the impact on Vc being under 2.5 %.
SPACING_CF_EXEMPT_BELOW_MM2 = 25.0

# The insulation families the engine uses, mapped to the column headings the
# reactance tables print. Elastomer and PVC are identical from 4 mm2 up.
_INSULATION_COLUMN = {
    "thermoplastic": "PVC",
    "elastomeric": "Elastomer",
    "xlpe": "XLPE",
    "other": "PVC",
}


def _nearest(table, area_mm2):
    """Value for `area_mm2`, falling back to the nearest tabulated size."""
    key = _fmt(area_mm2)
    if key in table:
        return table[key]
    sizes = sorted(table, key=float)
    if not sizes:
        return None
    return table[min(sizes, key=lambda s: abs(float(s) - float(area_mm2)))]


def _fmt(area_mm2):
    """Render an area the way the JSON keys it: 1.5 not 1.50, 25 not 25.0."""
    a = float(area_mm2)
    return str(int(a)) if a == int(a) else str(a)


# ---------------------------------------------------------------------------
# Reactance -- Tables 4.1 to 4.4
# ---------------------------------------------------------------------------

#: Reactance uplift constant, Table 4.1(A)/4.2(A) NOTE 1.
#: dX = K_SPACING * ln(1 + s/D), where s is the CLEAR separation between cable
#: surfaces and D the cable diameter. K = 2*pi*f * 2e-4 = 0.06283 ohm/km at 50 Hz.
#: The three printed constants are three points of this one function: at 0.5D,
#: 1D and 2D it gives 0.0255, 0.0436 and 0.0690 against the printed 0.0254,
#: 0.0435 and 0.0690.
#:
#: It is a pure spacing RATIO and is independent of formation, because for a
#: fixed formation the geometric mean distance scales linearly with centre
#: spacing. The base column follows the formation actually installed; the uplift
#: does not. See ANS-002 A3.1 and R-FRM-7 revised.
K_SPACING_OHM_KM = 0.06283


def spacing_uplift_ohm_km(separation_ratio):
    """Reactance uplift for single-core cables spaced apart, NOTE 1.

    `separation_ratio` is s/D: the clear gap between cable surfaces as a
    multiple of the cable diameter. For cables in single-way ducts D remains the
    CABLE diameter, not the duct diameter (NOTE 2).
    """
    if separation_ratio < 0:
        raise ValueError("separation_ratio must be >= 0")
    return K_SPACING_OHM_KM * math.log(1.0 + separation_ratio)


def reactance_ohm_km(area_mm2, construction="single_core", formation="trefoil",
                     insulation_family="xlpe", spacing=None, voltage="750V",
                     separation_ratio=None):
    """Reactance in ohm/km from Tables 4.1 to 4.4.

    construction  single_core | multicore | multicore_shaped | flexible_single
                  | flexible_multi | mims_single | mims_multi | aerial
    formation     trefoil | flat_touching  (single-core and aerial only)
    spacing       None for touching, or one of "0.5D", "1D", "2D" to add the
                  NOTE 1 correction. Ignored below 25 mm2 per NOTE 3.

    Returns (x_ohm_km, source_table, notes).
    """
    ins = _INSULATION_COLUMN.get(insulation_family, "XLPE")
    notes = []
    x = None
    table = None

    if construction == "single_core":
        table = "4.1(A)"
        x = _nearest(IMPEDANCE["4.1"]["single_core"]["data"][formation][ins], area_mm2)
    elif construction in ("multicore", "multicore_shaped"):
        table = "4.1(B)"
        geom = "shaped" if construction == "multicore_shaped" else "circular"
        block = IMPEDANCE["4.1"]["multicore"]["data"][geom]
        if ins not in block:                      # shaped has no Elastomer column
            notes.append(f"Table 4.1(B) has no shaped {ins} column; used PVC")
            ins = "PVC"
        x = _nearest(block[ins], area_mm2)
    elif construction == "flexible_single":
        table = "4.2(A)"
        x = _nearest(IMPEDANCE["4.2"]["single_core"]["data"][formation][ins], area_mm2)
    elif construction == "flexible_multi":
        table = "4.2(B)"
        x = _nearest(IMPEDANCE["4.2"]["multicore"]["data"]["circular"][ins], area_mm2)
    elif construction in ("mims_single", "mims_multi"):
        table = "4.3"
        col = ("single_core_trefoil" if construction == "mims_single" else "multicore")
        block = IMPEDANCE["4.3"]["data"][voltage][col]
        x = _nearest(block, area_mm2)
        if x is not None and _fmt(area_mm2) not in block:
            notes.append(f"Table 4.3 does not tabulate {area_mm2:g} mm2 for "
                         f"{voltage} {col}; nearest size used")
    elif construction == "aerial":
        table = "4.4"
        col = ("three_cables_flat" if formation == "flat_touching"
               else "single_phase_and_trefoil")
        x = _nearest(IMPEDANCE["4.4"]["data"][col], area_mm2)
        notes.append("Table 4.4 values assume a spacing of 0.4 m")
    else:
        raise ValueError(f"unknown construction {construction!r}")

    if x is None:
        return None, table, [f"no reactance tabulated for {area_mm2:g} mm2 "
                             f"{construction}"]

    # Continuous form, R-FRM-7 revised: any s/D, not just the three printed
    # points. The base column above already followed the stated formation.
    if separation_ratio is not None:
        if float(area_mm2) < SPACING_CF_EXEMPT_BELOW_MM2:
            notes.append(f"spacing correction not required below "
                         f"{SPACING_CF_EXEMPT_BELOW_MM2:g} mm2 up to 5D (NOTE 3)")
        else:
            up = spacing_uplift_ohm_km(separation_ratio)
            x += up
            notes.append(f"{separation_ratio:g}D separation: +{up:.4f} ohm/km "
                         f"(NOTE 1, K*ln(1+s/D))")
        return x, table, notes

    if spacing:
        if float(area_mm2) < SPACING_CF_EXEMPT_BELOW_MM2:
            notes.append(f"spacing correction not required below "
                         f"{SPACING_CF_EXEMPT_BELOW_MM2:g} mm2 up to 5D (NOTE 3)")
        else:
            cf = SPACING_CF_OHM_KM.get(spacing)
            if cf is None:
                raise ValueError(f"spacing must be one of "
                                 f"{sorted(k for k in SPACING_CF_OHM_KM if not k.startswith('_'))}")
            x += cf
            notes.append(f"{spacing} spacing correction +{cf} ohm/km added (NOTE 1)")
    return x, table, notes


# ---------------------------------------------------------------------------
# Resistance -- Tables 4.5 to 4.13
# ---------------------------------------------------------------------------

_R_TABLE = {
    ("single_core", "ac"): ("4.5", None),
    ("single_core", "dc"): ("4.6", None),
    ("multicore", "ac"): ("4.7", None),
    ("multicore", "dc"): ("4.8", None),
    ("multicore_shaped", "ac"): ("4.9", None),
    ("flexible_single", "ac"): ("4.10", "single_core"),
    ("flexible_multi", "ac"): ("4.10", "multicore"),
    ("flexible_single", "dc"): ("4.11", "single_core"),
    ("flexible_multi", "dc"): ("4.11", "multicore"),
    ("mims_single", "ac"): ("4.12", None),
    ("mims_multi", "ac"): ("4.12", None),
    ("aerial", "ac"): ("4.13", None),
}


def _interp_temp(block, temps, area_mm2, temp_c):
    """Linear interpolation across the tabulated conductor temperatures.

    Resistance is linear in temperature, so interpolating between columns is
    exact rather than an approximation.
    """
    key = _fmt(area_mm2)
    have = [t for t in temps if key in block[str(t)]]
    if not have:
        sizes = sorted({s for t in temps for s in block[str(t)]}, key=float)
        if not sizes:
            return None
        key = min(sizes, key=lambda s: abs(float(s) - float(area_mm2)))
        have = [t for t in temps if key in block[str(t)]]
    t = float(temp_c)
    if t <= have[0]:
        return block[str(have[0])][key]
    if t >= have[-1]:
        return block[str(have[-1])][key]
    for lo, hi in zip(have, have[1:]):
        if lo <= t <= hi:
            a, b = block[str(lo)][key], block[str(hi)][key]
            return a + (b - a) * (t - lo) / (hi - lo)
    return None


def resistance_ohm_km(area_mm2, temp_c, conductor="Copper",
                      construction="single_core", current="ac"):
    """Conductor resistance in ohm/km at `temp_c`, from Tables 4.5 to 4.13.

    Returns (r_ohm_km, source_table). Unlike the previous approach this is the
    standard's own a.c. resistance -- skin and proximity effect are already in
    it, so no AC/DC ratio is applied on top.
    """
    entry = _R_TABLE.get((construction, current))
    if entry is None:
        entry = _R_TABLE.get((construction, "ac"))
    if entry is None:
        raise ValueError(f"no resistance table for {construction}/{current}")
    tid, sub = entry
    tb = IMPEDANCE[tid]
    block = tb["data"]
    if sub is not None:
        block = block[sub]
    elif conductor in block:
        block = block[conductor]
    elif "Copper" in block:
        block = block["Copper"]
    return _interp_temp(block, tb["temperatures_c"], area_mm2, temp_c), tid


def available_temperatures(construction="single_core", current="ac"):
    """The conductor-temperature columns the resistance table actually carries.

    R-VD-11 needs this: Clause 4.4's band list is a target set to intersect with
    the table in use, not a lookup key. 80 C exists on Tables 4.5 and 4.6 only,
    so no multicore or flexible lookup can land on it.
    """
    entry = _R_TABLE.get((construction, current)) or _R_TABLE.get((construction, "ac"))
    if entry is None:
        return list(CLAUSE_4_4_FALLBACK)
    return list(IMPEDANCE[entry[0]]["temperatures_c"])


#: Used only when a construction resolves to no table at all.
CLAUSE_4_4_FALLBACK = (45.0, 60.0, 75.0, 80.0, 90.0, 110.0)


def ac_dc_ratio(area_mm2, temp_c=90.0, conductor="Copper",
                construction="single_core"):
    """R_ac / R_dc at `temp_c`, computed from the standard's own tables.

    Replaces the ratio previously derived from a manufacturer catalogue. At
    90 C copper this runs 1.00 to about 1.20 at 630 mm2 -- neither the 1.252
    nor the 1.120 that EXTRACTED-TABLES.md recorded as an open disagreement.
    """
    dc_construction = ("multicore" if construction == "multicore_shaped"
                       else construction)
    r_ac, _ = resistance_ohm_km(area_mm2, temp_c, conductor, construction, "ac")
    r_dc, _ = resistance_ohm_km(area_mm2, temp_c, conductor, dc_construction, "dc")
    if not r_ac or not r_dc:
        return 1.0
    return r_ac / r_dc


# ---------------------------------------------------------------------------
# Short-circuit limit temperature -- Table 5.2
# ---------------------------------------------------------------------------

_SC_BY_MATERIAL = LazyMapping(lambda: SHORT_CIRCUIT["5.2"]["by_material"])

# Table 5.2 prints "TP 90"; AS/NZS 3000 Table 3.2 designates the same material
# "TP-90". Accept either.
_SC_ALIASES = {"TP-90": "TP 90", "X-110": "X-HF-110"}

# Thermoplastic is the only group with a size dependence.
SC_SIZE_BREAK_MM2 = 300.0


def sc_limit_temp_c(insulation_code, area_mm2, family=None):
    """Permitted final conductor temperature under short circuit, Table 5.2.

    Thermoplastic insulation is limited to 160 C at or below 300 mm2 and
    140 C above it. Every other group is a single value, and R-S-150 and
    Type 150 fibrous are 350 C, not the 250 C the engine assumed by family.
    """
    code = _SC_ALIASES.get(insulation_code, insulation_code)
    limit = _SC_BY_MATERIAL.get(code)
    if limit is None:
        # Not named in Table 5.2 -- MIMS is the case in practice. Fall back to
        # the family assumption and say so at the call site.
        return None
    if isinstance(limit, dict):
        return limit["<=300"] if float(area_mm2) <= SC_SIZE_BREAK_MM2 else limit[">300"]
    return float(limit)


def sc_limit_is_tabulated(insulation_code):
    """Whether Table 5.2 names this insulation at all."""
    return _SC_ALIASES.get(insulation_code, insulation_code) in _SC_BY_MATERIAL


# ---------------------------------------------------------------------------
# Voltage drop -- Tables 4.14 to 4.31, for cross-checking only
# ---------------------------------------------------------------------------

class SpacedHasNoTabulatedVc(ValueError):
    """R-FRM-6/R-FRM-9. `air_spaced` has no tabulated voltage drop at all.

    Table 4.14 NOTE 2: "Vc values are only applied for single-core cables
    installed strictly in touching formation. Where single-core cables are
    spaced apart or in single-way ducts, the Vc is calculated using the
    impedance of the cable (see Clause 4.3) using the revised value of
    reactance detailed in notes to Tables 4.1 and 4.2."

    What is excluded is the tabulated mV/A.m ROUTE, not formation. ANS-002 A3.3
    corrected ANS-001 on this: a separated equilateral group is a real
    installation the standard contemplates -- Clause A.1.2 Method C is trefoil
    groups of single-way underground ducts, and Table 4.1(A) NOTE 2 exists to
    serve it. So `air_spaced` still requires a stated formation; it just has no
    tabulated Vc to look up.
    """


#: Arrangements with no tabulated Vc. R-FRM-9.
NO_TABULATED_VC = frozenset({"air_spaced"})


def vc_mv_per_a_m(table, area_mm2, temp_c, column="max", group=None,
                  arrangement=None):
    """Tabulated Vc in mV/A.m, for checking the impedance calculation against.

    The engine computes voltage drop from R and X; these tables are the
    standard's own answer to the same question and reproduce it to under 1 %.

    The "0.8 p.f." column is NOT a 0.8 p.f. value: it is the worst case over
    load power factors in [0.8, 1.0], which equals Max while the cable's own
    power factor stays at or above 0.8. See dame_cable.voltage_drop
    .mv_per_a_m_08_column and spec-exchange/ANS-001 R-VD-2.

    Raises SpacedHasNoTabulatedVc if `arrangement` is one the standard routes
    through Clause 4.3 instead.
    """
    if arrangement is not None and str(arrangement) in NO_TABULATED_VC:
        raise SpacedHasNoTabulatedVc(
            f"arrangement {arrangement!r} has no tabulated Vc: the cables are "
            f"separated, and Table {table} applies only to strictly touching "
            f"formation. Formation is still required -- the base column follows "
            f"the formation actually installed, trefoil or flat. Compute from "
            f"impedance per Clause 4.3, taking the reactance from the base "
            f"column for that formation plus the NOTE 1 spacing uplift "
            f"({', '.join(f'{k} +{v}' for k, v in sorted(SPACING_CF_OHM_KM.items()) if not k.startswith('_'))} ohm/km). "
            f"NOTE 3: no uplift is required below "
            f"{SPACING_CF_EXEMPT_BELOW_MM2:g} mm2 for separations up to 5D."
        )
    tb = VC[table]
    block = tb["data"].get(str(int(temp_c)) if float(temp_c) == int(temp_c)
                           else str(temp_c))
    if block is None:
        return None
    if group is not None:
        block = block.get(group, {})
    cell = _nearest(block, area_mm2)
    if cell is None:
        return None
    return cell[column] if isinstance(cell, dict) else cell


PF_08_CONSERVATIVE_BELOW_MM2 = 240.0
