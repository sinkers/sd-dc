# Piping System

Parametric piping generation for FreeCAD. Generates solid 3D pipe geometry (straights + elbows) with validated connections between plant items.

## Files

- `piping.py` — Core module (PipeSpec, StraightPipe, Elbow, PipeRoute)
- `route_engine.py` — Orthogonal route engine with A* pathfinding and obstacle avoidance
- `router.py` — Standalone A* grid router (PipeRouter class)
- `routing_report.html` — Visual test report with 5 scenarios (3 pass, 2 fail)
- `README.md` — This file (rules, terminology, and usage)

## Terminology

| Term | Definition |
|------|-----------|
| **Plant** | Mechanical equipment with fluid connections — pumps, heat exchangers, tanks, CDUs, dry coolers. Each plant item has one or more nozzles. |
| **Nozzle** | A connection point on a plant item. Defined by a **position** (centre of the pipe face) and a **direction** (unit vector pointing outward from the equipment face). |
| **Outlet** | A nozzle where fluid leaves the plant item. Pipe departs from here. |
| **Inlet** | A nozzle where fluid enters the plant item. Pipe arrives here. |
| **Piping** | The network of straight segments and 90° elbows that connects plant outlets to plant inlets. |
| **Obstacle** | Any object the pipe must avoid — structural columns, cable trays, platforms, pipe racks, other previously-routed pipes. |
| **Bend Radius (BR)** | The centreline radius of a 90° elbow. Default: 1.5 × OD (long-radius per ASME B16.9). |

## Fundamental Connection Rule

**Pipes connect exactly one outlet to one inlet.** No other connection topology is valid.

```
VALID:    Pump outlet ──pipe──▶ HX inlet
VALID:    Tank outlet ──pipe──▶ Pump inlet
INVALID:  Outlet ──pipe──▶ Outlet    (nowhere for fluid to go)
INVALID:  Inlet  ──pipe──▶ Inlet     (no driving pressure)
INVALID:  Pipe connected to a wall with no nozzle
```

Two pipe segments connect when:

```
segment_A.end.pos == segment_B.start.pos       (positions coincident)
segment_A.end.direction == -segment_B.start.direction  (directions opposing)
```

## Nozzle Alignment Rule

A nozzle defines a single connection plane. A pipe can only connect to a nozzle if the pipe segment at that nozzle is **collinear** with the nozzle's direction axis.

```
Nozzle definition:
  pos:       centre of the connection face (FreeCAD.Vector)
  direction: unit vector pointing OUTWARD from the equipment face

Departure (from outlet):
  - First waypoint MUST equal nozzle.pos
  - First segment direction MUST equal nozzle.direction
  - Pipe leaves the nozzle traveling in the nozzle's outward direction

Arrival (at inlet):
  - Last waypoint MUST equal nozzle.pos
  - Last segment direction MUST equal OPPOSITE of nozzle.direction
  - Pipe arrives traveling INTO the nozzle face
```

**Example:** A pump outlet nozzle on the right face has `direction = (+1, 0, 0)`.
The pipe's first segment must go in +X. Any other direction would mean the pipe exits at an angle to the nozzle face — physically impossible.

At the destination, an HX inlet nozzle on the left face has `direction = (-1, 0, 0)`.
The pipe's last segment must arrive going +X (opposite to -X), meaning it approaches from the left and connects flush to the nozzle face.

## Routing Constraints

### 90° Elbows Only — No 180° Reversals

All turns are exactly 90°. If a pipe needs to reverse direction on the same axis (e.g. go +Z then -Z), it **MUST** include a perpendicular intermediate segment:

```
INVALID:  ... → (+Z 1000mm) → (-Z 500mm) → ...     ← 180° turn, impossible with 90° elbow
VALID:    ... → (+Z 1000mm) → (+X 500mm) → (-Z 500mm) → ...  ← two 90° turns
```

### Minimum Segment Length

Each straight segment between elbows must be long enough for the elbows to fit:

| Position | Minimum Length | Why |
|----------|---------------|-----|
| Interior (elbow both ends) | 2 × BR (343 mm for DN100) | Both adjacent elbows consume BR from this segment |
| First or last segment | 1 × BR (171.5 mm for DN100) | Only one elbow on this segment |

Violating this constraint means elbows overlap — the geometry cannot be built.

### Obstacle Clearance at Nozzles

An obstacle must not be placed within 1 × BR of a nozzle face in the nozzle's departure direction. The pipe needs at least one bend radius of straight run before it can elbow away from an obstacle.

```
INVALID:  Nozzle ──100mm──▶ [OBSTACLE]   (100 < 171.5mm BR, can't turn in time)
VALID:    Nozzle ──200mm──▶ [OBSTACLE]   (200 > 171.5mm BR, can elbow before obstacle)
```

### Chain Integrity

Every pipe part's exit position must exactly equal the next part's entry position:

```
part[i].exit_pos == part[i+1].entry_pos   (tolerance: 0.000 mm)
```

