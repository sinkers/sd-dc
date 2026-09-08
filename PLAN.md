# Plan — layout engine, equipment catalogue, and the four views

The next phase of SD-DC. `SPEC.md` is the vision, `README.md` is what exists,
this is what to build and in what order.

**The gap.** Components work in isolation. `cable-sizing` sizes a feeder,
`piping` routes a pipe, `cfd-cabinet-cooling` solves a hall, `digital-twin` runs
one. Nothing composes them into a data centre, and there is no machine-readable
catalogue of the equipment they would compose.

**The shape of the fix.** One schema and one IR in the middle. Crawlers write
catalogue entries; a 2D web tool places them; a compiler turns placements into
geometry; four views read the same model and answer electrical, cooling, security
and fire questions.

---

## 0. The two keystones

Everything below hangs off two artifacts. Get these wrong and all five
workstreams need rework, which is why they come first and why they are small.

### 0.1 Equipment catalogue schema

One schema for every category — transformers, switchgear, gensets, UPS, PTUs,
CRAHs, chillers, CDUs, IT pods, GPU servers, network switches.

```yaml
# catalogue/cooling.crah/vertiv-liebert-dse-400.yaml
id: vertiv-liebert-dse-400
category: cooling.crah            # taxonomy, drives palette + view selection
vendor: Vertiv
model: Liebert DSE 400

envelope_mm: {w: 2400, d: 900, h: 2100}
clearances_mm: {front: 1200, rear: 900, left: 0, right: 0, top: 300}
weight_kg: 1450
floor_load_kpa: 8.2

ports:                            # the thing that makes this a building block
  - {id: chw_in,  kind: pipe,       dn: 100, pos: [0, 450, 300],  dir: [-1,0,0]}
  - {id: chw_out, kind: pipe,       dn: 100, pos: [0, 450, 500],  dir: [-1,0,0]}
  - {id: power,   kind: electrical, phases: 3, voltage_v: 415, kva: 15}
  - {id: supply,  kind: air,        m3_s: 12.5, face: front}

ratings: {cooling_kw: 400, airflow_m3_s: 12.5, chw_dt_k: 6}
fire:     {detection: aspirating_required, suppression_zone: mech}
security: {zone: plant, access: controlled}

provenance:
  source_doc: sha256:9f2a…        # dc-model S3 content address
  source_page: 3
  extracted_by: spec_extract@v1
  verified: false
  fields_verified: [envelope_mm, weight_kg]     # per field, not per record
```

Three decisions worth defending:

**Ports are the universal connector.** `piping/` already has exactly this
concept — a nozzle with position and outward direction. Generalising it to
electrical, air and data ports is what lets the layout engine auto-connect
instead of asking a human to draw every link. An electrical port carrying `kva`
and `voltage_v` is a valid request body for `cable-sizing` `/api/size` with no
translation layer — which is the point, and is why the port fields should be named
after that API rather than invented (§1a).

**Provenance is per field, not per record.** An envelope traced off a
dimensioned drawing is trustworthy. An airflow figure lifted from marketing copy
is not. One `verified: true` on the record would launder the second as the first.
This follows the practice already in `reference_tables.json`.

**Category is a dotted taxonomy.** `cooling.crah`, `power.mv.switchgear`,
`it.gpu_server`. Palette grouping, view selection and crawler routing all key off
it, so it has to be a controlled vocabulary, not a free-text label.

### 0.1a Single-vendor white-label builds

A requirement, recorded here because it constrains the schema and is cheap now
and expensive later: it must be possible to ship a **single-vendor build** — a
Delta-only design tool, say — from the same codebase.

This falls out of the code-public / data-private split rather than fighting it.
Each vendor agreement unlocks a distribution:

```
   public code  +  Delta catalogue subset   ──▶  Delta-branded tool
   public code  +  Vertiv catalogue subset  ──▶  Vertiv-branded tool
   public code  +  full private catalogue   ──▶  internal build
```

