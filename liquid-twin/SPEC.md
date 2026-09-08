# Liquid twin — two-loop DLC cooling system

**Status:** Phase 1 of 6 built. Sections 4.1-4.4 (elements), 9 and the
hydraulic half of 12 are implemented and tested; see README.md for what
changed once the physics was actually run.

A real-time model of the AU01 liquid cooling system: DLC cold plates → CDU →
dry coolers. Built to answer operating questions the CFD cannot — what happens
when a valve shuts, a CDU trips, or ambient hits 45 °C — and to drive a live
viewer showing fluid temperature and flow direction through the actual routed
pipework.

Companion to [`../digital-twin/`](../digital-twin/), which models the air side of
the same hall. The two are independent until Phase 6.

---

## 1. Why this is not a CFD problem

The heat exchangers reduce to two numbers each (UA and a flow exponent per side),
so nothing here needs a resolved flow field. What is left is a **1-D hydraulic
network** plus **1-D thermal transport** — a system of a few hundred states that
solves in well under a millisecond.

OpenFOAM has exactly one optional role, offline: if maldistribution across the
CDU or rack branch manifolds is genuinely in question, one steady incompressible
run of the header yields per-branch loss coefficients that become constants in
this model. Same CFD → reduced-model contract the air twin already uses. If the
branches are conventionally sized, skip it.

## 2. The governing decision: flow is an output

`cfd-cabinet-cooling/case-au01/0.orig/U` prescribes fan wall mass flow. Correct
for a steady design-point study, useless for asking what a closed valve does.

**This model must never prescribe a flow rate.** Every frame solves a pressure
network in which flow is the unknown:

| Element | Relation |
|---|---|
| Pipe / fitting | `Δp = K·ṁ·|ṁ|`, K from Darcy–Weisbach + Σ fitting K |
| Pump | `Δp = (a₀ + a₁Q + a₂Q²)·(N/N_ref)²`, affinity-scaled |
| Valve | `K = ρ / (2·Cv(x)²)`, Cv from the valve characteristic at position x |
| Heat exchanger | `Δp = K_hx·ṁ·|ṁ|` per side, K_hx from the rating point |
| Node | `Σ ṁ_in = Σ ṁ_out` |

Solved by Newton–Raphson on nodal pressures, warm-started from the previous
frame. Converges in 2–3 iterations at ~150 nodes.

**Consequence to preserve:** closing one rack branch valve must cause flow to
redistribute across the remaining parallel branches, the pump to ride up its
curve, and the isolated branch to heat up on its own thermal capacitance. That
emergent chain is the model's reason to exist.

### Closed valves

A fully closed valve gives K → ∞ and a singular Jacobian. Handle by clamping at a
large finite K (≈ 10¹² ) rather than pruning the branch, so the branch keeps its
thermal states and its temperature can still be shown rising.

## 3. Topology

```
   TCS / primary loop (PG25)                Facility loop (PG25)
   ─────────────────────────                ────────────────────
   ┌──────────────────────────┐
   │ DLC cold plates × N rack │
   └──┬────────────────────▲──┘
      │ rack return         │ rack supply
      ▼                     │
   ┌─────────────────────────────┐        ┌──────────────┐
   │  CDU  ── PHX (ε-NTU) ──     │        │  Dry coolers │
   │  secondary pump             │◄──────►│  (ambient)   │
   │  facility control valve     │  fac.  │  fan array   │
   └─────────────────────────────┘  pump  └──────────────┘
```

Three CDUs and one dry cooler bank, per `../cooling-model/`. A CDU and a dry
cooler are **the same component class** — a two-stream heat exchanger — differing
only in whether the cold stream is PG25 or ambient air.

## 4. Component models

### 4.1 DLC rack branch

Heat source on the fluid, with capacitance so starvation is finite:

```
C_branch · dT_out/dt = Q_liquid + ṁ·cp·(T_in − T_out)
Q_liquid = rack_kw · capture_fraction
```

`C_branch` is the fluid + cold plate thermal mass. Without it, ṁ → 0 divides by
zero; with it, a shut valve produces a realistic 30–60 s ramp to trip.

### 4.2 Heat exchanger (CDU PHX and dry cooler)

ε-NTU, counterflow:

```
UA:   1/UA = 1/(c_h · ṁ_h^0.8) + 1/(c_c · ṁ_c^0.8)
      NTU  = UA / C_min ,  Cr = C_min / C_max
      ε    = (1 − exp[−NTU(1−Cr)]) / (1 − Cr·exp[−NTU(1−Cr)])
      Q    = ε · C_min · (T_h,in − T_c,in)
```

