# AU01 whitespace airflow — findings

George Town, single whitespace, 736 kW air load, two Schneider Uniflair FWCV 40L2
fan walls. Study run 19–20 Aug 2026 in `case-au01`.

Live report: `case-au01/report-au01.html` (self-contained, regenerate with
`./build_report_au01.py case-au01`).

---

## 0. Position taken, 20 Aug 2026

**Conditional pass**, accepted by Andrew Sinclair on the basis that three rack
positions are unallocated. If the corner stagnation pocket proves real, positions
01 and 12 can be blanked or lightly loaded. That converts the residual exceedance
from a design failure into a placement constraint, and it changes neither the
plant selection, the return plenum, nor the fan duty point.

Two conditions attach to that position:

1. **Confirm at 50 mm before procurement.** Peaks are not grid converged (§7b);
   means are.
2. **The next pass should resolve rack internals**, not just the room — per-U load
   distribution and node-level fan behaviour. The present model treats each rack
   as one uniform volumetric source, which is the largest remaining gap and the
   main reason the corner peak is probably pessimistic.

Issued as `DAME-AU01-MEC-C02_Whitespace_Airflow_CFD_RevA`, against ticket
AU013-143.

---

## 1. Verdict

**The arrangement as drawn cannot cool the hall. With a return plenum over the
cold side and the fan walls throttled to rack demand, it can — with about 5 Pa
of static margin and 446 mm of ceiling clearance.**

| | as drawn (h3000) | + raised bulkhead | + plenum, 60 % throttle | + heads deleted, racks sealed |
|---|---|---|---|---|
| mean rack intake | ~50 °C | no change | 28.4–32.0 °C | **28.4–30.0 °C** |
| worst face | — | — | 41.3 °C at A01 | **37.2 °C at A01** |
| rack draw | — | — | 43.7 kg/s | **46.6 kg/s (95 % of demand)** |
| worst module ESP | — | — | 65.1 Pa | **65.9 Pa of 70** |
| settles? | no, still climbing | no | yes | yes, wander 0.03–0.33 K |
| verdict | FAIL | FAIL | FAIL | **FAIL on a single 60 mm patch** |

The final column is the trustworthy one. Two corrections separate it from the
third: the orphaned column heads were deleted (§5), and the rack cell zones were
given tops and end walls (§7). Both moved the result, the second materially.

**Where it now stands.** 22 of 24 racks sit within 0.4–0.8 K of supply
temperature, with face peaks of 28.8–29.4 °C — comfortably inside A2. The whole
failure is a localised hot spot on the two west end racks, A01 and B01, reaching
37.2 °C on a ~60 mm patch against a 35 °C allowable. Their *face means* are
29.96 and 29.59 °C, and their height-band means span only 1.5 K, so this is a
small, sharp spot rather than a warm face.

**And the earlier bottom-heavy reading was mostly an artefact.** With open rack
ends the bands showed the floor band 2.5 K hotter than the top and band 4 drawing
a third less air. Sealed, band flows are uniform (0.30 / 0.30 / 0.30 / 0.27 kg/s)
and the hottest band at A01 is b3, 1.0–1.5 m, not b1. So the missing end walls
were feeding that signal, which is exactly why the mechanism was not named at the
time.

ASHRAE A2 (Supermicro SYS-422GS-NB3RT-ALC): allowable 35 °C, recommended 27 °C.

---

## 2. Why the as-drawn arrangement fails

Not capacity, and not airflow quantity. Installed capacity is 950 kW against 736
(129 %) and nameplate airflow is 1.73× rack demand. The failure is **spatial**.

The fan wall discharge and the return slot sit **on the same plane**, about a
metre apart:

```
discharge    32.0 m² total  ->  2.26 m/s
return slot  15.6 m² total  ->  4.79 m/s     2.1x faster
```

The sink out-pulls the source at point-blank range, so supply air returns to the
unit it came from instead of crossing the 4.7 m to the pod. Working backwards
from the measured return temperature of 36.9 °C:

- fresh air reaching the racks: **19.0 kg/s of 84.65 — 22 %**
- racks re-ingesting their own 66.5 °C exhaust: **24.9 kg/s — 57 % of their draw**
- supply short-circuited straight to return: **65.7 kg/s — 78 %**

