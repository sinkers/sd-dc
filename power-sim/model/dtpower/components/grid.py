"""Grid connection: a capacity limit, a price, and a running bill.

``step(net_kw, price, dt, grid_up)``: net_kw > 0 imports from the grid,
net_kw < 0 exports to it. Import pays spot plus a flat network-and-retail adder.
Export, where allowed, earns spot (and pays it when spot is negative).

Demand charges are not modelled yet, and neither is reactive power: everything
here is kW at unity power factor.
"""

from __future__ import annotations

from ..engine import dollars
from ..params import field, resolve


class Grid:
    id = "grid"
    label = "Grid connection"
    kind = "utility_supply"
    role = "source"
    ports = [{"name": "OUT", "medium": "ac_lv_3ph"}]
    schema = [
        field("capacity_kw", "Connection capacity", default=400, unit="kW", min=50, max=10000, step=10),
        field("adder_per_mwh", "Network and retail adder", default=40, unit="$/MWh", min=0, max=300, step=1,
              help="Added to spot on every MWh imported. Flat, so it does not change what arbitrage earns."),
        field("export_allowed", "Export allowed", kind="toggle", default=False,
              help="Off: the BESS discharges no more than the site is drawing. On: it may push power into the grid."),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.reset()

    def reset(self) -> None:
        self.import_kw = 0.0
        self.export_kw = 0.0
        self.price = 0.0
        self.up = True
        self.v_pct = 100.0
        self.dip_ms = 0.0
        self.cost = 0.0
        self.import_kwh = 0.0
        self.export_kwh = 0.0
        self.peak_import_kw = 0.0
        self.over_capacity_steps = 0

    def step(self, net_kw: float, price: float, dt: float, grid_up=True) -> float:
        self.price, self.up = price, bool(grid_up)
        self.v_pct = getattr(grid_up, "v_pct", 100.0 if grid_up else 0.0)
        self.dip_ms = getattr(grid_up, "dip_ms", 0.0)
        if not grid_up:
            self.import_kw = self.export_kw = 0.0
            return 0.0
        self.import_kw = max(0.0, net_kw)
        self.export_kw = max(0.0, -net_kw) if self.p["export_allowed"] else 0.0
        self.cost += dollars(self.import_kw * dt, price + self.p["adder_per_mwh"])
        self.cost -= dollars(self.export_kw * dt, price)
        self.import_kwh += self.import_kw * dt
        self.export_kwh += self.export_kw * dt
        self.peak_import_kw = max(self.peak_import_kw, self.import_kw)
        if self.import_kw > self.p["capacity_kw"] + 1e-6:
            self.over_capacity_steps += 1
        return self.import_kw - self.export_kw

    def snapshot(self) -> dict:
        return {
            "up": self.up,
            "v_pct": self.v_pct,
            "dip_ms": self.dip_ms,
            "price": self.price,
            "import_kw": self.import_kw,
            "export_kw": self.export_kw,
            "capacity_kw": self.p["capacity_kw"],
            "utilisation_pct": self.import_kw / self.p["capacity_kw"] * 100,
            "over_capacity": self.import_kw > self.p["capacity_kw"] + 1e-6,
            "cost": self.cost,
            "import_kwh": self.import_kwh,
            "export_kwh": self.export_kwh,
        }
