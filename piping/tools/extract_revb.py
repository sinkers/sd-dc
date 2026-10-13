#!/usr/bin/env python3
"""Turn the Concept A Rev B connection build script into a routing benchmark.

  python3 tools/extract_revb.py "<.../Site layout/scripts>" [out.json]

`revb_connections_build.py` holds 34 pipe routes whose corner points were
written by hand and checked with route_engine.validate_waypoints. That makes
them a fair target for the router: the same ports, the same obstacles, and a
human answer to compare length and elbow count against.

The build script needs FreeCAD. This runs it against a stand-in that records
every port, every box/cylinder the script places (as an axis-aligned box) and
every pipe call, and draws nothing. Existing plant that lives only in the
FCStd (chillers, fan walls, the building) is not in the script, so it is not
in the benchmark either; the output says so.

The output is project data, so it goes to piping/private/ by default, which
is gitignored. This repository is public.
"""
from __future__ import annotations

import importlib
import json
import math
import os
import sys
import types

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_OUT = os.path.join(HERE, "..", "private", "revb_chw.json")


class _Any:
    """Accepts any attribute, call, index or iteration and does nothing."""

    def __getattr__(self, name):
        return _Any()

    def __setattr__(self, name, value):
        pass

    def __call__(self, *a, **k):
        return _Any()

    def __getitem__(self, k):
        return _Any()

    def __iter__(self):
        return iter(())


class _V(tuple):
    def __new__(cls, x=0.0, y=0.0, z=0.0):
        return super().__new__(cls, (float(x), float(y), float(z)))

    x = property(lambda s: s[0])
    y = property(lambda s: s[1])
    z = property(lambda s: s[2])


class _Placement:
    def __init__(self, base=None, *a, **k):
        self.Base = base


class _Header(_Any):
    """A horizontal cylinder the script may move later (it does, for D2)."""

    def __init__(self, box):
        object.__setattr__(self, "box", box)

    def __setattr__(self, name, value):
        b = self.box
        if name == "Placement" and getattr(value, "Base", None) is not None:
            length = b["max"][0] - b["min"][0]
            r = (b["max"][1] - b["min"][1]) / 2
            x, y, z = value.Base
            b["min"] = [x, y - r, z - r]
            b["max"] = [x + length, y + r, z + r]
        elif name == "Height":
            b["max"][0] = b["min"][0] + value


class _Doc(_Any):
    def __init__(self, headers):
        object.__setattr__(self, "headers", headers)

    def getObjectsByLabel(self, label):
        return [self.headers[label]] if label in self.headers else []


def _stub_modules(doc):
    fc = types.ModuleType("FreeCAD")
    fc.Vector = _V
    fc.Placement = _Placement
    fc.Rotation = lambda *a, **k: _Any()
    fc.ActiveDocument = doc
    for name, mod in (("FreeCAD", fc), ("Part", _Any()), ("Draft", _Any())):
        sys.modules[name] = mod


def extract(scripts_dir: str) -> dict:
    headers = {}
    _stub_modules(_Doc(headers))
    ports, boxes, pipes, cables = {}, [], [], []

    lib = types.ModuleType("revb_connections_lib")

    def port(obj, name, pos, d, kind, service, size):
        key = f"{obj}.{name}"
        ports[key] = {"pos": [float(c) for c in pos],
                      "dir": [int(round(c)) for c in d], "kind": kind,
                      "service": service, "size": str(size)}
        return key

    def box(g, label, x0, y0, z0, x1, y1, z1, *a, **k):
        boxes.append({"id": label, "min": [x0, y0, z0], "max": [x1, y1, z1]})
        return _Any()

    def cyl(g, label, cx, cy, z0, r, h, *a, **k):
        boxes.append({"id": label, "min": [cx - r, cy - r, z0],
                      "max": [cx + r, cy + r, z0 + h]})
        return _Any()

    def hcyl(g, label, x0, x1, y, z, r, *a, **k):
        boxes.append({"id": label, "min": [x0, y - r, z - r],
                      "max": [x1, y + r, z + r]})
        headers[label] = _Header(boxes[-1])
        return headers[label]

    def pipe(g, cid, pfrom, pto, wps, dn, service, *a, **k):
        pipes.append({"id": cid, "from": pfrom, "to": pto, "dn": int(dn),
                      "service": service,
                      "points": [[float(c) for c in w] for w in wps]})
        return []

    def cable(g, cid, pfrom, pto, wps, size, service, *a, **k):
        cables.append({"id": cid, "from": pfrom, "to": pto})
        return []

    for name, fn in dict(port=port, box=box, cyl=cyl, hcyl=hcyl, pipe=pipe,
                         cable=cable).items():
        setattr(lib, name, fn)
    for name in ("grp", "text", "port_marker", "write_sheets", "check_route"):
        setattr(lib, name, lambda *a, **k: _Any())
    lib.PORTS, lib.CONNS, lib.doc = ports, [], _Any()
    lib.V = _V
    lib.Placement = _Placement
    lib.Rotation = lambda *a, **k: _Any()
    lib.__all__ = [n for n in vars(lib) if not n.startswith("_")]
    sys.modules["revb_connections_lib"] = lib

    path = os.path.join(scripts_dir, "revb_connections_build.py")
    with open(path, encoding="utf-8") as fh:
        src = fh.read()
    real_reload = importlib.reload
    importlib.reload = lambda m: m          # the script reloads its library
    try:
        exec(compile(src, path, "exec"), {"__name__": "revb_build"})
    finally:
        importlib.reload = real_reload

    for b in boxes:
        b["min"] = [float(c) for c in b["min"]]
        b["max"] = [float(c) for c in b["max"]]
    return {
        "source": "Concept A Rev B revb_connections_build.py",
        "note": "Obstacles are only what the build script places (pump skids, "
                "headers, buffer tanks). Chillers, fan walls and the building "
                "live in the FCStd and are not included.",
        "ports": ports, "obstacles": boxes, "pipes": pipes,
        "cable_count": len(cables),
    }


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if not argv:
        print(__doc__)
        return 2
    out = argv[1] if len(argv) > 1 else DEFAULT_OUT
    data = extract(argv[0])
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, allow_nan=False)
    total = sum(math.dist(p["points"][i], p["points"][i + 1])
                for p in data["pipes"] for i in range(len(p["points"]) - 1))
    print(f"{len(data['ports'])} ports, {len(data['obstacles'])} obstacles, "
          f"{len(data['pipes'])} pipes ({total / 1000:.1f} m) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
