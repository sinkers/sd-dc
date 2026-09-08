"""The simulation engine: the ROM plus mode control and a command queue.

Deliberately free of transport concerns — no sockets, no asyncio. `advance()`
takes an elapsed simulated time and steps; the caller decides whether that came
from a wall clock (the service) or a loop counter (tests and replay). That is
what makes the twin's behaviour reproducible in a unit test.

Modes
-----
manual  the operator sets the B300 rack load directly (one figure for all of
        them, plus optional per-rack overrides)
auto    a seeded training-run profile drives the B300 racks; the operator can
        still override individual racks and all the cooling-side controls

In both modes the non-B300 racks (network, spine, storage) sit at their design
load — they are not part of the training job.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .model import HallModel, Inputs, Observables, State
from .params import RomParams
from .profiles import ProfileConfig, ProfileSample, TrainingRunProfile
from .topology import HallSpec

DRIVEN_CLASSES = ("b300",)


@dataclass
class Snapshot:
    """One published instant of the twin."""

    t: float
    speed: float
    mode: str
    state: State
    obs: Observables
    profile: ProfileSample | None
    verdict: str
    verdict_reason: str
    inputs: Inputs
    extras: dict = field(default_factory=dict)


class SimEngine:
    def __init__(
        self,
        spec: HallSpec,
        params: RomParams | None = None,
        dt: float = 0.5,
        speed: float = 1.0,
        mode: str = "auto",
        seed: int = 0,
        profile_config: ProfileConfig | None = None,
    ):
        self.spec = spec
        self.model = HallModel(spec, params or RomParams.load())
        self.dt = float(dt)
        self.speed = float(speed)
        self.mode = self._check_mode(mode)

        self.driven = [
            i for i, r in enumerate(spec.racks) if r.rack_class in DRIVEN_CLASSES
        ]
        self.driven_names = [spec.racks[i].name for i in self.driven]
        self._design_kw = np.array([r.design_kw for r in spec.racks])
        self.b300_setpoint_kw = float(
            self._design_kw[self.driven].max() if self.driven else 0.0
        )
        self.overrides: dict[str, float] = {}

        self.profile = TrainingRunProfile(
            len(self.driven), profile_config, seed=seed
        )
        self.last_profile: ProfileSample | None = None

        self.inputs = Inputs.design(spec)
        self.state = self.model.initial_state(self.inputs)
        self._accumulator = 0.0
        self._apply_loads()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def _check_mode(mode: str) -> str:
        if mode not in ("auto", "manual"):
            raise ValueError(f"unknown mode {mode!r}; expected 'auto' or 'manual'")
        return mode

    def _apply_loads(self) -> None:
        """Recompute every rack's load from mode, setpoint, profile and overrides."""
        kw = self._design_kw.copy()
        if self.driven:
            if self.mode == "auto" and self.last_profile is not None:
                peak = self._design_kw[self.driven]
                kw[self.driven] = self.last_profile.utilisation * peak
            else:
                kw[self.driven] = self.b300_setpoint_kw
        for name, value in self.overrides.items():
            kw[self.spec.rack_names.index(name)] = value
        self.inputs.rack_kw = np.clip(kw, 0.0, None)

    # -- stepping ------------------------------------------------------------
    def advance(self, sim_seconds: float) -> Snapshot:
        """Advance the twin by `sim_seconds` of simulated time."""
        self._accumulator += max(0.0, sim_seconds)
        obs = None
        while self._accumulator >= self.dt:
            self._accumulator -= self.dt
            if self.mode == "auto":
                self.last_profile = self.profile.advance(self.dt)
            self._apply_loads()
            self.state, obs = self.model.step(self.state, self.inputs, self.dt)
        if obs is None:
            _, obs = self.model.evaluate(self.state, self.inputs)
        return self.snapshot(obs)

    def snapshot(self, obs: Observables | None = None) -> Snapshot:
        if obs is None:
            _, obs = self.model.evaluate(self.state, self.inputs)
        verdict, reason = self.model.verdict(obs)
        return Snapshot(
            t=self.state.t,
            speed=self.speed,
            mode=self.mode,
            state=self.state,
            obs=obs,
            profile=self.last_profile if self.mode == "auto" else None,
            verdict=verdict,
            verdict_reason=reason,
            inputs=self.inputs,
            extras={"b300_setpoint_kw": self.b300_setpoint_kw},
        )

    def settle(self, seconds: float = 4000.0) -> Snapshot:
        """Run the hall to equilibrium at its current inputs before publishing, so
        a viewer connecting does not watch it warm up from a cold start.

        The cap is generous because the binding constraint is the lightest-loaded
        rack's thermal time constant (a 15 kW storage rack takes ~1250 s of
        simulated time to settle), and the whole solve costs under 300 ms.
        """
        # In auto mode, establish the profile's opening load first, so the hall
        # settles at the load the run actually starts from rather than at design
        # load — otherwise the first published frame shows a hall still hot from
        # settling while the job is only just ramping up.
        if self.mode == "auto" and self.last_profile is None:
            self.last_profile = self.profile.advance(self.dt)
            self._apply_loads()
        state, obs = self.model.steady_state(
            self.inputs, dt=1.0, tol=1e-5, max_time=seconds, state=self.state
        )
        self.state = state
        return self.snapshot(obs)

    # -- commands ------------------------------------------------------------
    def set_mode(self, mode: str) -> None:
        mode = self._check_mode(mode)
        if mode == "auto" and self.mode != "auto":
            self.profile.reset()
            self.last_profile = None
        self.mode = mode
        self._apply_loads()

    def set_load(self, target: str, kw: float) -> None:
        """`target` is "global" (all B300 racks) or a rack name."""
        if kw < 0:
            raise ValueError("kw must be >= 0")
        if target == "global":
            self.b300_setpoint_kw = float(kw)
            # An explicit load command is a manual act; honour it even if the
            # profile was driving, rather than having it silently overwritten on
            # the next tick.
            if self.mode == "auto":
                self.set_mode("manual")
        elif target in self.spec.rack_names:
            self.overrides[target] = float(kw)
        else:
            raise ValueError(f"unknown load target {target!r}")
        self._apply_loads()

    def clear_override(self, target: str) -> None:
        self.overrides.pop(target, None)
        self._apply_loads()

    def set_unit(self, unit: str, on: bool) -> None:
        if unit not in self.spec.module_names:
            raise ValueError(f"unknown fan wall module {unit!r}")
        self.inputs.unit_on[self.spec.module_names.index(unit)] = bool(on)

    def set_unit_airflow(self, unit: str, fraction: float) -> None:
        if unit not in self.spec.module_names:
            raise ValueError(f"unknown fan wall module {unit!r}")
        if not 0.0 <= fraction <= 1.2:
            raise ValueError("airflow fraction must be within 0..1.2")
        self.inputs.airflow_fraction[self.spec.module_names.index(unit)] = float(
            fraction
        )

    def set_supply_temp(self, celsius: float) -> None:
        if not 5.0 <= celsius <= 40.0:
            raise ValueError("supply temperature must be within 5..40 C")
        self.inputs.supply_temp_c = float(celsius)

    def set_speed(self, x: float) -> None:
        if not 0.0 <= x <= 200.0:
            raise ValueError("speed must be within 0..200")
        self.speed = float(x)

    def configure_auto(
        self, seed: int | None = None, config: ProfileConfig | None = None
    ) -> None:
        self.profile = TrainingRunProfile(
            len(self.driven),
            config or self.profile.config,
            seed=self.profile.seed if seed is None else int(seed),
        )
        self.last_profile = None
        self._apply_loads()
