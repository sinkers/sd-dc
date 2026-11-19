"""Build a site fly-over in Blender from a model-review GLB and a shot list.

Run through build_flythrough.sh. Directly:

    blender -b --factory-startup -P flythrough.py -- \
        --work <dir with model.glb, model.parts.json, scene.json> \
        --config <site config .json> [--quality draft|final] \
        [--engine eevee|cycles] [--stills] [--render] [--frames 1-120]

It always saves <work>/flythrough.blend, so the scene can be opened, scrubbed
and tweaked by hand. --stills renders one frame from the middle of every shot
to <work>/stills/ (the quick check). --render renders the whole animation to
<work>/frames/ as numbered PNGs; build_flythrough.sh then encodes the MP4.

How it hangs together
---------------------
Every part in the GLB keeps its FreeCAD name in its glTF extras, and
model.parts.json maps that name to the FreeCAD tree path. The config's
`collections` rules turn tree paths and labels into named collections (hall
roof, office level 2, gensets ...). Each collection hangs off one empty, a
"rig", so a roof lift or a drop into place is one animated empty plus a
visibility key on each part. Shots address the model through anchors - the
bounding box of some collections, measured in the layout's own frame - so a
camera position reads as "30% along the hall, 1.7 m above the pad" and survives
the design moving.

Each shot gets its own camera, bound by a timeline marker. Cuts are clean and
no camera's easing is bent by the shot after it.

Written against Blender 5.2 and kept working on 4.2+: the API differences that
matter (EEVEE's engine id, the sky model enum, video output, slotted actions)
are each tried both ways.
"""

import json
import math
import os
import re
import sys
import time
from collections import Counter

import bpy
import bmesh
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree


def say(msg):
    sys.stdout.write("[flythrough] %s\n" % msg)
    sys.stdout.flush()


# ---------------------------------------------------------------- arguments

def parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    import argparse
    ap = argparse.ArgumentParser(prog="flythrough.py")
    ap.add_argument("--work", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--quality", choices=["draft", "final"], default="draft")
    ap.add_argument("--engine", choices=["eevee", "cycles"], default="eevee")
    ap.add_argument("--stills", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--frames", default="", help="render only this range, e.g. 1-240")
    return ap.parse_args(argv)


# ---------------------------------------------------------------- small helpers

def set_first(obj, attr, candidates):
    """Set obj.attr to the first candidate the running Blender accepts."""
    for value in candidates:
        try:
            setattr(obj, attr, value)
            return value
        except (TypeError, ValueError, AttributeError):
            continue
    return None


class Frame:
    """The layout's local frame: origin and yaw, in recentred world metres."""

    def __init__(self, origin, yaw_deg):
        self.origin = Vector((origin[0], origin[1]))
        self.yaw = math.radians(yaw_deg)
        self.c, self.s = math.cos(self.yaw), math.sin(self.yaw)

    def to_local(self, p):
        d = Vector((p[0], p[1])) - self.origin
        return Vector((self.c * d.x + self.s * d.y, -self.s * d.x + self.c * d.y))

    def to_world(self, u, v, z):
        return Vector((self.origin.x + self.c * u - self.s * v,
                       self.origin.y + self.s * u + self.c * v, z))


def point_in_polygon(x, y, poly):
    inside = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            inside = not inside
        j = i
    return inside


def dist_to_polygon(x, y, poly):
    best = 1e18
    for i in range(len(poly)):
        ax, ay = poly[i]
        bx, by = poly[(i + 1) % len(poly)]
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy + 1e-12)))
        px, py = ax + t * dx, ay + t * dy
        best = min(best, math.hypot(x - px, y - py))
    return best


def srgb_to_linear(c):
    return [x / 12.92 if x <= 0.04045 else ((x + 0.055) / 1.055) ** 2.4 for x in c[:3]]