This is enforced by the `build_and_validate()` function.

## Failure Conditions

The router correctly **rejects** layouts that cannot be physically built:

| Condition | Cause | Fix |
|-----------|-------|-----|
| Blocked nozzle | Obstacle within 1×BR of nozzle face | Move obstacle ≥ 1×BR from nozzle |
| Enclosed inlet | All approach axes blocked by obstacles | Remove or relocate enclosing obstacles |
| Segment too short | Direction change needed within < 2×BR | Increase spacing between turns |
| 180° reversal | Consecutive segments reverse direction | Add perpendicular intermediate segment |
| Nozzle misalignment | Pipe direction doesn't match nozzle axis | Recalculate waypoints to align |

## Elbow Geometry

For a circular elbow with bend radius `R` and center `C`:

1. **Tangent condition**: At any point `P` on the arc, the flow direction is tangent to the arc, meaning `(P - C)` is perpendicular to the flow direction at `P`

2. **Center positioning**: When a straight in direction `entry_dir` meets an elbow turning toward `turn_dir`:
   ```
   center = entry_pos + turn_dir * R
   exit_pos = center + entry_dir * R
   ```

3. **Arc midpoint** (for FreeCAD 3-point arc construction):
   ```
   mid_vec = (radial_start + radial_end).normalize()
   arc_mid = center + mid_vec * R
   ```

4. **Bend normal**: Determined by right-hand rule from incoming to outgoing flow:
   ```
   bend_normal = flow_in.cross(flow_out).normalize()
   ```

## Pipe Sizes

| DN | OD (mm) | Wall Sch10S (mm) | Default BR (mm) |
|----|---------|------------------|-----------------|
| 25 | 33.7 | 2.77 | 50.6 |
| 50 | 60.3 | 2.77 | 90.5 |
| 80 | 88.9 | 3.05 | 133.4 |
| **100** | **114.3** | **3.05** | **171.5** |
| 150 | 168.3 | 3.40 | 252.5 |
| 200 | 219.1 | 3.76 | 328.7 |
| 250 | 273.0 | 4.19 | 409.5 |
| 300 | 323.9 | 4.57 | 485.9 |
| 400 | 406.4 | 4.78 | 609.6 |
| 500 | 508.0 | 5.54 | 762.0 |
| 600 | 609.6 | 5.54 | 914.4 |

BR = 1.5 × OD (long-radius elbows per ASME B16.9)

## Shape Construction

- **Straight**: Solid cylinder (`Part.makeCylinder`) along the segment direction
- **Elbow**: Circular pipe profile swept along a 3-point arc (entry, midpoint, exit)
- **Hollow** variant: Outer cylinder minus inner cylinder (for wall thickness modelling)

## Usage

### Waypoint Routing (Recommended)

```python
from route_engine import waypoints_to_pipe, validate_waypoints
import FreeCAD

# Define nozzles (position, outward direction)
pump_outlet = (FreeCAD.Vector(500, 200, 300), FreeCAD.Vector(1, 0, 0))
hx_inlet = (FreeCAD.Vector(3500, 200, 300), FreeCAD.Vector(-1, 0, 0))

# Define waypoints (orthogonal corners)
waypoints = [
    FreeCAD.Vector(500, 200, 300),    # start at pump outlet
    FreeCAD.Vector(900, 200, 300),    # +X 400mm
    FreeCAD.Vector(900, -200, 300),   # -Y 400mm (go around obstacle)
    FreeCAD.Vector(2400, -200, 300),  # +X past obstacle
    FreeCAD.Vector(2400, 200, 300),   # +Y back to centreline
    FreeCAD.Vector(3500, 200, 300),   # +X arrive at HX inlet
]

# Validate before building
errors = validate_waypoints(waypoints, bend_radius=171.5,
                           start_nozzle=pump_outlet, end_nozzle=hx_inlet)
assert not errors, errors

# Build geometry
objects, build_errors = waypoints_to_pipe(
    waypoints, doc, "Supply",
    od=114.3, bend_radius=171.5,
    start_nozzle=pump_outlet, end_nozzle=hx_inlet
)
```

### A* Automatic Routing

```python
from route_engine import RouteEngine

engine = RouteEngine(od=114.3, bend_radius=171.5, grid_size=200)

# Add obstacles (bounding boxes with padding)
engine.add_obstacle(FreeCAD.Vector(1600, 0, 0), FreeCAD.Vector(2000, 400, 1500))

# Route automatically
parts = engine.route(
    start_pos=FreeCAD.Vector(500, 200, 300),
    start_dir=FreeCAD.Vector(1, 0, 0),
    end_pos=FreeCAD.Vector(3500, 200, 300),
    arrive_dir=FreeCAD.Vector(1, 0, 0)  # arriving in +X (opposite to inlet's -X)
)

if parts:
    from route_engine import build_and_validate
    objects, errors = build_and_validate(parts, doc, "AutoRoute")
```

