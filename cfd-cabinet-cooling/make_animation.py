#!/usr/bin/env python3
"""
Build an animation of the parameter sweep: one frame per run, showing the
centreline temperature field sweeping from under-supplied (recirculating, FAIL)
through to over-supplied (bypassing, PASS) and back.

This case is steady-state, so there is no physical time axis to animate. The
meaningful thing to animate is the design parameter, which is what this does.

Usage:
    ./make_animation.py                    # sweep over whatever is in results.csv
    ./make_animation.py --param fanWallVelocity

Writes runs/anim/frame_*.png, runs/sweep.gif and (if ffmpeg is present)
runs/sweep.mp4
"""

from __future__ import annotations

import argparse
import csv
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

import plot_slice

UNITS = {
    "fanWallVelocity": "m/s",
    "supplyTemp": "K",
    "containmentTopZ": "m",
    "heatLoad": "W",
}

PRETTY = {
    "fanWallVelocity": "fan wall velocity",
    "supplyTemp": "supply temperature",
    "containmentTopZ": "containment top height",
    "heatLoad": "IT load",
}


def load_rows(results: Path, param: str | None) -> tuple[str, list[dict]]:
    if not results.is_file():
        raise SystemExit(f"{results} not found - run ./sweep.sh first")

    with results.open() as fh:
        rows = [r for r in csv.DictReader(fh) if r.get("verdict") not in (None, "", "ERROR")]
    if not rows:
        raise SystemExit(f"no usable rows in {results}")

    params = sorted({r["param"] for r in rows})
    if param is None:
        if len(params) > 1:
            raise SystemExit(
                f"{results} contains several swept parameters {params}; "
                f"choose one with --param"
            )
        param = params[0]
    elif param not in params:
        raise SystemExit(f"parameter '{param}' not in {results} (have {params})")

    rows = [r for r in rows if r["param"] == param]
    rows.sort(key=lambda r: float(r["value"]))
    return param, rows


def caption(param: str, row: dict) -> str:
    unit = UNITS.get(param, "")
    value = float(row["value"])
    verdict = row["verdict"]
    Ti = float(row["inletT_C"])
    Tmax = float(row["inletTmax_C"])
    gap = float(row["gap_kgs"])
    supply = float(row["supply_kgs"])
    through = float(row["through_kgs"])

    # Ratio against what the servers actually drew in this same run, rather
    # than a fixed reference, so the caption stays true if the fans droop.
    pct = f"   ({supply / through * 100:.0f} % of server demand)" if through else ""

    flow = (
        f"cold bypass {gap:+.2f} kg/s" if gap >= 0
        else f"HOT AIR RECIRCULATING {gap:+.2f} kg/s"
    )

    return (
        f"{PRETTY.get(param, param)} = {value:g} {unit}{pct}\n"
        f"server intake  mean {Ti:.1f} degC   max {Tmax:.1f} degC     "
        f"{flow}     [ {verdict} ]"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--param", default=None, help="which swept parameter to animate")
    ap.add_argument("--results", default="runs/results.csv")
    ap.add_argument("--hold", type=float, default=1.4, help="seconds per frame")
    args = ap.parse_args()

    results = Path(args.results)
    runs_dir = results.parent
    param, rows = load_rows(results, args.param)

    anim_dir = runs_dir / "anim"
    if anim_dir.exists():
        shutil.rmtree(anim_dir)
    anim_dir.mkdir(parents=True)

    frames: list[Path] = []
    for i, row in enumerate(rows):
        case = runs_dir / f"{param}_{row['value']}"
        if not (case / "postProcessing" / "slices").is_dir():
            print(f"  skipping {case.name}: no sampled slice "
                  f"(run: CASE_DIR={case} ./run.sh --sample)")
            continue
        out = anim_dir / f"frame_{i:02d}.png"
        plot_slice.render(case, out=out, title=caption(param, row))
        frames.append(out)
        print(f"  rendered {out.name}  ({row['value']} -> {row['verdict']})")

    if len(frames) < 2:
        raise SystemExit("need at least two sampled runs to animate")

    # Ping-pong so the loop sweeps up and back down instead of snapping.
    order = frames + frames[-2:0:-1]

    images = [Image.open(f).convert("RGB") for f in order]
    w, h = images[0].size
    scale = 1100 / w
    small = [im.resize((1100, int(h * scale)), Image.LANCZOS) for im in images]

    gif = runs_dir / "sweep.gif"
    small[0].save(gif, save_all=True, append_images=small[1:],
                  duration=int(args.hold * 1000), loop=0, optimize=True)
    print(f"wrote {gif}  ({gif.stat().st_size / 1e6:.1f} MB, {len(order)} frames)")

    if shutil.which("ffmpeg"):
        seq = anim_dir / "seq"
        seq.mkdir(exist_ok=True)
        for j, f in enumerate(order):
            shutil.copy(f, seq / f"s_{j:03d}.png")
        mp4 = runs_dir / "sweep.mp4"
        cmd = [
            "ffmpeg", "-y", "-loglevel", "error",
            "-framerate", f"{1 / args.hold:.4f}",
            "-i", str(seq / "s_%03d.png"),
            "-vf", "fps=25,pad=ceil(iw/2)*2:ceil(ih/2)*2",
            "-c:v", "libx264", "-pix_fmt", "yuv420p",
            str(mp4),
        ]
        subprocess.run(cmd, check=True)
        shutil.rmtree(seq)
        print(f"wrote {mp4}  ({mp4.stat().st_size / 1e6:.1f} MB)")
    else:
        print("ffmpeg not found - skipped MP4, GIF written")

    return 0


if __name__ == "__main__":
    sys.exit(main())
