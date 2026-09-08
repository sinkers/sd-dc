#!/usr/bin/env python3
"""Bake the CFD's sampled slices into textures Unreal can sample in real time.

The CFD writes three planes as scattered point data (`x y z value`, 51k-73k
points each). Unreal wants regular textures. This script grids them and writes
16-bit PNGs plus a manifest recording each plane's world placement and the value
range needed to un-normalise.

## How this stays "live" with only one CFD operating point

The baked texture supplies the *spatial pattern* — where the hot plume sits, how
the cold aisle stratifies. The ROM supplies the *magnitudes*, published every
frame as two scalars per plane:

    T_displayed(x) = T_supply_now + (T_baked(x) - T_supply_baked) * scale

where `scale` is the ratio of the hall's current supply-to-hot-aisle difference
to the baked case's. So turning the supply temperature down slides the whole
field; dropping the IT load compresses it toward the supply temperature; a fan
wall tripping widens it. The pattern is fixed, which is the honest limitation:
one basis field cannot change *shape* when the flow field genuinely
reorganises (a module going offline really does move the plume, not just scale
it).

The upgrade path, in order of cost:
  1. bake several operating points (unitsOff, supply temp, airflow turndown are
     all boundary-condition-only CFD changes: same mesh, restart from the
     converged field) and blend between the nearest bases;
  2. only if that is not enough, a POD/modal decomposition over a larger set.

Usage:
    ./bake_slices.py                       # all planes from case-hall at 4000
    ./bake_slices.py --resolution 1024 512
    ./bake_slices.py --case ../../cfd-cabinet-cooling/case-hall --time 4000
"""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
DEFAULT_CASE = REPO / "cfd-cabinet-cooling" / "case-hall"
BAKED = Path(__file__).resolve().parent / "baked"

# The three planes the CFD samples (case-hall/system/slices). `normal` is the
# constant axis; the other two become the texture's u and v.
PLANES = {
    "coldAisleA": {"normal": "z", "u": "x", "v": "y"},
    "rowAcentre": {"normal": "y", "u": "x", "v": "z"},
    "hallCentre": {"normal": "y", "u": "x", "v": "z"},
}


@dataclass
class PlaneManifest:
    name: str
    field: str
    file: str
    normal_axis: str
    normal_position_m: float
    u_axis: str
    v_axis: str
    u_range_m: list[float]
    v_range_m: list[float]
    resolution: list[int]
    value_min: float
    value_max: float
    units: str
    encoding: str
    points_sampled: int


def read_raw(path: Path) -> tuple[np.ndarray, np.ndarray]:
    """Return (points[N,3], values[N,k]) from an OpenFOAM raw surface file."""
    data = np.loadtxt(path, comments="#")
    if data.ndim != 2 or data.shape[1] < 4:
        raise ValueError(f"unexpected shape {data.shape} in {path}")
    return data[:, :3], data[:, 3:]


def grid_plane(
    points: np.ndarray,
    values: np.ndarray,
    plane: dict,
    resolution: tuple[int, int],
) -> tuple[np.ndarray, dict]:
    """Interpolate scattered points onto a regular grid in the plane's own axes."""
    from scipy.interpolate import griddata

    axis = {"x": 0, "y": 1, "z": 2}
    ui, vi, ni = axis[plane["u"]], axis[plane["v"]], axis[plane["normal"]]
    u, v = points[:, ui], points[:, vi]
    u_range = (float(u.min()), float(u.max()))
    v_range = (float(v.min()), float(v.max()))

    nu, nv = resolution
    gu = np.linspace(*u_range, nu)
    gv = np.linspace(*v_range, nv)
    mesh_u, mesh_v = np.meshgrid(gu, gv)

    # Linear where the sample points cover the plane, nearest to fill the holes
    # the geometry cuts out (racks, fan wall units) so the texture has no NaNs.
    linear = griddata((u, v), values, (mesh_u, mesh_v), method="linear")
    nearest = griddata((u, v), values, (mesh_u, mesh_v), method="nearest")
    grid = np.where(np.isnan(linear), nearest, linear)

    meta = {
        "u_range_m": list(u_range),
        "v_range_m": list(v_range),
        "normal_position_m": float(np.median(points[:, ni])),
    }
    return grid, meta


