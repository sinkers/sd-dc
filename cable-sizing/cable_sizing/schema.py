"""Section 8 - data schema.

The dataclasses the rest of the package computes on. Everything that the
standard treats as a lookup key is an enum, so a typo is a TypeError at the
boundary rather than a MissingTableData three modules later.

Units are fixed and named in every field:
    length          metres              (_m)
    area            square millimetres  (_mm2)
    resistance      ohms per kilometre  (_ohm_per_km)
    current         amperes             (_a)
    voltage         volts               (_v)
    temperature     degrees Celsius     (_c)
    time            seconds             (_s)
    thermal resistivity  K.m/W          (_km_w)
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Sequence


# --------------------------------------------------------------------------
# Conductor and cable construction
# --------------------------------------------------------------------------

class ConductorMaterial(str, Enum):
    COPPER = "Cu"
    ALUMINIUM = "Al"


class ConductorForm(str, Enum):
    SOLID = "solid"
    STRANDED = "stranded"
    FLEXIBLE = "flexible"


class Insulation(str, Enum):
    """Insulation class keyed by (compound family, max continuous conductor temp).

    The family matters as well as the temperature, because the short-circuit
    limiting temperature in Table 5.2 is keyed on the family and on whether the
    conductor exceeds 300 mm^2 - thermoplastic only.
    """

    THERMOPLASTIC_75 = "PVC/75"
    THERMOPLASTIC_90 = "PVC/90"
    THERMOSETTING_90 = "XLPE/90"
    THERMOSETTING_110 = "EPR/110"

    @property
    def family(self) -> str:
        return "thermoplastic" if self.value.startswith("PVC") else "thermosetting"

    @property
    def max_continuous_c(self) -> float:
        return float(self.value.split("/")[1])


class Sheath(str, Enum):
    NONE = "none"
    PVC = "PVC"
    HDPE = "HDPE"
    LSZH = "LSZH"


class Armour(str, Enum):
    NONE = "none"
    STEEL_WIRE = "SWA"
    ALUMINIUM_WIRE = "AWA"
    SCREEN_ONLY = "screen"


class CableConstruction(str, Enum):
    """Governs which reactance table applies."""

    SINGLE_CORE_TREFOIL = "1c-trefoil"
    SINGLE_CORE_FLAT_TOUCHING = "1c-flat-touching"
    SINGLE_CORE_FLAT_SPACED = "1c-flat-spaced"
    MULTICORE = "multicore"


#: R-TBL-1. The base table is selected by (conductor grouping, insulation
#: material class), in that order. The insulation DESIGNATION fixes the material
#: class -- not the temperature the cable is marketed at.
#:
#:   conductor grouping      thermoplastic 75   XLPE 90   XLPE 110
#:   two single-core                 3.9          3.10       3.11
#:   three single-core               3.12         3.13       3.14
#:   2-core cable                    3.15         3.16       3.17
#:   3-core and 4-core cable         3.18         3.19       3.20
BASE_TABLE = {
    ("two_single_core", "thermoplastic_75"): "3.9",
    ("two_single_core", "xlpe_90"): "3.10",
    ("two_single_core", "xlpe_110"): "3.11",
    ("three_single_core", "thermoplastic_75"): "3.12",
    ("three_single_core", "xlpe_90"): "3.13",
    ("three_single_core", "xlpe_110"): "3.14",
    ("multicore_2", "thermoplastic_75"): "3.15",
    ("multicore_2", "xlpe_90"): "3.16",
    ("multicore_2", "xlpe_110"): "3.17",
    ("multicore_3_4", "thermoplastic_75"): "3.18",
    ("multicore_3_4", "xlpe_90"): "3.19",
    ("multicore_3_4", "xlpe_110"): "3.20",
}

def insulation_class(ins: "Insulation") -> str:
    """R-TBL-1. The DESIGNATION fixes the material class, not the marketed
    temperature. V-90 is thermoplastic and takes the thermoplastic table."""
    return {
        "PVC/75": "thermoplastic_75",
        "PVC/90": "thermoplastic_75",
        "XLPE/90": "xlpe_90",
        "EPR/110": "xlpe_110",
    }[ins.value]


def conductor_grouping(construction: "CableConstruction", cores_loaded: int) -> str:
    """Which row of the R-TBL-1 grid the cable sits in."""
    if construction is CableConstruction.MULTICORE:
        return "multicore_2" if cores_loaded <= 2 else "multicore_3_4"
    return "two_single_core" if cores_loaded <= 2 else "three_single_core"


def base_table(cable: "Cable") -> str:
    """The base rating table for a cable, per R-TBL-1."""
    key = (conductor_grouping(cable.construction, cable.cores_loaded),
           insulation_class(cable.insulation))
    try:
        return BASE_TABLE[key]
    except KeyError:
        raise InvalidInstallation(
            f"no base rating table for {key} (R-TBL-1)") from None


def arrangements_for(cable: "Cable") -> frozenset:
    """Which arrangements the cable's table family tabulates (R-ARR-1)."""
    return (MULTICORE_ARRANGEMENTS
            if cable.construction is CableConstruction.MULTICORE
            else SINGLE_CORE_ARRANGEMENTS)


