"""Read a FreeCAD document the way a headless exporter needs to see it.

Shared by export_glb.py and audit.py, and deliberately free of side effects:
freecadcmd runs a script with `__name__` set to the file stem, so a module that
does work at import time cannot be imported by a sibling script without running
that work again.

The awkward part is that headless FreeCAD has no `ViewObject`, so visibility and
colour - the two things that decide what a reviewer should see - are not
reachable through the document API. Both are parsed out of the FCStd zip
directly: `GuiDocument.xml` for the per-object view providers, and the
`ShapeAppearance*` blobs it points at for the materials.
"""

import struct
import xml.etree.ElementTree as ET
import zipfile
from math import radians

import FreeCAD
import MeshPart

DEFAULT_COLOUR = (0.8, 0.8, 0.9, 1.0)


def say(message):
    """Print and flush.

    Not optional: freecadcmd tears the process down without flushing stdio, so
    anything still sitting in the buffer when the script exits is lost - which
    looks exactly like a silent crash mid-export.
    """
    print(message, flush=True)


def unpack_colour(raw):
    """FreeCAD packs a colour as a little-endian uint32 holding 0xRRGGBBAA."""
    value = struct.unpack("<I", raw)[0]
    return (((value >> 24) & 0xFF) / 255.0, ((value >> 16) & 0xFF) / 255.0,
            ((value >> 8) & 0xFF) / 255.0, (value & 0xFF) / 255.0)


def read_material(blob):
    """Pull (diffuse RGBA, transparency) out of a ShapeAppearance MaterialList."""
    if len(blob) < 28:
        return DEFAULT_COLOUR, 0.0
    count = struct.unpack("<I", blob[0:4])[0]
    if count < 1:
        return DEFAULT_COLOUR, 0.0
    # Per material: ambient, diffuse, specular, emissive, then shininess and
    # transparency as floats. We only need the diffuse colour and transparency.
    diffuse = unpack_colour(blob[8:12])
    transparency = struct.unpack("<f", blob[24:28])[0]
    return diffuse, transparency


def read_gui_state(fcstd):
    """Return {object name: (visible, rgba)} from the FCStd's GUI document."""
    state = {}
    with zipfile.ZipFile(fcstd) as z:
        root = ET.fromstring(z.read("GuiDocument.xml"))
        wanted = {}
        for vp in root.iter("ViewProvider"):
            name = vp.get("name")
            visible, material_file, transparency = True, None, None
            for prop in vp.iter("Property"):
                child = next(iter(prop), None)
                if child is None:
                    continue
                if prop.get("name") == "Visibility":
                    visible = child.get("value") == "true"
                elif prop.get("name") == "ShapeAppearance":
                    material_file = child.get("file")
                elif prop.get("name") == "Transparency":
                    transparency = int(child.get("value") or 0)
            wanted[name] = (visible, material_file, transparency)

        for name, (visible, material_file, transparency) in wanted.items():
            colour = DEFAULT_COLOUR
            if material_file:
                try:
                    colour, alpha_from_material = read_material(z.read(material_file))
                except KeyError:
                    alpha_from_material = 0.0
                # Transparency lives in two places and the integer property wins,
                # because that is the one the FreeCAD UI writes.
                if transparency:
                    alpha_from_material = transparency / 100.0
                if alpha_from_material:
                    colour = colour[:3] + (max(0.05, 1.0 - alpha_from_material),)
            state[name] = (visible, colour)
    return state


def parent_map(doc):
    """Map object name -> the container that holds it."""
    parent = {}
    for obj in doc.Objects:
        for child in getattr(obj, "Group", []) or []:
            parent[child.Name] = obj
    return parent


def ancestor_placement(obj, parents):
    """Product of the enclosing containers' placements, outermost applied last.

    This is the transform an object inherits from the containers it sits in, and
    leaving it out is what put every machine off its plinth. AU01 positions plant
    by wrapping it in an `App::Part` per unit - "GEN 4 UNIT" carries
    (0, -300, +750) - so the geometry's own placement puts it on the ground beside
    the pad and the container lifts it onto the pad and centres it. Skip this and
    all eight gensets and PTUs sink 750 mm into their plinths, four of them
    sliding 0.8-2.1 m sideways as well.

    `getGlobalPlacement()` computes the same thing and is the obvious answer, but
    `App::Link` does not implement it - and links are exactly how the PTUs,
    transformers, pump banks and rack runs are placed - so the chain is walked
    here instead. Containers without a Placement (`App::DocumentObjectGroup`)
    contribute nothing and are skipped.
    """
    chain, node, guard = [], parents.get(obj.Name), 0
    while node is not None and guard < 32:
        placement = getattr(node, "Placement", None)
        if placement is not None:
            chain.append(placement)
        node = parents.get(node.Name)
        guard += 1

    total = FreeCAD.Placement()
    for placement in reversed(chain):
        total = placement.multiply(total)
    return total


