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
## 7. Temperatures and setpoints — from Schneider RD110

Source: **RD110 rev 3**, the 10 MW GB300 reference design (`RD110DSR3-GB300.pdf`,
Facility Cooling and IT Space attribute tables), with the piping topology from
`RD110_3.2_Mech_Piping_EN_R1` and equipment from `RD110_3.3` and `RD110_4.2`.

| Parameter | Value | Grade | Where it comes from |
|---|---|---|---|
| Facility supply (CDU CW supply) | **37 °C** | H | stated |
| Facility return (CDU CW return) | **47 °C** | H | stated — a 10 K facility rise |
| TCS supply (cold plate inlet) | **40 °C** | H | stated |
| TCS return | **50 °C** | H | stated — a 10 K secondary rise |
| CDU approach | **3 K** | M | derived: 40 − 37 |
| ASHRAE liquid class | **W40** | M | derived: 37 °C supply sits in the W40 band |
| RD110 outdoor range | −9.6 to 39.3 °C | H | stated, for Paris and Singapore |
| Dry cooler approach | **still open** | — | RD110 cannot settle it — §7.1 |
| AU01 design ambient | **still open** | — | needs the site weather file, dry *and* wet bulb |
| Cold plate max inlet | **still open** | — | 40 °C is RD110's design value, not the allowable limit |

Both loops run a 10 K rise, and the whole chain is only 13 K wide: 37 → 40 at the
CDU, 40 → 50 through the plate, 50 → 47 back. That is a deliberately tight stack,
and it is why the CDU approach matters as much as it does.

### 7.1 RD110 does not use dry coolers — and this changes the answer

**RD110's baseline heat rejection is four Uniflair XRAF4242A EHT
high-temperature chillers in N+1**, not dry coolers. Dry coolers appear only in
its Design Options list — *"integrate dry coolers with adiabatic assist to
further optimize energy electricity"* — with no approach temperature given.

This is not a detail. A chiller makes 37 °C water at any ambient in its range.
A dry cooler cannot make water colder than the air it rejects into, so holding
RD110's 37 °C facility supply constrains ambient directly:

```
T_ambient,max = 37 °C − approach
```

| approach | max ambient that still yields 37 °C |
|---|---|
| 3 K | 34 °C |
| 5 K | 32 °C |
| 8 K | 29 °C |

Australian design dry bulbs sit above that band. Note that even RD110's own
stated maximum — 39.3 °C — is above every row, which is consistent with its
choosing chillers for the baseline.

**Adiabatic assist is therefore not an optimisation, it is the enabling
component.** Pre-cooling drives entering air toward wet bulb:

```
T_entering = T_db − η (T_db − T_wb)
```

At 38 °C dry bulb, 21 °C coincident wet bulb and η = 0.8, entering air is
24.4 °C, and a 5 K approach gives 29.4 °C — inside 37 °C with 7.6 K to spare.
The same site without assist is 43 °C, which misses by 6 K.

So the design question the model must answer is not "how much energy do dry
coolers save" but **"how many hours a year does the site's coincident wet bulb
let them hold 37 °C, and what carries the load when it does not"**. That makes
`hot_day.json` (§10) the primary scenario rather than a stress case, and it makes
the coincident wet bulb — not the dry bulb — the number to chase.

None of the arithmetic above is RD110's. It is derived from RD110's stated
temperatures plus an assumed dry cooler approach, and it needs a real selection
to firm up.

### 7.2 The two numbers that still decide everything

Unchanged from before, but now half-answered. The CDU approach is 3 K. The dry
cooler approach at design ambient is what §7.1 is about. Together:

```
T_plate,in ≥ T_air,entering + approach_drycooler + approach_CDU
```

With RD110's 3 K CDU approach and a 40 °C plate inlet ceiling, everything
upstream has 37 °C to work with — which is the whole of §7.1 in one line.

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
