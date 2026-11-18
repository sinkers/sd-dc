"""Run a simulation from an IndustroML-shaped model.

A model is the same four lists IndustroML uses — assets, interfaces,
connections (containers are not needed here). Each asset's ``kind`` picks its
component from ``components.REGISTRY``, and its ``attributes.simulation`` holds
that component's parameters. Cables say which asset feeds which, from the
supply end (``from``) to the load end (``to``). A ``data_link`` from a
controller to a storage asset says who sets that asset's power.

Radial networks only, rooted at a single source. That covers a site's point
of connection; a meshed or dual-path network is a later problem, and the
place it will be solved is here, not in the components.

Step order, each time step:

    0. work out the grid's condition for the step (outage, voltage sag);
    1. walk down the tree from the source, and back up it:
         loads report their demand,
         conversions (UPS) turn output demand into input demand,
         at each bus, the passive children are summed first, then each storage
         child's controller decides a set-point knowing what the bus draws;
    2. the source takes whatever is left.

Telemetry: pass ``measurements={asset_id: fn(t) -> dict}`` and any asset with a
measurement at time t is handed it through ``observe()`` instead of being
modelled. This is the seam for running the same network against a live site.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from .components import REGISTRY, PriceSignal
from .components.supply import GridEvents
from .engine import clock, run


@dataclass
class Node:
    id: str
    name: str
    comp: object
    children: list["Node"] = field(default_factory=list)
    controller: object | None = None
    generators: list["Node"] = field(default_factory=list)   # alternate supplies, via a transfer switch

    @property
    def role(self) -> str:
        return self.comp.role


class ModelError(ValueError):
    pass


def interfaces_for(asset_id: str, cls) -> list[dict]:
    """IndustroML interfaces for an asset, from its component's port list."""
    out = []
    for port in cls.ports:
        out.append({"id": f"{asset_id}.{port['name']}", "asset": asset_id, "name": port["name"],
                    "domain": port.get("domain", "electrical"), "medium": port["medium"]})
    return out


