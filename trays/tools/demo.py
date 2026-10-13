#!/usr/bin/env python3
"""Route and support a made-up outdoor tray run, and draw it.

  python3 tools/demo.py [--out DIR]

A ladder from a transformer's LV box across a yard, past a generator and a
drainage pit, to a switchroom wall. The scene is invented, so it can live in
the public repo; the tray uses a synthetic load table, not vendor data.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))

import service  # noqa: E402
from core.render import svg_to_png  # noqa: E402

SYNTHETIC_LADDER = {
    "family": "SYN-LADDER", "width": 600, "overall_width": 660,
    "side_height": 100, "self_weight": 6.6, "standard_length": 6000,
    "bend_radius": 600,
    # Invented, shaped like a heavy ladder table. Not from any datasheet.
    "load_ratings": [[3000, 60], [2500, 80], [2000, 120], [1500, 200]],
}

DEMO = {
    "id": "T-DEMO",
    "tray": SYNTHETIC_LADDER,
    "from": {"id": "TX1.LV_BOX", "pos": [0, 0, 3500], "dir": [1, 0, 0]},
    "to": {"id": "SWR.WALL_ENTRY", "pos": [24000, 9000, 3500],
           "dir": [-1, 0, 0]},
    "cables": [{"id": "LV mains 240 4C+E", "kg_per_m": 8.2, "count": 4},
               {"id": "sub-mains 95 4C+E", "kg_per_m": 3.6, "count": 2}],
    "obstacles": [
        {"id": "TX1", "min": [-3000, -1500, 0], "max": [0, 1500, 3000]},
        {"id": "GEN1", "min": [7000, -1200, 0], "max": [13000, 1200, 2800]},
        {"id": "PIT", "min": [16500, -800, 0], "max": [18500, 800, 300]},
        {"id": "SWITCHROOM", "min": [24000, 4000, 0],
         "max": [32000, 14000, 4500]},
        {"id": "KERB", "min": [3000, 3000, 0], "max": [21000, 3300, 200]},
    ],
    "supports": {"growth": 0.25},
    "render": {"views": ["plan", "front", "side", "iso"],
               "title": "Demo: outdoor ladder, transformer to switchroom"},
}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", default=os.path.join(HERE, "..", "out"))
    args = ap.parse_args()
    os.makedirs(args.out, exist_ok=True)
    r = service.route_and_support(DEMO)
    svg = r.pop("svg")
    for s in r.get("supports", []):
        s.pop("boxes", None)
    path = os.path.join(args.out, "tray_demo")
    with open(path + ".svg", "w") as fh:
        fh.write(svg)
    png = svg_to_png(svg)
    if png:
        with open(path + ".png", "wb") as fh:
            fh.write(png)
    with open(path + ".json", "w") as fh:
        json.dump(r, fh, indent=1)
    print(r["status"], r.get("span_mm"), len(r.get("supports", [])),
          "supports;", path + (".png" if png else ".svg"))
    for i in r.get("issues", []) + r.get("open_items", []):
        print(" ", i["code"], i["message"])
    for b in r.get("bom", []):
        print(" ", b)


if __name__ == "__main__":
    main()
