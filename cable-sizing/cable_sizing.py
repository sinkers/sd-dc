"""
AS/NZS 3008 cable sizing engine.

Sizes a cable for a connection between two points in the data centre power
network -- a source (switchboard, PDU, transformer) and a load (PDU, rack,
motor, CDU). Runs the four AS/NZS 3008 checks in order and returns the
smallest catalogue size that passes all of them, with a full audit trail.

    1. Current-carrying capacity, after derating
    2. Voltage drop
    3. Short-circuit (adiabatic) withstand
    4. Earth fault loop impedance

Current ratings come from `../cables/cable_catalog.json` (Nexans Australia).
Calculation primitives live in `as3008.py`.

Usage:
    from cable_sizing import Source, Load, Installation, size_feeder

    result = size_feeder(
        Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2),
        Load("PDU-A1", kw=250, power_factor=0.95),
        route_length_m=85,
        install=Installation(method="touching", ambient_c=45, n_circuits=4),
    )
    print(result.summary())
"""

import json
import math
import os
from dataclasses import dataclass, field

import as3008
import as3008_2025
import tables
import iec60228
import standards

CATALOG_PATH = tables.path_for("nexans")

# Catalogue rating column for each installation method.
INSTALL_COLUMNS = {
    "spaced":    "i_3ph_spaced_a",     # single layer, spaced one diameter, in air
    "touching":  "i_3ph_touching_a",   # single layer, touching, on tray/ladder
    "conduit":   "i_3ph_conduit_a",    # enclosed in conduit
    "buried":    "i_3ph_buried_a",     # direct buried / buried conduit
}

# Which ambient medium each installation method sits in.
INSTALL_MEDIUM = {
    "spaced": "air", "touching": "air", "conduit": "air", "buried": "soil",
}


AS3008_RATINGS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                   "as3008_ratings.json")


def _merge_standard_families(catalog):
    """Add families whose ratings come from the standard, not a manufacturer.

    The repo catalogue is manufacturer data, and for at least one family it
    runs well above the standard's own table: the LFH single-core ratings sit
    13-25% above AS/NZS 3008.1.1 Table 3.14 column 5, which two independent
    third-party calculators agree on. The likely reason is loaded-core count --
    a manufacturer three-phase column against the standard's four-core column
    for three phases plus a loaded neutral -- and the effect is that the engine
    picks one size small for a 3-phase-plus-neutral circuit.

    So the standard's table is carried alongside as its own family. Ratings
    come from the standard; diameters and masses, which the standard does not
    tabulate, come from a real cable of the same construction.
    """
    try:
        with open(AS3008_RATINGS_PATH) as fh:
            doc = json.load(fh)
    except FileNotFoundError:
        return catalog
    for fid, fam in doc.get("families", {}).items():
        donor = catalog["cables"].get("LFH_SINGLE", {}).get("sizes", {})
        sizes = {}
        for size_key, rating in fam["ratings_a"].items():
            geom = donor.get(size_key)
            if geom is None:
                continue          # no geometry for this size, so skip it
            entry = {k: v for k, v in geom.items()
                     if not k.startswith("i_3ph_")}
            # Per-arrangement ratings. `air_touching` is Table 3.14 column 5,
            # real tabulated data; the rest are that column scaled by the
            # arrangement's ratio to it at 400 mm2, where all ten Table 3.14
            # values are known. ESTIMATION GRADE -- see
            # as3008_ratings.json ratings_by_arrangement_provenance.
            #
            # Before this, all four methods returned the touching rating, which
            # is up to 47 % optimistic for a cable in thermal insulation and
            # 34 % for one in a shared underground conduit.
            by_arr = fam.get("ratings_by_arrangement_a", {})
            for col, arr in (("i_3ph_touching_a", "air_touching"),
                             ("i_3ph_spaced_a", "air_spaced_from_surface"),
                             ("i_3ph_conduit_a", "enclosed_conduit_in_air"),
                             ("i_3ph_buried_a", "buried_direct")):
                entry[col] = by_arr.get(arr, {}).get(size_key, rating)
            sizes[size_key] = entry
        catalog["cables"][fid] = {
            "name": fam["name"], "voltage_kv": fam["voltage_kv"],
            "insulation": fam["insulation"], "sheath": "-",
            "conductor": fam["conductor"], "class": fam["class"],
            "max_temp_c": fam["max_temp_c"], "colour": fam["colour"],
            "rating_source": fam["rating_table"],
            "loaded_cores": fam["loaded_cores"],
            "sizes": sizes,
        }
    return catalog


def load_catalog(path=CATALOG_PATH):
    """Load the repo cable catalogue, plus any standards-sourced families."""
    with open(path) as fh:
        return _merge_standard_families(json.load(fh))


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------

@dataclass
class Source:
    """The upstream end of the connection -- a switchboard or distribution point.

    fault_level_ka   -- prospective three-phase fault level at the source
    clearing_time_s  -- protective device clearing time for that fault
    protection       -- optional ("MCB", curve, rating_a) for loop impedance check
    """
    name: str
    voltage_v: float = 415.0
    phase_mode: str = "3-phase"
    fault_level_ka: float = 25.0
    clearing_time_s: float = 0.2
    protection_type: str = None     # "MCB" or None
    mcb_curve: str = "C"
    mcb_rating_a: float = None

    @property
    def phase_voltage_v(self):
        """Phase-to-earth voltage, used for fault and loop calculations."""
        if self.phase_mode == "3-phase":
            return self.voltage_v / math.sqrt(3.0)
        return self.voltage_v

    @property
    def source_impedance_ohm(self):
        """Network impedance implied by the declared fault level."""
        return self.phase_voltage_v / (self.fault_level_ka * 1000.0)