The data-private architecture is what makes this possible. A vendor who will not
agree to their catalogue appearing in a public repo may well agree to it shipping
in a build carrying their own name.

Four consequences for the schema and the engines, all small if designed in now:

- **`vendor` is a first-class filter, not metadata.** Already a field in §0.1.
  It needs to be indexed and queryable — `GET /api/items?vendor=delta` — not
  just present on the record.
- **Catalogue subsetting must be a build input**, not a code change. A manifest
  naming the vendors, categories and licence scope a build includes; the palette
  and every engine read only what it admits.
- **Substitution must degrade honestly.** A single-vendor catalogue will have
  gaps — no cable, no tray, no chiller in some size. The engine must say "no
  compliant item in this catalogue" rather than silently widening the search.
  Same principle as `verified: false`: absence is information.
- **Branding is theming, never a fork.** Name, logo, palette in a config file.
  The moment a vendor build needs a code change, there are two products.

Not W1 work. But `vendor` filtering and the "no item in this catalogue" failure
mode belong in the schema and the engine contract from the start, because
retrofitting either means touching every consumer.

### 0.2 The layout IR

`dc-model/DESIGN.md` §2 already specifies this: *"components with
types/params/poses, connections, routes, constraints, metadata"*, JSON-schema
constrained, with a deterministic compiler to geometry.

**Do not invent a second one.** The 2D tool and the DC-1 model become two authors
of the same IR:

```
   2D web tool  ─┐
                 ├─▶  SD-DC IR (YAML)  ──▶ compiler ──▶ glTF / IFC / FreeCAD
   DC-1 model   ─┘         ▲                                    │
                           │                                    ▼
                    catalogue refs                    twin · views · drawings
```

This is the highest-leverage alignment in the plan. It means the 2D tool is
training-data generation for free: every hand-built layout is a verified IR
sample, and the compiler is the reward signal `DESIGN.md` §5 needs for RL.

---

## 1. Sequencing

The one non-obvious call: **hand-seed the catalogue before building crawlers.**

Building twelve crawlers, then discovering the schema cannot express a chiller's
part-load curve, wastes months. Instead seed 15–20 entries by hand from
datasheets already on drive, drive them through the whole loop — palette →
place → compile → view — and only then automate collection. The schema gets
exercised by every consumer before it is expensive to change.

| Wave | Deliverable | Gate to pass |
|---|---|---|
| **W0** | Schema + IR + validator, `sddc_client.py`, `health`/`meta` contract | 20 hand-written entries validate; IR round-trips through the compiler |
| **W1** | 2D tool, hand-seeded catalogue, catalogues wrapped as services | Author a 1 MW hall in the browser, export IR, no hand-editing of YAML; palette served over HTTP, not read from disk |
| **W2** | Compilers: glTF, IFC | Twin loads the compiled hall; IFC opens in a third-party viewer |
| **W3** | Crawler + extraction fleet | 200+ verified entries across the four groups |
| **W4** | Electrical + cooling views | One-line and cable schedule generated from IR; twin driven by compiled zones |
| **W5** | Security + fire views | Zone/coverage/egress checks run and fail correctly on a deliberately bad layout |

W2 and W3 can run in parallel once W1 lands — they touch different files.

---

## 1a. Every component is an independent service

A cross-cutting requirement, and it changes the design of everything below.

Each component must run on its own, expose a REST API, expose an MCP server for
agents, and call its peers over HTTP rather than by import or filesystem path.

**Today it does not.** `cable-sizing` reads `../cables/cable_catalog.json`;
`digital-twin` reads `../cfd-cabinet-cooling/geometry/`. Those relative paths only
resolve inside a monorepo checkout, so no component can be deployed or versioned
alone. That is the coupling to remove.

### The pattern is already proven

`cable-sizing` is the reference implementation. Copy it rather than reinventing:

```
  service.py       one implementation of every operation. Plain dicts in,
                   plain dicts out. No HTTP, no JSON-RPC, no framework.
       │
       ├── server.py       REST + HTML UI, stdlib http.server
       ├── openapi.py      OpenAPI 3.1 description, hand-written
       ├── mcp_server.py   MCP over stdio, JSON-RPC 2.0, no SDK
       └── direct import    for tests and offline use
```

