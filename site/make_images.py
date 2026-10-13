#!/usr/bin/env python3
"""Regenerate the project page's demo images from invented scenes.

  python3 site/make_images.py

Everything drawn here is made up, so the output can be published: a small
chilled-water plant room for the pipe router, and the trays/tools/demo.py
yard for the tray router. No project coordinates and no vendor data.
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
IMG = os.path.join(HERE, "img")
sys.path.insert(0, os.path.join(ROOT, "piping"))

import service  # noqa: E402
from core.render import svg_to_png  # noqa: E402


def nozzle(i, pos, d, dn=150):
    return {"id": i, "pos": pos, "dir": d, "dn": dn}


# Two chillers feed a supply header to two CDUs; returns come back the same
# way. A column stands between them. Order matters: each routed pipe is an
# obstacle for the next, and R-1 first would block CH2's return nozzle.
PLANT = {
    "pipes": [
        {"id": "S-1", "dn": 150, "service": "CHW-S",
         "from": nozzle("CH1.out", [3000, 600, 1200], [1, 0, 0]),
         "to": nozzle("CDU1.in", [14000, 6800, 900], [-1, 0, 0])},
        {"id": "S-2", "dn": 150, "service": "CHW-S",
         "from": nozzle("CH2.out", [3000, 3600, 1200], [1, 0, 0]),
         "to": nozzle("CDU2.in", [14000, 9800, 900], [-1, 0, 0])},
        {"id": "R-2", "dn": 150, "service": "CHW-R",
         "from": nozzle("CDU2.out", [14000, 10400, 1500], [-1, 0, 0]),
         "to": nozzle("CH2.in", [3000, 4200, 600], [1, 0, 0])},
        {"id": "R-1", "dn": 150, "service": "CHW-R",
         "from": nozzle("CDU1.out", [14000, 7400, 1500], [-1, 0, 0]),
         "to": nozzle("CH1.in", [3000, 1200, 600], [1, 0, 0])},
    ],
    "obstacles": [
        {"id": "CH1", "min": [0, 0, 0], "max": [3000, 1800, 2000]},
        {"id": "CH2", "min": [0, 3000, 0], "max": [3000, 4800, 2000]},
        {"id": "CDU1", "min": [14000, 6400, 0], "max": [15200, 7800, 2200]},
        {"id": "CDU2", "min": [14000, 9400, 0], "max": [15200, 10800, 2200]},
        {"id": "COL-B2", "min": [8000, 3800, 0], "max": [8600, 4400, 4500]},
        {"id": "FLOOR", "min": [-2000, -2000, -500], "max": [18000, 13000, 0]},
    ],
    "render": {"views": ["plan", "front", "side", "iso"],
               "title": "Demo: chilled water, two chillers to two CDUs"},
}


def png(svg, name):
    data = svg_to_png(svg)
    if not data:
        sys.exit("rsvg-convert is needed to write PNGs")
    with open(os.path.join(IMG, name), "wb") as fh:
        fh.write(data)


def main():
    os.makedirs(IMG, exist_ok=True)
    r = service.render(PLANT)
    print("pipes:", r["routed"], "of", len(PLANT["pipes"]), "routed")
    png(r["svg"], "pipe_demo.png")
    subprocess.run([sys.executable, os.path.join(ROOT, "trays", "tools",
                                                 "demo.py")], check=True)


if __name__ == "__main__":
    main()
