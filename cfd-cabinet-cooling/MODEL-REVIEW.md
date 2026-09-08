# Cabinet cooling CFD — accuracy review

Review of `cfd-cabinet-cooling` (2D/row case + two-row hall case), 18 Aug 2026.
Method: independent recomputation of every derived quantity in
`simulationParameters` / `hallParameters` / the two dict generators; line-by-line
check of the generated OpenFOAM dictionaries, BCs and function objects; per-rack
report values re-derived from the raw `postProcessing/*.dat` files; convergence
and oscillation analysis of the hall run (`log.buoyantSimpleFoam`, iterations
2000–4000).

## Verdict

The model is sound. Solver choice, thermophysics, boundary conditions, source
terms, mesh construction and the balance checks are all correct, and every
report number that could be re-derived from raw data was reproduced exactly.
The items below are, in order: two findings that affect how far the hall
numbers can be trusted, one real (minor) code bug, and a set of documentation
inconsistencies. Nothing invalidates the headline findings.

## Verified correct

| Check | Result |
|---|---|
| Mesh cell counts | 2D 107,520 · 4-cab 430,080 · hall 184×76×56 − 2×25,600 = 731,904 — all reproduce exactly |
| Hall checkMesh | non-ortho 0, skew 2.1e-13, patch areas: supply 1,440 faces = 14.4 m² (4.0 × 3.6), intake 640 = 6.4 m², rack inlet 132 = 1.32 m² per rack — all match geometry |
| Rack demand (hall) | 36 kW / (1005 × 15) = 2.388 kg/s; ρ at 35.5 °C = 1.1436; U = 2.388/(1.1436 × 1.32) = 1.582 m/s; fan Su = 79.09 — matches generated `fvOptions` |
| Supply (hall) | 130,000 m³/h / 3600 / 14.4 m² = 2.5077 m/s — matches `0.orig/U`; measured 42.42 kg/s per unit, both units within 0.001 kg/s of each other |
| Mass loop closure (hall) | supply 84.83 kg/s vs return 42.3 + 42.4 kg/s — closed |
| Energy balance (hall) | 84.83 × 1005 × (311.30 − 301.15 K) = 865 kW vs 864 kW imposed — closes to ~0.1 % |
| Energy balance (row) | 1.847 × 1005 × 16.02 = 29.74 kW vs 30 kW — ~1 % as documented |
| Per-rack report table | all 19 racks whose raw `.dat` files predate the re-run in progress match `report-hall.html` to the last digit (A00–A11, B00–B06) |
| Report derived stats | ΔT 864/(70.2 × 1.005) = 12.25 K ✓ · return 38.14 °C ✓ · capacity 91 % ✓ · end-rack flow 2.48 vs mid 3.01 kg/s = 18 % ✓ · headroom 32 − 29.27 = 2.73 K ✓ |
| Fan-power claims (RESULTS.md) | (1.83/1.41)³ = 2.19 ≈ "2.2×" ✓ · (1.41/1.29)³ = 1.31 ≈ "1.3×" ✓ |
| results.csv vs RESULTS.md | all six sweep rows consistent, % of demand figures reproduce from supply/through columns |
| ASHRAE A1 thresholds | 27 °C recommended / 32 °C allowable — correct |
| Verification record | Phase 1/2/3 arithmetic checks out (4× scaling exact; the volumeMode-absolute bug and its fix are real and correctly described) |
| Sign conventions | `containmentGap` flip against `hotAisleCells`, per-rack `inlet_*` flip against `rackCells` — orientations correct; the `empty`-patch guard in both Allruns is present and the hall boundary file check passes |

## Finding 1 — hall metrics are last-iteration snapshots of an oscillating solve

The hall run never met `residualControl` (p_rgh 1e-4); it ran to the 4,000
iteration cap with p_rgh initial residual plateaued at ~0.077. That plateau is
the usual signature of a buoyant case with no truly steady solution — the plume
and the supply jets flap. Over iterations 3500–4000 the per-rack **means** move
only ±0.05–0.3 K and rack **flows** ±0.05–0.27 kg/s, but the face **peaks**
oscillate ±0.85–1.4 K. Over iterations 2000–4000, B00's peak ranges 31.5–34.8 °C
and A00's 32.2–34.2 °C.

Consequences:

- The MARGINAL verdict itself is robust — peaks at the end racks cross 32 °C
  repeatedly and the means never approach it.
- The specific published numbers "3 rack faces above 32 °C, worst B11 at
  33.54 °C" are a snapshot: at another stopping iteration the count is anywhere
  from ~2 to ~6 and the worst rack shuffles between A00/B00/B11.
- `plot_hall.final()` takes the last row of each `.dat`. Averaging the last
  ~500 iterations (and reporting the max-over-window for peaks) would make the
  report reproducible run-to-run at zero compute cost. The row case is not
  affected — its metrics genuinely flatten.

## Finding 2 — resolution and model choices that the end-rack finding leans on

The headline hall finding (end racks starved and hottest, corners leak) is
plausible and internally consistent, but three modelling choices all act on
exactly that region:

1. **The containment gap is one cell tall.** `containmentGap 0.1` m at
   `cellSize 0.10`. The bypass carries ~14.6 kg/s (~12 m³/s) through a
   single-cell slit (~1.68 m² total) at ~7 m/s mean. Leak distribution around
   the perimeter — the mechanism blamed for the corner hot spots — is at the
   floor of what one cell can represent. Worth one run at `cellSize 0.05`
   (~5.9 M cells; feasible per COMPUTE-OPTIONS) or with the gap ≥ 2 cells.
2. **Peaks are single-face maxima** on 0.01 m² faces of a 100 mm mesh; the
   quantity that decides MARGINAL vs PASS is the least mesh-converged number in
   the case. (Same remedy as above; or report a high percentile alongside max.)
3. **Racks have no flow resistance.** The proportional fan source
   (stiffness 50) lets room pressure push rack flow 4–46 % above the 2.388 kg/s
   target (2.46–3.49 kg/s across racks; achieved ΔT 12.25 K vs 15 K nameplate).
   Real racks — fan curves plus door/server resistance — sit much stiffer, so
   the 35 % rack-to-rack airflow spread is likely overstated and the end-rack
   airflow deficit somewhat exaggerated. A stiffness sensitivity (e.g. 50 →
   200 → 1000) would bound this cheaply. The same applies in milder form to the
   row case (1.85 kg/s achieved vs 2.0 target, i.e. ~7 % proportional droop).

Also inherited by both cases and already documented: uniform supply patch at
exactly rated airflow. Two FWCV units at 100 % of 130,000 m³/h give
supply/demand = 1.48; real units on VFDs would turn down, which changes the
bypass fraction and possibly the end-rack picture. A `unitAirflow_m3h` sweep is
the natural next study and needs no code changes.

## Bugs (minor, reporting only)

1. `plot_hall.py` FAIL branch: prints `rack {wpk_row}{worst % n:02d}` — row
   letter comes from the worst **peak**, index from the worst **mean**. Wrong
   rack named whenever they differ. Use `worst_row`.
2. `plot_hall.py` line ~148: `dT = 864000.0 / (sum(allf) * CP)` — hardcoded
   load; silently wrong if `rackLoad_kW` or `nRacksPerRow` changes. Use
   `load * 1000`.
3. `build_report_hall.py` "end vs mid" stat block: temperatures compare
   worst-end vs worst-mid (max), airflow compares averages, all presented in
   one grid that reads as like-for-like. Label or unify.
4. Exit-code convention differs: `plot_metrics.py` exits non-zero on anything
   but clean PASS; `plot_hall.py` exits 0 on MARGINAL. Fine if intended, but
   they gate differently in scripts.

## Documentation drift

- README says `fanWallVelocity 1.41 ≈ 110 % of server demand`;
  `simulationParameters` says `1.41 == 100 % of the server airflow demand`.
  Both are defensible (110 % of converged draw 1.847 kg/s vs 100 % of nameplate
  1.69/1.70 m³/s) but one definition should be picked.
- README "converged baseline: 1.89 kg/s, 15.6 K rise" is stale — the current
  baseline is 1.847 kg/s / 16.02 K (results.csv and README's own verification
  section).
- README still says "the dictionaries derive `rowHeatLoad = nCabinets ×
  heatLoad` for the source term" — superseded by per-cabinet sources from
  `make_row_dicts.py`; `rowHeatLoad` is now a dead parameter (and
  `fvOptions.aggregate.bak` is a leftover).
- `build_report_hall.py` hardcodes `2.51 m/s`, `0.1 m`, `864` in prose —
  parameter drift risk if `hallParameters` changes.
- RESULTS.md "air arrives back at the unit intake at 33.7 °C": a simple mixing
  estimate from the same table gives ~34.7 °C; if 33.7 is the measured
  `intakeT`, fine, but worth a re-read of the dat file when convenient.

## Input data not verifiable here

FWCV is a real Schneider/Uniflair front-flow chilled-water fan wall line
(200–500 kW), but the specific "40L2 = 475 kW net sensible, 130,000 m³/h,
4000 × 1600 × 4000, RAT 37 °C / EWT-LWT 20/30" figures could not be confirmed
against the public page (specs live in the datasheet PDF). Since supply
velocity, capacity margin and the RAT comparison all trace to these numbers,
keep the datasheet reference with the case. Note also the modelled return
(38.1 °C) sits above the 37 °C rated RAT, and the 28 °C supply assumption is
~2 K warmer than the SAT the rated point implies — conservative on supply,
slightly beyond rating on return.

## Open items suggested

1. Window-average the hall metrics in `plot_hall.py` / `build_report_hall.py`
   (last ~500 iterations) instead of last-sample; re-issue the report.
2. One hall run at `cellSize 0.05` (or gap ≥ 2 cells) to confirm the end-rack /
   corner-leak finding survives refinement.
3. Rack fan stiffness sensitivity (50/200/1000) to bound the airflow-spread
   claim.
4. `unitAirflow_m3h` turndown sweep — the units will not run at rated flow.
5. Fix the two `plot_hall.py` bugs and the README drift above.