The reason this matters is stated in `service.py`'s own docstring: a calculation
*cannot drift* between the browser and an agent, because there is only one
implementation. Every component gets the same three doors onto one room.

### What each component exposes

Two endpoints are mandatory everywhere, and both already exist in `cable-sizing`:

| Endpoint | Purpose |
|---|---|
| `GET /api/health` | liveness, for dependency checks and deploy gates |
| `GET /api/meta` | version, capabilities, and **which reference data is verified** |

`/api/meta` carrying verification state is what makes the provenance discipline
survive a network hop. A caller must be able to ask "is your earth-sizing table
verified?" without reading your source.

| Component | Service role | Representative operations |
|---|---|---|
| `cables` | catalogue | `GET /api/cables`, `/api/cables/{id}`, `/api/search?category=` |
| `cable-tray-ezystrut` | catalogue | `GET /api/trays`, `POST /api/fill` (bundle → tray), `/api/joints` |
| `catalogue` (new, §0.1) | catalogue | `GET /api/items?category=&vendor=`, `/api/items/{id}` — vendor filtering supports single-vendor builds (§0.1a) |
| `cable-sizing` | engine | `POST /api/size`, `/api/check` — **exists** |
| `piping` | engine | `POST /api/route` (nozzle→nozzle → parts), `/api/validate` |
| `layout` | engine | `POST /api/ir/validate`, `/api/compile`, `/api/constraints` |
| `cfd-cabinet-cooling` | solver | `POST /api/case` (IR → OpenFOAM case), `/api/jobs/{id}` |
| `digital-twin` | simulator | `POST /api/hall` (load a compiled layout), `GET /api/state` |

Solvers are asynchronous. CFD takes minutes to hours, so `POST /api/case` returns
a job id and the client polls — do not pretend a mesh-and-solve is a request.

### Batch endpoints are not optional

The obvious design, one HTTP call per decision, does not survive contact with a
real hall. Auto-connecting a 200-rack layout means thousands of `size_feeder`
calls. Every engine therefore needs a batch form:

```
POST /api/size        {source, load, route_length_m, install}      -> one result
POST /api/size/batch  {defaults: {...}, items: [{...}, {...}]}     -> N results
```

Same service function underneath, looped. Without this, the layout engine's
auto-connect step is unusable and someone will "fix" it by reaching back into a
direct import, undoing the separation.

### Discovery and degradation

Keep it boring. Environment variable per dependency, with a localhost default:

```
SDDC_CABLES_URL=http://localhost:8081
SDDC_CABLE_SIZING_URL=http://localhost:8082
SDDC_PIPING_URL=http://localhost:8083
```

A small shared `sddc_client.py` wraps `urllib.request` — stdlib, no `requests`
dependency — and does health-check-on-first-use, timeout, and one retry.

**Degrade loudly, never silently.** If `cable-sizing` is unreachable, the layout
engine must report "cable sizing unavailable, N connections unsized" in the IR
and in the UI. It must not quietly emit a layout with no cables, and it must not
substitute a guess. This is the same principle as the `verified: false` flag: the
absence of an answer is information.

Keep the direct-import path working for tests and offline use. Fast tests should
not need eight processes running.

### MCP surface

Each component ships **its own** MCP server, so it is independently useful to an
agent — `cable-sizing/mcp_server.py` already is, and it is already registered in
this project.

Then one **aggregator** MCP server at the repo root that fans out to whichever
services are running, so an agent can register a single entry and get the whole
toolkit. The aggregator holds no logic; it forwards to the REST APIs and merges
the tool lists.

Tool naming needs a convention from the start or it will collide once eight
components each expose `list_items`: `<component>_<verb>_<noun>` —
`cable_sizing_size_cable`, `piping_route_pipe`, `layout_compile_ir`.

### Security posture

