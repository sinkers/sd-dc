#!/usr/bin/env python3
"""Pack the loop layout into one binary bundle the browser viewer can fetch.

Reads `dtloop.layout` - the same topology FreeCAD builds the STEP model from -
and writes:

    viewer/geometry/geometry.bin     concatenated float32 triangle positions
    viewer/geometry/manifest.json    part table: name, group, service, offset

**No FreeCAD.** That is deliberate, and it was not the first design. Packing the
bundle from FreeCAD's own tessellation looked obvious - the solids were already
there - and produced 6.1 MB for a plant made of cylinders and boxes. The reason
is that `Shape.tessellate(deviation)` ignores the deviation for analytic
surfaces: every cylinder came out at ~500 triangles whether asked for 8 mm or
40 mm, and a 90-degree pipe run cost 1,000.

Meshing the primitives here instead gives full control - a 12-sided prism is
48 triangles and reads as round at plant scale - and has two better
consequences: the bundle is a fortieth of the size, and a contributor without
FreeCAD can still rebuild the viewer. FreeCAD keeps the job only it can do,
which is the STEP export.

Measured, across 148 pipe runs, 52 valves and 61 boxes:

    FreeCAD tessellation, fused solids, elbow spheres    431k triangles  15.5 MB
    FreeCAD tessellation, loose primitives                1.29M          46.5 MB
    FreeCAD tessellation, legs extended through corners   171k            6.1 MB
    procedural, 12-sided prisms (this)                     18k            0.6 MB

The second row is the one worth remembering: tessellating the primitives loose
is three times worse than tessellating the solid they fuse into, because fusing
discards the surface buried inside each joint.

Usage:  ./viewer/prepare_geometry.py
"""

from __future__ import annotations

import json
import math
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "loop"))

from dtloop.chiller import rd110_plant  # noqa: E402
from dtloop.layout import (  # noqa: E402
    SERVICES,
    Point,
    build_layout,
    summary,
)

# RD110's liquid load. 87 % of the AI racks only - the 48 networking racks at
# 15 kW are air-cooled, so applying 87 % to RD110's whole 7,536 kW IT figure
# overstates the liquid side by about 600 kW.
AI_RACK_KW = 142.0
AI_RACK_COUNT = 48
LIQUID_FRACTION = 0.87
LIQUID_LOAD_KW = AI_RACK_KW * AI_RACK_COUNT * LIQUID_FRACTION
RETURN_WATER_C = 47.0

OUT = HERE / "geometry"

# Sides on a pipe's cross-section. Twelve reads as round at plant scale and
# costs 48 triangles a leg; the whole plant is then under a megabyte.
SIDES = 12

# Valve bodies, matching geometry/model_loop.py so the two pictures agree.
VALVE_BODY_R = 1.9
VALVE_BODY_L = 220.0

SERVICE_COLOUR = {
    "facility_supply": [0.20, 0.55, 0.85],
    "facility_return": [0.85, 0.45, 0.20],
    "tcs_supply": [0.30, 0.75, 0.65],
    "tcs_return": [0.80, 0.25, 0.30],
}
KIND_COLOUR = {
    "rack": [0.35, 0.35, 0.40],
    "cdu": [0.55, 0.55, 0.60],
    "chiller": [0.45, 0.50, 0.55],
}
VALVE_COLOUR = [0.90, 0.80, 0.20]


class Blob:
    """Accumulates float32 triangles and remembers where each part started."""

    def __init__(self) -> None:
        self.buf = bytearray()

    def tell(self) -> int:
        return len(self.buf)

    def tri(self, a, b, c) -> None:
        for v in (a, b, c):
            self.buf += struct.pack("<3f", v[0], v[1], v[2])

    def quad(self, a, b, c, d) -> None:
        self.tri(a, b, c)
        self.tri(a, c, d)


