"""Size the circuits on a tray with the cable sizing calculator, and lay them.

Each circuit is sized by ../cable-sizing (AS/NZS 3008.1.1), the same engine
behind its web UI, REST API and MCP server, with the route length taken from
the tray plus the tails at each end. What the tray adds:

  - Grouping. Every circuit on the tray, and every parallel run of each,
    counts towards the grouping factor (the engine's own rule). The number
    of runs is only known after sizing, so sizing repeats until it settles.
  - Mass and footprint per circuit, from the catalogue's per-core weight and
    OD: trefoil runs take 3 x OD of width each (two on the deck, one in the
    notch, the neutral alongside), flat runs one OD per core, plus the earth.
    This is the rule cable-sizing/build_800a_table.py uses.
  - A layout: where each core sits across the tray, for the 3D model.

The catalogue is vendor data and lives outside the public repo; without it
nothing can be sized and the caller gets a clear error.
"""
from __future__ import annotations

import importlib.util
import math
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CABLE_SIZING = os.path.join(HERE, "..", "cable-sizing")

#: Working room at each tray edge, as cable-sizing/ezystrut.py allows.
SIDE_CLEARANCE_MM = 25.0
#: Gap between one circuit and the next across the tray.
CIRCUIT_GAP_MM = 0.0          # touching, which is what the rating assumes
EARTH_GAP_MM = 6.0

_svc = None


def sizing_service():
    """cable-sizing/service.py, loaded by path (its name clashes here)."""
    global _svc
    if _svc is None:
        if CABLE_SIZING not in sys.path:
            sys.path.append(CABLE_SIZING)
        spec = importlib.util.spec_from_file_location(
            "cable_sizing_service", os.path.join(CABLE_SIZING, "service.py"))
        mod = importlib.util.module_from_spec(spec)
        sys.modules["cable_sizing_service"] = mod
        spec.loader.exec_module(mod)
        _svc = mod
    return _svc


RATING_KEYS = ("kw", "kva", "amps")
PASS_THROUGH = ("power_factor", "voltage_v", "phase_mode", "fault_level_ka",
                "clearing_time_s", "max_voltage_drop_pct",
                "harmonic_content_pct", "out_of_balance_pct", "ambient_c",
                "max_parallel", "cable_type", "circuit_use", "standard",
                "vd_supply", "vd_use", "protection_type", "mcb_curve",
                "mcb_rating_a", "dedicated_onsite_substation")


def _payload(c, length_m, n_circuits, method, defaults):
    p = {k: c.get(k, defaults.get(k)) for k in PASS_THROUGH
         if c.get(k, defaults.get(k)) is not None}
    given = [k for k in RATING_KEYS if c.get(k) is not None]
    if len(given) != 1:
        raise ValueError(f"circuit {c.get('id')!r}: give exactly one of "
                         f"kw, kva or amps")
    p.update(source_name=c.get("from") or "source",
             load_name=c.get("to") or c.get("id") or "load",
             rating_kind=given[0], rating_value=c[given[0]],
             route_length_m=round(length_m, 2), method=method,
             formation=c.get("formation") or defaults.get("formation")
             or "trefoil",
             n_circuits=n_circuits)
    p.setdefault("cable_type", "XLPE_SDI_CU")
    if c.get("area_mm2") is not None:
        p["area_mm2"] = c["area_mm2"]
        p["parallel"] = c.get("parallel", 1)
    return p


def _entry(cable_type):
    cat = sizing_service().CATALOG_()
    if cable_type not in cat["cables"]:
        raise ValueError(f"cable type {cable_type!r} not in the catalogue; "
                         f"have {sorted(cat['cables'])}")
    return cat["cables"][cable_type]


def _size_row(entry, area):
    if area is None:
        return {}
    return entry["sizes"].get(f"{area:g}") or {}