These are engineering tools, not a product. Bind to localhost by default, no
auth, and say so plainly in each README. The moment one of them is bound to
`0.0.0.0` — as `digital-twin` already is, being deployed — it needs a decision
about authentication, and unauthenticated write endpoints on a
publicly-reachable service are not acceptable. Read-only catalogue endpoints are
a different and much easier case.

### Where this lands in the waves

W0 gains the `sddc_client.py` and the mandatory `health`/`meta` contract.
Wrapping the catalogues (`cables`, `cable-tray-ezystrut`) as services belongs in
W1, because the 2D tool's palette should consume the catalogue API rather than
read a JSON file — that is what proves the separation actually works before there
are eight of them.

---

## 2. The layout engine (`layout/`)

New component. Stdlib Python plus a plain SVG front end, matching
`cable-sizing/`: `server.py` for REST + HTML, `service.py` as the single
implementation, `ui.html` as one file.

```
layout/
  schema/            catalogue.schema.json, ir.schema.json
  service.py         one implementation of every operation
  server.py          stdlib http.server: REST + serves ui.html
  openapi.py         OpenAPI 3.1 description
  mcp_server.py      MCP over stdio for agents
  ui.html            SVG canvas, palette, property panel
  engine/
    place.py         instance placement, rotation, snapping
    constraints.py   clearance, overlap, floor loading, access routes
    connect.py       auto-connect ports -> cable-sizing / piping
    ir.py            read/write/validate the IR
  compile/
    gltf.py          -> digital twin
    ifc.py           -> handover
    freecad.py       -> emits a script for vm-setup, on demand only
  views/
    electrical.py  cooling.py  security.py  fire.py
```

### What the engine actually does

**Site model.** Boundary, grid, levels, rooms, zones. A hall is a room with a
pitch and a row/aisle convention, because that is what makes rack placement
generative rather than manual.

**Placement with constraints.** Position and rotation of catalogue instances,
checked against: clearance envelopes overlapping, equipment overlapping, access
routes blocked, floor loading exceeded. Constraint violations are *reported, not
prevented* — an engineer needs to see a clash before deciding, and a hard block
teaches nothing.

**Auto-connect.** The step that earns the whole design. Given a `power` port on a
CRAH and a spare way on a PTU, the engine posts to `cable-sizing`
`/api/size/batch` with the real route lengths taken from the layout, and writes
the returned cables back into the IR as connections. Same for pipe ports via
`piping` `/api/route`, and tray fill via `cable-tray-ezystrut` `/api/fill`.

Those three components already do the work; this is the wiring that makes them
useful together. Per §1a it is HTTP and batched, not direct import — and if a
service is down, the connections come back marked unsized rather than guessed.

### The 2D tool

Plain SVG and vanilla JS, per your call. Scope for W1, deliberately small:

- pan/zoom, snap-to-grid, metric dimensions
- palette grouped by catalogue taxonomy, drag to place
- select, move, rotate in 90° steps, delete, duplicate
- property panel showing the catalogue entry, with provenance visible
- clearance envelopes drawn as hatched overlays, clashes in red
- rooms and zones as editable polygons
- export/import IR

Not in W1: curves, arbitrary rotation, multi-level editing, undo trees. A flat
undo stack is enough. Accept that this is ~1500 lines of JS before it feels
good — that was the known cost of the zero-dependency choice.

---

## 3. Catalogue crawlers (`dc-model/`)

Reuse the existing platform. `collector/` already has politeness, a SQLite
frontier, a content-addressed S3 store, conditional GET and four adapter
strategies (`sitemap_static`, `url_list`, `abb_library`, `html_links`).
`portals.yaml` already holds scouted rows for most vendors named below.

### 3.0 The crawlers belong to DC-1, not to the catalogue

Worth being explicit, because it changes where this code should live. The
existing crawlers were built to feed the **drawing LLM** — they collect *documents
and drawings as training data*. The catalogue needs something different: *typed
equipment specifications*. Same acquisition machinery, different product.

That argues for a three-way split:

```
  collector/          ─ generic, reusable: politeness, frontier, S3, adapters
       ├──▶ dc-model/     training corpus     (documents, drawings, DXF, evals)
       └──▶ catalogue/    equipment specs     (typed YAML entries, per §0.1)
```

Two consequences:

- **`collector/` should be extracted** into a shared library that both consumers
  import, rather than living inside `dc-model/`. It is the only part that is
  genuinely common.
- **`dc-model/` should probably be its own repository.** It carries a training
  corpus of third-party drawings, which is what blocks publication of this repo
  (see `PUBLISH-REVIEW.md`). Splitting it solves the licensing problem and the
  conceptual one in the same move: this repo becomes the engineering toolkit,
  `dc-model` becomes the ML project that consumes it.

Do the extraction of `collector/` before W3 starts, while there is one consumer
and the interface is cheap to change.

**The missing layer is extraction, not collection.** Getting the PDF is largely
solved. Turning page 3 of a Vertiv datasheet into a validated catalogue entry is
not. That is the work.

### 3.1 Extraction pipeline

```
S3 doc (sha256)
   └─▶ classify        which category, which vendor, is it a datasheet
       └─▶ locate      which page holds the dimensional/rating table
           └─▶ extract  vision model -> candidate fields
               └─▶ validate  schema + unit + plausibility checks
                   └─▶ catalogue/<category>/<vendor>-<model>.yaml
                       provenance: verified=false, fields_verified=[]
```

`dc-model` already has the first two steps in usable form:
`tools/classify_pdfs.py`, the `drawing-locate` eval suite, and
`batch_extract.py` recovering vector geometry to DXF with a text-span sidecar.
The DXF plus positioned text is a better extraction substrate than raw PDF,
because a dimension line and its label arrive already associated.

**Nothing is verified by extraction alone.** Entries land `verified: false`. A
field moves to `fields_verified` only when a human confirms it or two independent
sources agree. The existing `drawing-locate` eval framework is the right place to
measure extraction accuracy per field, per category.

### 3.2 Wave order

You asked for all four groups. Sequenced by dependency rather than preference:

**W3a — IT load.** Sets the heat and power profile everything else is sized
from, so it comes first. GPU servers, IT pods, GPU networking.
Vendors: NVIDIA (adapter partly exists — `collect-nvidia-docs` is live),
Supermicro, Dell, HPE, Lenovo, OCP; Arista, Cisco, Juniper for networking.
The OCP specification archive is the highest-value target here — open licence,
structured, and it documents rack and pod geometry rather than just servers.

**W3b — Cooling**, parallel with W3c. Feeds CFD and the twin, which are the
components that already model behaviour, so payoff is immediate.
CRAC/CRAH: Vertiv, Stulz, Munters. Chillers: Carrier, Trane, Daikin, JCI/York.
Munters (`datacenter.munters.com/products/`) is scouted and **blocked at the
edge** — robots.txt permits `/products/`, Cloudflare returns 403 to every
automated client including a real browser. Row `munters-datacenter` in
`portals.yaml`, marked DO-NOT-SCHEDULE. It needs a commercial route, not a
technical one.
CDUs: Vertiv, Motivair, CoolIT, Boyd, Schneider.
Watch for: part-load curves and approach temperatures are the fields the twin
needs and the ones least likely to be in a clean table.

**W3c — Electrical spine.** Feeds `cable-sizing`, which is mature and can
consume it the day it lands. HV/MV transformers and switchgear: ABB, Siemens
Energy, Hitachi Energy, Schneider, Eaton. LV switchgear: same set. PTUs:
Vertiv, Schneider, Eaton, Starline.
PTUs are the weakest scouted group in `portals.yaml` — expect a recon pass first.

**W3d — Standby power.** Best-scouted group already (5 genset + 5 BESS vendors
verified), so it is the fastest to land and therefore last, not first.
Gensets: Cummins, Caterpillar, Rehlko, Rolls-Royce mtu, Generac.
UPS: Schneider/APC, Eaton, Vertiv. BESS: Tesla, Fluence, Sungrow, Wärtsilä.

