# Cable Sizing (AS/NZS 3008)

> **Where this came from.** The calculations here were reverse-engineered from
> jCalc's AS/NZS 3008 cable size calculator,
> <https://www.jcalc.net/cable-sizing-calculator-as3008>, which is the origin of
> this component. That provenance was never written down, so it could not be
> found by reading the code. The page is captured in
> `reference/jcalc-cable-sizing-as3008.txt`; jCalc's results are behind a login,
> but its documentation of method and defaults is public and is used here as a
> cross-check. See also `REVIEW-ELEK.md`, an independent check against a
> different implementation.

Programmatic cable sizing for connections between loads in the data centre power
network. Given a source, a load, a route length and an installation condition,
it returns the smallest cable that satisfies AS/NZS 3008.1.1, with a full audit
trail of every check.

This component is the calculation layer that sits on top of `../cables/`, which
is the Nexans Australia product catalogue. `cables/` answers *what cable exists*;
this answers *which one to use*.

## Files

| File | Purpose |
|---|---|
| `as3008.py` | AS/NZS 3008.1.1 calculation primitives — derating, voltage drop, K constant, loop impedance, earth sizing |
| `iec60228.py` | IEC 60228 conductor DC resistance, used when the catalogue lacks impedance data |
| `cable_sizing.py` | The sizing engine — `Source`, `Load`, `Installation`, `size_feeder()`, `size_network()` |
| `reference_tables.json` | All reference data, each table tagged with provenance and a `verified` flag |
| `EXTRACTED-TABLES.md` | Capture record of everything read from AS/NZS 3000:2018, including what was deliberately not encoded |
| `test_cable_sizing.py` | 150-check suite: published worked examples, table structure validation, AS/NZS 3000:2018 cross-checks |
| `standards.py` | The five standard profiles: reference ambients, installation vocabularies, voltage drop limits, IEC voltage factor |
| `install_diagrams.py` | Inline SVG diagrams of each installation arrangement |
| `service.py` | Service layer. The web UI, the REST API and the MCP server all call this, so they cannot disagree |
| `server.py` + `ui.html` | Web UI, REST API, OpenAPI and Swagger UI |
| `openapi.py` | OpenAPI 3.1 description of the REST API |
| `mcp_server.py` | MCP server over stdio, same operations as the REST API |
| `MCP.md` | MCP setup: Claude Code and Claude Desktop config, tools, resources |
| `build_800a_table.py` | Generates the 800 A 3ph+N+E schedule page into `out/` |
| `as3008_ratings.json` | AS/NZS 3008.1.1 Table 3.14 col 5 ratings, from two agreeing calculators |
| `ezystrut.py` | Tray selection against the Ezystrut range in `../cable-tray-ezystrut/` |
| `test_api.py` | 129-check suite for the standards layer, diagrams, service, OpenAPI and MCP |
| `tricab_families.json` | Tricab public family metadata. Deliberately carries no per-size electrical data: see below |
| `REVIEW-ELEK.md` | Review of ELEK Cable Pro Web against this engine, with the measured differences |
| `reference/` | Captured evidence: the jCalc origin page, the five ELEK pages, the cross-check scripts, the Tricab extractor |

## Usage

```python
from cable_sizing import Source, Load, Installation, size_feeder

result = size_feeder(
    Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2),
    Load("PDU-A1", kw=250, power_factor=0.95),
    route_length_m=85,
    install=Installation(method="touching", ambient_c=45, n_circuits=4),
)
print(result.summary())
```

```
MSB-1 -> PDU-A1   [XLPE_SDI_CU]
  Active            300 mm2
  Earth             120 mm2
  Design current    366.1 A
  Derating          0.716 (ambient 0.930 x grouping 0.770)
  Voltage drop      5.36 V (1.29 %)
  Fault current     12748 A -> min area 39.9 mm2 (K=142.9)
  Cable OD          28.8 mm
  ...
```

For a whole distribution board, `size_network()` takes a list of connections and
`cable_schedule()` renders the result as a schedule table:

```python
msb = Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2)
results = size_network([
    (msb, Load("PDU-A1", kw=250, power_factor=0.95), 85, Installation(ambient_c=45, n_circuits=4)),
    (msb, Load("CDU-1",  kw=75,  power_factor=0.88), 140, Installation(ambient_c=45, n_circuits=2)),
])
print(cable_schedule(results))
```

