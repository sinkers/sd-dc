# Implementation Plan: move the cabinet cooling case to 3D

## Where we are

The case is **already 3D machinery running on a 2D problem**. The domain is a
0.6 m wide slab with `symmetry` on both side planes, so the solution is uniform
in y by construction. Every tool in the pipeline — `blockMesh`, `subsetMesh`,
`createBaffles`, `topoSet`, the cell-zone sources — is dimension-agnostic and
already driven from `system/simulationParameters`.

That means going to 3D is **not a rewrite**. It is: widen the domain, replace the
symmetry planes with real end-of-row conditions, and split the single cabinet and
single supply patch into a row of them.

## Why bother — what 2D cannot answer

| Question | Visible in 2D? |
|---|---|
| Is the row cooled at the design airflow? | yes — already answered |
| Where is the airflow balance threshold? | yes — already answered |
| **What happens when one fan wall unit fails?** | **no** — the failure is asymmetric |
| **Do the cabinets at the row ends run hotter?** | **no** — symmetry forbids an end |
| **Does a 30 kW cabinet steal air from its neighbours?** | **no** — all cabinets identical |
| **Do the hot aisle end doors leak?** | **no** — no ends exist |
| **Is delivery along the fan wall even?** | **no** — supply is one uniform patch |

The first two are the questions the 2D case was built for and it answers them
well. The rest are the reason to go to 3D, and the fan-failure case is the one
with real money attached: it is the N+1 redundancy question.

## Cost — measured, not guessed

Baseline today: **107,520 cells, 3,000 SIMPLE iterations, 150 s on 6 ranks**
(17,920 cells/rank). Host has 14 cores and Docker sees 12.6 GB.

Scaling per-rank cell count on 12 ranks (see `COMPUTE-OPTIONS.md`: this
laptop cannot actually sustain 12 ranks efficiently, so Stage 2 is a remote job):

| Configuration | Width | Cells | Cells/rank | Est. runtime |
|---|---|---|---|---|
| Today (2D slab) | 0.6 m | 107,520 | 17,920 | 2.5 min |
| Stage 1: 4 cabinets, symmetry | 2.4 m | 430,080 | 35,840 | ~5 min |
| Stage 2: 12 cabinets + 1.2 m ends | 9.6 m | 1,720,320 | 143,360 | ~20 min |

**A full 3D row is a ~20 minute run.** A six-point sweep is two hours. This is
affordable, which drives the single most important scoping decision below.

### Consequence: no mesh refinement machinery

Keep the **uniform 50 mm mesh**. Do not introduce `refineHexMesh`. The
containment gap is 0.2 m = 4 cells, which is exactly what the validated 2D case
uses, and 1.7 M uniform cells runs in 20 minutes. Local refinement would add
2:1 hanging-node interfaces, a new failure mode at the `createBaffles` and
`subsetMesh` steps, and buy nothing we need. Revisit only if the cell count has
to come down (see Risks).

## Core design decision: one case, not two

Do **not** fork a `case3d/`. Parametrise width in the existing case so that

```
nCabinets 1;  endClearance 0;  sides -> symmetry
```

reproduces today's 2D result exactly. Benefits:

- The 2D case stays alive as a fast regression test rather than rotting.
- There is one set of dictionaries to maintain, not two that drift.
- The sweep, animation and viewer tooling keeps working throughout.

## Geometry

New parameters in `system/simulationParameters`:

```
cabinetPitch    0.6;                                  // one rack
nCabinets       12;
rowWidth        #eval "$nCabinets * $cabinetPitch";   // 7.2 m
endClearance    1.2;                                  // aisle space past each row end
roomWidth       #eval "$rowWidth + 2*$endClearance";  // 9.6 m
rowY0           #eval "$endClearance";
rowY1           #eval "$endClearance + $rowWidth";
nFanUnits       8;                                    // discrete units across the wall
```

Everything in x and z is unchanged, so the validated 2D cross-section is
preserved exactly.

### Topology in 3D

The closed-loop topology has to generalise carefully. The rule is: **the hall
connects to the return plenum only through the contained hot aisle, and the
plenum connects to the hall only through the unit intake.**

| Surface | 2D today | 3D |
|---|---|---|
| Plenum floor (z = `unitHeight`) | x 0.8 → 6.0, full width | x 0.8 → 7.2, full width, **minus** the hot aisle footprint (x 6.0 → 7.2, y `rowY0` → `rowY1`) |
| Cabinet row | full width | y `rowY0` → `rowY1` only |
| Cabinet top (z = 2.2) | x 4.8 → 6.0 | same, y-limited to the row |
| Containment panel (x = 6.0) | z 2.2 → `containmentTopZ` | same, y-limited to the row |
| **Row end panels + hot aisle doors** | do not exist | **new**: baffles at y = `rowY0` and y = `rowY1`, x 4.8 → 7.2, z 0 → `unitHeight` |
| `sides` (y = 0, y = `roomWidth`) | `symmetry` | `wall` (real room walls) once `endClearance > 0` |