def bundle(r, cable_type, formation):
    """Cores, mass, footprint and core positions for one sized circuit."""
    entry = _entry(cable_type)
    # The engine's own construction rule, so the layout agrees with how the
    # cable was rated.
    multicore = sizing_service().cs._construction(entry) == "multicore"
    s = r["sizes"]
    par = s["parallel_runs"] or 1
    act = _size_row(entry, s["active_mm2"])
    neu = _size_row(entry, s["neutral_mm2"]) if s["neutral_mm2"] else {}
    ear = _size_row(entry, s["earth_mm2"]) if s["earth_mm2"] else {}
    od = act.get("od_mm")
    w_core = (act.get("weight_kg_100m") or 0) / 100
    cores = []                       # (role, od, x from left, height of centre)
    x = 0.0
    if multicore:
        for k in range(par):
            cores.append(("cable", od, x + od / 2, od / 2))
            x += od
        mass = par * w_core
        earth_od = 0.0
    else:
        has_n = bool(s["neutral_mm2"])
        n_od = neu.get("od_mm") or od
        for k in range(par):
            if formation == "trefoil":
                r_ = od / 2
                cores += [("A", od, x + r_, r_), ("B", od, x + 3 * r_, r_),
                          ("C", od, x + 2 * r_, r_ + r_ * math.sqrt(3))]
                x += 2 * od
            else:
                for i, ph in enumerate("ABC"):
                    cores.append((ph, od, x + od / 2, od / 2))
                    x += od
            if has_n:
                cores.append(("N", n_od, x + n_od / 2, n_od / 2))
                x += n_od
        mass = par * (3 * w_core + (has_n and (neu.get("weight_kg_100m")
                                               or 0) / 100))
        earth_od = ear.get("od_mm") or 0.0
        if earth_od:
            x += EARTH_GAP_MM
            cores.append(("E", earth_od, x + earth_od / 2, earth_od / 2))
            x += earth_od
            mass += (ear.get("weight_kg_100m") or 0) / 100
    height = max((c[3] + c[1] / 2 for c in cores), default=0.0)
    return {"multicore": multicore, "parallel": par, "od_mm": od,
            "earth_od_mm": earth_od or None, "mass_kg_per_m": round(mass, 3),
            "width_mm": round(x, 1), "height_mm": round(height, 1),
            "bend_radius_mm": act.get("bend_install_mm"),
            "cores": [{"role": c[0], "od_mm": c[1], "x_mm": round(c[2], 1),
                       "z_mm": round(c[3], 1)} for c in cores],
            "name": entry.get("name"), "voltage_kv": entry.get("voltage_kv")}


def describe(r, b):
    s = r["sizes"]
    par = s["parallel_runs"] or 1
    a = f"{s['active_mm2']:g}"
    if b["multicore"]:
        body = f"{a} mm² multicore"
    else:
        body = f"3 x 1C {a}"
        if s["neutral_mm2"]:
            body += f" + 1C {s['neutral_mm2']:g} N"
        body += " mm²"
    out = f"{par} x ({body})" if par > 1 else body
    if s["earth_mm2"] and not b["multicore"]:
        out += f" + 1C {s['earth_mm2']:g} mm² E"
    kv = b.get("voltage_kv")
    return f"{out}, {b['name']}" + (f", {kv:g}/1 kV" if kv == 0.6 else "")