class Network:
    def __init__(self, model: dict, price: PriceSignal, outages: list | None = None, sags: list | None = None,
                 measurements: dict[str, Callable[[float], dict | None]] | None = None,
                 overrides: dict[str, dict] | None = None):
        self.model = model
        self.price = price
        self.events = GridEvents(outages or [], sags or [])
        self.measurements = measurements or {}
        overrides = overrides or {}

        self.nodes: dict[str, Node] = {}
        for a in model["assets"]:
            cls = REGISTRY.get(a["kind"])
            if cls is None:
                raise ModelError(f"{a['id']}: no simulation component for kind {a['kind']!r}")
            params = {**a.get("attributes", {}).get("simulation", {}), **overrides.get(a["id"], {})}
            self.nodes[a["id"]] = Node(a["id"], a.get("name", a["id"]), cls(params))

        def owner(iface: str) -> str:
            aid = iface.split(".", 1)[0]
            if aid not in self.nodes:
                raise ModelError(f"connection end {iface!r} names no asset")
            return aid

        fed: set[str] = set()
        for c in model.get("connections", []):
            src, dst = owner(c["from"]), owner(c["to"])
            if c["type"] == "cable" and self.nodes[src].role == "generator":
                # A generator is not a feeder: it is an alternate supply to the
                # bus it lands on, through that bus's transfer switch.
                if self.nodes[dst].role != "bus":
                    raise ModelError(f"{src} must land on a bus, not {dst}")
                self.nodes[dst].generators.append(self.nodes[src])
                fed.add(src)
            elif c["type"] == "cable":
                if dst in fed:
                    raise ModelError(f"{dst} is fed twice; only radial networks are supported")
                self.nodes[src].children.append(self.nodes[dst])
                fed.add(dst)
            elif c["type"] in ("data_link", "io_link"):
                a, b = self.nodes[src], self.nodes[dst]
                ctrl, target = (a, b) if a.role == "controller" else (b, a)
                if ctrl.role != "controller" or target.role != "storage":
                    raise ModelError(f"{c['id']}: a data link must join a controller to a storage asset")
                target.controller = ctrl.comp

        roots = [n for n in self.nodes.values() if n.role == "source"]
        if len(roots) != 1:
            raise ModelError(f"expected one source, found {len(roots)}")
        self.root = roots[0]
        unfed = [n.id for n in self.nodes.values() if n.id not in fed and n.role not in ("source", "controller")]
        if unfed:
            raise ModelError(f"not connected to the supply: {', '.join(unfed)}")

    # ── stepping ─────────────────────────────────────────────────────────────

    def supply(self, t: float, dt: float):
        """The grid's condition over this step: connected, lowest voltage, time in a dip."""
        return self.events.at(t, dt)

    def _storage_nodes(self):
        return [n for n in self.nodes.values() if n.role == "storage"]

    def prepare(self, dt: float, hours: float = 24, start_h: float = 0.0) -> None:
        forecast = self.price.forecast(dt, hours, start_h)
        for n in self._storage_nodes():
            if n.controller is not None:
                n.controller.prepare(forecast, n.comp, dt)

    def _draw(self, node: Node, t: float, dt: float, i: int, price: float, up: bool) -> float:
        """Power this node draws from its parent, kW (negative = supplies it)."""
        m = self.measurements.get(node.id)
        reading = m(t) if m else None
        if reading is not None:
            return node.comp.observe(reading, dt)

        if node.role == "load":
            return node.comp.step(t, dt, price)
        if node.role == "conversion":
            out = sum(self._draw(c, t, dt, i, price, up) for c in node.children)
            return node.comp.step(out, dt, up)
        if node.role in ("bus", "source"):
            utility = up
            gens = [g.comp for g in node.generators]
            for g in gens:
                g.control(t, dt, utility, price)
                up = g.bus_supply(up)           # an islanded set forms the bus; a retransfer breaks it
            passive = sum(self._draw(c, t, dt, i, price, up) for c in node.children if c.role != "storage")

            # Merit order: stored energy costs wear, a running set costs fuel, so
            # storage goes before the generator. In parallel a set still carries
            # its minimum load first, so it is never run unloaded. Islanded, it
            # carries the whole balance after storage.
            block = 0.0
            for g in gens:
                if g.online and not g.islanded:
                    block += g.dispatch(min(g.min_load_kw, passive - block), dt)
            storage = 0.0
            src = self.root.comp
            for c in node.children:
                if c.role != "storage":
                    continue
                req = 0.0
                if c.controller is not None and utility:
                    req = c.controller.decide(price, i, dt, c.comp, passive - block - storage,
                                              src.p["capacity_kw"], src.p["export_allowed"])
                storage += c.comp.step(req, dt, up)
            net = passive - block - storage
            for g in gens:
                if g.online and not g.islanded:
                    net -= g.dispatch(net, dt, add=True)
                else:
                    net -= g.dispatch(net, dt)
            if node.role == "bus":
                node.comp.load_kw, node.comp.storage_kw = passive, storage
                node.comp.generator_kw = sum(g.kw for g in gens)
            return net
        raise ModelError(f"{node.id}: role {node.role!r} cannot sit on a feeder")

    def step(self, t: float, dt: float, i: int) -> dict:
        price, up = self.price.at(t), self.supply(t, dt)
        net = self._draw(self.root, t, dt, i, price, up)
        self.root.comp.step(net, price, dt, up)
        return {"t": t, "clock": clock(t, seconds=dt < 1 / 60 - 1e-9), "price": price,
                "grid_up": bool(up), "v_pct": up.v_pct}

    def snapshot(self) -> dict:
        return {nid: n.comp.snapshot() for nid, n in self.nodes.items()}

    def run(self, hours: float = 24, dt_min: float = 5, keep_rows: bool = True,
            on_step: Callable[["Network", dict], None] | None = None, start_h: float = 0.0) -> list[dict]:
        self.prepare(dt_min / 60, hours, start_h)

        def step(t, dt, i):
            row = self.step(t, dt, i)
            if keep_rows:
                row["assets"] = self.snapshot()
            if on_step:
                on_step(self, row)
            return row

        return run(step, hours=hours, dt_min=dt_min, start_h=start_h)