def box(blob: Blob, origin: Point, size) -> int:
    x0, y0, z0 = origin.x, origin.y, origin.z
    x1, y1, z1 = x0 + size[0], y0 + size[1], z0 + size[2]
    p = [
        (x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0),
        (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1),
    ]
    # Wound counter-clockwise seen from outside, so the browser's recomputed
    # normals point out and flat shading is not inside-out.
    for a, b, c, d in (
        (0, 3, 2, 1), (4, 5, 6, 7),   # bottom, top
        (0, 1, 5, 4), (2, 3, 7, 6),   # -y, +y
        (1, 2, 6, 5), (3, 0, 4, 7),   # +x, -x
    ):
        blob.quad(p[a], p[b], p[c], p[d])
    return 12


def _basis(direction):
    """Two unit vectors perpendicular to `direction`, for the cross-section."""
    dx, dy, dz = direction
    up = (0.0, 0.0, 1.0) if abs(dz) < 0.9 else (1.0, 0.0, 0.0)
    ux = dy * up[2] - dz * up[1]
    uy = dz * up[0] - dx * up[2]
    uz = dx * up[1] - dy * up[0]
    n = math.sqrt(ux * ux + uy * uy + uz * uz)
    u = (ux / n, uy / n, uz / n)
    v = (
        dy * u[2] - dz * u[1],
        dz * u[0] - dx * u[2],
        dx * u[1] - dy * u[0],
    )
    return u, v


def prism(blob: Blob, start, direction, length: float, radius: float, sides=SIDES) -> int:
    """A capped prism from `start` along a unit `direction`. 4*sides triangles."""
    u, v = _basis(direction)
    end = tuple(start[i] + direction[i] * length for i in range(3))
    ring_a, ring_b = [], []
    for k in range(sides):
        th = 2.0 * math.pi * k / sides
        off = tuple(radius * (math.cos(th) * u[i] + math.sin(th) * v[i]) for i in range(3))
        ring_a.append(tuple(start[i] + off[i] for i in range(3)))
        ring_b.append(tuple(end[i] + off[i] for i in range(3)))
    for k in range(sides):
        j = (k + 1) % sides
        blob.quad(ring_a[k], ring_b[k], ring_b[j], ring_a[j])
    for k in range(1, sides - 1):
        blob.tri(ring_a[0], ring_a[k + 1], ring_a[k])   # start cap
        blob.tri(ring_b[0], ring_b[k], ring_b[k + 1])   # end cap
    return 4 * sides


def _leg(a: Point, b: Point):
    d = (b.x - a.x, b.y - a.y, b.z - a.z)
    length = math.sqrt(sum(c * c for c in d))
    if length < 1e-9:
        return None, 0.0
    return tuple(c / length for c in d), length


def pipe(blob: Blob, waypoints: list[Point], dn: int) -> int:
    """Legs only, each run half a bore through its corners.

    No elbow spheres: two cylinders overlapping through a right angle fill the
    corner completely, and a sphere at every vertex is what made the FreeCAD
    bundle unaffordable. See the module docstring for the measurements.
    """
    r = dn / 2.0
    n = len(waypoints)
    tris = 0
    for i, (a, b) in enumerate(zip(waypoints, waypoints[1:])):
        direction, length = _leg(a, b)
        if direction is None:
            continue
        start = (a.x, a.y, a.z)
        extra = 0.0
        if i > 0:
            start = tuple(start[j] - direction[j] * r for j in range(3))
            extra += r
        if i + 2 < n:
            extra += r
        tris += prism(blob, start, direction, length + extra, r)
    return tris


def valve(blob: Blob, waypoints: list[Point], dn: int) -> int:
    """A short fat barrel at the midpoint of the first leg."""
    a, b = waypoints[0], waypoints[1]
    direction, length = _leg(a, b)
    if direction is None or length < VALVE_BODY_L * 1.5:
        return 0
    off = length / 2 - VALVE_BODY_L / 2
    start = tuple((a.x, a.y, a.z)[i] + direction[i] * off for i in range(3))
    return prism(blob, start, direction, VALVE_BODY_L, dn / 2.0 * VALVE_BODY_R)


