#!/usr/bin/env python3
"""
3D perspective view of the two-row hall, exported as a still and an orbit video.

    ./.venv/bin/python make_hall_3d.py [CASE_DIR] [--still] [--frames N]

Writes <CASE_DIR>/hall_perspective.png and hall_perspective.mp4
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

import plot_hall

KELVIN = 273.15


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="case-hall")
    ap.add_argument("--still", action="store_true")
    ap.add_argument("--frames", type=int, default=140)
    ap.add_argument("--fps", type=int, default=25)
    a = ap.parse_args()
    case = Path(a.case)
    p = plot_hall.params(case)
    n = int(p["nRacksPerRow"])
    Tsup, ALLOW = p["supplyTemp_C"], 32.0
    lo, hi = Tsup - 2, Tsup + 14          # 26 .. 42 degC
    clim = (lo, hi)

    foam = case / "case.foam"; foam.touch(exist_ok=True)
    r = pv.OpenFOAMReader(str(foam))
    r.set_active_time_value(max(r.time_values))
    r.cell_to_point_creation = True
    mesh = r.read()["internalMesh"]
    mesh.point_data["TdegC"] = np.clip(mesh.point_data["T"] - KELVIN, lo, hi)

    pv.OFF_SCREEN = True
    pl = pv.Plotter(off_screen=True, window_size=(1600, 1008))
    sargs = dict(title="air temperature [degC]", n_labels=6, fmt="%.0f", color="black",
                 vertical=True, position_x=0.88, position_y=0.20, width=0.05, height=0.6,
                 title_font_size=15, label_font_size=12)

    # plan slice through the racks, and a vertical slice down the hot aisle
    pl.add_mesh(mesh.slice(normal="z", origin=(0, 0, p["rackHeight"] / 2)),
                scalars="TdegC", cmap="turbo", clim=clim,
                scalar_bar_args=sargs, lighting=False)
    pl.add_mesh(mesh.slice(normal="y", origin=(0, (p["hotY0"] + p["hotY1"]) / 2, 0)),
                scalars="TdegC", cmap="turbo", clim=clim,
                show_scalar_bar=False, lighting=False, opacity=0.9)

    # the allowable limit as a surface: where hot air escapes containment
    try:
        iso = mesh.contour([ALLOW], scalars="TdegC")
        if iso.n_points:
            pl.add_mesh(iso, color="white", opacity=0.35, show_scalar_bar=False)
    except Exception:
        pass

    def box(x0, x1, y0, y1, z0, z1, **kw):
        pl.add_mesh(pv.Box(bounds=(x0, x1, y0, y1, z0, z1)), **kw)

    # racks, drawn individually so the row reads as 12 cabinets
    for y0, y1 in ((p["rowAy0"], p["rowAy1"]), (p["rowBy0"], p["rowBy1"])):
        for i in range(n):
            x0 = p["podX0"] + i * p["rackPitch"]
            box(x0 + 0.02, x0 + p["rackPitch"] - 0.02, y0, y1, 0, p["rackHeight"],
                color="#24262b", show_edges=True, edge_color="#0d0e11", line_width=1)
    # containment above the racks
    contZ = p["plenumFloorZ"] - p["containmentGap"]
    for yf in (p["hotY0"], p["hotY1"]):
        box(p["podX0"], p["podX1"], yf - 0.03, yf + 0.03,
            p["rackHeight"], contZ, color="#1f2933", opacity=0.85)
    # fan wall banks, with supply face and intake (top or rear) picked out
    g = p["rearGap_eff"]
    rear = str(p.get("intakeSide", "top")) == "rear"
    for x0, x1, sx, rx in ((g, g + p["unitDepth"], g + p["unitDepth"], g),
                           (p["Lx"] - g - p["unitDepth"], p["Lx"] - g,
                            p["Lx"] - g - p["unitDepth"], p["Lx"] - g)):
        box(x0, x1, p["uy0"], p["uy1"], 0, p["unitHeight"],
            color="#46515c", show_edges=True, edge_color="#20262c", line_width=2)
        box(sx - 0.03, sx + 0.03, p["uy0"], p["uy1"], p["supplyZ0"], p["supplyZ1"],
            color="#1d4ed8")
        if rear:
            box(rx - 0.03, rx + 0.03, p["uy0"], p["uy1"],
                p["supplyZ0"], p["supplyZ1"], color="#c2410c")
        else:
            box(x0, x1, p["uy0"], p["uy1"],
                p["unitHeight"] - 0.03, p["unitHeight"] + 0.03, color="#c2410c")

    # airflow from both supply faces
    for sx, sgn in ((g + p["unitDepth"] + 0.1, 1),
                    (p["Lx"] - g - p["unitDepth"] - 0.1, -1)):
        try:
            seed = pv.Plane(center=(sx, (p["uy0"] + p["uy1"]) / 2,
                                    (p["supplyZ0"] + p["supplyZ1"]) / 2),
                            direction=(sgn, 0, 0),
                            i_size=p["supplyZ1"] - p["supplyZ0"],
                            j_size=p["unitWidth"] * 0.9,
                            i_resolution=5, j_resolution=5)
            st = mesh.streamlines_from_source(seed, vectors="U",
                                             integration_direction="forward",
                                             max_length=120.0, initial_step_length=0.3)
            if st.n_points:
                pl.add_mesh(st.tube(radius=0.03), scalars="TdegC", cmap="turbo",
                            clim=clim, show_scalar_bar=False)
        except Exception as exc:
            print(f"  (streamlines skipped: {exc})")

    nu = int(p.get("nUnitsPerEnd", 1))
    pl.add_text(f"{2*n} x {p['rackLoad_kW']:g} kW = {2*n*p['rackLoad_kW']:g} kW"
                f"  |  {2*nu} x {p['unitCapacity_kW']:g} kW FWCV  |  supply {Tsup:g} degC"
                f"  |  white surface = {ALLOW:g} degC allowable limit",
                position="upper_left", font_size=10, color="black")
    pl.add_axes(line_width=3, color="black")
    pl.set_background("white")

    focus = (p["Lx"] / 2, p["hallWidth"] / 2, p["plenumFloorZ"] / 2)
    diag = (p["Lx"] ** 2 + p["hallWidth"] ** 2 + (p["plenumFloorZ"] + p["plenumHeight"]) ** 2) ** 0.5
    VA = 30.0
    radius = (0.5 * diag) / np.tan(np.radians(VA / 2))

    def place(az, elev=0.40):
        t = np.radians(az)
        pl.camera.focal_point = focus
        pl.camera.position = (focus[0] + radius * np.cos(t),
                              focus[1] + radius * np.sin(t),
                              focus[2] + radius * elev)
        pl.camera.up = (0, 0, 1)
        pl.camera.view_angle = VA

    place(230)
    still = case / "hall_perspective.png"
    pl.screenshot(str(still)); print(f"wrote {still}")

    if not a.still:
        out = case / "hall_perspective.mp4"
        pl.open_movie(str(out), framerate=a.fps, quality=8)
        for i in range(a.frames):
            place(230 + 360.0 * i / a.frames)
            pl.write_frame()
        pl.close()
        print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB)")
    else:
        pl.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