def tree_paths(doc):
    """Map object name -> list of enclosing group/part labels, outermost first."""
    parent = {name: obj for name, obj in parent_map(doc).items()
              if obj.isDerivedFrom("App::DocumentObjectGroup")
              or obj.isDerivedFrom("App::Part")}

    paths = {}
    for obj in doc.Objects:
        path, node, guard = [], parent.get(obj.Name), 0
        while node is not None and guard < 32:
            path.append(node.Label)
            node = parent.get(node.Name)
            guard += 1
        paths[obj.Name] = list(reversed(path))
    return paths


def apply_container_visibility(doc, state):
    """Hide everything inside a hidden group, the way FreeCAD's 3D view does.

    This is the difference between "visible" and "shown". FreeCAD hides a whole
    subtree by hiding its container and leaves the children's own Visibility flag
    untouched, so reading per-object visibility alone reports parts as visible
    that nobody can see in FreeCAD.

    On the AU01 model that was not a detail: DAME keeps a component library in
    the file - `CMP_Delta_IT_Run`, `CMP_MPD_Dry_Cooler`, `CMP_Minera_TX`,
    `CMP_Schneider_PTU_3D`, `CMP_Grundfos_CR95`, `CMP_Fence_Panel_2400x2100` and
    the `AU01 layout - 1 phase` working assembly - each parked on the origin with
    its container hidden. All seven read as hidden containers full of visible
    children, so the first export dropped 3,440 parts of library geometry into
    the middle of the building: a second IT pod in the west half, a dry cooler
    floating over the PTUs, and manifold pipework running 14.7 m below grade.

    Note the asymmetry, which is why this belongs here and not in the model: an
    `App::Link` renders its target's geometry even when the target's *container*
    is hidden - that is how the placed dry coolers and PTUs appear on site while
    their masters do not - but it renders nothing if the target's *leaves* are
    hidden. So the fix is to skip the leaves at export time. Hiding them in the
    document instead breaks 13 of the 15 placed instances.
    """
    hidden_containers = [obj for obj in doc.Objects
                         if "Group" in obj.PropertiesList
                         and not state.get(obj.Name, (True, None))[0]]

    suppressed = 0
    for container in hidden_containers:
        stack = list(getattr(container, "Group", []) or [])
        seen = set()
        while stack:
            child = stack.pop()
            if child.Name in seen:
                continue
            seen.add(child.Name)
            stack.extend(getattr(child, "Group", []) or [])
            visible, colour = state.get(child.Name, (True, DEFAULT_COLOUR))
            if visible:
                state[child.Name] = (False, colour)
                suppressed += 1
    return len(hidden_containers), suppressed


def facets(shape, linear, angular):
    """Mesh a shape and return flat (positions, normals), 9 floats per facet."""
    mesh = MeshPart.meshFromShape(Shape=shape, LinearDeflection=linear,
                                  AngularDeflection=radians(angular), Relative=False)
    positions, normals = [], []
    for facet in mesh.Facets:
        p = facet.Points
        n = facet.Normal
        for vertex in p:
            positions.extend((vertex[0], vertex[1], vertex[2]))
            normals.extend((n.x, n.y, n.z))
    return positions, normals


IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)


def world_shape(obj, ancestors):
    """The object's geometry where FreeCAD actually draws it."""
    shape = obj.Shape.copy()
    shape.Placement = ancestors.multiply(obj.Shape.Placement)
    return shape


