"""Cable sizing standard profiles.

Four standards size cables the same way and disagree about the inputs. Design
current, derating, operating temperature, voltage drop and the adiabatic
short-circuit check are common; what changes between them is the reference
ambient, the soil model, the installation vocabulary, the permitted voltage
drop, whether an IEC voltage factor applies, and the units. This module holds
those differences so `cable_sizing.py` stays one engine rather than four.

## What each profile can and cannot do

The one thing a profile cannot supply is a current-carrying capacity table. Ours
come from `../cables/cable_catalog.json`, which is Nexans Australia data on the
AS/NZS basis (40 C air, 25 C soil). So:

  AS/NZS 3008.1.1   rating_source = "catalogue". The engine SELECTS a size,
                    picking the smallest that passes every check.

  IEC / BS / NEC    rating_source = "user_supplied". We hold no ampacity table
                    on a 30 C basis, and re-referencing the AS/NZS ratings with
                    the ambient closed form would run OPTIMISTIC -- see the
                    docstring on `as3008.ambient_rating_factor`, which measures
                    that error at up to +6.5%. Optimistic factors undersize
                    cable, so the profile asks for the tabulated rating instead
                    of inventing one. The engine then CHECKS a nominated size,
                    running every other calculation on that standard's rules
                    with a full audit trail.

Select mode and check mode are both honest. Guessing an ampacity would not be.

## Provenance

Reference ambients, soil models, installation vocabularies and voltage drop
limits are transcribed from ELEK Cable Pro Web's four calculator pages,
captured 2026-09-02 into `reference/elek-cable-sizing-{as,iec,bs,nec}.txt`.
That is a competent third-party implementation, not the printed standard, so
every profile carries `verified: False` and names the clause or table to check
against. Treat these as good pointers pending a read of the standard itself.
The AS/NZS figures are the exception in one respect: its voltage drop limits,
minimum conductor sizes and temperature limits are independently verified in
`reference_tables.json` against the printed AS/NZS 3000:2018.
"""
from __future__ import annotations

import dataclasses

EVIDENCE = "reference/elek-cable-sizing-{}.txt (captured 2026-09-02)"


@dataclasses.dataclass(frozen=True)
class Method:
    """One installation arrangement, as that standard names it."""
    id: str
    label: str
    medium: str                  # "air" or "soil"
    ref: str                     # the standard's own designation
    catalogue_column: str = None  # rating column in cable_catalog.json, if any
    diagram: str = "generic"      # key into install_diagrams.DIAGRAMS
    note: str = ""


@dataclasses.dataclass(frozen=True)
class Standard:
    id: str
    name: str
    title: str
    jurisdiction: str
    rating_source: str            # "catalogue" or "user_supplied"
    rating_table_ref: str
    air_c: float
    soil_c: float
    soil_resistivity: str
    burial_depth_m: float
    methods: tuple
    vd_limits: tuple              # (label, lighting_pct, other_pct) rows
    vd_note: str
    voltage_factor_c: float
    voltage_factor_note: str
    area_unit: str
    impedance_unit: str
    source: str
    verified: bool = False
    extra_rules: tuple = ()

    @property
    def selects_size(self):
        return self.rating_source == "catalogue"

    def vd_limit_pct(self, supply="public", use="other"):
        """Permitted voltage drop for a supply arrangement and load use."""
        idx = 1 if use == "lighting" else 2
        for row in self.vd_limits:
            if row[0] == supply:
                return row[idx]
        return self.vd_limits[0][idx]