@dataclass
class Load:
    """The downstream end of the connection. Give exactly one rating."""
    name: str
    kw: float = None
    kva: float = None
    amps: float = None
    hp: float = None
    power_factor: float = 0.9
    efficiency: float = 1.0
    max_voltage_drop_pct: float = None   # defaults from AS/NZS 3000 clause 3.6.2
    # Third-and-higher-order harmonic current as a percentage of phase current.
    # At or above 40% the harmonic load is "substantial" per clause 3.5.2(b)(i)
    # NOTE 1 and the neutral is sized for out-of-balance plus harmonics.
    # IT loads, VSDs and switch-mode supplies routinely exceed this.
    harmonic_content_pct: float = 0.0
    # Maximum out-of-balance current as a percentage of phase current.
    out_of_balance_pct: float = 100.0


@dataclass
class Installation:
    """How and where the cable is installed."""
    method: str = "touching"
    #: Cable formation: "trefoil" or "flat_touching". Independent of `method` --
    #: single-core cables are commonly laid in trefoil on a tray that is
    #: "unenclosed touching". Left None it is guessed and a warning is raised;
    #: the guess costs about 19 % on reactance. See _FORMATION_FALLBACK.
    formation: str = None
    ambient_c: float = None        # defaults to the standard's basis
    n_circuits: int = 1
    # There is deliberately no AU/NZ basis switch here. The reference ambient
    # belongs to the standard, and AS/NZS 3008 parts 1.1 and 1.2 have separate
    # rating tables, so switching the basis without switching the table
    # mis-references the ratings. Pick standard="AS3008NZ" instead.
    max_parallel: int = 4          # most parallel runs allowed per phase
    cable_type: str = "XLPE_SDI_CU"
    circuit_use: str = "other_circuits"          # AS/NZS 3000 Table 3.3 row
    dedicated_onsite_substation: bool = False    # clause 3.6.2 Exception 3 -> 7%
    # Which standard's rules apply. See standards.py: only AS/NZS carries a
    # rating table here, so the others need `tabulated_rating_a` supplied and
    # run in check mode rather than select mode.
    standard: str = standards.DEFAULT
    tabulated_rating_a: float = None
    vd_supply: str = "public"      # standards.Standard.vd_limits row
    vd_use: str = "other"          # "lighting" or "other"
    # Whether parallel runs of THIS circuit count as separate groups for the
    # grouping factor. They do, and the default says so.
    #
    # jCalc's AS/NZS 3008 calculator -- the tool this component was originally
    # reverse-engineered from -- states it outright in its own documentation:
    # the Number of Circuits parameter "includes parallel cables in this
    # circuit and cables from any other circuits included in the same
    # installation ... And the standard treats parallel cables as multiple
    # circuits." Captured in reference/jcalc-cable-sizing-as3008.txt.
    #
    # Physics agrees: parallel runs on a tray are separate bundles of loaded
    # cores warming each other. Set this False only where the runs are
    # genuinely separated enough not to interact, and say why.
    parallel_runs_grouped: bool = True

    def profile(self):
        return standards.get(self.standard)

    def method_spec(self):
        return standards.method(self.standard, self.method)

    def medium(self):
        return self.method_spec().medium

    def base_ambient_c(self):
        """The reference ambient the rating table is drawn up on."""
        std = self.profile()
        return std.air_c if self.medium() == "air" else std.soil_c

    def effective_ambient_c(self):
        return self.ambient_c if self.ambient_c is not None else self.base_ambient_c()


# ---------------------------------------------------------------------------
# Result
# ---------------------------------------------------------------------------

@dataclass
class Check:
    """One AS/NZS 3008 check on a candidate size."""
    name: str
    passed: bool
    detail: str
    margin_pct: float = None