def instance_key(obj, ancestors=None):
    """Split an object into (signature, local shape, translation, rotation).

    Two objects sharing a signature are the same geometry in a different place,
    so the mesh can be built once and instanced. Getting this wrong silently puts
    copies in the wrong place, so three things guard it.

    First, the transform is the *world* one: the containers' placements composed
    with the object's own, via `ancestor_placement`. AU01 places plant by wrapping
    each unit in an `App::Part` that carries the offset onto its plinth, so an
    object's own placement alone leaves it beside the pad rather than on it.

    Second, that own placement comes from `Shape.Placement`, never
    `obj.Placement`. For an `App::Link` the two differ - `obj.Shape` already has
    the link resolved into it while `obj.Placement` still holds the link's
    transform - and applying the latter put both dry coolers 38 m west of site.
    `local + Shape.Placement == Shape` holds by construction for every type.

    Third, the result is checked rather than assumed: the local shape is put back
    through the transform and its centre of mass compared with the world shape's.
    Anything that does not land where it should is exported in world coordinates
    with no transform and no instancing - bigger and slower for that part, never
    in the wrong place.

    `getGlobalPlacement()` computes the same world transform for most objects and
    is not used, for one disqualifying reason: `App::Link` does not implement it,
    and links are how the PTUs, transformers, pump banks and rack runs are placed.
    Beware of `ViewObject.getBoundingBox()` too, which looks like ground truth for
    "where does FreeCAD draw this" and is not - it reports the local box and
    ignores inherited transforms, so it silently confirms whatever frame you
    already believed.

    A part whose world placement is identity has its position baked into the
    vertices, which is what a flattened STEP import looks like. There the only
    recoverable transform is the translation that takes its bounding-box corner to
    the origin, so copies that differ by a rotation will not match signatures and
    get meshed separately. That is a missed saving, not an error.

    The signature itself is deliberately strict: face and edge counts, area,
    volume, local bounding-box dimensions, and a hash of every vertex of the local
    shape rounded to a micron.
    """
    if ancestors is None:
        ancestors = FreeCAD.Placement()
    shape = obj.Shape
    placed = world_shape(obj, ancestors)
    placement = placed.Placement

    if not placement.isIdentity():
        local = shape.copy()
        local.Placement = FreeCAD.Placement()
        translation = tuple(placement.Base)
        q = placement.Rotation.Q
        rotation = (q[0], q[1], q[2], q[3])
    else:
        box = placed.BoundBox
        translation = (box.XMin, box.YMin, box.ZMin)
        local = placed.copy()
        local.translate(FreeCAD.Vector(-box.XMin, -box.YMin, -box.ZMin))
        rotation = IDENTITY_ROTATION

    if not _lands_back(placed, local, translation, rotation):
        # Bake world coordinates and give it a signature nothing else can share.
        return ("world", obj.Name), placed, (0.0, 0.0, 0.0), IDENTITY_ROTATION

    local_box = local.BoundBox
    vertex_hash = hash(tuple(sorted(
        (round(v.X, 3), round(v.Y, 3), round(v.Z, 3)) for v in local.Vertexes
    )))
    signature = (
        len(shape.Faces), len(shape.Edges),
        round(shape.Area, 2), round(shape.Volume, 2),
        round(local_box.XLength, 3), round(local_box.YLength, 3),
        round(local_box.ZLength, 3),
        vertex_hash,
    )
    return signature, local, translation, rotation


def _lands_back(shape, local, translation, rotation, tolerance=1.0):
    """True if `local` put back through the transform recovers `shape`'s position.

    The test is on centre of mass, not the bounding box. Bounding boxes of curved
    solids are computed to a tolerance rather than exactly, and the error moves
    when the shape is rotated - on this model the same solid's box differed by up
    to 630 mm between two evaluations - so a box test rejected 600 perfectly good
    parts and pushed them out of instancing. Centre of mass is exact and
    transforms exactly under a rigid motion, which is all this needs to catch.

    Compounds do not expose CenterOfMass, so those fall back to a box test with
    slack proportional to the part.
    """
    # Compose with whatever placement `local` already carries, rather than
    # overwriting it. `Shape.translate` moves a shape by changing its placement,
    # so the bbox-normalised branch arrives here holding -bboxmin; assigning the
    # transform on top of that dropped the -bboxmin and doubled the offset, which
    # failed 603 good parts and dropped them out of instancing.
    replaced = local.copy()
    replaced.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*translation), FreeCAD.Rotation(*rotation)
    ).multiply(local.Placement)
    try:
        return (replaced.CenterOfMass - shape.CenterOfMass).Length <= tolerance
    except AttributeError:
        want, got = shape.BoundBox, replaced.BoundBox
        slack = tolerance + 0.01 * max(want.XLength, want.YLength, want.ZLength)
        return all(abs(a - b) <= slack for a, b in (
            (want.XMin, got.XMin), (want.YMin, got.YMin), (want.ZMin, got.ZMin),
            (want.XMax, got.XMax), (want.YMax, got.YMax), (want.ZMax, got.ZMax)))