### PipeRoute Fluent API

```python
from piping import PipeSpec, PipeRoute

spec = PipeSpec.from_dn(150)  # DN150 pipe

route = PipeRoute(spec, "MyPipe")
route.start_at(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(1, 0, 0))
route.straight(2000)                        # 2m straight
route.elbow(FreeCAD.Vector(0, 1, 0))       # 90° bend to +Y
route.straight(1500)                        # 1.5m straight

objects = route.build(doc)
issues = route.validate()  # Check all joints (should be [])
```

### Sequential Routing (Pipe as Obstacle)

```python
from router import PipeRouter
from piping import create_pipe_run

router = PipeRouter(grid_size=200)
router.add_obstacle_box(equipment_min, equipment_max)

# Route first pipe
supply_wp = router.find_path(pump_discharge, hx_inlet)
supply = create_pipe_run(doc, "Supply", 150, supply_wp)

# Add first pipe as obstacle, then route second pipe
router.add_pipe_as_obstacle(supply, padding=300)
return_wp = router.find_path(hx_outlet, pump_suction)
ret = create_pipe_run(doc, "Return", 150, return_wp)
```

## Obstacle Avoidance Strategies

| Strategy | When to Use | Route Shape |
|----------|-------------|-------------|
| Go AROUND (horizontal) | Obstacle spans full height | Detour in ±Y, return to centreline |
| Go OVER (vertical) | Obstacle is short / pipe can clear it | Rise in +Z above obstacle top |
| Go UNDER | Elevated obstacle with clearance below | Drop in -Z below obstacle |
| Sequential avoidance | Multiple pipes in same corridor | Previously routed pipes become obstacles |

## A* Pathfinding Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `grid_size` | 200 mm | Cell size. Smaller = more precise but slower. |
| `bend_penalty` | 2.5× | Cost multiplier for direction changes. Higher = fewer elbows. |
| Movement | 6 directions | ±X, ±Y, ±Z (orthogonal only) |
| Max iterations | 300,000 | Safety limit to prevent infinite loops |

## Design Decisions

1. **Outlet → Inlet only** — every pipe run represents a physical fluid path from source to destination
2. **Nozzle alignment enforced** — prevents impossible connections at equipment faces
3. **Hollow pipes** — both OD and ID modelled (wall thickness matters for weight/cost)
4. **1.5D default** — long-radius elbows per ASME B16.9, the most common in industrial piping
5. **Connection-point protocol** — enables future components (tees, reducers, valves) to plug in
6. **Validation built-in** — catch connection errors and impossible geometry before exporting
7. **Fail-fast on blocked nozzles** — reports why routing is impossible, not just "no path found"
8. **Minimum segment constraint** — prevents physically impossible geometry where elbows overlap
9. **A* with bend penalty** — produces routes that minimise the number of elbows (fewer fittings, lower pressure drop)
10. **Sequential routing** — previously routed pipes become obstacles for subsequent routes, preventing clashes

## Lessons Learned

### Geometry Pitfalls

- **FreeCAD `Part.Arc()` fails on 180° arcs** — always validate that consecutive segments are not parallel-opposite before attempting to build an elbow
- **`Vector.normalize()` mutates in place** — in FreeCAD, calling `v.normalize()` modifies `v` and returns it. Copy first if you need the original: `d = FreeCAD.Vector(v).normalize()`
- **Elbow consumes BR from BOTH adjacent segments** — a straight between two elbows loses 2×BR of its total length. If the segment is shorter than 2×BR, the elbows overlap and creation fails
- **Pipe sweep profile must be perpendicular to path** — `Part.makeCircle(r, pos, direction)` where `direction` is the flow direction at that point

### Nozzle Placement Pitfalls

- **Don't place nozzles flush with obstacle surfaces** — if a nozzle face coincides with an obstacle face (e.g. tank bottom nozzle at same Z as platform top), the pipe visually appears to connect to the obstacle rather than clearly departing from the nozzle
- **Leave visible clearance around nozzles** — nozzle stubs should protrude clearly from the plant body so the connection point is unambiguous in renders
- **Both inlet and outlet on same face is confusing** — if both are on the same equipment face, pipes cross each other. Place inlet/outlet on opposite faces where possible

### Routing Strategy

- **Validate waypoints BEFORE building geometry** — `validate_waypoints()` catches all constraint violations cheaply; building Part shapes is expensive and produces cryptic errors
- **The arrival direction is the inverse of the nozzle direction** — easy to get backwards. The nozzle direction points OUTWARD; the pipe arrives going INWARD (opposite)
- **Check obstacle overlap with pipe elevation** — a "low" cable tray at Z=0-150 doesn't block a pipe at Z=450, but a "tall" column at Z=0-1500 blocks everything
- **Sort pipe objects by creation order, not name** — alphabetical sorting of names like "Pipe_0e", "Pipe_0s", "Pipe_1e" mixes elbows with straights and breaks chain validation
