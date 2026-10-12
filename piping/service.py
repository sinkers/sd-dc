"""The piping service: plain dicts in, plain dicts out.

This is the only implementation behind the MCP servers and the REST API, so an
agent and a person asking the same question get the same answer. It imports
nothing from FreeCAD; geometry is built elsewhere from the centreline it
returns.

Units are millimetres throughout. A nozzle is {"id", "pos": [x, y, z],
"dir": [dx, dy, dz], "dn"?}, the same fields as a catalogue port in
PLAN.md 0.1, so a catalogue port can be passed straight in. `dir` points out
of the equipment face. An obstacle is {"id", "min": [x, y, z], "max": [...]}.

A route that cannot be built comes back as status "failed" with a reason
(blocked_nozzle, enclosed_inlet, enclosed_outlet, no_path,
no_path_within_budget), the nozzle and obstacle involved, what was measured
and what would fix it. Bad input raises ValueError with a message the caller
can act on.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict

from core import (Box, Nozzle, RouteOptions, centreline_parts, list_specs,
                  route_network, route_pipe, spec_for, validate_route)
from core.geom import axis_dir, point, segment_box
from core.specs import SCH10S

VERSION = "0.1.0"

LIMITS = {
    "obstacles": 5000,
    "pipes": 200,
    "points": 200,
    "max_expansions": 2_000_000,
    "grid_mm_min": 25.0,
}

DEFAULT_OPTIONS = {
    "clearance_mm": 50.0,
    "grid_mm": 250.0,
    "bend_cost_mm": 1000.0,
    "margin_mm": 2000.0,
    "max_expansions": 200_000,
    "floor_z_mm": None,
}

FAILURE_REASONS = {
    "blocked_nozzle": "an obstacle sits too close in front of a nozzle for "
                      "the first elbow",
    "enclosed_inlet": "the inlet's straight approach has no corner that can "
                      "turn away",
    "enclosed_outlet": "the outlet's straight run has no corner that can "
                       "turn away",
    "no_path": "every route inside the search box is blocked",
    "no_path_within_budget": "the search stopped at max_expansions",
}

RULES = [
    "a pipe runs from one outlet to one inlet",
    "the first run leaves along the outlet's dir; the last arrives against "
    "the inlet's dir",
    "runs follow the x, y or z axis; every elbow is 90 degrees, never 180",
    "elbows are long radius, BR = 1.5 x OD",
    "runs next to a nozzle are at least 1 x BR; runs between elbows at "
    "least 2 x BR",
    "every run keeps radius + clearance_mm from every obstacle, except the "
    "obstacle a nozzle sits on, and pipes meeting at a shared nozzle only "
    "have to not touch there",
    "in a batch, each routed pipe is an obstacle for the ones after it",
]

_ID = re.compile(r"^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$")

# --------------------------------------------------------------- schemas
# Shared by the MCP tool list and the OpenAPI description.

_VEC = {"type": "array", "items": {"type": "number"}, "minItems": 3,
        "maxItems": 3}
NOZZLE_SCHEMA = {
    "type": "object",
    "required": ["pos", "dir"],
    "properties": {
        "id": {"type": "string",
               "description": "Interface id, e.g. CDU-05.chw_out."},
        "pos": {**_VEC, "description": "Centre of the connection face, mm."},
        "dir": {**_VEC, "description": "Outward direction from the "
                                       "equipment face; must be along an "
                                       "axis."},
        "dn": {"type": "integer", "description": "Nominal size, if the "
                                                 "request does not give one."},
    },
}
OBSTACLE_SCHEMA = {
    "type": "object",
    "required": ["min", "max"],
    "properties": {"id": {"type": "string"}, "min": _VEC, "max": _VEC},
}
OPTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "clearance_mm": {"type": "number", "default": 50,
                         "description": "Gap kept between the pipe surface "
                                        "and any obstacle."},
        "grid_mm": {"type": "number", "default": 250,
                    "description": "Spacing of the regular corner grid. "
                                   "Nozzles and obstacle faces are always "
                                   "candidate corners as well."},
        "bend_cost_mm": {"type": "number", "default": 1000,
                         "description": "An elbow costs as much as this "
                                        "much pipe."},
        "margin_mm": {"type": "number", "default": 2000,
                      "description": "How far the search may go beyond the "
                                     "box around the two nozzles."},
        "max_expansions": {"type": "integer", "default": 200000},
        "floor_z_mm": {"type": ["number", "null"],
                       "description": "Keep the pipe above this level."},
    },
}
PIPE_FIELDS = {
    "id": {"type": "string", "description": "Line id, e.g. P-W-12."},
    "dn": {"type": "integer", "enum": sorted(SCH10S)},
    "schedule": {"type": "string", "enum": ["10S"], "default": "10S"},
    "from": {**NOZZLE_SCHEMA, "description": "Outlet nozzle."},
    "to": {**NOZZLE_SCHEMA, "description": "Inlet nozzle."},
}
ROUTE_SCHEMA = {
    "type": "object",
    "required": ["from", "to"],
    "properties": {**PIPE_FIELDS,
                   "obstacles": {"type": "array", "items": OBSTACLE_SCHEMA},
                   "options": OPTIONS_SCHEMA},
}
NETWORK_SCHEMA = {
    "type": "object",
    "required": ["pipes"],
    "properties": {
        "pipes": {"type": "array", "items": {
            "type": "object", "required": ["from", "to"],
            "properties": PIPE_FIELDS},
            "description": "Routed in this order; each routed pipe becomes "
                           "an obstacle for the rest."},
        "obstacles": {"type": "array", "items": OBSTACLE_SCHEMA},
        "options": OPTIONS_SCHEMA,
    },
}
VALIDATE_SCHEMA = {
    "type": "object",
    "required": ["points"],
    "properties": {
        "dn": PIPE_FIELDS["dn"],
        "schedule": PIPE_FIELDS["schedule"],
        "points": {"type": "array", "items": _VEC,
                   "description": "Corner points, outlet first."},
        "from": PIPE_FIELDS["from"],
        "to": PIPE_FIELDS["to"],
        "obstacles": {"type": "array", "items": OBSTACLE_SCHEMA},
        "options": {"type": "object", "properties": {
            "clearance_mm": OPTIONS_SCHEMA["properties"]["clearance_mm"]}},
    },
}

# --------------------------------------------------------------- parsing


def _obj(v, what):
    if not isinstance(v, dict):
        raise ValueError(f"{what} must be an object")
    return v


def _nozzle(v, what):
    v = _obj(v, what)
    for k in ("pos", "dir"):
        if k not in v:
            raise ValueError(f"{what} needs {k!r}")
    nid = str(v.get("id") or what)
    return Nozzle(nid, point(v["pos"], f"{what}.pos"),
                  axis_dir(v["dir"], f"{what}.dir"))


def _spec(req, what="request"):
    dn = req.get("dn")
    if dn is None:
        dns = {n.get("dn") for n in (req.get("from") or {}, req.get("to") or {})
               if isinstance(n, dict) and n.get("dn") is not None}
        if len(dns) > 1:
            raise ValueError(f"{what}: nozzles disagree on dn {sorted(dns)}; "
                             f"give dn explicitly")
        dn = dns.pop() if dns else None
    if dn is None:
        raise ValueError(f"{what} needs dn (or dn on a nozzle)")
    try:
        dn = int(dn)
    except (TypeError, ValueError):
        raise ValueError(f"{what}: dn must be an integer, got {dn!r}")
    return spec_for(dn, req.get("schedule", "10S"))


def _obstacles(v):
    v = v or []
    if not isinstance(v, list):
        raise ValueError("obstacles must be a list")
    if len(v) > LIMITS["obstacles"]:
        raise ValueError(f"at most {LIMITS['obstacles']} obstacles")
    out = []
    for k, o in enumerate(v):
        o = _obj(o, f"obstacles[{k}]")
        lo = point(o.get("min", ()), f"obstacles[{k}].min")
        hi = point(o.get("max", ()), f"obstacles[{k}].max")
        if any(lo[i] >= hi[i] for i in range(3)):
            raise ValueError(f"obstacles[{k}]: min must be below max on "
                             f"every axis")
        out.append(Box(str(o.get("id") or f"obstacle-{k}"), lo, hi))
    return out


def _options(v):
    v = _obj(v or {}, "options")
    unknown = set(v) - set(DEFAULT_OPTIONS)
    if unknown:
        raise ValueError(f"unknown options {sorted(unknown)}; expected "
                         f"{sorted(DEFAULT_OPTIONS)}")
    o = {**DEFAULT_OPTIONS, **{k: x for k, x in v.items() if x is not None
                               or k == "floor_z_mm"}}
    for k in ("clearance_mm", "grid_mm", "bend_cost_mm", "margin_mm"):
        o[k] = float(o[k])
        if not math.isfinite(o[k]) or o[k] < 0:
            raise ValueError(f"options.{k} must be a non-negative number")
    if o["grid_mm"] < LIMITS["grid_mm_min"]:
        raise ValueError(f"options.grid_mm must be at least "
                         f"{LIMITS['grid_mm_min']:.0f}")
    o["max_expansions"] = int(o["max_expansions"])
    if not 1 <= o["max_expansions"] <= LIMITS["max_expansions"]:
        raise ValueError(f"options.max_expansions must be 1 to "
                         f"{LIMITS['max_expansions']}")
    if o["floor_z_mm"] is not None:
        o["floor_z_mm"] = float(o["floor_z_mm"])
    return o


def _hash(obj):
    blob = json.dumps({"v": VERSION, "req": obj}, sort_keys=True,
                      separators=(",", ":"), default=str)
    return hashlib.sha256(blob.encode()).hexdigest()


# --------------------------------------------------------------- results


def _summary(points, spec):
    parts = centreline_parts(points, spec)
    straight = sum(p["length_mm"] for p in parts if p["type"] == "straight")
    arcs = sum(p["arc_mm"] for p in parts if p["type"] == "elbow")
    elbows = sum(1 for p in parts if p["type"] == "elbow")
    corner = sum(math.dist(points[i], points[i + 1])
                 for i in range(len(points) - 1))
    return parts, {
        "elbows": elbows,
        "straight_mm": round(straight, 1),
        "elbow_arc_mm": round(arcs, 1),
        "centreline_mm": round(straight + arcs, 1),
        "corner_to_corner_mm": round(corner, 1),
    }


def _bom(rows):
    """rows: (spec, summary). One pipe line and one elbow line per DN."""
    pipe, elbows = defaultdict(float), defaultdict(int)
    for spec, s in rows:
        pipe[(spec.dn, spec.schedule)] += s["straight_mm"]
        elbows[(spec.dn, spec.schedule)] += s["elbows"]
    out = []
    for dn, sch in sorted(pipe):
        out.append({"item": "pipe", "dn": dn, "schedule": sch,
                    "length_m": round(pipe[(dn, sch)] / 1000, 3)})
        if elbows[(dn, sch)]:
            out.append({"item": "elbow 90 LR", "dn": dn, "schedule": sch,
                        "count": elbows[(dn, sch)]})
    return out


def _fragment(pid, spec, a, b, points, summary, digest):
    """An IndustroML v1 connection, ready to write into the model."""
    ids = (pid, a.id, b.id)
    if not all(isinstance(i, str) and _ID.match(i) for i in ids):
        return None, ("ids must match IndustroML's id pattern "
                      "^[A-Za-z0-9]+(?:[._-][A-Za-z0-9]+)*$ to emit a "
                      "connection")
    return {
        "id": pid, "type": "pipe", "from": a.id, "to": b.id,
        "attributes": {
            "dn": spec.dn, "schedule": spec.schedule, "od_mm": spec.od,
            "bend_radius_mm": round(spec.bend_radius, 2),
            "elbows": summary["elbows"],
            "length_m": round(summary["centreline_mm"] / 1000, 3),
            "path_mm": [[round(c, 2) for c in p] for p in points],
            "routed_by": f"sd-dc piping {VERSION}",
            "request_sha256": digest,
        },
    }, None


def _result(pid, spec, a, b, res, obstacles, opts, digest):
    base = {"id": pid, "from": a.id, "to": b.id, "spec": spec.as_dict(),
            "request_sha256": digest,
            "stats": {"expansions": res.expansions, "ms": round(res.ms, 1)}}
    if not res.ok:
        return {"status": "failed", **base, **res.failure}
    points = [list(map(lambda c: round(c, 3), p)) for p in res.points]
    parts, summary = _summary(res.points, spec)
    issues = validate_route(res.points, spec, a, b, obstacles,
                            opts["clearance_mm"])
    frag, note = _fragment(pid, spec, a, b, res.points, summary, digest)
    out = {"status": "routed", **base, "points": points, "parts": parts,
           "summary": summary, "bom": _bom([(spec, summary)]),
           "validation": {"ok": not issues, "issues": issues}}
    if frag:
        out["industroml"] = frag
    else:
        out["industroml_note"] = note
    return out


def _route_options(o):
    return RouteOptions(**o)


# ------------------------------------------------------------- endpoints


def route(req: dict) -> dict:
    """Route one pipe from an outlet nozzle to an inlet nozzle."""
    req = _obj(req, "request")
    spec = _spec(req)
    a, b = _nozzle(req.get("from"), "from"), _nozzle(req.get("to"), "to")
    obstacles = _obstacles(req.get("obstacles"))
    opts = _options(req.get("options"))
    pid = str(req.get("id") or f"{a.id}-{b.id}")
    digest = _hash({"id": pid, "dn": spec.dn, "from": req["from"],
                    "to": req["to"], "obstacles": req.get("obstacles") or [],
                    "options": opts})
    res = route_pipe(spec, a, b, obstacles, _route_options(opts))
    return _result(pid, spec, a, b, res, obstacles, opts, digest)


def route_batch(req: dict) -> dict:
    """Route pipes in order; each routed pipe is an obstacle for the rest."""
    req = _obj(req, "request")
    pipes = req.get("pipes")
    if not isinstance(pipes, list) or not pipes:
        raise ValueError("pipes must be a non-empty list")
    if len(pipes) > LIMITS["pipes"]:
        raise ValueError(f"at most {LIMITS['pipes']} pipes per batch")
    obstacles = _obstacles(req.get("obstacles"))
    opts = _options(req.get("options"))
    items, ids = [], set()
    for k, p in enumerate(pipes):
        p = _obj(p, f"pipes[{k}]")
        a = _nozzle(p.get("from"), f"pipes[{k}].from")
        b = _nozzle(p.get("to"), f"pipes[{k}].to")
        pid = str(p.get("id") or f"{a.id}-{b.id}")
        if pid in ids:
            raise ValueError(f"pipes[{k}]: duplicate id {pid!r}")
        ids.add(pid)
        items.append((pid, _spec(p, f"pipes[{k}]"), a, b))
    digest = _hash({"pipes": pipes, "obstacles": req.get("obstacles") or [],
                    "options": opts})
    results = []
    placed = list(obstacles)
    for (pid, spec, a, b), (_, res) in zip(
            items, route_network(items, obstacles, _route_options(opts))):
        results.append(_result(pid, spec, a, b, res, placed, opts,
                               _hash({"batch": digest, "id": pid})))
        if res.ok:
            placed += [segment_box(res.points[i], res.points[i + 1],
                                   spec.radius, f"{pid}/run{i}",
                                   (a.pos, b.pos))
                       for i in range(len(res.points) - 1)]
    ok = [r for r in results if r["status"] == "routed"]
    specs = {pid: spec for pid, spec, _, _ in items}
    return {
        "status": ("routed" if len(ok) == len(results)
                   else "partial" if ok else "failed"),
        "routed": len(ok), "failed": len(results) - len(ok),
        "request_sha256": digest,
        "bom": _bom([(specs[r["id"]], r["summary"]) for r in ok]),
        "results": results,
    }


def validate(req: dict) -> dict:
    """Check corner points someone drew against the routing rules."""
    req = _obj(req, "request")
    pts = req.get("points")
    if not isinstance(pts, list) or len(pts) > LIMITS["points"]:
        raise ValueError(f"points must be a list of at most "
                         f"{LIMITS['points']} [x, y, z]")
    pts = [point(p, f"points[{k}]") for k, p in enumerate(pts)]
    spec = _spec(req)
    a = _nozzle(req["from"], "from") if req.get("from") else None
    b = _nozzle(req["to"], "to") if req.get("to") else None
    obstacles = _obstacles(req.get("obstacles"))
    clearance = float(_obj(req.get("options") or {}, "options")
                      .get("clearance_mm", DEFAULT_OPTIONS["clearance_mm"]))
    issues = validate_route(pts, spec, a, b, obstacles, clearance)
    out = {"ok": not issues, "issues": issues, "spec": spec.as_dict()}
    if len(pts) >= 2 and not any(i["code"] in ("not_orthogonal",)
                                 for i in issues):
        _, out["summary"] = _summary(pts, spec)
    return out


def specs() -> dict:
    return {"schedule": "10S", "bend_radius": "1.5 x OD (long radius)",
            "sizes": list_specs()}


def meta() -> dict:
    return {"service": "sd-dc piping", "version": VERSION, "units": "mm",
            "rules": RULES, "failure_reasons": FAILURE_REASONS,
            "defaults": DEFAULT_OPTIONS, "limits": LIMITS}