def material(name, colour, alpha=1.0, roughness=0.6, metallic=0.0, emission=None):
    """Config colours are sRGB, as picked in any colour picker."""
    colour = srgb_to_linear(colour)
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    bsdf.inputs["Base Color"].default_value = (colour[0], colour[1], colour[2], 1.0)
    bsdf.inputs["Roughness"].default_value = roughness
    bsdf.inputs["Metallic"].default_value = metallic
    bsdf.inputs["Alpha"].default_value = alpha
    if alpha < 1.0:
        set_first(mat, "surface_render_method", ["BLENDED"])   # 4.2+
        set_first(mat, "blend_method", ["BLEND"])               # older EEVEE
    if emission:
        for key in ("Emission Color", "Emission"):
            if key in bsdf.inputs:
                bsdf.inputs[key].default_value = (*emission, 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 2.0
    return mat


# ---------------------------------------------------------------- scene build

def reset_scene():
    bpy.ops.wm.read_factory_settings(use_empty=True)
    scene = bpy.context.scene
    scene.unit_settings.system = "METRIC"
    return scene


def import_model(work, config=None):
    """The main GLB, then any extra_models. An extra model's part table may name
    the main parts it `replaces` (a linked component exported part by part):
    those are dropped so the pieces stand in for them."""
    parts = import_glb(os.path.join(work, "model.glb"))
    for extra in (config or {}).get("extra_models", []):
        with open(os.path.join(work, extra["parts"])) as fh:
            replaces = set(json.load(fh).get("replaces", []))
        if replaces:
            keep = []
            for obj in parts:
                if (obj.get("name") or obj.name) in replaces:
                    bpy.data.objects.remove(obj, do_unlink=True)
                else:
                    keep.append(obj)
            say("dropped %d parts replaced by %s" % (len(parts) - len(keep), extra["glb"]))
            parts = keep
        parts += import_glb(os.path.join(work, extra["glb"]))
    return parts


def import_glb(glb):
    say("importing %s (%.1f MB)" % (glb, os.path.getsize(glb) / 1e6))
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=glb)
    imported = [o for o in bpy.data.objects if o not in before]

    # Flatten the hierarchy, keeping world transforms. The GLB hangs every part
    # off one root carrying the mm->m scale and the Y-up rotation.
    for obj in imported:
        if obj.parent is not None:
            mw = obj.matrix_world.copy()
            obj.parent = None
            obj.matrix_world = mw
    parts = [o for o in imported if o.type == "MESH"]
    for obj in [o for o in imported if o.type == "EMPTY"]:
        bpy.data.objects.remove(obj, do_unlink=True)
    say("imported %d parts" % len(parts))
    return parts


def part_paths(work, config=None):
    tables = ["model.parts.json"] + [e["parts"] for e in (config or {}).get("extra_models", [])]
    paths = {}
    for t in tables:
        with open(os.path.join(work, t)) as fh:
            for row in json.load(fh)["part_table"]:
                paths[row["name"]] = (row["label"], row.get("path") or [])
    return paths


# ---------------------------------------------------------------- plan

def load_plan(config, work, config_path):
    """A construction-sequence plan (plan-<mode>.json) drives the build shot.

    "plan": {"file": "plan-ground_up.json", "stage_by": "layer" | "task",
             "captions": {"<layer or task id>": "on-screen text"},
             "skip": ["<id>", ...]}

    Every part the plan builds goes to the collection "plan_<id>" of its layer
    (or task), unless an explicit collection rule claims it first. Parts the
    plan does not build (existing, context) stay on screen throughout. A build
    shot with "stages": "plan" then drops the stages in the plan's order."""
    spec = config.get("plan")
    if not spec:
        return None
    path = spec["file"]
    if not os.path.isabs(path):
        for base in (work, os.path.dirname(os.path.abspath(config_path))):
            if os.path.exists(os.path.join(base, path)):
                path = os.path.join(base, path)
                break
    with open(path) as fh:
        plan = json.load(fh)
    by = spec.get("stage_by", "layer")
    task_layer = {t["id"]: t["layer"] for t in plan["tasks"]}
    if by == "layer":
        order = [l["id"] for l in plan["layers"]]
        names = {l["id"]: l["name"] for l in plan["layers"]}
    else:
        tasks = sorted(plan["tasks"], key=lambda t: (t["start"], t["finish"]))
        order = [t["id"] for t in tasks]
        names = {t["id"]: t["name"] for t in tasks}
    part_stage = {}
    for name, entry in plan["parts"].items():
        tid = entry.get("build")
        if tid in task_layer:            # "existing" and the like stand throughout
            part_stage[name] = task_layer[tid] if by == "layer" else tid
    say("plan %s (%s): %d parts over %d %ss" % (os.path.basename(path), plan.get("mode", "?"),
                                              len(part_stage), len(order), by))
    return {"order": order, "names": names, "part_stage": part_stage,
            "captions": spec.get("captions", {}), "skip": set(spec.get("skip", [])),
            "coll_stage": {}}


def plan_stages(plan, rigs):
    """Build-shot stages in plan order, each with its caption."""
    stages = []
    for sid in plan["order"]:
        if sid in plan["skip"]:
            continue
        colls = ["plan_" + sid] if ("plan_" + sid) in rigs else []
        colls += sorted(c for c, s in plan["coll_stage"].items() if s == sid)
        if colls:
            stages.append({"collections": colls,
                           "caption": plan["captions"].get(sid, plan["names"][sid])})
    return stages