AS_NZS = Standard(
    id="AS3008",
    name="AS/NZS 3008.1.1",
    title="Cable selection for typical AUSTRALIAN installation conditions",
    jurisdiction="AU",
    rating_source="catalogue",
    rating_table_ref="Table 3.9 (unenclosed and enclosed in air), via the "
                     "Nexans Australia catalogue",
    air_c=40.0,
    soil_c=25.0,
    soil_resistivity="1.2 K.m/W",
    burial_depth_m=0.5,
    methods=(
        Method("spaced", "Unenclosed, spaced from a surface", "air", "Table 3.9",
               "i_3ph_spaced_a", "spaced",
               "Clearance of at least one cable diameter to the surface."),
        Method("touching", "Unenclosed, touching, on a tray or ladder", "air",
               "Table 3.9", "i_3ph_touching_a", "touching",
               "Single layer, cables in contact."),
        Method("conduit", "Enclosed in conduit in air", "air", "Table 3.9",
               "i_3ph_conduit_a", "conduit_air"),
        Method("buried", "Buried direct in the ground", "soil", "Table 3.9",
               "i_3ph_buried_a", "buried_direct",
               "Standard depth of burial 0.5 m."),
    ),
    vd_limits=(
        ("public", 5.0, 5.0),
        ("substation", 7.0, 7.0),
    ),
    vd_note="5 % of nominal from the point of supply to any point in the "
            "installation, rising to 7 % where the point of supply is the LV "
            "terminals of a substation on the premises and dedicated to it "
            "(clause 3.6.2). Design guidance: 0.5 % consumers mains, "
            "1.5-2 % submains, 2.5 % final subcircuits. Voltage rise limited "
            "to 2 % (AS/NZS 4777.1:2016); DC voltage drop to 3 % "
            "(AS/NZS 5033:2014).",
    voltage_factor_c=1.0,
    voltage_factor_note="AS/NZS 3008 does not prescribe an IEC 60909 voltage "
                        "factor, so none is applied. See REVIEW-ELEK.md "
                        "finding 2: this is the one respect in which our fault "
                        "current sits below ELEK's, by about 3 % on a "
                        "three-phase fault.",
    area_unit="mm2",
    impedance_unit="ohm/km",
    source=EVIDENCE.format("as") + "; voltage drop limits, minimum sizes and "
           "temperature limits independently verified against the printed "
           "AS/NZS 3000:2018 in reference_tables.json",
    extra_rules=(
        "Neutral not smaller than the active for consumers mains, submains and "
        "final subcircuits (clause 3.5.2).",
        "Conductors in parallel must be at least 4 mm2.",
        "Table 3.9 tabulates further arrangements that the catalogue carries no "
        "rating column for -- exposed to direct sunlight, partially and "
        "completely surrounded by thermal insulation, and buried in conduits. "
        "Only the four arrangements with catalogue ratings are offered.",
    ),
)


# AS/NZS 3008 is one standard in two parts, and the parts are not "the same
# tables with a different ambient written on them": part 1.1 tabulates typical
# Australian conditions and part 1.2 typical New Zealand conditions, which are
# cooler, and each part has its own current-carrying capacity tables. So the NZ
# part is a separate profile rather than a basis switch on the Australian one.
#
# It has to be user_supplied for the same reason IEC and BS are. Our catalogue
# holds Nexans ratings on the Australian 40 C basis. Re-referencing those to the
# NZ 30 C basis and calling the answer a Table 14 rating would be inventing a
# number from the wrong table. An earlier version of this repo had exactly that
# trap: `Installation.basis="NZ"` silently rebased the Australian ratings.
AS_NZS_NZ = Standard(
    id="AS3008NZ",
    name="AS/NZS 3008.1.2",
    title="Cable selection for typical NEW ZEALAND installation conditions",
    jurisdiction="NZ",
    rating_source="user_supplied",
    rating_table_ref="Table 14 (and the other NZ rating tables)",
    air_c=30.0,
    soil_c=15.0,
    # Sources disagree here and neither is the printed standard: ELEK's NZ
    # calculator says 1.0 K.m/W, jCalc's says 1.2. Air and soil temperature and
    # the 0.5 m depth agree across both. The figure only bites on buried
    # ratings, which are user-supplied for this profile anyway, so the conflict
    # is recorded rather than resolved.
    soil_resistivity="1.0 K.m/W (ELEK); jCalc states 1.2 -- unresolved",
    burial_depth_m=0.5,
    methods=(
        Method("spaced", "Unenclosed, spaced", "air", "Table 14", None,
               "spaced"),
        Method("touching", "Unenclosed, touching", "air", "Table 14", None,
               "touching"),
        Method("sun", "Unenclosed, exposed to direct sunlight", "air",
               "Table 14", None, "spaced",
               "Solar gain is in the tabulated rating, so do not also derate "
               "for it."),
        Method("enclosed_air", "Enclosed in a wiring enclosure in air", "air",
               "Table 14", None, "conduit_air"),
        Method("ti_partial_unenclosed",
               "Partially surrounded by thermal insulation, unenclosed", "air",
               "Table 14", None, "clipped_direct"),
        Method("ti_partial_enclosed",
               "Partially surrounded by thermal insulation, enclosed", "air",
               "Table 14", None, "conduit_wall"),
        Method("ti_complete_unenclosed",
               "Completely surrounded by thermal insulation, unenclosed", "air",
               "Table 14", None, "conduit_insulated_wall"),
        Method("ti_complete_enclosed",
               "Completely surrounded by thermal insulation, enclosed", "air",
               "Table 14", None, "conduit_insulated_wall"),
        Method("buried", "Buried direct in the ground", "soil", "Table 14",
               None, "buried_direct",
               "Standard depth of burial 0.5 m."),
        Method("buried_enclosure", "Buried in an enclosure", "soil",
               "Table 14", None, "buried_ducts"),
    ),
    vd_limits=(
        ("public", 5.0, 5.0),
        ("substation", 7.0, 7.0),
    ),
    vd_note="Same limits as the Australian part: 5 % of nominal from the point "
            "of supply to any point in the installation, rising to 7 % where "
            "the point of supply is the LV terminals of a substation on the "
            "premises and dedicated to it.",
    voltage_factor_c=1.0,
    voltage_factor_note="As for the Australian part, no IEC 60909 voltage "
                        "factor is prescribed, so none is applied.",
    area_unit="mm2",
    impedance_unit="ohm/km",
    source=EVIDENCE.format("nz") + "; cross-checked against "
           "reference/jcalc-cable-sizing-as3008.txt",
    extra_rules=(
        "The reference conditions are cooler than the Australian part: 30 C "
        "air against 40 C, 15 C soil against 25 C, and soil thermal "
        "resistivity 1.0 K.m/W against 1.2. A rating read from an Australian "
        "table is therefore NOT valid here.",
        "Neutral not smaller than the active for consumers mains, submains and "
        "final subcircuits (AS/NZS 3000 clause 3.5.2).",
        "Conductors in parallel must be at least 4 mm2.",
    ),
)

