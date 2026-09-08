# Digital Twin of the AU01 Hall — new work stream `digital-twin/`

## Context

The CFD stream (`cfd-cabinet-cooling/`) answers steady-state design questions offline. This new, fully isolated stream builds a **real-time digital twin** of the AU01 hall: a lightweight physics solver (reduced-order model, "ROM") calibrated from the existing OpenFOAM outputs, streaming live state to an Unreal Engine 5 scene built from the FreeCAD model at higher fidelity than the CFD geometry. Two modes modulate the B300 rack heat load: **manual** (UI sliders) and **auto** (synthetic transformer-training-run power profile: ramp, sustained utilisation, checkpoint dips, eval pauses, stragglers/restarts).

Everything lives under a new top-level `digital-twin/` directory. `cfd-cabinet-cooling/` is consumed **read-only**: geometry STLs + `cfd_export_params.json` (CFD_Export_RevE), `case-hall/postProcessing/` (72 per-rack channels × 205 iterations + 3 raw T/U slice fields), `verification/*.txt` (4 hall variants with full 24-rack tables), and the RESULTS.md 6-point fan sweep. UE is not installed yet — the plan includes setup.

Decisions already made with the user: hybrid ROM (lumped network calibrated to CFD + baked CFD fields for visuals); standalone Python service → UE over WebSocket JSON; UE 5 install included; auto mode is a synthetic seeded generator.

## Directory layout (all new files)

```
digital-twin/
├── README.md, pyproject.toml          # package "dthall": numpy, scipy, websockets, matplotlib, pytest
├── rom/dthall/
│   ├── topology.py     # node graph from cfd_export_params.json + B300 schedule
│   ├── model.py        # governing ODEs, state vector, step() — pure numpy, no I/O
│   ├── gap.py          # containment-gap recirculation/spill closure
│   ├── rackfan.py      # proportional fan model (stiffness = calibration param)
│   ├── calibrate.py    # least-squares fit against CFD data → params_calibrated.json
│   ├── params_default.json / params_calibrated.json
│   ├── profiles.py     # AUTO mode training-run generator (seeded)
│   ├── sim.py          # SimEngine: fixed-dt loop, command queue, speed multiplier
│   ├── telemetry.py    # versioned JSON schema encode/decode
│   ├── server.py       # asyncio WebSocket server (state out / commands in)
│   ├── cli.py          # dthall run|calibrate|validate|replay|debugview
│   └── debugview.py    # matplotlib live dashboard (pre-UE demo, real WS client)
├── rom/tests/          # energy balance, gap sign law, validation gate, profiles, schema, WS round-trip
├── fields/
│   ├── bake_slices.py  # raw CFD slices → 16-bit PNG textures + slice_manifest.json
│   └── baked/
├── ue-export/
│   ├── export_gltf.py  # FreeCAD-MCP script: DAME_AU01_Building → named-node .glb files
│   ├── export_manifest.json
│   └── assets/
├── ue/AU01Twin/        # Unreal project (Milestone 5+; Binaries/Intermediate/Saved gitignored)
└── docs/ROM.md, TELEMETRY.md, UE-SETUP.md
```

## 1. Reduced-order model

**Node graph** (~58 states, sub-ms per step):
- 24 rack nodes (`rack_A01…rack_B12`, names matching the CFD schedule): exhaust air temp + a rack thermal-mass state `T_m` so load steps produce realistic 1–5 min lags.
- 4 cold-aisle zones (A/B × west/east — aligned to fan-wall modules W1/W2/E1/E2 so unit-off asymmetry shows). Per-rack intake = zone temp + calibrated per-rack bias (stratification/hot spots).
- 1 open-top hot-aisle node, 1 upper-room node.
- 4 fan-wall module nodes: 32,500 m³/h each when on, 237.5 kW capacity, supply-temp setpoint with coil low-pass (τ≈30–60 s) and capacity saturation (overload → supply temp floats up).

**Physics** (reuse constants/relations from `make_hall_dicts.py`: cp=1005, R=287.05, ρ=P/(RT), ṁ=kW/(cp·ΔT)):
- Rack airflow from load via the design-ΔT relation with a fan-stiffness calibration parameter.
- **Gap closure (`gap.py`) — the headline physics from RESULTS.md**: per zone, net imbalance between rack demand and supply resolves through the open-top HAC gap. Racks starved → hot-aisle air recirculates into intakes (with per-rack path coefficients — end-door racks recirculate more); surplus → cold spill dilutes the hot aisle. The gap-flow **sign flip is the verdict law** and a first-class model output.
- Per-node energy balances `ρVcp dT/dt = Σṁcp T_in − ṁcp T + P`; heat goes load → rack mass → air.
- Integration: explicit RK2/RK4 (or exponential Euler per node) at dt = 0.25–0.5 s.

