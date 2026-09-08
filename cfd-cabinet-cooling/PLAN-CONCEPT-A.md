# PLAN — Concept A cooling verification (AU013-143)

Handoff plan for the hall CFD. Objective: decide whether the as-drawn cooling
system — **one FWCV 40L2 per end, each = 2 stacked 40L1 modules** — holds the
concept-A load inside the ASHRAE A2 envelope in normal operation and in the two
degraded cases (module fault, whole-unit water isolation), and quantify the
operational response the maintenance case needs.

Everything below runs in `sd-dc/cfd-cabinet-cooling` on the existing
`case-hall` machinery. Do not rebuild what exists; the generator already
supports everything in Phases 0 and 3.

---

## 0. Baseline configuration (already supported — set, don't code)

`case-hall/system/hallParameters`, exact values:

| Parameter | Value | Basis |
|---|---|---|
| hallWidth | 8.2 | clear width between wall faces (8,350 grid − 2×75 wall) |
| sideAisle | 1.4 | south cold aisle per building model; north aisle becomes the remainder (~2.6) automatically |
| plenumFloorZ | 4.0 | unit height |
| plenumHeight | 0 | **AU01 has no ceiling plenum** — open-room return above containment; zTop = 4.0 (eave ~4.09) |
| unitWidth / unitDepth / unitHeight | 4.0 / 1.6 / 4.0 | 40L2 |
| nUnitsPerEnd | 1 | one 40L2 per end |
| modulesPerUnit | 2 | the L2 is 2 stacked 40L1 modules; patches A1/B1 = lower, A2/B2 = upper |
| supplyZ0 / supplyZ1 | 0.2 / 1.9 | discharge window PER MODULE, from module base |
| unitAirflow_m3h | 62500 | per 40L1 module (brochure) |
| unitCapacity_kW | 237.5 | per module (brochure, RAT 37 °C / EWT-LWT 20/30 — chilled water loop, no derate) |
| intakeSide / rearGap | rear / 1.6 | service-corridor return per FWCV brochure p.4 |
| supplyTemp_C | 28.0 | design supply; A2 allowable envelope by choice |
| nRacksPerRow / rackPitch | 12 / 0.6 | 24 positions |
| rackDepth / rackHeight | 1.2 / 2.0 | rack open face; hotAisleWidth 1.8 per building model |
| containmentGap | 0.1 | unsealed strip below 4.0 (with sealEndDoors 1 the end doors are full height) |
| endBulkhead / sealEndDoors | 1 / 1 | carry forward from the current fix-under-test set |
| allowableMax_C / recommendedMax_C | 35.0 / 27.0 | ASHRAE A2 (matches B300 HGX air-cooled envelope) |
| serverDeltaT_K | 15.0 | baseline; see the ΔT sensitivity in Phase 3 |
| cellSize | 0.10 for the matrix, 0.05 for confirmation runs | see Phase 4 |

Note the grid rule: every plane must land on a multiple of cellSize — the
generator hard-stops if not.

## 1. Per-rack loads (code change — port from the row case)

The hall generator currently takes one uniform `rackLoad_kW`. Port the row
case's `row_loads.csv` mechanism (`make_row_dicts.py::read_loads`) to
`make_hall_dicts.py` as `case-hall/hall_loads.csv` with columns
`rack,kW` (rack = A01…B12). Any rack not listed keeps `rackLoad_kW`.
A 0 kW rack keeps its fan source (network/storage gear still moves air) unless
`kW` and a new optional `fanVel` column are both 0 — simplest: keep the fan
source at the velocity implied by each rack's own load and `serverDeltaT_K`
(load-proportional airflow), which also fixes the current uniform-velocity
approximation. Derive per-rack `fanSu` from that rack's kW.

Concept-A load map (embodies the placement rule: heavy air mid-row, light/spare
at the ends). Totals must reproduce 741.8 kW air:

| Rack | kW | | Rack | kW |
|---|---|---|---|---|
| A01 | 0 (spare) | | B01 | 0 (spare) |
| A02–A05 | 36.75 (B300) | | B02–B05 | 36.75 (B300) |
| A06 | 40 (IB leaf) | | B06 | 40 (IB leaf) |
| A07 | 45 (IB spine) | | B07 | 13.8 (N/S eth) |
| A08–A11 | 36.75 (B300) | | B08–B11 | 36.75 (B300) |
| A12 | 15 (storage) | | B12 | 0 (spare) |

Check: 16 × 36.75 + 2 × 40 + 45 + 13.8 + 15 = 741.8 kW. Print the total in the
generator report and abort if it differs from the CSV sum.

## 2. Window-averaged metrics (code change — small)

Per MODEL-REVIEW.md the solver plateaus without converging and face peaks
oscillate ±0.8–1.4 K; last-iteration sampling is not reproducible. In
`plot_hall.py` (and `build_report_hall.py` via the shared helper): replace
`final()` with `windowed(case, fo, n=500)` returning (mean over the last 500
iterations, max over the window for `*_inletTmax`). Verdicts use windowed mean
for the mean-intake test and windowed max for the peak test. Keep `final()`
for backwards compatibility.

## 3. Run matrix

All runs identical except the named parameters. `unitsOff` changes are
BC-only — same mesh, so runs R1–R3 can restart from R0's converged field
(`startFrom latestTime` after copying the case) to cut solve time.