@dataclass
class SizingResult:
    source_name: str
    load_name: str
    cable_type: str
    passed: bool
    design_current_a: float = 0.0
    active_area_mm2: float = None
    earth_area_mm2: float = None
    neutral_area_mm2: float = None
    neutral_current_a: float = None
    substantial_harmonics: bool = False
    voltage_drop_limit_pct: float = None
    parallel: int = 1
    derating_factor: float = 1.0
    ambient_factor: float = 1.0
    grouping_factor: float = 1.0
    required_capacity_a: float = 0.0
    derated_capacity_a: float = 0.0
    operating_temp_c: float = None
    voltage_drop_v: float = None
    voltage_drop_pct: float = None
    fault_current_a: float = None
    min_fault_area_mm2: float = None
    k_constant: float = None
    max_loop_length_m: float = None
    od_mm: float = None
    weight_kg_per_m: float = None
    bend_radius_mm: float = None
    checks: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    failure_reason: str = None

    def summary(self):
        """Human-readable sizing report."""
        head = f"{self.source_name} -> {self.load_name}   [{self.cable_type}]"
        lines = [head, "=" * len(head)]
        if not self.passed:
            lines.append(f"NO SOLUTION: {self.failure_reason}")
            lines.append(f"  design current      {self.design_current_a:.1f} A")
            lines.append(f"  required capacity   {self.required_capacity_a:.1f} A")
            return "\n".join(lines)

        runs = f"{self.parallel} x " if self.parallel > 1 else ""
        lines += [
            f"  Active            {runs}{self.active_area_mm2:g} mm2",
            # The neutral is None where harmonics demand a bigger one but the
            # standard's ratings are user-supplied, so there is no per-size
            # table to search. Say that rather than printing a misleading size.
            (f"  Neutral           not sized "
             f"({self.neutral_current_a:.1f} A, see warnings)"
             if self.neutral_area_mm2 is None else
             f"  Neutral           {runs}{self.neutral_area_mm2:g} mm2"
             + (f"  ({self.neutral_current_a:.1f} A, substantial harmonics)"
                if self.substantial_harmonics else "")),
            f"  Earth             {self.earth_area_mm2:g} mm2",
            f"  Design current    {self.design_current_a:.1f} A",
            f"  Derating          {self.derating_factor:.3f} "
            f"(ambient {self.ambient_factor:.3f} x grouping {self.grouping_factor:.3f})",
            f"  Table rating req. {self.required_capacity_a:.1f} A "
            f"(design / derating)",
            f"  Derated capacity  {self.derated_capacity_a:.1f} A "
            f"(installed, all runs)",
            f"  Operating temp    {self.operating_temp_c:.1f} C",
            f"  Voltage drop      {self.voltage_drop_v:.2f} V "
            f"({self.voltage_drop_pct:.2f} %)",
            f"  Fault current     {self.fault_current_a:.0f} A "
            f"-> min area {self.min_fault_area_mm2:.1f} mm2 (K={self.k_constant:.1f})",
        ]
        if self.max_loop_length_m is not None:
            lines.append(f"  Max loop length   {self.max_loop_length_m:.0f} m")
        lines += [
            f"  Cable OD          {self.od_mm:g} mm",
            f"  Weight            {self.weight_kg_per_m:.2f} kg/m per core",
            f"  Bend radius       {self.bend_radius_mm:g} mm (installation)",
            "  Checks:",
        ]
        for c in self.checks:
            mark = "PASS" if c.passed else "FAIL"
            margin = f"  ({c.margin_pct:+.1f}% margin)" if c.margin_pct is not None else ""
            lines.append(f"    [{mark}] {c.name}: {c.detail}{margin}")
        for w in self.warnings:
            lines.append(f"  ! {w}")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

# Which AS/NZS 3008 impedance table applies to a catalogue family, and in what
# formation. Every family in the repo catalogue is single-core; the mapping is
# explicit so a multicore family added later picks up Tables 4.1(B)/4.7 rather
# than silently reading the single-core columns.
def _construction(entry):
    """AS/NZS 3008 construction key for a catalogue family."""
    name = f"{entry.get('name','')} {entry.get('insulation','')}".lower()
    if "mims" in name:
        return "mims_single"
    if "flex" in name or entry.get("class") == 5:
        return "flexible_single"
    if "aerial" in name or "abc" in name:
        return "aerial"
    cores = entry.get("loaded_cores")
    if "single core" in name or "single-core" in name or cores is None:
        return "single_core"
    return "multicore"


# Fallback only. FORMATION IS NOT A FUNCTION OF INSTALLATION METHOD.
#
# Trefoil versus flat is an independent physical choice: single-core cables can
# be laid in trefoil on a tray that is "unenclosed touching", and the Tricab
# report that this engine was checked against says exactly that -- "3 x 1 core
# trefoil ... Unenclosed spaced from surface". Two axes, not one.
#
# Guessing flat from a "spaced" or "touching" method costs about 19 % on
# reactance at every size (Table 4.2(A): 0.0791 trefoil against 0.0943 flat at
# 400 mm2). That overstates voltage drop, so it is the conservative direction,
# but it is still wrong and can push the selection a size larger than needed.
#
# Installation.formation carries the real answer. This map is used only when the
# caller does not state one, and a warning is raised when it is.
_FORMATION_FALLBACK = {
    "conduit": "trefoil",
    "conduit_air": "trefoil",
    "buried": "trefoil",
    "buried_direct": "trefoil",
}
_FORMATION_DEFAULT = "flat_touching"     # the higher-reactance direction

FORMATIONS = ("trefoil", "flat_touching")


