#!/usr/bin/env python3
"""Pack the AU01 STL export into one binary bundle the browser viewer can fetch.

Reads `cfd-cabinet-cooling/geometry/CFD_Export_RevE/*.stl` (ASCII, metres) and
writes:

    viewer/geometry/geometry.bin     concatenated float32 triangle positions
    viewer/geometry/manifest.json    part table, rack bindings, airflow emitters

Three things this does that a plain STL-per-file approach would not:

1. **Keeps the solid names.** The ASCII STLs carry named solids
   (`solid rack_A05-HD`), which is the whole binding mechanism — a rack mesh in
   the browser finds its telemetry by that name. `THREE.STLLoader` discards them.

2. **One fetch instead of forty.** Positions only; normals are recomputed in the
   browser, which halves the payload and gives correct flat shading on
   non-indexed geometry anyway.

3. **Derives the airflow emitters from the real faces.** `racks_intake.stl` and
   `racks_exhaust.stl` contain the actual breathing faces per rack, so the
   particle emitters sit exactly where the CFD's own inlet/outlet face zones sit,
   with the correct outward normal. No hand-placed guesses.

Usage:  ./prepare_geometry.py
"""

from __future__ import annotations

import json
import re
import struct
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EXPORT = REPO / "cfd-cabinet-cooling" / "geometry" / "CFD_Export_RevE"
OUT = HERE / "geometry"

# Which STL files to pack, and the render group each belongs to. Groups drive
# material choice and visibility toggles in the viewer.
SOURCES = [
    ("room_shell.stl", "shell"),
    ("racks_body.stl", "racks"),
    ("racks_intake.stl", "rack_intake_faces"),
    ("racks_exhaust.stl", "rack_exhaust_faces"),
    ("fanwall_w_body.stl", "fanwalls"),
    ("fanwall_e_body.stl", "fanwalls"),
    ("fw_w_supply_m1.stl", "supply_faces"),
    ("fw_w_supply_m2.stl", "supply_faces"),
    ("fw_e_supply_m1.stl", "supply_faces"),
    ("fw_e_supply_m2.stl", "supply_faces"),
    ("fw_w_intake_m1.stl", "intake_faces"),
    ("fw_w_intake_m2.stl", "intake_faces"),
    ("fw_e_intake_m1.stl", "intake_faces"),
    ("fw_e_intake_m2.stl", "intake_faces"),
    ("hac.stl", "hac"),
    ("bulkheads_h3000.stl", "bulkheads"),
    ("gantry.stl", "gantry"),
]

# Maps a fan-wall patch solid name to the telemetry module key. The CFD export
# names modules by end and index (`fw_w_supply_m1`); telemetry uses W1/W2/E1/E2.
MODULE_OF_PATCH = {
    "fw_w_supply_m1": "W1",
    "fw_w_supply_m2": "W2",
    "fw_e_supply_m1": "E1",
    "fw_e_supply_m2": "E2",
    "fw_w_intake_m1": "W1",
    "fw_w_intake_m2": "W2",
    "fw_e_intake_m1": "E1",
    "fw_e_intake_m2": "E2",
}

VERTEX_RE = re.compile(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)")


@dataclass
class Solid:
    name: str
    group: str
    source: str
    positions: list[float] = field(default_factory=list)

    @property
    def triangles(self) -> int:
        return len(self.positions) // 9


def parse_ascii_stl(path: Path, group: str) -> list[Solid]:
    """Split an ASCII STL into its named solids, keeping only vertex positions."""
    solids: list[Solid] = []
    current: Solid | None = None
    for line in path.read_text().splitlines():
        s = line.strip()
        if s.startswith("solid"):
            name = s[len("solid") :].strip() or path.stem
            current = Solid(name=name, group=group, source=path.name)
            solids.append(current)
        elif s.startswith("endsolid"):
            current = None
        elif s.startswith("vertex") and current is not None:
            m = VERTEX_RE.match(s)
            if m:
                current.positions.extend(float(v) for v in m.groups())
    return [s for s in solids if s.triangles]