### 3.3 Start with the drive, not the crawler

`dc-model/CORPUS.md` established the pattern once already: *"you already hold the
corpus the recon said was hard to get"*, and it changed the build order. Repeat
it. Before any new adapter, inventory what is on drive and in SharePoint per
category, extract from that, and crawl only the gaps. Cheaper, faster, and no
terms-of-use question.

### 3.4 Terms of use

`portals.yaml` records a `tos_stance` per source and 19 of 45 rows are still
`unknown`, which is currently blocking gate G0. Vendor datasheets are
copyrighted; collection here is internal engineering use as a customer.
Keep the existing discipline: record the stance, quote the clause, no account
creation, no defeating login walls or rate limits. Where CAD or BIM sits behind
registration, note the wall and stop.

`tools/record_tos_stance.py` already enforces this — it refuses a positive stance
with no quoted clause, and refuses any stance without the URL that was read. Use
it rather than editing `portals.yaml` by hand.

---

## 4. Geometry and the twin

Per your call: glTF and IFC direct, FreeCAD optional.

**glTF is the twin path.** `compile/gltf.py` emits envelopes plus zone metadata.
The `digital-twin/viewer/` already has a geometry pipeline and vendored deps, so
this lands as a new loader rather than a new app.

**IFC is the handover path.** Real interop with the consultants who will
eventually take a design forward. Use IfcSpace for rooms/zones and
IfcDistributionElement subtypes for equipment, so the classification survives
export.

**FreeCAD stays for detail, on demand.** `compile/freecad.py` emits a script for
`vm-setup` when someone wants STEP, real piping solids from `piping/`, or tray
geometry from `cable-tray-ezystrut/`. Keeping it out of the iteration loop is the
whole point — headless FreeCAD is too slow and too fragile to sit in a design
loop, and both of those are load-bearing reasons rather than preferences.

**Generalising the twin.** `digital-twin/` is currently AU01-specific: a ROM
calibrated against one CFD case. Driving it from an arbitrary compiled layout is
a real piece of work, not a config change. The honest path:

1. Compile layout → zones + heat sources + air paths (mechanical, not thermal)
2. Fit the ROM per zone from a small CFD case set, the way AU01 was fitted
3. Only then claim the twin runs an arbitrary hall

Step 2 is the expensive one and it is per-topology, not per-layout. Expect the
first generalisation to cover one archetype — contained hot aisle with a fan
wall — and to need a new CFD campaign for each further archetype.

---

## 5. The four views

Views read the IR and the catalogue. They do not own geometry, and they are how
the toolkit earns the phrase "model how it will run".

### 5.1 Electrical

Mostly assembly of things that already work.

- One-line diagram generated from the connection graph
- Cable schedule via `cable-sizing`, using real route lengths from the layout
- Load flow and diversity roll-up: rack → PTU → LV board → transformer
- Fault level propagation, and selectivity between upstream and downstream devices
- N+1 / 2N redundancy checks: does every load have two independent paths, and
  does either path alone carry it
- Tray fill and loading via `cable-tray-ezystrut`

The harmonics work already done in `cable-sizing` (AS/NZS 3000 clause 3.5.2,
neutral sizing, and the finding that a delta primary traps triplens but passes
5th/7th) belongs in this view as a transformer-level check.

### 5.2 Cooling

- Heat map by zone from IT load in the layout
- CFD case generation: compile a hall into an OpenFOAM case for
  `cfd-cabinet-cooling`, replacing the hand-built `case-au01`/`case-hall` dicts
- Twin drive: zones, heat sources and air paths as in §4
- Capacity check per CRAH/CDU/chiller against connected load, with N+1
- Water-side: flow, ΔT and DN sizing through `piping/`

### 5.3 Security

New ground for this repo. Deliberately modest first pass — geometric checks, not
a security design.

- Zone model: public → reception → office → white space → plant, with a tier per
  zone and required transitions between them