def _cable_electrical(entry, spec, area_mm2, conductor, temp_c, max_temp_c,
                      method="touching", formation=None):
    """Return (r_ohm_km at temp_c, x_ohm_km, warnings) for one core.

    Prefers the catalogue AC resistance, which already includes skin and
    proximity effect, and rescales it from the temperature it is quoted at
    (the insulation maximum) down to the actual operating temperature. Falls
    back to a DC resistance with an AC/DC uplift applied.
    """
    warnings = []
    construction = _construction(entry)

    # AS/NZS 3008.1.1:2025 Tables 4.5 to 4.13 tabulate a.c. resistance against
    # conductor temperature directly, with skin and proximity effect already in
    # the value. That is the standard's own number, so it is preferred over
    # both the catalogue figure and any AC/DC uplift.
    r_std, r_table = as3008.resistance_ac_ohm_km(
        area_mm2, temp_c, conductor.name, construction)
    if r_std is not None:
        cat = spec.get("r_ac_ohm_km")
        if cat is not None:
            f_q = 1.0 + conductor.alpha * (max_temp_c - 20.0)
            f_t = 1.0 + conductor.alpha * (temp_c - 20.0)
            cat_at_temp = cat * f_t / f_q
            if abs(cat_at_temp - r_std) / r_std > 0.05:
                warnings.append(
                    f"{area_mm2:g} mm2: catalogue R_ac {cat_at_temp:.4f} ohm/km "
                    f"differs from AS/NZS 3008 Table {r_table} "
                    f"({r_std:.4f}) by "
                    f"{100*(cat_at_temp-r_std)/r_std:+.1f}%; the standard is used"
                )
        return (r_std,
                _reactance(entry, spec, area_mm2, warnings, method, formation),
                warnings)

    r_ac = spec.get("r_ac_ohm_km")
    if r_ac is not None:
        # r_ac is quoted at the conductor maximum temperature. Rescale by the
        # ratio of the resistance-temperature factors.
        f_quoted = 1.0 + conductor.alpha * (max_temp_c - 20.0)
        f_target = 1.0 + conductor.alpha * (temp_c - 20.0)
        _large_conductor_warning(area_mm2, warnings)
        return (r_ac * f_target / f_quoted,
                _reactance(entry, spec, area_mm2, warnings, method, formation), warnings)

    r20 = spec.get("r_dc_ohm_km") or iec60228.r_dc_20(conductor.name, area_mm2)
    if r20 is None:
        return None, None, [f"no resistance data for {area_mm2:g} mm2 {conductor.name}"]
    if not spec.get("r_dc_ohm_km"):
        warnings.append(
            f"resistance for {area_mm2:g} mm2 taken from IEC 60228, not the catalogue"
        )
    ratio = as3008.ac_dc_ratio(area_mm2)
    r = as3008.resistance_at_temp(r20, conductor, temp_c) * ratio
    if ratio > 1.01:
        warnings.append(
            f"AC/DC ratio {ratio:.3f} applied to the {area_mm2:g} mm2 DC "
            f"resistance for skin and proximity effect"
        )
    _large_conductor_warning(area_mm2, warnings)
    return r, _reactance(entry, spec, area_mm2, warnings, method, formation), warnings


def _large_conductor_warning(area_mm2, warnings):
    """Flag that AS/NZS 3008 is more conservative than the catalogue at large sizes."""
    if float(area_mm2) >= as3008.LARGE_CONDUCTOR_REVIEW_MM2:
        warnings.append(
            f"{area_mm2:g} mm2: AS/NZS 3008 Table 4.5(A) implies an AC/DC ratio up "
            f"to 1.25 against the catalogue's {as3008.ac_dc_ratio(area_mm2):.3f}; "
            f"confirm voltage drop against the printed table before issue"
        )


def _reactance(entry, spec, area_mm2, warnings, method="touching",
               formation=None):
    """Reactance in ohm/km, from AS/NZS 3008 Tables 4.1 to 4.4.

    This used to fall back to a single nominal 0.08 ohm/km for every size and
    formation, which understated reactance for flat-touching single-core by up
    to 50 %. The standard's own tables now supply it, indexed by construction,
    formation and insulation.
    """
    construction = _construction(entry)
    if formation is None:
        formation = _FORMATION_FALLBACK.get(method, _FORMATION_DEFAULT)
        if construction.startswith(("single_core", "flexible_single")):
            warnings.append(
                f"cable formation not stated; assumed {formation!r} for "
                f"reactance. Trefoil and flat differ by about 19 % in X, so "
                f"state Installation(formation=...) rather than let this be "
                f"guessed from the installation method"
            )
    family = as3008.resolve_insulation(entry["insulation"]).family
    x, table, notes = as3008.reactance_ohm_km(
        area_mm2, construction=construction, formation=formation,
        insulation_family=family)
    if x is None:
        x = spec.get("x_ohm_km")
        if x is None:
            x = iec60228.NOMINAL_X_OHM_KM
            warnings.append(
                f"reactance for {area_mm2:g} mm2 not tabulated; assumed "
                f"{x} ohm/km"
            )
        return x
    warnings.extend(notes)
    cat = spec.get("x_ohm_km")
    if cat is not None and abs(cat - x) / x > 0.10:
        warnings.append(
            f"{area_mm2:g} mm2: catalogue X {cat:.4f} ohm/km differs from "
            f"AS/NZS 3008 Table {table} ({x:.4f}) by {100*(cat-x)/x:+.1f}%; "
            f"the standard is used"
        )
    return x


@dataclass
class _Context:
    """Everything a candidate size is judged against, resolved once."""
    source: object
    load: object
    install: object
    route_length_m: float
    std: object
    entry: dict
    sizes: list
    conductor: object
    insulation: object
    rating_column: str          # None when the rating is user-supplied
    ambient: float
    k_amb: float
    i_design: float
    i_neutral: float
    vd_limit_pct: float
    vd_limit_v: float
    floor_mm2: float
    setup_warnings: tuple = ()


