# Software Defined Data Centre (SD-DC) Design Toolkit

> **This is the original vision document.** For what actually exists today see
> [`README.md`](README.md); for what is being built next see [`PLAN.md`](PLAN.md).
> Parts of this document describe a structure that was never built — those are
> marked where they occur.

## Vision

A programmatic toolkit that enables AI agents to design, model, and iterate on data centre infrastructure layouts using parametric 3D CAD. The system transforms high-level specifications (power capacity, cooling requirements, rack counts) into detailed engineering models with accurate geometry, piping, and spatial relationships.

## Problem Statement

Data centre design today requires:
- Weeks of manual CAD work by specialist mechanical/electrical engineers
- Iterative layout changes that cascade through multiple drawing sets
- Expert knowledge of equipment dimensions, clearances, and connection requirements
- Coordination between disciplines (structural, mechanical, electrical, civil)

**SD-DC** automates the spatial design layer — generating and validating layouts that satisfy engineering constraints, then outputting models suitable for detailed engineering, visualisation, and construction documentation.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                     SD-DC Design Toolkit                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐   │
│  │ Specification│   │ Layout       │   │ Output           │   │
│  │ Layer        │   │ Engine       │   │ Layer            │   │
│  │              │   │              │   │                  │   │
│  │ • Power MW   │──▶│ • Spatial    │──▶│ • STEP/IFC      │   │
│  │ • Cooling kW │   │   solver    │   │ • SVG renders   │   │
│  │ • Rack count │   │ • Clearance │   │ • BOM/schedules │   │
│  │ • Redundancy │   │   checks    │   │ • Piping ISO    │   │
│  │ • Site bounds│   │ • Equipment │   │ • Cable trays   │   │
│  └──────────────┘   │   placement │   │ • FCStd native  │   │
│                      └──────────────┘   └──────────────────┘   │
│                             │                                   │
│                      ┌──────▼──────┐                           │
│                      │ Component   │                           │
│                      │ Library     │                           │
│                      │             │                           │
│                      │ • Dry coolers│                          │
│                      │ • CDUs/XDUs │                           │
│                      │ • Pumps     │                           │
│                      │ • Generators│                           │
│                      │ • Switchgear│                           │
│                      │ • UPS       │                           │
│                      │ • Racks     │                           │
│                      │ • Pipe fittings│                        │
│                      └─────────────┘                           │
│                                                                 │
├─────────────────────────────────────────────────────────────────┤
│  Infrastructure: FreeCAD (headless VM) + XML-RPC + MCP Bridge   │
└─────────────────────────────────────────────────────────────────┘
```

## Core Components

### 1. Component Library (`/components/`)

Parametric definitions of data centre equipment. Each component defines:

- **Geometry** — accurate 3D envelope with connection points
- **Parameters** — capacity (kW, kVA, A), dimensions, weight
- **Connections** — pipe stubs, cable entry points, duct flanges
- **Clearances** — maintenance access zones, airflow clearances
- **Metadata** — manufacturer, model, datasheet reference

#### Initial Component Set

| Category | Components | Parameters |
|----------|-----------|------------|
| **Cooling - Rejection** | Dry coolers, cooling towers, adiabatic coolers | Capacity kW, fan count, dimensions, water flow rate |
| **Cooling - Distribution** | CDUs (Vertiv XDU 1350, Schneider), CRAHs, rear-door heat exchangers | Capacity kW, flow rate, connections |
| **Cooling - Pumps** | Inline centrifugal, end-suction, variable speed | Flow rate, head, motor kW |
| **Power - Generation** | Diesel generators, gas generators, BESS | MVA, fuel type, runtime |
| **Power - Distribution** | HV switchgear, transformers, LV switchboards, PDUs, busway | Voltage, current, sections |
| **Power - UPS** | Rotary UPS, static UPS, lithium UPS | kVA, autonomy, topology |
| **IT - Racks** | Standard 42U, 48U, 52U; open frames | Width, depth, power density kW |
| **Structure** | Containers, prefab modules, steel frames | Dimensions, structural loads |
| **Piping** | Headers, manifolds, valves, reducers, elbows | DN size, schedule, material |
| **Cable Management** | Cable trays (Ezystrut), ladders, conduit | Width, load rating |

### 2. Layout Engine (`/engine/`)

Takes a specification and generates optimal spatial arrangements:

```python
spec = DCSpec(
    power_mw=2.5,
    cooling_type="closed_loop_dry",
    redundancy="N+1",
    rack_count=120,
    power_density_kw_per_rack=20,
    site_boundary=Polygon(...),  # cadastral or custom
)

