#!/usr/bin/env python3
"""
Render the vertical centreline slice of a cabinet cooling run: air temperature
with the airflow drawn over it, so you can see at a glance whether cold air is
reaching the servers or hot air is spilling back over the containment.

Requires the sampled slice to exist:
    ./run.sh --sample          (or: postProcess -func slices -latestTime)

Usage:
    ./plot_slice.py [CASE_DIR]        # default: ./case

Writes <CASE_DIR>/slice.png
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import Rectangle  # noqa: E402
from matplotlib.tri import LinearTriInterpolator, Triangulation  # noqa: E402

KELVIN = 273.15

# Fixed colour range so every run in a sweep is directly comparable.
T_MIN_C, T_MAX_C = 18.0, 40.0

# Geometry is read from case/system/simulationParameters so the sketch always
# matches the mesh that was actually solved.
GEOMETRY_DEFAULTS = {
    "unitDepth": 0.8,
    "unitHeight": 2.6,
    "supplyZ0": 0.4,
    "supplyZ1": 2.4,
    "coldAisleDepth": 4.0,
    "cabinetDepth": 1.2,
    "cabinetHeight": 2.2,
    "hotAisleDepth": 1.2,
    "plenumHeight": 0.8,
    "containmentTopZ": 2.4,
    "cabinetPitch": 0.6,
    "nCabinets": 1,
    "endClearance": 0.0,
}


def find_slice_dir(case: Path) -> Path:
    root = case / "postProcessing" / "slices"
    if not root.is_dir():
        raise SystemExit(
            f"{root} not found.\n"
            f"Generate it with:  ./run.sh --sample"
        )
    times = sorted(root.iterdir(), key=lambda p: float(p.name))
    return times[-1]


def read_raw(path: Path) -> np.ndarray:
    rows = [
        [float(tok) for tok in line.split()]
        for line in path.read_text().splitlines()
        if line.strip() and not line.startswith("#")
    ]
    if not rows:
        raise SystemExit(f"{path} contains no data")
    return np.asarray(rows)


def geometry(case: Path) -> dict[str, float]:
    """Read the geometry block out of simulationParameters.

    Only the primitive lengths are read; the derived positions are recomputed
    here so this stays in step with the dictionary's own #eval expressions.
    """
    g = dict(GEOMETRY_DEFAULTS)
    params = case / "system" / "simulationParameters"
    try:
        for line in params.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2 and parts[0] in g:
                try:
                    g[parts[0]] = float(parts[1].rstrip(";"))
                except ValueError:
                    pass
    except OSError:
        pass

    g["rowWidth"] = g["nCabinets"] * g["cabinetPitch"]
    g["roomWidth"] = g["rowWidth"] + 2 * g["endClearance"]
    g["rowY0"] = g["endClearance"]
    g["rowY1"] = g["endClearance"] + g["rowWidth"]
    g["cabinetX0"] = g["unitDepth"] + g["coldAisleDepth"]
    g["cabinetX1"] = g["cabinetX0"] + g["cabinetDepth"]
    g["roomLength"] = g["cabinetX1"] + g["hotAisleDepth"]
    g["roomHeight"] = g["unitHeight"] + g["plenumHeight"]
    return g


def render(case: Path, out: Path | None = None, title: str | None = None) -> Path:
    """Render the centreline slice for `case`. Returns the written image path.

    `title` overrides the default heading, which make_animation.py uses to caption
    each frame with its swept value and verdict instead of a directory name.
    """
    sdir = find_slice_dir(case)
    g = geometry(case)
    room_x, room_z = g["roomLength"], g["roomHeight"]
    cab_x0, cab_x1, cab_z1 = g["cabinetX0"], g["cabinetX1"], g["cabinetHeight"]
    unit_d, unit_h = g["unitDepth"], g["unitHeight"]
    cont_z = g["containmentTopZ"]

    t_file = sdir / "T_centreline.raw"
    u_file = sdir / "U_centreline.raw"
    for f in (t_file, u_file):
        if not f.is_file():
            raise SystemExit(f"missing {f}")

    tdat = read_raw(t_file)
    udat = read_raw(u_file)

    x, z, T = tdat[:, 0], tdat[:, 2], tdat[:, 3] - KELVIN
    ux, uz = udat[:, 3], udat[:, 5]
    umag = np.hypot(ux, uz)

    tri = Triangulation(x, z)

    fig, ax = plt.subplots(figsize=(14.5, 7.6))

    levels = np.linspace(T_MIN_C, T_MAX_C, 45)
    cf = ax.tricontourf(tri, np.clip(T, T_MIN_C, T_MAX_C), levels=levels,
                        cmap="turbo", extend="both")
    cb = fig.colorbar(cf, ax=ax, pad=0.015, fraction=0.031)
    cb.set_label("air temperature [degC]", fontsize=11)
    cb.set_ticks(np.arange(18, 41, 2))

    # The 27 degC ASHRAE line: anything the cold aisle side of this is a problem.
    ax.tricontour(tri, T, levels=[27.0], colors="white", linewidths=1.6,
                  linestyles="--")

    # ---- airflow, interpolated onto a regular grid for streamlines ---------
    gx = np.linspace(0, room_x, 360)
    gz = np.linspace(0, room_z, 210)
    GX, GZ = np.meshgrid(gx, gz)
    GU = LinearTriInterpolator(tri, ux)(GX, GZ)
    GW = LinearTriInterpolator(tri, uz)(GX, GZ)
    GU = np.ma.filled(GU, 0.0)
    GW = np.ma.filled(GW, 0.0)

    ax.streamplot(GX, GZ, GU, GW, color="k", linewidth=0.6, density=2.0,
                  arrowsize=0.8, arrowstyle="->")

    # ---- geometry overlay --------------------------------------------------
    # Cabinet.
    ax.add_patch(Rectangle((cab_x0, 0), cab_x1 - cab_x0, cab_z1,
                           facecolor="0.20", edgecolor="k", lw=1.5, zorder=5))
    ax.text((cab_x0 + cab_x1) / 2, cab_z1 / 2, "CABINET\n30 kW",
            ha="center", va="center", color="w", fontsize=11,
            fontweight="bold", zorder=6)

    # Fan wall unit, with the supply opening left as a gap in its face.
    ax.add_patch(Rectangle((0, 0), unit_d, unit_h,
                           facecolor="0.32", edgecolor="k", lw=1.5, zorder=5))
    ax.text(unit_d / 2, unit_h * 0.45, "FAN\nWALL\nUNIT", ha="center",
            va="center", color="w", fontsize=10, fontweight="bold", zorder=6)

    # Supply discharge on the unit face.
    ax.plot([unit_d, unit_d], [g["supplyZ0"], g["supplyZ1"]],
            color="tab:blue", lw=6, zorder=7, solid_capstyle="butt")
    ax.text(unit_d + 0.12, (g["supplyZ0"] + g["supplyZ1"]) / 2, "SUPPLY",
            color="tab:blue", fontsize=10, fontweight="bold", rotation=90,
            ha="left", va="center", zorder=8,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="none", alpha=0.85))

    # Return intake on TOP of the unit.
    ax.plot([0, unit_d], [unit_h, unit_h], color="tab:red", lw=6, zorder=7,
            solid_capstyle="butt")
    ax.text(unit_d / 2, unit_h + 0.14, "INTAKE", ha="center", va="bottom",
            color="tab:red", fontsize=10, fontweight="bold", zorder=8,
            bbox=dict(boxstyle="round,pad=0.22", fc="white", ec="none", alpha=0.85))

    # Plenum floor, separating the cold aisle from the return plenum.
    ax.plot([unit_d, cab_x1], [unit_h, unit_h], color="k", lw=4, zorder=6,
            solid_capstyle="butt")

    # Containment panel above the cabinet.
    if cont_z > cab_z1:
        ax.plot([cab_x1, cab_x1], [cab_z1, cont_z], color="k", lw=5, zorder=6,
                solid_capstyle="butt")

    # The leakage gap: the whole point of the study.
    if cont_z < unit_h:
        ax.annotate(
            f"leakage gap {unit_h - cont_z:.2f} m",
            xy=(cab_x1, (cont_z + unit_h) / 2),
            xytext=(cab_x0 - 1.3, cont_z - 0.06),
            fontsize=9, ha="center", va="center", zorder=8,
            bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="0.4", alpha=0.92),
            arrowprops=dict(arrowstyle="->", lw=1.2),
        )

    # Region labels.
    ax.text((unit_d + cab_x0) / 2, 0.16, "COLD AISLE", ha="center", fontsize=11,
            color="navy", fontweight="bold", zorder=7)
    ax.text((cab_x1 + room_x) / 2, 0.16, "HOT\nAISLE", ha="center", fontsize=10,
            color="darkred", fontweight="bold", zorder=7)
    ax.text((unit_d + cab_x1) / 2, unit_h + (room_z - unit_h) / 2,
            "RETURN PLENUM", ha="center", va="center", fontsize=11,
            color="darkred", fontweight="bold", zorder=7)

    # Cold aisle depth dimension.
    ax.annotate("", xy=(unit_d, 0.62), xytext=(cab_x0, 0.62), zorder=8,
                arrowprops=dict(arrowstyle="<->", lw=1.1, color="navy"))
    ax.text((unit_d + cab_x0) / 2, 0.68, f"{g['coldAisleDepth']:.1f} m",
            ha="center", va="bottom", fontsize=9, color="navy", zorder=8,
            bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="none", alpha=0.85))

    ax.set_xlim(0, room_x)
    ax.set_ylim(0, room_z)
    ax.set_aspect("equal")
    ax.set_xlabel("x [m]")
    ax.set_ylabel("z [m]")
    ax.set_title(
        title if title is not None else (
            f"Centreline air temperature and airflow - {case}\n"
            f"peak speed {umag.max():.2f} m/s   "
            f"(white dashed line = 27 degC ASHRAE intake limit)"
        ),
        fontsize=12,
    )

    fig.tight_layout()
    out = out if out is not None else case / "slice.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=140)
    plt.close(fig)
    return out


def main() -> int:
    case = Path(sys.argv[1] if len(sys.argv) > 1 else "case")
    print(f"wrote {render(case)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