def _resolve(source, load, route_length_m, install, catalog):
    """Shared setup for select mode and check mode."""
    std = install.profile()
    m = install.method_spec()          # raises on an unknown method
    if install.cable_type not in catalog["cables"]:
        raise ValueError(
            f"cable type {install.cable_type!r} not in catalogue "
            f"({sorted(catalog['cables'])})"
        )
    entry = catalog["cables"][install.cable_type]
    conductor = as3008.CONDUCTORS[entry["conductor"]]
    insulation = as3008.resolve_insulation(entry["insulation"])

    i_design = as3008.design_current(
        source.phase_mode, source.voltage_v, kw=load.kw, kva=load.kva,
        amps=load.amps, hp=load.hp, power_factor=load.power_factor,
        efficiency=load.efficiency,
    )
    ambient = install.effective_ambient_c()
    k_amb = as3008.ambient_rating_factor(
        insulation.max_temp_c, ambient, install.base_ambient_c(),
        medium=m.medium,
    )
    k_grp = as3008.grouping_rating_factor(install.n_circuits)

    setup_warnings = []
    # The tabulated ambient factors exist only for 90 C XLPE on a 40 C air
    # basis, so every other profile falls back to the closed form, which the
    # docstring on ambient_rating_factor measures as optimistic by up to 6.5%.
    # An optimistic derating factor undersizes cable, so it is said out loud.
    if (ambient != install.base_ambient_c()
            and not as3008.ambient_factor_is_tabulated(
                insulation.max_temp_c, install.base_ambient_c(), m.medium)):
        setup_warnings.append(
            f"ambient factor {k_amb:.3f} comes from the closed form, with no "
            f"tabulated factor held for a {install.base_ambient_c():g} C "
            f"{m.medium} basis at {insulation.max_temp_c:g} C. It runs "
            f"optimistic by up to 6.5%, so confirm it against the correction "
            f"factor tables in {std.name} before issue")

    # Voltage drop limit: an explicit load limit wins, then the standard's own
    # table, and only AS/NZS has the substation exception.
    if load.max_voltage_drop_pct is not None:
        vd_limit_pct = load.max_voltage_drop_pct
    elif install.standard == standards.AS_NZS.id:
        vd_limit_pct = as3008.voltage_drop_limit_pct(
            install.dedicated_onsite_substation)
    else:
        vd_limit_pct = std.vd_limit_pct(install.vd_supply, install.vd_use)

    ctx = _Context(
        source=source, load=load, install=install,
        route_length_m=route_length_m, std=std, entry=entry,
        sizes=sorted(entry["sizes"].items(), key=lambda kv: float(kv[0])),
        conductor=conductor, insulation=insulation,
        rating_column=m.catalogue_column,
        ambient=ambient, k_amb=k_amb,
        i_design=i_design,
        i_neutral=as3008.neutral_design_current(
            source.phase_mode, i_design,
            out_of_balance_pct=load.out_of_balance_pct,
            harmonic_content_pct=load.harmonic_content_pct),
        vd_limit_pct=vd_limit_pct,
        vd_limit_v=vd_limit_pct / 100.0 * source.voltage_v,
        floor_mm2=as3008.min_conductor_area(install.circuit_use),
        setup_warnings=tuple(setup_warnings),
    )
    return ctx, k_amb, k_grp


def _derating(ctx, parallel):
    """Grouping and total derating factor for a given parallel-run count.

    Returns (k_grp, k_total, n_groups).
    """
    n_groups = ctx.install.n_circuits
    if ctx.install.parallel_runs_grouped:
        n_groups *= parallel
    k_grp = as3008.grouping_rating_factor(n_groups)
    return k_grp, ctx.k_amb * k_grp, n_groups


def _base_rating(ctx, spec):
    """Tabulated rating for one size, from the catalogue or from the user.

    A profile whose `rating_source` is "user_supplied" has no column in our
    catalogue, so the rating has to come in with the request. Deriving one by
    re-referencing the AS/NZS figures would be optimistic and would undersize:
    see the note in standards.py.
    """
    if ctx.rating_column:
        return spec.get(ctx.rating_column)
    return ctx.install.tabulated_rating_a