- Access control points on zone boundaries; flag any boundary crossed without one
- Camera placement with 2D field-of-view cones and coverage gaps on boundaries
  and door lines
- Clear zones and standoff to site boundary
- Man-trap / airlock presence on the white-space boundary

Standards to confirm before any of this is quoted, not asserted from memory:
Uptime Institute tier requirements for physical security, ISO/IEC 27001 Annex A
physical controls, and for government work the SCEC/ASIO T4 material. Treat all
of these as unverified until read, per the repo's practice.

### 5.4 Fire protection

Same posture: geometric and topological checks first.

- Detection zones and coverage, including aspirating/VESDA sampling pipe runs in
  white space and containment
- Suppression zones: which agent where, and volume per zone for gaseous systems
- Compartmentation: fire-rated boundaries, penetrations where a tray or pipe
  crosses one — this is the check that most obviously needs the layout
- Egress: travel distance, dead ends, exit width against occupancy
- Interaction with cooling: containment and hot-aisle ceilings versus detection
  and sprinkler throw, and mechanical shutdown on alarm

Australian standards to verify before use: AS 1670 (detection and alarm), AS 2118
(sprinklers), AS 2419 (hydrants), AS ISO 14520 (gaseous agents), and the NCC. I
have not read these; they are named as targets for a capture pass of the kind
already done for AS/NZS 3000:2018 in `cable-sizing/EXTRACTED-TABLES.md`, and
nothing should be quoted from them until that pass is done.

---

## 6. Risks

**The schema is wrong in a way that surfaces late.** Highest-consequence risk.
Mitigated by W0/W1 ordering: hand-seed and drive the full loop before crawling.
Accept one deliberate schema break after W1 and version it from the start.

**Extraction accuracy is category-dependent.** Envelopes and weights extract
well; part-load curves, approach temperatures and impedance tables do not.
Measure per field with the existing eval framework, publish the numbers, and
leave low-accuracy fields `verified: false` rather than filling them badly.
`dc-model/RESUME.md` already keeps a quotable/not-quotable split — extend it.

**Twin generalisation is under-estimated.** §4 sets out why. The realistic
outcome for this phase is one archetype, not arbitrary halls.

**Scope of the views.** Security and fire are whole engineering disciplines. What
is proposed is a set of geometric checks that catch obvious errors early — not a
design, and not a compliance certificate. Say so in the output of every view, the
way `cable-sizing` does.

**The 2D tool grows without limit.** Every engineer will want one more feature.
Hold the W1 scope list; put anything else behind a gate that requires the loop to
be working end to end first.

**The service separation gets undone the first time it is slow.** Someone will
hit a slow auto-connect and fix it with a direct import, and the components stop
being independent. Two mitigations: ship the batch endpoints in the same change
as the single-item ones so the fast path exists from day one, and add a test that
runs the layout engine against *live HTTP services only*, with the direct-import
path unavailable. If that test passes, the separation is real.

**Existing filesystem coupling is technical debt with a deadline.**
`cable-sizing` reading `../cables/cable_catalog.json` and `digital-twin` reading
`../cfd-cabinet-cooling/geometry/` both have to go before either component can be
deployed alone. Cheapest while there are two consumers, not eight.

---

## 7. First four things

1. Write `layout/schema/catalogue.schema.json` and `ir.schema.json`. Align the IR
   with `dc-model/DESIGN.md` §2 rather than inventing one.
2. Hand-write 20 catalogue entries from datasheets already on drive — spread
   across all four groups so the schema meets a chiller, a switchboard, a GPU
   server and a genset before it is fixed.
3. Wrap `cables` as a service: `service.py`, `server.py`, `/api/health`,
   `/api/meta`, `/api/cables`. Then cut `cable-sizing` over to reading it via
   `sddc_client.py` instead of `../cables/cable_catalog.json`. Small, and it
   proves the §1a pattern on the one dependency that already exists — before
   `layout` adds five more.
4. Build `layout/ui.html` far enough to place those 20 and export IR. Nothing
   else until that round-trips.