IEC = Standard(
    id="IEC60364",
    name="IEC 60364-5-52",
    title="Selection and erection of electrical equipment, wiring systems",
    jurisdiction="International",
    rating_source="user_supplied",
    rating_table_ref="Tables B.52.5 (air) and B.52.12 (buried)",
    air_c=30.0,
    soil_c=20.0,
    soil_resistivity="2.5 K.m/W",
    burial_depth_m=0.7,
    methods=(
        Method("A1", "A1  Insulated conductors in conduit in a thermally "
               "insulated wall", "air", "Method A1", None, "conduit_insulated_wall"),
        Method("B1", "B1  Insulated conductors in conduit on a wooden wall",
               "air", "Method B1", None, "conduit_wall"),
        Method("C", "C  On a wooden wall", "air", "Method C", None,
               "clipped_direct"),
        Method("D2", "D2  Sheathed cables direct in the ground", "soil",
               "Method D2", None, "buried_direct",
               "Reference depth of laying 0.7 m."),
        Method("F_trefoil", "F  Trefoil touching in free air", "air",
               "Method F", None, "trefoil",
               "Clearance to the wall not less than one cable diameter."),
        Method("F_flat", "F  Flat touching in free air", "air", "Method F",
               None, "touching",
               "Clearance to the wall not less than one cable diameter."),
        Method("G", "G  Flat spaced in free air, horizontal", "air",
               "Method G", None, "spaced"),
    ),
    vd_limits=(
        ("public", 3.0, 5.0),
        ("private", 6.0, 8.0),
    ),
    vd_note="Table G.52.1: 3 % lighting and 5 % other uses for an installation "
            "supplied directly from a public LV distribution system, rising to "
            "6 % and 8 % from a private LV supply. Beyond 100 m the limits may "
            "rise by 0.005 % per metre, capped at an extra 0.5 %.",
    voltage_factor_c=1.1,
    voltage_factor_note="IEC 60909 voltage factor c = 1.1 for maximum LV fault "
                        "current.",
    area_unit="mm2",
    impedance_unit="ohm/km",
    source=EVIDENCE.format("iec"),
    extra_rules=(
        "Adiabatic check per IEC 60364-5-54, which uses the same "
        "S = I*sqrt(t)/k form as AS/NZS 3008.",
    ),
)