def _evaluate(ctx, area, spec, parallel):
    """Every applicable check on one candidate size and run count.

    Always evaluates every check it can compute, rather than stopping at the
    first failure, so check mode can show the margin on all of them.
    """
    source, load, install = ctx.source, ctx.load, ctx.install
    checks, warnings = [], list(ctx.setup_warnings)

    base_rating = _base_rating(ctx, spec)
    if base_rating is None:
        return None
    k_grp, k_total, n_groups = _derating(ctx, parallel)
    derated = base_rating * k_total * parallel

    # --- check 1: current-carrying capacity ---
    cap_ok = derated >= ctx.i_design
    checks.append(Check(
        "current capacity", cap_ok,
        f"{derated:.1f} A derated vs {ctx.i_design:.1f} A design",
        100.0 * (derated - ctx.i_design) / ctx.i_design,
    ))

    # --- operating temperature, then resistance at that temperature ---
    t_op = as3008.operating_temperature(
        ctx.ambient, ctx.insulation.max_temp_c, ctx.i_design, derated)
    # R-VD-11: band against the columns THIS table carries, not a global list.
    t_col = as3008.round_to_temp_column(
        t_op, as3008_2025.available_temperatures(_construction(ctx.entry)))
    r, x, w = _cable_electrical(ctx.entry, spec, area, ctx.conductor, t_col,
                                ctx.insulation.max_temp_c, method=ctx.install.method,
                                formation=ctx.install.formation)
    warnings += w
    if r is None:
        return None

    # --- check 2: voltage drop ---
    z = as3008.cable_impedance(r, x, power_factor=load.power_factor)
    vd = as3008.voltage_drop(
        source.phase_mode, ctx.i_design, ctx.route_length_m, z, parallel=parallel)
    vd_pct = 100.0 * vd / source.voltage_v
    vd_ok = vd <= ctx.vd_limit_v
    checks.append(Check(
        "voltage drop", vd_ok,
        f"{vd:.2f} V ({vd_pct:.2f} %) vs {ctx.vd_limit_pct:g} % limit",
        100.0 * (ctx.vd_limit_v - vd) / ctx.vd_limit_v,
    ))

    # --- check 3: short-circuit withstand ---
    # The IEC voltage factor c scales both the driving voltage and the network
    # impedance implied by the declared fault level. c = 1.0 for AS/NZS and the
    # NEC, so those profiles are unaffected.
    c = ctx.std.voltage_factor_c
    z_cable_ohm = math.hypot(r, x) * ctx.route_length_m / 1000.0 / parallel
    i_fault = as3008.prospective_fault_current(
        c * source.phase_voltage_v, c * source.source_impedance_ohm, z_cable_ohm)
    # AS/NZS 3008.1.1:2025 Table 5.2. Thermoplastic drops from 160 C to 140 C
    # above 300 mm2, so the limit depends on the size being tested.
    sc_limit, sc_verified = as3008.sc_limit_temp(ctx.insulation, area)
    if not sc_verified:
        warnings.append(
            f"short-circuit limit {sc_limit:g} C for "
            f"{ctx.insulation.code} assumed by family; AS/NZS 3008 Table 5.2 "
            f"does not name this insulation"
        )
    k = as3008.k_constant(ctx.conductor, t_col, sc_limit)
    s_min = as3008.min_area_for_fault(i_fault, source.clearing_time_s, k)
    s_min_per_run = s_min / parallel
    sc_ok = area >= s_min_per_run
    checks.append(Check(
        "short circuit", sc_ok,
        f"{area:g} mm2 vs {s_min_per_run:.1f} mm2 required "
        f"({i_fault:.0f} A for {source.clearing_time_s:g} s, K={k:.1f})",
        100.0 * (area - s_min_per_run) / s_min_per_run,
    ))

    # --- neutral conductor (AS/NZS 3000 clause 3.5.2) ---
    neutral_area = area
    if ctx.i_neutral > ctx.i_design:
        if ctx.rating_column:
            for n_key, n_spec in ctx.sizes:
                n_area = float(n_key)
                if n_area < area:
                    continue
                n_rating = n_spec.get(ctx.rating_column)
                if n_rating is None:
                    continue
                if n_rating * k_total * parallel >= ctx.i_neutral:
                    neutral_area = n_area
                    break
            else:
                neutral_area = float(ctx.sizes[-1][0])
            if neutral_area > area:
                warnings.append(
                    f"neutral upsized to {neutral_area:g} mm2 for "
                    f"{ctx.i_neutral:.1f} A neutral current "
                    f"({load.harmonic_content_pct:g}% harmonic content)")
        else:
            # No per-size rating table to search, so the neutral cannot be
            # upsized here. Say so rather than reporting it equal to the active.
            warnings.append(
                f"neutral carries {ctx.i_neutral:.1f} A against a "
                f"{ctx.i_design:.1f} A phase current, but {ctx.std.name} "
                f"ratings are user-supplied, so the neutral size has not been "
                f"checked: size it from {ctx.std.rating_table_ref} for "
                f"{ctx.i_neutral:.1f} A")
            neutral_area = None

    # --- earth conductor ---
    earth_area = as3008.min_earth_area(
        area, n_active=parallel, n_earth=1, conductor_name=ctx.conductor.name)
    earth_area = _next_catalog_size(ctx.sizes, earth_area)

    # --- check 4: earth fault loop impedance (only if protection given) ---
    max_len = None
    if source.protection_type == "MCB" and source.mcb_rating_a:
        i_trip = as3008.mcb_trip_current(source.mcb_curve, source.mcb_rating_a)
        r_e = iec60228.r_dc_20(ctx.conductor.name, earth_area)
        if r_e is not None:
            ze = as3008.resistance_at_temp(r_e, ctx.conductor, t_col)
            max_len = as3008.max_length_calculated(
                source.phase_voltage_v, i_trip,
                source.source_impedance_ohm, r / parallel, ze)
            loop_ok = ctx.route_length_m <= max_len
            checks.append(Check(
                "earth loop impedance", loop_ok,
                f"{ctx.route_length_m:g} m route vs {max_len:.0f} m max "
                f"(trip {i_trip:.0f} A)",
                100.0 * (max_len - ctx.route_length_m) / max_len,
            ))
        else:
            warnings.append(
                f"earth loop check skipped: no resistance data for "
                f"{earth_area:g} mm2 earth")

    if n_groups > ctx.install.n_circuits:
        warnings.append(
            f"{parallel} parallel runs counted as {n_groups} grouped bundles, "
            f"so the grouping factor is {k_grp:.3f} rather than "
            f"{as3008.grouping_rating_factor(ctx.install.n_circuits):.3f}")

    return {
        "passed": all(c.passed for c in checks),
        "checks": checks, "warnings": warnings,
        "k_grp": k_grp, "k_total": k_total, "n_groups": n_groups,
        "area": area, "parallel": parallel, "derated": derated,
        "t_op": t_op, "vd": vd, "vd_pct": vd_pct,
        "i_fault": i_fault, "s_min_per_run": s_min_per_run, "k": k,
        "neutral_area": neutral_area, "earth_area": earth_area,
        "max_len": max_len, "spec": spec,
    }


