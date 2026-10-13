"""A tray run as solids to build: ladder, supports and the cables in it.

No FreeCAD here. This turns a routed tray, its supports and its cable layout
into a list of primitives, which freecad_build.py turns into solids on any
machine with FreeCAD (the CAD host, or a workstation). Keeping the geometry
decisions here means they can be tested without a CAD kernel, and the
FreeCAD side is a dumb interpreter.

Every primitive is a planar profile, a rectangle or a circle, placed in a
frame at a point on the tray, then either extruded along a straight or
revolved about a bend's axis. That one rule gives straights, horizontal
bends and risers for rails and cables alike: the profile keeps its place in
the tray's cross-section, so a cable on the inside of a bend follows a
tighter arc than one on the outside, as it does on site.

  {"kind": "extrude", "group", "profile": "rect"|"circle",
   "at": [x,y,z], "u": [...], "v": [...], "w", "h" | "r",
   "dir": [...], "length"}
  {"kind": "revolve", ...same profile..., "centre": [...], "axis": [...],
   "angle": 90}
  {"kind": "box", "group", "min", "max"}

u is the tray's lateral axis (left), v its up axis, so a profile centred at
at + u*a + v*b. Bends use the fitting's centreline radius.
"""
from __future__ import annotations

import math

RAIL_T = 3.0           # side rail thickness, mm
RUNG_PITCH = 300.0     # ladder rung spacing, mm
RUNG = (25.0, 20.0)    # rung along-run x height, mm

COLOURS = {"tray": "#c9a227", "supports": "#8a96a3", "context": "#d9dde3"}
CIRCUIT_COLOURS = ["#1f6fd1", "#d1402b", "#1b9e77", "#7b4fc9", "#e08a00",
                   "#00838f", "#b0569b", "#5d7a1f"]


def _sub(a, b):
    return tuple(a[i] - b[i] for i in range(3))


def _add(a, b, k=1.0):
    return tuple(a[i] + b[i] * k for i in range(3))


def _cross(a, b):
    return (a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2],
            a[0] * b[1] - a[1] * b[0])


def _dot(a, b):
    return sum(a[i] * b[i] for i in range(3))


def _unit(a):
    n = math.sqrt(_dot(a, a))
    return tuple(c / n for c in a)


def _rot90(v, k):
    """v rotated +90 degrees about unit axis k (Rodrigues, cos 0, sin 1)."""
    return _add(_cross(k, v), k, _dot(k, v))


def frames(points, radius):
    """Pieces of the centreline with the tray frame on each.

    Returns a list of ("straight", start, dir, length, u, v) and
    ("bend", t1, a, b, centre, axis, u, v) in order. u, v are the frame at
    the start of the piece.
    """
    pts = [tuple(map(float, p)) for p in points]
    dirs = [_unit(_sub(pts[i + 1], pts[i])) for i in range(len(pts) - 1)]
    a0 = dirs[0]
    if abs(a0[2]) < 0.5:
        v = (0.0, 0.0, 1.0)
    else:
        # A run that starts vertical: lay the deck facing the way it turns.
        nxt = next((d for d in dirs if abs(d[2]) < 0.5), (1.0, 0.0, 0.0))
        v = tuple(-c for c in nxt)
    out = []
    pos = pts[0]
    n = len(dirs)
    for i, a in enumerate(dirs):
        u = _cross(v, a)
        end = pts[i + 1]
        if i < n - 1:
            b = dirs[i + 1]
            t1 = _add(end, a, -radius)
            length = math.dist(pos, t1)
            if length > 0.5:
                out.append(("straight", pos, a, length, u, v))
            k = _unit(_cross(a, b))
            centre = _add(t1, b, radius)
            out.append(("bend", t1, a, b, centre, k, u, v))
            # The frame turns with the bend.
            v = _rot90(v, k)
            pos = _add(end, b, radius)
        else:
            length = math.dist(pos, end)
            if length > 0.5:
                out.append(("straight", pos, a, length, u, v))
    return out


def _sweep(piece, group, profile, offset, size, colour=None):
    """One profile carried along one piece of centreline."""
    u, v = piece[-2], piece[-1]
    if piece[0] == "straight":
        _, start, a, length, _, _ = piece
        prim = {"kind": "extrude", "at": list(start), "dir": list(a),
                "length": length}
    else:
        _, t1, a, b, centre, k, _, _ = piece
        prim = {"kind": "revolve", "at": list(t1), "centre": list(centre),
                "axis": list(k), "angle": 90.0}
    prim.update(group=group, profile=profile, u=list(u), v=list(v),
                offset=list(offset))
    if profile == "circle":
        prim["r"] = size
    else:
        prim["w"], prim["h"] = size
    if colour:
        prim["colour"] = colour
    return prim


def build_spec(points, tray, supports=(), layout=(), obstacles=(),
               name="tray"):
    """Primitives for a ladder tray, its supports, its cables and context.

    tray: TrayType (width, overall_width, side_height, centre_bend_radius).
    layout: cables.lay_out() rows: circuit, od_mm, lateral_mm, up_mm.
    """
    R = tray.centre_bend_radius
    W, H = tray.width, tray.side_height
    deck = -H / 2 + RUNG[1]                 # rung top, from the centreline
    pieces = frames(points, R)
    prims = []
    for p in pieces:
        for side in (1, -1):
            prims.append(_sweep(p, "tray", "rect",
                                (side * (W / 2 + RAIL_T / 2), 0.0),
                                (RAIL_T, H)))
        if p[0] == "straight":
            _, start, a, length, u, v = p
            n = int(length // RUNG_PITCH)
            for j in range(n + 1):
                s = min(length - RUNG[0], j * RUNG_PITCH + RUNG[0] / 2)
                if s < 0:
                    continue
                prims.append({"kind": "extrude", "group": "tray",
                              "profile": "rect", "at": list(_add(start, a, s)),
                              "u": list(u), "v": list(v),
                              "offset": [0.0, -H / 2 + RUNG[1] / 2],
                              "w": W, "h": RUNG[1], "dir": list(a),
                              "length": RUNG[0]})
    colours, k = {}, 0
    for core in layout:
        cid = core["circuit"]
        if cid not in colours:
            colours[cid] = CIRCUIT_COLOURS[k % len(CIRCUIT_COLOURS)]
            k += 1
        for p in pieces:
            prims.append(_sweep(p, f"cable:{cid}", "circle",
                                (core["lateral_mm"], deck + core["up_mm"]),
                                core["od_mm"] / 2, colours[cid]))
    for s in supports:
        for b in s.get("boxes", []):
            prims.append({"kind": "box", "group": "supports",
                          "min": list(b["min"]), "max": list(b["max"])})
    for o in obstacles:
        prims.append({"kind": "box", "group": "context", "label": o.get("id"),
                      "min": list(o["min"]), "max": list(o["max"])})
    groups = {"tray": COLOURS["tray"], "supports": COLOURS["supports"],
              "context": COLOURS["context"]}
    groups.update({f"cable:{c}": col for c, col in colours.items()})
    return {"name": name, "units": "mm", "groups": groups,
            "primitives": prims}