BS = Standard(
    id="BS7671",
    name="BS 7671",
    title="Requirements for electrical installations, IET Wiring Regulations",
    jurisdiction="UK",
    rating_source="user_supplied",
    rating_table_ref="Table 4E2A and the other 4-series rating tables",
    air_c=30.0,
    soil_c=20.0,
    soil_resistivity="2.5 K.m/W",
    burial_depth_m=0.7,
    methods=(
        Method("A", "A  Enclosed in conduit in a thermally insulating wall",
               "air", "Method A", None, "conduit_insulated_wall"),
        Method("B", "B  Enclosed in conduit on a wall or in trunking", "air",
               "Method B", None, "conduit_wall"),
        Method("C", "C  Clipped direct", "air", "Method C", None,
               "clipped_direct"),
        Method("E", "E  In free air or on a perforated cable tray", "air",
               "Method E", None, "tray_perforated",
               "Horizontal or vertical."),
    ),
    vd_limits=(
        ("public", 3.0, 5.0),
        ("private", 6.0, 8.0),
    ),
    vd_note="Table 4Ab: 3 % lighting and 5 % other uses from a public LV "
            "distribution system, rising to 6 % and 8 % from a private LV "
            "supply. The calculated drop should include the effect of harmonic "
            "currents.",
    voltage_factor_c=1.1,
    voltage_factor_note="IEC 60909 voltage factor c = 1.1, BS 7671 being "
                        "harmonised with the IEC series.",
    area_unit="mm2",
    impedance_unit="ohm/km",
    source=EVIDENCE.format("bs"),
)

NEC = Standard(
    id="NEC",
    name="NEC 310.16",
    title="National Electrical Code, NFPA 70",
    jurisdiction="US",
    rating_source="user_supplied",
    rating_table_ref="Table 310.16 (and Table 310.12 for dwelling services)",
    air_c=30.0,
    soil_c=20.0,
    soil_resistivity="90 C.cm/W",
    burial_depth_m=0.0,
    methods=(
        Method("raceway", "Insulated conductors in a raceway", "air",
               "Table 310.16", None, "conduit_air"),
        Method("tray", "Inside a cable tray", "air", "Table 310.16", None,
               "tray_perforated"),
        Method("free_air", "Insulated conductors in free air", "air",
               "Table 310.17", None, "spaced"),
        Method("buried", "Insulated conductors directly buried", "soil",
               "Table 310.16", None, "buried_direct"),
        Method("messenger", "Insulated conductors on a messenger", "air",
               "Table 310.20", None, "messenger"),
    ),
    vd_limits=(
        ("branch", 3.0, 3.0),
        ("feeder_and_branch", 5.0, 5.0),
    ),
    vd_note="A recommendation rather than a prescriptive limit. The "
            "Informational Notes to 210.19(A) and 215.2(A)(1) recommend about "
            "3 % on a branch circuit and about 5 % for feeder plus branch "
            "combined.",
    voltage_factor_c=1.0,
    voltage_factor_note="No IEC 60909 voltage factor; the NEC does not use one.",
    area_unit="kcmil / AWG",
    impedance_unit="ohm/1000 ft",
    source=EVIDENCE.format("nec"),
    extra_rules=(
        "Ampacity is additionally limited by the equipment TERMINAL "
        "temperature rating (60, 75 or 90 C) under 110.14(C), regardless of "
        "the conductor insulation rating. This engine does not apply that "
        "limit: enter the rating already reduced to the terminal column.",
        "Table 310.16 assumes not more than three current-carrying conductors "
        "in a raceway; more requires the 310.15(C)(1) adjustment.",
        "Outdoor ambient is taken as 40 C, plus 33 C for rooftop raceways.",
        "Sizes are AWG and kcmil. This engine works in mm2 throughout, so a "
        "nominated size must be converted before entry.",
    ),
)

STANDARDS = {s.id: s for s in (AS_NZS, AS_NZS_NZ, IEC, BS, NEC)}
DEFAULT = AS_NZS.id


def get(standard_id):
    if standard_id not in STANDARDS:
        raise ValueError(
            f"unknown standard {standard_id!r}, expected one of "
            f"{sorted(STANDARDS)}")
    return STANDARDS[standard_id]


def method(standard_id, method_id):
    std = get(standard_id)
    for m in std.methods:
        if m.id == method_id:
            return m
    raise ValueError(
        f"{std.name} has no installation method {method_id!r}, expected one of "
        f"{[m.id for m in std.methods]}")


def as_dict(std):
    d = dataclasses.asdict(std)
    d["selects_size"] = std.selects_size
    d["methods"] = [dataclasses.asdict(m) for m in std.methods]
    d["vd_limits"] = [{"supply": r[0], "lighting_pct": r[1], "other_pct": r[2]}
                      for r in std.vd_limits]
    return d


def catalogue():
    """Every profile, as plain dicts, for the API and the UI."""
    return {sid: as_dict(s) for sid, s in STANDARDS.items()}