def size_circuits(circuits, tray_length_m, method="touching", defaults=None,
                  max_rounds=6):
    """Size every circuit on one tray. Returns rows, totals and issues."""
    if not circuits:
        return None
    defaults = defaults or {}
    svc = sizing_service()
    ids = set()
    for k, c in enumerate(circuits):
        cid = c.get("id") or f"C{k + 1}"
        if cid in ids:
            raise ValueError(f"duplicate circuit id {cid!r}")
        ids.add(cid)
    runs = {k: int(c.get("parallel", 1)) for k, c in enumerate(circuits)}
    rounds = 0
    while True:
        rounds += 1
        n = sum(runs.values())
        results = []
        for k, c in enumerate(circuits):
            length = tray_length_m + float(c.get("tails_m", 0.0))
            p = _payload(c, length, n, method, defaults)
            r = svc.check(p) if "area_mm2" in p else svc.size(p)
            results.append((c, length, r, p))
        new = {k: (r["sizes"]["parallel_runs"] or 1)
               for k, (_, _, r, _) in enumerate(results)}
        if new == runs or rounds >= max_rounds:
            break
        runs = new

    rows, issues = [], []
    for k, (c, length, r, p) in enumerate(results):
        cid = c.get("id") or f"C{k + 1}"
        if not r["sizes"]["active_mm2"]:
            issues.append({"code": "circuit_unsized", "circuit": cid,
                           "message": f"{cid}: {r.get('failure_reason')}"})
            rows.append({"id": cid, "passed": False,
                         "failure_reason": r.get("failure_reason")})
            continue
        b = bundle(r, p["cable_type"], p["formation"])
        cur, vd = r["currents"], r["voltage_drop"]
        failed = [ch["name"] for ch in r["checks"] if not ch["passed"]]
        row = {
            "id": cid, "from": c.get("from"), "to": c.get("to"),
            "load": {key: c[key] for key in RATING_KEYS
                     if c.get(key) is not None},
            "cable": describe(r, b), "cable_type": p["cable_type"],
            "formation": p["formation"],
            "voltage_v": r["inputs"]["voltage_v"],
            "active_mm2": r["sizes"]["active_mm2"],
            "neutral_mm2": r["sizes"]["neutral_mm2"],
            "earth_mm2": r["sizes"]["earth_mm2"],
            "parallel": r["sizes"]["parallel_runs"],
            "length_m": round(length, 1),
            "design_a": round(cur["design_a"], 1),
            "capacity_a": round(cur["derated_capacity_a"], 1),
            "utilisation": round(cur["design_a"]
                                 / cur["derated_capacity_a"], 2)
            if cur["derated_capacity_a"] else None,
            "derating": r["derating"],
            "operating_temp_c": round(r["thermal"]["operating_temp_c"], 1)
            if r["thermal"]["operating_temp_c"] else None,
            "vd_v": round(vd["volts"], 2) if vd["volts"] is not None
            else None,
            "vd_pct": round(vd["percent"], 2) if vd["percent"] is not None
            else None,
            "vd_limit_pct": vd["limit_percent"],
            "fault_a": round(r["fault"]["current_a"])
            if r["fault"]["current_a"] else None,
            "max_loop_length_m": r["max_loop_length_m"],
            "passed": r["passed"], "failed_checks": failed,
            "warnings": r["warnings"][:5],
            "mass_kg_per_m": b["mass_kg_per_m"], "width_mm": b["width_mm"],
            "height_mm": b["height_mm"], "od_mm": b["od_mm"],
            "bend_radius_mm": b["bend_radius_mm"],
            "manufacturers": r.get("manufacturers"),
            "_cores": b["cores"],
        }
        if not r["passed"]:
            issues.append({"code": "circuit_fails", "circuit": cid,
                           "message": f"{cid}: fails "
                                      f"{', '.join(failed) or 'sizing'}; "
                                      f"{r.get('failure_reason') or ''}"})
        rows.append(row)
    sized = [r for r in rows if "mass_kg_per_m" in r]
    totals = {
        "circuits": len(rows),
        "grouped_runs": sum(runs.values()),
        "sizing_rounds": rounds,
        "mass_kg_per_m": round(sum(r["mass_kg_per_m"] for r in sized), 2),
        "width_mm": round(sum(r["width_mm"] for r in sized)
                          + CIRCUIT_GAP_MM * max(0, len(sized) - 1), 1),
        "height_mm": max((r["height_mm"] for r in sized), default=0.0),
        "max_bend_radius_mm": max((r["bend_radius_mm"] or 0
                                   for r in sized), default=0),
    }
    return {"rows": rows, "totals": totals, "issues": issues,
            "cable_bom": cable_bom(sized)}


def cable_bom(rows):
    """Metres of each cable to order: every core over the circuit length."""
    out = {}
    for r in rows:
        for core in r["_cores"]:
            role = core["role"]
            area = (r["earth_mm2"] if role == "E" else
                    r["neutral_mm2"] if role == "N" else r["active_mm2"])
            key = (r["cable_type"], area, "earth" if role == "E" else "")
            out[key] = out.get(key, 0.0) + r["length_m"]
    return [{"cable_type": k[0], "area_mm2": k[1],
             "use": k[2] or "active/neutral", "metres": round(v, 1)}
            for k, v in sorted(out.items(), key=lambda kv: (kv[0][0],
                                                            -kv[0][1]))]


def lay_out(rows, tray_width):
    """Each core's position across the tray: lateral offset from the tray
    centreline (+ is the tray's left) and height above the deck."""
    x = -tray_width / 2 + SIDE_CLEARANCE_MM
    out = []
    for r in rows:
        if "_cores" not in r:
            continue
        for core in r["_cores"]:
            out.append({"circuit": r["id"], "role": core["role"],
                        "od_mm": core["od_mm"],
                        "lateral_mm": round(x + core["x_mm"], 1),
                        "up_mm": core["z_mm"]})
        x += r["width_mm"] + CIRCUIT_GAP_MM
    return out