layout = engine.generate(spec)
# Returns: positioned components, piping routes, cable paths
```

#### Solver Constraints

- **Clearance rules** — minimum maintenance access (e.g., 1.2m around switchgear)
- **Pipe routing** — shortest path with bend limits, support spacing
- **Structural** — load distribution, foundation requirements
- **Code compliance** — fire separation, egress paths, ventilation
- **Thermal** — hot/cold aisle, exhaust plume separation for outdoor plant

### 3. Specification Layer (`/specs/`)

Input format for describing what to design:

```yaml
# spec.yaml
project:
  name: "AU01 Edge Data Centre"
  location: "-37.8136, 144.9631"
  
power:
  total_it_load_mw: 2.5
  pue_target: 1.25
  redundancy: "2N"
  utility_voltage_kv: 22
  
cooling:
  type: "closed_loop"
  rejection: "dry_cooler"
  design_ambient_db: 40  # °C
  supply_temp: 35  # °C to IT
  return_temp: 45  # °C from IT
  
it_hall:
  rack_count: 120
  rack_kw: 20
  row_configuration: "hot_aisle_containment"
  
site:
  boundary_source: "cadastral"  # or "geojson", "coordinates"
  parcel_id: "LOT 1 PS123456"
  setbacks_m: 3
```

### 4. Output Layer (`/output/`)

Generated deliverables:

| Output | Format | Use |
|--------|--------|-----|
| 3D Model | .FCStd, .STEP, .IFC | Engineering, coordination |
| Renders | .SVG, .PNG | Presentations, approvals |
| BOM | .CSV, .XLSX | Procurement, costing |
| Piping schedule | .CSV | Mechanical contractor |
| Cable schedule | .CSV | Electrical contractor |
| Layout drawing | .PDF (from SVG) | Approvals, construction |
| Site plan | .DXF | Civil/planning submission |

### 5. Infrastructure (`/vm-setup/`)

The FreeCAD execution environment (this directory):

- Parallels VM with headless FreeCAD
- XML-RPC server for programmatic access
- MCP bridge for AI agent integration
- Auto-start on boot, auto-recovery on crash

## Design Principles

1. **Parametric first** — dimensions derive from capacity, not the reverse
2. **Connection-driven** — components connect at defined ports; piping/cables route automatically
3. **Constraint-based** — the solver enforces clearances, codes, and physics
4. **Iterative** — change one parameter, regenerate the affected scope
5. **Export-ready** — outputs go directly to engineering tools (Revit, AutoCAD, fabrication)
6. **AI-native** — designed for agent control via MCP, not human GUI interaction

## Workflow

```
1. SPECIFY  →  Define requirements (power, cooling, racks, site)
2. GENERATE →  Layout engine places equipment, routes services
3. VALIDATE →  Check clearances, capacity, redundancy paths
4. RENDER   →  SVG/PNG isometric views for review
5. ITERATE  →  Agent or human adjusts spec, regenerate
6. EXPORT   →  STEP/IFC for detailed engineering, BOM for procurement
```

## API Design (Agent Interface)

```python
from sddc import Toolkit, DCSpec, CoolingSystem, PowerSystem

# Initialize (connects to FreeCAD VM)
tk = Toolkit(host="10.211.55.5", port=9875)

# Define spec
spec = DCSpec.from_yaml("spec.yaml")

# Generate cooling system
cooling = CoolingSystem(
    capacity_kw=2500,
    type="closed_loop_dry",
    n_coolers=1,
    n_pumps=3,
    n_cdus=3,
    cdu_model="vertiv_xdu_1350",
    redundancy="N+1",
)
cooling.generate(tk)  # Creates 3D model in FreeCAD

# Generate power system
power = PowerSystem(
    capacity_mva=3.0,
    topology="2N",
    gen_model="cat_c32",
    ups_model="vertiv_liebert_eXL",
)
power.generate(tk)

# Validate
issues = tk.validate()  # Returns clearance violations, capacity mismatches