Cross-check: 19 kg/s absorbing 736 kW leaves the pod at 66.5 °C; mixed with
65.7 kg/s of untouched 28 °C bypass that gives a 36.65 °C return, against 36.88
measured. The picture is self-consistent.

**Raising the bulkhead does not help.** h4000 reached 41.71 °C mean at t = 14.0 s
against h3000's 41.44 °C at t = 14.6 s — indistinguishable. That is what
established the problem as architectural rather than a slot-sizing question. It
also halves the slot (7.79 → 3.59 m²) and puts it directly above the discharge's
top edge, so it removes separation rather than adding it.

### Root cause

Rev C/D had a ceiling plenum, which gave **vertical separation** between supply
and return. Rev E deleted it — correctly, because the containment roof sat below
the pipework and was choking the exhaust. But that put the return in the same
plane as the supply. The fix for the exhaust problem created a worse supply
problem.

---

## 3. The fix, and the constraint it forces

**Deck over the cold side**, open only above the hot aisle, plus **enclosed pod
ends**, leaves the racks as the only path from supply to return.

That forces a second change. You cannot push 84.65 kg/s through a pod that
accepts 48.8 — a sealed arrangement at nameplate flow is mass-infeasible. So the
fan walls must come down to roughly rack demand. **The airflow surplus is not a
safety margin here; it is the thing that breaks both the circuit and the pressure
budget.**

At 60 % of nameplate:

- supply/demand 1.040 — a small positive bias, so leakage runs cold→hot
- every module passes equal mass in and out (12.70 kg/s), which the earlier model
  did not enforce
- return arrives at ~43 °C rather than being diluted by bypass, which is a
  *better* coil operating point than the 37 °C rating condition

Control implication: the FWCV has EC fans regulated over Modbus and **4 optional
remote air temperature sensors "for controlling"**, plus group working across up
to 30 units. Control on **cold-aisle / rack-inlet temperature**, not return air.
The unit's built-in return sensor would be actively wrong here: as the circuit
tightens, return temperature rises by design, and a return-air controller would
speed the fans up and re-open the short circuit.

---

## 4. The ceiling is the binding constraint

The deck must sit at the fan wall top, 4.00 m. Any lower and the upper part of
the discharge blows into the plenum and short-circuits again. That leaves the
gable void as the entire return path, and the gable is shallow exactly where the
units are:

| across the unit | roof height | clear above deck |
|---|---|---|
| y = 2.1 m (unit edge) | 4.446 m | **446 mm** |
| y = 3.1 m | 4.616 m | 616 mm |
| y = 4.1 m (ridge) | 4.786 m | 786 mm |

Plenum cross-section **3.59 m²**, carrying the return at **6.3 m/s**.

Measured external static (discharge p_rgh minus return p_rgh, straight out of the
CFD rather than estimated with a loss coefficient):

| module | required ESP |
|---|---|
| W1 / E1 (lower) | 44.7 / 43.0 Pa |
| **W2 / E2 (upper)** | **65.1 / 63.5 Pa** |

**65.1 Pa against the 70 Pa the 475 kW rating assumes — 5 Pa of margin**, and it
is the upper modules that govern.

At nameplate the same duct would run 10.6 m/s and ~124 Pa, well past budget. The
throttle is what makes the tight ceiling survivable.

Two things would firm this up:
1. **The actual fan curve.** 70 Pa is the *rating point*, not the fan's ceiling.
   At 60 % flow an EC fan normally has more static in hand, so real margin is
   probably better than 5 Pa.
2. **Whether the deck can be locally deeper** away from the units, where the
   gable is taller.

A 50 mm deck was modelled with its **top flush to the fan wall**, so its
thickness eats into the cold side rather than the plenum. Inverted it would cost
about 0.4 m² of a 3.59 m² duct. At 446 mm, deck build-up, purlins, hangers and
insulation are not detailing — they are the design.

---

## 4b. The remaining hot spot: a stagnation pocket at the pod corners

With the plenum in, the heads deleted and the racks sealed, one failure is left.

**Location, from the reconstructed time-averaged field:**

