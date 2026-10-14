"""Simulation 01: grid, BESS and UPS, with price-driven demand response.

    UTIL ── MSB ──┬── BESS-1        (DR-1 sets its power over a data link)
                  └── UPS-1 ── GPU-1

The BESS and the UPS share the main switchboard. The controller watches the
spot price: it charges the BESS when power is cheap and discharges it when power
is dear, offsetting what the site imports. The GPU fleet may also be power
capped, either all the time or only while the price is high.

The network is an IndustroML-shaped model (``model()``), run by
dtpower.network. Parameters are keyed by asset id.

Savings are measured against the same day run again with no BESS and no
price-triggered cap. The day is run three times, so that the saving splits
cleanly into what the BESS earned and what the cap earned:

    baseline   BESS off, demand-response cap off
    bess       BESS on,  demand-response cap off
    full       BESS on,  demand-response cap as configured

A fixed ("always") cap is part of the site's configuration, not demand
response, so it applies in all three runs.
"""

from __future__ import annotations

from ..components import REGISTRY, PriceSignal
from ..network import Network, interfaces_for

ID = "bess-dr"
TITLE = "Grid, BESS and UPS"
DESCRIPTION = ("Price-driven demand response: a BESS beside a UPS-fed GPU load, charging when power is cheap "
               "and discharging when it is dear.")

# (id, name, kind) in drawing order, then the cables and data links between them.
ASSETS = [
    ("UTIL", "Grid connection", "utility_supply"),
    ("MSB", "Main switchboard", "switchboard"),
    ("BESS-1", "BESS", "bess"),
    ("UPS-1", "UPS", "ups"),
    ("GPU-1", "GPU servers", "server"),
    ("DR-1", "DR controller", "plc"),
    ("GEN-1", "Generator", "generator"),
]
LINKS = [
    ("C-01", "cable", "UTIL.OUT", "MSB.IN"),
    ("C-02", "cable", "MSB.OUT", "BESS-1.AC"),
    ("C-03", "cable", "MSB.OUT", "UPS-1.IN"),
    ("C-04", "cable", "UPS-1.OUT", "GPU-1.IN"),
    ("D-01", "data_link", "DR-1.NET", "BESS-1.CTRL"),
    ("C-05", "cable", "GEN-1.OUT", "MSB.ALT"),
]

# Sim-level defaults under every scenario. The generator is fitted but switched
# off unless a scenario turns it on, so the price and disturbance scenarios
# keep the results they were written for.
DEFAULTS = {"GEN-1": {"enabled": False}}


def model(params: dict | None = None) -> dict:
    """The site as an IndustroML model, with each asset's simulation parameters attached."""
    params = params or {}
    assets, interfaces = [], []
    for aid, name, kind in ASSETS:
        cls = REGISTRY[kind]
        domain = "control" if cls.role == "controller" else "electrical"
        assets.append({"id": aid, "name": name, "kind": kind, "domain": domain, "container": "SITE",
                       "attributes": {"simulation": dict(params.get(aid, {}))}})
        interfaces += interfaces_for(aid, cls)
    connections = [{"id": cid, "type": t, "from": a, "to": b} for cid, t, a, b in LINKS]
    return {
        "meta": {"format": "IndustroML", "version": "0.1", "site_name": TITLE, "units": {"power": "kW"}},
        "containers": [{"id": "SITE", "name": TITLE, "type": "site"}],
        "assets": assets, "interfaces": interfaces, "connections": connections,
    }


def _price(source: dict) -> PriceSignal:
    kind = source["kind"]
    if kind == "nem":
        return PriceSignal.nem(source["key"])
    if kind == "flat":
        return PriceSignal.flat(source["price"])
    if kind == "tou":
        return PriceSignal.tou(**source.get("args", {}))
    raise ValueError(f"unknown price source {kind!r}")


# Shared by the disturbance scenarios.
WINDOW = [13 + 58 / 60, 14 + 43 / 60]
SAG = {"t": 14.0, "residual_pct": 70, "duration_ms": 150}
UPS_NO_RT = {"ride_through": False, "resync_s": 180, "recharge_pct": 20}

