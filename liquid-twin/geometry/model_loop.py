#!/usr/bin/env python3
"""Build the RD110 two-loop plant as FreeCAD solids and export STEP.

Reads the topology from `dtloop.layout` - the same module the browser viewer and
(from Phase 2) the hydraulic solver read - so the STEP model a reviewer marks up
and the network the solver runs cannot drift apart.

Runs inside FreeCAD's own Python, not a plain interpreter:

    ./geometry/run.sh          # from the liquid-twin directory

Outputs, all regenerable:

    models/RD110_Loop.FCStd       the editable document
    models/RD110_Loop.step        STEP AP214, for review in any CAD viewer

Every pipe segment is its own named object rather than one fused network, so a
reviewer can select a run and read its tag. Note that FreeCAD sanitises names
for its own document - `CDU-1` becomes `CDU_1` - which is why the browser bundle
is not built from these objects: it keys on the layout's names, and it is built
by `viewer/prepare_geometry.py` with no FreeCAD involved.

That split was not the first design. Packing the browser bundle from FreeCAD's
own tessellation gave 6.1 MB for a plant made of cylinders and boxes, because
`Shape.tessellate(deviation)` ignores the deviation for analytic surfaces - every
cylinder came out at ~500 triangles whether asked for 8 mm or 40 mm. Meshing
12-sided prisms in plain Python gives 0.56 MB and lets someone without FreeCAD
rebuild the viewer. So FreeCAD keeps only the job that needs it: STEP.
"""

import os
import sys
import time

import FreeCAD
import Part

# FreeCAD's console mode reads this on stdin, where __file__ does not exist, so
# the component root is taken from the environment with __file__ as the fallback.
# `run.sh` sets LIQUID_TWIN_DIR; running the file directly does not need to.
_ENV_ROOT = os.environ.get("LIQUID_TWIN_DIR")
if _ENV_ROOT:
    ROOT = os.path.abspath(_ENV_ROOT)
elif "__file__" in dir():
    ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
else:
    raise SystemExit("set LIQUID_TWIN_DIR to the liquid-twin directory")
REPO_LOOP = os.path.join(ROOT, "loop")
if REPO_LOOP not in sys.path:
    sys.path.insert(0, REPO_LOOP)

from dtloop.layout import SERVICES, build_layout, summary  # noqa: E402

OUT_DIR = os.path.join(ROOT, "models")

# Colour by service, so the STEP model reads the same way as the browser view.
SERVICE_COLOUR = {
    "facility_supply": (0.20, 0.55, 0.85),  # 37 C - cool blue
    "facility_return": (0.85, 0.45, 0.20),  # 47 C - warm
    "tcs_supply": (0.30, 0.75, 0.65),       # 40 C - teal
    "tcs_return": (0.80, 0.25, 0.30),       # 50 C - hot
}
KIND_COLOUR = {
    "rack": (0.35, 0.35, 0.40),
    "cdu": (0.55, 0.55, 0.60),
    "chiller": (0.45, 0.50, 0.55),
}
VALVE_COLOUR = (0.90, 0.80, 0.20)

VALVE_BODY_R = 1.9   # multiple of pipe radius, so a valve reads at a glance
VALVE_BODY_L = 220.0  # mm


def vec(p):
    return FreeCAD.Vector(p.x, p.y, p.z)


def pipe_parts(waypoints, dn):
    """A cylinder per leg, plus a sphere per elbow. What the fused solid is made of."""
    r = dn / 2.0
    parts = []
    for a, b in zip(waypoints, waypoints[1:]):
        d = vec(b).sub(vec(a))
        length = d.Length
        if length < 1e-6:
            continue
        parts.append(Part.makeCylinder(r, length, vec(a), d.normalize()))
    for p in waypoints[1:-1]:
        parts.append(Part.makeSphere(r, vec(p)))
    if not parts:
        raise ValueError("no pipe geometry produced")
    return parts



def pipe_solid(waypoints, dn):
    """Straight cylinders along the centreline, with spheres filling the elbows.

    Cylinders-and-spheres rather than a swept profile with real bend radii: this
    model is for reviewing routing and connectivity, and a sphere at each vertex
    is visually indistinguishable at plant scale while being far more robust.
    `piping/route_engine.py` is where real bend radii and clash checks live, and
    is where this should go when the routing itself needs signing off.
    """
    parts = pipe_parts(waypoints, dn)
    solid = parts[0]
    for extra in parts[1:]:
        solid = solid.fuse(extra)
    return solid.removeSplitter()


def valve_solid(segment):
    """A short fat barrel on the first leg of the run, at its midpoint."""
    a, b = segment.waypoints[0], segment.waypoints[1]
    d = vec(b).sub(vec(a))
    if d.Length < VALVE_BODY_L * 1.5:
        return None
    direction = FreeCAD.Vector(d).normalize()
    start = vec(a).add(direction.multiply(d.Length / 2 - VALVE_BODY_L / 2))
    return Part.makeCylinder(
        segment.dn / 2.0 * VALVE_BODY_R, VALVE_BODY_L, start,
        FreeCAD.Vector(d).normalize(),
    )


def add(doc, name, shape, colour, label=""):
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    obj.Label = label or name
    try:
        obj.ViewObject.ShapeColor = colour
    except AttributeError:
        pass  # console mode has no ViewObject
    return obj




def build():
    t0 = time.time()
    lay = build_layout()
    problems = lay.validate()
    if problems:
        raise SystemExit("layout is not valid:\n  " + "\n  ".join(problems))

    print(summary(lay))
    os.makedirs(OUT_DIR, exist_ok=True)

    doc = FreeCAD.newDocument("RD110_Loop")
    objects = []

    for e in lay.equipment:
        box = Part.makeBox(e.size[0], e.size[1], e.size[2], vec(e.origin))
        objects.append(add(doc, e.name, box, KIND_COLOUR.get(e.kind, (0.5, 0.5, 0.5)), e.label))

    for s in lay.segments:
        objects.append(add(doc, s.name, pipe_solid(s.waypoints, s.dn),
                           SERVICE_COLOUR[s.service], f"{s.name} DN{s.dn}"))
        if s.valve:
            body = valve_solid(s)
            if body is not None:
                objects.append(add(doc, s.valve, body, VALVE_COLOUR,
                                   f"{s.valve} on {s.name}"))

    doc.recompute()
    print(f"built {len(objects)} objects in {time.time() - t0:.1f} s")

    fcstd = os.path.join(OUT_DIR, "RD110_Loop.FCStd")
    doc.saveAs(fcstd)
    print(f"wrote {fcstd}")

    step = os.path.join(OUT_DIR, "RD110_Loop.step")
    t1 = time.time()
    Part.export(objects, step)
    print(f"wrote {step} ({os.path.getsize(step) / 1e6:.1f} MB) "
          f"in {time.time() - t1:.1f} s")

    return doc


if __name__ == "__main__":
    build()
