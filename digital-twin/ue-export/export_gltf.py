"""Export AU01 geometry from FreeCAD to glTF for Unreal, preserving node names.

Run this **inside FreeCAD**, either through the MCP bridge
(`mcp__freecad__execute_code`) or from FreeCAD's own Python console. It is not
importable by the twin's test suite — it depends on the FreeCAD runtime.

## Why glTF and not the existing STLs

`cfd-cabinet-cooling/geometry/CFD_Export_RevE/` already has clean STLs, but STL
is a bag of unnamed triangles: it carries no object names, no hierarchy and no
materials. The whole binding strategy here depends on names — a rack actor in
Unreal finds its telemetry by being called `rack_A05`, the same string the CFD
function object and `cfd_export_params.json` use. glTF preserves node names and
imports natively into UE 5 (enable the built-in glTF Importer plugin).

## Why re-export rather than convert

The CFD export is deliberately *reduced*: sub-50 mm clutter dropped, outboard
legs removed, everything simplified to what the mesher needs. The twin wants the
opposite — more parts, not fewer, because it is being looked at rather than
meshed. So this reads the same source model and exports a richer selection.

## Fidelity beyond the CFD export

| Group | CFD export | This export |
|---|---|---|
| shell | single fused box + gable | walls, roof, doors, penetrations as separate nodes |
| racks | 24 plain boxes | 24 enclosures, per-rack named, front/rear faces separate so doors can be perforated in UE |
| fan walls | blockage boxes + patch quads | full FWCV bodies, per-module, with grille faces |
| HAC | baffles + end doors | same, plus frames and door leaves as separate nodes |
| gantry | decimated, clutter removed | full detail — it reads as the visual anchor of the room |
| dressing | absent | floor, lighting, CDU bay, pump-room wall if present in the model |

Usage inside FreeCAD:

    exec(open('/path/to/export_gltf.py').read())
    export_all('/path/to/digital-twin/ue-export/assets')
"""

from __future__ import annotations

import json
import os

# Groups to export, in the order Unreal should import them. Each entry lists the
# FreeCAD label prefixes to gather. Labels come from the AU01 building model
# (DAME_AU01_Building.FCStd); the CFD export group `_80_CFD_Export` is the
# reference for how these are named.
GROUPS = {
    "shell": ["_10_Shell", "Wall", "Roof", "Slab", "Door", "RollerDoor"],
    "racks": ["rack_", "_30_Racks", "Cabinet"],
    "fanwalls": ["fanwall", "FW-", "_40_FanWall", "FWCV"],
    "hac": ["hac", "HAC", "Containment", "Baffle"],
    "gantry": ["gantry", "Gantry", "Tray", "Busway", "FireMain", "_60_Services"],
    "dressing": ["CDU", "PumpRoom", "Light", "Floor", "_70_"],
}

# Metres. FreeCAD works in mm; glTF is metres, Y-up, right-handed. UE is Z-up,
# left-handed, centimetres, and its importer handles the axis/scale conversion —
# but only if the glTF is genuinely in metres, hence the explicit scale.
MM_TO_M = 0.001


def _doc():
    import FreeCAD

    doc = FreeCAD.ActiveDocument
    if doc is None:
        raise RuntimeError(
            "no active FreeCAD document; open DAME_AU01_Building.FCStd first"
        )
    return doc


def _visible_shapes(doc):
    """Every object with a shape, keyed by label."""
    out = {}
    for obj in doc.Objects:
        shape = getattr(obj, "Shape", None)
        if shape is None or shape.isNull():
            continue
        if not shape.Faces:
            continue
        out[obj.Label] = obj
    return out


def match_group(label: str) -> str | None:
    for group, prefixes in GROUPS.items():
        for prefix in prefixes:
            if label.startswith(prefix) or prefix in label:
                return group
    return None


