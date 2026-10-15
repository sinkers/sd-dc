"""Section 4 of the spec - rating (correction) factors.

Conventions, stated once here because every double-counting bug in a cable
sizing tool comes from leaving them implicit:

C1. A rating factor corrects a TABULATED capacity toward the actual
    installation. It is only ever applied to a capacity declared
    DeclaredAs.TABULATED. Handing this module a capacity already declared
    DeclaredAs.DERATED raises InvalidDeclaration - it never silently skips.

C2. Factors multiply. I_z = I_t * product(cf_i). No factor is additive and no
    factor is applied twice, which the FactorSet enforces by keying on name.

C3. Ambient correction is chosen by medium, not by the user. A buried
    arrangement takes the soil table and an in-air arrangement takes the air
    table; asking for the wrong one is not expressible.

C4. Direct sunlight is not a table of its own. Per the Clause 3.5.8 note the
    approximation is to enter the air ambient table at ambient + 20 K. It
    therefore REPLACES the ordinary ambient factor rather than multiplying it.

C5. The harmonic factor is not a plain multiplier and is not part of the
    FactorSet product. Above the standard's threshold it changes which
    conductor governs, from phase to neutral, so it returns a basis as well as
    a number and is applied by current_capacity, not here.

C6. Depth of burial and soil thermal resistivity apply to buried arrangements
    only. Supplying them for an in-air arrangement is rejected at the
    InstallationMethod boundary, not quietly ignored.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from .errors import (InadmissibleFactor, InvalidDeclaration,
                     MissingTableData, OpenItem)
from .schema import (
    Cable,
    CableConstruction,
    DeclaredAs,
    InstallationArrangement,
    InstallationMethod,
    Load,
    SupportType,
)
from .tables.registry import TableStore

#: Retired. Solar radiation is a base-rating COLUMN
#: (InstallationArrangement.AIR_EXPOSED_TO_SUN), not a correction factor. The
#: Clause 3.5.8(b) "+20 K on the measured ambient" proxy applies only to cable
#: types OUTSIDE the 3.9-3.20, 3.31 and 3.32 families, which is out of M4 scope
#: and raises. Kept as a named constant so the number is not silently
#: reintroduced somewhere else. See R-ADM-3.
SUNLIGHT_AMBIENT_UPLIFT_K_OUT_OF_SCOPE = 20.0


@dataclass(frozen=True)
class RatingFactor:
    name: str
    value: float
    source: str
    key: dict = field(default_factory=dict)

    def __str__(self) -> str:
        return f"{self.name}={self.value:.4g} ({self.source})"


@dataclass
class FactorSet:
    factors: list[RatingFactor] = field(default_factory=list)

    def add(self, factor: RatingFactor) -> None:
        if any(f.name == factor.name for f in self.factors):
            raise InvalidDeclaration(
                f"rating factor {factor.name!r} applied twice - see convention C2"
            )
        self.factors.append(factor)

    @property
    def product(self) -> float:
        p = 1.0
        for f in self.factors:
            p *= f.value
        return p

    def as_dict(self) -> dict[str, float]:
        return {f.name: f.value for f in self.factors}

    def __str__(self) -> str:
        return " x ".join(str(f) for f in self.factors) or "(none)"


# --------------------------------------------------------------------------
# Harmonics - Clause 3.5.9 / Table 3.4
# --------------------------------------------------------------------------

class HarmonicBasis(str, Enum):
    PHASE = "phase"
    NEUTRAL = "neutral"


@dataclass(frozen=True)
class HarmonicOutcome:
    cf: float
    basis: HarmonicBasis
    #: the current the corrected capacity must be compared against
    governing_current_a: float
    fundamental_phase_a: float
    neutral_a: float
    source: str

    def __str__(self) -> str:
        return (
            f"harmonic cf={self.cf:.4g} on {self.basis.value} basis, "
            f"governing current {self.governing_current_a:.4g} A"
        )


def neutral_current_a(load: Load) -> tuple[float, float]:
    """Return (fundamental phase current, neutral current) for triplen content.

    Convention: Load.design_current_a is the TOTAL RMS phase current including
    harmonic content. With third-harmonic fraction r defined as I_3 / I_1,

        I_phase = I_1 * sqrt(1 + r^2)          so  I_1 = I_b / sqrt(1 + r^2)
        I_neutral = 3 * I_3 = 3 * r * I_1      (triplens add arithmetically)

    Setting I_neutral = I_phase gives r = 1/sqrt(8) = 35.36 %, which is the
    crossover at which the neutral becomes the governing conductor on pure
    physics. Note that AS/NZS 3008.1.1 Clause 3.5.9 places its band edge at
    33 %, slightly conservative of that. The standard's band edge governs;
    the 35.36 % figure is retained only as a sanity check in the test suite.
    """
    r = load.third_harmonic_fraction
    i1 = load.design_current_a / ((1.0 + r * r) ** 0.5)
    return i1, 3.0 * r * i1


def harmonic_treatment(store: TableStore, load: Load) -> HarmonicOutcome:
    """Look up Table 3.4 and decide which conductor governs.

    Raises OpenItem rather than assuming 1.0 when the table has not been
    transcribed and the harmonic content is non-trivial - a missing derating
    here is unconservative, and no default is defensible.
    """
    r = load.third_harmonic_fraction
    i1, i_n = neutral_current_a(load)

    if r == 0.0:
        return HarmonicOutcome(
            cf=1.0,
            basis=HarmonicBasis.PHASE,
            governing_current_a=load.design_current_a,
            fundamental_phase_a=i1,
            neutral_a=0.0,
            source="no declared harmonic content",
        )

    try:
        row = store.row("cf_harmonic", third_harmonic_fraction=r)
    except MissingTableData as exc:
        raise OpenItem(
            "Third-harmonic content of "
            f"{r:.1%} was declared but the Table 3.4 correction factor bands "
            "(AS/NZS 3008.1.1:2025 Clause 3.5.9) have not been transcribed into "
            "cf_harmonic.csv. No default is defensible: assuming 1.0 "
            "under-sizes the cable and assuming the worst band over-sizes it. "
            f"Underlying lookup failure: {exc}"
        ) from exc

    basis = HarmonicBasis(str(row["basis"]).strip().lower())
    governing = load.design_current_a if basis is HarmonicBasis.PHASE else i_n
    return HarmonicOutcome(
        cf=float(row["cf"]),
        basis=basis,
        governing_current_a=governing,
        fundamental_phase_a=i1,
        neutral_a=i_n,
        source="AS/NZS 3008.1.1:2025 Table 3.4",
    )


# --------------------------------------------------------------------------
# The factor set
# --------------------------------------------------------------------------

def _size_band(size_mm2: float) -> str:
    """Coarse band label used by the depth-of-burial table axis."""
    return "small" if size_mm2 <= 185 else "large"


#: R-ADM. What each base column already accounts for, and therefore which
#: factor families may be applied on top of it. A factor for an influence the
#: column already carries is INADMISSIBLE, not merely redundant, and is
#: rejected rather than multiplied by.
A = InstallationArrangement
ADMISSIBLE: dict[InstallationArrangement, frozenset[str]] = {
    A.AIR_SPACED:               frozenset({"ambient_air", "grouping", "harmonic"}),
    A.AIR_SPACED_FROM_SURFACE:  frozenset({"ambient_air", "grouping", "harmonic"}),
    A.AIR_TOUCHING:             frozenset({"ambient_air", "grouping", "harmonic"}),
    # the sun is IN the column: no uplift of any kind, including the
    # Cl 3.5.8(b) +20 K proxy (R-ADM-3)
    A.AIR_EXPOSED_TO_SUN:       frozenset({"ambient_air", "grouping", "harmonic"}),
    A.ENCLOSED_CONDUIT_IN_AIR:  frozenset({"ambient_air", "grouping", "harmonic"}),
    # the insulation is IN the column (R-ADM-4); grouping is undefined (OI-4.8)
    A.INSULATION_PARTIAL:              frozenset({"ambient_air", "harmonic"}),
    A.INSULATION_COMPLETE:             frozenset({"ambient_air", "harmonic"}),
    A.INSULATION_PARTIAL_UNENCLOSED:   frozenset({"ambient_air", "harmonic"}),
    A.INSULATION_PARTIAL_ENCLOSED:     frozenset({"ambient_air", "harmonic"}),
    A.INSULATION_COMPLETE_UNENCLOSED:  frozenset({"ambient_air", "harmonic"}),
    A.INSULATION_COMPLETE_ENCLOSED:    frozenset({"ambient_air", "harmonic"}),
    A.BURIED_DIRECT: frozenset({"ambient_soil", "depth", "soil_resistivity",
                                "grouping", "harmonic"}),
    A.BURIED_CONDUIT_SHARED: frozenset({"ambient_soil", "depth",
                                        "soil_resistivity", "grouping", "harmonic"}),
    A.BURIED_CONDUIT_SINGLE_WAY: frozenset({"ambient_soil", "depth",
                                            "soil_resistivity", "grouping", "harmonic"}),
    A.BURIED_CONDUIT: frozenset({"ambient_soil", "depth", "soil_resistivity",
                                 "grouping", "harmonic"}),
}

#: Which depth table the arrangement uses. R-ADM-1: not interchangeable.
DEPTH_TABLE = {
    A.BURIED_DIRECT: "3.46",
    A.BURIED_CONDUIT_SHARED: "3.47",
    A.BURIED_CONDUIT_SINGLE_WAY: "3.47",
    A.BURIED_CONDUIT: "3.47",
}


def admit(arrangement: InstallationArrangement, family: str) -> None:
    """Raise unless `family` may be applied on top of `arrangement`."""
    allowed = ADMISSIBLE.get(arrangement)
    if allowed is None:
        raise InadmissibleFactor(
            f"no admissibility rule recorded for arrangement "
            f"{arrangement.value!r}")
    if family not in allowed:
        raise InadmissibleFactor(
            f"a {family!r} factor is inadmissible against arrangement "
            f"{arrangement.value!r}: that influence is already in the base "
            f"rating column. Admissible here: {sorted(allowed)}. "
            f"See M4 Rev B section 4.5.")


def build_factor_set(
    store: TableStore,
    cable: Cable,
    method: InstallationMethod,
    declared_as: DeclaredAs = DeclaredAs.TABULATED,
) -> FactorSet:
    """Assemble every applicable correction factor for one route segment.

    Five families exist, not seven: thermal insulation contact and solar
    radiation are base-rating COLUMNS, so a factor for either is rejected
    rather than defaulted to 1.00 (M4 Rev B finding 4).
    """
    if declared_as is DeclaredAs.DERATED:
        raise InvalidDeclaration(
            "Rating factors were requested for a capacity declared DERATED. "
            "A DERATED capacity already contains its factors; applying them "
            "again double-counts. See convention C1."
        )

    fs = FactorSet()
    max_c = cable.insulation.max_continuous_c
    arr = method.arrangement

    # -- ambient. The TABLE is chosen by arrangement, never by the caller:
    #    that is what stops an air cable being corrected off the soil datum
    #    (R-ADM-2).
    if arr.is_buried:
        admit(arr, "ambient_soil")
        fs.add(RatingFactor(
            name="ambient_soil",
            value=store.value("cf_ambient_soil",
                              max_conductor_c=max_c, ambient_c=method.ambient_c),
            source="AS/NZS 3008.1.1:2025 Table 3.45",
            key={"max_conductor_c": max_c, "ambient_c": method.ambient_c},
        ))
        admit(arr, "depth")
        fs.add(RatingFactor(
            name="depth_of_burial",
            value=store.value("cf_depth",
                              table=DEPTH_TABLE[arr],
                              axis_value=_depth_axis(arr, cable),
                              depth_m=method.depth_of_burial_m),
            source=f"AS/NZS 3008.1.1:2025 Table {DEPTH_TABLE[arr]}",
            key={"depth_m": method.depth_of_burial_m},
        ))
        admit(arr, "soil_resistivity")
        fs.add(RatingFactor(
            name="soil_thermal_resistivity",
            value=store.value(
                "cf_soil_resistivity",
                arrangement=arr,
                resistivity_km_w=method.soil_thermal_resistivity_km_w,
            ),
            source="AS/NZS 3008.1.1:2025 Table 3.48",
            key={"resistivity_km_w": method.soil_thermal_resistivity_km_w},
        ))
    else:
        admit(arr, "ambient_air")
        # No solar uplift. Where the cable is in the 3.9-3.20 family the
        # exposed-to-sun rating is the AIR_EXPOSED_TO_SUN base column, and the
        # ambient factor is entered at the MEASURED ambient (R-ADM-3).
        fs.add(RatingFactor(
            name="ambient_air",
            value=store.value("cf_ambient_air",
                              max_conductor_c=max_c, ambient_c=method.ambient_c),
            source="AS/NZS 3008.1.1:2025 Table 3.44",
            key={"max_conductor_c": max_c, "ambient_c": method.ambient_c},
        ))

    # -- grouping. Applied at ONE circuit too: a single circuit is not
    #    automatically 1.00, and the support type alone moves it 0.95 to 1.00
    #    (R-ADM-6, finding 5). Undefined against the insulation columns.
    if arr.in_thermal_insulation:
        if method.circuits_in_group > 1 or method.support_type is not SupportType.NONE:
            raise InadmissibleFactor(
                "no grouping table is nominated for cables surrounded by "
                "thermal insulation, so a grouping factor cannot be derived "
                "(OI-4.8). Declare support_type=NONE and a single circuit, or "
                "take the case to IEC 60287.")
    else:
        admit(arr, "grouping")
        fs.add(RatingFactor(
            name="grouping",
            value=store.value("cf_grouping",
                              grouping_code=method.grouping_code,
                              circuits=method.circuits_in_group),
            source="AS/NZS 3008.1.1:2025 Table 3.33/3.34/3.35",
            key={"grouping_code": method.grouping_code,
                 "circuits": method.circuits_in_group,
                 "support_type": method.support_type.value,
                 "circuit_spacing": method.circuit_spacing.value,
                 "rows": method.rows},
        ))

    return fs


def _depth_axis(arrangement: InstallationArrangement, cable: Cable) -> str:
    """R-ADM-1. Table 3.46 is keyed by size band, 3.47 by core count."""
    if DEPTH_TABLE[arrangement] == "3.46":
        return _size_band(cable.size_mm2)
    return ("multicore" if cable.construction is CableConstruction.MULTICORE
            else "single_core")
