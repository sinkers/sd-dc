#!/usr/bin/env freecadcmd
"""Export what the GLB leaves behind: terrain, aerial image planes, frames and outlines.

Run through build_flythrough.sh, which is the front door. Options travel in the
FLYTHROUGH_ARGS environment variable as JSON, because freecadcmd treats every
token after the script name as another document to open (the same trap
model-review/export_glb.py documents).

    FLYTHROUGH_ARGS='{"fcstd": "...", "config": "...", "out": "..."}' \
        freecadcmd export_scene.py

`model-review/export_glb.py` meshes every visible solid into one GLB. Three
things a fly-over needs never make it into that file, because they are not
solids:

- terrain, held as a `Mesh::Feature` (a surveyed TIN)
- the aerial photograph, held as an `Image::ImagePlane`
- the placement of the layout's local frame, and any outline the camera or the
  ground pad needs (a fence line, a lease boundary)

This writes them to `scene.json` plus one `terrain_<label>.json` per mesh, all
in FreeCAD millimetres. The Blender side converts to metres and recentres.
No project data is baked in: every label comes from the site config.
"""

import json
import os
import sys
import time

import FreeCAD


def say(msg):
    sys.stdout.write("[export_scene] %s\n" % msg)
    sys.stdout.flush()


def by_label(doc, label):
    found = doc.getObjectsByLabel(label)
    return found[0] if found else None


def global_placement(obj):
    try:
        return obj.getGlobalPlacement()
    except Exception:  # older FreeCAD
        return obj.Placement


def yaw_deg(placement):
    # Yaw about Z only. Site layouts here are never pitched or rolled.
    return placement.Rotation.toEuler()[0]


def export_mesh(obj, out_dir):
    points, facets = obj.Mesh.Topology
    path = os.path.join(out_dir, "terrain_%s.json" % obj.Name)
    with open(path, "w") as fh:
        json.dump({
            "label": obj.Label,
            "units": "mm",
            "points": [[round(p.x, 1), round(p.y, 1), round(p.z, 1)] for p in points],
            "facets": [list(f) for f in facets],
        }, fh)
    bb = obj.Mesh.BoundBox
    say("terrain %s: %d points, %d facets -> %s" % (obj.Label, len(points), len(facets),
                                                     os.path.basename(path)))
    return {"label": obj.Label, "file": os.path.basename(path),
            "bbox_mm": [bb.XMin, bb.YMin, bb.ZMin, bb.XMax, bb.YMax, bb.ZMax]}


def export_image_plane(obj, fcstd_dir, out_dir):
    image = obj.ImageFile
    if image and not os.path.isabs(image):
        image = os.path.normpath(os.path.join(fcstd_dir, image))
    # FreeCAD embeds the image in the FCStd and points ImageFile at a copy in its
    # per-session cache, which is deleted when this process exits. Keep our own.
    if image and os.path.exists(image):
        import shutil
        kept = os.path.join(out_dir, "aerial_%s%s" % (obj.Name, os.path.splitext(image)[1]))
        shutil.copyfile(image, kept)
        image = kept
    pl = global_placement(obj)
    return {
        "label": obj.Label,
        "image": image,
        "exists": bool(image) and os.path.exists(image),
        "size_mm": [float(obj.XSize), float(obj.YSize)],
        # Image::ImagePlane is centred on its placement.
        "centre_mm": [pl.Base.x, pl.Base.y, pl.Base.z],
        "yaw_deg": yaw_deg(pl),
    }


def export_outline(obj):
    shape = obj.Shape
    wire = shape.Wires[0] if shape.Wires else None
    if wire is None:
        return None
    pts = [[round(v.X, 1), round(v.Y, 1), round(v.Z, 1)] for v in wire.OrderedVertexes]
    return {"label": obj.Label, "points_mm": pts, "closed": wire.isClosed()}


def main(args):
    started = time.time()
    with open(args["config"]) as fh:
        config = json.load(fh)
    out_dir = args["out"]
    os.makedirs(out_dir, exist_ok=True)

    doc = FreeCAD.openDocument(args["fcstd"])
    fcstd_dir = os.path.dirname(os.path.abspath(args["fcstd"]))
    say("opened %s: %d objects" % (os.path.basename(args["fcstd"]), len(doc.Objects)))

    ground = config.get("ground", {})
    scene = {"source": os.path.basename(args["fcstd"]),
             "exported": time.strftime("%Y-%m-%dT%H:%M:%S"),
             "units": "mm", "terrain": [], "aerials": [], "frames": {}, "outlines": {}}

    # Terrain: the labels the config names, else every mesh feature.
    labels = ground.get("terrain")
    meshes = ([by_label(doc, l) for l in labels] if labels
              else [o for o in doc.Objects if o.isDerivedFrom("Mesh::Feature")])
    for obj in meshes:
        if obj is None:
            continue
        scene["terrain"].append(export_mesh(obj, out_dir))

    # Aerial photographs.
    aerial = ground.get("aerial")
    planes = ([by_label(doc, aerial)] if aerial
              else [o for o in doc.Objects if o.TypeId == "Image::ImagePlane"])
    for obj in planes:
        if obj is None:
            continue
        entry = export_image_plane(obj, fcstd_dir, out_dir)
        scene["aerials"].append(entry)
        if not entry["exists"]:
            say("WARNING aerial image not found: %s" % entry["image"])

    # Local frames: the placement that gives u/v axes to the camera anchors.
    for label in set(filter(None, [config.get("frame")] + config.get("extra_frames", []))):
        obj = by_label(doc, label)
        if obj is None:
            say("WARNING frame %s not found" % label)
            continue
        pl = global_placement(obj)
        scene["frames"][label] = {"base_mm": [pl.Base.x, pl.Base.y, pl.Base.z],
                                  "yaw_deg": yaw_deg(pl)}

    # Outlines: the pad, the recentring origin, anything else the config names.
    wanted = set(config.get("outlines", []))
    for key in ("pad",):
        if ground.get(key, {}).get("outline"):
            wanted.add(ground[key]["outline"])
    if config.get("origin", {}).get("outline"):
        wanted.add(config["origin"]["outline"])
    for label in wanted:
        obj = by_label(doc, label)
        entry = export_outline(obj) if obj is not None else None
        if entry is None:
            say("WARNING outline %s not found or has no wire" % label)
            continue
        scene["outlines"][label] = entry

    path = os.path.join(out_dir, "scene.json")
    with open(path, "w") as fh:
        json.dump(scene, fh, indent=1)
    say("wrote %s in %.0fs (%d terrain, %d aerial, %d frames, %d outlines)"
        % (path, time.time() - started, len(scene["terrain"]), len(scene["aerials"]),
           len(scene["frames"]), len(scene["outlines"])))
    return 0


def _entry():
    raw = os.environ.get("FLYTHROUGH_ARGS")
    if not raw:
        say("FLYTHROUGH_ARGS is not set; run this through build_flythrough.sh")
        sys.exit(2)
    sys.exit(main(json.loads(raw)))


_entry()
