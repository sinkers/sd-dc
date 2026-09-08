# Implementation Plan: OpenFOAM Cabinet Cooling Simulation

## Goal

A simple, reproducible OpenFOAM case simulating one 30 kW server cabinet in a hot-aisle-containment pod, supplied by a fan wall blowing cold air into the cold aisle. The output must let a human (or agent) visually judge whether cooling is sufficient and iterate on airflow parameters (fan wall flow rate, supply temperature, containment leakage).

**Primary success metric:** mass-weighted average air temperature entering the cabinet front (server inlet temperature) must be ≤ 27 °C (ASHRAE A1 recommended max). Secondary: no visible hot-air recirculation from hot aisle back into cold aisle.

## Constraints & environment

- Host is an Apple Silicon Mac. Run OpenFOAM in Docker: image `opencfd/openfoam-default:2406` (runs natively on ARM64). All `Allrun` scripts must work inside that container.
- Use **OpenFOAM v2406 (ESI/OpenCFD)** dialect — solver `buoyantSimpleFoam` (steady-state, buoyant, compressible). Do NOT use OpenFOAM Foundation 11/12 (`foamRun`) syntax.
- Visualisation with ParaView on the host (case writes standard OpenFOAM format; provide a `case.foam` stub file). Automated screenshots via `pvbatch` are a stretch goal — do not block on it.
- Everything lives in `sd-dc/cfd-cabinet-cooling/`. No changes elsewhere in the repo.

## Physics & sanity numbers (use these to validate the setup)

- Heat load: 30 kW into air inside the cabinet.
- Server airflow assumption: ΔT across servers ≈ 15 K → mass flow through cabinet ṁ = 30000 / (1005 × 15) ≈ **2.0 kg/s ≈ 1.7 m³/s (~3600 CFM)**.
- Fan wall supply: 20 % margin → ≈ **2.0 m³/s at 20 °C**. Over a 2 m × 1 m fan-wall patch that is 1.0 m/s face velocity.
- Expected hot-aisle temperature ≈ 20 + 15 = ~35 °C. If the converged solution shows cabinet exhaust wildly off ~35 °C, the heat/momentum sources are mis-set — stop and fix before proceeding.

## Geometry (all axis-aligned boxes — keep it this simple)

Single pod segment, origin at floor corner, x = supply→return direction, z = up:

| Object | Extent (m) | Notes |
|---|---|---|
| Room | 5.0 × 2.4 × 3.0 (x,y,z) | whole domain |
| Fan wall (inlet patch) | on x=0 wall: y 0.2–2.2, z 0.5–2.5 | 2 m × 2 m patch, velocity inlet |
| Cold aisle | x 0–1.8 | open |
| Cabinet | x 1.8–3.0, y 0.9–1.5, z 0–2.2 | 1.2 deep × 0.6 wide × 2.2 high; front face at x=1.8, exhaust at x=3.0 |
| Hot aisle containment | x 3.0–4.2, full width, walls + ceiling panels sealing hot aisle from room above/beside cabinet | baffles |
| Blanking panels | fill the y and z gaps around the cabinet in the containment front plane (x=1.8–3.0 plane boundaries) | baffles — hot aisle must only connect to cold aisle through the cabinet |
| Return outlet | ceiling of hot aisle: x 3.2–4.0, y 0.6–1.8, z=3.0 | pressure outlet |

Implementation: **one blockMesh block for the room, then `topoSet` + `createBaffles`** for cabinet walls, containment panels and blanking panels, and `topoSet` for the `servers` cellZone (the cabinet interior). No STL, no snappyHexMesh. Uniform cell size **50 mm** (~290k cells) with the block graded or refined only if trivially easy; 50 mm uniform is acceptable.