#: Tables outside M4 scope. A request resolving here raises rather than falling
#: back to the a.c. family (R-TBL-3).
OUT_OF_SCOPE_TABLES = {
    "3.21": "d.c.", "3.22": "d.c.", "3.23": "d.c.", "3.24": "d.c.",
    "3.25": "d.c.", "3.26": "d.c.",
    "3.27": "flexible cords", "3.28": "high-temperature",
    "3.29": "MIMS", "3.30": "MIMS", "3.31": "aerial", "3.32": "aerial",
}


# --------------------------------------------------------------------------
# Installation
# --------------------------------------------------------------------------

class InstallationArrangement(str, Enum):
    """A column pair on a base rating table, M4 Rev B section 4.4.

    Not a free description of an installation. Each value names one column pair
    (Cu, Al) of Tables 3.9-3.20, and the mapping from a physical installation to
    one of these is Tables 3.5-3.8, held separately (R-ARR-2).

    Single-core tables carry four air arrangements; multicore tables carry
    three, having no `air_spaced_from_surface`, and split the thermal insulation
    block into unenclosed and enclosed (R-ARR-1).
    """

    # --- air, single-core and multicore ---------------------------------
    AIR_SPACED = "air_spaced"
    AIR_TOUCHING = "air_touching"
    AIR_EXPOSED_TO_SUN = "air_exposed_to_sun"
    ENCLOSED_CONDUIT_IN_AIR = "enclosed_conduit_in_air"
    # --- air, single-core only ------------------------------------------
    AIR_SPACED_FROM_SURFACE = "air_spaced_from_surface"
    # --- thermal insulation, single-core --------------------------------
    INSULATION_PARTIAL = "insulation_partial"
    INSULATION_COMPLETE = "insulation_complete"
    # --- thermal insulation, multicore ----------------------------------
    INSULATION_PARTIAL_UNENCLOSED = "insulation_partial_unenclosed"
    INSULATION_PARTIAL_ENCLOSED = "insulation_partial_enclosed"
    INSULATION_COMPLETE_UNENCLOSED = "insulation_complete_unenclosed"
    INSULATION_COMPLETE_ENCLOSED = "insulation_complete_enclosed"
    # --- buried ----------------------------------------------------------
    BURIED_DIRECT = "buried_direct"
    BURIED_CONDUIT_SHARED = "buried_conduit_shared"
    BURIED_CONDUIT_SINGLE_WAY = "buried_conduit_single_way"
    BURIED_CONDUIT = "buried_conduit"          # multicore, single pair

    @property
    def is_buried(self) -> bool:
        return self.value.startswith("buried")

    @property
    def in_thermal_insulation(self) -> bool:
        """Thermal insulation is a base-rating column, not a factor (finding 4)."""
        return self.value.startswith("insulation")

    @property
    def is_solar_exposed(self) -> bool:
        """Solar radiation is a base-rating column, not a factor (finding 4)."""
        return self is InstallationArrangement.AIR_EXPOSED_TO_SUN


#: Which arrangements each base-table family tabulates. A request for one the
#: family does not carry raises rather than resolving to a neighbour (R-ARR-1).
SINGLE_CORE_ARRANGEMENTS = frozenset({
    InstallationArrangement.AIR_SPACED,
    InstallationArrangement.AIR_SPACED_FROM_SURFACE,
    InstallationArrangement.AIR_TOUCHING,
    InstallationArrangement.AIR_EXPOSED_TO_SUN,
    InstallationArrangement.ENCLOSED_CONDUIT_IN_AIR,
    InstallationArrangement.INSULATION_PARTIAL,
    InstallationArrangement.INSULATION_COMPLETE,
    InstallationArrangement.BURIED_DIRECT,
    InstallationArrangement.BURIED_CONDUIT_SHARED,
    InstallationArrangement.BURIED_CONDUIT_SINGLE_WAY,
})