def write_png16(path: Path, normalised: np.ndarray) -> None:
    """Write a single-channel 16-bit PNG with no third-party image library.

    `normalised` is in 0..1, row 0 at the bottom (v increasing upward), which is
    flipped here so the PNG reads top-down as image formats expect.
    """
    import struct
    import zlib

    a = np.clip(normalised, 0.0, 1.0)
    a = np.flipud(a)
    px = (a * 65535.0 + 0.5).astype(">u2")
    height, width = px.shape

    raw = bytearray()
    for row in px:
        raw.append(0)  # filter type 0
        raw.extend(row.tobytes())

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    header = struct.pack(">IIBBBBB", width, height, 16, 0, 0, 0, 0)  # 16-bit grey
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", header)
        + chunk(b"IDAT", zlib.compress(bytes(raw), 9))
        + chunk(b"IEND", b"")
    )


def bake(
    case: Path,
    time: str,
    resolution: tuple[int, int],
    out: Path,
) -> list[PlaneManifest]:
    slices = case / "postProcessing" / "slices" / time
    if not slices.is_dir():
        raise SystemExit(f"no sampled slices at {slices}")
    out.mkdir(parents=True, exist_ok=True)

    manifests: list[PlaneManifest] = []
    for name, plane in PLANES.items():
        for field, units in (("T", "degC"), ("U", "m/s")):
            src = slices / f"{field}_{name}.raw"
            if not src.exists():
                print(f"  skip {src.name} (not sampled)")
                continue

            points, values = read_raw(src)
            if field == "T":
                values = values[:, :1] - 273.15  # bake in Celsius
            else:
                values = np.linalg.norm(values[:, :3], axis=1, keepdims=True)

            grid, meta = grid_plane(points, values, plane, resolution)
            grid = grid[..., 0]

            vmin, vmax = float(np.nanmin(grid)), float(np.nanmax(grid))
            span = max(vmax - vmin, 1e-6)
            png = out / f"{field}_{name}.png"
            write_png16(png, (grid - vmin) / span)

            manifests.append(
                PlaneManifest(
                    name=name,
                    field=field,
                    file=png.name,
                    normal_axis=plane["normal"],
                    normal_position_m=round(meta["normal_position_m"], 4),
                    u_axis=plane["u"],
                    v_axis=plane["v"],
                    u_range_m=[round(x, 4) for x in meta["u_range_m"]],
                    v_range_m=[round(x, 4) for x in meta["v_range_m"]],
                    resolution=list(resolution),
                    value_min=round(vmin, 4),
                    value_max=round(vmax, 4),
                    units=units,
                    encoding="grey16, value = value_min + png/65535 * (value_max - value_min)",
                    points_sampled=int(len(points)),
                )
            )
            print(
                f"  {png.name}: {len(points)} points -> {resolution[0]}x{resolution[1]}, "
                f"{vmin:.2f}..{vmax:.2f} {units}"
            )
    return manifests


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--case", type=Path, default=DEFAULT_CASE)
    ap.add_argument("--time", default=None, help="time directory (default: latest)")
    ap.add_argument(
        "--resolution", type=int, nargs=2, default=(512, 256), metavar=("NU", "NV")
    )
    ap.add_argument("--out", type=Path, default=BAKED)
    args = ap.parse_args(argv)

    slices_root = args.case / "postProcessing" / "slices"
    if args.time:
        time = args.time
    else:
        times = sorted(
            (p.name for p in slices_root.iterdir() if p.is_dir()),
            key=lambda s: float(s),
        )
        if not times:
            raise SystemExit(f"no time directories under {slices_root}")
        time = times[-1]

    print(f"baking {args.case.name} slices at t={time} -> {args.out}")
    manifests = bake(args.case, time, tuple(args.resolution), args.out)
    if not manifests:
        raise SystemExit("nothing baked")

    # The reference state the ROM remaps these fields against.
    from dthall.topology import from_hall_parameters

    spec = from_hall_parameters(args.case / "system" / "hallParameters")
    temps = [m for m in manifests if m.field == "T"]
    manifest = {
        "source_case": str(args.case.relative_to(REPO)),
        "source_time": time,
        "reference": {
            "supply_temp_c": spec.supply_temp_c,
            "hall_delta_t_k": spec.design_delta_t_k,
            "it_load_kw": spec.design_load_kw,
            "note": (
                "Telemetry publishes fields.scale and fields.offset_k each frame. "
                "Remap as: T = supply_temp_c + offset_k + (T_baked - supply_temp_c) * scale"
            ),
        },
        "peak_baked_temp_c": max((m.value_max for m in temps), default=None),
        "planes": [asdict(m) for m in manifests],
    }
    path = args.out.parent / "slice_manifest.json"
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