def bbox(positions: list[float]) -> dict:
    xs = positions[0::3]
    ys = positions[1::3]
    zs = positions[2::3]
    return {
        "min": [round(min(xs), 4), round(min(ys), 4), round(min(zs), 4)],
        "max": [round(max(xs), 4), round(max(ys), 4), round(max(zs), 4)],
        "centre": [
            round((min(xs) + max(xs)) / 2, 4),
            round((min(ys) + max(ys)) / 2, 4),
            round((min(zs) + max(zs)) / 2, 4),
        ],
    }


def face_plane(positions: list[float]) -> dict:
    """Describe a flat quad/face solid: centre, outward normal, and extents.

    The rack intake/exhaust solids and the fan-wall patch solids are all planar,
    so the normal is well defined and is what the particle emitters aim along.
    Sign is resolved later against the rack's own body centre, since an STL's
    winding tells us a normal direction but not which side is "out of the rack".
    """
    box = bbox(positions)
    lo, hi = box["min"], box["max"]
    extent = [hi[i] - lo[i] for i in range(3)]
    axis = extent.index(min(extent))  # the degenerate axis is the normal
    normal = [0.0, 0.0, 0.0]
    normal[axis] = 1.0
    return {
        "centre": box["centre"],
        "normal": normal,
        "extent": [round(e, 4) for e in extent],
        "axis": "xyz"[axis],
        "area": round(
            max(
                extent[(axis + 1) % 3] * extent[(axis + 2) % 3],
                1e-9,
            ),
            4,
        ),
    }


def telemetry_key(solid_name: str) -> str | None:
    """`rack_A05-HD` -> `A05`; `rack_A05-HD_intake` -> `A05`."""
    if not solid_name.startswith("rack_"):
        return None
    tag = solid_name[len("rack_") :]
    for suffix in ("_intake", "_exhaust"):
        if tag.endswith(suffix):
            tag = tag[: -len(suffix)]
    return tag.split("-")[0]


