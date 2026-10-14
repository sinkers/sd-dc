"""Busbar / switchboard: the node where feeders meet. Power balances here and
nothing is lost; cable and busbar losses are not modelled yet."""

from __future__ import annotations

from ..params import field, resolve


class Busbar:
    id = "bus"
    label = "Main switchboard"
    kind = "switchboard"
    role = "bus"
    # ALT is the alternate supply side of the transfer switch: a generator.
    ports = [{"name": "IN", "medium": "ac_lv_3ph"}, {"name": "OUT", "medium": "ac_lv_3ph", "many": True},
             {"name": "ALT", "medium": "ac_lv_3ph"}]
    schema = [
        field("voltage_v", "Nominal voltage", default=415, unit="V", min=230, max=33000, step=1, advanced=True),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.reset()

    def reset(self) -> None:
        self.load_kw = 0.0
        self.storage_kw = 0.0
        self.generator_kw = 0.0

    def snapshot(self) -> dict:
        return {"load_kw": self.load_kw, "storage_kw": self.storage_kw, "generator_kw": self.generator_kw,
                "net_kw": self.load_kw - self.storage_kw - self.generator_kw}