The outputs feed the rest of the toolkit directly: `od_mm` and `weight_kg_per_m`
size cable trays and check tray loading, and `bend_radius_mm` constrains routing
geometry.

## The four checks

Sizes are tried in ascending order, and for each size every parallel-run count
from 1 up to `Installation.max_parallel`. The first combination passing all four
checks wins. Preferring fewer runs of a larger cable matches normal practice.

1. **Current-carrying capacity** — catalogue rating x derating >= design current
2. **Voltage drop** — against the load's `max_voltage_drop_pct`
3. **Short-circuit withstand** — adiabatic `I²t = K²S²`
4. **Earth fault loop impedance** — only when a protective device is declared

## Formulas

**Design current** — per phase:

```
3-phase:  I = VA / (sqrt(3) x V)          1-phase / 2-phase:  I = VA / V
VA from kW: VA = kW x 1000 / pf           from hp: kW = hp x 0.7457 / efficiency
```

**Derating** — required table rating is `I_design / (k_ambient x k_grouping)`.

**Operating temperature** — losses go as `I²`, so the rise above ambient does too:

```
theta_op = theta_ambient + (theta_max - theta_ambient) x (I / I_rated)²
```

This is then rounded **up** to the next tabulated resistance column
(45, 60, 75, 90, 110 °C) before resistance is resolved.

**Voltage drop** — with a known load power factor the in-phase projection is
used, otherwise the worst-case magnitude:

```
Zc = R cos(phi) + X sin(phi)       (specified pf)
Zc = sqrt(R² + X²)                 (worst case)
Vd = factor x I x L x Zc / 1000 / parallel_runs
```

`factor` is sqrt(3) for three-phase, 2 for single-phase and DC, and drops to 1.5
(120°) or 1.0 (180°) for balanced two-phase mains.

**Short-circuit withstand** — `S_min = I_f x sqrt(t) / K`, with the fault current
taken at the far end of the cable so the cable's own impedance limits it.

**Earth conductor** — AS/NZS 3000 clause 5.3.3, or a fixed proportion of the
combined active area above 630 mm² (25% copper, 40% aluminium). Parallel runs are
combined as `S_combined = S_active x m / n`.

## Data provenance

This matters, so it is spelled out per quantity.

| Quantity | Source | Confidence |
|---|---|---|
| Current-carrying capacities | `../cables/cable_catalog.json` (Nexans Australia) | Manufacturer published |
| Tricab family construction/ratings | `tricab_families.json` (tricab.com) | Publisher published; **no per-size data, see below** |
| Conductor DC resistance | `iec60228.py` — IEC 60228 class 2 | Verified: matches all 14 catalogue values exactly |
| AC resistance | Catalogue `r_ac_ohm_km`, else DC x AC/DC ratio | See caveat below |
| Reactance | Catalogue `x_ohm_km`, else 0.08 Ω/km nominal | Fallback is formation-dependent; flagged in warnings |
| K constant | Computed from conductor physics | Verified to <0.6% against 6 published values |
| Ambient derating | Tabulated values from the catalogue, closed form outside their range | Tabulated values preferred (see below) |
| Grouping derating | `../cables/cable_catalog.json` | Empirical, single layer touching on tray |
| Minimum earth sizes | AS/NZS 3000:2018 clause 5.3.3 | **Unverified — see `reference_tables.json`** |
| Insulation temperature limits | AS/NZS 3000:2018 Table 3.2 | **Verified** against the printed standard |
| Minimum conductor sizes | AS/NZS 3000:2018 Table 3.3 | **Verified** against the printed standard |
| Voltage drop limits | AS/NZS 3000:2018 clause 3.6.2 | **Verified** against the printed standard |
| Conductor colours | AS/NZS 3000:2018 Table 3.4 | **Verified** against the printed standard |
| Conduit fill | AS/NZS 3000:2018 Tables C10–C12 | **Verified**; medium-duty columns not captured |
| Aluminium earthing conditions | AS/NZS 3000:2018 clause 5.3.2.1.2 | **Verified** against the printed standard |

All reference tables live in `reference_tables.json`, each carrying a `verified`
flag, a `source` string and a `note`. `as3008.verification_report()` reports the
status of every table, and `as3008.unverified_tables()` lists those not yet read
from a printed standard. The test suite prints the provenance of all six tables
on every run, and refuses to let a table be marked `verified` while it still
carries placeholder provenance.

