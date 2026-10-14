"""Standby generator behind an automatic transfer switch.

Rated in prime kVA with a power factor: kW available = prime kVA x pf.

Two reasons to run, each switchable:

``start on outage``
    The grid is lost; the set starts at once and takes the load after the
    start delay (cranking, run-up and the transfer switch). It then forms the
    bus on its own (islanded). When the grid has been healthy for the
    retransfer time, the switch transfers back. Open transition: the bus sees
    a short dead break, which a UPS without ride-through will see as a sag.

``start on price``
    The control system starts it whenever the spot price is at or above a
    threshold, and runs it in parallel with the grid to cut import. It runs
    at least the minimum run time once started, so it does not hunt on a
    price that hovers at the threshold.

After it stops carrying load it runs unloaded for the cool-down time and then
stops. Islanded, it trips if the load exceeds its overload limit; a trip needs
a manual reset, so it stays off for the rest of the run.

Fuel is litres per kWh carried, plus an idle burn whenever the set is turning,
which is enough to compare its running cost with the price it is offsetting.
The default 0.27 L/kWh is a typical diesel figure near full load, verified:
false. In parallel it carries at least its minimum load, because a diesel run
lightly loaded for hours wet-stacks; the network gives it that block before the
BESS, then the BESS, then the set again for anything left.

The network steps a generator in two calls: ``control()`` before the bus is
solved (is it online, and is it forming the bus or running in parallel?) and
``dispatch()`` after (how much it carries).
"""

from __future__ import annotations

from ..params import field, resolve
from .supply import Supply, as_supply

EPS = 1e-6


