"""AUTO mode: a synthetic transformer training-run power profile.

What a large training job looks like from the electrical/thermal side, which is
what the twin needs to show:

  ramp        job launches; ranks come up staggered over a minute or two and
              climb to their sustained utilisation
  sustained   the long steady grind at 92-98% utilisation, with correlated
              jitter — GPUs across a job breathe together because they are
              synchronised by collectives, so the noise has a shared component
              as well as a per-rack one
  checkpoint  periodic sharp dips: compute pauses while state is written, so
              power drops hard for tens of seconds and steps back
  eval        occasional longer, deeper dips for evaluation passes
  straggler   rare: one rack falls behind or a rank restarts. That rack drops to
              idle while everyone else stalls at reduced utilisation waiting on
              the collective — the whole job's power sags, not just one rack's

Everything is seeded: same seed, same run, so a scenario is reproducible and a
demo can be replayed. Nothing here touches wall-clock time or global RNG state.

Timescales are compressed by default (checkpoints every few minutes rather than
every half hour) so a viewer sees the full character of a training run inside a
few minutes. `ProfileConfig` exposes all of it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

import numpy as np

PHASES = ("ramp", "sustained", "checkpoint", "eval", "straggler")


@dataclass
class ProfileConfig:
    # ramp
    ramp_s: float = 90.0
    stagger_s: float = 45.0
    # sustained
    sustained_util: float = 0.95
    jitter_sigma: float = 0.025  # std dev of the utilisation jitter
    jitter_tau_s: float = 8.0  # correlation time of that jitter
    shared_jitter_fraction: float = 0.6  # how much of it is hall-wide
    # checkpointing
    checkpoint_interval_s: float = 300.0
    checkpoint_jitter_s: float = 60.0
    checkpoint_duration_s: float = 35.0
    checkpoint_util: float = 0.30
    # evaluation passes, expressed as every Nth checkpoint becoming an eval
    eval_every_n_checkpoints: int = 4
    eval_duration_s: float = 180.0
    eval_util: float = 0.15
    # stragglers / restarts
    straggler_rate_per_hour: float = 3.0
    straggler_duration_s: float = 120.0
    straggler_peer_util: float = 0.70
    # floors
    idle_util: float = 0.08

    def validate(self) -> None:
        if not 0.0 < self.sustained_util <= 1.0:
            raise ValueError("sustained_util must be in (0, 1]")
        if self.checkpoint_interval_s <= self.checkpoint_duration_s:
            raise ValueError("checkpoint_interval_s must exceed its duration")
        if self.idle_util < 0.0:
            raise ValueError("idle_util must be >= 0")
        for name in ("ramp_s", "jitter_tau_s", "straggler_duration_s"):
            if getattr(self, name) <= 0.0:
                raise ValueError(f"{name} must be positive")


@dataclass
class ProfileSample:
    t: float
    phase: str
    progress: float  # 0..1 through the current phase
    utilisation: np.ndarray  # per driven rack
    mean_utilisation: float
    straggler: int | None
    checkpoints: int
    evals: int


class TrainingRunProfile:
    """Deterministic given (n_racks, config, seed)."""

    def __init__(self, n_racks: int, config: ProfileConfig | None = None, seed: int = 0):
        self.n = int(n_racks)
        self.config = config or ProfileConfig()
        self.config.validate()
        self.seed = int(seed)
        self.rng = np.random.Generator(np.random.PCG64(self.seed))
        self.reset()

    # -- lifecycle -----------------------------------------------------------
    def reset(self) -> None:
        c = self.config
        self.t = 0.0
        self.phase = "ramp"
        self.phase_t = 0.0
        self.phase_len = c.ramp_s
        self.checkpoints = 0
        self.evals = 0
        self.straggler: int | None = None
        self._jitter_shared = 0.0
        self._jitter_own = np.zeros(self.n)
        # each rack starts its ramp at a slightly different moment
        self._start_offset = self.rng.uniform(0.0, c.stagger_s, self.n)
        self._schedule_next_checkpoint()

    def _schedule_next_checkpoint(self) -> None:
        c = self.config
        jitter = self.rng.uniform(-c.checkpoint_jitter_s, c.checkpoint_jitter_s)
        self._next_checkpoint_t = self.t + max(
            c.checkpoint_duration_s * 2.0, c.checkpoint_interval_s + jitter
        )

    # -- integration ---------------------------------------------------------
    def advance(self, dt: float) -> ProfileSample:
        if dt <= 0:
            raise ValueError("dt must be positive")
        c = self.config
        self.t += dt
        self.phase_t += dt

        self._advance_jitter(dt)
        self._advance_phase(dt)

        base = self._base_utilisation()
        shared = c.shared_jitter_fraction * self._jitter_shared
        own = (1.0 - c.shared_jitter_fraction) * self._jitter_own
        util = np.clip(base * (1.0 + shared + own), c.idle_util, 1.0)

        if self.phase == "straggler" and self.straggler is not None:
            util[self.straggler] = c.idle_util

        return ProfileSample(
            t=self.t,
            phase=self.phase,
            progress=(
                min(1.0, self.phase_t / self.phase_len) if self.phase_len > 0 else 1.0
            ),
            utilisation=util,
            mean_utilisation=float(util.mean()),
            straggler=self.straggler,
            checkpoints=self.checkpoints,
            evals=self.evals,
        )

    def _advance_jitter(self, dt: float) -> None:
        """Ornstein-Uhlenbeck noise: correlated in time, unlike white noise, so
        the racks visibly breathe rather than flicker."""
        c = self.config
        decay = np.exp(-dt / c.jitter_tau_s)
        scale = c.jitter_sigma * np.sqrt(1.0 - decay**2)
        self._jitter_shared = self._jitter_shared * decay + scale * self.rng.normal()
        self._jitter_own = self._jitter_own * decay + scale * self.rng.normal(
            size=self.n
        )

    def _advance_phase(self, dt: float) -> None:
        c = self.config
        if self.phase in ("checkpoint", "eval", "straggler"):
            if self.phase_t >= self.phase_len:
                self._enter("sustained", 0.0)
                self.straggler = None
            return

        if self.phase == "ramp":
            if self.phase_t >= self.phase_len:
                self._enter("sustained", 0.0)
            return

        # sustained: checkpoints are scheduled, stragglers are a Poisson process
        if self.t >= self._next_checkpoint_t:
            self.checkpoints += 1
            self._schedule_next_checkpoint()
            if (
                c.eval_every_n_checkpoints > 0
                and self.checkpoints % c.eval_every_n_checkpoints == 0
            ):
                self.evals += 1
                self._enter("eval", c.eval_duration_s)
            else:
                self._enter("checkpoint", c.checkpoint_duration_s)
            return

        p_straggler = c.straggler_rate_per_hour * dt / 3600.0
        if self.n > 0 and self.rng.random() < p_straggler:
            self.straggler = int(self.rng.integers(self.n))
            self._enter("straggler", c.straggler_duration_s)

    def _enter(self, phase: str, length: float) -> None:
        self.phase = phase
        self.phase_t = 0.0
        self.phase_len = length

    def _base_utilisation(self) -> np.ndarray:
        c = self.config
        if self.phase == "ramp":
            # staggered S-curve: each rack starts at its own offset
            local = np.clip((self.t - self._start_offset) / c.ramp_s, 0.0, 1.0)
            s = local * local * (3.0 - 2.0 * local)  # smoothstep
            return c.idle_util + (c.sustained_util - c.idle_util) * s
        if self.phase == "checkpoint":
            return np.full(self.n, c.checkpoint_util)
        if self.phase == "eval":
            return np.full(self.n, c.eval_util)
        if self.phase == "straggler":
            return np.full(self.n, c.straggler_peer_util)
        return np.full(self.n, c.sustained_util)

    # -- reporting -----------------------------------------------------------
    def describe(self) -> dict:
        return {
            "seed": self.seed,
            "phase": self.phase,
            "checkpoints": self.checkpoints,
            "evals": self.evals,
            "straggler": self.straggler,
            "config": asdict(self.config),
        }
