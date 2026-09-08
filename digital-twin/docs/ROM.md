# The reduced-order model

What it is, what it is calibrated against, what it is allowed to claim.

## The node graph

```
  W1 W2 ──┐                                        ┌── E1 E2      4 fan-wall modules
          ├─> cold_A_west  cold_A_east ────────────┤              4 cold zones
          │        │             │                 │
          │      row A racks   row A racks         │              24 racks
          │        └──────┬──────┘                 │
          ├─> cold_B_west  cold_B_east             │
          │        │             │                 │
          │      row B racks   row B racks         │
          │        └──────┬──────┘                 │
          │           HOT AISLE  <─── spill ───────┘              1 open-top aisle
          │               │  └──── recirculation ──> rack intakes
          └────────── RETURN <─────┘                              1 return path
```

58 dynamic states for a 24-rack hall:

| State | Count | What sets its time constant |
|---|---|---|
| `T_m` rack metal | 24 | thermal mass / metal-to-air conductance, ~60–90 s |
| `T_cold` cold zones | 4 | zone volume / airflow through it, ~2–3 s |
| `T_hot` hot aisle | 1 | aisle volume / total rack flow, ~1 s |
| `T_ret` return path | 1 | return volume / fan flow, ~8 s |
| `T_sup` coil discharge | 4 | chilled-water coil lag, 45 s |

Rack exhaust temperature is **not** a state. Air spends milliseconds inside a
rack, so it is solved algebraically from the metal temperature each step:

```
m·cp·(T_ex − T_in) = UA·(T_m − (T_in + T_ex)/2)
```

The lag the twin shows after a load step therefore comes from the metal, which
is where it comes from in reality. About 20% of a load step reaches the air
almost immediately — increasing airflow extracts more heat from already-hot
heatsinks — and the remaining 80% arrives over the metal's time constant.

## The governing law

Everything the twin is interesting for comes from one line in `gap.py`:

```python
T_in = (1 - phi) * T_zone + phi * T_hot
```

`phi` is the fraction of a rack's intake air that came from the hot aisle rather
than the cold zone. It has two parts:

1. **A zone deficit term.** Racks move their own airflow regardless of what the
   fan wall delivers (`rackfan.py`). If a zone's racks demand more than reaches
   it, the shortfall can only come over the containment — AU01's hot aisle is
   open-topped, so this is the design's intended return path, not a leak.
   `zone_coupling` decides how much of a neighbouring zone's surplus migrates
   across before a starved zone resorts to the hot aisle.
2. **A baseline term.** Aisle-end racks entrain hot air even when the hall is
   comfortably oversupplied. This is not a fudge: `verification/hall_v4` shows
   supply exceeding rack demand by 15% while the four end-of-row racks still
   ingest ~1.3 K above the middle of the row.

Mass is conserved by construction — every kilogram recirculated out of the hot
aisle is matched by a kilogram of cold spill into it, and each zone balances
`supply_in = Σ(1−phi)·m_rack + spill`. `test_energy_balance.py` holds the whole
loop to a tighter closure than the CFD achieves, in the starved case as well as
the oversupplied one.

### Energy accounting

At any instant:

```
it_load_kw = cooling_kw + storage_kw
```

`storage_kw` is the rate heat is going into the hall's thermal mass. It is zero
only at equilibrium. This matters for reading the twin: during a checkpoint dip
the HUD legitimately shows IT at 328 kW and cooling duty at 564 kW, and the
236 kW difference is the hall giving back heat it had stored. Comparing load
against duty alone is a steady-state check, not a live one. The books close to
machine precision at every timestep (`test_energy_closes_during_a_transient_too`).

## Calibration

Reference: **`case-hall` at its v4 configuration** — 50 mm cells, 8.35 m hall,
24 × 36 kW uniform, 28 °C supply, all four modules running. It is the only hall
run with per-rack results on disk, and the only one whose `system/hallParameters`
still describes the case that produced them.

Data is read directly from `case-hall/postProcessing/` by `cfddata.py`, never
from a transcription of the printed summary, and always as **windowed
statistics**: the hall CFD does not converge (p_rgh plateaus at ~0.077 at the
4000-iteration cap). Over the last 500 iterations the rack means wander ±0.05–0.3 K
and the flows ±0.05–0.27 kg/s, but the face peaks swing ±0.85–1.4 K. Means are
averaged over that window; peaks are taken as the window maximum.

### Fitted coefficients

| Coefficient | Fitted | Identified by |
|---|---|---|
| `module_flow_multiplier` | 1.0416 | total supply mass flow |
| `fan_flow_multiplier` | 1.2627 | total flow through the racks |
| `recirc_baseline[end]` | 0.1370 | end-of-row intake temperatures |
| `recirc_baseline[next]` | 0.0386 | second/second-last intake temperatures |
| `recirc_baseline[mid]` | 0.0202 | mid-row intake temperatures |
| `peak_multiplier` | 6.275 | the `inletTmax` channels |