def export_all(out_dir: str, groups: list[str] | None = None) -> dict:
    """Export one .glb per group and write the actor-binding manifest.

    Returns the manifest dict, which is also written to `export_manifest.json`.
    """
    import FreeCAD
    import importGLTF  # FreeCAD's glTF exporter

    doc = _doc()
    os.makedirs(out_dir, exist_ok=True)
    shapes = _visible_shapes(doc)

    buckets: dict[str, list] = {g: [] for g in GROUPS}
    unmatched: list[str] = []
    for label, obj in sorted(shapes.items()):
        group = match_group(label)
        if group is None:
            unmatched.append(label)
        else:
            buckets[group].append(obj)

    manifest = {
        "source_document": doc.Name,
        "units": "m",
        "scale_applied": MM_TO_M,
        "up_axis": "Y (glTF convention; UE importer converts to Z-up)",
        "groups": {},
        "racks": {},
        "unmatched_labels": unmatched,
    }

    wanted = groups or list(GROUPS)
    for group in wanted:
        objs = buckets.get(group) or []
        if not objs:
            print(f"  {group}: nothing matched, skipping")
            continue
        path = os.path.join(out_dir, f"{group}.glb")
        importGLTF.export([o for o in objs], path)
        manifest["groups"][group] = {
            "file": os.path.basename(path),
            "node_count": len(objs),
            "nodes": [o.Label for o in objs],
        }
        print(f"  {group}: {len(objs)} nodes -> {os.path.basename(path)}")

    # The rack binding table: Unreal actor name -> telemetry key. Rack labels in
    # the model are `rack_A03-HD`; telemetry keys are the bare position `A03`.
    for obj in buckets.get("racks") or []:
        label = obj.Label
        if not label.startswith("rack_"):
            continue
        tag = label[len("rack_") :]
        telemetry_key = tag.split("-")[0]
        box = obj.Shape.BoundBox
        manifest["racks"][label] = {
            "telemetry_key": telemetry_key,
            "centre_m": [
                round(box.Center.x * MM_TO_M, 4),
                round(box.Center.y * MM_TO_M, 4),
                round(box.Center.z * MM_TO_M, 4),
            ],
            "size_m": [
                round(box.XLength * MM_TO_M, 4),
                round(box.YLength * MM_TO_M, 4),
                round(box.ZLength * MM_TO_M, 4),
            ],
        }

    path = os.path.join(out_dir, "export_manifest.json")
    with open(path, "w") as fh:
        json.dump(manifest, fh, indent=2)
    print(f"  wrote {path}")

    if unmatched:
        print(
            f"\n  {len(unmatched)} labels matched no group. Check whether any of "
            f"these should be exported, and extend GROUPS if so:\n    "
            + "\n    ".join(unmatched[:25])
        )
    if not manifest["racks"]:
        print(
            "\n  WARNING: no rack_* labels found. Unreal actors bind to telemetry "
            "by these names, so the scene cannot be wired without them. Check the "
            "model's rack naming against cfd_export_params.json rack_schedule_kw."
        )
    return manifest


def verify_against_cfd_params(manifest: dict, params_path: str) -> list[str]:
    """Cross-check the export against the CFD geometry contract.

    Catches the failure that would otherwise only show up as a scene that looks
    subtly wrong: a rack in the wrong bay, or a model exported in millimetres.
    """
    with open(params_path) as fh:
        params = json.load(fh)
    problems = []

    expected = set(params["rack_schedule_kw"])
    got = {r["telemetry_key"] for r in manifest["racks"].values()}
    # schedule keys are "A03-HD"; telemetry keys are "A03"
    expected_keys = {k.split("-")[0] for k in expected}
    if missing := expected_keys - got:
        problems.append(f"racks missing from the export: {sorted(missing)}")
    if extra := got - expected_keys:
        problems.append(f"racks in the export but not the schedule: {sorted(extra)}")

    room = params["room"]
    x_max = room["x"][1] * params["scale"]
    y_max = room["y"][1] * params["scale"]
    for label, rack in manifest["racks"].items():
        cx, cy, _ = rack["centre_m"]
        if not (0 <= cx <= x_max and 0 <= cy <= y_max):
            problems.append(
                f"{label} centre {rack['centre_m']} lies outside the room "
                f"({x_max:.2f} x {y_max:.2f} m) - check units"
            )
        sx, sy, sz = rack["size_m"]
        if not (0.3 < sx < 1.5 and 0.5 < sy < 2.0 and 1.0 < sz < 2.6):
            problems.append(f"{label} size {rack['size_m']} is not a 600x1200x2000 rack")

    return problems


if __name__ == "__main__":
    here = os.path.dirname(os.path.abspath(__file__))
    result = export_all(os.path.join(here, "assets"))
    params = os.path.join(
        here,
        "..",
        "..",
        "cfd-cabinet-cooling",
        "geometry",
        "CFD_Export_RevE",
        "cfd_export_params.json",
    )
    if os.path.exists(params):
        issues = verify_against_cfd_params(result, params)
        print("\n" + ("\n".join(f"  PROBLEM: {p}" for p in issues) or "  geometry checks passed"))
