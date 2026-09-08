"""Calibration parameters for the ROM.

Everything here is a fitted or estimated coefficient — nothing geometric
(that lives in `topology.HallSpec`). Split into two groups:

Fitted against steady CFD (`calibrate.py`):
    supply_reach, zone_coupling, fan_flow_multiplier, recirc_*, peak_multiplier

Estimated from physical reasoning, NOT identifiable from steady CFD:
    thermal_mass_kj_per_k, rack_ua_kw_per_k, coil_tau_s, return_mix_factor

The second group sets how fast the twin responds to a load step. Steady-state
CFD carries no information about it, so those values are engineering estimates
and the transient behaviour is "plausible physics", not validated physics. This
is called out in docs/ROM.md and in the README's scope limits.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

DEFAULT_PARAMS_FILE = Path(__file__).with_name("params_default.json")
CALIBRATED_PARAMS_FILE = Path(__file__).with_name("params_calibrated.json")


@dataclass
class RomParams:
    # -- airflow distribution ------------------------------------------------
    # Fraction of a module's discharge that reaches the near half of the pod;
    # the remainder carries to the far half. 0.5 = perfectly mixed hall.
    supply_reach: float = 0.72
    # How freely surplus cold air migrates from a surplus zone to a starved one
    # before the starved zone is forced to pull from the hot aisle. 0 = zones
    # isolated, 1 = the cold side is one perfectly shared plenum.
    zone_coupling: float = 0.5

    # Corrects nameplate volumetric flow to the mass flow the fan wall actually
    # delivers. The CFD sets a velocity boundary condition and realises 84.78
    # kg/s where nameplate volume at supply-air density gives 81.4 — a 4%
    # difference in its supply-patch density convention. Fitting it here keeps
    # the ROM's mass balance aligned with the CFD it is calibrated against
    # without corrupting the underlying "a fan moves volume" physics.
    module_flow_multiplier: float = 1.0

    # -- rack fans -----------------------------------------------------------
    # Racks move more air than the design-dT relation implies (the CFD shows
    # +4..46%); one global multiplier on m = Q/(cp dT).
    fan_flow_multiplier: float = 1.20
    # Airflow at zero IT load, as a fraction of design flow (fans never stop).
    fan_flow_floor: float = 0.25
    # Time constant of the rack fans' response to a load change.
    #
    # Real server fan controllers track component temperature, not power draw:
    # when a GPU goes idle the fans do not step down with it, they coast and then
    # ramp as the heatsinks cool. Modelling airflow as instantaneous in load makes
    # a load drop look far worse than it is — the fans collapse while the metal is
    # still hot, so the exhaust temperature spikes hard (40 -> 54 C on a checkpoint
    # dip) before decaying. A first-order lag is the minimum honest fix; it is not
    # a real fan control law, and the value is an estimate, not a measurement.
    fan_tau_s: float = 25.0

    # -- containment gap / recirculation ------------------------------------
    # Baseline recirculation fraction by position in the row, present even when
    # the hall is oversupplied: aisle-end racks mix with hot air regardless.
    # Keyed "end" (first/last), "next" (second/second-last), "mid" (the rest).
    # 3 positional parameters rather than 24 per-rack ones: better conditioned
    # against 4 CFD variants, and it transfers to a hall with a different rack
    # count. Per-rack overrides are available for known outliers.
    recirc_baseline: dict[str, float] = field(
        default_factory=lambda: {"end": 0.105, "next": 0.010, "mid": 0.003}
    )
    recirc_baseline_override: dict[str, float] = field(default_factory=dict)
    # How a zone-level supply deficit converts into rack-level recirculation:
    #
    #     phi = baseline + recirc_gain * deficit_fraction ** recirc_exponent
    #
    # This is the coefficient the fan-speed lever runs entirely through, so it
    # deserves the detail. An exponent of 1.0 is the naive linear reading — the
    # shortfall is made up one-for-one from the hot aisle. The single-cabinet fan
    # wall sweep (RESULTS.md, six points from 68% to 127% of demand) says the
    # relationship saturates: the per-point gain runs 0.95, 1.25, 1.62 as the
    # deficit shrinks. Fitting gain and exponent together lands on 0.63 / 0.634
    # and reduces the RMS error in phi by 18x versus linear.
    #
    # This matters where it counts. Near the balance point — exactly where you
    # would sit if you turned the fans down to save energy — the linear form is
    # optimistic by about 0.8 K of intake temperature. A model used to justify a
    # turndown should not be optimistic there.
    recirc_gain: float = 0.63
    recirc_exponent: float = 0.634
    max_recirc_fraction: float = 0.95

    # -- hot spots -----------------------------------------------------------
    # Peak face temperature is much more recirculation-sensitive than the mean:
    # phi_peak = clip(peak_multiplier * phi_mean). Fitted to the CFD's
    # inletTmax channels.
    peak_multiplier: float = 6.0

    # -- transient response (ESTIMATED, not CFD-identifiable) ---------------
    # The rack's metal-to-air conductance is sized from the temperature
    # difference the heatsinks run at design load: UA = P_design / dT_metal.
    # 25 K is a reasonable mean heatsink-to-air difference for a dense air-cooled
    # rack (heatsinks ~60 C, air ~35 C). Sizing UA this way rather than picking a
    # number keeps it scaled to the rack, and it does not disturb the steady
    # state at all: at equilibrium the air carries exactly P regardless of UA.
    rack_metal_delta_t_k: float = 25.0
    # Thermal mass of the metal actually in the air path — heatsinks and the
    # boards they sit on, not the chassis steel, which is largely thermally
    # isolated from the airflow. With the UA above this gives a rack time
    # constant of roughly a minute, which is the right order for a load step.
    thermal_mass_kj_per_k: dict[str, float] = field(
        default_factory=lambda: {
            "default": 100.0,
            "b300": 110.0,
            "hd": 100.0,
            "ib_leaf": 90.0,
            "ib_spine": 95.0,
            "ethernet": 40.0,
            "net": 55.0,
            "storage": 80.0,
            "spare": 5.0,
        }
    )
    # Chilled-water coil lag on the supply air temperature.
    coil_tau_s: float = 45.0
    # Scales the effective return-path mixing volume (transport delay from the
    # hot aisle back to the unit intakes).
    return_mix_factor: float = 1.0

    # -- misc ----------------------------------------------------------------
    idle_power_fraction: float = 0.08  # rack draw at idle, fraction of design

    def thermal_mass(self, rack_class: str) -> float:
        """Thermal mass [kJ/K] for a rack class, falling back to default."""
        return self.thermal_mass_kj_per_k.get(
            rack_class, self.thermal_mass_kj_per_k["default"]
        )

    def baseline_recirc(self, name: str, position: int, n_positions: int) -> float:
        if name in self.recirc_baseline_override:
            return self.recirc_baseline_override[name]
        last = n_positions - 1
        if position in (0, last):
            key = "end"
        elif position in (1, last - 1):
            key = "next"
        else:
            key = "mid"
        return self.recirc_baseline[key]

    # -- serialisation -------------------------------------------------------
    def to_json(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(asdict(self), indent=2) + "\n")

    @classmethod
    def from_json(cls, path: str | Path) -> "RomParams":
        data = json.loads(Path(path).read_text())
        data.pop("_comment", None)
        return cls(**data)

    @classmethod
    def load(cls, path: str | Path | None = None) -> "RomParams":
        """Load calibrated params if present, else the committed defaults."""
        if path is not None:
            return cls.from_json(path)
        if CALIBRATED_PARAMS_FILE.exists():
            return cls.from_json(CALIBRATED_PARAMS_FILE)
        if DEFAULT_PARAMS_FILE.exists():
            return cls.from_json(DEFAULT_PARAMS_FILE)
        return cls()
