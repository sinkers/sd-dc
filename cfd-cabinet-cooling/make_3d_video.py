#!/usr/bin/env python3
"""
Render a 3D perspective view of the pod and export it as a video.

Reads the OpenFOAM case directly (VTK's OpenFOAM reader), builds a readable
scene - solid cabinets and fan wall unit, the containment and plenum panels, a
temperature slice through the row, and the 27 degC isosurface - then orbits a
perspective camera around it and writes an MP4.

Needs the project venv:
    ./.venv/bin/python make_3d_video.py [CASE_DIR] [--frames N] [--still]

Writes <CASE_DIR>/perspective.mp4 and <CASE_DIR>/perspective.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pyvista as pv

import plot_slice  # reuse the geometry reader so the scene matches the mesh

KELVIN = 273.15
T_MIN_C, T_MAX_C = 18.0, 40.0
ASHRAE_C = 27.0


def build_scene(case: Path, plotter: pv.Plotter) -> None:
    g = plot_slice.geometry(case)

    foam = case / "case.foam"
    foam.touch(exist_ok=True)
    reader = pv.OpenFOAMReader(str(foam))
    reader.set_active_time_value(max(reader.time_values))
    reader.cell_to_point_creation = True
    mesh = reader.read()["internalMesh"]

    # Temperature in degrees C, clipped so the fixed colour scale reads cleanly.
    if "T" not in mesh.point_data:
        raise SystemExit("field T not found - has the case been run and reconstructed?")
    mesh.point_data["TdegC"] = np.clip(mesh.point_data["T"] - KELVIN, T_MIN_C, T_MAX_C)

    clim = (T_MIN_C, T_MAX_C)
    sargs = dict(title="air temperature [degC]", n_labels=6, fmt="%.0f",
                 title_font_size=15, label_font_size=12, color="black",
                 vertical=True, position_x=0.88, position_y=0.20,
                 width=0.05, height=0.60)

    # --- vertical slice along the row centre: the familiar 2D picture, in place
    y_mid = (g["rowY0"] + g["rowY1"]) / 2
    plotter.add_mesh(mesh.slice(normal="y", origin=(0, y_mid, 0)),
                     scalars="TdegC", cmap="turbo", clim=clim,
                     scalar_bar_args=sargs, lighting=False)

    # --- floor-level plan slice: shows variation along the row
    plotter.add_mesh(mesh.slice(normal="z", origin=(0, 0, g["cabinetHeight"] * 0.5)),
                     scalars="TdegC", cmap="turbo", clim=clim,
                     show_scalar_bar=False, lighting=False, opacity=0.55)

    # --- the ASHRAE limit as a surface: anything in the cold aisle is a problem
    try:
        iso = mesh.contour([ASHRAE_C], scalars="TdegC")
        if iso.n_points:
            plotter.add_mesh(iso, color="white", opacity=0.28,
                             show_scalar_bar=False, label=f"{ASHRAE_C:.0f} degC")
    except Exception:
        pass

    # --- solid geometry, drawn from the same parameters the mesh was built from
    def box(x0, x1, y0, y1, z0, z1, **kw):
        plotter.add_mesh(pv.Box(bounds=(x0, x1, y0, y1, z0, z1)), **kw)

    # cabinet row
    box(g["cabinetX0"], g["cabinetX1"], g["rowY0"], g["rowY1"], 0, g["cabinetHeight"],
        color="#2b2b30", show_edges=True, edge_color="#101014", line_width=2)
    # fan wall unit
    box(0, g["unitDepth"], 0, g["roomWidth"], 0, g["unitHeight"],
        color="#4a5560", show_edges=True, edge_color="#20262c", line_width=2)
    # plenum floor
    box(g["unitDepth"], g["cabinetX1"], g["rowY0"], g["rowY1"],
        g["unitHeight"] - 0.02, g["unitHeight"] + 0.02,
        color="#8a8f96", opacity=0.55)
    # containment panel above the cabinets
    if g["containmentTopZ"] > g["cabinetHeight"]:
        box(g["cabinetX1"] - 0.02, g["cabinetX1"] + 0.02, g["rowY0"], g["rowY1"],
            g["cabinetHeight"], g["containmentTopZ"], color="#1f2933")
    # supply opening and top intake, as coloured plates
    box(g["unitDepth"] - 0.02, g["unitDepth"] + 0.02, 0, g["roomWidth"],
        g["supplyZ0"], g["supplyZ1"], color="#1d4ed8")
    box(0, g["unitDepth"], 0, g["roomWidth"],
        g["unitHeight"] - 0.02, g["unitHeight"] + 0.02, color="#c2410c")

    # --- airflow, seeded across the supply opening
    try:
        seed = pv.Plane(center=(g["unitDepth"] + 0.05, g["roomWidth"] / 2,
                                (g["supplyZ0"] + g["supplyZ1"]) / 2),
                        direction=(1, 0, 0),
                        i_size=g["supplyZ1"] - g["supplyZ0"],
                        j_size=g["roomWidth"] * 0.9,
                        i_resolution=6, j_resolution=6)
        stream = mesh.streamlines_from_source(
            seed, vectors="U", integration_direction="forward",
            max_length=60.0, initial_step_length=0.2)
        if stream.n_points:
            plotter.add_mesh(stream.tube(radius=0.018), scalars="TdegC",
                             cmap="turbo", clim=clim, show_scalar_bar=False)
    except Exception as exc:
        print(f"  (streamlines skipped: {exc})")

    plotter.add_axes(line_width=3, color="black")
    plotter.set_background("white")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("case", nargs="?", default="case")
    ap.add_argument("--frames", type=int, default=180)
    ap.add_argument("--fps", type=int, default=30)
    ap.add_argument("--still", action="store_true", help="write only the PNG")
    args = ap.parse_args()
    case = Path(args.case)

    pv.OFF_SCREEN = True
    plotter = pv.Plotter(off_screen=True, window_size=(1600, 1008))
    build_scene(case, plotter)

    g = plot_slice.geometry(case)
    focus = (g["roomLength"] / 2, g["roomWidth"] / 2, g["roomHeight"] / 2)
    # Put the camera far enough back that the scene's full diagonal fits inside
    # the field of view with 20 % margin, at every azimuth. Derived rather than
    # guessed, so it still frames correctly if the row gets longer.
    VIEW_ANGLE = 30.0
    diag = (g["roomLength"] ** 2 + g["roomWidth"] ** 2 + g["roomHeight"] ** 2) ** 0.5
    radius = (0.52 * diag) / np.tan(np.radians(VIEW_ANGLE / 2))

    # Caption the real load distribution, not an assumed uniform one.
    import plot_row
    n = int(g["nCabinets"])
    kw = plot_row.loads(case, n)
    spread = "" if len(set(kw)) == 1 else "  (" + "/".join(f"{v:g}" for v in kw) + " kW)"
    plotter.add_text(
        f"{n} cabinet row, {sum(kw):g} kW total{spread} - fan wall unit with "
        f"top intake, {g['coldAisleDepth']:g} m cold aisle",
        position="upper_left", font_size=11, color="black")

    def place(az_deg: float, elev: float = 0.42) -> None:
        a = np.radians(az_deg)
        plotter.camera.focal_point = focus
        plotter.camera.position = (focus[0] + radius * np.cos(a),
                                   focus[1] + radius * np.sin(a),
                                   focus[2] + radius * elev)
        plotter.camera.up = (0, 0, 1)
        plotter.camera.view_angle = VIEW_ANGLE   # perspective, not parallel

    place(215)
    still = case / "perspective.png"
    plotter.screenshot(str(still))
    print(f"wrote {still}")

    if not args.still:
        out = case / "perspective.mp4"
        plotter.open_movie(str(out), framerate=args.fps, quality=8)
        for i in range(args.frames):
            place(215 + 360.0 * i / args.frames)
            plotter.write_frame()
        plotter.close()
        print(f"wrote {out}  ({out.stat().st_size/1e6:.1f} MB, "
              f"{args.frames} frames at {args.fps} fps)")
    else:
        plotter.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
