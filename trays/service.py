"""The tray service: route a cable tray run and support it off the ground.

Plain dicts in and out, like piping/service.py, and served by the same MCP
and REST front ends. Units are mm and kg.

  {"id": "T-1",
   "tray": {"family": "NEMA3", "width": 600, "bend_radius": 600},
   "from": {"id": "TX1.LV", "pos": [...], "dir": [...]},
   "to":   {"id": "MSB.IN", "pos": [...], "dir": [...]},
   "points": [[...], ...]          # optional: support this route as drawn
   "cables": [{"id": "F-01", "kg_per_m": 8.2, "count": 4}],
   "obstacles": [{"id", "min", "max"}],
   "options": {...router options},
   "supports": {"growth": 0.25, "near_fitting_mm": 600, ...},
   "render": {"views": [...]}}     # optional: also draw it

`tray` is a family and width from the Ezystrut catalogue when that file is
present (it is vendor data, so not in the public repo), or a full
description: {family, width, overall_width, side_height, self_weight,
standard_length, load_ratings: [[span_mm, kg_per_m], ...], bend_radius}.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
sys.path.append(os.path.join(HERE, "..", "piping"))

import tray as T  # noqa: E402
from core.geom import Box, Nozzle, axis_dir, point  # noqa: E402
from core.render import VIEWS, render_sheet  # noqa: E402
from core.router import RouteOptions  # noqa: E402
from core.validate import validate_route  # noqa: E402

VERSION = "0.1.0"

STEEL = "#8a96a3"

_VEC = {"type": "array", "items": {"type": "number"}, "minItems": 3,
        "maxItems": 3}
_NOZZLE = {"type": "object", "required": ["pos", "dir"],
           "properties": {"id": {"type": "string"}, "pos": _VEC,
                          "dir": _VEC}}
TRAY_SCHEMA = {
    "type": "object",
    "required": ["from", "to", "tray"],
    "properties": {
        "id": {"type": "string"},
        "tray": {"type": "object", "required": ["family", "width"],
                 "description": "A catalogue family and width, e.g. NEMA3 "
                                "600, or a full description with "
                                "load_ratings [[span_mm, kg_per_m], ...].",
                 "properties": {"family": {"type": "string"},
                                "width": {"type": "number"},
                                "bend_radius": {"type": "number"}}},
        "from": {**_NOZZLE, "description": "Where the run starts; dir "
                                           "points the way the tray leaves."},
        "to": {**_NOZZLE, "description": "Where it ends; dir points out of "
                                         "the equipment, so the tray "
                                         "arrives against it."},
        "points": {"type": "array", "items": _VEC,
                   "description": "Support this route as drawn instead of "
                                  "routing it."},
        "cables": {"type": "array", "items": {
            "type": "object", "required": ["kg_per_m"],
            "properties": {"id": {"type": "string"},
                           "kg_per_m": {"type": "number"},
                           "count": {"type": "integer", "default": 1}}}},
        "cable_kg_per_m": {"type": "number",
                           "description": "Total cable load, instead of "
                                          "cables."},
        "obstacles": {"type": "array", "items": {
            "type": "object", "required": ["min", "max"],
            "properties": {"id": {"type": "string"}, "min": _VEC,
                           "max": _VEC}}},
        "options": {"type": "object", "description": "Router options, as "
                                                     "for piping."},
        "supports": {"type": "object", "properties": {
            "growth": {"type": "number", "default": 0.25},
            "near_fitting_mm": {"type": "number", "default": 600},
            "splice_fraction": {"type": "number", "default": 0.25},
            "floor_z_mm": {"type": "number", "default": 0},
            "clearance_mm": {"type": "number", "default": 50},
            "max_post_height_mm": {"type": "number", "default": 4000}}},
        "render": {"type": "object", "properties": {
            "views": {"type": "array", "items": {"enum": list(VIEWS)}},
            "title": {"type": "string"}}},
    },
}

_catalogue = None


def _load_catalogue():
    global _catalogue
    if _catalogue is None and os.path.exists(T.CATALOGUE):
        with open(T.CATALOGUE) as fh:
            _catalogue = json.load(fh)
    return _catalogue


def _tray(v):
    if not isinstance(v, dict):
        raise ValueError("tray must be an object")
    if "load_ratings" in v:
        try:
            return T.TrayType(
                family=str(v["family"]), width=float(v["width"]),
                overall_width=float(v.get("overall_width", v["width"])),
                side_height=float(v["side_height"]),
                self_weight=float(v["self_weight"]),
                standard_length=float(v["standard_length"]),
                load_ratings=tuple((float(s), float(r))
                                   for s, r in v["load_ratings"]),
                bend_radius=float(v.get("bend_radius", v["width"])),
                part=str(v.get("part", "")))
        except KeyError as e:
            raise ValueError(f"tray description is missing {e}") from None
    cat = _load_catalogue()
    if cat is None:
        raise ValueError("the tray catalogue is not on this server; give "
                         "the tray in full, with load_ratings")
    return T.tray_from_catalogue(cat, v.get("family"), int(v.get("width")),
                                 v.get("bend_radius"))


def _nozzle(v, what):
    if not isinstance(v, dict):
        raise ValueError(f"{what} must be an object")
    return Nozzle(str(v.get("id") or what), point(v.get("pos"), f"{what}.pos"),
                  axis_dir(v.get("dir"), f"{what}.dir"))


def _load(req):
    if req.get("cables"):
        return sum(float(c["kg_per_m"]) * int(c.get("count", 1))
                   for c in req["cables"])
    if req.get("cable_kg_per_m") is not None:
        return float(req["cable_kg_per_m"])
    raise ValueError("give cables [{kg_per_m, count}] or cable_kg_per_m; "
                     "support spacing depends on the load")


def _support_options(v):
    v = dict(v or {})
    known = {"growth", "near_fitting_mm", "splice_fraction", "floor_z_mm",
             "clearance_mm", "max_post_height_mm", "post_gap_mm",
             "slide_step_mm"}
    bad = set(v) - known
    if bad:
        raise ValueError(f"unknown support options {sorted(bad)}")
    return T.SupportOptions(**{k: float(x) for k, x in v.items()})


def route_and_support(req: dict) -> dict:
    if not isinstance(req, dict):
        raise ValueError("request must be an object")
    tray = _tray(req.get("tray"))
    a, b = _nozzle(req.get("from"), "from"), _nozzle(req.get("to"), "to")
    obstacles = [Box(str(o.get("id", f"obstacle{k}")),
                     point(o["min"], "min"), point(o["max"], "max"))
                 for k, o in enumerate(req.get("obstacles") or [])]
    load = _load(req)
    sopts = _support_options(req.get("supports"))
    rid = str(req.get("id") or "T-1")
    digest = hashlib.sha256(json.dumps(
        {k: v for k, v in req.items() if k != "render"}, sort_keys=True,
        default=str).encode()).hexdigest()
    out = {"id": rid, "request_sha256": digest, "version": VERSION}

    if req.get("points"):
        pts = [point(p, f"points[{k}]") for k, p in
               enumerate(req["points"])]
        out["route"] = "given"
    else:
        ro = RouteOptions(**{k: v for k, v in (req.get("options") or {})
                             .items()})
        if ro.floor_z_mm is None:
            ro.floor_z_mm = sopts.floor_z_mm
        res = T.route_tray(tray, a, b, obstacles, ro)
        if not res.ok:
            out.update(status="failed", **res.failure)
            return _maybe_render(out, req, tray, a, b, obstacles, None, None)
        pts = res.points
        out["route"] = "routed"
    issues = validate_route(pts, T._RouterSpec(tray), a, b, obstacles,
                            (req.get("options") or {}).get("clearance_mm",
                                                           50.0))
    sup = T.support_run(pts, tray, load, obstacles, sopts, rid)
    out.update(points=[[round(c, 1) for c in p] for p in pts],
               route_issues=issues, **{k: v for k, v in sup.items()
                                       if k != "id"})
    problems = issues or sup["issues"]
    out["status"] = "supported" if not problems else "needs_attention"
    return _maybe_render(out, req, tray, a, b, obstacles, pts, sup)


def _maybe_render(out, req, tray, a, b, obstacles, pts, sup):
    r = req.get("render")
    if r is None:
        return out
    if not isinstance(r, dict):
        raise ValueError("render must be an object")
    views = tuple(r.get("views") or ("plan", "front", "iso"))
    boxes = [{"id": o.id, "min": list(o.lo), "max": list(o.hi)}
             for o in obstacles]
    if sup:
        for s in sup["supports"]:
            for bx in s["boxes"]:
                boxes.append({**bx, "id": f"{s['id']}/{bx['id']}",
                              "label": "", "fill": STEEL})
    drawn = {"id": out["id"], "od": tray.overall_width,
             "band": [tray.overall_width, tray.side_height],
             "bend_radius": tray.centre_bend_radius, "service": "tray",
             "colour": "#d18f00", "from_pos": list(a.pos),
             "to_pos": list(b.pos)}
    if pts:
        bad = {i["segment"] for i in out.get("route_issues", [])
               if "segment" in i}
        drawn.update(points=[list(p) for p in pts],
                     issues=[{"segment": i} for i in bad])
    else:
        drawn["reason"] = out.get("reason", "failed")
    n = len(sup["supports"]) if sup else 0
    note = (f"{tray.family} {tray.width:g}, {out.get('design_kg_per_m', '?')}"
            f" kg/m design load, span {out.get('span_mm', '?')} mm, "
            f"{n} supports. sd-dc trays {VERSION}, request "
            f"{out['request_sha256'][:12]}")
    issues = [i["message"] for i in (sup or {}).get("issues", [])][:3]
    out["svg"] = render_sheet(
        boxes, [drawn], views, title=r.get("title") or f"Tray {out['id']}",
        notes=[note] + issues + ["Draft: support ratings are unverified "
                                 "AU01-2 drawing values; not a structural "
                                 "design."],
        labels=("plan",))
    return out