Recirculation baselines are **positional** (end / next / mid) rather than 24
independent per-rack values. Three parameters against 24 observations is far
better conditioned, and it transfers to a hall with a different rack count.
Per-rack overrides exist for known outliers but are unused.

On `module_flow_multiplier`: the CFD sets a velocity boundary condition and
realises 84.78 kg/s where nameplate volume at supply-air density gives 81.40 —
a 4% difference in its supply-patch density convention. Fitting it keeps the
ROM's mass balance aligned with the CFD without corrupting the "a fan moves
volume" physics that governs the twin's own predictions.

### Not fitted, and why

- **`supply_reach`, `zone_coupling`** — unidentifiable from this reference. It is
  symmetric (four modules, uniform load) and comfortably oversupplied, so no zone
  is starved and nothing in the data responds to how supply is distributed or
  migrates between zones. They keep priors of 0.72 and 0.5.
- **`recirc_gain`** — the *baseline* recirculation is identified; the *gain*
  (how a deficit converts into recirculation) is not, for the same reason. Prior
  1.0, i.e. a deficit is made up entirely from the hot aisle.
- **`rack_metal_delta_t_k`, `thermal_mass_kj_per_k`, `coil_tau_s`,
  `return_mix_factor`** — transient parameters. Steady CFD carries no information
  about them whatsoever. These are physical estimates: the metal-to-air
  conductance is sized from a 25 K design heatsink-to-air difference, and the
  thermal mass is that of the metal actually in the air path (heatsinks and
  boards, ~100 kJ/K per rack — not the chassis steel, which is largely
  thermally isolated from the airflow).

Usefully, `UA` and thermal mass **cannot** disturb the steady state: at
equilibrium the air carries exactly `P` regardless of either. So the transient
estimates and the steady-state fit are cleanly separable.

### Earlier hall variants

`verification/hall_v1_baseline.txt`, `v2_bulkhead_sealed`, `v3_1500hotaisle_42U`
are *geometry* variants — different hot aisle widths, bulkhead configurations and
mesh densities. Only their printed summaries survive; `hallParameters` has since
moved on to v4, and the parameters that produced them are not recoverable from
the repo. Using them as references would mean guessing at the geometry, so they
are not used. This is the main reason the quantitative fit rests on a single
operating point.

## Validation gate

`dthall validate`, and `test_validation_gate.py` as a regression:

```
  [PASS] rack mean intake within 1.0 K    24/24 racks (need >= 22)
  [PASS] rack mean intake worst error     0.21 K (limit 1.5)
  [PASS] rack peak intake worst error     2.02 K (limit 2.5)
  [PASS] total supply flow                84.78 vs 84.78 kg/s (-0.0%)
  [PASS] total flow through racks         72.37 vs 72.37 kg/s (+0.0%)
  [PASS] return air temp (enthalpy mean)  38.14 vs 38.14 C (CFD area-mean 37.11 C)
  [PASS] energy closure                   0.00%
  [PASS] reached steady state             True
```

Peak tolerance is 2.5 K because the CFD's own peaks oscillate by more than a
kelvin over the averaging window; demanding better would be fitting noise.

The gate also asserts that the **end-of-row lift is reproduced, not averaged
away** (the ROM's end-minus-middle difference must match the CFD's to within
0.3 K), and that the uncalibrated defaults *fail* — otherwise a broken parameter
loader could make the gate pass without testing anything.

### A note on return temperature

The CFD's `returnT*` channels are `areaAverage(T)` over the intake patch, which
is not the enthalpy mean when velocity varies across the patch. Here they differ
by about 1 K — which is exactly why `hall_v4`'s summary quotes 37.20 °C while
`MODEL-REVIEW.md`'s energy-closure check uses 38.15 °C for the same run. A
lumped model's return node carries a well-mixed enthalpy temperature, so the
gate compares against the enthalpy mean (38.14 °C) and reports the area mean
alongside it. Comparing the ROM against the area mean would be an
apples-to-oranges check that the model could only pass by being wrong.

## The return path, and why the twin is silent about it

Worth stating separately, because it looks like something the twin should answer
and is not.

At each end of AU01, return air cannot go straight to the fan wall's rear intake.
The unit is a solid block 4 m tall (x 2.0–3.6 at the west end) spanning y 2.1–6.1,
and bulkheads seal the 2.1 m passages either side of it up to 3.0 m. So the air
has to get over something first — over a bulkhead, or through the gable space
above the unit — then down into the 2 m rear corridor and forward into the
intake. Those openings total about **7.9 m²** as drawn, which is the design
sheet's ~7.8 m² figure.

