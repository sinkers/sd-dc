"""Build a tray model from a model3d.py spec, inside FreeCAD.

  freecadcmd freecad_build.py              # SPEC and OUT from the environment
  TRAY_SPEC=spec.json TRAY_OUT=out/T-1 freecadcmd freecad_build.py

Writes OUT.FCStd and OUT.step: one Part feature per group (tray, supports,
context, and one per circuit), each a compound of the group's solids, with
the group colour set when a GUI is present and stored as a property
otherwise. This file only interprets the spec; every geometry decision is in
model3d.py.
"""
import json
import os

import FreeCAD
import Part
from FreeCAD import Vector


def _v(p):
    return Vector(*p)


def _face(prim):
    at, u, v = _v(prim["at"]), _v(prim["u"]), _v(prim["v"])
    a, b = prim["offset"]
    c = at + u * a + v * b
    if prim["profile"] == "circle":
        normal = u.cross(v)
        return Part.Face(Part.Wire(Part.makeCircle(prim["r"], c, normal)))
    w, h = prim["w"] / 2, prim["h"] / 2
    pts = [c - u * w - v * h, c + u * w - v * h, c + u * w + v * h,
           c - u * w + v * h]
    return Part.Face(Part.makePolygon(pts + [pts[0]]))


def _solid(prim):
    if prim["kind"] == "box":
        lo, hi = prim["min"], prim["max"]
        return Part.makeBox(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2],
                            _v(lo))
    f = _face(prim)
    if prim["kind"] == "extrude":
        return f.extrude(_v(prim["dir"]) * prim["length"])
    return f.revolve(_v(prim["centre"]), _v(prim["axis"]), prim["angle"])


def _rgb(hex_colour):
    return tuple(int(hex_colour[i:i + 2], 16) / 255 for i in (1, 3, 5))


def build(spec, out):
    doc = FreeCAD.newDocument(spec.get("name", "tray").replace("-", "_"))
    by_group = {}
    failed = 0
    for prim in spec["primitives"]:
        try:
            by_group.setdefault(prim["group"], []).append(_solid(prim))
        except Exception:                      # noqa: BLE001
            failed += 1
    objs = []
    for group, solids in by_group.items():
        name = group.replace(":", "_").replace("-", "_")
        obj = doc.addObject("Part::Feature", name)
        obj.Label = group
        obj.Shape = Part.makeCompound(solids)
        # A document saved without a GUI comes back hidden otherwise.
        obj.Visibility = True
        colour = spec["groups"].get(group)
        if colour:
            obj.addProperty("App::PropertyString", "Colour", "Tray")
            obj.Colour = colour
            if FreeCAD.GuiUp:
                obj.ViewObject.ShapeColor = _rgb(colour)
                if group == "context":
                    obj.ViewObject.Transparency = 70
        objs.append(obj)
    doc.recompute()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    doc.saveAs(out + ".FCStd")
    import Import
    Import.export(objs, out + ".step")
    report = {"fcstd": out + ".FCStd", "step": out + ".step",
              "groups": {g: len(s) for g, s in by_group.items()},
              "failed_primitives": failed}
    with open(out + ".build.json", "w") as fh:
        json.dump(report, fh, indent=1)
    return report


spec_path = os.environ.get("TRAY_SPEC")
out_path = os.environ.get("TRAY_OUT")
if spec_path and out_path:
    with open(spec_path) as fh:
        print(json.dumps(build(json.load(fh), out_path)))
