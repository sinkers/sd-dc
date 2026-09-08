# SD-DC — a toolkit for AI-led data centre design

Maintain catalogues of real equipment, use them as building blocks to define a
data centre, then model how it will actually run.

The unit of work is not a drawing. It is a **catalogue entry**, a **sizing
calculation**, or a **simulation** — each one machine-readable, each one carrying
its own provenance, each one verifiable by execution. An agent can select a
cable, route a pipe, size a tray, and predict a hall's thermals without a human
transcribing anything from a PDF.

`SPEC.md` holds the original architectural vision, [`PLAN.md`](PLAN.md) is the
roadmap for the next phase — layout engine, equipment catalogue crawlers, and the
electrical, cooling, security and fire views. This file describes what is
actually built.

---

## Purpose and use

**This is a private study and research project. It is not for commercial use.**

The toolkit exists to explore whether data centre design can be driven
programmatically by AI agents — sizing, routing, and simulating from
machine-readable equipment data rather than by hand in CAD.

### Code open, data private

The split is deliberate and it runs through the whole system:

| | Public | Private |
|---|---|---|
| Engines, schemas, tests, docs | `sd-dc` | |
| Collected vendor documents | | S3 `catalogue/` |
| Standards tables | | S3 `standards/` |
| Source registries and crawlers | | `sddc-collector` |
| Training corpus and DC-1 | | `dc-model` |

This is the posture the established AS/NZS 3008 calculators already take.
Verified 2026-09-04: Tricab's client-side JavaScript contains **no numeric
tables at all** — it posts to a server endpoint — and jCalc's public page cites
table numbers 21 times while publishing none of their contents. The calculator
holds the data; the user gets an answer.

It also makes vendor agreements tractable. "We pull your data and use it, we do
not republish it" is a workable conversation, and it is verifiable rather than a
promise: `redistribute: false` is a field on every source and is stamped into the
provenance of every collected object.

And it is what allows a **single-vendor build** — a Delta-only tool, say — from
the same codebase, with only that vendor's catalogue. See `PLAN.md` §0.1a.

### What that means for vendor data

Equipment catalogues are built from manufacturer documentation, collected for
private study under that purpose. Two rules follow, and both are enforced rather
than merely stated:

- **Documents are never redistributed.** No vendor datasheet, brochure or CAD
  file is published from this repository. They are fetched to a private bucket.
  `catalogue/sources.yaml` records `redistribute: false` per source, and the
  provenance sidecar on every collected object carries it too, so a consumer
  knows the terms without going back to the registry.
- **Transcribed facts are kept, documents are not.** `cable_catalog.json` and
  `tray_catalogue.json` hold dimensions, ratings and load data read out of those
  documents. A dimension is a fact; the document is someone's copyright work.
  Nothing in the code reads the source documents.

Collection is polite by construction: robots.txt and `Content-Signal` are
honoured, rates are deliberately slow, and a machine-readable AI-training refusal
is a hard stop. See `sddc-collector`.

### If you are not us

**A statement of purpose here is not a licence.** It records what this project
is; it does not grant you anything, and it does not change what any vendor's
terms permit.

If you clone this and use it commercially, the vendor data in it is not licensed
to you. Check each source's terms — `catalogue/sources.yaml` records the stance
and quotes the clause — and obtain your own permission. Several vendors publish a
route: Korvest, for instance, offer a Copyright Release Form.

## The three layers

