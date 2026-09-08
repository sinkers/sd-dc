# Review: ELEK Cable Pro Web against our AS/NZS 3008 engine

Reviewed <https://elek.com/calculators/cable-sizing-as> on 2026-09-02 and
cross-checked its published calculation against `as3008.py` and
`cable_sizing.py`.

ELEK is worth reviewing rather than merely reading because their calculator
prints every intermediate quantity of a worked example *and* the equation behind
each one. That makes it an independent implementation to check ours against, not
just another opinion about the standard.

Captured evidence:

| File | What it is |
|---|---|
| `reference/elek-cable-sizing-as.txt` | Full page text, including all equations and the worked example |
| `reference/elek-calculator.png` | Screenshot of the calculator in its default state |
| `reference/compare_elek.py` | Runnable cross-check, 10 quantities |

Reproduce with `python3 reference/compare_elek.py`.

## Access note

The page returns 403 to a headless browser behind a Cloudflare Turnstile
challenge, and loads in a headed one. That is bot management, not an objection
to being read: `elek.com/robots.txt` names `ClaudeBot`, `anthropic-ai`,
`GPTBot`, `CCBot`, `Google-Extended`, `PerplexityBot` and `cohere-ai` each with
an **empty** `Disallow:`, which is allow-all. No `Content-Signal` is served.

## Their worked example

100 A at pf 0.9 lagging, single phase 230 V, 50 m, PVC V-75 copper single core,
unenclosed spaced (Table 3.9), ambient 40 °C, tabulated rating 187 A, correction
factor 1.00, fault level 3 kA, t = 0.1 s. They report 50 mm² active, 50 mm²
neutral, 16 mm² earth.

## What agrees

Every formula we share with them agrees to better than 0.2 %:

| Quantity | Ours | ELEK | Δ |
|---|---|---|---|
| Operating temperature | 50.0089 °C | 50.01 °C | −0.00 % |
| Voltage drop | 4.3163 V | 4.32 V | −0.09 % |
| Voltage drop percent | 1.8767 % | 1.88 % | −0.18 % |
| K, phase (Cu 50.01 → 160 °C) | 129.0178 | 129.02 | −0.00 % |
| K, earth (Cu 40 → 160 °C) | 135.9023 | 135.90 | +0.00 % |

The two K values are the strongest result here. Our `k_constant()` derives K
from conductor physics rather than reading it from a table, and it reproduces
both of ELEK's published constants exactly. It also pins down two things they do
not state outright: their **phase** K is taken at the conductor's *operating*
temperature (50.01 °C, their own reported figure), and their **earth** K is
taken at *ambient* (40 °C), which is right because an earth conductor carries no
load current and so sits at ambient before the fault.

Feeding ELEK's own method through our primitives also reproduces their network
impedance (0.0843 Ω), fault current (1988.6 A vs 1988.89 A) and minimum phase
area (4.874 mm² vs 4.87 mm²).

## What differs

### 1. The fault loop omits the return conductor on single-phase circuits

`cable_sizing.py:404` builds the fault path from the phase conductor's
impedance once:

```python
z_cable_ohm = math.hypot(r, x) * route_length_m / 1000.0 / parallel
```

ELEK's phase-to-neutral fault sums the active **and** the neutral, because a
single-phase fault current goes out along one and back along the other:

```
Ipn = c·Vpp / (Zn + sqrt(Ral,ref² + Xal²) + sqrt(Rnl,ref² + Xnl²))
```

On their example we read **+17.0 %** on the fault current and **+17.1 %** on the
required area. Higher fault current means a larger required area, so this
oversizes rather than undersizes — but it is still wrong, and it is wrong by a
material amount.

For a three-phase symmetrical fault, counting the phase conductor once is
correct, so this affects single-phase and DC circuits only.

### 2. No IEC 60909 voltage factor (c = 1.1)

ELEK applies `c = 1.1` to both the network impedance and the driving voltage.
We apply neither. The two uses do not cancel once cable impedance is in the
denominator, and on a three-phase fault this runs the *opposite* way to
finding 1: at 415 V, 50 kA and 10 m of 95 mm² we read 32 430 A against ELEK's
33 500 A, i.e. **−3.2 %**. That is the one difference that makes us less
conservative rather than more.