| | value |
|---|---|
| hottest point, row A | x 8.510 m, z 1.501 m, 35.17 °C (interpolated) |
| hottest point, row B | x 8.510 m, z 1.501 m, 35.16 °C |
| per-rack face maximum | 37.20 °C at A01, 37.18 °C at B01 |
| face means | 29.96 °C (A01), 29.59 °C (B01) |

That is **70 mm in from the outboard end of the first rack, three quarters of the
way up the face.** Rows A and B agree to 0.01 K, so it is geometric, not noise.

**Mechanism.** The supply leaves the fan wall and sets up two large recirculation
cells in the clearance zone rather than sweeping straight to the pod. Their return
legs run along the pod face, and where the rack row begins the flow separates
around the corner. That corner is not swept by fresh supply, so warm air lingers
and is re-ingested by the first rack.

It is a **stagnation pocket, not a leak**. The containment is sealed, the rack ends
and tops are now closed, and the hot aisle cannot reach the corner — the HAC door
blocks it. What fails is air change at one corner.

**Two numbers that look contradictory and are not.** The face map peaks at
35.2 °C where the per-rack metric reports 37.2 °C. The map is interpolated to mesh
points and therefore smoothed; the metric is a maximum over actual mesh faces.
Likewise, in the plan view the red *inside* the rack outlines is air within the
rack volumes, heated by definition — not intake air.

**Extent on the face — 79 % of A01's intake is below 30 °C.** The exceedance is
narrow, not a broad wash:

| band from the outboard end | points | mean | max |
|---|---|---|---|
| 0–150 mm | 27 | 30.61 | **35.17 °C** |
| 150–300 mm | 44 | 29.60 | 32.13 °C |
| **300–450 mm (middle)** | 22 | **29.07** | **30.09 °C** |
| 450–600 mm | 44 | 29.19 | 33.40 °C |

Two separate features, not one:

1. A **narrow vertical band in the outermost ~150 mm**, peaking at z 1.2–1.7 m —
   roughly **U27–U38** on a 42U rack. This is the stagnation pocket.
2. A **small floor-level patch at the inboard edge** (571 mm from the end,
   z 0–0.2 m, max 33.4 °C) — a different, minor feature in the inter-rack gap.

The **middle of the rack is the coolest part of the face** (max 30.09 °C), so
loading the centre and keeping the outboard edge lightly populated is a valid
placement strategy. An earlier draft of this document claimed the warm region
spanned the full rack width; that was wrong — it came from reading the bounding
box of scattered points rather than their distribution.

**Candidates, cheapest first.** Set the first rack inboard so its face clears the
separation line; fit an end-of-row deflector to turn supply into the corner; or
extend the pod-end enclosure forward past the rack face. All are small physical
changes and none touches the cooling plant. Figures:
`hotspot_faces.png`, `hotspot_plan.png`, `hotspot_path.png`.

---

## 5. A geometry bug: three column heads with no columns

Three transverse members, **200 × 250 mm**, underside at **1.810 m — 190 mm below
the 2.0 m rack tops** and 250 mm in front of the intake plane, spanning the full
pod width at 3.66 m centres. The three racks they crossed carried the three
hottest faces in the hall.

They were **not** service-run structure:

- they lived in `_45_Support_Columns_CFD`, a group holding only heads and **no
  columns**
- **nothing vertical exists below 1.9 m** anywhere in the model to carry them
- the real service frame is self-supporting — `Spine-Beam-A/B` at z 2059.9–2359.9,
  *above* the rack tops, with posts to top rails at 3959.9
- their top face at 2059.9 is exactly the spine beams' underside, consistent with
  a superseded scheme where columns carried headstocks that carried the spine

Confirmed as leftovers not on the Delta drawings and **deleted** from
`DAME_AU01_CFD_SingleRoom.FCStd`; export regenerated (4056 triangles, 36 fewer,
nothing below the rack tops). Backups in `geometry/fcstd-backups/`.

`_45_Support_Columns_CFD` was deliberately **left in place but empty** —
`make_cfd_export.py` dereferences it and would crash on `None`.

### Follow-on clash

