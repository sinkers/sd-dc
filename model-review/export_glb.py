#!/usr/bin/env freecadcmd
"""Tessellate an .FCStd assembly into one GLB for web review.

Run it through export.sh, which is the only front door that gets the arguments
in (freecadcmd treats stray tokens as documents to open, so options travel in
EXPORT_GLB_ARGS):

    ./export.sh --fcstd "<model>.FCStd" --out viewer/model/au01.glb

Headless, so the GUI stays free and a FreeCAD VM runs it exactly as a laptop
does. Visibility is the filter that gets the part set right: FreeCAD hides a
solid when a fusion, cut or compound consumes it, so exporting only the visible
set avoids emitting a boolean's result *and* its inputs, which would double the
geometry and z-fight.

Meshing goes through `MeshPart.meshFromShape`, not `Shape.tessellate`. The
latter ignores its deviation argument on analytic surfaces - every cylinder
comes out at ~500 triangles whether you ask for 8 mm or 40 mm - the same trap
documented at length in liquid-twin/viewer/prepare_geometry.py. `meshFromShape`
honours both linear and angular deflection, so LOD is a knob here rather than a
wish.
"""

import argparse
import json
import os
import sys
import time

import FreeCAD

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fcstd_gui import (DEFAULT_COLOUR, ancestor_placement,  # noqa: E402
                        apply_container_visibility, facets, instance_key, parent_map,
                        read_gui_state, say, tree_paths, world_shape)
from glb import GlbBuilder  # noqa: E402

# Datum objects: construction aids that report faces but are not parts. Left
# in, they tessellate into the coloured sheets that spoil FreeCAD's own renders.
DATUM_TYPES = {"App::Plane", "App::Line", "App::Origin", "PartDesign::Plane",
               "PartDesign::Line", "PartDesign::Point"}


def _group_children(obj):
    """Every object under `obj`'s Group tree, however deep."""
    seen, stack, out = set(), list(getattr(obj, "Group", []) or []), []
    while stack:
        child = stack.pop()
        if child.Name in seen:
            continue
        seen.add(child.Name)
        out.append(child)
        stack.extend(getattr(child, "Group", []) or [])
    return out