To drop in verified data: edit the `data` block, set `verified` to `true`, put
the exact edition and table number in `source`, and run the suite. The
structural checks (monotonicity, bounds, coverage, earth never exceeding its
active) will catch transcription errors.

### Insulation temperature limits (verified)

AS/NZS 3000 Table 3.2 has been read from the printed standard, giving 21
insulation types with three limits each. Two subtleties it settles:

- **V-90 is rated 75 °C in normal use**, not 90 °C, as are V-90HT, HFI-90-TP and
  TP-90. The higher figure is the *maximum permissible* temperature, allowed only
  where the cable is protected against severe mechanical damage. Current ratings
  derive from the normal-use figure, so that is what the engine uses as its
  rating basis; `max_permissible_c` is recorded but never applied automatically.
- **`X-110` is not an AS/NZS 3000 designation.** The standard lists X-HF-110.
  The code accepts `X-110` as an alias because cable tools and catalogues use it.

`min_ambient_c` is captured for all 21 types but is not yet checked by the engine.
Short-circuit limit temperatures are *not* in Table 3.2 — they come from AS/NZS
3008 Table 53 (2017) / Table 5.2 (2025) and remain unverified, currently assigned
by family (thermoplastic 160 °C, thermoset 250 °C).

### Neutral sizing and harmonics (verified)

AS/NZS 3000 clause 3.5.2 is implemented, which closes the harmonic gap that
matters most for this toolkit — IT loads, VSDs and switch-mode supplies are
exactly the harmonic-generating equipment the clause names.

- A harmonic load of **40% or more** of the total load on any single phase is
  "substantial" (NOTE 1). Above that threshold the third and higher order
  harmonic current is **added** to the maximum out-of-balance load, taken as
  100% of the highest harmonic current on any phase.
- Third harmonics are additive in the neutral, so **the neutral can legitimately
  need to be larger than the active**. For a 250 kW PDU feeder at 55% harmonic
  content the engine returns a 300 mm² active with a **630 mm²** neutral.
- Set `Load(harmonic_content_pct=...)` and `Load(out_of_balance_pct=...)`. The
  default is a linear balanced load, giving a neutral equal to the active per
  clause 3.5.2(b)(ii).

Exceptions 2 and 3 of clause 3.5.2, which permit a *reduced* neutral given a
detection device or predominantly multiphase load, are **not** applied.

### Voltage drop is a cumulative budget (verified)

Clause 3.6.2 limits the drop between the point of supply and *any* point in the
installation, so drops along a path add — a chain of individually compliant
segments can still breach the limit. `size_feeder()` checks one segment;
`voltage_drop_budget()` checks a whole path:

```python
budget = voltage_drop_budget([msb_to_pdu, pdu_to_rack], nominal_voltage_v=415)
# {'total_pct': 2.00, 'limit_pct': 5.0, 'passed': True, 'margin_pct': 3.00, ...}
```

The limit is **5%**, rising to **7%** where the point of supply is the LV
terminals of a substation on the premises and dedicated to the installation
(Exception 3) — set `Installation(dedicated_onsite_substation=True)`. Clause
3.6.3 confirms the parallel-conductor treatment the engine already used: assess
one conductor carrying the circuit current divided by the number in parallel.

### Conduit sizing and aluminium earths (verified)

`min_conduit_size()` implements AS/NZS 3000:2018 Tables C10–C12:

```python
as3008.min_conduit_size(95, 4)                      # -> 80.0 mm heavy duty rigid UPVC
as3008.min_conduit_size(95, 4, conduit_type="corflo")  # -> 100.0 mm
as3008.min_conduit_size(16, 1, cable_form="4c_earth")  # -> 40.0 mm
```

Only the heavy duty rigid UPVC and Corflo columns were captured — the medium duty
columns were cut off in the source images, so medium duty conduit cannot be
returned. See `EXTRACTED-TABLES.md`.

`check_aluminium_earth()` implements clause 5.3.2.1.2: aluminium earths must be
solid at 10 mm² or below, at least 16 mm² for a main earthing conductor, and not
underground or in damp situations unless designed for it.

### Independent cross-check against Table C8

AS/NZS 3000:2018 Table C8 and the clause C4.2 worked examples are used to check
the engine, never as a data source. Both examples reproduce exactly — the
35 mm²/16 mm² size selections and all three percentages (3.65%, 2.45%, 1.46%).