def _fill_result(result, ctx, ev, k_amb, k_grp):
    spec = ev["spec"]
    result.passed = ev["passed"]
    result.active_area_mm2 = ev["area"]
    result.earth_area_mm2 = ev["earth_area"]
    result.neutral_area_mm2 = ev["neutral_area"]
    result.parallel = ev["parallel"]
    result.design_current_a = ctx.i_design
    result.neutral_current_a = ctx.i_neutral
    result.substantial_harmonics = as3008.is_substantial_harmonic(
        ctx.load.harmonic_content_pct)
    result.ambient_factor = k_amb
    result.grouping_factor = ev["k_grp"]
    result.derating_factor = ev["k_total"]
    result.required_capacity_a = ctx.i_design / ev["k_total"]
    result.voltage_drop_limit_pct = ctx.vd_limit_pct
    result.derated_capacity_a = ev["derated"]
    result.operating_temp_c = ev["t_op"]
    result.voltage_drop_v = ev["vd"]
    result.voltage_drop_pct = ev["vd_pct"]
    result.fault_current_a = ev["i_fault"]
    result.min_fault_area_mm2 = ev["s_min_per_run"]
    result.k_constant = ev["k"]
    result.max_loop_length_m = ev["max_len"]
    result.od_mm = spec.get("od_mm")
    result.weight_kg_per_m = (spec["weight_kg_100m"] / 100.0
                              if spec.get("weight_kg_100m") else None)
    result.bend_radius_mm = spec.get("bend_install_mm")
    result.checks = ev["checks"]
    result.warnings = ev["warnings"]
    return result


def size_feeder(source, load, route_length_m, install=None, catalog=None):
    """Size the cable connecting `source` to `load`.

    Returns a SizingResult. Tries every catalogue size in ascending order, and
    for each size every parallel-run count from 1 up to install.max_parallel,
    returning the first combination that passes all applicable checks.

    Requires a standard that carries a rating table. For IEC, BS 7671 and the
    NEC use `check_feeder`, which verifies a size you nominate against a rating
    you supply.
    """
    install = install or Installation()
    catalog = catalog or load_catalog()
    ctx, k_amb, k_grp = _resolve(source, load, route_length_m, install, catalog)

    if not ctx.std.selects_size and install.tabulated_rating_a is None:
        raise ValueError(
            f"{ctx.std.name} ratings are not held here, so a size cannot be "
            f"selected. Read the current-carrying capacity from "
            f"{ctx.std.rating_table_ref}, supply it as the tabulated rating, "
            f"and check a size you nominate instead; or select against "
            f"{standards.AS_NZS.name}, whose table is held."
        )

    result = SizingResult(source.name, load.name, install.cable_type,
                          passed=False)
    result.design_current_a = ctx.i_design
    result.neutral_current_a = ctx.i_neutral
    result.substantial_harmonics = as3008.is_substantial_harmonic(
        load.harmonic_content_pct)
    # Provisional, on a single run. Overwritten by _fill_result on success;
    # only the failure message reads these.
    _, k_total_1, _ = _derating(ctx, 1)
    result.ambient_factor = k_amb
    result.grouping_factor = k_grp
    result.derating_factor = k_total_1
    result.required_capacity_a = ctx.i_design / k_total_1
    result.voltage_drop_limit_pct = ctx.vd_limit_pct

    for parallel in range(1, install.max_parallel + 1):
        for size_key, spec in ctx.sizes:
            area = float(size_key)
            if area < ctx.floor_mm2:
                continue  # AS/NZS 3000 Table 3.3 minimum conductor size
            if parallel > 1 and area < 4.0:
                continue  # AS/NZS 3000 minimum 4 mm2 for parallel cables
            ev = _evaluate(ctx, area, spec, parallel)
            if ev is None or not ev["passed"]:
                continue
            return _fill_result(result, ctx, ev, k_amb, k_grp)

    result.failure_reason = (
        f"no size up to {install.max_parallel} parallel runs of the largest "
        f"catalogue size satisfies {result.required_capacity_a:.0f} A required "
        f"capacity, {ctx.vd_limit_pct:g}% voltage drop over "
        f"{route_length_m:g} m, and the fault duty"
    )
    return result