def world_bbox(obj):
    pts = [obj.matrix_world @ Vector(c) for c in obj.bound_box]
    return (min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts),
            max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts))


def classify(parts, paths, config, plan=None):
    """Put every part in exactly one collection, by the config's ordered rules."""
    rules = config.get("collections", [])
    compiled = []
    for rule in rules:
        compiled.append((rule["name"], set(rule.get("paths", [])),
                         re.compile(rule["label_regex"]) if rule.get("label_regex") else None))
    exclude = set(config.get("exclude_paths", []))
    flat_limit = float(config.get("drop_flat_below_m", 0.002))

    groups, dropped_flat, dropped_excluded = {}, 0, 0
    votes = {}          # explicit collection -> plan stages of its parts
    for obj in parts:
        name = obj.get("name") or obj.name
        label, path = paths.get(name, (obj.get("label") or obj.name, []))
        obj["label"] = label
        if exclude.intersection(path):
            bpy.data.objects.remove(obj, do_unlink=True)
            dropped_excluded += 1
            continue
        bb = world_bbox(obj)
        if bb[5] - bb[2] < flat_limit:
            # 2D linework the layout carries for the plan view: no use in 3D,
            # and it z-fights with the slabs.
            bpy.data.objects.remove(obj, do_unlink=True)
            dropped_flat += 1
            continue
        target = None
        for cname, cpaths, regex in compiled:
            if (cpaths and cpaths.intersection(path)) or (regex and regex.search(label)):
                target = cname
                break
        stage = plan["part_stage"].get(name) if plan else None
        if target is None:
            target = ("plan_" + stage) if stage else config.get("default_collection", "other")
        elif stage:
            votes.setdefault(target, Counter())[stage] += 1
        groups.setdefault(target, []).append(obj)
    if plan:
        # An explicit collection (a roof that a later shot lifts) arrives with
        # the plan stage that builds most of it.
        for cname, c in votes.items():
            plan["coll_stage"][cname] = c.most_common(1)[0][0]
    say("classified %d parts into %d collections (%d flat and %d excluded dropped)"
        % (sum(len(v) for v in groups.values()), len(groups), dropped_flat, dropped_excluded))
    for cname in sorted(groups):
        say("  %-16s %4d parts" % (cname, len(groups[cname])))
    return groups


def build_rigs(groups):
    """One collection and one rig empty per group; parts parent to the rig."""
    rigs = {}
    for cname, objs in groups.items():
        coll = bpy.data.collections.new(cname)
        bpy.context.scene.collection.children.link(coll)
        rig = bpy.data.objects.new("RIG_" + cname, None)
        rig.empty_display_size = 2.0
        coll.objects.link(rig)
        for obj in objs:
            for c in list(obj.users_collection):
                c.objects.unlink(obj)
            coll.objects.link(obj)
            obj.parent = rig          # rig is identity, so world is unchanged
        rigs[cname] = rig
    return rigs


def linearise_imported_colours(parts):
    """FreeCAD colours are sRGB, but the GLB writer puts them in baseColorFactor,
    which glTF defines as linear. Read as linear they render washed out, so
    convert them back once."""
    done = set()
    for obj in parts:
        for mat in obj.data.materials:
            if mat is None or mat.name in done or not mat.node_tree:
                continue
            done.add(mat.name)
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf is None:
                continue
            c = bsdf.inputs["Base Color"].default_value
            lin = srgb_to_linear(c)
            bsdf.inputs["Base Color"].default_value = (*lin, c[3])
            bsdf.inputs["Roughness"].default_value = 0.7


def apply_material_overrides(groups, config):
    rules = config.get("materials", [])
    if not rules:
        return
    made = {}
    for objs in groups.values():
        for obj in objs:
            label = obj.get("label", obj.name)
            for i, rule in enumerate(rules):
                if re.search(rule["match"], label):
                    if i not in made:
                        made[i] = material("OVR_%d_%s" % (i, rule["match"][:20]),
                                           rule.get("color", [0.7, 0.7, 0.7]),
                                           alpha=rule.get("alpha", 1.0),
                                           roughness=rule.get("roughness", 0.6),
                                           metallic=rule.get("metallic", 0.0),
                                           emission=rule.get("emission"))
                    obj.data.materials.clear()
                    obj.data.materials.append(made[i])
                    break


# ---------------------------------------------------------------- ground

def load_terrain(work, entry, offset):
    with open(os.path.join(work, entry["file"])) as fh:
        t = json.load(fh)
    verts = [Vector((p[0] / 1000.0, p[1] / 1000.0, p[2] / 1000.0)) - offset for p in t["points"]]
    return BVHTree.FromPolygons(verts, t["facets"]), verts


