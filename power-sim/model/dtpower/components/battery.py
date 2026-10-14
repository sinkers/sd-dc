"""Battery: the cells only, measured at their DC terminals.

No converter and no controls. BESS and UPS each wrap one of these; so will the
bidirectional UPS in the next simulation.

``exchange(kw, dt)``: kw > 0 discharges (energy leaves the terminals), kw < 0
charges. The request is clamped to the C-rate and to the SoC window, and the
power actually exchanged is returned.
"""

from __future__ import annotations

import math

from ..engine import clamp
from ..params import field, resolve


class Battery:
    schema = [
        field("capacity_kwh", "Usable capacity", default=400, unit="kWh", min=10, max=4000, step=10),
        field("soc_init_pct", "Starting state of charge", default=50, unit="%", min=0, max=100, step=1),
        field("soc_min_pct", "Minimum SoC", default=10, unit="%", min=0, max=50, step=1),
        field("soc_max_pct", "Maximum SoC", default=95, unit="%", min=50, max=100, step=1),
        field("max_c_rate", "Maximum C-rate", default=0.5, unit="C", min=0.1, max=10, step=0.05,
              help="Power limit as a multiple of capacity. 0.5C empties the battery in two hours."),
        field("cell_rte_pct", "Cell round-trip efficiency", default=95, unit="%", min=70, max=100, step=0.5, advanced=True),
        field("self_discharge_pct_day", "Self-discharge", default=0.1, unit="%/day", min=0, max=5, step=0.05, advanced=True),
        field("wear_cost_per_mwh", "Wear cost", default=25, unit="$/MWh out", min=0, max=200, step=1, advanced=True,
              help="Degradation charged per MWh discharged: pack cost over lifetime MWh. An assumption, not a datasheet figure."),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.reset()

    def reset(self) -> None:
        p = self.p
        self.energy_kwh = clamp(p["soc_init_pct"], 0, 100) / 100 * p["capacity_kwh"]
        self.charged_kwh = 0.0     # into the terminals
        self.discharged_kwh = 0.0  # out of the terminals
        self.last_kw = 0.0

    @property
    def eta(self) -> float:
        """One-way efficiency, the round trip split evenly."""
        return math.sqrt(self.p["cell_rte_pct"] / 100)

    @property
    def soc(self) -> float:
        return self.energy_kwh / self.p["capacity_kwh"]

    @property
    def max_kw(self) -> float:
        return self.p["max_c_rate"] * self.p["capacity_kwh"]

    def limits(self, dt: float) -> tuple[float, float]:
        """(max discharge kW, max charge kW) at the terminals for a step of dt."""
        p = self.p
        above = max(0.0, self.energy_kwh - p["soc_min_pct"] / 100 * p["capacity_kwh"])
        below = max(0.0, p["soc_max_pct"] / 100 * p["capacity_kwh"] - self.energy_kwh)
        return (min(self.max_kw, above * self.eta / dt),
                min(self.max_kw, below / self.eta / dt))

    def exchange(self, kw: float, dt: float) -> float:
        max_dis, max_chg = self.limits(dt)
        actual = clamp(kw, -max_chg, max_dis)
        if actual > 0:
            self.energy_kwh -= actual * dt / self.eta
            self.discharged_kwh += actual * dt
        elif actual < 0:
            self.energy_kwh += -actual * dt * self.eta
            self.charged_kwh += -actual * dt
        self.energy_kwh -= self.energy_kwh * self.p["self_discharge_pct_day"] / 100 * dt / 24
        self.energy_kwh = clamp(self.energy_kwh, 0.0, self.p["capacity_kwh"])
        self.last_kw = actual
        return actual

    @property
    def equivalent_cycles(self) -> float:
        return self.discharged_kwh / self.p["capacity_kwh"]

    @property
    def wear_cost(self) -> float:
        return self.discharged_kwh / 1000 * self.p["wear_cost_per_mwh"]

    def snapshot(self) -> dict:
        return {
            "soc_pct": self.soc * 100,
            "energy_kwh": self.energy_kwh,
            "dc_kw": self.last_kw,
            "c_rate": abs(self.last_kw) / self.p["capacity_kwh"],
            "cycles": self.equivalent_cycles,
            "wear_cost": self.wear_cost,
        }