MULTICORE_ARRANGEMENTS = frozenset({
    InstallationArrangement.AIR_SPACED,
    InstallationArrangement.AIR_TOUCHING,
    InstallationArrangement.AIR_EXPOSED_TO_SUN,
    InstallationArrangement.ENCLOSED_CONDUIT_IN_AIR,
    InstallationArrangement.INSULATION_PARTIAL_UNENCLOSED,
    InstallationArrangement.INSULATION_PARTIAL_ENCLOSED,
    InstallationArrangement.INSULATION_COMPLETE_UNENCLOSED,
    InstallationArrangement.INSULATION_COMPLETE_ENCLOSED,
    InstallationArrangement.BURIED_DIRECT,
    InstallationArrangement.BURIED_CONDUIT,
})


class SupportType(str, Enum):
    """Table 3.34 axis. Required with no default: a single circuit is NOT 1.00
    (M4 Rev B finding 5) -- support type alone moves the factor 0.95 to 1.00."""

    UNPERFORATED_TRAY = "unperforated_tray"
    PERFORATED_TRAY = "perforated_tray"
    LADDER = "ladder"
    VERTICAL_PERFORATED_TRAY = "vertical_perforated_tray"
    #: not on a tray or support: Table 3.33 applies instead
    NONE = "none"


class CircuitSpacing(str, Enum):
    """Table 3.34 axis. Required input, not a default (R-GRP-1a). At two
    circuits touching and spaced differ by 4.5 %."""

    TOUCHING = "touching"
    SPACED = "spaced"


class SystemType(str, Enum):
    DC = "dc"
    SINGLE_PHASE_AC = "1ph"
    THREE_PHASE_AC = "3ph"

    @property
    def voltage_drop_multiplier(self) -> float:
        """Route factor in the voltage-drop expression."""
        return {"dc": 2.0, "1ph": 2.0, "3ph": 3 ** 0.5}[self.value]


class DeclaredAs(str, Enum):
    """How a current-carrying capacity figure handed to this package was derived.

    This is the single guard against double-counting derating factors. Any
    capacity entering the calculation must say which it is, and the two are
    handled on mutually exclusive paths:

      TABULATED  the raw table figure at the table's reference conditions.
                 Rating factors WILL be applied. This is the normal case.
      DERATED    a figure that already has rating factors folded in, e.g. a
                 manufacturer's or a previous calculation's I_z. Rating factors
                 are REFUSED - supplying any raises InvalidDeclaration.
    """

    TABULATED = "tabulated"
    DERATED = "derated"


@dataclass(frozen=True)
class InstallationMethod:
    """Everything about how one stretch of cable sits in the world."""

    arrangement: InstallationArrangement
    ambient_c: float
    #: Table 3.34 axes. support_type has NO default: a single circuit is not
    #: CF 1.00, and the support alone moves the factor 0.95 to 1.00 (finding 5).
    support_type: SupportType
    circuit_spacing: CircuitSpacing = CircuitSpacing.TOUCHING
    circuits_in_group: int = 1
    #: rows or tiers of trays or supports, Table 3.34 axis
    rows: int = 1
    #: which grouping table and item applies; see R-GRP notes
    grouping_code: str = "default"
    depth_of_burial_m: float | None = None
    soil_thermal_resistivity_km_w: float | None = None

    def __post_init__(self) -> None:
        if self.circuits_in_group < 1:
            raise InvalidInstallation("circuits_in_group must be >= 1")
        if self.rows < 1:
            raise InvalidInstallation("rows must be >= 1")
        # R-GRP-1. Table 3.34 tabulates no more than three circuits per tier.
        # A fourth is outside the table, not off the top of a band.
        if (self.support_type is not SupportType.NONE
                and self.circuits_in_group > 3):
            raise InvalidInstallation(
                f"{self.circuits_in_group} circuits per tier is outside Table "
                "3.34, which tabulates 1, 2 and 3 only (R-GRP-1). This case "
                "goes to IEC 60287 calculation, it does not extrapolate."
            )
        if self.support_type is not SupportType.NONE and self.rows > 3:
            raise InvalidInstallation(
                f"{self.rows} rows is outside Table 3.34, which tabulates "
                "1, 2 and 3 (R-GRP-1)."
            )
        if self.arrangement.is_buried and self.depth_of_burial_m is None:
            raise InvalidInstallation(
                f"{self.arrangement.value} requires depth_of_burial_m"
            )
        if self.arrangement.is_buried and self.soil_thermal_resistivity_km_w is None:
            raise InvalidInstallation(
                f"{self.arrangement.value} requires soil_thermal_resistivity_km_w"
            )


class InvalidInstallation(ValueError):
    pass


