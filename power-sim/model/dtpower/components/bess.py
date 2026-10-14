"""BESS: a Battery behind a bidirectional Converter, with its own auxiliary load
(HVAC, BMS, controls) and an operating mode.

``step(request_kw, dt, grid_up)`` takes an AC set-point from a controller
(positive = discharge onto the bus, negative = charge from it) and returns the
net AC power it actually exchanged, auxiliaries included.

It is grid-following: when the grid is lost it trips on anti-islanding. A
voltage sag trips it too, unless **fault ride-through** (LVRT) is on and the sag
is inside the ride-through envelope. After a trip it waits for the grid to be
healthy for the **reconnect** time, then ramps its power limit back up at the
**reconnect ramp** rate. AS/NZS 4777.2 sets both for inverters in Australia;
the defaults here are its figures as commonly quoted, verified: false. A
grid-forming BESS would be a different component, not a flag on this one.
"""

from __future__ import annotations

from ..params import field, override, prefixed, resolve, unprefix
from .battery import Battery
from .converter import Converter
from .supply import SAG_THRESHOLD_PCT, as_supply

MODES = [
    {"value": "auto", "label": "Auto (follow controller)"},
    {"value": "idle", "label": "Hold"},
    {"value": "charge", "label": "Force charge"},
    {"value": "discharge", "label": "Force discharge"},
]

EPS = 1e-6


class BESS:
    id = "bess"
    label = "Battery energy storage"
    # Not an IndustroML kind yet: the schema has no bess, battery or inverter.
    kind = "bess"
    kind_proposed = True
    role = "storage"
    ports = [{"name": "AC", "medium": "ac_lv_3ph"}, {"name": "CTRL", "medium": "ethernet_rj45", "domain": "data"}]
    schema = [
        field("enabled", "Enabled", kind="toggle", default=True),
        field("mode", "Mode", kind="select", default="auto", options=MODES),
        *override(Battery.schema, {"capacity_kwh": {"label": "Energy capacity"}}),
        *prefixed(override(Converter.schema, {"rated_kw": {"label": "Power rating (PCS)"}}), "pcs"),
        field("aux_kw", "Auxiliary load", default=2, unit="kW", min=0, max=50, step=0.5, advanced=True,
              help="HVAC, BMS and controls, drawn whenever the BESS is enabled and the grid is up."),
        field("lvrt", "Fault ride-through (LVRT)", kind="toggle", default=True,
              help="On: stays connected through sags inside the envelope below. Off: any sag trips it."),
        field("lvrt_floor_pct", "Ride-through floor", default=50, unit="% of nominal", min=0, max=90, step=1),
        field("lvrt_ms", "Ride-through time", default=1000, unit="ms", min=0, max=5000, step=10),
        field("reconnect_s", "Reconnect delay", default=60, unit="s", min=0, max=600, step=5,
              help="Healthy grid needed after a trip before it reconnects."),
        field("ramp_pct_per_min", "Reconnect ramp", default=16.67, unit="% of rating per min", min=1, max=100, step=0.01,
              advanced=True, help="Power limit rise after reconnecting."),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.battery = Battery(self.p)
        self.pcs = Converter(unprefix(self.p, "pcs"))
        self.reset()

    def reset(self) -> None:
        self.battery.reset()
        self.ac_kw = 0.0
        self.request_kw = 0.0
        self.status = "idle" if self.p["enabled"] else "disabled"
        self.tripped = False
        self.healthy_s = 0.0            # healthy grid since the trip
        self.since_reconnect_s = 1e9    # long ago: no ramp limit at the start
        self.trips = 0
        self.trip_cause = ""

    def trips_on(self, supply) -> bool:
        s = as_supply(supply)
        if not s.up:
            return True
        if s.v_pct >= SAG_THRESHOLD_PCT:
            return False
        p = self.p
        return not (p["lvrt"] and s.v_pct >= p["lvrt_floor_pct"] and s.dip_ms <= p["lvrt_ms"])

    def power_limit_kw(self) -> float:
        """Rating, or less while ramping back after a reconnect."""
        ramp = self.p["ramp_pct_per_min"] / 100 * self.since_reconnect_s / 60
        return self.rated_kw * min(1.0, ramp)

    @property
    def rated_kw(self) -> float:
        return self.pcs.p["rated_kw"]

    def step(self, request_kw: float, dt: float, grid_up=True) -> float:
        p = self.p
        secs = dt * 3600
        if p["enabled"] and self.trips_on(grid_up):
            if not self.tripped:
                self.trips += 1
            s = as_supply(grid_up)
            self.tripped, self.healthy_s = True, 0.0
            self.trip_cause = "grid lost" if not s.up else f"sag to {s.v_pct:.0f} %"
        elif self.tripped:
            self.healthy_s += secs
            if self.healthy_s >= p["reconnect_s"]:
                self.tripped, self.since_reconnect_s = False, 0.0

        if not p["enabled"] or self.tripped:
            self.battery.exchange(0.0, dt)
            self.ac_kw = 0.0
            self.request_kw = 0.0
            self.status = ("reconnecting" if self.healthy_s > 0 else "tripped") if p["enabled"] else "disabled"
            return 0.0
        self.since_reconnect_s += secs

        want = {"idle": 0.0, "charge": -self.rated_kw, "discharge": self.rated_kw}.get(p["mode"], request_kw)
        self.request_kw = want
        lim = self.power_limit_kw()
        want = max(-lim, min(lim, want))
        dc = self.battery.exchange(self.pcs.dc_for_ac(self.pcs.limit_ac(want)), dt)
        delivered = self.pcs.ac_for_dc(dc)
        self.ac_kw = delivered - self.pcs.p["no_load_kw"] - p["aux_kw"]

        if delivered > EPS:
            self.status = "discharging"
        elif delivered < -EPS:
            self.status = "charging"
        elif want > EPS:
            self.status = "empty"
        elif want < -EPS:
            self.status = "full"
        else:
            self.status = "idle"
        return self.ac_kw

    def snapshot(self) -> dict:
        b = self.battery
        return {
            "enabled": self.p["enabled"],
            "mode": self.p["mode"],
            "status": self.status,
            "ac_kw": self.ac_kw,
            "request_kw": self.request_kw,
            "rated_kw": self.rated_kw,
            "capacity_kwh": b.p["capacity_kwh"],
            "duration_h": b.p["capacity_kwh"] / self.rated_kw,
            "soc_min_pct": b.p["soc_min_pct"],
            "soc_max_pct": b.p["soc_max_pct"],
            "power_limit_kw": self.power_limit_kw() if not self.tripped else 0.0,
            "reconnect_remaining_s": max(0.0, self.p["reconnect_s"] - self.healthy_s) if self.tripped else 0.0,
            "trips": self.trips,
            "trip_cause": self.trip_cause,
            "lvrt": self.p["lvrt"],
            **b.snapshot(),
        }