### 3. Fault resistance is taken at operating temperature, not ambient

We resolve resistance once, at the rounded-up operating temperature column, and
use it for both the voltage drop and the fault calculation. ELEK uses two
values: 0.433 Ω/km at operating temperature for voltage drop, and 0.418 Ω/km at
*ambient* for the fault. Minimum resistance maximises fault current, which is
the conservative choice for a withstand check.

### 4. Resistance temperature is rounded up rather than interpolated

`round_to_temp_column()` rounds the operating temperature up to the next
tabulated column (45/60/75/90/110 °C). ELEK interpolates between the bracketing
columns — their output names both ("Col. no. (min. temp.) 1, Col. no. (max.
temp.) 5"). Ours is conservative on voltage drop. It also perturbs K: at
t_op = 50.01 °C we would use the 60 °C column and get K = 122.02, where ELEK's
un-rounded 50.01 °C gives 129.02.

### 5. No protective-device coordination check

ELEK checks the three coordination zones from AS/NZS 3000, none of which we
implement:

- Zone A: `IN ≥ IB` and `IN ≤ IZ`, with fuses further limited to `IN ≤ 0.9·IZ`
- Zone B: `I2 ≤ 1.45·IZ` for circuit breakers, `1.6·IZ` for fuses
- Zone C: `ISCB ≥ ISC`

We use a declared device only for the earth fault loop check. A cable can pass
all four of our checks and still be improperly protected.

## Does any of this change a selected size?

Only if the short-circuit check is the binding one. Swept across 315 sizeable
three-phase cases (50–2000 kW, 10–400 m, 10/25/50 kA, 40/45/50 °C ambient,
4 grouped circuits), the tightest check was:

| Binding check | Cases | Share |
|---|---|---|
| Current capacity | 236 | 74.9 % |
| Voltage drop | 63 | 20.0 % |
| Short circuit | 16 | 5.1 % |

All 16 short-circuit-limited cases were 10 m runs with small loads and high
fault levels — which is exactly the condition ELEK's own text names ("rarely
dictates the active size for short cable runs carrying a small load current and
where the supply's fault level is high"). Our engine arrived at that
independently.

So findings 1–3 are confined to about 5 % of three-phase cases, and within that
5 % some of those selections sit on margins as thin as 1.3 %.

## Where ELEK is a useful source of verified data

Five of our reference tables are still marked `unverified` in
`reference_tables.json`, and the page carries printed values for several:

- Voltage drop limits: 5 % general, 7 % for a dedicated on-premises substation,
  plus design guidance of 0.5 % consumers mains, 1.5–2 % submains, 2.5 % final
  subcircuits. Voltage *rise* limited to 2 % (AS/NZS 4777.1:2016), DC voltage
  drop to 3 % (AS/NZS 5033:2014). Our clause 3.6.2 table already carries the
  5 % and 7 % figures and is marked verified; the AC rise and DC limits are new
  and we hold neither.
- Table basis: ambient air 40 °C, soil 25 °C, soil thermal resistivity
  1.2 K·m/W, burial depth 0.5 m. Consistent with `AMBIENT_BASIS["AU"]` and with
  the catalogue's ambient derating starting at 45 °C.
- Minimum 4 mm² for conductors in parallel. Already enforced at
  `cable_sizing.py:359`.
- Correction factors are in AS/NZS 3008.1 Tables 3.33–3.48, and resistance and
  reactance in Tables 4.5–4.11 and 4.1–4.2. Useful pointers for closing out
  `ac_dc_resistance_ratio` and `reactance_ohm_km`, but the values themselves are
  not on the page.

## Recommendation, in order

1. Add the neutral return conductor to the fault loop for single-phase and DC
   circuits (finding 1). Largest error, and it currently oversizes.
2. Add `c = 1.1` to the fault calculation (finding 2). Only finding that makes
   us less conservative.
3. Use ambient-temperature resistance for the fault path (finding 3).
4. Add the Zone A/B/C coordination checks (finding 5). Real compliance gap, but
   it needs a protective device database to be worth much.
5. Leave the temperature rounding (finding 4) alone unless sizes prove
   sensitive to it. It is conservative and it is cheap.

None of these were changed as part of this review: the engine is untouched, and
all 150 existing checks still pass.