def check_feeder(source, load, route_length_m, area_mm2, install=None,
                 catalog=None, parallel=1):
    """Check a size you nominate, rather than selecting one.

    This is how the IEC, BS 7671 and NEC profiles are used: you read the
    tabulated current-carrying capacity out of that standard's table, put it in
    `Installation.tabulated_rating_a`, and this runs design current, derating,
    operating temperature, voltage drop, the adiabatic short-circuit check and
    the earth fault loop check on that standard's rules.

    Every check is reported with its margin whether it passes or fails, because
    the point of checking a nominated size is to see how close it sits.
    """
    install = install or Installation()
    catalog = catalog or load_catalog()
    ctx, k_amb, k_grp = _resolve(source, load, route_length_m, install, catalog)

    spec = ctx.entry["sizes"].get(f"{float(area_mm2):g}", {})
    if _base_rating(ctx, spec) is None:
        raise ValueError(
            f"no current-carrying capacity for {area_mm2:g} mm2 under "
            f"{ctx.std.name}. Supply Installation.tabulated_rating_a from "
            f"{ctx.std.rating_table_ref}."
        )

    result = SizingResult(source.name, load.name, install.cable_type,
                          passed=False)
    ev = _evaluate(ctx, float(area_mm2), spec, parallel)
    if ev is None:
        raise ValueError(
            f"cannot evaluate {area_mm2:g} mm2: no resistance data available")
    _fill_result(result, ctx, ev, k_amb, k_grp)
    if not result.passed:
        failed = [c.name for c in ev["checks"] if not c.passed]
        result.failure_reason = (
            f"{area_mm2:g} mm2 fails {', '.join(failed)}")
    return result


def _next_catalog_size(sizes, min_area):
    """Smallest catalogue size >= min_area, or the largest if none reaches it."""
    for size_key, _ in sizes:
        if float(size_key) >= min_area:
            return float(size_key)
    return float(sizes[-1][0])


# ---------------------------------------------------------------------------
# Network-level helper
# ---------------------------------------------------------------------------

def size_network(connections, catalog=None):
    """Size every connection in a list of (source, load, length_m, install) tuples.

    Returns a list of SizingResult in the same order.
    """
    catalog = catalog or load_catalog()
    out = []
    for conn in connections:
        source, load, length = conn[0], conn[1], conn[2]
        install = conn[3] if len(conn) > 3 else Installation()
        out.append(size_feeder(source, load, length, install, catalog))
    return out


def voltage_drop_budget(results, nominal_voltage_v, limit_pct=None,
                        dedicated_onsite_substation=False):
    """Check the cumulative voltage drop along a path against clause 3.6.2.

    AS/NZS 3000 clause 3.6.2 limits the drop between the point of supply and
    *any* point in the installation, so the drops of the cables in series along
    a path add. size_feeder() only sees one segment, so a path of individually
    compliant segments can still breach the limit overall.

    `results` must be the SizingResult objects along one path, in order from the
    point of supply. Returns a dict with the running total and a pass/fail.
    """
    if limit_pct is None:
        limit_pct = as3008.voltage_drop_limit_pct(dedicated_onsite_substation)
    segments, total_v = [], 0.0
    for r in results:
        if not r.passed:
            raise ValueError(f"segment {r.source_name}->{r.load_name} has no solution")
        total_v += r.voltage_drop_v
        segments.append({
            "from": r.source_name,
            "to": r.load_name,
            "drop_v": r.voltage_drop_v,
            "drop_pct": r.voltage_drop_pct,
            "cumulative_v": total_v,
            "cumulative_pct": 100.0 * total_v / nominal_voltage_v,
        })
    total_pct = 100.0 * total_v / nominal_voltage_v
    return {
        "segments": segments,
        "total_v": total_v,
        "total_pct": total_pct,
        "limit_pct": limit_pct,
        "passed": total_pct <= limit_pct,
        "margin_pct": limit_pct - total_pct,
    }


def cable_schedule(results):
    """Render a list of SizingResult as a cable schedule table."""
    header = (f"{'From':<12} {'To':<12} {'Cable':<14} {'Active':>12} "
              f"{'Neutral':>9} {'Earth':>8} {'I (A)':>8} {'Vd %':>7} {'OD':>7}")
    lines = [header, "-" * len(header)]
    harmonic_note = False
    for r in results:
        if not r.passed:
            lines.append(f"{r.source_name:<12} {r.load_name:<12} "
                         f"{'NO SOLUTION':<14}")
            continue
        harmonic_note = harmonic_note or r.substantial_harmonics
        active = (f"{r.parallel}x{r.active_area_mm2:g}" if r.parallel > 1
                  else f"{r.active_area_mm2:g}")
        neutral = f"{r.neutral_area_mm2:g}"
        if r.substantial_harmonics:
            neutral += "*"
        lines.append(
            f"{r.source_name:<12} {r.load_name:<12} {r.cable_type:<14} "
            f"{active:>12} {neutral:>9} {r.earth_area_mm2:>8g} "
            f"{r.design_current_a:>8.1f} {r.voltage_drop_pct:>7.2f} {r.od_mm:>7g}")
    if harmonic_note:
        lines.append("* neutral sized for substantial harmonic content "
                     "(AS/NZS 3000 clause 3.5.2(b)(i))")
    return "\n".join(lines)