def main() -> int:
    lay = build_layout()
    problems = lay.validate()
    if problems:
        print("layout is not valid:", file=sys.stderr)
        for p in problems:
            print(f"  {p}", file=sys.stderr)
        return 1

    print(summary(lay))
    OUT.mkdir(parents=True, exist_ok=True)
    blob = Blob()
    parts = []

    for e in lay.equipment:
        offset = blob.tell()
        tris = box(blob, e.origin, e.size)
        parts.append({
            "name": e.name, "group": e.kind, "tag": e.kind,
            "byteOffset": offset, "triangles": tris,
            "label": e.label, "pod": e.pod,
            "centre": [round(c, 1) for c in e.centre().as_tuple()],
        })

    for s in lay.segments:
        offset = blob.tell()
        tris = pipe(blob, s.waypoints, s.dn)
        parts.append({
            "name": s.name, "group": "pipe", "tag": s.service,
            "byteOffset": offset, "triangles": tris,
            "dn": s.dn, "length_m": round(s.length_mm() / 1000.0, 3),
            "elbows": s.elbows(), "from": s.from_node, "to": s.to_node,
            "valve": s.valve, "pod": s.pod,
        })
        if s.valve:
            offset = blob.tell()
            tris = valve(blob, s.waypoints, s.dn)
            if tris:
                parts.append({
                    "name": s.valve, "group": "valve", "tag": s.service,
                    "byteOffset": offset, "triangles": tris,
                    "on_segment": s.name, "dn": s.dn, "pod": s.pod,
                })

    # The chiller mode table. Computed here rather than in the browser so the
    # physics has one implementation and JavaScript only looks things up.
    plant = rd110_plant()
    sweep = plant.sweep(LIQUID_LOAD_KW, RETURN_WATER_C, lo=-10.0, hi=48.0, step=0.5)

    lo, hi = lay.bounds()
    manifest = {
        "units": "mm",
        "up_axis": "z",
        "source": "liquid-twin/viewer/prepare_geometry.py from dtloop.layout",
        "layout": lay.name,
        "binary": "geometry.bin",
        "sides": SIDES,
        "total_triangles": sum(p["triangles"] for p in parts),
        "bounds": {"min": lo.as_tuple(), "max": hi.as_tuple()},
        "services": SERVICES,
        "service_colour": SERVICE_COLOUR,
        "kind_colour": KIND_COLOUR,
        "valve_colour": VALVE_COLOUR,
        "chillers": {
            "model": "Uniflair XRAF4242A EHT free-cooling chiller",
            "units": len(plant.units),
            "running": plant.running,
            "unit_rated_kw": plant.units[0].rated_kw,
            "capacity_kw": round(plant.capacity_kw, 1),
            "liquid_load_kw": round(LIQUID_LOAD_KW, 1),
            "return_water_c": RETURN_WATER_C,
            "crossover_c": round(plant.crossover_ambient_c(LIQUID_LOAD_KW, RETURN_WATER_C), 2),
            "rd110_ambient_max_c": 39.3,
            "sweep": sweep,
            "note": (
                "Free cooling below the crossover: fans only, compressors off. "
                "Above it the coil pre-cools and the compressors carry the rest. "
                "UA, fan power and the COP curve are grade L judgement, not RD110 "
                "figures - see dtloop/chiller.py."
            ),
        },
        "parts": parts,
    }

    (OUT / "geometry.bin").write_bytes(bytes(blob.buf))
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(f"wrote geometry.bin  {len(blob.buf) / 1e6:.2f} MB, "
          f"{manifest['total_triangles']} triangles")
    print(f"wrote manifest.json {len(parts)} parts")
    print(f"chillers: {plant.running} of {len(plant.units)} running, "
          f"{plant.capacity_kw:.0f} kW against a {LIQUID_LOAD_KW:.0f} kW liquid load; "
          f"free cooling below {plant.crossover_ambient_c(LIQUID_LOAD_KW, RETURN_WATER_C):.1f} C")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