def main() -> int:
    if not EXPORT.is_dir():
        raise SystemExit(f"geometry export not found at {EXPORT}")
    OUT.mkdir(parents=True, exist_ok=True)

    solids: list[Solid] = []
    for filename, group in SOURCES:
        path = EXPORT / filename
        if not path.exists():
            print(f"  skip {filename} (absent)")
            continue
        found = parse_ascii_stl(path, group)
        solids.extend(found)
        print(f"  {filename}: {len(found)} solids, {sum(s.triangles for s in found)} triangles")

    # -- pack the binary blob ------------------------------------------------
    blob = bytearray()
    parts = []
    for s in solids:
        offset = len(blob) // 4  # in float32 units
        blob.extend(struct.pack(f"<{len(s.positions)}f", *s.positions))
        parts.append(
            {
                "name": s.name,
                "group": s.group,
                "source": s.source,
                "offset": offset,
                "floats": len(s.positions),
                "triangles": s.triangles,
                "bbox": bbox(s.positions),
            }
        )
    (OUT / "geometry.bin").write_bytes(bytes(blob))

    # -- rack bindings -------------------------------------------------------
    by_group: dict[str, list[Solid]] = {}
    for s in solids:
        by_group.setdefault(s.group, []).append(s)

    racks: dict[str, dict] = {}
    for s in by_group.get("racks", []):
        key = telemetry_key(s.name)
        if key:
            racks[key] = {
                "mesh": s.name,
                "bbox": bbox(s.positions),
                "row": key[0],
                "position": int(key[1:]),
            }

    for group, field_name in (
        ("rack_intake_faces", "intake"),
        ("rack_exhaust_faces", "exhaust"),
    ):
        for s in by_group.get(group, []):
            key = telemetry_key(s.name)
            if key and key in racks:
                racks[key][field_name] = face_plane(s.positions)

    # Resolve normal signs so they point out of the rack: an intake face's normal
    # should point away from the rack body (air comes toward it), an exhaust
    # face's normal likewise. Without this the streams blow the wrong way, which
    # looks plausible until you notice the hot aisle is being fed from outside.
    for key, rack in racks.items():
        centre = rack["bbox"]["centre"]
        for field_name in ("intake", "exhaust"):
            face = rack.get(field_name)
            if not face:
                continue
            axis = "xyz".index(face["axis"])
            outward = 1.0 if face["centre"][axis] > centre[axis] else -1.0
            face["normal"] = [
                round(n * outward, 4) for n in face["normal"]
            ]

    # -- fan wall module patches --------------------------------------------
    modules: dict[str, dict] = {}
    for group, field_name in (("supply_faces", "supply"), ("intake_faces", "intake")):
        for s in by_group.get(group, []):
            module = MODULE_OF_PATCH.get(s.name)
            if module is None:
                continue
            entry = modules.setdefault(module, {"end": "west" if "_w_" in s.name else "east"})
            plane = face_plane(s.positions)
            # Supply blows into the room (toward the pod), intake draws from it.
            axis = "xyz".index(plane["axis"])
            toward_pod = 1.0 if entry["end"] == "west" else -1.0
            if field_name == "supply":
                plane["normal"] = [0.0, 0.0, 0.0]
                plane["normal"][axis] = toward_pod
            else:
                plane["normal"] = [0.0, 0.0, 0.0]
                plane["normal"][axis] = -toward_pod
            entry[field_name] = plane

    # Fan wall body extents. The viewer needs these to route return air *over*
    # each unit and down into the corridor behind it: the unit is a solid block
    # 4 m tall spanning the full width of the hall's centre, so a straight line
    # from the hot aisle to the rear intake would pass through it.
    bodies = {}
    for s in by_group.get("fanwalls", []):
        end = "west" if s.name.endswith("_w") else "east"
        bodies[end] = bbox(s.positions)

    params_path = EXPORT / "cfd_export_params.json"
    params = json.loads(params_path.read_text()) if params_path.exists() else {}
    scale = params.get("scale", 0.001)
    room = params.get("room", {})
    hac = params.get("hac", {})

    manifest = {
        "units": "m",
        "up_axis": "z",
        "source": str(EXPORT.relative_to(REPO)),
        "binary": "geometry.bin",
        "total_triangles": sum(p["triangles"] for p in parts),
        "parts": parts,
        "racks": racks,
        "modules": modules,
        "fanwall_bodies": bodies,
        "room": {
            "x": [v * scale for v in room.get("x", [0, 24.13])],
            "y": [v * scale for v in room.get("y", [0, 8.2])],
            "eave": room.get("eave", 4090) * scale,
            "apex": room.get("apex", 4786) * scale,
        },
        "hot_aisle": {
            "x": [v * scale for v in hac.get("x", [8435, 15755])],
            "y": [v * scale for v in hac.get("y", [3200, 5000])],
            "baffle_z": [v * scale for v in hac.get("baffle_z", [2000, 3960])],
            "open_top": True,
        },
    }
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")

    print(
        f"\n  packed {len(parts)} parts, {manifest['total_triangles']} triangles, "
        f"{len(blob) / 1024:.0f} KB binary"
    )
    print(f"  racks bound: {len(racks)}")
    missing = [k for k, r in racks.items() if "intake" not in r or "exhaust" not in r]
    if missing:
        print(f"  WARNING: racks without intake/exhaust faces: {sorted(missing)}")
    print(f"  fan wall modules: {sorted(modules)}")
    for m in sorted(modules):
        s = modules[m].get("supply", {})
        print(
            f"    {m}: supply centre {s.get('centre')} normal {s.get('normal')} "
            f"area {s.get('area')} m2"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
