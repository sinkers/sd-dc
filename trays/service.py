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
import math
import os
import re
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(HERE)
sys.path.append(os.path.join(HERE, "..", "piping"))

import cables as C  # noqa: E402
import model3d as M  # noqa: E402
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
        "circuits": {
            "type": "array",
            "description": "Circuits to size with the cable sizing "
                           "calculator (AS/NZS 3008) and lay on this tray. "
                           "Replaces cables and cable_kg_per_m: their mass "
                           "drives the supports. Length is the tray route "
                           "plus tails_m.",
            "items": {"type": "object", "properties": {
                "id": {"type": "string"},
                "from": {"type": "string"}, "to": {"type": "string"},
                "kw": {"type": "number"}, "kva": {"type": "number"},
                "amps": {"type": "number"},
                "power_factor": {"type": "number", "default": 0.9},
                "voltage_v": {"type": "number", "default": 415},
                "cable_type": {"type": "string", "default": "XLPE_SDI_CU"},
                "formation": {"enum": ["trefoil", "flat_touching"],
                              "default": "trefoil"},
                "tails_m": {"type": "number", "default": 0,
                            "description": "Cable beyond the tray, both "
                                           "ends together (drops into "
                                           "boards)."},
                "ambient_c": {"type": "number"},
                "fault_level_ka": {"type": "number"},
                "max_voltage_drop_pct": {"type": "number"},
                "harmonic_content_pct": {"type": "number"},
                "area_mm2": {"type": "number",
                             "description": "Check this size instead of "
                                            "selecting one."},
                "parallel": {"type": "integer"}}}},
        "circuit_defaults": {"type": "object",
                             "description": "Fields applied to every "
                                            "circuit that does not set "
                                            "them, e.g. ambient_c."},
        "install_method": {"type": "string", "default": "touching"},
        "model": {"type": "object", "description": "Build the 3D model: "
                  "ladder, supports and every core as solids, FCStd and "
                  "STEP, when FreeCAD is installed on the server.",
                  "properties": {
                      "build": {"type": "boolean", "default": True},
                      "include_spec": {"type": "boolean", "default": False},
                      "context": {"type": "boolean", "default": True}}},
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
    circuits = req.get("circuits")
    if circuits is not None and (not isinstance(circuits, list)
                                 or not circuits):
        raise ValueError("circuits must be a non-empty list")
    load = None if circuits else _load(req)
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
    tray_m = sum(math.dist(pts[i], pts[i + 1])
                 for i in range(len(pts) - 1)) / 1000
    out["tray_length_m"] = round(tray_m, 2)
    sized, layout, cable_issues = None, [], []
    if circuits:
        sized = C.size_circuits(circuits, tray_m,
                                method=req.get("install_method", "touching"),
                                defaults=req.get("circuit_defaults") or {})
        load = sized["totals"]["mass_kg_per_m"]
        layout = C.lay_out(sized["rows"], tray.width)
        cable_issues = sized["issues"] + _fit_checks(sized["totals"], tray)
    sup = T.support_run(pts, tray, load, obstacles, sopts, rid)
    out.update(points=[[round(c, 1) for c in p] for p in pts],
               route_issues=issues, **{k: v for k, v in sup.items()
                                       if k != "id"})
    if sized:
        out["circuits"] = [{k: v for k, v in r.items() if k != "_cores"}
                           for r in sized["rows"]]
        out["cable_totals"] = sized["totals"]
        out["cable_bom"] = sized["cable_bom"]
        out["cable_issues"] = cable_issues
    problems = issues or sup["issues"] or cable_issues
    out["status"] = "supported" if not problems else "needs_attention"
    if req.get("model"):
        out["model"] = _model(req["model"], rid, pts, tray, sup, layout,
                              req.get("obstacles") or [])
    return _maybe_render(out, req, tray, a, b, obstacles, pts, sup)


def _fit_checks(totals, tray):
    """Does the cable fit across and within the tray, and round its bends."""
    out = []
    need = totals["width_mm"] + 2 * C.SIDE_CLEARANCE_MM
    if need > tray.width:
        out.append({"code": "tray_full",
                    "message": f"cables need {need:.0f} mm of width with "
                               f"{C.SIDE_CLEARANCE_MM:g} mm each side; "
                               f"{tray.family} {tray.width:g} has "
                               f"{tray.width:g} mm. Use a wider tray, a "
                               f"second tray, or fewer circuits",
                    "need_mm": round(need), "have_mm": tray.width})
    if totals["height_mm"] > tray.side_height:
        out.append({"code": "above_rails",
                    "message": f"cables stand {totals['height_mm']:.0f} mm, "
                               f"above the {tray.side_height:g} mm rails"})
    if totals["max_bend_radius_mm"] > tray.bend_radius:
        out.append({"code": "bend_too_tight",
                    "message": f"largest cable needs a "
                               f"{totals['max_bend_radius_mm']:g} mm bend "
                               f"radius; tray bends are "
                               f"{tray.bend_radius:g} mm inside radius"})
    return out


FREECADCMD_CANDIDATES = (
    "/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd",
    "/usr/bin/freecadcmd", "/usr/local/bin/freecadcmd")
MODEL_DIR = os.environ.get("TRAY_MODEL_DIR") or os.path.join(HERE, "out",
                                                             "models")


def freecadcmd():
    exe = os.environ.get("FREECADCMD") or shutil.which("freecadcmd")
    if exe:
        return exe
    return next((p for p in FREECADCMD_CANDIDATES if os.path.exists(p)), None)


def _model(m, rid, pts, tray, sup, layout, obstacles):
    """The 3D model: always the build spec; solids too when FreeCAD is here.

    Files go under MODEL_DIR (TRAY_MODEL_DIR), named from the run id, so a
    caller cannot choose where on the server they land.
    """
    if not isinstance(m, dict):
        m = {}
    spec = M.build_spec(pts, tray, sup["supports"], layout,
                        obstacles if m.get("context", True) else (),
                        name=rid)
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", rid)[:80] or "tray"
    out = {"primitives": len(spec["primitives"]),
           "groups": sorted(spec["groups"])}
    if m.get("include_spec"):
        out["spec"] = spec
    if m.get("build", True) is False:
        out["built"] = False
        return out
    exe = freecadcmd()
    if not exe:
        out.update(built=False, note="FreeCAD is not installed here; build "
                   "the spec with freecad_build.py on the CAD host")
        return out
    os.makedirs(MODEL_DIR, exist_ok=True)
    base = os.path.join(MODEL_DIR, safe)
    with open(base + ".spec.json", "w") as fh:
        json.dump(spec, fh)
    env = {**os.environ, "TRAY_SPEC": base + ".spec.json", "TRAY_OUT": base}
    try:
        subprocess.run([exe, os.path.join(HERE, "freecad_build.py")],
                       env=env, capture_output=True, timeout=600, check=True)
        with open(base + ".build.json") as fh:
            out.update(built=True, **json.load(fh))
    except (subprocess.SubprocessError, OSError, ValueError) as exc:
        out.update(built=False, error=f"{type(exc).__name__}: {exc}")
    return out


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
