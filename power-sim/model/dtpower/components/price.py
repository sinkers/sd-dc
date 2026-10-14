"""Price signal: $/MWh as a function of time of day.

Either a recorded NEM day (data/nem_prices.json, AEMO RRP at 30 minutes) or a
synthetic shape. ``at(t)`` is a step function: each interval holds its price,
the way the market settles it.
"""

from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

DATA = Path(__file__).resolve().parents[1] / "data" / "nem_prices.json"


@lru_cache(maxsize=1)
def nem_days() -> dict:
    return json.loads(DATA.read_text())


class PriceSignal:
    id = "price"
    label = "Spot price"

    def __init__(self, series: list[float], interval_min: float = 30, name: str = "", source: str = ""):
        if not series:
            raise ValueError("price series is empty")
        self.series = [float(v) for v in series]
        self.interval_min = interval_min
        self.name = name
        self.source = source

    def at(self, t: float) -> float:
        i = int(math.floor((t % 24) * 60 / self.interval_min + 1e-9))
        return self.series[i % len(self.series)]

    def forecast(self, dt: float, hours: float = 24, start_h: float = 0.0) -> list[float]:
        """The price at every step of a run: what a perfect-foresight controller sees."""
        return [self.at(start_h + i * dt) for i in range(round(hours / dt))]

    # ── sources ─────────────────────────────────────────────────────────────

    @classmethod
    def nem(cls, key: str) -> "PriceSignal":
        day = nem_days()["days"][key]
        return cls(day["rrp"], day["interval_min"], name=f"{day['region']} {day['date']}",
                   source=nem_days()["_provenance"]["source"])

    @classmethod
    def flat(cls, price: float) -> "PriceSignal":
        return cls([price], 24 * 60, name=f"Flat ${price:g}/MWh", source="synthetic")

    @classmethod
    def tou(cls, offpeak: float = 45, shoulder: float = 110, peak: float = 380,
            peak_hours: tuple[int, int] = (15, 21), shoulder_hours: tuple[int, int] = (7, 15)) -> "PriceSignal":
        """Time-of-use: off-peak overnight, shoulder through the day, peak in the evening."""
        series = []
        for h in range(24):
            if peak_hours[0] <= h < peak_hours[1]:
                series.append(peak)
            elif shoulder_hours[0] <= h < shoulder_hours[1]:
                series.append(shoulder)
            else:
                series.append(offpeak)
        return cls(series, 60, name="Time-of-use tariff", source="synthetic")

    def snapshot(self, t: float) -> dict:
        return {"price": self.at(t)}
