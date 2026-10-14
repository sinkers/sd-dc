"""GPU server load: a fleet of identical servers, a utilisation setting shaped by
a workload profile, and an optional power cap.

Server power is linear between idle and maximum in utilisation. That is a
simplification, and the idle figures below are estimates.

The power cap can be fixed ("always") or a demand-response lever that applies
only while the price is above a threshold ("price"). Capping costs compute.
Throughput is modelled as (capped dynamic power / uncapped dynamic power) ** 0.35,
the sub-linear shape GPUs show under a power limit: cutting dynamic power by a
third loses roughly an eighth of throughput. PERF_EXPONENT is an assumption to
calibrate, not a measured figure.
"""

from __future__ import annotations

import math

from ..engine import clamp
from ..params import field, resolve

PERF_EXPONENT = 0.35

# max_kw is the vendor's published system maximum. idle_kw is our estimate.
SERVERS = {
    "dgx-h100": {"label": "NVIDIA DGX H100 (8x H100)", "max_kw": 10.2, "idle_kw": 2.6,
                 "provenance": {"source": "NVIDIA DGX H100 datasheet, max system power 10.2 kW", "verified": False,
                                "fields_verified": [], "note": "idle_kw estimated"}},
    "dgx-b200": {"label": "NVIDIA DGX B200 (8x B200)", "max_kw": 14.3, "idle_kw": 3.6,
                 "provenance": {"source": "NVIDIA DGX B200 datasheet, max system power ~14.3 kW", "verified": False,
                                "fields_verified": [], "note": "idle_kw estimated"}},
    "dgx-b300": {"label": "NVIDIA DGX B300 (8x B300)", "max_kw": 14.5, "idle_kw": 3.6,
                 "provenance": {"source": "Colfax DGX B300 listing: 14.5 kW at the busbar, 15.1 kW at the PSU; "
                                          "Flopper.io spec sheet ~14 kW. Not NVIDIA's own datasheet",
                                "verified": False, "fields_verified": [], "note": "idle_kw estimated"}},
    "gb200-nvl72": {"label": "NVIDIA GB200 NVL72 (rack)", "max_kw": 132.0, "idle_kw": 33.0,
                    "provenance": {"source": "Published rack figures 120-132 kW", "verified": False,
                                   "fields_verified": [], "note": "idle_kw estimated"}},
    # Max-Q and Max-P are two power profiles on the same Vera Rubin hardware,
    # not two products: the same rack with a different power ceiling. Idle is
    # the same for both.
    "vr200-nvl72-maxq": {"label": "NVIDIA Vera Rubin NVL72 (rack), Max-Q", "max_kw": 190.0, "idle_kw": 45.0,
                         "provenance": {"source": "Ming-Chi Kuo supply-chain estimate, Jan 2026: ~1.8 kW per GPU, "
                                                  "~190 kW per rack. SemiAnalysis: Max-Q and Max-P are default power "
                                                  "profiles on one design. No NVIDIA-published figure",
                                        "verified": False, "fields_verified": [], "note": "idle_kw estimated"}},
    "vr200-nvl72-maxp": {"label": "NVIDIA Vera Rubin NVL72 (rack), Max-P", "max_kw": 230.0, "idle_kw": 45.0,
                         "provenance": {"source": "Ming-Chi Kuo supply-chain estimate, Jan 2026: ~2.3 kW per GPU, "
                                                  "~230 kW per rack. No NVIDIA-published figure",
                                        "verified": False, "fields_verified": [], "note": "idle_kw estimated"}},
    "generic-8gpu": {"label": "Generic 8-GPU PCIe server", "max_kw": 6.5, "idle_kw": 1.6,
                     "provenance": {"source": "Illustrative", "verified": False, "fields_verified": []}},
}

PROFILES = [
    {"value": "constant", "label": "Constant"},
    {"value": "training", "label": "Training run (checkpoint dips every 2 h)"},
    {"value": "inference", "label": "Inference (follows the business day)"},
    {"value": "overnight-batch", "label": "Overnight batch (22:00 to 06:00)"},
    {"value": "bursty", "label": "Bursty (random 15-minute jobs)"},
]

CAP_TRIGGERS = [
    {"value": "always", "label": "Always applied"},
    {"value": "price", "label": "Only when price is high (demand response)"},
]


