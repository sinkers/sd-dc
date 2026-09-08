# FreeCAD VM MCP - Agent Instructions

## Overview

This system runs FreeCAD headless on a Parallels VM and exposes it via XML-RPC on port 9875. Any AI agent with network access to the VM can create, modify, and export 3D CAD models programmatically.

## Quick Start (For Agents)

### Connect to the RPC Server

```python
import xmlrpc.client
import json

proxy = xmlrpc.client.ServerProxy('http://10.211.55.5:9875/RPC2')

# Verify connection
assert proxy.ping() == "pong"
```

### Available RPC Methods

| Method | Arguments | Returns | Description |
|--------|-----------|---------|-------------|
| `ping()` | - | `"pong"` | Health check |
| `get_version()` | - | dict | FreeCAD version info |
| `list_documents()` | - | list[str] | Open document names |
| `create_document(name)` | name: str | dict | Create new document |
| `close_document(name)` | name: str | bool | Close document |
| `save_document(name, path?)` | name: str, path: str | bool | Save to .FCStd |
| `get_objects(doc_name?)` | doc_name: str | list[dict] | List all objects |
| `get_object(obj_name, doc_name?)` | obj_name: str | dict | Object details |
| `create_object(type_id, name, doc_name?, properties?)` | ... | dict | Add object |
| `delete_object(obj_name, doc_name?)` | obj_name: str | bool | Remove object |
| `execute_code(code)` | code: str | JSON str | Run arbitrary Python |
| `recompute(doc_name?)` | doc_name: str | bool | Recompute model |
| `get_parts_list(doc_name?)` | doc_name: str | list[dict] | BOM with volumes |

### Execute Arbitrary Code

The most powerful method is `execute_code()` which runs Python inside FreeCAD:

```python
code = """
import FreeCAD
import Part

doc = FreeCAD.newDocument("MyModel")
box = doc.addObject("Part::Box", "MyBox")
box.Length = 1000
box.Width = 500
box.Height = 300
doc.recompute()

result = f"Created box: {box.Length}x{box.Width}x{box.Height}mm"
"""

response = json.loads(proxy.execute_code(code))
# response = {"status": "ok", "result": "Created box: 1000x500x300mm"}
```

**Important:** Set `result` variable in your code to return data. The response is always JSON with `status` and `result` (or `error` + `traceback`).

### Common FreeCAD Object Types

| Type ID | Description | Key Properties |
|---------|-------------|----------------|
| `Part::Box` | Rectangular box | Length, Width, Height |
| `Part::Cylinder` | Cylinder | Radius, Height |
| `Part::Sphere` | Sphere | Radius |
| `Part::Cone` | Cone | Radius1, Radius2, Height |
| `Part::Torus` | Torus | Radius1, Radius2 |
| `Part::Feature` | Custom shape | Shape (set programmatically) |

### Positioning Objects

```python
obj.Placement = FreeCAD.Placement(
    FreeCAD.Vector(x, y, z),        # position in mm
    FreeCAD.Rotation(axis, angle)   # or FreeCAD.Rotation(yaw, pitch, roll)
)
```

### Creating Pipes/Tubes

```python
start = FreeCAD.Vector(0, 0, 0)
end = FreeCAD.Vector(1000, 0, 0)
direction = end - start
pipe = Part.makeCylinder(outer_radius, direction.Length, start, direction)
obj = doc.addObject("Part::Feature", "Pipe")
obj.Shape = pipe
```

### Exporting Models

```python
# STEP format (industry standard)
shapes = [obj.Shape for obj in doc.Objects if hasattr(obj, 'Shape')]
compound = Part.makeCompound(shapes)
compound.exportStep('/home/freecad/output.step')

# STL format (3D printing/visualization)
import Mesh
mesh = Mesh.Mesh()
for s in shapes:
    mesh.addMesh(Mesh.Mesh(s.tessellate(1.0)))
mesh.write('/home/freecad/output.stl')

# OBJ format
mesh.write('/home/freecad/output.obj')

# Native FreeCAD
doc.saveAs('/home/freecad/output.FCStd')
```

### Generating Renders (SVG)

Since FreeCAD runs headless, generate SVG renders via tessellation:

```python
import math

shapes = [obj.Shape for obj in doc.Objects if hasattr(obj, 'Shape')]
compound = Part.makeCompound(shapes)
bb = compound.BoundBox
cx, cy, cz = bb.Center.x, bb.Center.y, bb.Center.z

# Tessellate
all_triangles = []
for shape in shapes:
    points, facets = shape.tessellate(tolerance_mm)
    all_triangles.append((points, facets))

# Project isometrically
a, b = math.radians(30), math.radians(35)
scale = 800 / max(bb.XLength, bb.YLength, bb.ZLength)

def project(x, y, z):
    x -= cx; y -= cy; z -= cz
    px = x * math.cos(a) - y * math.sin(a)
    py = -(x * math.sin(a) + y * math.cos(a)) * math.sin(b) + z * math.cos(b)
    return px * scale, -py * scale

# Build SVG polygons with flat shading...
```

### SSH Access

For file transfers or direct debugging:

```bash
ssh -i ~/.ssh/freecad-vm freecad@10.211.55.5
```

Copy files:
```bash
scp -i ~/.ssh/freecad-vm local_file.py freecad@10.211.55.5:~/
scp -i ~/.ssh/freecad-vm freecad@10.211.55.5:~/output.step ./
```

## VM Management

```bash
# Status
prlctl list -f

# Stop
prlctl stop freecad-mcp

# Start
prlctl start freecad-mcp

# After start, wait ~15s for RPC server to initialize
# Then verify: python3 -c "import xmlrpc.client; print(xmlrpc.client.ServerProxy('http://10.211.55.5:9875/RPC2').ping())"
```

## Troubleshooting

| Issue | Solution |
|-------|----------|
| Connection refused | VM may not be running. `prlctl start freecad-mcp` then wait 15s |
| RPC timeout | SSH in and check: `pgrep -a freecad`. Restart: `systemctl --user restart freecad-rpc` |
| IP changed | Check: `prlctl list -f` for current IP |
| Out of memory | Model too complex. Reduce tessellation tolerance or split model |
| Module not found | Some FreeCAD modules unavailable headless. Use Part, Mesh, FreeCAD core |

## Architecture

```
┌─────────────────────────────────────────────┐
│  Host (macOS ARM64)                         │
│  ┌───────────────┐   ┌──────────────────┐  │
│  │ Claude Code   │   │ freecad-mcp      │  │
│  │ (Agent)       │──▶│ MCP Bridge       │  │
│  └───────────────┘   │ (uvx freecad-mcp │  │
│                       │  --host 10.211.55.5)│
│                       └────────┬─────────┘  │
│                                │ XML-RPC    │
│  ┌─────────────────────────────▼─────────┐  │
│  │  Parallels VM: freecad-mcp            │  │
│  │  Ubuntu 24.04 ARM64                   │  │
│  │  ┌────────────┐  ┌────────────────┐   │  │
│  │  │ Xvfb :99   │  │ freecadcmd     │   │  │
│  │  │ (virtual   │──│ + RPC server   │   │  │
│  │  │  display)  │  │ port 9875      │   │  │
│  │  └────────────┘  └────────────────┘   │  │
│  │  IP: 10.211.55.5                      │  │
│  └────────────────────────────────────────┘  │
└─────────────────────────────────────────────┘
```