# Export
tk.export_step("output/full_model.step")
tk.export_svg("output/isometric.svg", view="isometric")
tk.export_bom("output/bom.csv")
```

## Implementation Phases

### Phase 1: Foundation (Current) ✅
- [x] FreeCAD headless VM with RPC server
- [x] MCP bridge configuration
- [x] Basic component creation (boxes, cylinders, pipes)
- [x] SVG rendering pipeline
- [x] STEP/OBJ/STL export

### Phase 2: Component Library
- [ ] Parametric component definitions (JSON/YAML schema)
- [ ] Dry cooler family (1MW–5MW range)
- [ ] Vertiv XDU 1350 accurate model
- [ ] Pump family (various sizes)
- [ ] Pipe fitting library (elbows, tees, reducers, valves)
- [ ] Rack models (42U, 48U with power density variants)

### Phase 3: Layout Engine
- [ ] Specification parser (YAML → internal model)
- [ ] Equipment placement solver
- [ ] Pipe routing algorithm (A* with bend cost)
- [ ] Clearance checker
- [ ] Redundancy path validator

### Phase 4: Integration
- [ ] MCP tool wrappers for each operation
- [ ] Cadastral/GIS integration (site boundary import)
- [ ] Cable tray routing
- [ ] Structural framing generation
- [ ] BOM extraction and export

### Phase 5: Advanced
- [ ] IFC export for BIM coordination
- [ ] Thermal CFD pre-check (simplified)
- [ ] Electrical single-line diagram generation
- [ ] Construction sequencing
- [ ] Cost estimation from BOM + rates DB

## File Structure

> **This section is aspirational, not a description of the repository.**
> `components/`, `engine/`, `specs/`, `output/` and `sddc/` below do not exist.
> The layout that does exist is in [`README.md`](README.md); the plan for getting
> from one to the other is in [`PLAN.md`](PLAN.md), where the layout engine lands
> as `layout/` rather than the split shown here.

```
sd-dc/
├── SPEC.md                          # This file
├── components/                      # Component library
│   ├── schema.json                  # Component definition schema
│   ├── cooling/
│   │   ├── dry_cooler.py
│   │   ├── vertiv_xdu_1350.py
│   │   └── pump_centrifugal.py
│   ├── power/
│   │   ├── generator.py
│   │   ├── transformer.py
│   │   └── ups.py
│   ├── it/
│   │   └── rack.py
│   └── piping/
│       ├── header.py
│       ├── fittings.py
│       └── routing.py
├── engine/                          # Layout engine
│   ├── solver.py
│   ├── constraints.py
│   ├── routing.py
│   └── validation.py
├── specs/                           # Example specifications
│   └── au01_edge_dc.yaml
├── output/                          # Generated outputs
├── cooling-model/                   # Working models
│   ├── model_cooling_system.py
│   ├── CoolingSystem.FCStd
│   ├── PumpSkid_Test.step
│   └── CoolingSystem_render.svg
├── vm-setup/                        # Infrastructure
│   ├── INSTALL.md
│   ├── AGENT_INSTRUCTIONS.md
│   ├── create-vm.sh
│   ├── provision.sh
│   ├── freecad_rpc_server.py
│   └── cloud-init/
├── cable-tray-ezystrut/            # Existing cable tray data
├── cables/                          # Nexans cable catalogue (product data)
├── cable-sizing/                    # AS/NZS 3008 cable sizing engine
│   ├── as3008.py
│   ├── iec60228.py
│   ├── cable_sizing.py
│   └── test_cable_sizing.py
└── sddc/                           # Python package (future)
    ├── __init__.py
    ├── toolkit.py
    ├── spec.py
    └── components/
```

## Technology Choices

| Layer | Technology | Rationale |
|-------|-----------|-----------|
| CAD Engine | FreeCAD 1.x | Open source, Python API, parametric, STEP/IFC export |
| Execution | Parallels VM (ARM64) | Isolated, reproducible, auto-recoverable |
| Interface | XML-RPC + MCP | Standard protocols, any agent can connect |
| Spec Format | YAML | Human-readable, version-controllable |
| Component Defs | Python classes | Full parametric control, inheritance |
| Rendering | Tessellation → SVG | Works headless, scalable, lightweight |
| Data Exchange | STEP (3D), IFC (BIM), DXF (2D) | Industry standard interop |

## Success Criteria

1. **Agent can generate a complete cooling system layout** from a spec in < 60 seconds
2. **Exported STEP files open cleanly** in AutoCAD, Revit, Inventor
3. **Clearance validation catches** all spatial conflicts before export
4. **Pipe routing produces realistic paths** with proper supports and bend radii
5. **BOM accurately reflects** all placed components with correct quantities
6. **Non-expert users** can produce engineering-grade layouts by describing requirements in natural language to an AI agent
