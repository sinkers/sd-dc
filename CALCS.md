# Calculation register

Every engineering calculation and simulation in this repository: what it
decides, what it runs on, the method or standard it follows, where the formulas
are, where its inputs come from, how it is checked, how to reproduce it, and
what is still open. It is written for a reviewer checking the engineering, not
the software.

Formulas are cited by file and function rather than line, so the pointers
survive edits. "Status" means:

| Status | Meaning |
|---|---|
| **Verified** | Reproduces a published answer (a standard's worked example, a vendor figure) or an independent tool, under test |
| **Calibrated** | Fitted to, and regression-tested against, a higher-fidelity model at stated operating points; not independently verified |
| **Checked** | Closes an energy or mass balance, or a hand calculation, but has no external reference |
| **Placeholder** | Uses typical or assumed values that must be replaced before a number is quoted |

```bash
./run-tests.sh      # every suite below, exactly as CI runs it
```

CI has no licensed data. Suites that need the AS/NZS tables or a vendor
catalogue skip there and must be run locally after
`tools/data_pull_standards.sh` and `tools/data_pull_vendor.sh`
(set `SDDC_ARTIFACTS_BUCKET`).

## Summary

| # | Calculation | Engine | Method | Status |
|---|---|---|---|---|
| [C1](#c1-lv-cable-sizing--reference-engine) | LV cable sizing, reference | Python, stdlib (`cable-sizing/cable_sizing/`) | AS/NZS 3008.1.1:2025, AS/NZS 3000; methodology Rev B | Verified, with open items |
| [C2](#c2-lv-cable-sizing--service-engine) | LV cable sizing, service | Python, stdlib (`cable-sizing/feeder.py`, `as3008.py`) | AS/NZS 3008.1.1, AS/NZS 3000:2018; derived from jCalc | Verified against AS/NZS 3000 App C and ELEK; superseded in method by C1 |
| [C3](#c3-design-current-neutral-and-harmonics) | Design current, neutral, harmonics | Python, stdlib (`cable-sizing/design_current.py`) | Methodology S3 Rev B; AS/NZS 3000 cl. 3.5.2 | Checked |
| [C4](#c4-cable-tray-span-supports-and-cables-on-the-tray) | Tray span, supports, cables on a tray | Python (`trays/`), sizing by C2 | Vendor load tables; C2 | Checked; vendor data withheld |
| [C5](#c5-pipe-routing-and-pipe-specification) | Pipe routing and pipe specification | Python (`piping/core/`), FreeCAD for solids | Orthogonal A*, Sch 10S table, ASME B16.9 long radius | Checked (geometry rules) |
| [C6](#c6-air-cooling-cfd) | Air cooling CFD | OpenFOAM v2406 (Docker) | RANS, k-ω SST, buoyant; ASHRAE TC9.9 | Checked; no mesh independence |
| [C7](#c7-hall-thermal-digital-twin) | Hall thermal reduced-order model | Python, numpy; scipy to calibrate (`digital-twin/`) | 58-state lumped model, RK2 | Calibrated to C6 at one point |
| [C8](#c8-liquid-cooling-hydraulics-and-plant) | Liquid cooling hydraulics and plant | Python, numpy (`liquid-twin/`) | Darcy–Weisbach, Newton network solve, ε-NTU | Checked; some inputs placeholder |
| [C9](#c9-power-and-demand-response-simulation) | Grid, BESS, UPS, GPU load, demand response | Python, stdlib (`power-sim/`) | Energy balance per step; DP dispatch | Not on main yet (PR #3) |

No commercial solver or power-systems package is used. Only C6 runs on an
established third-party solver; C1–C5 and C7–C9 are this repository's own code.

---

## C1. LV cable sizing — reference engine

**Decides** the smallest conductor (and parallel runs, neutral, PE) for a
circuit that passes every check, and records why.

**Engine.** `cable-sizing/cable_sizing/`, standard library only. Entry point
`select_conductor.select()`. Example: `cable-sizing/example_cable_sizing.py`.

**Method.** `cable-sizing/METHODOLOGY.md` (Rev A), with Section 3 and Section 4
at Rev B (`METHODOLOGY-S3-RevB.md`, `METHODOLOGY-S4-RevB.md`). Every figure in
Section 4 is marked with its source class (table value, clause rule, published
answer, DAME convention, third-party cross-check). The order of checks is
Section 2 of the methodology: design current, device, rating factors,
capacity, voltage drop, short circuit, earth fault loop, PE, neutral.

| Step | Where |
|---|---|
| Base rating table selection (R-TBL-1) | `schema.base_table`, `schema.arrangements_for` |
| Rating factors: ambient, grouping (Table 3.34 by support type), depth, soil, harmonics | `rating_factors.build_factor_set`, `rating_factors.admit`, `rating_factors.harmonic_treatment` |
| Current-carrying capacity, I_b ≤ I_n ≤ I_z | `current_capacity.capacity`, `current_capacity.check_capacity` |
| Voltage drop from R and X at operating temperature | `voltage_drop.voltage_drop`, `voltage_drop.mv_per_a_m`, `voltage_drop.operating_temperature_c` |
| Short-circuit withstand, k from Table 5.2 limits | `short_circuit.k_factor`, `short_circuit.minimum_size`, `short_circuit.check` |
| Earth fault loop impedance, PE minimum | `earth_fault.loop_impedance_ohm`, `earth_fault.pe_minimum_size`, `earth_fault.check` |

**Inputs.** AS/NZS 3008.1.1:2025 and AS/NZS 3000 tables as CSV in
`cable-sizing/data/`. Licensed; not in git. `python3 -m cable_sizing.tables.validate data/`
reports what is transcribed. Synthetic stand-ins in `cable-sizing/tests/fixtures/`.

**Verification.** `cd cable-sizing && python3 -m pytest tests` (113 tests).
- `tests/test_m4_verification.py`: the standard's own published answers,
  Appendix A.1.2 and Appendix B, and the methodology's acceptance cases
  (V4-xx). These need the licensed `data/` and skip without it.
- `tests/test_verification.py`: tabulated mV/A·m against the R/X calculation.
  Skips until the mV/A·m table is transcribed.
- The remaining tests run on the synthetic fixtures in CI.

**Open items.**
- AS/NZS 3000 Table 5.1 (minimum PE size) and the maximum Zs tables are not
  transcribed, so the earth-fault step stops at an `OpenItem`.
- mV/A·m tables not transcribed (independent cross-check only).
- `spec-exchange/ASK-003` (transcribe the Section 3 base rating tables) is
  recorded as OPEN, but the tables are present in the licensed `data/` and the
  Appendix A and B cases that depend on them pass. Close the record, or say
  what is still missing.
- Not yet behind the service; see C2.

## C2. LV cable sizing — service engine

**Decides** the same as C1, for the REST API, MCP tools, browser UI, the tray
tool (C4), the 800 A schedule and `cables/model_cable_system.py`.

**Engine.** `cable-sizing/feeder.py` (`size_feeder`, `check_feeder`,
`size_network`) on the primitives in `cable-sizing/as3008.py`. Service layer
`service.py`; every front end calls it.

**Method.** Reverse-engineered from jCalc's AS/NZS 3008 calculator (captured in
`reference/jcalc-cable-sizing-as3008.txt`); described in `cable-sizing/README.md`.

| Step | Where (`as3008.py` unless noted) |
|---|---|
| Design current | `design_current` |
| Ambient factor (analytic, capped by the tabulated set) | `ambient_rating_factor`, `ambient_factor_is_tabulated` |
| Grouping factor | `grouping_rating_factor` |
| Operating temperature, R at temperature, a.c./d.c. ratio | `operating_temperature`, `resistance_at_temp`, `ac_dc_ratio` |
| Voltage drop | `voltage_drop`, `cable_impedance` |
| Adiabatic, k | `k_constant`, `min_area_for_fault` |
| Fault current, loop length | `prospective_fault_current`, `max_length_calculated` |
| Selection loop over size and parallel runs | `feeder.size_feeder`, `feeder._evaluate` |

**Inputs.** AS/NZS 3008 JSON tables, `reference_tables.json` (AS/NZS 3000
tables) and the Nexans catalogue `../cables/cable_catalog.json`. Licensed or
vendor; not in git. `reference_tables_public.json` is in git.

**Verification.**
- `python3 test_feeder.py` (158 checks): AS/NZS 3000 Table C8 reproduced
  within 1 % for 2.5–25 mm², and the clause C4.2 worked examples.
- `python3 test_api.py` (150 checks): the REST and MCP front ends.
- `REVIEW-ELEK.md`: independent comparison with the ELEK calculator.
- `python3 test_synthetic.py`: assembly on invented numbers, runs in CI.

**Differences from C1 a reviewer should know.** Grouping uses one table
(touching, on tray or ladder) whatever the support, and holds the last value
beyond the table (`as3008.grouping_rating_factor`); Rev B keys Table 3.34 on
support type and refuses a fourth circuit per tier (R-GRP-1). Where the
formation of single-core cables is not stated it is assumed, with a warning;
the guess moves reactance by about 19 % (`feeder._reactance`). A size from the
service should be checked against C1 until the service moves onto it.

## C3. Design current, neutral and harmonics

**Engine.** `cable-sizing/design_current.py`: `design_current`,
`board_design_current`, `true_power_factor`, `distortion_factor`,
`triplen_neutral_current`, `unbalance_neutral_current`, `neutral_current`.

**Method.** Methodology Section 3 Rev B (`cable-sizing/METHODOLOGY-S3-RevB.md`):
displacement and distortion power factor, triplen harmonics adding in the
neutral, AS/NZS 3000 cl. 3.5.2 "substantial harmonics" at 40 %.

**Verification.** `python3 test_design_current.py` reproduces every §3.10
verification case of the methodology, as closed-form hand calculations. No
external published answer.

## C4. Cable tray span, supports, and cables on the tray

**Decides** the tray span and support positions for a route and the cable load
on it, and sizes the cables carried (via C2).

**Engine.** `trays/tray.py` (`choose_span`: the longest published span whose
rated load covers the cable load; `support_run`; `bom`), `trays/cables.py`
(sizing through `cable-sizing/service.py`, bundling and formation).

**Inputs.** Ezystrut tray catalogue (`cable-tray-ezystrut/tray_catalogue.json`),
vendor data, not in git. Tests use a synthetic catalogue.

**Verification.** `cd trays && python3 -m pytest tests` (31 tests): geometry,
clearances, span choice, and the sizing hand-off. No comparison with a vendor
span table under test.

**Open item.** `cable-tray-ezystrut/cable_tray_router.py`, the earlier
hand-scripted router, hard-codes span and load ratings from the AU01-2 drawing
set. `trays/` replaces it for calculation; the old file is kept for its FreeCAD
geometry. Those hard-coded ratings are vendor figures in a tracked file.

## C5. Pipe routing and pipe specification

**Decides** an orthogonal centreline between nozzles that clears obstacles and
respects minimum straight lengths between elbows. No hydraulic calculation;
hydraulics are C8.

**Engine.** `piping/core/router.py` (A* over corners and headings, with bend
cost and clearance), `piping/core/validate.py` (route rules, structured issue
codes), `piping/core/specs.py` (pipe sizes). FreeCAD solids in `piping/piping.py`
and `piping/route_engine.py`.

**Verification.** `cd piping && python3 -m pytest tests` (47 tests, plus a Rev B
benchmark that needs project data in `piping/private/`). Scenarios A–C route;
D and E are correctly refused (`routing_report.html`).

**Open item.** The Sch 10S table in `specs.py` cites no source and appears to
mix series: DN25, DN32, DN65 and DN125 outside diameters are ISO 1127 values
(33.7, 42.4, 76.1, 139.7 mm), not ASME B36.19M (33.4, 42.2, 73.0, 141.3 mm),
and the DN65 and DN600 walls differ from ASME 10S. Check against the pipe
standard the project specifies.

## C6. Air cooling CFD

**Decides** whether the supply air keeps rack intakes inside ASHRAE limits, for
one cabinet slice (`case`), the AU01 hall (`case-hall`) and the AU01 single
room (`case-au01`).

**Engine.** OpenFOAM v2406 in Docker (`opencfd/openfoam-default:2406`,
`cfd-cabinet-cooling/run.sh`). `buoyantSimpleFoam` (steady) for `case` and
`case-hall`; `buoyantPimpleFoam` (transient) for `case-au01`, which did not
converge steady. k-ω SST, blockMesh and snappyHexMesh, air as an ideal gas
(cp 1005 J/kg·K, Pr 0.71). Post-processing in Python and matplotlib.

**Method and limits.** `cfd-cabinet-cooling/README.md`, `FINDINGS-AU01.md`
(assumptions register with confidence grading), `MODEL-REVIEW.md`. ASHRAE
TC9.9 A1 limits in `plot_metrics.py`; A1–A4 in `plot_hall.py`.

**Verification.**
- Energy balance: ṁ = Q/(cp·ΔT) sets the target flow; the baseline closes to
  about 1 % (`README.md`, "What is modelled").
- Phased regression record: `VERIFICATION-3D.md` and `verification/*.txt`.
- `RESULTS.md` records a corrected return temperature (33.7 → 34.85 °C, from
  the adiabatic energy balance); the run that produced the original was
  overwritten.

**Open items.** No mesh independence study (50 mm cells). AU01 peak
temperatures are not grid converged; means are (`FINDINGS-AU01.md`). Fan walls
are boundary conditions, not machines; surfaces adiabatic, dry air. No tests
run the solver; solved output (2.3 GB) is in S3, not git.

## C7. Hall thermal digital twin

**Decides** rack intake temperatures and margins in real time, including under
load changes and fan wall trips.

**Engine.** `digital-twin/rom/dthall/`, numpy (scipy for calibration). 58
states. `model.HallModel.evaluate` (rack intake as a blend of cold zone and
hot-aisle entrainment; exhaust from a quasi-steady UA balance), `model.HallModel.step`
(explicit midpoint RK2), `gap.solve` (containment gap flow closure),
`rackfan.rack_mass_flow`, `constants.mass_flow_for_load`.

**Calibration.** `calibrate.fit` (least squares) to the case-hall CFD (C6);
parameters in `params_calibrated.json`. Method and scope: `digital-twin/docs/ROM.md`.

**Verification.** `cd digital-twin && python3 -m pytest rom/tests` (119
tests). The validation gate (`rom/tests/test_validation_gate.py`) holds every
rack's mean intake within 0.21 K of the CFD, flows within 0.0 %, energy
closing to 0.00 %. It reads the CFD probes from a committed extract
(`rom/dthall/data/case_hall_reference/`, made by
`tools/extract_cfd_reference.py`), identical to the full case.

**Open items.** One CFD operating point only (864 kW, 28 °C supply, all
modules on). `supply_reach` and `zone_coupling`, which govern every N-1 answer,
are not identifiable from it; one extra CFD run with a module off is the
recommended fix (`docs/ROM.md`). Transient time constants are estimates.
Air side only.

## C8. Liquid cooling hydraulics and plant

**Decides** flows, pressures and temperatures in the two-loop direct liquid
cooling system, including what a shut valve or tripped CDU does.

**Engine.** `liquid-twin/loop/dtloop/`, numpy.

| Element | Where |
|---|---|
| Pipe: Darcy–Weisbach, Swamee–Jain, laminar blend, ε = 4.5e-5 m | `components.Pipe` |
| Valve: K = 1.296e9 / (Kv² ρ) | `components.KV_TO_K`, `components.Valve` |
| Network: Newton solve with backtracking, Σṁ = 0 at nodes | `hydraulics.solve` |
| Plate exchangers: ε-NTU | `hx.effectiveness`, `hx.PlateExchanger` |
| Chiller with free cooling | `chiller.FreeCoolingChiller`, `chiller.ChillerPlant` |
| Pipe DN from velocity limit | `layout.size_dn` |
| Circuits, pump sizing, scenarios | `plant.build_circuits`, `plant.size_pumps`, `plant.run_scenarios` |

**Inputs.** `loop_params.json`: every value with a source and a confidence
grade (23 H, 10 M, 5 L, 1 C). 13 values are still unknown and `params.py`
refuses to return them rather than default (`LoopParams.pending()`: CDU rating
point, pump curves, site ambient, cold plate inlet limit, DLC capture
fraction). Temperatures from Schneider RD110 rev 3.

**Verification.** `cd liquid-twin && python3 -m pytest loop/tests` (137
tests): closure of the network solve, loop closure, valve authority, ε-NTU
limits. Checked, not verified against a vendor selection.

**Placeholders.** PG25 properties are typical published values (ASHRAE
Fundamentals ch. 31, Dow DOWFROST), not the fill's datasheet (`fluid.py`).
Chiller COP slope −0.11 /K is graded L (`chiller.FreeCoolingChiller.cop_per_k`).
`layout.size_dn` uses DN as the bore (under 3 % error, conservative).

## C9. Power and demand response simulation

On branch `power-sim` (PR #3), not on main yet. Grid, BESS, UPS, generator and
GPU load over a day; battery dispatch by perfect-foresight dynamic programming;
AEMO prices. Standard library only, no load flow, fault level or dynamics.
To be added here when it merges.

---

## Not calculations

Geometry and catalogue work with no engineering calculation of its own:
`cables/` (catalogue; `model_cable_system.py` builds tray geometry and calls
C2 for sizing), `cable-tray-ezystrut/` (FreeCAD tray geometry and joints),
`cooling-model/` (FreeCAD plant geometry; its README is the source of the CDU
and dry cooler figures C8 cites), `site/`, `vm-setup/`.

## Data that is not in the repository

| Data | Used by | Fetch |
|---|---|---|
| AS/NZS 3008.1.1:2025 and AS/NZS 3000 tables | C1, C2 | `tools/data_pull_standards.sh` |
| Nexans catalogue, Tricab families | C2, C4 | `tools/data_pull_vendor.sh` |
| Ezystrut tray catalogue | C4 | `tools/data_pull_vendor.sh` |
| Solved CFD cases | C6 (C7 uses the committed extract) | `cfd-cabinet-cooling/README.md` |
| Rev B piping benchmark | C5 | project data, `piping/private/` |

The standards are Standards Australia copyright and the catalogues are vendor
data; the code that reads them is open, the tables are not.
