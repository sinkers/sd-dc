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

import schedule  # noqa: E402
import service  # noqa: E402
from core.render import svg_to_png  # noqa: E402

SYNTHETIC_LADDER = {
    "family": "SYN-LADDER", "width": 900, "overall_width": 960,
    "side_height": 100, "self_weight": 9.5, "standard_length": 6000,
    "bend_radius": 900,
    # Invented, shaped like a heavy ladder table. Not from any datasheet.
    "load_ratings": [[3000, 50], [2500, 70], [2000, 100], [1500, 170]],
}

#: Feeders from a transformer's LV board to the switchroom. Invented loads.
CIRCUITS = [
    {"id": "F-01", "from": "TX1-LV", "to": "MSB-1", "kw": 1200,
     "power_factor": 0.95, "tails_m": 8},
    {"id": "F-02", "from": "TX1-LV", "to": "MSB-2", "kw": 400,
     "power_factor": 0.95, "tails_m": 8},
    {"id": "F-03", "from": "TX1-LV", "to": "MECH-DB", "kw": 160,
     "power_factor": 0.9, "harmonic_content_pct": 30, "tails_m": 10},
    {"id": "F-04", "from": "TX1-LV", "to": "UPS-1 input", "kva": 250,
     "power_factor": 0.9, "tails_m": 8},
    {"id": "F-05", "from": "TX1-LV", "to": "AUX-DB", "amps": 63,
     "cable_type": "XHF110_4C1CE_CU", "tails_m": 12},
]

DEMO = {
    "id": "T-DEMO",
    "tray": SYNTHETIC_LADDER,
    "from": {"id": "TX1.LV_BOX", "pos": [0, 0, 3500], "dir": [1, 0, 0]},
    "to": {"id": "SWR.WALL_ENTRY", "pos": [24000, 9000, 3500],
           "dir": [-1, 0, 0]},
    "circuits": CIRCUITS,
    "circuit_defaults": {"ambient_c": 40, "fault_level_ka": 25},
    "obstacles": [
        {"id": "TX1", "min": [-3000, -1500, 0], "max": [0, 1500, 3000]},
        {"id": "GEN1", "min": [7000, -1200, 0], "max": [13000, 1200, 2800]},
        {"id": "PIT", "min": [16500, -800, 0], "max": [18500, 800, 300]},
        {"id": "SWITCHROOM", "min": [24000, 4000, 0],
         "max": [32000, 14000, 4500]},
        {"id": "KERB", "min": [3000, 3000, 0], "max": [21000, 3300, 200]},
    ],
    "supports": {"growth": 0.25},
    "model": {"build": True},
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
    if r.get("circuits"):
        with open(path + "_schedule.csv", "w") as fh:
            fh.write(schedule.to_csv(r["circuits"]))
        with open(path + "_schedule.md", "w") as fh:
            fh.write(schedule.to_markdown(r))
        for c in r["circuits"]:
            print(f"  {c['id']:5} {c['cable']}: {c['length_m']} m, "
                  f"{c['design_a']} A of {c['capacity_a']} A, "
                  f"VD {c['vd_pct']} % ({c['vd_v']} V)")
    if r.get("model"):
        print("  model:", {k: r["model"].get(k) for k in
                           ("built", "fcstd", "step", "error", "note")})
    print(r["status"], r.get("span_mm"), len(r.get("supports", [])),
          "supports;", path + (".png" if png else ".svg"))
    for i in r.get("issues", []) + r.get("open_items", []):
        print(" ", i["code"], i["message"])
    for b in r.get("bom", []):
        print(" ", b)


if __name__ == "__main__":
    main()