Raising the services clear of the racks instead of deleting them puts them
through the containment baffles, and there is **40 mm** between the baffle tops
(3.96 m) and the deck (4.00 m). Rerouting in y — clear of the intake planes at
y = 2.0 and 6.2 — is likely better than raising, and that is a structural
question.

---

## 6. Assumptions register — where every input comes from

Confidence is graded: **M** measured/published, **D** derived from measured
inputs, **C** a client or design decision, **A** my assumption, **X** excluded.

### 6.1 Geometry — all M, read not transcribed

| input | value | source |
|---|---|---|
| hall envelope | 24.130 × 8.200 m, eave 4.090, apex 4.786 | `cfd_export_params.json` → `room` (FreeCAD Rev E) |
| fan wall bodies | 4.0 w × 1.6 d × 4.0 h, y 2.100–6.100 | `cfd_export_params.json` → `fanwall` |
| module split | 2.000 m (2 stacked 40L1) | same |
| rack bodies | 24 × 600 × 1200 × 2000, 610 pitch, x 8.440–15.750 | `racks_body.stl`, parsed per solid |
| hot aisle | y 3.200–5.000 (1.8 m), doors 2.0 m, baffles z 2.0–3.96 | `cfd_export_params.json` → `hac` |
| bulkheads | h3000 as-drawn / h4000 variant, 80 thick | `bulkheads_h*.stl` |
| overhead services | 4056 triangles, lowest z 2.060 | `gantry.stl` (post-correction, §5) |
| return slot area | 7.79 m² (h3000) / 3.59 m² (h4000) | **D** — `A(h) = 20.392 − 4.2h`, re-derived from the gable and verified against the exporter's own figure |

### 6.2 Thermal load — the chain that matters most

| input | value | source |
|---|---|---|
| rack air load | 16 × 36 kW (HD, positions 03–10) + 8 × 20 kW (NET, 01–02, 11–12) = **736 kW** | **M/C** `cfd_export_params.json` → `rack_schedule_kw` |
| provenance of 36 kW | rounded from the 36.75 kW/rack air share in `AU013-143-cooling-check.md`, itself from the B300 load sheet | **C** — and that sheet is otherwise superseded (§8) |
| **server air-side ΔT** | **15.0 K** | **A — ASSUMED. Not published.** |
| → per-rack airflow, HD | 2.388 kg/s = 7,335 m³/h = **4,317 CFM** = 1.70 m/s face | **D** from `mdot = kW·1000/(cp·ΔT)` |
| → per-rack airflow, NET | 1.327 kg/s = 4,075 m³/h = 2,398 CFM = 0.94 m/s face | **D** |
| → both | **120 CFM per kW** | **D** |
| total rack demand | 48.82 kg/s | **D** |

**This is the weakest link in the study.** The Supermicro datasheet publishes no
airflow or CFM figure — only *"6× 80mm Fan(s)"* per node. Everything downstream of
ΔT (rack airflow, the throttle setting, plenum velocity, required ESP) is
therefore built on an assumption, and `AU013-143-cooling-check.md` flagged exactly
this: *"The B300 air-side ΔT assumption needs pinning down before fan wall airflow
(as opposed to kW) can be checked — this decided everything in the CFD sweeps."*

#### Cross-checked against the published fan matrix (20 Aug 2026)

Supermicro's System Fan Matrix does publish free-air ratings, so the assumption
can at least be tested for plausibility. Source:
<https://www.supermicro.com/en/support/resources/thermal> → System Fans.

| part | application | RPM | CFM | static (in.H2O) | dBA |
|---|---|---|---|---|---|
| FAN-0082L4 | SC743/745/748 | 5,000 | 68.3 | 0.53 | 45.0 |
| FAN-0111L4 | SC827, SC217 | 9,500 | 100.0 | 1.77 | 61.0 |
| FAN-0129L4 / 0148L4 | SC827/217, SC747 rear GPU | 11,000 | 116.5 | 2.14 | 62.5 |
| FAN-0162L4 | SC217, SC827 | 13,500 | 118.2 | 3.40 | 67.0 |
| FAN-0136L4 | SC827/217 high performance | 13,800 | 144.2 | 3.46 | 73.0 |

