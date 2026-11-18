"""Fixed-step time runner, and the conventions every component follows.

Units, everywhere in this package:
    power kW, energy kWh, time hours, price AUD/MWh, money AUD.

Sign convention: a component's ``ac_kw`` is positive when it supplies the bus it
sits on and negative when it draws from it. A battery's ``dc_kw`` is positive
when it discharges.

The runner is deliberately tiny. Topology, and the order in which components
are stepped, belong to each simulation, not to the engine.
"""

from __future__ import annotations

from typing import Callable


def run(step: Callable[[float, float, int], dict], hours: float = 24.0, dt_min: float = 5.0,
        start_h: float = 0.0) -> list[dict]:
    """Step from start_h for `hours`. dt_min may be a fraction: 1/60 is one second."""
    dt = dt_min / 60.0
    n = round(hours / dt)
    return [step(start_h + i * dt, dt, i) for i in range(n)]


def dollars(kwh: float, price_per_mwh: float) -> float:
    return kwh / 1000.0 * price_per_mwh


def clamp(v: float, lo: float, hi: float) -> float:
    return min(hi, max(lo, v))


def clock(t_hours: float, seconds: bool = False) -> str:
    """'13:05', or '13:05:07' with seconds, from hours since midnight."""
    if seconds:
        s = round(t_hours * 3600) % 86400
        return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"
    m = round(t_hours * 60) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"