def build_ground(work, scene_info, config, offset, pad_poly):
    """One textured ground mesh over the aerial's extent, draped on the TIN.

    Inside the TIN it takes the surveyed level; outside it takes the level of the
    nearest TIN point, so the edge of the survey does not show as a cliff. Inside
    the pad outline it is cut flat to the pad, blending back to the terrain over
    `margin_m`, so the buildings sit on a platform rather than in the hill.
    """
    ground = config.get("ground", {})
    trees = [load_terrain(work, e, offset) for e in scene_info["terrain"]]
    aerial = scene_info["aerials"][0] if scene_info["aerials"] else None

    if aerial:
        w, h = aerial["size_mm"][0] / 1000.0, aerial["size_mm"][1] / 1000.0
        c = Vector(aerial["centre_mm"]) / 1000.0 - offset
        yaw = math.radians(aerial["yaw_deg"])
    else:
        xs = [v.x for _, vs in trees for v in vs] or [-500, 500]
        ys = [v.y for _, vs in trees for v in vs] or [-500, 500]
        w, h = max(xs) - min(xs), max(ys) - min(ys)
        c, yaw = Vector(((max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2, 0)), 0.0

    n = int(ground.get("grid", 240))
    nx, ny = n, max(2, int(n * h / w))
    pad = ground.get("pad", {})
    margin = float(pad.get("margin_m", 6.0))
    pad_z = -float(pad.get("cut_m", 0.25))
    zs = [v.z for _, vs in trees for v in vs]
    mean_z = sum(zs) / len(zs) if zs else 0.0

    bm = bmesh.new()
    uv_layer = bm.loops.layers.uv.new("aerial")
    grid = []
    cy, sy = math.cos(yaw), math.sin(yaw)
    for j in range(ny + 1):
        row = []
        for i in range(nx + 1):
            lx, ly = (i / nx - 0.5) * w, (j / ny - 0.5) * h
            x, y = c.x + cy * lx - sy * ly, c.y + sy * lx + cy * ly
            z = None
            for tree, _ in trees:
                hit = tree.ray_cast(Vector((x, y, 5000.0)), Vector((0, 0, -1)))
                if hit[0] is not None:
                    z = hit[0].z
                    break
            if z is None and trees:
                near = [t.find_nearest(Vector((x, y, mean_z))) for t, _ in trees]
                near = [p for p in near if p[0] is not None]
                z = min(near, key=lambda p: p[3])[0].z if near else 0.0
            if z is None:
                z = 0.0
            if pad_poly:
                if point_in_polygon(x, y, pad_poly):
                    z = pad_z
                else:
                    d = dist_to_polygon(x, y, pad_poly)
                    if d < margin:
                        k = d / margin
                        k = k * k * (3 - 2 * k)           # smoothstep batter
                        z = pad_z + (z - pad_z) * k
            row.append((bm.verts.new((x, y, z)), (i / nx, j / ny)))
        grid.append(row)
    for j in range(ny):
        for i in range(nx):
            quad = [grid[j][i], grid[j][i + 1], grid[j + 1][i + 1], grid[j + 1][i]]
            face = bm.faces.new([q[0] for q in quad])
            for loop, q in zip(face.loops, quad):
                loop[uv_layer].uv = q[1]
    mesh = bpy.data.meshes.new("Ground")
    bm.to_mesh(mesh)
    bm.free()
    for poly in mesh.polygons:
        poly.use_smooth = True
    obj = bpy.data.objects.new("Ground", mesh)
    bpy.context.scene.collection.objects.link(obj)

    mat = bpy.data.materials.new("Ground")
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    bsdf = nodes.get("Principled BSDF")
    bsdf.inputs["Roughness"].default_value = 0.95
    if aerial and aerial["exists"]:
        tex = nodes.new("ShaderNodeTexImage")
        tex.image = bpy.data.images.load(aerial["image"])
        tex.extension = "EXTEND"
        uv = nodes.new("ShaderNodeUVMap")
        uv.uv_map = "aerial"
        links.new(uv.outputs["UV"], tex.inputs["Vector"])
        links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
    else:
        bsdf.inputs["Base Color"].default_value = (0.42, 0.36, 0.25, 1)
    mesh.materials.append(mat)
    say("ground %dx%d over %.0f x %.0f m, %d terrain source(s)%s"
        % (nx, ny, w, h, len(trees), ", pad cut" if pad_poly else ""))

    if pad_poly and pad.get("hardstand", True):
        hb = bmesh.new()
        # Hardstand sits clearly below the slabs (top of slab = 0) and clearly
        # above the cut ground, so neither pair z-fights from a distance.
        top = [hb.verts.new((x, y, -float(pad.get("hardstand_below_m", 0.1)))) for x, y in pad_poly]
        hb.faces.new(top)
        hm = bpy.data.meshes.new("Hardstand")
        hb.to_mesh(hm)
        hb.free()
        ho = bpy.data.objects.new("Hardstand", hm)
        bpy.context.scene.collection.objects.link(ho)
        hm.materials.append(material("Hardstand", pad.get("color", [0.46, 0.45, 0.42]),
                                     roughness=0.9))
    return obj


# ---------------------------------------------------------------- world, light, render

def build_world(config):
    look = config.get("look", {})
    world = bpy.data.worlds.new("World")
    bpy.context.scene.world = world
    world.use_nodes = True
    nodes, links = world.node_tree.nodes, world.node_tree.links
    bg = nodes.get("Background")
    elev = math.radians(look.get("sun_elevation_deg", 38))
    azim = math.radians(look.get("sun_azimuth_deg", 30))
    try:
        sky = nodes.new("ShaderNodeTexSky")
        set_first(sky, "sky_type", ["MULTIPLE_SCATTERING", "NISHITA", "SINGLE_SCATTERING",
                                    "PREETHAM"])
        set_first(sky, "sun_elevation", [elev])
        set_first(sky, "sun_rotation", [azim])
        set_first(sky, "sun_disc", [False])
        links.new(sky.outputs["Color"], bg.inputs["Color"])
        bg.inputs["Strength"].default_value = look.get("sky_strength", 0.35)
    except Exception as exc:  # no sky node: a plain blue-grey is fine
        say("sky texture unavailable (%s); using a flat sky" % exc)
        bg.inputs["Color"].default_value = (0.55, 0.68, 0.85, 1)
        bg.inputs["Strength"].default_value = 1.0

    sun_data = bpy.data.lights.new("Sun", "SUN")
    sun_data.energy = look.get("sun_strength", 3.5)
    sun_data.angle = math.radians(1.5)
    sun = bpy.data.objects.new("Sun", sun_data)
    bpy.context.scene.collection.objects.link(sun)
    # A sun light points down its -Z; aim it from (azimuth, elevation).
    sun.rotation_euler = (math.pi / 2 - elev, 0.0, azim + math.pi / 2)


def configure_render(scene, args, config):
    q = config.get(args.quality, {})
    scene.render.fps = int(q.get("fps", 24 if args.quality == "draft" else 30))
    res = q.get("resolution", [1280, 720] if args.quality == "draft" else [1920, 1080])
    scene.render.resolution_x, scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    if args.engine == "cycles":
        scene.render.engine = "CYCLES"
        try:
            prefs = bpy.context.preferences.addons["cycles"].preferences
            set_first(prefs, "compute_device_type", ["METAL", "OPTIX", "CUDA", "HIP"])
            prefs.get_devices()
            for dev in prefs.devices:
                dev.use = True
            scene.cycles.device = "GPU"
        except Exception as exc:
            say("cycles GPU setup skipped: %s" % exc)
        scene.cycles.samples = int(q.get("samples", 32 if args.quality == "draft" else 160))
        scene.cycles.use_denoising = True
    else:
        engine = set_first(scene.render, "engine", ["BLENDER_EEVEE", "BLENDER_EEVEE_NEXT"])
        say("render engine %s" % engine)
        ee = scene.eevee
        set_first(ee, "taa_render_samples", [int(q.get("samples", 16 if args.quality == "draft" else 64))])
        set_first(ee, "use_raytracing", [args.quality == "final"])
        set_first(ee, "use_shadows", [True])
    set_first(scene.view_settings, "view_transform", ["AgX", "Filmic"])
    set_first(scene.view_settings, "look", ["AgX - Medium High Contrast", "None"])
    scene.view_settings.exposure = float(config.get("look", {}).get("exposure", 0.0))
    scene.render.film_transparent = False
    scene.render.image_settings.file_format = "PNG"


# ---------------------------------------------------------------- anchors

class Anchors:
    def __init__(self, frame, rigs, config):
        self.frame = frame
        self.boxes = {}
        spec = config.get("anchors", {})
        for name, a in spec.items():
            colls = a.get("collections", ["*"])
            objs = [o for c, rig in rigs.items() if colls == ["*"] or c in colls
                    for o in rig.children]
            if not objs:
                say("WARNING anchor %s has no parts" % name)
                continue
            us, vs, zs = [], [], []
            for obj in objs:
                for corner in obj.bound_box:
                    p = obj.matrix_world @ Vector(corner)
                    l = frame.to_local(p)
                    us.append(l.x)
                    vs.append(l.y)
                    zs.append(p.z)
            self.boxes[name] = (min(us), min(vs), min(zs), max(us), max(vs), max(zs))
            b = self.boxes[name]
            say("anchor %-8s %.0f x %.0f x %.1f m" % (name, b[3] - b[0], b[4] - b[1], b[5] - b[2]))

    def point(self, spec):
        """{"anchor","u","v","h"} -> world point. u, v are fractions of the anchor's
        box in the layout frame; h is metres above the pad. dx, dy are metres."""
        if isinstance(spec, (list, tuple)):
            return Vector(spec)
        b = self.boxes[spec.get("anchor", "site")]
        u = b[0] + spec.get("u", 0.5) * (b[3] - b[0]) + spec.get("dx", 0.0)
        v = b[1] + spec.get("v", 0.5) * (b[4] - b[1]) + spec.get("dy", 0.0)
        return self.frame.to_world(u, v, spec.get("h", 0.0))


# ---------------------------------------------------------------- animation

def keyed(interp):
    """Context manager: new keyframes use this interpolation (no fcurve API needed,
    which Blender 5 moved behind slotted actions)."""
    class _K:
        def __enter__(self):
            self.prefs = bpy.context.preferences.edit
            self.old = self.prefs.keyframe_new_interpolation_type
            self.prefs.keyframe_new_interpolation_type = interp

        def __exit__(self, *exc):
            self.prefs.keyframe_new_interpolation_type = self.old
    return _K()


class RigTimeline:
    """Keys each rig's height and its parts' visibility, in time order."""

    def __init__(self, rigs):
        self.rigs = rigs
        self.state = {name: [0.0, True] for name in rigs}
        for name in rigs:
            self.key(name, 1)

    def key(self, name, frame, z=None, visible=None):
        st = self.state[name]
        if z is not None:
            st[0] = z
        if visible is not None:
            st[1] = visible
        rig = self.rigs[name]
        rig.location.z = st[0]
        with keyed("BEZIER"):
            rig.keyframe_insert("location", index=2, frame=frame)
        with keyed("CONSTANT"):
            for obj in rig.children:
                obj.hide_render = not st[1]
                obj.hide_viewport = not st[1]
                obj.keyframe_insert("hide_render", frame=frame)
                obj.keyframe_insert("hide_viewport", frame=frame)

    def lift(self, name, f0, f1, dz, hide_after):
        z = self.state[name][0]
        self.key(name, f0)
        self.key(name, f1, z=z + dz)
        if hide_after:
            self.key(name, f1 + 1, visible=False)

    def drop(self, name, f0, f1, height):
        self.key(name, f0 - 1, z=height, visible=False)
        self.key(name, f0, visible=True)
        self.key(name, f1, z=0.0)


def make_camera(name, lens, clip_start=0.5):
    # Depth precision goes with clip_end / clip_start. 0.1 m near a 6 km far plane
    # z-fights slabs and hardstand a few centimetres apart in the aerial shots,
    # so only walk-throughs bring the near plane in.
    cam_data = bpy.data.cameras.new(name)
    cam_data.lens = lens
    cam_data.clip_start = clip_start
    cam_data.clip_end = 6000.0
    cam = bpy.data.objects.new(name, cam_data)
    tgt = bpy.data.objects.new(name + "_target", None)
    tgt.empty_display_size = 1.0
    for o in (cam, tgt):
        bpy.context.scene.collection.objects.link(o)
    con = cam.constraints.new("TRACK_TO")
    con.target = tgt
    con.track_axis = "TRACK_NEGATIVE_Z"
    con.up_axis = "UP_Y"
    return cam, tgt


def key_camera(cam, tgt, frame, pos, look, lens=None):
    cam.location = pos
    tgt.location = look
    cam.keyframe_insert("location", frame=frame)
    tgt.keyframe_insert("location", frame=frame)
    if lens:
        cam.data.lens = lens
        cam.data.keyframe_insert("lens", frame=frame)


def build_shots(config, anchors, timeline, fps, plan=None, captions=None):
    """captions, if given, collects on-screen text as {text, start_s, end_s}:
    one per build stage that has a caption, and one per shot with "caption"."""
    scene = bpy.context.scene
    captions = captions if captions is not None else []
    frame = 1
    last = None            # (pos, look, lens) at the end of the previous shot
    shot_spans = []
    for shot in config["shots"]:
        n = max(1, int(round(shot["duration_s"] * fps)))
        f0, f1 = frame, frame + n - 1
        lens = shot.get("lens_mm", 35)
        cam, tgt = make_camera("CAM_" + shot["name"], lens, shot.get("clip_start_m", 0.5))
        marker = scene.timeline_markers.new(shot["name"], frame=f0)
        marker.camera = cam
        kind = shot.get("type", "path")

        if kind in ("orbit", "build"):
            centre = anchors.point(shot.get("target", {"anchor": "site"}))
            r, h = shot.get("radius_m", 200), shot.get("height_m", 90)
            a0, a1 = shot.get("from_deg", 220), shot.get("to_deg", 300)
            step = max(1, int(fps / 2))
            frames = list(range(f0, f1 + 1, step))
            if frames[-1] != f1:
                frames.append(f1)
            for f in frames:
                t = (f - f0) / max(1, f1 - f0)
                a = math.radians(a0 + (a1 - a0) * t)
                rel = Vector((r * math.cos(a), r * math.sin(a)))
                world_rel = Vector((anchors.frame.c * rel.x - anchors.frame.s * rel.y,
                                    anchors.frame.s * rel.x + anchors.frame.c * rel.y))
                pos = Vector((centre.x + world_rel.x, centre.y + world_rel.y, h))
                key_camera(cam, tgt, f, pos, centre, lens if f == f0 else None)
            last = (pos, centre, lens)
        else:
            keys = shot["keys"]
            if shot.get("continue") and last is not None:
                key_camera(cam, tgt, f0, last[0], last[1], last[2])
            for k in keys:
                f = f0 + int(round(k.get("t", 0.0) * fps))
                f = min(max(f, f0), f1)
                pos, look = anchors.point(k["cam"]), anchors.point(k["look"])
                key_camera(cam, tgt, f, pos, look, k.get("lens_mm", lens if f == f0 else None))
                last = (pos, look, k.get("lens_mm", lens))

        for ev in shot.get("events", []):
            fs = f0 + int(round(ev.get("at_s", 0.0) * fps))
            fe = fs + max(1, int(round(ev.get("dur_s", 1.0) * fps)))
            for name in ev.get("collections", []):
                if name not in timeline.rigs:
                    say("WARNING shot %s: no collection %s" % (shot["name"], name))
                    continue
                act = ev["action"]
                if act == "lift":
                    timeline.lift(name, fs, fe, ev.get("dz_m", 25.0), ev.get("hide_after", True))
                elif act == "hide":
                    timeline.key(name, fs, visible=False)
                elif act == "show":
                    timeline.key(name, fs, visible=True)
                elif act == "restore":
                    timeline.key(name, fs)
                    timeline.key(name, fe, z=0.0, visible=True)

        if shot.get("caption"):
            captions.append({"text": shot["caption"], "start_s": (f0 - 1) / fps,
                             "end_s": f1 / fps})
        if kind == "build":
            stages = shot["stages"]
            if stages == "plan":
                if not plan:
                    raise SystemExit("shot %s: stages \"plan\" needs a \"plan\" in the config"
                                     % shot["name"])
                stages = plan_stages(plan, timeline.rigs)
            height = shot.get("drop_m", 30.0)
            each = shot.get("each_s", 2.0)
            gap = shot.get("step_s", 1.2)
            start = f0 + int(round(shot.get("start_s", 1.0) * fps))
            staged = [c for st in stages for c in st["collections"] if c in timeline.rigs]
            for name in staged:                       # clear the site
                # hidden from the shot's first frame; a key on the frame before
                # keeps them standing through any earlier shot
                if f0 > 1:
                    timeline.key(name, f0 - 1)
                timeline.key(name, f0, z=height, visible=False)
            if shot.get("intro_caption"):
                captions.append({"text": shot["intro_caption"], "start_s": (f0 - 1) / fps,
                                 "end_s": (start - 1) / fps})
            for i, st in enumerate(stages):
                s0 = start + int(round(i * gap * fps))
                s1 = s0 + int(round(each * fps))
                if st.get("caption"):
                    nxt = start + int(round((i + 1) * gap * fps)) if i + 1 < len(stages) else f1 + 1
                    captions.append({"text": st["caption"], "start_s": (s0 - 1) / fps,
                                     "end_s": (min(nxt, f1 + 1) - 1) / fps})
                for name in st["collections"]:
                    if name in timeline.rigs:
                        timeline.drop(name, s0, min(s1, f1), height)
            say("build: %d stages over %.1f s" % (len(stages), (len(stages) - 1) * gap + each))

        shot_spans.append((shot["name"], f0, f1))
        say("shot %-12s frames %5d-%5d  (%.1f s)" % (shot["name"], f0, f1, n / fps))
        frame = f1 + 1

    scene.frame_start = 1
    scene.frame_end = frame - 1
    scene.camera = bpy.data.objects["CAM_" + config["shots"][0]["name"]]
    return shot_spans


# ---------------------------------------------------------------- main

def main():
    args = parse_args()
    started = time.time()
    with open(args.config) as fh:
        config = json.load(fh)
    with open(os.path.join(args.work, "scene.json")) as fh:
        scene_info = json.load(fh)

    scene = reset_scene()
    parts = import_model(args.work, config)
    plan = load_plan(config, args.work, args.config)
    groups = classify(parts, part_paths(args.work, config), config, plan)
    rigs = build_rigs(groups)
    linearise_imported_colours([o for objs in groups.values() for o in objs])
    apply_material_overrides(groups, config)

    # Recentre on the origin outline (else the frame base), at pad level.
    frame_info = scene_info["frames"].get(config.get("frame", ""), {"base_mm": [0, 0, 0],
                                                                    "yaw_deg": 0})
    pad_rl = frame_info["base_mm"][2] / 1000.0
    outline_label = config.get("origin", {}).get("outline")
    outline = scene_info["outlines"].get(outline_label) if outline_label else None
    if outline:
        pts = outline["points_mm"]
        cx = sum(p[0] for p in pts) / len(pts) / 1000.0
        cy = sum(p[1] for p in pts) / len(pts) / 1000.0
    else:
        cx, cy = frame_info["base_mm"][0] / 1000.0, frame_info["base_mm"][1] / 1000.0
    offset = Vector((cx, cy, pad_rl))
    # The rigs sit at the origin with identity transforms, so each part's own
    # transform is its world placement: shift the parts, not the rigs.
    for objs in groups.values():
        for obj in objs:
            obj.location = obj.location - offset
    say("recentred on (%.1f, %.1f) m, pad RL %.2f m" % (cx, cy, pad_rl))

    frame = Frame(((frame_info["base_mm"][0] / 1000.0) - cx,
                   (frame_info["base_mm"][1] / 1000.0) - cy), frame_info["yaw_deg"])

    pad_label = config.get("ground", {}).get("pad", {}).get("outline")
    pad_poly = None
    if pad_label and pad_label in scene_info["outlines"]:
        pad_poly = [(p[0] / 1000.0 - cx, p[1] / 1000.0 - cy)
                    for p in scene_info["outlines"][pad_label]["points_mm"]]
        if len(pad_poly) > 2 and pad_poly[0] == pad_poly[-1]:
            pad_poly = pad_poly[:-1]
    build_ground(args.work, scene_info, config, offset, pad_poly)
    build_world(config)
    configure_render(scene, args, config)

    bpy.context.view_layer.update()          # matrix_world after the recentre
    anchors = Anchors(frame, rigs, config)
    timeline = RigTimeline(rigs)
    captions = []
    spans = build_shots(config, anchors, timeline, scene.render.fps, plan, captions)
    with open(os.path.join(args.work, "captions.json"), "w") as fh:
        json.dump({"style": config.get("caption_style", {}), "items": captions}, fh, indent=1)
    if captions:
        say("%d captions -> captions.json (burnt in at encode)" % len(captions))

    blend = os.path.join(args.work, "flythrough.blend")
    bpy.ops.wm.save_as_mainfile(filepath=blend)
    info = {"fps": scene.render.fps, "frame_start": scene.frame_start,
            "frame_end": scene.frame_end, "shots": spans,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
            "engine": scene.render.engine, "quality": args.quality}
    with open(os.path.join(args.work, "render_info.json"), "w") as fh:
        json.dump(info, fh, indent=1)
    say("saved %s: %d frames, %.0f s at %d fps (built in %.0fs)"
        % (blend, scene.frame_end, scene.frame_end / scene.render.fps,
           scene.render.fps, time.time() - started))

    if args.stills:
        os.makedirs(os.path.join(args.work, "stills"), exist_ok=True)
        for name, f0, f1 in spans:
            f = (f0 + f1) // 2
            scene.frame_set(f)
            for m in scene.timeline_markers:   # bind the shot's camera for a still
                if m.name == name:
                    scene.camera = m.camera
            scene.render.filepath = os.path.join(args.work, "stills", "%s_%05d.png" % (name, f))
            bpy.ops.render.render(write_still=True)
            say("still %s frame %d" % (name, f))

    if args.render:
        if args.frames:
            a, b = args.frames.split("-")
            scene.frame_start, scene.frame_end = int(a), int(b)
        scene.render.filepath = os.path.join(args.work, "frames", "")
        scene.render.use_overwrite = False       # rerun to resume
        scene.render.use_placeholder = True
        say("rendering frames %d-%d" % (scene.frame_start, scene.frame_end))
        bpy.ops.render.render(animation=True)
        say("render done in %.0f min" % ((time.time() - started) / 60))


main()
