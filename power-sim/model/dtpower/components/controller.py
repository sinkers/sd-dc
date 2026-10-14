"""Demand-response controller: turns a price into a BESS set-point.

Two strategies:

``threshold``
    Charge while the price is at or below one level, discharge while it is at
    or above another. What a simple site controller does. Needs no forecast.

``optimal``
    Perfect foresight over the day. Dynamic programming over state of charge
    finds the charge / hold / discharge sequence at full power that earns the
    most against the day's prices, after converter and cell losses and wear.
    Energy left in the battery at midnight is valued at the day's median
    price, so the plan cannot profit by simply emptying the battery. It is a
    benchmark for what arbitrage could have earned, not a controller you could
    deploy. It plans at full power on a grid of SoC levels, so where the site
    holds discharge below full power it can trail a well-tuned threshold rule
    by a few percent.

Either way, the controller keeps a reserve: it never discharges below
``reserve_pct``, so there is always some energy left for resilience. It never
charges harder than the grid connection has headroom for, and with export off it
never discharges more than the site is drawing.

Peak shaving runs on top of either strategy. With it on, whenever the site
would draw more than ``site_max_demand_kw`` the BESS discharges the excess,
whatever the price, down to the battery's own minimum rather than the reserve:
holding a demand limit is one of the things the reserve is for. Charging is
held under the limit too. This is how the BESS can absorb a UPS's recharge
after a disturbance without the site setting a new peak.
"""

from __future__ import annotations

from ..params import field, resolve
from .bess import BESS

STRATEGIES = [
    {"value": "threshold", "label": "Price thresholds"},
    {"value": "optimal", "label": "Optimal schedule (perfect foresight)"},
]


class PriceController:
    id = "controller"
    label = "Demand response"
    kind = "plc"
    role = "controller"
    ports = [{"name": "NET", "medium": "ethernet_rj45", "domain": "data"}]
    schema = [
        field("strategy", "Strategy", kind="select", default="threshold", options=STRATEGIES),
        field("charge_below", "Recharge when price is at or below", default=80, unit="$/MWh", min=-1000, max=1000, step=5),
        field("discharge_above", "Discharge when price is at or above", default=250, unit="$/MWh", min=0, max=15000, step=10,
              help="Used by the price-threshold strategy. The optimal strategy ignores both thresholds."),
        field("reserve_pct", "Reserve kept for resilience", default=20, unit="% SoC", min=0, max=100, step=1),
        field("peak_shave", "Hold site to max demand", kind="toggle", default=False,
              help="The BESS discharges whenever the site would draw more than the limit, whatever the price."),
        field("site_max_demand_kw", "Site max demand", default=300, unit="kW", min=10, max=10000, step=5),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.plan: list[int] | None = None
        self.table: list[list[int]] | None = None
        self.decision = "hold"

    def prepare(self, forecast: list[float], bess: BESS, dt: float, levels: int = 161) -> None:
        """Build the optimal plan for a day: +1 discharge, -1 charge, 0 hold, per step."""
        self.plan = self.table = None
        if self.p["strategy"] != "optimal" or not forecast:
            return
        b, pcs = bess.battery, bess.pcs
        cap = b.p["capacity_kwh"]
        lo = max(b.p["soc_min_pct"], self.p["reserve_pct"]) / 100 * cap
        hi = b.p["soc_max_pct"] / 100 * cap
        if hi <= lo:
            return
        h = (hi - lo) / (levels - 1)
        rated = min(bess.rated_kw, b.max_kw * pcs.eta)
        gain = rated * dt * pcs.eta * b.eta          # cell energy added per charging step
        loss = rated * dt / pcs.eta / b.eta          # cell energy removed per discharging step
        mwh = rated * dt / 1000                      # AC energy per step
        wear = b.p["wear_cost_per_mwh"] * (rated / pcs.eta) * dt / 1000
        up, dn = max(1, round(gain / h)), max(1, round(loss / h))

        n = len(forecast)
        median = sorted(forecast)[n // 2]
        value = [(lo + k * h) * b.eta * pcs.eta / 1000 * median for k in range(levels)]
        choice = []
        for i in range(n - 1, -1, -1):
            px = forecast[i]
            nxt, act = [0.0] * levels, [0] * levels
            for k in range(levels):
                # Ties go to acting now rather than later: if the site draws less
                # than the rated power the battery runs slower than planned, and
                # acting early leaves time to finish.
                best, a = value[k], 0
                if k - dn >= 0 and value[k - dn] + px * mwh - wear >= best - 1e-9:
                    best, a = value[k - dn] + px * mwh - wear, 1
                if k + up < levels and value[k + up] - px * mwh > best + 1e-9:
                    best, a = value[k + up] - px * mwh, -1
                elif k + up < levels and a == 0 and value[k + up] - px * mwh >= best - 1e-9:
                    best, a = value[k + up] - px * mwh, -1
                nxt[k], act[k] = best, a
            value = nxt
            choice.append(act)
        choice.reverse()

        # Keep the whole table, not one path through it: the controller looks up
        # the best action for the state of charge the battery is actually at,
        # so it recovers when reality departs from the plan (a discharge held
        # back to the site's draw, a step clipped by the connection).
        self.table, self.grid = choice, (lo, h, levels)
        self.plan = self._path(b.energy_kwh, up, dn)

    def _level(self, energy_kwh: float) -> int:
        lo, h, levels = self.grid
        return min(levels - 1, max(0, round((energy_kwh - lo) / h)))

    def _path(self, energy_kwh: float, up: int, dn: int) -> list[int]:
        """The plan as it would run if every step went exactly as modelled."""
        k, plan = self._level(energy_kwh), []
        for act in self.table:
            a = act[k]
            plan.append(a)
            k += up if a < 0 else -dn if a > 0 else 0
        return plan

    def decide(self, price: float, step: int, dt: float, bess: BESS, site_kw: float,
               grid_capacity_kw: float, export_allowed: bool) -> float:
        p = self.p
        if self.table is not None:
            action = self.table[step][self._level(bess.battery.energy_kwh)] if step < len(self.table) else 0
        elif price >= p["discharge_above"]:
            action = 1
        elif price <= p["charge_below"]:
            action = -1
        else:
            action = 0

        rated = bess.rated_kw
        b = bess.battery
        own_draw = bess.p["aux_kw"] + bess.pcs.p["no_load_kw"]
        shave = 0.0
        if p["peak_shave"]:
            shave = max(0.0, site_kw + own_draw - p["site_max_demand_kw"])
            grid_capacity_kw = min(grid_capacity_kw, p["site_max_demand_kw"])

        above_reserve = b.energy_kwh - p["reserve_pct"] / 100 * b.p["capacity_kwh"]
        if action > 0 and above_reserve > 1e-9:
            self.decision = "discharge"
            limit = min(rated, bess.pcs.ac_for_dc(above_reserve * b.eta / dt))
            if not export_allowed:
                limit = min(limit, site_kw + own_draw)
            return max(0.0, limit, min(rated, shave))
        if shave > 1e-9:
            self.decision = "peak shave"
            return min(rated, shave)
        if action < 0:
            self.decision = "charge"
            headroom = grid_capacity_kw - site_kw - own_draw
            return -max(0.0, min(rated, headroom))
        self.decision = "hold"
        return 0.0

    def snapshot(self) -> dict:
        return {"decision": self.decision, "strategy": self.p["strategy"]}