```
   ┌────────────────────────────────────────────────────────────────┐
   │  1. CATALOGUES — what exists                                   │
   │     cables/ · cable-tray-ezystrut/ · dc-model/                 │
   │     Real products, real ratings, tagged with provenance         │
   └───────────────────────────┬────────────────────────────────────┘
                               │  selected by
   ┌───────────────────────────▼────────────────────────────────────┐
   │  2. ENGINEERING — which one, and how it connects               │
   │     cable-sizing/ · piping/ · cooling-model/                   │
   │     Standards-based calculation and geometry generation         │
   └───────────────────────────┬────────────────────────────────────┘
                               │  feeds
   ┌───────────────────────────▼────────────────────────────────────┐
   │  3. SIMULATION — how it will run                               │
   │     cfd-cabinet-cooling/ · digital-twin/                       │
   │     CFD ground truth, then a real-time reduced-order model      │
   └────────────────────────────────────────────────────────────────┘

   Infrastructure: vm-setup/ (headless FreeCAD + XML-RPC + MCP bridge)
```

Layer 1 answers *what can I buy*. Layer 2 answers *what should I use, and does it
comply*. Layer 3 answers *what happens when I switch it on*.

---

## Components

| Component | Layer | What it does | State |
|---|---|---|---|
| [`cables/`](cables/) | Catalogue | Nexans Australia cable catalogue — 3 families, 40 sizes, with OD, weight, bend radius, pulling tension and impedance | Working |
| [`cable-tray-ezystrut/`](cable-tray-ezystrut/) | Catalogue | Ezystrut tray systems — 5 families (ET5, ET3, ET, CT, NEMA3), datasheets, STEP models, joining rules | Working |
| [`dc-model/`](dc-model/) | Catalogue | **Moved to a private repo** — training corpus, DC-1. See the stub for why | External |
| `sddc-collector` | Catalogue | **Separate repo** — polite crawler, content-addressed store. 69 tests, `core.py` 99% | External, public |
| [`cable-sizing/`](cable-sizing/) | Engineering | AS/NZS 3008 cable sizing with full audit trail. REST API, MCP server and browser UI | Mature |
| [`piping/`](piping/) | Engineering | Orthogonal pipe routing with A* obstacle avoidance, generating solid FreeCAD geometry | Working, 3/5 scenarios pass |
| [`cooling-model/`](cooling-model/) | Engineering | Parametric cooling plant and pump skid geometry, exported to STEP/OBJ | Working |
| [`cfd-cabinet-cooling/`](cfd-cabinet-cooling/) | Simulation | OpenFOAM: does a fan wall keep a 30 kW cabinet inside ASHRAE limits? | Working |
| [`digital-twin/`](digital-twin/) | Simulation | Real-time AU01 hall thermals, calibrated against the CFD, streamed to a browser and Unreal | Deployed |
| [`vm-setup/`](vm-setup/) | Infrastructure | Headless FreeCAD VM, XML-RPC server, MCP bridge | Working |

---

## 1. Catalogues

Catalogues are **data, not code** — JSON files that an engine reads. Splitting
them this way means a catalogue can be corrected without touching a calculation,
and a calculation can be validated without a live vendor site.

### `cables/`

Nexans Australia, 16 cable types documented in markdown, 3 with full current
ratings machine-readable in `cable_catalog.json`:

- `XLPE_SDI_CU`, `XLPE_SDI_AL` — single-core XLPE, copper and aluminium
- `LFH_SINGLE` — low fire hazard, 110 °C

Each size carries outer diameter, weight, installation and installed bend radius,
maximum pulling tension, and (for copper) AC/DC resistance and reactance. The
geometry fields exist so that a sizing result feeds straight into tray fill,
tray loading and routing constraints.

### `cable-tray-ezystrut/`

Five tray families with load/span data, plus PDF datasheets, STEP models of
brackets and trapezes, and `JOINING_RULES.md` — the rules that make a generated
tray run buildable rather than merely drawn. `cable_tray_router.py` generates
routes; `joint_reference.html` and `verification/` are generated evidence that
the joints resolve.

### `dc-model/`

The bet that the scarce asset is not data but **verified** data. An acquisition
and extraction platform that turns vendor documentation and real Australian DA
submissions into structured geometry:

- **Acquisition** — polite crawler honouring robots and `Content-Signal`, with
  per-host token buckets, conditional GET, a SQLite frontier and a
  content-addressed S3 store