SCENARIOS = [
    {"id": "nsw-spike", "label": "NSW1, 12 Oct 2026: $13,017 afternoon spike",
     "description": "A recorded NEM day. Prices sit between $30 and $230 until 14:00, then spike past $13,000 for half an hour. "
                    "The BESS charges through the cheap midday and empties into the spike.",
     "price": {"kind": "nem", "key": "NSW1-2026-10-12"},
     "params": {"DR-1": {"charge_below": 80, "discharge_above": 250}}},
    {"id": "nsw-spike-cap", "label": "NSW1, 12 Oct 2026: spike with GPU power cap",
     "description": "The same spike day, with the GPU fleet capped to 70 % of maximum whenever the price passes $300. "
                    "The saving splits into what the BESS earned and what the cap earned, and the cap's cost shows as lost compute.",
     "price": {"kind": "nem", "key": "NSW1-2026-10-12"},
     "params": {"DR-1": {"charge_below": 80, "discharge_above": 250},
                "GPU-1": {"cap_enabled": True, "cap_trigger": "price", "cap_pct": 70, "cap_price": 300}}},
    {"id": "nsw-peaks", "label": "NSW1, 9 Oct 2026: morning and evening peaks",
     "description": "A recorded NEM day with two peaks. Overnight runs at $230 to $990, midday falls below $60, and the evening "
                    "climbs again. The BESS cycles twice.",
     "price": {"kind": "nem", "key": "NSW1-2026-10-09"},
     "params": {"DR-1": {"charge_below": 70, "discharge_above": 220}}},
    {"id": "nsw-morning-optimal", "label": "NSW1, 10 Oct 2026: one $4,091 spike, perfect foresight",
     "description": "A recorded day with a single half-hour spike at 07:00. Runs the perfect-foresight strategy, "
                    "which is the most arbitrage could have earned on this day.",
     "price": {"kind": "nem", "key": "NSW1-2026-10-10"},
     "params": {"DR-1": {"strategy": "optimal"}}},
    {"id": "sa-negative", "label": "SA1, 8 Oct 2026: negative prices all afternoon",
     "description": "A recorded South Australian day where solar pushes the price below zero from 07:00 to 16:00, down to "
                    "-$248. The BESS is paid to charge.",
     "price": {"kind": "nem", "key": "SA1-2026-10-08"},
     "params": {"DR-1": {"charge_below": 0, "discharge_above": 90}}},
    {"id": "tou", "label": "Time-of-use tariff, evening peak",
     "description": "A synthetic tariff: $45 overnight, $110 through the day, $380 from 15:00 to 21:00.",
     "price": {"kind": "tou"},
     "params": {"DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "outage", "label": "Grid outage, 25 minutes at 18:00",
     "description": "The time-of-use day, with the grid lost from 18:00 to 18:25. The BESS trips on anti-islanding. "
                    "The UPS carries the GPUs from its own battery until that battery is exhausted. Run at one-minute steps.",
     "price": {"kind": "tou"},
     "outages": [[18.0, 18.0 + 25 / 60]],
     "dt_min": 1,
     "params": {"DR-1": {"charge_below": 60, "discharge_above": 300}}},
    # ── Grid disturbances. A 45-minute window at two-second steps, so a
    # sag, the minutes on battery, the resync and the recharge can all be seen.
    # A sag is an event with a depth and a duration, not a sample, so 150 ms
    # inside a two-second step still registers as 150 ms.
    {"id": "sag-no-ride-through", "label": "Voltage sag to 70 % for 150 ms, UPS without ride-through",
     "description": "A 150 ms dip to 70 % at 14:00, the kind a fault on a neighbouring feeder causes. With ride-through off, "
                    "the UPS transfers to battery, stays there for the 3-minute resync, walks back onto the grid, then "
                    "recharges at 20 % of its rating. The recharge takes the UPS input to about 195 kW, a new peak.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "sags": [SAG],
     "params": {"UPS-1": UPS_NO_RT, "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "sag-ride-through", "label": "Same sag, UPS with ride-through",
     "description": "The same dip with ride-through on. 150 ms at 70 % is inside the ride-through envelope (500 ms, "
                    "down to 50 %), so the DC link carries it, the battery is never used and nothing else happens.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "sags": [SAG],
     "params": {"UPS-1": {**UPS_NO_RT, "ride_through": True}, "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "sag-max-demand", "label": "Same sag, UPS recharge held to 160 kW max demand",
     "description": "No ride-through, but the UPS's input is limited to 160 kW. The recharge only gets the headroom "
                    "above the load, about 15 kW, so the site peak stays at 160 kW and the battery takes longer to "
                    "refill. Raise the recharge rate or the max demand to trade one against the other.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "sags": [SAG],
     "params": {"UPS-1": {**UPS_NO_RT, "max_demand_enabled": True, "max_demand_kw": 160},
                "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "sag-bess-shave", "label": "Same sag, BESS covers the UPS recharge",
     "description": "No ride-through and no UPS limit, so the UPS recharges at full rate, but the BESS holds the site to "
                    "160 kW by discharging the excess. The UPS refills quickly and the grid never sees the peak. The "
                    "BESS has fault ride-through on, so the sag does not trip it.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "sags": [SAG],
     "params": {"UPS-1": UPS_NO_RT,
                "DR-1": {"charge_below": 60, "discharge_above": 300, "peak_shave": True, "site_max_demand_kw": 160}}},
    {"id": "sag-bess-trips", "label": "Same sag, BESS without fault ride-through",
     "description": "As before, but the BESS has fault ride-through off, so the sag trips it too. It waits 60 s for the "
                    "grid to settle, then ramps back at 16.67 % of rating per minute. The UPS starts recharging while "
                    "the BESS is still ramping, and the site goes over 160 kW until it catches up.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "sags": [SAG],
     "params": {"UPS-1": {**UPS_NO_RT, "resync_s": 30}, "BESS-1": {"lvrt": False},
                "DR-1": {"charge_below": 60, "discharge_above": 300, "peak_shave": True, "site_max_demand_kw": 160}}},
    {"id": "sag-storm", "label": "Storm: four sags in seven minutes, no ride-through",
     "description": "Four dips between 14:00 and 14:06:30, as in a storm with repeated reclose attempts. Each one "
                    "restarts the UPS's 3-minute resync, so it stays on battery for nearly ten minutes and the battery "
                    "falls by about half. A second storm before it recharges would leave it short.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2,
     "sags": [SAG, {"t": 14 + 2 / 60, "residual_pct": 60, "duration_ms": 120},
              {"t": 14 + 5 / 60, "residual_pct": 75, "duration_ms": 300},
              {"t": 14 + 6.5 / 60, "residual_pct": 55, "duration_ms": 200}],
     "params": {"UPS-1": UPS_NO_RT, "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "interruption-2s", "label": "Two-second interruption, UPS with ride-through",
     "description": "The supply drops out completely for two seconds. No ride-through setting covers that: the UPS "
                    "goes to battery and the BESS trips, whatever their settings. The UPS resyncs after a minute, and "
                    "the BESS reconnects after its 60-second delay and ramps back.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "outages": [[14.0, 14.0 + 2 / 3600]],
     "params": {"UPS-1": {**UPS_NO_RT, "ride_through": True, "resync_s": 60},
                "DR-1": {"charge_below": 60, "discharge_above": 300, "peak_shave": True, "site_max_demand_kw": 160}}},
    # ── Generator. 250 kVA prime at 0.8 pf: 200 kW.
    {"id": "outage-gen", "label": "Grid outage, generator starts in 30 s",
     "description": "The grid is lost at 14:00 for 20 minutes. The UPS carries the GPUs on battery while the generator "
                    "starts; at 14:00:30 the set takes the bus. The UPS resyncs to it, walks the load across and "
                    "recharges from it. The grid returns at 14:20; after two minutes healthy the transfer switch goes "
                    "back, and its 100 ms open-transition break sends the UPS to battery once more.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "outages": [[14.0, 14 + 20 / 60]],
     "params": {"GEN-1": {"enabled": True}, "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "outage-gen-trip", "label": "Grid outage, UPS recharge trips the generator",
     "description": "As before, but the UPS recharges at 35 % of its rating. Once it is back on the generator, load plus "
                    "recharge is about 235 kW against a 200 kW set with a 110 % overload limit. The set trips, the UPS "
                    "goes back to battery with nothing behind it, and the load drops before the grid returns.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "outages": [[14.0, 14 + 20 / 60]],
     "params": {"GEN-1": {"enabled": True}, "UPS-1": {"recharge_pct": 35},
                "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "outage-gen-max-demand", "label": "Grid outage, UPS max demand keeps the generator on",
     "description": "The same 35 % recharge, with the UPS's input held to 185 kW. The recharge gets only the headroom "
                    "above the load, the set stays inside its rating, and the GPUs ride the whole outage.",
     "price": {"kind": "tou"}, "window": WINDOW, "dt_s": 2, "outages": [[14.0, 14 + 20 / 60]],
     "params": {"GEN-1": {"enabled": True},
                "UPS-1": {"recharge_pct": 35, "max_demand_enabled": True, "max_demand_kw": 185},
                "DR-1": {"charge_below": 60, "discharge_above": 300}}},
    {"id": "nsw-spike-gen", "label": "NSW1, 12 Oct 2026: generator runs above $500/MWh, no BESS",
     "description": "The spike day on a site with a generator and no BESS. The control system starts the set whenever "
                    "the spot price reaches $500/MWh and runs it in parallel with the grid for at least 30 minutes. "
                    "Fuel at 0.27 L/kWh and $2/L costs about $540/MWh, so it pays only well above the threshold. "
                    "Switch the BESS back on to see the two compete: the BESS goes first, being cheaper, and on this "
                    "day it covers the spike by itself, so the generator adds nothing but fuel.",
     "price": {"kind": "nem", "key": "NSW1-2026-10-12"},
     "params": {"GEN-1": {"enabled": True, "price_start": True, "price_threshold": 500},
                "BESS-1": {"enabled": False},
                "DR-1": {"charge_below": 80, "discharge_above": 250}}},
    {"id": "flat", "label": "Flat $100/MWh (control case)",
     "description": "No spread, so nothing to arbitrage. The saving is negative: the BESS's auxiliaries and no-load losses "
                    "cost money and earn nothing. Every other scenario should be read against this one.",
     "price": {"kind": "flat", "price": 100},
     "params": {}},
]


def timing(sc: dict) -> dict:
    """Where a scenario's run starts, how long it lasts and its step, plus its grid events."""
    start, end = sc.get("window", [0.0, 24.0])
    dt_min = sc["dt_s"] / 60 if "dt_s" in sc else sc.get("dt_min", 5)
    return {"start_h": start, "hours": end - start, "dt_min": dt_min,
            "outages": sc.get("outages", []), "sags": sc.get("sags", [])}


def scenario(sid: str) -> dict:
    for s in SCENARIOS:
        if s["id"] == sid:
            return s
    raise KeyError(f"unknown scenario {sid!r}")


def describe() -> dict:
    """Everything the viewer needs: the model, each asset's schema, the scenarios."""
    comps = {}
    for aid, name, kind in ASSETS:
        cls = REGISTRY[kind]
        comps[aid] = {"name": name, "kind": kind, "role": cls.role, "label": cls.label,
                      "kind_proposed": getattr(cls, "kind_proposed", False), "schema": cls.schema}
    return {
        "id": ID, "title": TITLE, "description": DESCRIPTION,
        "model": model(), "assets": comps,
        "scenarios": [{"id": s["id"], "label": s["label"], "description": s["description"], "params": merge_params(s, {}),
                       **timing(s)} for s in SCENARIOS],
    }


def merge_params(sc: dict, params: dict | None) -> dict:
    """Scenario params under caller params, per asset."""
    params = params or {}
    return {aid: {**DEFAULTS.get(aid, {}), **sc.get("params", {}).get(aid, {}), **params.get(aid, {})}
            for aid, _, _ in ASSETS}


def _run_once(params: dict, price: PriceSignal, tm: dict, *, bess_on: bool, dr_cap: bool, dr_gen: bool,
              keep_rows: bool, measurements=None) -> dict:
    over = {}
    if not dr_gen and params["GEN-1"].get("price_start"):
        over["GEN-1"] = {"price_start": False}
    if not bess_on:
        over["BESS-1"] = {"enabled": False}
    if not dr_cap and params["GPU-1"].get("cap_trigger") == "price":
        over["GPU-1"] = {"cap_enabled": False}
    net = Network(model(params), price, outages=tm["outages"], sags=tm["sags"], overrides=over,
                  measurements=measurements)
    grid, bess, gen = net.nodes["UTIL"].comp, net.nodes["BESS-1"].comp, net.nodes["GEN-1"].comp
    b = bess.battery
    e0 = b.energy_kwh
    # Energy the battery holds above (or below) where it started, valued as AC
    # at the run's median price. The optimal controller values it the same way.
    fc = sorted(price.forecast(tm["dt_min"] / 60, tm["hours"], tm["start_h"]))
    median = fc[len(fc) // 2]
    worth = b.eta * bess.pcs.eta * median / 1000
    cost, wear, stored = [], [], []

    def record(_n, _r):
        cost.append(grid.cost + gen.fuel_cost)      # the generator's fuel is part of the bill
        wear.append(b.wear_cost)
        stored.append((b.energy_kwh - e0) * worth if bess.p["enabled"] else 0.0)

    rows = net.run(hours=tm["hours"], dt_min=tm["dt_min"], start_h=tm["start_h"], keep_rows=keep_rows, on_step=record)
    return {"net": net, "rows": rows, "cost": cost, "wear": wear, "stored": stored, "median": median,
            "soc_start_pct": e0 / b.p["capacity_kwh"] * 100}


def _saving(base: dict, run: dict, i: int = -1) -> float:
    return base["cost"][i] - run["cost"][i] - run["wear"][i] + run["stored"][i]


def simulate(scenario_id: str = "nsw-spike", params: dict | None = None, measurements=None) -> dict:
    sc = scenario(scenario_id)
    p = merge_params(sc, params)
    price = _price(sc["price"])
    tm = timing(sc)

    kw = dict(measurements=measurements)
    # Each run adds one demand-response measure to the one before, so the saving
    # splits into what each added. Order matters: the generator's figure is what
    # it adds on top of a BESS that is already offsetting the same load.
    base = _run_once(p, price, tm, bess_on=False, dr_cap=False, dr_gen=False, keep_rows=False, **kw)
    bess_only = _run_once(p, price, tm, bess_on=True, dr_cap=False, dr_gen=False, keep_rows=False, **kw)
    bess_cap = _run_once(p, price, tm, bess_on=True, dr_cap=True, dr_gen=False, keep_rows=False, **kw)
    full = _run_once(p, price, tm, bess_on=True, dr_cap=True, dr_gen=True, keep_rows=True, **kw)
    net, rows = full["net"], full["rows"]

    for i, r in enumerate(rows):
        r["baseline_cost"] = base["cost"][i]
        r["saving"] = _saving(base, full, i)

    saving_bess = _saving(base, bess_only)
    saving_total = _saving(base, full)
    b = net.nodes["BESS-1"].comp.battery
    g, gpu, ups, gen = (net.nodes[k].comp for k in ("UTIL", "GPU-1", "UPS-1", "GEN-1"))
    charge_px = [r["price"] for r in rows if r["assets"]["BESS-1"]["status"] == "charging"]
    dis_px = [r["price"] for r in rows if r["assets"]["BESS-1"]["status"] == "discharging"]
    summary = {
        "baseline_cost": base["cost"][-1],
        "cost": full["cost"][-1],
        "bill_saving": base["cost"][-1] - full["cost"][-1],
        "wear_cost": full["wear"][-1],
        "stored_energy_value": full["stored"][-1],
        "median_price": full["median"],
        "soc_start_pct": full["soc_start_pct"],
        "soc_end_pct": b.soc * 100,
        "saving": saving_total,
        "saving_bess": saving_bess,
        "saving_cap": _saving(base, bess_cap) - saving_bess,
        "saving_gen": saving_total - _saving(base, bess_cap),
        "bess_charged_kwh": b.charged_kwh,
        "bess_discharged_kwh": b.discharged_kwh,
        "bess_cycles": b.equivalent_cycles,
        "mean_charge_price": sum(charge_px) / len(charge_px) if charge_px else None,
        "mean_discharge_price": sum(dis_px) / len(dis_px) if dis_px else None,
        "import_kwh": g.import_kwh,
        "export_kwh": g.export_kwh,
        "peak_import_kw": g.peak_import_kw,
        "over_capacity_steps": g.over_capacity_steps,
        "gpu_curtailed_kwh": gpu.curtailed_kwh,
        "gpu_work_lost_server_h": gpu.work_lost_server_h,
        "unserved_kwh": ups.unserved_kwh,
        # disturbance ride-through
        "disturbances": len(tm["sags"]) + len(tm["outages"]),
        "ups_transfers": ups.transfers,
        "ups_on_battery_s": ups.on_battery_s,
        "ups_min_soc_pct": ups.min_soc_pct,
        "ups_end_soc_pct": ups.battery.soc * 100,
        "ups_peak_input_kw": ups.peak_input_kw,
        "ups_over_demand_s": ups.over_demand_s,
        "ups_max_demand_kw": ups.p["max_demand_kw"] if ups.p["max_demand_enabled"] else None,
        "bess_trips": net.nodes["BESS-1"].comp.trips,
        "site_max_demand_kw": p["DR-1"].get("site_max_demand_kw") if p["DR-1"].get("peak_shave") else None,
        # generator
        "gen_enabled": gen.p["enabled"],
        "gen_kwh": gen.kwh,
        "gen_fuel_l": gen.fuel_l,
        "gen_fuel_cost": gen.fuel_cost,
        "gen_run_h": gen.run_h,
        "gen_starts": gen.starts,
        "gen_trips": gen.trips,
        "gen_peak_kw": gen.peak_kw,
        "gen_rated_kw": gen.rated_kw,
        "gen_cost_per_mwh": gen.cost_per_mwh,
    }
    return {
        "sim": ID,
        "scenario": {k: sc.get(k) for k in ("id", "label", "description")} | tm,
        "price": {"name": price.name, "source": price.source, "series": price.series, "interval_min": price.interval_min},
        "params": p,
        "summary": summary,
        "rows": rows,
    }
