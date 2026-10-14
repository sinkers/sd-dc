"""UPS: rectifier, DC link with a Battery, inverter, and a static bypass.

``step(load_kw, dt, supply)`` serves the load and returns what the UPS draws
from its input bus: the load, plus the UPS's own losses, plus battery recharge.

Input disturbances. The UPS watches its input. When the voltage falls outside
its input window it transfers the load to the battery. With **ride-through**
on, a sag that is short enough and shallow enough is carried on the DC link
instead, and the battery is never called on. With it off, any sag below the
window transfers. Either way, once the UPS is on battery it stays there until
the input has been healthy for the **resync** time. Then the rectifier walks
the load back onto the grid over the **walk-in** time, and the battery
recharges. Recharge is capped by the **max demand** setting: it only gets the
headroom between what the load draws and that limit, so the recharge never
pushes the UPS input above it.

This UPS is one-directional: its battery only ever feeds its own output. The
next simulation swaps the rectifier for a bidirectional Converter so the battery
can also export to the input bus. That is the case for retiring the BESS.
"""

from __future__ import annotations

import math

from ..params import field, override, resolve
from .battery import Battery
from .supply import as_supply

# Losses as a fraction of rated power: k0 + k1*x + k2*x^2, x = load / rating.
# Shaped to give about 96 % at full load and 94-95 % at quarter load in double
# conversion, and about 99 % in eco mode. That is the usual shape of published
# curves, not any one vendor's. verified: false.
LOSS = {
    "double-conversion": (0.010, 0.010, 0.020),
    "eco": (0.003, 0.002, 0.005),
}
BYPASS_LOSS = 0.002  # static switch, fraction of load
EPS = 1e-6

TOPOLOGIES = [
    {"value": "double-conversion", "label": "Double conversion (online)"},
    {"value": "eco", "label": "Eco mode (bypass, inverter on standby)"},
]