- **Corpus** — 1,215 documents, SHA-256 addressed
- **Extraction** — vector geometry recovered to DXF plus a JSON sidecar of
  positioned text spans. On vector pages, recall median 95.0%
- **Evals** — two suites, `drawing-read` and `drawing-locate`

`RESUME.md` is the hand-off document and `DESIGN.md` sets out the longer-term
aim: a model that emits *geometry programs* rather than pictures, so output is
verifiable by execution.

---

## 2. Engineering

### `cable-sizing/`

The most developed component, and the template for the rest. Given a source, a
load, a route length and an installation condition, it returns the smallest
compliant cable with every check shown.

Four checks in order: current-carrying capacity after derating, voltage drop,
short-circuit withstand, earth fault loop impedance.

```python
from cable_sizing import Source, Load, Installation, size_feeder

result = size_feeder(
    Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2),
    Load("PDU-A1", kw=250, power_factor=0.95, harmonic_content_pct=55),
    route_length_m=85,
    install=Installation(method="touching", ambient_c=45, n_circuits=4),
)
print(result.summary())
```

Standards covered: AS/NZS 3008.1.1 and 1.2, with AS/NZS 3000:2018 for voltage
drop limits, minimum sizes, neutral sizing and conduit fill; IEC 60364-5-52,
BS 7671 and NEC 310.16 for check-only operation.

Three front ends over one service layer, so a calculation cannot drift between
a browser and an agent:

| Front end | Entry point |
|---|---|
| REST + HTML | `server.py`, described by `openapi.py` |
| MCP (stdio) | `mcp_server.py` — 5 tools, 3 resources. See `MCP.md` |
| Direct | `import cable_sizing` |

302 checks across two suites (`test_cable_sizing.py`, `test_api.py`).

### `piping/`

Routes pipe between plant nozzles using only 90° elbows, on a grid, avoiding
obstacles via A*. Generates solid geometry, not centrelines, and validates that
consecutive parts actually meet. The minimum-segment-length constraint is
enforced because two elbows closer than 2×bend radius cannot be built.

`routing_report.html` is honest about the current state: 5 scenarios, 3 pass.

### `cooling-model/`

Parametric cooling plant and pump skid generation, exported to STEP and OBJ for
downstream use.

---

## 3. Simulation

### `cfd-cabinet-cooling/`

An OpenFOAM case answering one question: does this fan wall deliver enough cold
air to keep a 30 kW cabinet inside ASHRAE limits, and what happens when it
doesn't? A 600 mm cabinet pitch of a contained row, modelled as a slice through
an effectively infinite row with symmetry planes.

Everything runs in Docker. `run.sh` meshes and solves; `plot_metrics.py` gives a
PASS/FAIL verdict with convergence plots.

Generated reports cover the baseline case, the AU01 hall and a 3D verification
record. `FINDINGS-AU01.md` grades every input by confidence, and is explicit
that the server air-side ΔT is assumed rather than published — the weakest link
in the study.

### `digital-twin/`

A reduced-order physics model of the AU01 hall, calibrated against the OpenFOAM
CFD, running faster than real time and streaming state to a browser and an
Unreal scene. Each visitor gets their own hall.

**Live: <https://au01-twin.dametech.net/>**

Two drive modes: manual load, or a synthetic transformer training run with ramp,
sustained grind, checkpoint dips, eval pauses, stragglers and restarts. Three
scenarios ship: `training_run`, `n_minus_one`, `west_fanwall_trip`.

This is the pattern worth repeating — CFD is too slow to sit inside a design
loop, so it becomes the ground truth that calibrates something fast enough to.

---

## Where the large data lives

Meshes and converged CFD solutions are too large for git and are needed by
cluster workers, so they live in S3:

```
s3://$SDDC_ARTIFACTS_BUCKET/
├── cfd/<case>/<git-sha>/     mesh + solution fields + manifest.json
└── geometry/<sha256>/        STL/STEP exports, content-addressed
```

Fetch CFD cases with `cfd-cabinet-cooling/tools/data_pull.sh`, push with
`data_push.sh`. Fetch the licensed standards tables with
`tools/data_pull_standards.sh` — you need your own licensed copy of AS/NZS 3008
and AS/NZS 3000 to use those legitimately.
Workers get read-only access via `tools/iam-worker-readonly.json`.

CFD is keyed by **case + git sha**, because a solution only means anything
against the case dictionaries that produced it. `data_push.sh` refuses to file a
solution under a sha whose dictionaries are modified, and the manifest records
`dictionaries_dirty` so a consumer can tell. Geometry is small and dedupes, so it
gets content-addressing instead.

## Working practice

Four conventions hold across the repo. They exist because an agent consuming
this data cannot tell a measured number from a plausible one unless we say so.

**1. Provenance is a field, not a comment.** Reference data carries a `verified`
flag and a source string. `cable-sizing/reference_tables.json` has 9 verified
tables and 5 unverified; `as3008.verification_report()` prints the status of
each, and the test suite refuses to let a table be marked verified while it still
holds placeholder provenance. `cable-tray-ezystrut/tray_catalogue.json` and
`cable-sizing/as3008_ratings.json` carry the same fields.

**2. Say which numbers are quotable.** `dc-model/RESUME.md` lists quotable
measurements and, separately, numbers that *look* publishable and are wrong, with
the reason. Cheaper than rediscovering it.

**3. Capture records are kept.** When a standard or datasheet is read,
`EXTRACTED-TABLES.md`-style records note what was captured, what was deliberately
not encoded and why, and what remains outstanding.

**4. Verify by execution.** Does the script run, does STEP export, does the pipe
route close, do the clearances pass, do the tests go green. This is what makes
the output trustworthy to an agent, and it is also a reward signal.

---

## Getting started

Most components are standard-library Python 3 and need nothing installed.

```bash
# Cable sizing — no dependencies
cd cable-sizing
python3 test_cable_sizing.py        # 152 checks
python3 server.py                   # REST + UI on localhost
python3 build_status.py && open STATUS.html

# CFD — needs Docker, plus matplotlib on the host
cd cfd-cabinet-cooling
./run.sh && ./plot_metrics.py case

# Digital twin — numpy + websockets
cd digital-twin
pip install -e '.[dev]'

# FreeCAD geometry (piping, cooling-model, tray models)
# needs the headless FreeCAD VM
cd vm-setup && cat INSTALL.md
```

To give an agent cable sizing directly:

```bash
claude mcp add cable-sizing -- python3 "$PWD/cable-sizing/mcp_server.py"
```

---

## Known gaps

- **No layout engine yet.** `SPEC.md` describes a spatial solver that takes a
  `DCSpec` and places equipment. Components exist; the thing that composes them
  into a whole data centre does not.
- **Catalogue coverage is thin against the ambition.** Three cable families and
  five tray families. No generators, UPS, switchgear, transformers, CDUs or racks
  as machine-readable catalogue entries.
- **Cable reactance** is tabulated for one family only; the other 26 of 40 sizes
  fall back to a construction-based nominal.
- **AS/NZS 3000 clause 5.3.3** (earthing conductor sizing) is still unverified,
  and it is the last safety-critical table in `cable-sizing`.
- **`piping/`** fails 2 of its 5 routing scenarios.
- **`k.html`** at the repo root is a stray scraped page, not part of the toolkit.

---

## Safety

Nothing here is a substitute for a standard or for a chartered engineer. The
sizing engines implement published *methodology* and read manufacturer
catalogues; they do not reproduce copyrighted rating tables, and unverified
reference data is labelled as such. Check `verification_report()` and the
component READMEs before anything is issued for construction.