All are 80 × 80 × 38 mm.

**FAN-0082L4 is a real part but almost certainly not the one.** It is specified for
SC743/745/748 — 4U tower and workstation chassis — and at 5,000 RPM, 0.53 in.H2O
and 45 dBA it is a quiet, low-static fan. A B300 node with dense heatsinks, cold
plates and filtration needs several times that static. Decisively: at ΔT 15 K the
rack would need **132 % of FAN-0082L4's free-air rating**, which is impossible.

Inverting the assumption gives something checkable. At 8 nodes/rack × 6 fans:

| server ΔT | rack CFM | per node | **per fan, delivered** |
|---|---|---|---|
| 12 K | 5,396 | 675 | 112.4 |
| **15 K (assumed)** | **4,317** | **540** | **89.9** |
| 18 K | 3,597 | 450 | 74.9 |
| 20 K | 3,238 | 405 | 67.5 |

So ΔT 15 K needs **90 CFM per fan delivered**, which is 62–77 % of free-air rating
for the server-class fans (116–144 CFM). That is a normal delivered-to-free-air
ratio for a populated server, so **the 15 K assumption is plausible and
self-consistent.**

**And the risk direction is favourable.** Reaching a dangerous ΔT below 15 K would
require delivery at close to free-air rating, which a dense GPU node will not
achieve. The more likely outcome is the 116.5 CFM class at realistic system
resistance, landing nearer **18–19 K** — which *reduces* airflow, *reduces* plenum
velocity and *increases* ESP margin. The tight-ceiling risk in §4 is therefore
lower than the sensitivity table alone implies.

Three things remain unverified and should not be presented as settled:

1. **Which fan the SYS-422GS-NB3RT-ALC actually uses.** The matrix is a
   chassis-accessory list and does not cover that system.
2. **The delivered-to-free-air ratio.** 62–77 % is engineering judgement, not a
   published figure. Only a system-level airflow spec settles it.
3. **The air/liquid split.** The node is DLC-2 liquid-cooled with "up to 95 % heat
   capture", so those 6 fans handle only the residual air load. A per-node air
   load near 4.5 kW is consistent with the load sheet, but the split itself is
   still open.

#### Why it decides feasibility

| server ΔT | rack demand | throttle needed | plenum velocity | approx required ESP |
|---|---|---|---|---|
| 12 K | 61.0 kg/s | 75 % | 7.91 m/s | **~102 Pa — fails the 70 Pa budget** |
| **15 K (assumed)** | **48.8 kg/s** | **60 %** | **6.33 m/s** | **65 Pa — 5 Pa margin** |
| 18 K | 40.7 kg/s | 50 % | 5.27 m/s | ~45 Pa |
| 20 K | 36.6 kg/s | 45 % | 4.75 m/s | ~37 Pa |

ESP scaled as flow² from the measured 65.1 Pa, so approximate — part of the loss
is not velocity-squared. Direction and magnitude hold.

**If the servers run a tighter ΔT than 15 K, the return plenum stops fitting.**
Getting the real airflow per node from Supermicro is the single highest-value
input outstanding.

Related, and unresolved: the datasheet says *"DLC-2 supporting up to 95% of heat
capture via cold plates (with max config)"*. The load sheet assumes ~35 % of node
heat to air; the datasheet's best case implies ~5 %. Those differ by a factor of
seven on the air load. The 736 kW figure follows the conservative sheet, which is
the right direction for sizing, but the gap should be closed.

### 6.3 Fan wall duty

| input | value | source |
|---|---|---|
| airflow | 130,000 m³/h per end (65,000 per module) | **M** `cfd_export_params.json` → `fanwall.unit`; Schneider FWCV brochure |
| net sensible capacity | 475 kW per end (237.5 per module) | **M** same |
| rating conditions | RAT 37 °C, 30 % RH, ESP 70 Pa, EWT/LWT 20/30 °C, EU4 | **M** brochure, verified in `AU013-143-cooling-check.md` |
| EC fans, Modbus speed control | yes | **M** brochure |
| 4 remote air temperature sensors "for controlling" | optional | **M** brochure OPTIONS list |
| group working | up to 30 units on one LAN | **M** brochure |
| discharge face | full 4.0 × 2.0 m per module (8.0 m²) | **M** `fw_*_supply_m*.stl` |