@dataclass(frozen=True)
class RouteSegment:
    length_m: float
    method: InstallationMethod
    label: str = ""


@dataclass(frozen=True)
class Route:
    """An ordered run of segments between origin and load.

    Two different rules apply along a route and they must not be conflated:

      * current-carrying capacity is governed by the WORST single segment,
        because the cable is a series element and its hottest point limits it;
      * voltage drop ACCUMULATES over every segment.
    """

    segments: Sequence[RouteSegment]

    def __post_init__(self) -> None:
        if not self.segments:
            raise InvalidInstallation("Route must have at least one segment")
        if any(s.length_m <= 0 for s in self.segments):
            raise InvalidInstallation("every segment length_m must be > 0")

    @property
    def total_length_m(self) -> float:
        return sum(s.length_m for s in self.segments)

    @classmethod
    def single(cls, length_m: float, method: InstallationMethod) -> "Route":
        return cls([RouteSegment(length_m=length_m, method=method)])


# --------------------------------------------------------------------------
# Cable
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Cable:
    material: ConductorMaterial
    insulation: Insulation
    construction: CableConstruction
    size_mm2: float
    cores_loaded: int
    form: ConductorForm = ConductorForm.STRANDED
    sheath: Sheath = Sheath.PVC
    armour: Armour = Armour.NONE
    #: parallel identical cables per phase
    parallel_sets: int = 1
    #: protective earthing conductor size, if it runs with this cable
    pe_size_mm2: float | None = None
    pe_material: ConductorMaterial | None = None

    def __post_init__(self) -> None:
        if self.size_mm2 <= 0:
            raise ValueError("size_mm2 must be > 0")
        if self.parallel_sets < 1:
            raise ValueError("parallel_sets must be >= 1")
        if self.cores_loaded < 1:
            raise ValueError("cores_loaded must be >= 1")

    def with_size(self, size_mm2: float) -> "Cable":
        from dataclasses import replace

        return replace(self, size_mm2=size_mm2)


# --------------------------------------------------------------------------
# Load and protection
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Load:
    """The electrical demand the circuit has to carry."""

    design_current_a: float          # I_b, fundamental phase current
    system: SystemType
    nominal_voltage_v: float         # line-to-line for 3ph, line-to-neutral for 1ph
    power_factor: float = 0.9
    #: third-harmonic content of the phase current, as a fraction (0.0 - 1.0)
    third_harmonic_fraction: float = 0.0
    #: allowable voltage drop, fraction of nominal (AS/NZS 3000 default 5 %)
    max_voltage_drop_fraction: float = 0.05

    def __post_init__(self) -> None:
        if not 0.0 <= self.power_factor <= 1.0:
            raise ValueError("power_factor must be in [0, 1]")
        if not 0.0 <= self.third_harmonic_fraction <= 1.0:
            raise ValueError("third_harmonic_fraction must be in [0, 1]")
        if self.design_current_a <= 0:
            raise ValueError("design_current_a must be > 0")

    @property
    def sin_phi(self) -> float:
        return (1.0 - self.power_factor ** 2) ** 0.5


class DeviceType(str, Enum):
    MCB_B = "MCB-B"
    MCB_C = "MCB-C"
    MCB_D = "MCB-D"
    MCCB = "MCCB"
    FUSE_GG = "fuse-gG"
    HRC = "HRC"


@dataclass(frozen=True)
class Protection:
    device: DeviceType
    rating_a: float                  # I_n
    #: prospective fault current at the origin of the circuit
    prospective_fault_current_a: float
    #: clearing time at that fault current
    clearing_time_s: float
    #: I_2, the current guaranteeing operation in conventional time.
    #: Left None for devices where the standard's 1.45 I_z rule is applied via
    #: the device's own declared factor - see select_conductor.
    fusing_current_a: float | None = None
    #: maximum disconnection time permitted for this circuit (AS/NZS 3000)
    max_disconnection_time_s: float = 0.4
    #: external earth fault loop impedance upstream of this circuit
    external_loop_impedance_ohm: float = 0.0


@dataclass
class CheckResult:
    """Uniform result object. Every check returns one of these."""

    name: str
    passed: bool
    governing_value: float
    limit: float
    units: str
    detail: dict = field(default_factory=dict)

    @property
    def margin(self) -> float:
        """Positive means headroom."""
        return self.limit - self.governing_value

    def __str__(self) -> str:
        verdict = "PASS" if self.passed else "FAIL"
        return (
            f"[{verdict}] {self.name}: {self.governing_value:.4g} "
            f"vs limit {self.limit:.4g} {self.units}"
        )