Two consequences:

1. **Lowering the bulkheads is a real design lever and the ROM cannot evaluate
   it.** Dropping them from 3.0 m to 2.0 m enlarges the return openings to about
   12.1 m², a 53% increase, which roughly halves the slot velocity and cuts the
   pressure drop by around 2×. But the ROM has *one lumped return node with no
   pressure drop at all*, so it will report identical temperatures either way.
   This is a static-pressure/ESP question. Answering it needs the CFD —
   `case-au01` already accepts `bulkhead h3000|h4000` as a scenario knob, and a
   2 m variant would need regenerating from FreeCAD via `make_cfd_export.py`.
   The viewer shows the geometry and the computed areas so the question is
   visible; it does not pretend the thermal model answered it.

2. **The slot velocity depends on which flow you mean.** The design sheet's
   ~2.6 m/s is at the racks' airflow demand (~151,000 m³/h). The fan wall is
   sized at 260,000 m³/h, so at full fan speed the same opening sees ~4.8 m/s.
   Both are right; they answer different questions. The viewer labels its figure
   "at fan flow" for exactly this reason.

## Calibration scheme mismatch — the most important caveat

The ROM is calibrated against `case-hall`, which has a **contained hot aisle with
a ceiling plenum**. AU01 has an **open-top hot aisle with a baffled channel
exiting at its ends**. These are materially different return schemes.

What transfers: the rack-level physics (airflow from load, metal thermal mass,
the energy balance), and the *form* of the gap closure — that a supply deficit is
made up by entraining hot air, and that the verdict turns on the sign of that
flow.

What does not transfer with any confidence: the *coefficients* of that closure.
`recirc_baseline` was fitted to end-of-row racks leaking past a containment
panel below a plenum floor. In AU01 the aisle has no roof at all, so the
geometry of the leak is different and the fitted numbers are being used outside
the configuration that produced them.

No CFD of the AU01 open-top scheme has been run. `case-au01` is meshed and staged
but has never been solved. Until it is, AU01 numbers from this twin should be read
as "the right shape, calibrated on a different containment scheme" — which is why
the very first item in the CFD list below matters more than the tuning ones.

## What this model cannot tell you

- **It is calibrated at one operating point.** It reproduces that point to
  0.21 K. Its response to *changes* rests on physics plus priors, not on data.
  See "Next CFD runs" below.
- **Transient time constants are estimated, not validated.** The shape is
  physical; the exact seconds are engineering judgement.
- **One field basis.** The baked slice textures scale and slide with ROM state
  but cannot change *shape*, and a module going offline genuinely reorganises the
  flow field rather than just scaling it. See `fields/bake_slices.py`.
- **No pressure drop anywhere.** One lumped return node, so bulkhead height, slot
  area, gantry blockage and filter loading are all invisible to it. Fan flow is
  imposed, not the result of a fan curve meeting a system curve.
- **Coil capacity is a hard cap.** Duty is limited to nameplate regardless of
  entering air temperature. A real chilled-water coil does better as the return
  gets hotter (larger LMTD), so the twin's equilibrium temperature in a
  capacity-limited scenario is pessimistic.
- **Air-side only.** The B300 racks also reject ~68.25 kW each to liquid. None of
  that is modelled; `design_kw` is the air fraction.
- **Four cold zones.** Enough to make a single module trip asymmetric, not enough
  to resolve a temperature gradient along a row.
- **No rack-level detail.** No per-U profile, no blanking panels, no humidity, no
  radiation, adiabatic surfaces — the same simplifications as the CFD it comes
  from.

## Next CFD runs, in value order

All three are **boundary-condition-only** changes to `case-hall`: same mesh,
restart from the converged field, and around a dollar of EC2 spot time using the
existing `cfd-cabinet-cooling/remote/` scripts.

0. **`case-au01` at all** — the AU01 open-top scheme has never been solved. The
   case is meshed and staged. Everything the twin says about AU01 currently rests
   on coefficients fitted to a *different containment scheme* (see above). This
   outranks every tuning run below.
1. **`unitsOff A1`** — an asymmetric run. This is the single highest-value
   addition: it is the only thing that can identify `supply_reach` and
   `zone_coupling`, which currently govern every N-1 answer the twin gives on
   priors alone.
2. **`unitAirflow_m3h` turndown sweep** — drives the hall through the balance
   point where gap flow crosses zero, identifying `recirc_gain` and validating
   the failure mode the twin is built to show.
3. **`supplyTemp_C` sweep** — confirms the field remap's offset behaviour and
   checks the coil model against a second thermal operating point.

A transient run (`buoyantPimpleFoam`) would be the only way to validate the time
constants, and is a genuinely more expensive proposition — worth flagging as a
decision rather than assuming.