| Run | unitsOff | supplyTemp_C | serverDeltaT_K | Question |
|---|---|---|---|---|
| R0 | — | 28 | 15 | Baseline: does the as-drawn system pass A2 with concept-A loads? |
| R0-dT20 | — | 28 | 20 | Airflow-demand sensitivity (if B300 air side runs ΔT 20, margins relax everywhere) |
| R1a | A1 | 28 | 15 | **Fault: lower module of the west unit out** (712.5 kW, supply/demand ~1.06) |
| R1b | A2 | 28 | 15 | Fault: upper module out — stratification differs from R1a; report the worse of the pair |
| R2 | A1,A2 | 28 | 15 | **Maintenance: whole west 40L2 isolated** (475 kW, supply/demand ~0.71) — expected to breach; establishes the unmitigated picture |
| R2-s26 | A1,A2 | 26 | 15 | Maintenance + setpoint drop, step 1 |
| R2-s24 | A1,A2 | 24 | 15 | Maintenance + setpoint drop, step 2 — find the setpoint (or residual load cap) that brings the worst windowed peak ≤ 35 °C |

West end (A-end) is the failure side of record: it is nearer the heavy A07
spine and, in the building, the pod CDU bay sits in FW-A's discharge (see
Phase 5). If R1a/R1b pass with margin, a B-end repeat is not required.

Optional R3 (only if R2-s24 still fails): R2 conditions with the 16 B300 racks
reduced to 30 kW air each (GPU pause proxy, −108 kW) — quantifies the load-shed
alternative to setpoint.

## 4. Mesh and compute

- Matrix at `cellSize 0.10` (~1.0 M cells, minutes per run locally) to rank
  scenarios and find the R2 mitigation point.
- Confirmation at `cellSize 0.05` (~5.8 M cells at zTop 4.0) for R0 and the
  worst passing degraded case only. Use the remote box per COMPUTE-OPTIONS.md;
  keep `writeFormat binary`.
- Same solver settings as current case-hall (buoyantSimpleFoam, k-ω SST,
  4,000 iterations). Do not stop early on residuals — the plateau is expected;
  the windowed metrics handle it.

## 5. CDU bay obstruction (code change — small, do before the 0.05 runs)

The building model places the pod CDU bay (2 rack-size CDUs + manifold)
1.84 m in front of FW-A, directly upstream of the west end racks. Add a
generic solid-obstacle mechanism: `obstacles` entries in hallParameters
(`obstacle x0 y0 z0 x1 y1 z1`, repeatable) that subtract cells the same way
the unit banks do. Concept-A values, in case coordinates (podX0 − 1.5 to
podX0 − 0.7 in x, rows A and B y-bands, z 0–2.0):
two boxes `[podX0−1.5, podX0−0.7] × [rowAy0, rowAy1] × [0, 2.0]` and the same
at the row-B band. Run R0 and the worst degraded case with and without —
the delta is the "move the CDU bay?" answer for the layout ticket.

## 6. Acceptance criteria

1. `checkMesh` clean, zero `empty` patches, every run.
2. Mass loop closes: Σ|supply patches| = Σ|return patches| within 1 %;
   stopped modules carry < 0.5 % of a running module's flow.
3. Energy closes within 2 %: Σ(rack kW) vs total supply × cp × (windowed
   return T − supply T).
4. Per-rack table reports **windowed** mean and peak; verdict per rack against
   A2 (mean ≤ 35 = pass; windowed peak > 35 = flag the rack).
5. R0 must PASS outright for concept A to stand.
6. R1a/R1b: report as the fault case — target PASS on mean with peaks ≤ 35;
   MARGINAL acceptable if breaches are confined to windowed peaks on ≤ 2 racks
   and quantified.
7. R2 series: identify the minimum mitigation (setpoint and/or load) with the
   worst windowed peak ≤ 35 — this number goes to the ticket as the
   maintenance procedure requirement.
8. Deliverables: updated `report-hall.html` per run (or one comparative
   report), `runs/` CSV of scenario → worst mean / worst peak / bypass
   fraction / per-module flows, and a closing comment on AU013-143 with the
   three verdicts and the R2 mitigation number.

## 7. Facts the runs must respect (do not re-litigate)

- L2 = 2 stacked L1 modules; module has own fans + CW valve; the L2 has ONE
  water IN/OUT — hence R1 (module) vs R2 (whole unit) are distinct real cases.
- All coolers on the chilled water loop; 20/30 EWT/LWT available; no derate.
- Airflow figures are per module: 62,500 m³/h (40L1).
- Supply at 28 °C is above the 27 °C recommended limit by design; the working
  envelope is A2 allowable 35 °C.
- The fan model undershoots its target ~7 % at stiffness 50 (documented); do
  not tune it mid-study. A stiffness sensitivity is out of scope here.

## 8. Open inputs (chase in parallel, do not block)

1. B300 HGX air-side ΔT / airflow per rack from vendor data — replaces the
   15/20 K assumption; rerun R0 only if it lands outside 15–20 K.
2. Schneider: per-module water isolation valves as an option on the L2 (if
   yes, R2 collapses into R1 and the maintenance procedure shrinks).
3. Schneider: available airflow above the 70 Pa rating point (extra margin in
   degraded cases if the remaining modules can overspeed).