Ensure patch faces for inlet/outlet are created via `topoSet` faceSets + `createPatch` (or defined directly in blockMesh by splitting the boundary — implementer's choice, blockMesh boundary splitting is simpler if vertices are placed to line up; otherwise use createPatch).

## Case setup

- **Solver:** `buoyantSimpleFoam`, steady, gravity (0 0 -9.81).
- **Turbulence:** k-omega SST, standard wall functions.
- **Thermo:** `heRhoThermo`, perfect gas, air (constant cp = 1005, mu = 1.8e-5, Pr = 0.7).
- **fvOptions**, both scoped to the `servers` cellZone:
  1. Heat: `scalarSemiImplicitSource` on `h` (energy), `absolute`, injectionRate 30000 W total over the zone (`volumeMode absolute`).
  2. Server fans (momentum): `vectorSemiImplicitSource` on `U` in +x, calibrated so the through-cabinet flow reaches ≈ 2.0 kg/s. Start with an explicit source of order (ṁ × Δv / V_zone) and tune by checking the `cabinetFlow` functionObject below. Alternative if easier to calibrate: `fanMomentumSource` (available in v2406) with a flat fan curve. Either is acceptable — the acceptance test is the achieved mass flow, not the mechanism.
- **Boundary conditions:**
  - `fanWall` (inlet): `fixedValue U (1.0 0 0)`; `fixedValue T 293.15` (20 °C); turbulence: intensity 5 %, mixing length ~0.1 m; `fixedFluxPressure p_rgh`.
  - `outlet`: `fixedValue p_rgh` (0 gauge → `fixedValue uniform 101325` consistent with pRef setup); `inletOutlet` on U and T (backflow at 35 °C).
  - All walls/baffles: no-slip, adiabatic (`zeroGradient` T), `fixedFluxPressure`.
- **Numerics:** first-order upwind on div terms is fine for this purpose; limitedLinear acceptable. Relaxation: p_rgh 0.3, U 0.7, h/k/omega 0.5. Run 1500–3000 iterations.

## Function objects (in controlDict — these are the deliverable metrics)

1. `serverInletT` — `surfaceFieldValue`, mass-weighted average of T on the cabinet front face (faceZone at x=1.8 over cabinet extent). **The** pass/fail number.
2. `serverExhaustT` — same on cabinet rear face (x=3.0). Sanity: ≈ inlet + 15 K.
3. `cabinetFlow` — mass flow rate through the cabinet front faceZone. Target 2.0 ± 0.2 kg/s (used to calibrate the momentum source).
4. `residuals` + `fieldMinMax` on T (catch divergence / runaway hot spots).
5. Write these to postProcessing/ as .dat; add a small Python script `plot_metrics.py` (matplotlib) that plots serverInletT vs iteration to confirm convergence and prints a PASS/FAIL line against the 27 °C threshold.

## Deliverables & directory layout

```
cfd-cabinet-cooling/
├── PLAN.md                  # this file
├── README.md                # how to run, how to read results, how to tweak parameters
├── case/
│   ├── 0.orig/  system/  constant/
│   ├── Allrun                # blockMesh → topoSet → createBaffles → setup checks → buoyantSimpleFoam
│   ├── Allclean
│   └── case.foam             # empty stub for ParaView
├── run.sh                    # docker run wrapper (mounts case, runs Allrun in opencfd/openfoam-default:2406)
├── plot_metrics.py           # convergence + PASS/FAIL from postProcessing dat files
├── sweep.sh                  # (phase 4) clone case with PARAM overrides, run, collect CSV
└── paraview/
    └── views.md              # recipe: which slices/streamlines to set up (pvbatch script if time allows)
```

**Parameterisation for optimisation:** put the tunable numbers — fan wall velocity, supply temperature, cabinet target mass flow / momentum source coefficient — in a single `case/system/simulationParameters` file included via `#include` / `$vars` from the BC and fvOptions dicts, so a sweep only edits one file. `sweep.sh` takes `NAME=value` pairs, copies `case/` to `runs/<tag>/`, substitutes, runs, and appends `tag, fanVel, supplyT, serverInletT_final` to `runs/results.csv`.

## Visualisation recipe (document in paraview/views.md)

- Horizontal T slice at z = 1.0 m and z = 2.0 m (shows recirculation over/around containment).
- Vertical T slice at y = 1.2 m (through cabinet centreline: cold aisle → cabinet → hot aisle).
- Streamlines seeded on the fan wall patch, coloured by T (shows delivery path and any bypass).
- Colour scale fixed 18–40 °C so runs are visually comparable across the sweep.
- Optional iso-surface T = 30 °C to show hot-air escape from containment.

## Execution phases (agent should verify each before the next)

1. **Mesh & zones** — blockMesh + topoSet + createBaffles run clean; `checkMesh` passes; cabinet cellZone volume ≈ 1.2×0.6×2.2 = 1.58 m³; open in ParaView to confirm baffles seal the hot aisle.
2. **Cold flow** — run ~200 iterations with heat source off. Verify cabinetFlow reaches ~2 kg/s (tune momentum source), no divergence, flow goes fan wall → cold aisle → cabinet → hot aisle → outlet.
3. **Full run** — enable 30 kW source, run to convergence (residuals < 1e-4 or metrics flat for 300 iterations). Check sanity numbers above.
4. **Sweep & report** — run at least 3 fan-wall velocities (e.g. 0.7 / 1.0 / 1.3 m/s), produce results.csv and the metric plots, and write a short results section into README.md stating whether the baseline provides sufficient cooling and which direction to optimise.

## Acceptance criteria

- `./run.sh` completes end-to-end on a clean checkout with only Docker installed.
- `checkMesh` reports no errors.
- Converged baseline reproduces the sanity numbers (ΔT ≈ 15 K across cabinet at ~2 kg/s).
- `plot_metrics.py` prints PASS/FAIL against 27 °C server inlet temperature.
- Opening `case/case.foam` in ParaView with the documented recipe visually shows cold/hot aisle separation (or the failure mode, if any).
- README.md explains, in one page, how to change fan flow / supply temp and rerun.

## Out of scope (do not build)

- Transient simulation, CRAC/chiller plant modelling, radiation, humidity, multiple cabinets, snappyHexMesh geometry, mesh-independence study. Note them in README as future work.