def is_aggregate(obj, exportable):
    """True if `obj` only restates geometry that its children already carry.

    A group or App::Part exposes a Shape that is a compound of its contents.
    Exporting both the container and the contents doubles the geometry and makes
    it z-fight with itself, so the container has to go - but only once something
    inside it is actually being exported. If every child is hidden, the
    container's compound is the sole representation of that plant and dropping it
    would quietly delete it from the review model.

    This is checked per model rather than driven off a list of type names,
    because guessing that list got it wrong: `App::Link` was on it, and links
    turned out to be the only visible copy of the transformers and pump skids -
    23 of the 24 links in the AU01 model point at a hidden target. A link is
    never an aggregate; it holds no Group, so it can never match here.
    """
    if "Group" not in obj.PropertiesList:
        return False
    return any(child.Name in exportable and "Group" not in child.PropertiesList
               for child in _group_children(obj))


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fcstd", required=True, help="source .FCStd")
    ap.add_argument("--out", required=True, help="destination .glb")
    ap.add_argument("--deflection", type=float, default=12.0,
                    help="linear deflection in mm (default 12: plant-scale review)")
    ap.add_argument("--angular", type=float, default=30.0,
                    help="angular deflection in degrees (default 30)")
    ap.add_argument("--min-diag", type=float, default=0.0,
                    help="skip parts whose bbox diagonal is under this many mm")
    ap.add_argument("--probe", type=int, default=0,
                    help="mesh only this many parts, report cost, and stop")
    ap.add_argument("--show", action="append", default=[], metavar="GROUP_LABEL",
                    help="export this group and everything under it as shown, whatever "
                         "the saved view says (repeatable). FreeCAD hides a group by "
                         "hiding its children too, so leaf flags are overridden. The "
                         "fly-over uses it so a roof hidden for review still exports.")
    args = ap.parse_args(argv)

    started = time.time()
    say("opening %s" % args.fcstd)
    gui_state = read_gui_state(args.fcstd)
    doc = FreeCAD.openDocument(args.fcstd)
    paths = tree_paths(doc)
    parents = parent_map(doc)
    say("opened in %.0fs: %d objects" % (time.time() - started, len(doc.Objects)))

    # --show: everything under these groups counts as shown, before the hidden-
    # container pass runs. Hiding a group in FreeCAD's tree also clears its
    # children's own flags, so opening the group alone would export nothing.
    for label in args.show:
        matches = doc.getObjectsByLabel(label)
        if not matches:
            say("--show: no group labelled %r" % label)
        stack, seen = list(matches), set()
        while stack:
            obj = stack.pop()
            if obj.Name in seen:
                continue
            seen.add(obj.Name)
            _, colour = gui_state.get(obj.Name, (True, DEFAULT_COLOUR))
            gui_state[obj.Name] = (True, colour)
            stack.extend(getattr(obj, "Group", []) or [])
        say("--show %s: %d objects" % (label, len(seen)))

    # A hidden group hides its contents in FreeCAD without clearing their own
    # Visibility flags, so this has to run before anything trusts `gui_state`.
    containers, suppressed = apply_container_visibility(doc, gui_state)
    say("hidden groups: %d, suppressing %d parts inside them" % (containers, suppressed))

    # Pass one: everything a reviewer could see - visible, solid, not a datum.
    eligible = {}
    skipped_hidden = skipped_empty = skipped_small = 0
    skipped_aggregate = skipped_datum = 0
    for obj in doc.Objects:
        visible, colour = gui_state.get(obj.Name, (True, DEFAULT_COLOUR))
        if not visible:
            skipped_hidden += 1
            continue
        if obj.TypeId in DATUM_TYPES:
            skipped_datum += 1
            continue
        shape = getattr(obj, "Shape", None)
        if shape is None or not shape.Faces:
            skipped_empty += 1
            continue
        if args.min_diag and shape.BoundBox.DiagonalLength < args.min_diag:
            skipped_small += 1
            continue
        eligible[obj.Name] = (obj, colour)

    # Pass two: drop the containers whose contents are already in pass one. It
    # needs pass one complete first, since the test is whether a child survived.
    candidates = []
    for obj, colour in eligible.values():
        if is_aggregate(obj, eligible):
            skipped_aggregate += 1
            continue
        candidates.append((obj, colour))

    say("parts: %d to mesh" % len(candidates))
    say("  skipped: %d hidden, %d group aggregates, %d datums, %d without solids, %d too small"
        % (skipped_hidden, skipped_aggregate, skipped_datum, skipped_empty,
           skipped_small))

    if args.probe:
        sample = candidates[:args.probe]
        t0 = time.time()
        triangles = 0
        for obj, _ in sample:
            positions, _n = facets(obj.Shape, args.deflection, args.angular)
            triangles += len(positions) // 9
        elapsed = time.time() - t0
        per_part = elapsed / max(1, len(sample))
        tris_per_part = triangles / max(1, len(sample))
        say("PROBE %d parts: %d triangles in %.1fs" % (len(sample), triangles, elapsed))
        say("PROBE per part: %.0f triangles, %.2fs" % (tris_per_part, per_part))
        say("PROBE full run estimate: %.1fM triangles, %.0f min, ~%.0f MB raw"
              % (tris_per_part * len(candidates) / 1e6,
                 per_part * len(candidates) / 60.0,
                 tris_per_part * len(candidates) * 108 / 1e6))
        return 0

    builder = GlbBuilder()
    parts_table = []
    failures = []
    meshes = {}       # instance signature -> glTF mesh index
    reused = 0
    baked = 0         # parts whose transform failed the round-trip check
    for index, (obj, colour) in enumerate(candidates):
        try:
            ancestors = ancestor_placement(obj, parents)
            signature, local, translation, rotation = instance_key(obj, ancestors)
            if signature[0] == "world":
                baked += 1
            # Colour belongs to the instance, not the shape, so two copies of
            # one part painted differently must not share a mesh.
            signature = signature + (tuple(round(c, 4) for c in colour),)
            mesh = meshes.get(signature)
            if mesh is None:
                positions, normals = facets(local, args.deflection, args.angular)
                if not positions:
                    continue
                mesh = builder.add_mesh(obj.Label, positions, normals, colour)
                meshes[signature] = mesh
            else:
                reused += 1
        except Exception as exc:  # a single bad solid must not lose the export
            failures.append((obj.Name, str(exc)[:120]))
            continue

        path = paths.get(obj.Name, [])
        # The label goes in extras as well as the node name, because three.js
        # sanitises glTF node names on load and turns every space into an
        # underscore. The viewer shows the extras copy.
        builder.add_instance(obj.Label, mesh, translation=translation,
                             rotation=rotation, path=path,
                             extras={"name": obj.Name, "label": obj.Label})
        box = world_shape(obj, ancestors).BoundBox
        parts_table.append({
            "name": obj.Name, "label": obj.Label, "path": path,
            "mesh": mesh,
            "bbox": [round(v, 1) for v in (box.XMin, box.YMin, box.ZMin,
                                           box.XMax, box.YMax, box.ZMax)],
        })
        if index and index % 500 == 0:
            say("  %d/%d parts, %d meshes, %.2fM triangles, %.0fs"
                % (index, len(candidates), builder.mesh_count,
                   builder.unique_triangles / 1e6, time.time() - started))

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "wb") as fh:
        fh.write(builder.build())

    manifest = {
        "source": os.path.basename(args.fcstd),
        "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "deflection_mm": args.deflection,
        "angular_deg": args.angular,
        "min_diag_mm": args.min_diag,
        "parts": len(parts_table),
        "meshes": builder.mesh_count,
        "instanced_parts": reused,
        "world_baked_parts": baked,
        "triangles": builder.unique_triangles,
        "units": "source mm, glb metres",
        "part_table": parts_table,
    }
    side_car = os.path.splitext(args.out)[0] + ".parts.json"
    with open(side_car, "w") as fh:
        json.dump(manifest, fh, indent=1)

    size_mb = os.path.getsize(args.out) / 1e6
    say("wrote %s" % args.out)
    say("  %d parts from %d meshes (%d instanced), %.2fM triangles, %.1f MB, %.0fs"
        % (len(parts_table), builder.mesh_count, reused,
           builder.unique_triangles / 1e6, size_mb, time.time() - started))
    if baked:
        say("  %d parts failed the transform round-trip and were baked in world "
            "coordinates" % baked)
    say("wrote %s" % side_car)
    if failures:
        say("%d parts failed to mesh:" % len(failures))
        for name, err in failures[:20]:
            say("  %s: %s" % (name, err))
    return 0


def _entry():
    """Entry point, called unconditionally.

    There is no `__name__ == "__main__"` guard because freecadcmd would defeat
    it: it execs the script with `__name__` set to the file stem ("export_glb"),
    so a guarded main never runs and the process exits silently with nothing but
    the FreeCAD banner.

    Options arrive in the environment rather than on argv, because freecadcmd
    treats every token after the script name as another document to open and
    dies on anything that is not CAD. export.sh is the front door that turns a
    normal command line into EXPORT_GLB_ARGS.
    """
    raw = os.environ.get("EXPORT_GLB_ARGS")
    if raw:
        import shlex
        argv = shlex.split(raw)
    else:
        argv = sys.argv[1:]
    sys.exit(main(argv))


_entry()