The plenum-floor "minus hot aisle footprint" is the piece most likely to be got
wrong. Implement it as `boxToFace` add, then `boxToFace` subtract, in
`topoSetDict.baffles`. If it is missed, cold room air short-circuits into the
plenum around the row ends and every result is quietly wrong.

## Per-cabinet sources and metrics

One `servers` cellZone becomes N zones, each with its own heat and fan source, so
that mixed loads and per-cabinet intake temperatures become possible. At N = 12
that is 12 cell zones, 12 face zones, 24 `fvOptions` entries and ~40 function
objects. Hand-writing that is untenable.

**Add a generator**, `make_row_dicts.py`, that reads `nCabinets` and an optional
per-cabinet load table and writes:

- `system/topoSetDict.zones` — N cellZones `servers_00..`, N oriented faceZones
  `cabinetInlet_00..`, `cabinetOutlet_00..`, plus the per-cabinet containment gap
  zones
- `system/fvOptions` — `serverHeat_NN` and `serverFans_NN` per cabinet
- `system/rowFunctions` — per-cabinet `surfaceFieldValue` objects,
  `#include`d from `controlDict`

Every generated file gets a `// GENERATED by make_row_dicts.py - do not edit`
header, and `Allrun` runs the generator before `blockMesh` so it cannot go stale.

Per-cabinet loads come from a plain table, e.g. `row_loads.csv`:

```
index,kW
0,30
1,30
...
6,5          # a low-density cabinet in the middle of the row
```

Default: every cabinet at `heatLoad`, which must reproduce the uniform result.

## Discrete fan wall units

Split the single `fanWall` patch into `fanWall_00 .. fanWall_{nFanUnits-1}`,
each a y-band of the unit face, via `topoSetDict.patches` boxes plus
`createPatch`. Each patch takes its own velocity from a table
`fan_units.csv`, defaulting to `fanWallVelocity` everywhere.

This is what unlocks the fan-failure study: set one unit to 0 m/s and the rest
to their N+1 boosted speed, and read the per-cabinet intake temperatures.

## Post-processing — the real work

The current single-slice picture stops being sufficient the moment the answer
varies along the row.

1. **`plot_slice.py`** — add `--y` to choose the slice plane (default: row
   centre). Existing behaviour unchanged when the domain is one pitch wide.
2. **`plot_plan.py`** (new) — horizontal slices at rack mid-height (z = 1.1) and
   at the containment gap (z = 2.5), which is where end-of-row and fan-failure
   asymmetry actually shows.
3. **`plot_row.py`** (new) — **the headline 3D chart**: intake temperature, mean
   and peak, versus cabinet index, with the 27 °C and 32 °C limits drawn on.
   Plus per-cabinet gap flow. One glance tells you which cabinets are in trouble.
4. **`plot_metrics.py`** — the verdict becomes **worst cabinet in the row**, not
   a single number. Report the offending index.
5. **`sweep.sh`** — mechanism unchanged. Add a separate `scenarios.sh` for
   discrete configurations (all fans running / one unit failed / one unit failed
   with N+1 boost / mixed load row), since those are not scalar sweeps.

## Solver settings

- `decomposeParDict`: `simple (6 1 1)` is wrong once y matters. Switch to
  `scotch` (verified working in this image; `hierarchical` is the fallback).
  **Rank count: use `cells / 20,000`, capped by physical cores — not 12 on this
  laptop.** Measured strong scaling peaks at 8 ranks and *collapses* beyond it:
  12 ranks is 1.9x slower than 6 on the current mesh. See `COMPUTE-OPTIONS.md`
  for the scaling table. For the 1.72 M-cell row that means ~85 ranks, which this
  machine does not have — so Stage 2 wants a remote CPU box, not a bigger local
  decomposition.
- `endTime`: raise the cap to 5,000. 3D lateral recirculation will converge more
  slowly than the 2D slab; `residualControl` still stops it early when it can.
- Relaxation factors were tuned on an effectively 2D problem. If convergence
  stalls, drop `U` to 0.5 and `p_rgh` to 0.25 before touching anything else.
- Add `renumberMesh -overwrite` after meshing. At 1.7 M cells the bandwidth
  reduction is worth a few percent per iteration.
- Physics is unchanged: `buoyantSimpleFoam`, k-ω SST, same thermophysical model.

## Execution phases

Each phase must pass its check before the next starts.

### Phase 1 — parametrise width, prove equivalence
Add the width parameters; keep `nCabinets 1`, `endClearance 0`, `sides` as
symmetry. Regenerate and re-run.

**Check:** bit-for-bit reproduction of the current result — intake mean
20.19 °C, peak 20.22 °C, gap flow +0.191 kg/s. Any deviation means the
parametrisation broke something.

