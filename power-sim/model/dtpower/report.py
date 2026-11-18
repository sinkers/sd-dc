"""Plant figures for the report: voltage, power flows, state of charge and
power capping, summarised from a run's rows.

Like the sequence of events, this reads snapshots by asset kind, so any
simulation built from these components gets the same tables.
"""

from __future__ import annotations

from .engine import clock


def _dt_h(rows: list[dict]) -> float:
    return rows[1]["t"] - rows[0]["t"] if len(rows) > 1 else 1.0


def _stat(values: list[float], dt: float, rows: list[dict]) -> dict:
    if not values:
        return {"peak_kw": 0.0, "peak_at": None, "mean_kw": 0.0, "min_kw": 0.0, "energy_kwh": 0.0}
    i = max(range(len(values)), key=values.__getitem__)
    return {"peak_kw": values[i], "peak_at": rows[i]["clock"], "mean_kw": sum(values) / len(values),
            "min_kw": min(values), "energy_kwh": sum(values) * dt}


def _periods(rows: list[dict], on, extra=None) -> list[dict]:
    """Contiguous runs of steps where on(row) holds."""
    out, start = [], None
    for i, r in enumerate(rows + [None]):
        active = r is not None and on(r)
        if active and start is None:
            start = i
        elif not active and start is not None:
            seg = rows[start:i]
            p = {"start": seg[0]["t"], "end": seg[-1]["t"] + _dt_h(rows),
                 "clock_start": seg[0]["clock"], "clock_end": clock(seg[-1]["t"] + _dt_h(rows), len(seg[0]["clock"]) > 5)}
            if extra:
                p.update(extra(seg))
            out.append(p)
            start = None
    return out


def plant(rows: list[dict], assets: dict) -> dict:
    """assets maps id -> {"name", "kind"}."""
    if not rows:
        return {}
    dt = _dt_h(rows)
    by_kind = {}
    for aid, meta in assets.items():
        by_kind.setdefault(meta["kind"], []).append(aid)
    out: dict = {"step_s": round(dt * 3600, 3), "steps": len(rows)}

    # ── voltage at the point of connection ──
    g = by_kind.get("utility_supply", [None])[0]
    if g:
        snaps = [r["assets"][g] for r in rows]
        up = [s for s in snaps if s["up"]]
        sag_steps = [r for r in rows if r["assets"][g]["up"] and r["assets"][g]["v_pct"] < 90]
        out["voltage"] = {
            "lowest_pct": min(s["v_pct"] for s in snaps),
            "lowest_at": rows[min(range(len(rows)), key=lambda i: snaps[i]["v_pct"])]["clock"],
            "mean_pct": sum(s["v_pct"] for s in up) / len(up) if up else 0.0,
            "sags": len(_periods(rows, lambda r: r["assets"][g]["up"] and r["assets"][g]["v_pct"] < 90)),
            "below_90_s": sum(s["dip_ms"] for s in snaps if s["up"]) / 1000,
            "sag_steps": len(sag_steps),
            "outage_s": sum(1 for s in snaps if not s["up"]) * dt * 3600,
            "outages": _periods(rows, lambda r: not r["assets"][g]["up"]),
        }

    # ── power flows ──
    flows = []

    def add(label, aid, get):
        if aid is None:
            return
        vals = [get(r["assets"][aid]) for r in rows]
        flows.append({"label": label, "asset": aid, **_stat(vals, dt, rows)})

    add("Grid import (net)", g, lambda s: s["import_kw"] - s["export_kw"])
    for u in by_kind.get("ups", []):
        add(f"{assets[u]['name']} input", u, lambda s: s["input_kw"])
        add(f"{assets[u]['name']} output", u, lambda s: s["output_kw"])
        add(f"{assets[u]['name']} losses", u, lambda s: s["loss_kw"])
    for s_id in by_kind.get("server", []):
        add(f"{assets[s_id]['name']} load", s_id, lambda s: s["kw"])
        add(f"{assets[s_id]['name']} demand before cap", s_id, lambda s: s["uncapped_kw"])
    for b in by_kind.get("bess", []):
        add(f"{assets[b]['name']} discharge", b, lambda s: max(0.0, s["ac_kw"]))
        add(f"{assets[b]['name']} charge", b, lambda s: max(0.0, -s["ac_kw"]))
    for gen in by_kind.get("generator", []):
        add(f"{assets[gen]['name']} output", gen, lambda s: s["kw"])
    out["power"] = flows

    # ── state of charge ──
    socs = []

    def soc(label, aid, get):
        vals = [get(r["assets"][aid]) for r in rows]
        lo = min(range(len(vals)), key=vals.__getitem__)
        socs.append({"label": label, "asset": aid, "start_pct": vals[0], "end_pct": vals[-1],
                     "lowest_pct": vals[lo], "lowest_at": rows[lo]["clock"], "highest_pct": max(vals)})

    for b in by_kind.get("bess", []):
        soc(assets[b]["name"], b, lambda s: s["soc_pct"])
    for u in by_kind.get("ups", []):
        soc(f"{assets[u]['name']} battery", u, lambda s: s["battery_soc_pct"])
    out["soc"] = socs

    # ── power capping on the load ──
    caps = []
    for s_id in by_kind.get("server", []):
        snaps = [r["assets"][s_id] for r in rows]
        periods = _periods(rows, lambda r: r["assets"][s_id]["capped"], lambda seg: {
            "cut_peak_kw": max(x["assets"][s_id]["uncapped_kw"] - x["assets"][s_id]["kw"] for x in seg),
            "capped_kw": min(x["assets"][s_id]["kw"] for x in seg),
            "lowest_throughput_pct": min(x["assets"][s_id]["throughput_pct"] for x in seg),
            "mean_price": sum(x["price"] for x in seg) / len(seg),
        })
        caps.append({
            "asset": s_id, "name": assets[s_id]["name"],
            "applied": bool(periods),
            "capped_steps": sum(1 for s in snaps if s["capped"]),
            "capped_h": sum(1 for s in snaps if s["capped"]) * dt,
            "curtailed_kwh": snaps[-1]["curtailed_kwh"],
            "work_lost_server_h": snaps[-1]["work_lost_server_h"],
            "lowest_throughput_pct": min(s["throughput_pct"] for s in snaps),
            "periods": periods,
        })
    out["capping"] = caps
    return out

