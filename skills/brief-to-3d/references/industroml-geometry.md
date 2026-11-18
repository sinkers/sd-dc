# Carrying site and building geometry in IndustroML v0.1

IndustroML v0.1 (`~/workspace/industroml/industroml.schema.json`) describes a
site as four lists: `containers`, `assets`, `interfaces`, `connections`. It was
built for connectivity, not architecture. It has no storey, no roof and no
opening type. Everything here uses only what v0.1 allows: the enums as they
stand, and free-form `attributes` (the schema's `extendedAttributes` takes any
extra field). Nothing in this file changes the schema.

Where v0.1 has no home for something, the convention below puts it in
attributes, and the skill logs a schema gap in D3 (`owner: IndustroML`). Gaps
known today:

- **G1** no `storey` container type. Levels live in `building.attributes.levels`, rooms point at them by name.
- **G2** no opening (door, window, shutter) type. Openings live in `building.attributes.openings`.
- **G3** no roof type. The roof lives in `building.attributes.roof`.
- **G4** no site-works kinds (fence, gate, car park). These are `area` containers with attributes.
- **G5** `meta.units` exists, but geometry fields are not typed by the schema. Units are fixed by this convention: mm, in the frame stated.

## Frames and units

- Lengths in **mm**. Levels in **mm above the pad** (`ffl_mm`); the pad itself as `pad_rl_m` (m AHD) on the site.
- **Site frame**: the CRS on `site.attributes.crs` (for example `EPSG:28354`, MGA zone 54), or `local` if the model is not georeferenced.
- **Layout frame**: `building.attributes.frame = {origin_mm: [x, y, z], yaw_deg}` in site coordinates. Building footprints, rooms and equipment positions are in the layout frame. This matches how the FreeCAD model holds them (inside an `App::Part`) and how the fly-over anchors read them.
- Polygons are lists of `[x, y]`, anticlockwise, not closed (the first point is not repeated).

## Containers

```yaml
containers:
- id: SITE
  name: <site name>
  type: site
  attributes:
    crs: EPSG:28354
    datum: AHD
    boundary_mm: [[x, y], ...]          # lease / controlled boundary (source in the brief)
    pad_rl_m: 120.00
    aerial: {image: <file>, control_points: [...], status: hand-registered}
- id: B-HALL
  name: Data hall
  type: building
  parent: SITE
  attributes:
    frame: {origin_mm: [x, y, z], yaw_deg: -15.0}
    footprint_mm: [[x, y], ...]
    levels: [{name: L1, ffl_mm: 0, floor_to_floor_mm: null, clear_mm: 6500}]
    roof: {type: gable, pitch_deg: 5, eave_mm: 8500, ridge_mm: 9830}
    structure: {frames_at_mm: 6500, column_mm: [300, 300]}
    openings:
    - {id: B-HALL.D01, kind: roller_shutter, wall: west, width_mm: 5000, head_mm: 4500, security: restricted}
- id: B-OFF
  name: Office block
  type: building
  parent: SITE
  attributes:
    levels:
    - {name: L1, ffl_mm: 0, floor_to_floor_mm: 3250, clear_mm: 2700}
    - {name: L2, ffl_mm: 3250, floor_to_floor_mm: 2850, clear_mm: 2550}
    roof: {type: flat, top_mm: 6100, parapet_mm: 6800}
    voids: [{level: L2, polygon_mm: [[...]], reason: logistics strip open to the shell}]
- id: R-2.01
  name: NOC
  type: room
  parent: B-OFF
  attributes:
    level: L2
    number: "2.01"
    polygon_mm: [[x, y], ...]
    area_m2: 72.0                         # measured from the polygon
    rds_area_m2: 72.0                     # from the room data sheet, for the D10 check
    security_zone: restricted
    source: DAME-AIH-ARC-011 Rev E
- id: YARD-W
  name: West plant yard
  type: area
  parent: SITE
  attributes: {polygon_mm: [[...]]}
- id: POD-1
  name: AI pod 1
  type: area                              # racks inside are type: rack
  parent: B-HALL
- id: SW-FENCE
  name: Compound fence
  type: area
  parent: SITE
  attributes:
    kind: fence                           # G4
    rule: "rectangle on the layout frame, 6 m clear of the plant yards, enclosing office and car park"
    line_mm: [[x, y], ...]
    height_mm: 2400
    gates: [{id: SW-FENCE.G-S, width_mm: 10000, type: double_swing, at_mm: [x, y]}]
- id: SW-CARPARK
  name: Car park
  type: area
  parent: SITE
  attributes: {kind: car_park, bays: 20, accessible_bays: 2, polygon_mm: [[...]],
               dimensions_source: "AS/NZS 2890.1 - OPEN until quoted"}
```

Rack positions use `type: rack` containers under their pod, with
`attributes.position_mm` and `yaw_deg`.

## Assets

Every placed item of plant is an asset in the container it stands in, with its
placement and catalogue reference in attributes:

```yaml
- id: GEN-G1-001
  name: Generator G1-001
  domain: electrical
  kind: generator
  container: YARD-W
  attributes:
    manufacturer: <from catalogue>
    model: <from catalogue>
    catalogue_ref: generator/<vendor>-<model>
    position_mm: [x, y, 0]                # layout frame, footprint corner or centre (say which)
    position_ref: centre
    yaw_deg: 0
    envelope_mm: [12164, 3666, 2900]      # L x W x H
    phase: 1
    source: Schneider 10MW GA R0 (scaled - assumption)
```

Kind mapping used so far: genset `generator`; MV pod `ring_main_unit`, plus a
`transformer` if the pod holds one; LV/IT PTU `switchboard` (with a `ups`
asset where the PTU carries one); chiller `chiller`; dry cooler `dry_cooler`;
fan wall `crah`; CDU `cdu`; GPU node `server`; busway `busbar_section`. If no
kind fits, use `load` and log the gap. Do not invent a kind.

## Interfaces and connections

As the schema has them (see `planning/industroml-private/au013_revb.yaml` for a
worked model). Interface IDs are `ASSET.PORT`; positions go in
`attributes.position_mm` relative to the asset, with `direction`.

The schema needs at least one asset, interface and connection, so a model
built before R7 must still carry the utility supply to the first switchboard.
That is usually known from the grid connection strategy.

## Validation

Validate with `validate_industroML.py` after every write. Exit 0 or fix.