### Phase 2 — widen with symmetry retained
`nCabinets 4`, `endClearance 0`, `sides` still symmetry, uniform loads. The row
still spans the full width, so this is a *wider slab of the same problem*.

**Check (the important one):** the answer must match Phase 1 to within
**0.1 K on intake temperature and 2 % on gap flow**, and total heat must balance
against 4 × 30 kW. This is the single most valuable test in the plan — it proves
the 3D generalisation is sound before any new physics is introduced. ~5 min.

### Phase 3 — per-cabinet zones and metrics
Introduce `make_row_dicts.py`, N cellZones, per-cabinet function objects, and
`plot_row.py`. Loads still uniform.

**Check:** per-cabinet intake temperatures identical across all 4 cabinets to
within noise; every per-cabinet inlet mass flow positive (catches faceZone
`flip` errors); summed per-cabinet flow equals the previous single-zone flow.

### Phase 4 — real ends
`nCabinets 12`, `endClearance 1.2`, `sides` to `wall`, add the row end panels and
hot aisle doors, and the plenum-floor cut-out.

**Check:** `checkMesh` clean and no `empty` patch (the existing guard).
Mass balance closes. Then the first genuinely new result: **is there an
end-of-row penalty?** Expect the end cabinets to differ; the magnitude is the
finding. ~20 min.

### Phase 5 — discrete fan units and scenarios
Split the supply patch, add `fan_units.csv` and `scenarios.sh`. Run:
uniform / one unit failed / one unit failed with the rest boosted / mixed-load
row.

**Check:** with all units at the same velocity, the result matches Phase 4 —
splitting one patch into eight must change nothing. Then report the fan-failure
result, which is the deliverable this whole exercise is for.

### Phase 6 — documentation and visuals
Update `README.md`, write `RESULTS-3D.md`, regenerate the animation over the
scenario set rather than a scalar sweep, and republish the viewer artifact with
the per-cabinet row chart.

## Acceptance criteria

1. `nCabinets 1, endClearance 0` reproduces the current 2D result exactly.
2. Phase 2 matches Phase 1 within 0.1 K and 2 %.
3. `checkMesh` clean, zero `empty` patches, at every phase.
4. Mass balance closes: supply = Σ(through cabinets) + gap flow = intake return.
5. Energy balance closes to ~1 % against Σ(per-cabinet kW).
6. Every per-cabinet inlet mass flow is positive.
7. Splitting the supply into `nFanUnits` at equal velocity changes nothing.
8. `plot_row.py` identifies the worst cabinet and its index.
9. A full row run completes in under 30 minutes on this machine.

## Risks

| Risk | Mitigation |
|---|---|
| **Docker memory ceiling** (12.6 GB) is the binding constraint, not CPU | 1.7 M cells needs ~3.5 GB; if a bigger row is wanted, cut `endClearance`, drop to a half-row with one symmetry plane, or fall back to a 100 mm base mesh with `refineHexMesh` around the cabinets |
| Plenum-floor cut-out missed → cold air short-circuits into the plenum | Phase 4 check on mass balance; assert plenum floor face count equals the computed area / cellSize² |
| Per-cabinet faceZone `flip` flags wrong → sign errors in half the metrics | Acceptance criterion 6 catches it directly |
| `subsetMesh` `empty`-patch trap | already guarded in `Allrun`; the guard must survive the refactor |
| Generated dicts hand-edited and then overwritten | `// GENERATED` headers; generator runs from `Allrun` |
| Convergence stalls in 3D | raise `endTime`, then loosen relaxation; watch `solverInfo` |
| Disk growth — each run is ~16× the field data | `rm -rf runs/*/processor*` after reconstruction; already documented |
| Half-row symmetry is invalid for fan failure | only use lateral symmetry in Phases 1–3; Phase 5 requires the full row |

## Out of scope

Unchanged from the 2D case, and each would change the numbers:

- Transient behaviour — fan failure is modelled as a *new steady state*, which
  says nothing about how long the racks have before they overheat. That needs
  `buoyantPimpleFoam` and is the natural next project after this one.
- Rack-resolved geometry: perforated doors, per-U load distribution, internal
  blanking.
- A real coil and fan curve — supply is still a fixed velocity at a fixed
  temperature, so the unit has infinite cooling capacity.
- Humidity, radiation, wall heat transfer.
- Mesh independence study.

## Optional follow-on: geometry from the SD-DC model

This case builds its geometry from axis-aligned boxes, which is why the mesh
pipeline is cheap and reliable. That holds as long as the layout is boxes.

If the goal is to drive CFD from the parametric layout in `SPEC.md` (Phase 5,
"thermal CFD pre-check"), the path is: export the pod from the FreeCAD model as
STL → `snappyHexMesh` → the same solver, sources and post-processing. Treat that
as a separate project: `snappyHexMesh` brings surface-feature capture, layer
addition and mesh-quality iteration, none of which the current pipeline needs.
Do not couple it to this work.