class UPS:
    id = "ups"
    label = "UPS"
    kind = "ups"
    role = "conversion"
    ports = [{"name": "IN", "medium": "ac_lv_3ph"}, {"name": "OUT", "medium": "ac_lv_3ph"}]
    schema = [
        field("rated_kw", "UPS rating", default=250, unit="kW", min=20, max=3000, step=10),
        field("topology", "Operating mode", kind="select", default="double-conversion", options=TOPOLOGIES),
        field("ride_through", "Ride through input sags", kind="toggle", default=True,
              help="On: short, shallow sags are carried on the DC link and the battery is not used. "
                   "Off: any sag below the input window transfers the load to battery."),
        field("input_window_pct", "Input window, lower limit", default=85, unit="% of nominal", min=50, max=95, step=1,
              help="Below this the input is out of tolerance."),
        field("ride_through_ms", "Ride-through time", default=500, unit="ms", min=0, max=5000, step=10,
              help="With ride-through on, sags shorter than this stay on the grid."),
        field("ride_through_floor_pct", "Ride-through floor", default=50, unit="% of nominal", min=0, max=90, step=1,
              help="With ride-through on, sags deeper than this transfer anyway."),
        field("resync_s", "Resync time", default=60, unit="s", min=0, max=900, step=5,
              help="How long the input must be healthy before the UPS takes the load back from the battery."),
        field("walk_in_s", "Walk-in time", default=10, unit="s", min=0, max=120, step=1, advanced=True,
              help="The rectifier ramps the load back onto the grid over this time; the battery covers the rest."),
        field("recharge_pct", "Battery recharge rate", default=10, unit="% of rating", min=1, max=50, step=1),
        field("max_demand_enabled", "Limit UPS input to max demand", kind="toggle", default=False),
        field("max_demand_kw", "UPS max demand", default=200, unit="kW", min=20, max=3000, step=5,
              help="Recharge only uses the headroom below this. The load itself is never limited."),
        *override(Battery.schema, {
            "capacity_kwh": {"label": "UPS battery capacity", "default": 45, "min": 5, "max": 1000, "step": 5},
            "soc_init_pct": {"default": 100},
            "soc_min_pct": {"default": 5},
            "soc_max_pct": {"default": 100},
            "max_c_rate": {"default": 6},
            "cell_rte_pct": {"default": 92},
            "wear_cost_per_mwh": {"default": 0},
        }, omit=("self_discharge_pct_day",)),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.battery = Battery({**self.p, "self_discharge_pct_day": 0})
        self.reset()

    def reset(self) -> None:
        self.battery.reset()
        self.input_kw = self.output_kw = self.loss_kw = 0.0
        self.unserved_kw = self.unserved_kwh = 0.0
        self.demand_kw = 0.0
        self.recharge_kw = 0.0
        self.recharge_limited = False
        self.status = "online"
        self.mode = "normal"            # normal | battery | walk-in
        self.healthy_s = 0.0            # time the input has been good, while on battery
        self.walk_s = 0.0
        self.cause = ""                 # why the UPS last went to battery
        self.transfers = 0
        self.on_battery_s = 0.0
        self.min_soc_pct = self.battery.soc * 100
        self.peak_input_kw = 0.0
        self.over_demand_s = 0.0

    def loss_kw_at(self, load_kw: float) -> float:
        k0, k1, k2 = LOSS[self.p["topology"]]
        x = load_kw / self.p["rated_kw"]
        return self.p["rated_kw"] * (k0 + k1 * x + k2 * x * x)

    def input_trips(self, supply) -> bool:
        """Does this step's supply push the input out of tolerance?"""
        s = as_supply(supply)
        p = self.p
        if not s.up:
            return True
        if s.v_pct >= p["input_window_pct"]:
            return False
        if p["ride_through"] and s.dip_ms <= p["ride_through_ms"] and s.v_pct >= p["ride_through_floor_pct"]:
            return False
        return True

    def _advance_mode(self, supply, dt: float) -> None:
        s = as_supply(supply)
        secs = dt * 3600
        if self.input_trips(s):
            if self.mode != "battery":
                self.transfers += 1
            self.mode, self.healthy_s = "battery", 0.0
            self.cause = "grid lost" if not s.up else f"sag to {s.v_pct:.0f} %"
            return
        if self.mode == "battery":
            self.healthy_s += secs
            if self.healthy_s >= self.p["resync_s"]:
                self.mode, self.walk_s = "walk-in", 0.0
        elif self.mode == "walk-in":
            self.walk_s += secs
            if self.walk_s >= self.p["walk_in_s"]:
                self.mode = "normal"

    def step(self, load_kw: float, dt: float, grid_up=True) -> float:
        p = self.p
        self.demand_kw = load_kw
        self._advance_mode(grid_up, dt)
        overload = load_kw > p["rated_kw"]
        self.recharge_kw, self.recharge_limited = 0.0, False

        if self.mode == "normal" and overload:
            # The static bypass carries the load straight from the input: no
            # conditioning and no ride-through until the load falls back.
            self.battery.exchange(0.0, dt)
            self.status = "bypass"
            self.loss_kw = BYPASS_LOSS * load_kw
            self.output_kw, self.unserved_kw = load_kw, 0.0
            self.input_kw = load_kw + self.loss_kw
            return self._account(dt)

        loss = self.loss_kw_at(min(load_kw, p["rated_kw"]))
        need = load_kw + loss
        share = {"normal": 1.0, "battery": 0.0}.get(
            self.mode, min(1.0, self.walk_s / p["walk_in_s"]) if p["walk_in_s"] > 0 else 1.0)
        from_grid = need * share
        from_batt = need - from_grid

        if from_batt > EPS:
            max_dis, _ = self.battery.limits(dt)
            if overload or max_dis < from_batt:
                # End of discharge (or an overload with no bypass to go to).
                self.battery.exchange(0.0, dt)
                self.status, self.loss_kw = "load dropped", 0.0
                self.output_kw, self.unserved_kw = 0.0, load_kw
                self.unserved_kwh += load_kw * dt
                self.input_kw = 0.0
                return self._account(dt)
            self.battery.exchange(from_batt, dt)
            self.on_battery_s += dt * 3600
            if self.mode == "battery":
                self.status = "on battery" if self.healthy_s == 0 else "resync"
            else:
                self.status = "walk-in"
        else:
            # On the grid: recharge into whatever headroom max demand leaves.
            want = p["recharge_pct"] / 100 * p["rated_kw"]
            allowed = want
            if p["max_demand_enabled"]:
                allowed = max(0.0, min(want, p["max_demand_kw"] - from_grid))
            got = -self.battery.exchange(-allowed, dt)
            _, can_take = self.battery.limits(dt)
            self.recharge_kw = got
            self.recharge_limited = allowed < want - EPS and (can_take > EPS or got > EPS)
            self.status = "recharging" if got > 0.05 else ("eco" if p["topology"] == "eco" else "online")

        self.loss_kw = loss
        self.output_kw, self.unserved_kw = load_kw, 0.0
        self.input_kw = from_grid + self.recharge_kw
        return self._account(dt)

    def _account(self, dt: float) -> float:
        self.min_soc_pct = min(self.min_soc_pct, self.battery.soc * 100)
        self.peak_input_kw = max(self.peak_input_kw, self.input_kw)
        if self.p["max_demand_enabled"] and self.input_kw > self.p["max_demand_kw"] + EPS:
            self.over_demand_s += dt * 3600
        return self.input_kw

    def autonomy_min(self, load_kw: float) -> float:
        """Minutes the battery would carry this load, from where it is now."""
        b = self.battery
        usable = max(0.0, b.energy_kwh - b.p["soc_min_pct"] / 100 * b.p["capacity_kwh"]) * b.eta
        draw = load_kw + self.loss_kw_at(load_kw)
        return usable / draw * 60 if draw > 0 else math.inf

    def snapshot(self) -> dict:
        out = self.output_kw
        p = self.p
        return {
            "status": self.status,
            "mode": self.mode,
            "cause": self.cause,
            "topology": p["topology"],
            "rated_kw": p["rated_kw"],
            "input_kw": self.input_kw,
            "output_kw": out,
            "loss_kw": self.loss_kw,
            "load_pct": out / p["rated_kw"] * 100,
            "eff_pct": out / (out + self.loss_kw) * 100 if out > 0 else 0.0,
            "unserved_kw": self.unserved_kw,
            "unserved_kwh": self.unserved_kwh,
            "autonomy_min": min(self.autonomy_min(self.demand_kw), 9999.0),
            "battery_soc_pct": self.battery.soc * 100,
            "battery_kwh": self.battery.p["capacity_kwh"],
            "recharge_kw": self.recharge_kw,
            "recharge_limited": self.recharge_limited,
            "resync_remaining_s": max(0.0, p["resync_s"] - self.healthy_s) if self.mode == "battery" else 0.0,
            "max_demand_kw": p["max_demand_kw"] if p["max_demand_enabled"] else None,
            "ride_through": p["ride_through"],
            "transfers": self.transfers,
            "on_battery_s": self.on_battery_s,
        }
