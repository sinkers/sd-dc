"""Sequence of events: what changed, when, read back out of a run.

A protection engineer reads a disturbance from the relay's sequence-of-events
log, not from a trend: "14:00:00.000 sag to 70 %, 14:00:00 UPS to battery,
14:03:10 UPS on line". This builds that log from the rows of a run by watching
each asset's state and reporting every change, with the numbers that matter
at that moment.

It works from snapshots and asset kinds only, so any simulation built from
these components gets a log without writing one.
"""

from __future__ import annotations

MAX_EVENTS = 400


def _fmt_kw(v) -> str:
    return f"{v:,.0f} kW" if abs(v) >= 10 else f"{v:,.1f} kW"


def _grid_state(s: dict) -> str:
    if not s["up"]:
        return "outage"
    if s["v_pct"] < 90:
        return "sag"
    return "over" if s.get("over_capacity") else "normal"


def _describe(kind: str, now: str, snap: dict) -> tuple[str, str, str] | None:
    """(event, detail, severity) for an asset entering state `now`, or None to stay quiet."""
    if kind == "utility_supply":
        if now == "outage":
            return "Grid lost", "", "alarm"
        if now == "sag":
            return (f"Voltage sag to {snap['v_pct']:.0f} %", f"{snap['dip_ms']:.0f} ms below 90 %", "alarm")
        if now == "over":
            return "Import over connection capacity", _fmt_kw(snap["import_kw"]), "alarm"
        return "Grid normal", f"importing {_fmt_kw(snap['import_kw'])}", "info"

    if kind == "ups":
        soc = f"battery {snap['battery_soc_pct']:.0f} %"
        return {
            "on battery": (f"Transferred to battery ({snap.get('cause') or 'input lost'})", soc, "alarm"),
            "resync": ("Input healthy, resync timer running",
                       f"{soc}, {snap['resync_remaining_s']:.0f} s to go", "warn"),
            "walk-in": ("Walking the load back onto its input", soc, "warn"),
            "recharging": (f"Recharging at {_fmt_kw(snap['recharge_kw'])}"
                           + (", held to max demand" if snap.get("recharge_limited") else ""),
                           f"{soc}, input {_fmt_kw(snap['input_kw'])}", "info"),
            "online": ("On line", f"{soc}, input {_fmt_kw(snap['input_kw'])}", "info"),
            "eco": ("On line, eco mode", soc, "info"),
            "bypass": ("Static bypass: overload", f"load {_fmt_kw(snap['output_kw'])}", "warn"),
            "load dropped": ("Load dropped: battery exhausted", f"{_fmt_kw(snap['unserved_kw'])} unserved", "alarm"),
        }.get(now, (now, soc, "info"))

    if kind == "bess":
        soc = f"SoC {snap['soc_pct']:.0f} %"
        return {
            "tripped": (f"Tripped ({snap.get('trip_cause') or 'grid'})", soc, "alarm"),
            "reconnecting": ("Grid healthy, reconnect timer running",
                             f"{soc}, {snap['reconnect_remaining_s']:.0f} s to go", "warn"),
            "charging": (f"Charging at {_fmt_kw(-snap['ac_kw'])}", soc, "info"),
            "discharging": (f"Discharging at {_fmt_kw(snap['ac_kw'])}", soc, "info"),
            "idle": ("Idle", soc, "info"),
            "full": ("Full", soc, "info"),
            "empty": ("At reserve", soc, "info"),
            "disabled": ("Disabled", soc, "info"),
        }.get(now, (now, soc, "info"))

    if kind == "generator":
        kw = _fmt_kw(snap["kw"])
        if now == "off":
            return "Stopped", f"{snap['fuel_l']:.0f} L used so far", "info"
        if now.startswith("starting"):
            return f"Start signal ({snap.get('reason') or 'manual'})", f"on load in {snap['countdown_s']:.0f} s", "warn"
        if now == "running/islanded":
            return "On load, islanded: carrying the site", kw, "warn"
        if now == "running/parallel":
            return "Running in parallel with the grid", kw, "info"
        if now == "cooldown":
            return "Off load, cooling down", "", "info"
        if now == "tripped":
            return "Tripped on overload", "", "alarm"
        return None

    if kind == "plc":
        return {"charge": ("Decision: charge BESS", "", "info"),
                "discharge": ("Decision: discharge BESS", "", "info"),
                "peak shave": ("Decision: peak shave to site max demand", "", "warn"),
                "hold": ("Decision: hold", "", "info")}.get(now)

    if kind == "server":
        if now == "capped":
            return "Power cap applied", f"{_fmt_kw(snap['kw'])} of {_fmt_kw(snap['uncapped_kw'])} wanted", "warn"
        return "Power cap released", _fmt_kw(snap["kw"]), "info"
    return None


def _state(kind: str, snap: dict) -> str | None:
    if kind == "utility_supply":
        return _grid_state(snap)
    if kind == "ups":
        return snap["status"]
    if kind == "bess":
        return snap["status"]
    if kind == "generator":
        st = snap["state"]
        if st == "running":
            return "running/islanded" if snap["islanded"] else "running/parallel"
        return st
    if kind == "plc":
        return snap["decision"]
    if kind == "server":
        return "capped" if snap["capped"] else "uncapped"
    return None


def _extra_watches(kind: str, snap: dict) -> dict:
    """Threshold conditions worth their own line, on top of the state."""
    out = {}
    if kind == "ups" and snap.get("max_demand_kw"):
        out["over max demand"] = snap["input_kw"] > snap["max_demand_kw"] + 1e-6
    return out


def sequence(rows: list[dict], assets: dict) -> dict:
    """Build the sequence-of-events log from a run.

    assets maps asset id -> {"name", "kind"}. The first row sets the starting
    state silently; every change after it is an event.
    """
    events: list[dict] = []
    last: dict[str, str | None] = {}
    last_extra: dict[tuple, bool] = {}
    truncated = False
    for r in rows:
        for aid, snap in r["assets"].items():
            meta = assets.get(aid)
            if not meta:
                continue
            kind = meta["kind"]
            st = _state(kind, snap)
            if st is not None:
                prev = last.get(aid, "__first__")
                if prev != "__first__" and st != prev:
                    d = _describe(kind, st, snap)
                    if d:
                        events.append({"t": r["t"], "clock": r["clock"], "asset": aid, "name": meta["name"],
                                       "kind": kind, "event": d[0], "detail": d[1], "severity": d[2]})
                last[aid] = st
            for key, on in _extra_watches(kind, snap).items():
                k = (aid, key)
                if k in last_extra and on != last_extra[k]:
                    events.append({"t": r["t"], "clock": r["clock"], "asset": aid, "name": meta["name"], "kind": kind,
                                   "event": f"Input above max demand ({_fmt_kw(snap['max_demand_kw'])})" if on
                                   else "Input back under max demand",
                                   "detail": f"input {_fmt_kw(snap['input_kw'])}", "severity": "alarm" if on else "info"})
                last_extra[k] = on
        if len(events) > MAX_EVENTS:
            truncated = True
            events = events[:MAX_EVENTS]
            break
    return {"events": events, "truncated": truncated,
            "counts": {s: sum(1 for e in events if e["severity"] == s) for s in ("alarm", "warn", "info")}}
