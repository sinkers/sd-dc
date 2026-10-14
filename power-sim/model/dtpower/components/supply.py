"""The condition of the grid supply over one time step, and the disturbances
that set it.

A voltage sag lasts milliseconds and a time step lasts a second or more, so a
sag is not sampled; it is an event with a depth and a duration. Each step,
``GridEvents.at(t, dt)`` reports the lowest voltage reached during the step and
how long the voltage spent below 90 % of nominal. Equipment decides from those
two numbers whether it rides through or trips, the way a protection relay or
a UPS input monitor does.

``Supply`` is truthy when the grid is connected at all. Code that only cares
about outages can keep treating it as a bool.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SAG_THRESHOLD_PCT = 90.0  # IEC 61000-4-30: a dip starts below 90 % of nominal


@dataclass(frozen=True)
class Supply:
    up: bool = True          # connected at all (False during an outage)
    v_pct: float = 100.0     # lowest residual voltage during the step, % of nominal
    dip_ms: float = 0.0      # time spent below 90 % during the step

    def __bool__(self) -> bool:
        return self.up


NORMAL = Supply()


def as_supply(x) -> Supply:
    """Accept a Supply, or a plain bool from code that predates disturbances."""
    return x if isinstance(x, Supply) else (NORMAL if x else Supply(up=False, v_pct=0.0))


@dataclass
class GridEvents:
    """Outages as [start_h, end_h] windows, sags as {t_h, residual_pct, duration_ms}."""

    outages: list = field(default_factory=list)
    sags: list = field(default_factory=list)

    def at(self, t: float, dt: float) -> Supply:
        if any(a <= t < b for a, b in self.outages):
            return Supply(up=False, v_pct=0.0, dip_ms=dt * 3.6e6)
        t1 = t + dt
        v, dip = 100.0, 0.0
        for s in self.sags:
            s0 = s["t"]
            s1 = s0 + s["duration_ms"] / 3.6e6
            overlap = min(t1, s1) - max(t, s0)
            if overlap > 0 or (s0 >= t and s0 < t1):
                v = min(v, s["residual_pct"])
                dip += max(overlap, 0.0) * 3.6e6
        return Supply(up=True, v_pct=v, dip_ms=dip) if v < 100.0 else NORMAL