Calibrated from **one vendor rating point**: c_h, c_c back out from the rated
duty, flows and terminal temperatures. That is the whole "couple of numbers".

For the dry cooler the cold stream is air: `C_c = ṁ_air·cp_air`, with `ṁ_air`
from the fan curve at commanded speed, and `T_c,in = T_ambient`.

### 4.3 Pump

Quadratic head curve, affinity laws for VFD speed, plus an efficiency curve so
the model reports shaft kW (needed for the PUE story).

### 4.4 Fluid — PG25

| Property | Treatment |
|---|---|
| ρ | linear in T |
| cp | linear in T |
| k | constant |
| μ | **polynomial in T — mandatory.** Roughly triples between 40 °C and 0 °C; a constant μ makes cold-end pressure drop badly wrong |

## 5. Thermal transport — and why it makes the demo look real

A single temperature per pipe changes colour everywhere at once and reads as
fake. Each pipe run is discretised into N finite volumes with upwind advection:

```
dT_i/dt = [ ṁ·cp·(T_{i−1} − T_i) + UA_amb·(T_amb − T_i) ] / (ρ·V_i·cp)
```

Cell count set so Courant ≤ 1 at the frame dt (0.1 s, matching the air twin). At
2 m/s a 60 m run needs ~30 cells and carries a ~30 s transport delay, so a load
step sends a visible thermal front down the pipe. A few thousand cells total is
computationally free.

**Timescale split:** hydraulics settle in milliseconds, thermals in tens of
seconds. Solve hydraulics quasi-steady each frame; integrate only thermal states.
Same split the air twin uses.

## 6. Controls

Three PI loops with rate limits. Without them, scenarios have no dynamics worth
watching — the interest is in the controller fighting the disturbance.

| Loop | Manipulated | Controlled | Notes |
|---|---|---|---|
| CDU secondary | secondary pump speed | rack supply temperature | primary temperature control |
| CDU facility side | facility control valve | rack supply temperature | valve authority matters; equal-percentage characteristic |
| Heat rejection | dry cooler fan speed | facility supply temperature | ambient-limited region below minimum speed |

## 7. Temperatures and setpoints — **PENDING Schneider RD110**

All temperature references are to be taken from the Schneider Electric **RD110**
design package. **Not yet obtained — every value below is a placeholder and must
not be quoted until replaced.**

| Parameter | Symbol | Value | Source |
|---|---|---|---|
| Facility supply water temperature | T_fws | **TBD** | RD110 |
| Facility return water temperature | T_frw | **TBD** | RD110 |
| Technology (TCS) supply temperature | T_tcs,s | **TBD** | RD110 |
| Technology return temperature | T_tcs,r | **TBD** | RD110 |
| CDU approach (PHX terminal ΔT) | — | **TBD** | RD110 |
| Dry cooler approach at design ambient | — | **TBD** | RD110 |
| Design ambient (dry bulb) | T_amb,des | **TBD** | RD110 + site |
| ASHRAE liquid class | — | **TBD** | RD110 |
| Max cold plate inlet temperature | — | **TBD** | RD110 / node vendor |

For orientation only, pending RD110: ASHRAE liquid cooling classes are W17, W27,
W32, W40, W45 and W+, named for the maximum facility supply water temperature in
°C. The class RD110 assumes decides whether the dry coolers can run without
adiabatic assist on a design day.

### The two numbers that decide everything

**CDU approach** and **dry cooler approach at design ambient**. Together they set
the floor on cold plate inlet temperature:

```
T_plate,in ≥ T_ambient + approach_drycooler + approach_CDU
```

At 40 °C ambient with a 5 K and a 6 K approach, that floor is 51 °C before any
control action. Whether the interesting scenarios are hot-day or
flow-distribution ones is decided by these two numbers, so obtain them before
writing the solver.

## 8. Load and plant data

Sourced from this repo; confidence marked as in `FINDINGS-AU01.md`.