The resistance comparison also located where reactance starts to matter:

| Size range | Agreement, resistance only | Reading |
|---|---|---|
| 2.5–25 mm² | within **0.71%** | Resistance model confirmed |
| 35–95 mm² | +1.6% to +9.4% high | Reactance not negligible above ~35 mm² |
| 1–1.5 mm² | +12% to +16% high | Table C8's `Vc` exceeds IEC 60228 class 2; unexplained, below the sizes targeted here |

Back-solving Table C8 for reactance gives a consistent **0.105–0.114 Ω/km** across
16–95 mm² for multicore PVC — about 33% above the 0.08 Ω/km previously assumed.
The nominal fallback is now split by construction (single-core 0.08 from the
catalogue's own range, multicore 0.107 from Table C8). Every catalogue cable is
single-core, so selections are unchanged, but the multicore figure is available
and sourced.

### Finding the earth conductor sizes

Secondary sources cite "AS/NZS 3000 Table 5.1", which is misleading twice over.
The label collides across the two standards:

| Purpose | Standard | Reference |
|---|---|---|
| Minimum earth conductor size | AS/NZS 3000 | clause **5.3.3** |
| Short-circuit fault constant K | AS/NZS 3008.1.1:2025 | Table 5.1 (was Table 52 in 2017) |

Clause 3.5.3 of AS/NZS 3000 settles it: *"The size of an earthing conductor shall
be determined in accordance with Clause 5.3.3."* So the sizing rules live at
clause **5.3.3** in Section 5, not clause 5.1 — and AS/NZS 3000 numbers tables
per section, so any "Table 5.1" is simply the first table in Section 5.

No rating table from AS/NZS 3008 is reproduced here — that document is
copyrighted. What is implemented is the *methodology*, with ratings supplied by
the manufacturer catalogue already in the repo.

### The K constant is computed, not looked up

AS/NZS 3008 publishes K in Table 52 (2017) / Table 5.1 (2025), but the table is
a closed-form result of the adiabatic heat balance:

```
K = sqrt( Qc (beta + 20) / rho20 x ln( (beta + theta_f) / (beta + theta_i) ) )
```

Implementing this directly means any initial/final temperature pair works,
including the non-tabulated ones that arise from a computed operating
temperature. Validation:

| Case | Published K | Computed | Error |
|---|---|---|---|
| Cu X-90, 90→250 °C | 143 | 142.87 | −0.09% |
| Al X-90, 90→250 °C | 94 | 94.55 | +0.59% |
| Cu V-75, 75→160 °C | 111.2 | 111.17 | −0.03% |
| Al V-75, 75→160 °C | 73.6 | 73.65 | +0.07% |
| Cu, 45→250 °C (example 1) | 167.4 | 167.38 | −0.01% |
| Cu, 50→250 °C (example 2) | 164.7 | 164.66 | −0.03% |

### Ambient derating: tabulated values win

The closed form for the ambient rating factor is

```
k = sqrt( (theta_max - theta_ambient) / (theta_max - theta_base) )
```

which captures the shape of the standard's correction tables but runs
**optimistic** against them, because it ignores the temperature dependence of
resistivity and of the thermal resistances:

| Ambient | Tabulated | Closed form | Error |
|---|---|---|---|
| 45 °C | 0.93 | 0.949 | +2.0% |
| 50 °C | 0.87 | 0.894 | +2.8% |
| 55 °C | 0.79 | 0.837 | +5.9% |
| 60 °C | 0.71 | 0.775 | +9.1% |

An optimistic derating factor undersizes cable, so `ambient_rating_factor()`
returns the **more conservative** of the two whenever a tabulated value applies
(90 °C conductor on a 40 °C air basis), interpolating between tabulated points,
and falls back to the closed form only outside that range.

### Caveat: AC resistance of large conductors

Skin and proximity effect make AC resistance exceed DC resistance, growing with
conductor area. Scaling DC resistance by temperature alone understates the
catalogue's own AC figure by up to **10.7%** at 630 mm² — the unsafe direction
for voltage drop. `as3008.AC_DC_RATIO`, derived from the catalogue, corrects this
to within 0.05%.

There is a residual disagreement between sources at large sizes. Against the
AS/NZS 3008 Table 4.5(A) values quoted in the elek.com worked examples:

| Size | Implied by AS/NZS 3008 | Nexans catalogue | Agreement |
|---|---|---|---|
| 35 mm² | 1.001 | 1.001 | Exact |
| 630 mm² | 1.252 | 1.120 | Standard is 12% more conservative |

The catalogue is the optimistic source. Sizing at or above 400 mm² therefore
emits a warning telling you to confirm voltage drop against the printed table.
The likely cause is a different formation basis or the inclusion of sheath eddy
losses, but that could not be resolved without the standard itself.

## Validation

```
$ python3 test_cable_sizing.py
All 150 checks passed.
```

The suite validates the primitives against two independently published worked examples
([elek.com, AS/NZS 3008.1.1:2025](https://elek.com/articles/as-nzs-3008-cable-sizing-calculations-step-by-step-guide/)):

**Example 1** — 400 V three-phase, 1200 A, 260 m, buried single-core copper
XLPE, 3.2% voltage drop limit, 15 kA for 1 s:

| Quantity | Published | Computed |
|---|---|---|
| Operating temperature | 40.47 °C | 40.47 °C |
| Voltage drop (3x630) | 12.49 V / 3.12% | 12.49 V / 3.12% |
| K at 45→250 °C | 167.4 | 167.38 |
| Minimum fault area | 46.77 mm² | 46.78 mm² |
| Earth area before rounding | 472.5 mm² | 472.5 mm² |

**Example 2** — 690 V, 75 kW at pf 0.9, 5 m, high-temperature copper:

| Quantity | Published | Computed |
|---|---|---|
| Design current | 69.73 A | 69.73 A |
| Voltage drop | 0.361 V | 0.3607 V |
| K at 50→250 °C | 164.7 | 164.66 |
| Minimum fault area | 33.04 mm² | 33.04 mm² |

### Where the engine disagrees with example 1, and why

Driven end-to-end, the engine returns **3 x 500 mm²** where the paper concludes
3 x 630 mm². This is not an error — the paper steps from 2x400 straight to 3x630
and never evaluates 500 mm². Enumerating the candidates:

| Candidate | Capacity | Voltage drop | Verdict |
|---|---|---|---|
| 2 x 500 | 1446 A | 5.02% | Fails 3.2% limit |
| 2 x 630 | 1640 A | 4.24% | Fails 3.2% limit |
| **3 x 500** | **2169 A** | **3.15%** | **Smallest passing** |
| 3 x 630 | 2460 A | 2.75% | Passes, larger than needed |

Three runs are genuinely required, and 500 mm² is the smallest size that works at
three runs. The engine finds the more economical valid answer.

## Limitations

- **Not a substitute for the standard.** All six reference tables are currently
  unverified against a printed standard — run `as3008.verification_report()`.
  The earth sizes and the large conductor voltage drop matter most.
- Two open questions on the earth table, recorded in `reference_tables.json`:
  whether AS/NZS 3000 Table 5.1 specifies aluminium earth sizes at all, and what
  its real upper bound is (secondary sources say 120 mm² copper, the encoded
  data runs to 630 mm²).
- Grouping factors cover a single layer touching on a tray or ladder. Multiple
  tiers, mixed spacing and enclosed grouping are not modelled.
- Soil thermal resistivity and burial depth are not modelled; buried ratings are
  the catalogue values at their own reference conditions.
- Only the three cable types in `cable_catalog.json` that carry current ratings
  are selectable. Reactance is only tabulated for `XLPE_SDI_CU`; the rest fall
  back to a construction-based nominal.
- Conduit sizing cannot return medium-duty conduit — those columns were cut off
  in the captured source images.
- Clause 3.5.2 Exceptions 2 and 3, which permit a reduced neutral, are not
  applied — the engine never sizes a neutral below its active.
- MCB trip multiples use the upper limit of each curve's band (B 5x, C 10x,
  D 20x). MCCB-specific trip curves are not modelled.

## Five standards, two modes

`standards.py` carries a profile per standard: its reference ambient and soil
model, its installation vocabulary, its voltage drop limits, whether an IEC
60909 voltage factor applies, and its units. Design current, derating,
operating temperature, voltage drop and the adiabatic short-circuit check are
common to all four, so there is one engine rather than four.

| Standard | Reference | Methods | Voltage drop | c | Mode |
|---|---|---|---|---|---|
| AS/NZS 3008.1.1 (AU) | 40 °C air, 25 °C soil, 1.2 K·m/W, 0.5 m | 4, Table 3.9 | 5 %, or 7 % from a dedicated on-site substation | 1.0 | **select** |
| AS/NZS 3008.1.2 (NZ) | 30 °C air, 15 °C soil, 1.0 K·m/W, 0.5 m | 10, Table 14 | 5 %, or 7 % substation | 1.0 | check |
| IEC 60364-5-52 | 30 °C air, 20 °C soil, 2.5 K·m/W, 0.7 m | 7, A1–G | 3 % lighting / 5 % other, 6 % / 8 % private | 1.1 | check |
| BS 7671 | 30 °C air, 20 °C ground, 2.5 K·m/W, 0.7 m | 4, A–E | 3 % / 5 %, 6 % / 8 % private | 1.1 | check |
| NEC (NFPA 70) | 30 °C indoor, 40 °C outdoor +33 °C rooftop | 5, 310.16 | ~3 % branch, ~5 % total, advisory only | 1.0 | check |

### The two AS/NZS parts are two standards, not one with a switch

AS/NZS 3008 comes in two parts: **1.1** tabulates typical *Australian*
conditions and **1.2** typical *New Zealand* ones, which are cooler — 30 °C air
against 40 °C, 15 °C soil against 25 °C, and soil thermal resistivity 1.0 K·m/W
against 1.2. Each part has **its own current-carrying capacity tables**, so a
rating read from the Australian Table 3.9 is not valid on the NZ basis and the
NZ part is a separate profile rather than an ambient switch.

An earlier version of this repo had exactly that switch, `Installation(basis="NZ")`,
and it was a trap: it re-referenced the Australian catalogue ratings against a
30 °C base and reported the answer as if it came from the NZ table. The field is
gone; pick `standard="AS3008NZ"` instead.

One consequence worth knowing. The tabulated ambient correction factors held
here cover only 90 °C XLPE on the 40 °C Australian air basis. On every other
basis the closed form stands alone and, as `as3008.ambient_rating_factor`
measures, it runs optimistic by up to 6.5 %. So any result computed off the
Australian basis carries a warning saying so and naming the correction factor
tables to confirm against.

#### What the pairing error actually costs

`reference/compare_au_nz.py` measures it. Applying **either part correctly** to
the same feeder lands on the same size — the parts move the reference ambient
and move their table numbers to match, so they agree about the physics. The
sizing impact comes entirely from pairing a rating with the wrong basis, and
across 895 cases spanning load, length, ambient and grouping:

| Error | Effect | Frequency | Worst case |
|---|---|---|---|
| Table 3.9 rating on the NZ basis | oversized | 41.9 % | 16 → 25 mm² (+56 % area) |
| Table 14 rating on the AU basis | **undersized** | 48.2 % | 25 → 16 mm² (−36 % area) |

The dangerous direction is the more common of the two, which is why the switch
was deleted rather than exposed. Current-carrying capacity is the binding check
in 90 % of those cases, so the reference ambient carries most of the answer.

The Table 14 ratings in that script are **estimated** by scaling Table 3.9 —
this repo holds no NZ ratings. The script says so, bounds the estimate, and has
one function to replace with real Table 14 values. The direction of each error
does not depend on the exact ratio.

The mode column is the honest part. **Select mode** picks the smallest size that
passes every check, and needs a current-carrying capacity table. The only one
held here is Nexans Australia data on the AS/NZS 3008.1.1 basis, so select mode
is that one part only.

**Check mode** verifies a size you nominate against a rating you read out of
your standard's own table, and runs every other calculation on that standard's
rules with the full audit trail. It works under all five.

No ampacity is derived for a standard whose table is absent. Re-referencing the
AS/NZS ratings to a 30 °C basis with the ambient closed form runs *optimistic*
by up to 6.5 % — `as3008.ambient_rating_factor` measures that — and an
optimistic factor undersizes cable. So the tool asks for the number instead of
inventing one, and refuses select mode with a message naming the table to read.

Reference ambients, installation vocabularies and voltage drop limits are
transcribed from ELEK's five calculator pages, captured under `reference/`.
That is a competent third-party implementation rather than the printed
standard, so every profile carries `verified: False` and names the clause to
check against.

## Installation diagrams

An installation method is a picture before it is a word: "unenclosed spaced" and
"enclosed in conduit" differ by how much still air surrounds the conductor,
which is exactly what sets the tabulated rating. `install_diagrams.py` draws
twelve arrangements as inline SVG — spacing, the surface, the enclosure, the
soil and the depth — on a shared viewBox with a reserved caption band, themed
through CSS custom properties so they work in light and dark. Every standard's
methods name one of these keys, and `test_api.py` fails if any method points at
a diagram that does not exist.

## The web tool

```
python3 server.py          # then open http://127.0.0.1:8765
```

Standard library only, so there is no install step. It is a thin front end:
every number comes from the engine, and the page adds no engineering of its own
beyond matching the chosen size against the catalogues.

| Route | What it is |
|---|---|
| `/` | The calculator, with the standard selector and the method pictures |
| `/docs` | Swagger UI |
| `/openapi.json` | OpenAPI 3.1 description |

Declaring a protective device is what turns the earth fault loop check on;
without one the page says so rather than quietly reporting three checks as four.

## REST API

Nine operations, described at `/openapi.json` and browsable at `/docs`.

| | |
|---|---|
| `POST /api/size` | Select the smallest passing conductor. AS/NZS only |
| `POST /api/check` | Check a size you nominate. All five standards |
| `GET /api/standards` | All five profiles, with method ids and diagram keys |
| `GET /api/standards/{id}` | One profile |
| `GET /api/cable-types` | Catalogue families and the sizes held |
| `GET /api/diagrams` | Every diagram as inline SVG, keyed |
| `GET /api/diagrams/{key}` | One diagram as an `image/svg+xml` response |
| `GET /api/meta` | Everything the UI needs in one call |
| `GET /api/health` | Liveness and a summary of the loaded data |

A deliberate refusal is a 400 with an actionable message, not a 500. Swagger UI
is the one thing that needs the network, loaded from a pinned CDN build; the API
and the calculator work offline, and `/docs` says so if the bundle fails to
load.

```bash
curl -sS -X POST localhost:8765/api/check -H 'Content-Type: application/json' \
  -d '{"standard":"BS7671","method":"C","area_mm2":95,
       "tabulated_rating_a":270,"rating_value":90,"voltage_v":400,
       "route_length_m":60,"vd_supply":"private"}'
```

## MCP server

```
claude mcp add cable-sizing -- python3 /ABS/PATH/cable-sizing/mcp_server.py
```

Standard library only: JSON-RPC 2.0 over stdio, no SDK to install or keep in
step. Full setup and client configuration are in `MCP.md`. Five tools — `size_cable`, `check_cable_size`, `list_standards`,
`list_cable_types`, `get_installation_diagram` — and three resources, all
calling the same `service.py` as the web UI, so an agent and a person get the
same answer to the same question.

An agent that asks for a size under a standard whose table is absent gets a tool
error naming the table to read, rather than a plausible number.

## Tests

```
python3 test_cable_sizing.py     # 150 checks, the engine
python3 test_api.py              # 129 checks, everything around it
```

`test_api.py` pins the two properties that matter most: that adding the
standards layer did not move an AS/NZS answer, and that no standard whose rating
table is absent can produce a size.

## Two manufacturer catalogues, on different footings

The tool draws on two catalogues and keeps them visibly separate, because what is
public about them differs in a way that matters.

**Nexans** (`../cables/cable_catalog.json`) publishes per-size current ratings,
AC and DC resistance, reactance, overall diameter and mass. That is what a sizing
calculation needs, so this catalogue *drives* the sizing.

**Tricab** (`tricab_families.json`, 143 families captured 2026-09-02) publishes
family codes, construction, rated voltage, conductor temperature rating and
conductor material. It does **not** publish any per-size electrical data: current
ratings, resistance, reactance, diameter, mass and bending radius all sit behind
a trade login, their TriCalc sizing tool sits behind the same login, and their
datasheet PDFs are served through a per-session token a logged-out session cannot
complete. Verified 2026-09-02.

So Tricab families are offered as a **construction match** against a size the
engine has already chosen, and never as a sizing input. No Tricab ratings are
recorded anywhere in this repo, because guessing them would defeat the purpose of
having a provenance table at all. Closing that gap needs a Tricab trade account;
with one, `reference/build_tricab_families.py` is the place to extend.