def profile_factor(profile: str, t: float) -> float:
    """Multiplier on utilisation at hour t, in [0, 1]."""
    h = t % 24
    if profile == "training":
        return 0.35 if (h % 2) < 0.1 else 1.0
    if profile == "inference":
        return 0.45 + 0.55 * (0.5 - 0.5 * math.cos(2 * math.pi * (h - 2) / 24))
    if profile == "overnight-batch":
        return 1.0 if (h >= 22 or h < 6) else 0.3
    if profile == "bursty":
        slot = int(h * 4)
        r = math.sin(slot * 12.9898 + 78.233) * 43758.5453
        return 0.2 + 0.8 * (r - math.floor(r))
    return 1.0


class GPUServerLoad:
    id = "gpu"
    label = "GPU servers"
    # One asset stands for a fleet of identical servers; `count` says how many.
    kind = "server"
    role = "load"
    ports = [{"name": "IN", "medium": "ac_lv_3ph"}]
    schema = [
        field("server", "Server model", kind="select", default="dgx-h100",
              options=[{"value": k, "label": v["label"]} for k, v in SERVERS.items()]),
        field("count", "Number of servers", default=16, unit="servers", min=1, max=500, step=1),
        field("utilisation_pct", "Utilisation", default=80, unit="%", min=0, max=100, step=1),
        field("profile", "Workload profile", kind="select", default="constant", options=PROFILES),
        field("cap_enabled", "Power cap", kind="toggle", default=False),
        field("cap_pct", "Cap level", default=70, unit="% of max", min=20, max=100, step=1),
        field("cap_trigger", "Cap applies", kind="select", default="always", options=CAP_TRIGGERS),
        field("cap_price", "Cap above price", default=300, unit="$/MWh", min=0, max=5000, step=10),
    ]

    def __init__(self, params: dict | None = None):
        self.p = resolve(self.schema, params)
        self.spec = SERVERS[self.p["server"]]
        self.reset()

    def reset(self) -> None:
        self.kw = 0.0
        self.uncapped_kw = 0.0
        self.capped = False
        self.throughput_pct = 100.0
        self.curtailed_kwh = 0.0
        self.work_lost_server_h = 0.0  # server-hours of compute lost to the cap

    @property
    def max_kw(self) -> float:
        return self.spec["max_kw"] * self.p["count"]

    @property
    def idle_kw(self) -> float:
        return self.spec["idle_kw"] * self.p["count"]

    def cap_active(self, price: float) -> bool:
        p = self.p
        if not p["cap_enabled"]:
            return False
        return p["cap_trigger"] == "always" or price >= p["cap_price"]

    def step(self, t: float, dt: float, price: float = 0.0) -> float:
        p = self.p
        util = clamp(p["utilisation_pct"] / 100 * profile_factor(p["profile"], t), 0, 1)
        demand = self.idle_kw + (self.max_kw - self.idle_kw) * util
        self.uncapped_kw = demand
        self.capped = False
        self.throughput_pct = 100.0
        if self.cap_active(price):
            cap = max(self.idle_kw, p["cap_pct"] / 100 * self.max_kw)
            if demand > cap:
                self.capped = True
                dyn = demand - self.idle_kw
                ratio = (cap - self.idle_kw) / dyn if dyn > 0 else 1.0
                self.throughput_pct = 100 * ratio ** PERF_EXPONENT
                demand = cap
        self.kw = demand
        self.curtailed_kwh += (self.uncapped_kw - self.kw) * dt
        self.work_lost_server_h += (1 - self.throughput_pct / 100) * util * p["count"] * dt
        return self.kw

    def observe(self, reading: dict, dt: float) -> float:
        """Take a measured fleet power instead of modelling it (telemetry replay)."""
        self.kw = self.uncapped_kw = float(reading["kw"])
        self.capped = False
        self.throughput_pct = 100.0
        return self.kw

    def snapshot(self) -> dict:
        return {
            "kw": self.kw,
            "uncapped_kw": self.uncapped_kw,
            "max_kw": self.max_kw,
            "idle_kw": self.idle_kw,
            "capped": self.capped,
            "throughput_pct": self.throughput_pct,
            "curtailed_kwh": self.curtailed_kwh,
            "work_lost_server_h": self.work_lost_server_h,
            "server_label": self.spec["label"],
        }
