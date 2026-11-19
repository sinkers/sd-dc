"""Minimal glTF 2.0 / GLB writer for faceted CAD parts, with instancing.

No dependencies, so it runs inside `freecadcmd`'s bundled interpreter as happily
as in the system one. It writes exactly the subset a CAD review viewer needs:
flat-shaded triangles, one material per distinct colour, one node per part with
its FreeCAD tree path in node `extras`, and - the point of the design - many
nodes able to share one mesh.

Instancing matters more than anything else here. A plant model is mostly the
same vendor part over and over (80 copies of a pipe fitting, 8 of a
transformer), and each copy costs a node and a transform instead of another
20,000 triangles. Every instance still keeps its own name and tree path, so
nothing is lost for review; only the geometry is shared.

Triangles arrive non-indexed - three vertices per facet, one facet normal
repeated. That is deliberate. CAD reads wrong with averaged vertex normals: a
box gets a soft, inflated look and a chamfer vanishes. Welding the seams back
together is exactly what `gltfpack` does downstream, better than we would, so
uncompressed output is about 3x larger than it needs to be and that is fine.

Coordinates go in as FreeCAD gives them: millimetres, Z up. The root node
carries the 0.001 scale and the -90 degree X rotation that takes Z-up CAD into
glTF's Y-up convention, so nothing is baked into the vertex data.
"""

from __future__ import annotations

import json
import struct

# glTF constants, spelled out so the accessor code reads as the spec does.
FLOAT = 5126
UNSIGNED_INT = 5125
ARRAY_BUFFER = 34962
ELEMENT_ARRAY_BUFFER = 34963
TRIANGLES = 4

IDENTITY_ROTATION = (0.0, 0.0, 0.0, 1.0)
# -90 degrees about X as a quaternion (x, y, z, w): Z-up CAD into Y-up glTF.
Z_UP_TO_Y_UP = [-0.7071067811865476, 0.0, 0.0, 0.7071067811865476]


class GlbBuilder:
    def __init__(self, scale=0.001, z_up=True):
        self.scale = scale
        self.z_up = z_up
        self._blobs = []          # binary chunk pieces, in order
        self._offset = 0          # running length of the binary chunk
        self._buffer_views = []
        self._accessors = []
        self._meshes = []
        self._nodes = []
        self._materials = []
        self._material_keys = {}  # colour tuple -> material index
        self._mesh_triangles = []  # triangles per mesh, for reporting

    # ---------- binary plumbing ----------

    def _append(self, data, target):
        """Copy `data` into the binary chunk, 4-byte aligned, and return its view."""
        pad = (-self._offset) % 4
        if pad:
            self._blobs.append(b"\x00" * pad)
            self._offset += pad
        view = len(self._buffer_views)
        self._buffer_views.append(
            {"buffer": 0, "byteOffset": self._offset, "byteLength": len(data),
             "target": target}
        )
        self._blobs.append(data)
        self._offset += len(data)
        return view

    def _vec3_accessor(self, values, with_bounds):
        data = struct.pack("<%df" % len(values), *values)
        view = self._append(data, ARRAY_BUFFER)
        acc = {"bufferView": view, "componentType": FLOAT,
               "count": len(values) // 3, "type": "VEC3"}
        if with_bounds:
            # POSITION requires min/max, per axis over the flat array.
            acc["min"] = [min(values[0::3]), min(values[1::3]), min(values[2::3])]
            acc["max"] = [max(values[0::3]), max(values[1::3]), max(values[2::3])]
        self._accessors.append(acc)
        return len(self._accessors) - 1

    def _index_accessor(self, count):
        """The trivial 0..count-1 index run that non-indexed triangles need."""
        data = struct.pack("<%dI" % count, *range(count))
        view = self._append(data, ELEMENT_ARRAY_BUFFER)
        self._accessors.append(
            {"bufferView": view, "componentType": UNSIGNED_INT,
             "count": count, "type": "SCALAR", "min": [0], "max": [count - 1]}
        )
        return len(self._accessors) - 1

    def _material(self, colour):
        """Return a material index for an RGBA colour, reusing one if seen."""
        key = tuple(round(c, 4) for c in colour)
        if key in self._material_keys:
            return self._material_keys[key]
        index = len(self._materials)
        mat = {
            "name": "c_%02x%02x%02x_%02x" % tuple(int(c * 255) for c in key),
            "pbrMetallicRoughness": {
                "baseColorFactor": list(key),
                "metallicFactor": 0.15,
                "roughnessFactor": 0.65,
            },
            "doubleSided": True,
        }
        if key[3] < 1.0:
            mat["alphaMode"] = "BLEND"
        self._materials.append(mat)
        self._material_keys[key] = index
        return index

    # ---------- public API ----------

    def add_mesh(self, name, positions, normals, colour):
        """Store geometry once and return its mesh index for instances to share."""
        if not positions:
            return None
        pos = self._vec3_accessor(positions, with_bounds=True)
        nrm = self._vec3_accessor(normals, with_bounds=False)
        triangles = len(positions) // 9
        idx = self._index_accessor(triangles * 3)
        self._meshes.append({
            "name": name,
            "primitives": [{
                "attributes": {"POSITION": pos, "NORMAL": nrm},
                "indices": idx,
                "material": self._material(colour),
                "mode": TRIANGLES,
            }],
        })
        self._mesh_triangles.append(triangles)
        return len(self._meshes) - 1

    def add_instance(self, name, mesh, translation=None, rotation=None,
                     path=None, extras=None):
        """Place a shared mesh in the scene under its own name and tree path."""
        node = {"name": name, "mesh": mesh}
        if translation and any(translation):
            node["translation"] = [float(v) for v in translation]
        if rotation and tuple(rotation) != IDENTITY_ROTATION:
            node["rotation"] = [float(v) for v in rotation]
        node_extras = dict(extras or {})
        if path:
            node_extras["path"] = list(path)
        if node_extras:
            node["extras"] = node_extras
        self._nodes.append(node)

    @property
    def instance_count(self):
        return len(self._nodes)

    @property
    def mesh_count(self):
        return len(self._meshes)

    @property
    def unique_triangles(self):
        """Triangles actually stored in the buffer."""
        return sum(self._mesh_triangles)

    def build(self):
        if not self._nodes:
            raise ValueError("nothing to export: no instances were added")

        # Everything hangs off one root carrying the unit and axis convention.
        root = {"name": "model_root", "children": list(range(len(self._nodes))),
                "scale": [self.scale] * 3}
        if self.z_up:
            root["rotation"] = Z_UP_TO_Y_UP
        nodes = self._nodes + [root]

        binary = b"".join(self._blobs)
        gltf = {
            "asset": {"version": "2.0", "generator": "sd-dc model-review"},
            "scene": 0,
            "scenes": [{"nodes": [len(nodes) - 1]}],
            "nodes": nodes,
            "meshes": self._meshes,
            "materials": self._materials,
            "accessors": self._accessors,
            "bufferViews": self._buffer_views,
            "buffers": [{"byteLength": len(binary)}],
        }

        json_chunk = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
        json_chunk += b" " * ((-len(json_chunk)) % 4)
        binary += b"\x00" * ((-len(binary)) % 4)

        total = 12 + 8 + len(json_chunk) + 8 + len(binary)
        out = bytearray()
        out += struct.pack("<4sII", b"glTF", 2, total)
        out += struct.pack("<I4s", len(json_chunk), b"JSON") + json_chunk
        out += struct.pack("<I4s", len(binary), b"BIN\x00") + binary
        return bytes(out)