### 6.4 Air properties — M, standard

`cp` 1005 J/kg·K, `R` 287.05, `p` 101,325 Pa, `mu` 1.82e−5, `Pr` 0.71, ideal gas.
All in `constant/thermophysicalProperties`. ρ at 28 °C = 1.1721 kg/m³.

### 6.5 Envelope and setpoints

| input | value | source |
|---|---|---|
| allowable max intake | 35.0 °C | **M** Supermicro datasheet: *"Operating Temperature: 10°C to 35°C"* — matches ASHRAE A2 |
| recommended max | 27.0 °C | **M** ASHRAE TC9.9, all classes |
| supply air temperature | 28.0 °C | **C** original brief; deliberately above the 27 °C recommended, consistent with maximising free cooling |

### 6.6 My design choices — A, and open to challenge

| choice | value | why |
|---|---|---|
| return plenum deck | top at 4.00 m, 50 mm thick | **A** — 4.00 is forced (any lower and the discharge blows into the plenum); thickness set into the cold side, not the plenum |
| pod ends enclosed | rack top to deck | **A/C** — your instruction, needed to force exhaust upward |
| supply throttle | 60 % of nameplate | **A** — chosen to give supply/demand 1.040, a small positive bias so leakage runs cold→hot |
| fan stiffness | 200 | **A** — numerical; calibrated so rack draw reaches 92 % of target (was 80 % at 50) |

### 6.7 Numerics — A, and their justification

| setting | value | basis |
|---|---|---|
| base cell | 100 mm, 25 mm on thin plates | the export states 50 mm and drops sub-50 mm clutter on that basis; 100/25 keeps plates at the same absolute resolution for ~4× fewer cells |
| solver | `buoyantPimpleFoam` transient | the steady solver demonstrably cannot converge this flow (§7) |
| endTime / averaging | 30 s, averaged from 18 s | mean intake peaks at ~7 s and settles by 14 s; 60 s was measured as unnecessary |
| maxCo | 3.0, PIMPLE 2 outer correctors | compromise between timestep and stability |
| turbulence | k-ω SST, 5 % inlet intensity, L = 0.1 × unit width | **A** — conventional for room airflow; not calibrated here |
| schemes | cell-limited gradients, `limited corrected 0.33` | required by the cut mesh |

### 6.8 Deliberately excluded — X

- **Non-IT heat.** No fabric or solar gain, no lighting, no CDU standing losses, no
  TCS pipe gains. Walls are adiabatic. `AU013-143-cooling-check.md` estimated
  10–25 kW of CDU standing losses alone and suggested a working figure of
  770–800 kW on the fan walls rather than 736. **The study is therefore optimistic
  by roughly 5 %.**
- **Liquid cooling.** Only the air share is modelled; the ~1,092 kW liquid loop and
  the CDUs are absent (CDUs are in the pump room).
- **Infiltration and containment leakage.** No door leakage, cable penetrations or
  blanking-plate gaps. Real containment leaks 5–10 %.
- **Humidity.** Dry air; no latent load.
- **Rack-internal detail.** No blanking plates, no U-by-U load distribution, no
  server fan curves. Each rack is a uniform volumetric heat and momentum source.
- **Transient events.** No fan failure ramp, no thermal ride-through, no N−1
  (`unitsOff` supports it but it has not been run).

## 7. What the study does not tell you

- **Rack airflow is imposed, not predicted.** Each rack holds one target velocity
  across its whole volume, so variation in flow up the height of a face is a
  modelling assumption. Intake faces are now banded into four 500 mm heights
  reporting temperature and flow, which shows *where* the heat sits but still
  cannot predict how server fans redistribute it.
- **ESP is compared against the rating point, not the fan curve** (see §4).
- **Coil capacity at reduced airflow needs vendor part-load data.** Higher return
  temperature helps the LMTD; lower face velocity hurts the air side. The brochure
  will not resolve which wins.
