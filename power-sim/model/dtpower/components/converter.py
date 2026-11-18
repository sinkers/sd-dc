"""Bidirectional converter (PCS, inverter-rectifier): AC one side, DC the other.

The BESS uses one today. The next simulation puts one inside the UPS so its
battery can push power back onto the site bus.

Loss model: a fixed no-load loss while energised plus a flat proportional loss.
That is enough for arbitrage sums. A load-dependent curve can replace ``eta``
without changing the interface.
"""

from __future__ import annotations

from ..engine import clamp
from ..params import field, resolve


class Converter:
    schema = [
        field("rated_kw", "Converter rating", default=200, unit="kW", min=10, max=4000, step=10),
        field("eff_pct", "Converter efficiency (one way)", default=98, unit="%", min=85, max=99.5, step=0.1, advanced=True),
        field("no_load_kw", "No-load loss", default=0.4, unit="kW", min=0, max=20, step=0.1, advanced=True),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)

    @property
    def eta(self) -> float:
        return self.p["eff_pct"] / 100

    def limit_ac(self, ac_kw: float) -> float:
        return clamp(ac_kw, -self.p["rated_kw"], self.p["rated_kw"])

    def dc_for_ac(self, ac_kw: float) -> float:
        """DC power the battery must exchange to produce this AC power."""
        return ac_kw / self.eta if ac_kw >= 0 else ac_kw * self.eta

    def ac_for_dc(self, dc_kw: float) -> float:
        """AC power produced by this DC exchange; the inverse of dc_for_ac."""
        return dc_kw * self.eta if dc_kw >= 0 else dc_kw / self.eta