| Item | Value | Source | Confidence |
|---|---|---|---|
| Hall liquid load | ~1,092 kW | `cfd-cabinet-cooling/FINDINGS-AU01.md` §6 | M |
| B300 rack liquid share | ~68 kW | `digital-twin/README.md` scope limits | M |
| B300 rack air share | 36.75 kW | `AU013-143-cooling-check.md` | C |
| DLC heat capture | "up to 95 %" | `FINDINGS-AU01.md` §365 — **split still open** | L |
| CDUs | 3 × Vertiv XDU 1350 | `cooling-model/README.md`, `SPEC.md` §207 | M |
| Dry cooler | 2.5 MW | `cooling-model/README.md` | L — placeholder geometry |
| CDU standing losses | 10–25 kW | `AU013-143-cooling-check.md` | L |

**Open:** the air/liquid split is not settled (`FINDINGS-AU01.md` §365). 68 + 36.75
= 104.75 kW/rack implies a 65 % liquid share, well below "up to 95 %". Resolve
before the model is used for capacity decisions.

## 9. Network source

The hydraulic graph and the render geometry come from the **same** routed
network. [`../piping/`](../piping/) already produces it:

- `PipeSpec.from_dn()` → bore, wall thickness
- `PipeRoute.get_total_length()` → run length
- route waypoints → elbow count → Σ fitting K
- the same waypoints → viewer geometry, one segment id per hydraulic element

This is the main structural argument for building on `piping/route_engine.py`
rather than a hand-written topology file: a layout change updates the physics and
the picture together.

## 10. Scenarios

Replayable JSON, same format as `digital-twin/scenarios/`.

| Scenario | Shows |
|---|---|
| `valve_close_rack.json` | flow redistribution, pump riding its curve, isolated branch heating — **the headline demo** |
| `cdu_trip.json` | N-1 across 3 × XDU 1350 at ~1,092 kW |
| `hot_day.json` | ambient sweep to design + extreme; where control authority is lost |
| `pump_trip.json` | facility pump loss, standby start, transport delay visible |
| `adiabatic_assist.json` | spray assist recovering a hot-day excursion |

## 11. Telemetry and viewer

Extends the existing WebSocket schema (`digital-twin/docs/TELEMETRY.md`). New:

```
segments: [ { id, m_dot, t_c, direction, velocity } ]     per pipe cell
components: [ { id, type, duty_kw, approach_k, saturated } ]
valves: [ { id, position, dp_kpa, authority } ]
pumps: [ { id, speed, head_kpa, flow, shaft_kw } ]
```

Viewer colours each pipe cell by temperature and animates flow direction from
sign and velocity. Reuses the three.js shell and geometry packer.

## 12. Verification

| Gate | Test |
|---|---|
| Energy closure | `it_kw = rejected_kw + storage_kw` at **every** timestep, not just steady state. The air twin's pattern — copy it exactly |
| Vendor rating point | XDU 1350 duty reproduced at rated flows and temperatures |
| Hydraulic closure | Σ Δp around each loop = pump head, to solver tolerance |
| Pump operating point | curve/system intersection matches hand calc |
| Valve authority | β = Δp_valve,open / Δp_branch within expected range |
| Redistribution | closing one of N parallel branches raises flow in the others; total flow falls |

## 13. Scope limits — state these in the README

- **Water hammer is not modelled.** A rigid-column quasi-steady solve carries no
  acoustic wave, so the pressure spike on fast valve closure is invisible. Valve
  stroke is rate-limited in the model; surge analysis is a separate calculation.
  Stated prominently because valve closure is the demo.
- No two-phase flow, no cavitation, no NPSH check.
- No air entrainment, no expansion vessel dynamics, no glycol degradation or
  concentration drift.
- Cold plates are a lumped branch — no die-level or per-node resolution.
- Fouling factors constant; no fouling growth over time.
- Dry cooler performance from the rating point scaled by flow exponents, not from
  part-load vendor data. The air twin carries the same caveat
  (`FINDINGS-AU01.md` §7) and it is the same weakness.

## 14. Phasing

| Phase | Deliverable |
|---|---|
| 0 | `loop_params.json` — every number in §7 and §8, each with source and confidence |
| 1 | Hydraulic core + tests (§12 rows 3–6) |
| 2 | Thermal transport + the shared ε-NTU component |
| 3 | Controls + scenarios |
| 4 | Telemetry + viewer |
| 5 | Validation and honest scope limits |
| 6 | *Later:* couple to the air twin — CDU standing losses and pump room heat become air-side load; one rack object owns both its liquid and air share |

## 15. Where it lives

Sibling to `digital-twin/`, not inside it. The air twin's contract with the CFD
is clean and documented, and folding a physics-first liquid model into a
CFD-calibrated ROM would muddy both. Share the WebSocket server and viewer shell;
keep the models separate until Phase 6.