- **Peak temperatures are mesh-sensitive.** The earlier hall study moved the peak
  3.4 K between 100 mm and 50 mm cells. Present runs are 100 mm base with 25 mm on
  thin plates; a marginal peak needs the finer mesh before it is quoted.
- **Supply air temperature is a lever but a blunt one for this failure.** With the
  plenum, mean intake is ~1 K above supply, so lowering supply moves the mean
  almost 1:1 — but the binding constraint is a local excursion, and you would need
  roughly 21 °C supply to bring a 42 °C peak inside A2. On a free-cooling Uniflair
  loop that is the most expensive available fix. Fix the geometry first, keep a
  1–2 K water trim in reserve for margin.

---

## 8. Method notes and tooling bugs found

Recorded because several produced *plausible wrong answers* rather than failures.

| symptom | cause | fix |
|---|---|---|
| Steady solver reported energy balance closing to 103 % yet intake temperatures climbed +1.73 K per 1000 iterations with no plateau | `buoyantSimpleFoam` cannot converge a buoyancy-driven open-top aisle | transient `buoyantPimpleFoam` with time averaging |
| Upper fan wall modules appeared starved (37 vs 5 kg/s) | supply and return were independent patches, so mass balanced only across a whole end | prescribe mass flow on both; each module now passes equal mass |
| Rack draw 20 % under target | soft velocity source working against the pressure field | fan stiffness 50 → 200, draw now 92 % |
| "solver completed 4696 iterations", results fetched, instance terminated — run had covered 14 s of a 60 s transient | one SSH session held open for hours; a dropped connection looked identical to success | run `Allrun` detached on the box and poll; verify the solver reached `endTime` |
| Plotter printed "time averaged from t = 35 s" for a run that never reached 35 s | silent fallback to a tail average | fails loudly and labels the output as unconverged |
| A completed transient reported as never having started, instance terminated before fetching, 2.5 h of results lost | failure check hardcoded `log.buoyantSimpleFoam` | solver log name derived from `controlDict` |
| An instance kept billing with no supervisor | harness killed the launcher; `SIGKILL` bypasses the terminate-on-exit trap | launch detached (`nohup … & disown`); always check for stray instances after a run |
| `reconstructPar` would have written fields onto a stale mesh | snappy only ever wrote the mesh into processor directories | `reconstructParMesh` first |
| Run died in 3 iterations with a negative temperature | `p_rgh` initialised to 0; in `buoyantSimpleFoam` with `perfectGas` it carries absolute pressure, so density went to zero | initialise to 101325 |
| FPE inside `GAMGSolver::scale` | GAMG defaults coarsen too far on a cut mesh | explicit `nCellsInCoarsestLevel 500`, GaussSeidel |
| snappy geometry not found in a processor directory | `Allclean` deleted the generated `roof.stl` after the host wrote it | `constant/triSurface` is never cleaned |
| Wall BCs missed patches | snappy names a patch **per STL solid** (`hac_hac_baffle_a`), not per file | widened regexes |
| Export script only ran in the GUI | set `ViewObject.ShapeColor` unconditionally | guarded; original archived as `geometry/make_cfd_export.RevE-original.py` |

Also: the FreeCAD MCP `execute_code` endpoint errors internally on any input
(including `print("hello")`), and the MCP targets FreeCAD inside a Parallels VM
rather than the local application. CAD work was done with
`/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd`.

---

## 9. Provenance

Geometry is **read, not transcribed** — `make_au01_dicts.py` parses
`cfd_export_params.json` and the STLs directly, so the CFD cannot drift from the
building model. `au01Parameters` holds solver choices only. The plenum deck and
pod-end enclosure are generated parametrically by the CFD and now also exist in
the CAD (`_50_Return_Plenum_CFD`, `_51_Pod_End_Enclosure_CFD`).

`AU013-143-cooling-check.md` is **superseded** — the racks have been spread out
since, and its 741.8 kW distribution with a 45 kW IB spine no longer applies. The
authoritative schedule is the export's: 16 HD at 36 kW + 8 NET at 20 kW = 736 kW.
CDUs are in the pump room, so the whitespace contains nothing but the IT pod.

Compute: EC2 Graviton spot, `c8g.48xlarge`. Total spend across the study ~$32.
