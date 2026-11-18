#!/usr/bin/env freecadcmd
"""Cut a FreeCAD site model into plan geometry for make_plans.py.

    PLANS_ARGS='{"fcstd": "...", "out": "plan_geometry.json", "root": "_10_3D_Model",
                 "frame": "Schneider_10MW_Layout", "cuts": {"L1": 1200, "L2": 4500},
                 "site_lines": ["Fence_Line_Flat", ...], "labels": {"L1": "<group>", "L2": "<group>"}}' \
        freecadcmd extract_plan_geometry.py

Also runs inside the FreeCAD GUI (exec the file with PLANS_ARGS set), which is
how the AU07 set was first cut. For every Part::Feature under `root`:

- `cuts[name]`: the section loops at that height, if the solid spans it
- `mid`: one section at mid-height (capped at the lowest cut), for things that
  sit below the cut (slabs, kerbs, line marking) and for the site plan

Coordinates are in the `frame` part's local frame, in mm. Linework that lives
in site coordinates (fence line, parcels, roads, contours) is converted into
that frame. Draft text under the label groups comes through as room labels.
"""
import json
import os
import time

import FreeCAD
from FreeCAD import Vector as V


def run(args):
    doc = FreeCAD.openDocument(args["fcstd"]) if "fcstd" in args else FreeCAD.getDocument(args["doc"])

    def L(n):
        r = doc.getObjectsByLabel(n)
        return r[0] if r else None

    frame = L(args["frame"])
    inv = frame.Placement.inverse()
    cuts = args.get("cuts", {"L1": 1200.0, "L2": 4500.0})
    low = min(cuts.values())

    def polys(wires, to_local=False, defl=25):
        out = []
        for w in wires:
            pts = w.discretize(Deflection=defl)
            if to_local:
                pts = [inv.multVec(p) for p in pts]
            out.append({"pts": [[round(p.x, 1), round(p.y, 1)] for p in pts], "closed": w.isClosed()})
        return out

    def section(shape, z):
        try:
            return shape.slice(V(0, 0, 1), z)
        except Exception:
            return []

    objs = []

    def collect(g):
        for k in g.Group:
            if k.TypeId == "App::DocumentObjectGroup":
                collect(k)
            elif k.TypeId == "Part::Feature":
                objs.append(k)
    collect(L(args["root"]))

    items = []
    for o in objs:
        s = o.Shape
        b = s.BoundBox
        rec = {"label": o.Label, "z": [round(b.ZMin), round(b.ZMax)], "cuts": {}}
        for name, zc in cuts.items():
            if b.ZMin < zc < b.ZMax:
                rec["cuts"][name] = polys(section(s, zc))
        h = b.ZMax - b.ZMin
        zm = None if h <= 0.5 else min(b.ZMin + 0.5 * h, low)
        rec["mid"] = polys(section(s, zm)) if zm is not None else []
        items.append(rec)

    site = {}
    for lab in args.get("site_lines", []):
        o = L(lab)
        if o is not None:
            site[lab] = polys(o.Shape.Wires, True, 200)

    labels = []
    for level, group in args.get("labels", {}).items():
        g = L(group)
        for t in (g.Group if g else []):
            labels.append({"level": level, "text": list(t.Text),
                           "xy": [round(t.Placement.Base.x), round(t.Placement.Base.y)]})

    out = {"model": os.path.basename(doc.FileName),
           "saved": time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(doc.FileName))),
           "frame_yaw_deg": frame.Placement.Rotation.toEuler()[0],
           "items": items, "site": site, "labels": labels}
    with open(args["out"], "w") as fh:
        json.dump(out, fh)
    print("[plans] %d objects, %d labels -> %s" % (len(items), len(labels), args["out"]))


run(json.loads(os.environ["PLANS_ARGS"]))