**Calibration** (`calibrate.py`, read-only inputs): windowed stats over the last ~50 iterations of `case-hall/postProcessing/` channels (CFD never fully converges — window, don't take endpoints), the 4 `verification/hall_v*.txt` rack tables, and the RESULTS.md 6-point sweep for the gap closure. ~60 structured free parameters (24 intake biases, 24 hot-path coefficients, zone mixing fractions, gap coefficients, global fan stiffness, 5 per-class thermal masses). scipy `least_squares` on per-rack inletT and flow residuals. Thermal masses are **not identifiable from steady CFD** — set from physical estimates and documented as such (transient behaviour is plausible-physics, not CFD-validated, in v1). More CFD points later are cheap (~$1 for 30 EC2 spot runs, scripts exist in `remote/`) and `calibrate.py` accepts extra case directories.

**Validation gate** (`dthall validate` + pytest): reproduce all 6 sweep verdicts (gap-flow sign) 6/6; hall v1–v4 per-rack mean inletT within ±1.0 °C for ≥22/24 racks (±1.5 °C worst), flows ±5 %; energy balance closes <0.1 %. The gate is a test — regressions fail the suite.

## 2. Field visuals from CFD slices

`fields/bake_slices.py`: grid the three raw slice fields (coldAisleA z=0.9375, rowAcentre y=2.825, hallCentre y=4.175; `x y z val` format) via `scipy.interpolate.griddata` onto ~512×256 grids → 16-bit PNGs + manifest (plane origin/extent, T range). UE uses the baked texture as the spatial shape and remaps it live with two scalars from telemetry: `T(x) = T_sup_now + (T_bake(x) − T_sup_bake)·scale`. One operating point today = one basis; multi-point blend (then POD) is the documented v2 upgrade.

## 3. Service and wire protocol

- `SimEngine` (fixed dt, wall-clock pacing with `speed` multiplier, 0 = as-fast-as-possible for tests), telemetry snapshots at 10 Hz.
- **WebSocket** (not UDP): UE ships WebSocket support built in, JSON framing is free, command ordering matters, localhost latency irrelevant. `websockets` asyncio server, multiple clients (UE + debugview + tests).
- State message: mode/profile phase, per-module supply state, zone temps, per-zone gap flow + spill flag, 24 rack entries (P_kw, T_in, T_ex, q_m3h, recirc_frac, status), per-plane field scale/offset, totals with balance error. `hello` on connect carries schema version + rack names for actor binding.
- Commands: `set_mode`, `set_load` (global scaling of B300 racks or per-rack), `set_unit` (W1/W2/E1/E2 on/off), `set_supply_temp`, `set_speed`, `auto_config` (seed, period). Ack/err replies.
- `dthall replay --script scenario.json --out csv` for headless regression; `dthall debugview` — matplotlib dashboard as a real WS client (rack bar chart vs ASHRAE limits, zone traces, gap-sign indicators, profile strip) — this is the demo before UE exists.

## 4. Auto mode (`profiles.py`)

`TrainingRunProfile(seed, config)` — deterministic via `numpy.random.Generator(PCG64)`. Phase state machine emitting per-B300-rack utilisation mapped to `P = P_idle + u·(36.75 − P_idle)` kW (non-B300 racks near-constant):
ramp-up (staggered S-curve) → sustained (0.92–0.98 with OU-process jitter, shared + per-rack components) → periodic checkpoint dips (~0.3 for 20–60 s) → occasional eval pauses (~0.15 for 2–5 min) → rare Poisson straggler/restart events (one rack idles, rest hold ~0.7, synchronized resume). Timescales compressed (~30 min "training day" by default). Tests assert seed determinism, bounds, phase statistics.

## 5. Unreal Engine 5 on this Mac

Runbook in `docs/UE-SETUP.md` (manual steps flagged):
1. **Install**: Epic Games Launcher → UE 5.4+ (native Apple Silicon; ~60 GB). Install Xcode; v1 stays Blueprint-only.
2. **Project**: Blank Blueprint game template at `digital-twin/ue/AU01Twin/`, Lumen on. Enable built-in plugins: WebSocket Networking, glTF Importer, JSON Blueprint Utilities, Niagara. If the installed 5.x's Blueprint WebSocket node coverage is lacking, fall back to a ~60-line C++ subsystem wrapping `FWebSocketsModule` (decide at Milestone 5).
3. **Geometry**: STL isn't natively importable and loses names. `ue-export/export_gltf.py` runs through the FreeCAD MCP (`mcp__freecad__execute_code`) against `DAME_AU01_Building.FCStd`, exporting **more parts than the CFD export** (shell with cladding/doors, detailed racks, full FWCV bodies with grilles, HAC panels, gantry trays/busways, dressing) as one .glb per group with **named nodes** (`rack_A01…` — the actor↔telemetry binding key). Verify imported dimensions against `cfd_export_params.json` (room 24.13×8.2 m, pod_origin [8435,2000,0]). An editor Python script (`Content/Python/bind_actors.py`) spawns/binds actors from `export_manifest.json`.
4. **Scene**: `BP_TelemetryClient` (connects ws://127.0.0.1:8765, parses JSON, event dispatcher) → `BP_Rack` per rack (emissive panels coloured by T_in/T_ex, Niagara exhaust plume ∝ flow/temp, warning pulse on recirc/over-limit), `BP_FanWall` per module (spinning fans ∝ Q, on/off), Niagara curl-noise flow over the HAC top edge driven by per-zone gap flow (visualises the verdict law), 3 translucent field planes sampling the baked slice textures remapped by telemetry scale/offset, UMG HUD (mode toggle, load sliders, unit switches, supply-temp, speed, 24-row rack table, profile phase) sending `cmd` JSON back.

## 6. Milestones (each independently demoable)

| # | Milestone | Demo / verify |
|---|---|---|
| 1 | ROM core | steady state + step-load lag; pytest: energy <0.1 %, gap sign flips on supply deficit |
| 2 | Calibration + validation gate | `dthall validate` scorecard vs v1–v4 + 6-point sweep; results in docs/ROM.md |
| 3 | Service + debugview + manual mode | kill fan unit W1 live in debugview, watch row A heat up; WS round-trip test |
| 4 | Auto mode + baked fields | training-run profile animating temps; baked PNGs checked vs raw scatter |
| 5 | UE install + geometry import | static hall walkthrough; dims vs params JSON; 24/24 racks named |
| 6 | UE live binding | HUD slider → cmd → ROM → material change; parity with `wscat` |
| 7 | Polish + showpiece | auto run, kill a fan wall, watch recirculation flip; debugview numbers == UE HUD |

**Honest v1 exclusions** (stated in README): no liquid-cooling loop (B300s also reject 68.25 kW/rack to liquid — out of scope), transient constants physically estimated not CFD-validated, single-operating-point field basis, last-write-wins multi-client.

## Key read-only inputs

- `cfd-cabinet-cooling/geometry/CFD_Export_RevE/cfd_export_params.json` — geometry + rack schedule source of truth
- `cfd-cabinet-cooling/case-hall/postProcessing/` — calibration channels + raw slices
- `cfd-cabinet-cooling/make_hall_dicts.py` — physics constants/relations to reuse
- `cfd-cabinet-cooling/RESULTS.md` + `verification/hall_v*.txt` — calibration + validation targets
- `cfd-cabinet-cooling/geometry/make_cfd_export.py` — reference pattern for the FreeCAD export script
- PLAN-CONCEPT-A.md B300 schedule: A02-05/A08-11/B02-05/B08-11 = 36.75 kW B300; A06/B06 40 kW; A07 45 kW; B07 13.8 kW; A12 15 kW; A01/B01/B12 spare (~742 kW air total)

## Verification

**Pre-UE**: full pytest suite (energy closure, gap sign law vs RESULTS.md, v1–v4 gate tolerances, profile determinism, schema round-trip, WS server round-trip); `dthall replay` regression CSVs; debugview exercising the exact wire protocol UE will use; manual `wscat` smoke of every command.

**With UE**: in-editor dimension check vs `cfd_export_params.json`; 24/24 actor name binding with unbound-key logging; numerical parity debugview vs UE HUD on the same session; command→visible-change latency < 300 ms; identical scenario replay in both clients.