class Generator:
    id = "generator"
    label = "Generator"
    kind = "generator"
    role = "generator"
    ports = [{"name": "OUT", "medium": "ac_lv_3ph"}]
    schema = [
        field("enabled", "Enabled", kind="toggle", default=True),
        field("prime_kva", "Prime rating", default=250, unit="kVA", min=10, max=5000, step=5),
        field("pf", "Power factor", default=0.8, unit="", min=0.5, max=1.0, step=0.01,
              help="kW available is prime kVA times power factor."),
        field("start_on_outage", "Start immediately on grid outage", kind="toggle", default=True),
        field("start_delay_s", "Start delay", default=30, unit="s", min=0, max=300, step=1,
              help="From the start signal to the generator taking load: cranking, run-up and transfer."),
        field("retransfer_s", "Retransfer delay", default=120, unit="s", min=0, max=1800, step=10,
              help="How long the grid must be healthy before the load goes back to it."),
        field("transfer_ms", "Transfer break", default=100, unit="ms", min=0, max=2000, step=10, advanced=True,
              help="Dead time on the bus when an open-transition switch transfers back to the grid."),
        field("price_start", "Start on high price", kind="toggle", default=False,
              help="The control system runs the generator in parallel with the grid while the price is high."),
        field("price_threshold", "Start at or above price", default=500, unit="$/MWh", min=0, max=17500, step=10),
        field("min_run_min", "Minimum run time", default=30, unit="min", min=0, max=240, step=5, advanced=True),
        field("cooldown_s", "Cool-down", default=300, unit="s", min=0, max=1800, step=10, advanced=True),
        field("overload_pct", "Overload trip", default=110, unit="% of rating", min=100, max=150, step=1, advanced=True),
        field("min_load_pct", "Minimum load in parallel", default=30, unit="% of rating", min=0, max=80, step=5, advanced=True,
              help="A diesel set run lightly loaded for long wet-stacks, so in parallel it always carries at least this."),
        field("idle_fuel_pct", "Idle fuel burn", default=10, unit="% of full-load rate", min=0, max=40, step=1, advanced=True,
              help="Fuel burnt while running unloaded: starting, cooling down, or carrying little."),
        field("fuel_l_per_kwh", "Fuel use", default=0.27, unit="L/kWh", min=0.15, max=0.5, step=0.01, advanced=True),
        field("fuel_price", "Fuel price", default=2.0, unit="$/L", min=0.5, max=5.0, step=0.05, advanced=True),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.reset()

    def reset(self) -> None:
        self.state = "off" if self.p["enabled"] else "disabled"   # off|starting|running|cooldown|tripped|disabled
        self.reason = ""          # outage | price
        self.timer_s = 0.0        # time in the current state
        self.healthy_s = 0.0      # grid healthy while islanded
        self.run_s = 0.0          # time running on a price start
        self.islanded = False
        self.blip = False         # a transfer break this step
        self.kw = 0.0
        self.kwh = 0.0
        self.fuel_l = 0.0
        self.starts = 0
        self.trips = 0
        self.run_h = 0.0
        self.peak_kw = 0.0

    @property
    def rated_kw(self) -> float:
        return self.p["prime_kva"] * self.p["pf"]

    @property
    def online(self) -> bool:
        return self.state == "running"

    @property
    def fuel_cost(self) -> float:
        return self.fuel_l * self.p["fuel_price"]

    @property
    def cost_per_mwh(self) -> float:
        return self.p["fuel_l_per_kwh"] * self.p["fuel_price"] * 1000

    def _start(self, reason: str) -> None:
        self.state, self.reason, self.timer_s = "starting", reason, 0.0

    def control(self, t: float, dt: float, utility, price: float) -> None:
        """Advance the start/stop logic for this step, before the bus is solved."""
        p = self.p
        u = as_supply(utility)
        secs = dt * 3600
        self.blip = False
        if self.state in ("disabled", "tripped"):
            return
        wants_price = p["price_start"] and u.up and price >= p["price_threshold"]
        wants_outage = p["start_on_outage"] and not u.up

        if self.state == "off" or self.state == "cooldown":
            if wants_outage:
                if self.state == "cooldown":           # still turning: back on load at once
                    self.state, self.reason, self.islanded = "running", "outage", True
                    self.healthy_s = 0.0
                else:
                    self._start("outage")
                    self.starts += 1
            elif wants_price:
                if self.state == "cooldown":
                    self.state, self.reason, self.run_s = "running", "price", 0.0
                else:
                    self._start("price")
                    self.starts += 1
            elif self.state == "cooldown":
                self.timer_s += secs
                if self.timer_s >= p["cooldown_s"]:
                    self.state = "off"
            return

        if self.state == "starting":
            # A start whose reason has gone away before the set is on load is abandoned.
            if (self.reason == "outage" and u.up) or (self.reason == "price" and not wants_price and not wants_outage):
                self.state, self.timer_s = "cooldown", 0.0
                return
            self.timer_s += secs
            if self.timer_s >= p["start_delay_s"]:
                self.state, self.run_s, self.healthy_s = "running", 0.0, 0.0
                self.islanded = not u.up
            return

        # running
        if not u.up:
            if not self.islanded:              # grid lost while running in parallel: island now
                self.islanded, self.reason = True, "outage"
            self.healthy_s = 0.0
            return
        if self.islanded:
            self.healthy_s += secs
            if self.healthy_s >= p["retransfer_s"]:
                self.islanded, self.blip = False, p["transfer_ms"] > 0
                if wants_price:
                    self.reason, self.run_s = "price", 0.0
                else:
                    self.state, self.timer_s = "cooldown", 0.0
            return
        self.run_s += secs
        if not wants_price and self.run_s >= p["min_run_min"] * 60:
            self.state, self.timer_s = "cooldown", 0.0

    def bus_supply(self, utility) -> Supply:
        """What the bus sees this step, given the utility and this set."""
        u = as_supply(utility)
        if self.blip:
            return Supply(up=True, v_pct=0.0, dip_ms=self.p["transfer_ms"])
        if not u.up and self.online and self.islanded:
            return Supply()                    # the set forms the bus
        return u

    @property
    def min_load_kw(self) -> float:
        return self.rated_kw * self.p["min_load_pct"] / 100

    def _idle_fuel(self, dt: float) -> None:
        if self.state in ("starting", "running", "cooldown"):
            self.fuel_l += self.p["idle_fuel_pct"] / 100 * self.rated_kw * self.p["fuel_l_per_kwh"] * dt

    def dispatch(self, demand_kw: float, dt: float, add: bool = False) -> float:
        """Carry load. Islanded: all of it, or trip. In parallel: up to rating. Returns kW supplied.

        add=True tops up a block already dispatched this step (the parallel
        minimum load), rather than starting the step afresh."""
        if not add:
            self._idle_fuel(dt)
        if not self.online:
            self.kw = 0.0
            return 0.0
        if self.islanded:
            if demand_kw > self.rated_kw * self.p["overload_pct"] / 100 + EPS:
                self.state, self.trips, self.kw = "tripped", self.trips + 1, 0.0
                return 0.0
            out = max(0.0, demand_kw)
        else:
            room = self.rated_kw - (self.kw if add else 0.0)
            out = max(0.0, min(room, demand_kw))
        self.kw = (self.kw if add else 0.0) + out
        self.kwh += out * dt
        self.fuel_l += out * dt * self.p["fuel_l_per_kwh"]
        if not add:
            self.run_h += dt
        self.peak_kw = max(self.peak_kw, self.kw)
        return out

    def snapshot(self) -> dict:
        p = self.p
        remaining = 0.0
        if self.state == "starting":
            remaining = max(0.0, p["start_delay_s"] - self.timer_s)
        elif self.online and self.islanded and self.healthy_s > 0:
            remaining = max(0.0, p["retransfer_s"] - self.healthy_s)
        return {
            "enabled": p["enabled"],
            "state": self.state,
            "reason": self.reason,
            "islanded": self.islanded and self.online,
            "kw": self.kw,
            "rated_kw": self.rated_kw,
            "prime_kva": p["prime_kva"],
            "pf": p["pf"],
            "load_pct": self.kw / self.rated_kw * 100 if self.rated_kw else 0.0,
            "countdown_s": remaining,
            "kwh": self.kwh,
            "fuel_l": self.fuel_l,
            "fuel_cost": self.fuel_cost,
            "cost_per_mwh": self.cost_per_mwh,
            "run_h": self.run_h,
            "starts": self.starts,
            "trips": self.trips,
            "price_start": p["price_start"],
            "price_threshold": p["price_threshold"],
        }
