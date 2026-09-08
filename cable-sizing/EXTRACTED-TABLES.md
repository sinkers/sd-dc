# Extracted reference data — AS/NZS 3000:2018

Capture record for reference data read from the printed standard, transcribed
into `reference_tables.json` on **2026-08-21**.

**Source edition: AS/NZS 3000:2018** (*Electrical installations — Wiring Rules*).
Every table below was read from that edition. Data attributed to any other
standard is marked as such and is **not** verified.

Machine-readable form: `reference_tables.json`. Each block there carries
`standard`, `edition`, `verified`, `source` and `note` fields.
`as3008.verification_report()` prints the status of all of them.

---

## 1. Verified — AS/NZS 3000:2018

| # | Reference | Title | Captured | Used for |
|---|---|---|---|---|
| 1 | Table 3.2 | Limiting temperatures for insulated cables | 21 insulation types, 3 limits each | Rating basis, operating temperature ceiling, short-circuit initial temperature |
| 2 | Table 3.3 | Nominal minimum cross-sectional area of conductors | 7 wiring-system rows | Absolute floor on conductor size |
| 3 | Clause 3.5.2 | Neutral conductor | Full rule set incl. harmonics | Neutral sizing |
| 4 | Table 3.4 | Conductor colours for installation wiring | 4 functions | Cable schedules, 3D model colours |
| 5 | Clause 3.6.2 | Voltage drop — value | 5% / 7% / 11% limits | Voltage drop limit |
| 6 | Clause 3.6.3 | Conductors in parallel | Method statement | Confirmed existing parallel treatment |
| 7 | Table C8 | Voltage drop — simplified method | 12 sizes × 2 phase modes | **Independent cross-check**, reactance derivation |
| 8 | Clause C4.1/C4.2 | Simplified voltage drop, background and examples | Formulas C1, C2 + 2 worked examples | Confirmed cumulative percentage method |
| 9 | Table C10 | Single-core sheathed cables in conduit | 2 families, 21 sizes | Conduit sizing |
| 10 | Table C11 | Two-core and earth cables in conduit | 3 families, 14 sizes | Conduit sizing |
| 11 | Table C12 | Four-core and earth cables in conduit | 3 families, 18 sizes | Conduit sizing |
| 12 | Clause 5.3.2.1.2 | Aluminium conductors as earthing conductors | 5 conditions + exception | Aluminium earth compliance |

### 1.1 Table 3.2 — Limiting temperatures

Three limits per insulation: **normal use**, **maximum permissible**, **minimum
ambient**. Current ratings derive from *normal use*, so that is the engine's
rating basis.

| Family | Types | Normal use °C |
|---|---|---|
| Thermoplastic | V-75, HFI-75-TP, TPE-75, V-90, HFI-90-TP, TP-90, V-90HT | 75 |
| Elastomeric | R-EP-90, R-CPE-90, R-HF-90, R-CSP-90 | 90 |
| Elastomeric | R-HF-110, R-E-110 | 110 |
| Elastomeric | R-S-150 | 150 |
| XLPE | X-90, X-90UV, X-HF-90 | 90 |
| XLPE | X-HF-110 | 110 |
| MIMS | MIMS | 100 (250 max permissible) |
| Other | PE, LLDPE | 70 |

Two findings:

- **V-90 is rated 75 °C in normal use**, not 90 °C — as are V-90HT (105 °C max),
  HFI-90-TP and TP-90. The higher figure applies only where the cable is
  protected against severe mechanical damage. Confirmed all 11 normal-use values
  previously encoded from secondary sources.
- **`X-110` does not exist in Table 3.2.** The standard lists X-HF-110. Kept as an
  alias since catalogues and sizing tools use it.

Short-circuit limit temperatures are **not** in Table 3.2 — they come from
AS/NZS 3008 Table 53 (2017) / Table 5.2 (2025) and **remain unverified**,
currently assigned by family (thermoplastic 160 °C, thermoset 250 °C).

### 1.2 Table 3.3 — Minimum conductor size

| Wiring system | Use | Material | mm² |
|---|---|---|---|
| Insulated conductors | Socket-outlets | Copper | 2.5 |
| Insulated conductors | Other circuits | Copper | 1 |
| Insulated conductors | Signal and relay control | Copper | 0.5 |
| Bare conductors | — | Copper | 6 |
| Insulated flexible conductors | — | Copper | 0.75 |
| Aerial wiring | — | Copper | 6 |
| Aerial wiring | — | Aluminium | 16 |

Exception 1 allows smaller conductors on socket-outlet subcircuits based on
suitability. Exception 2: the table does not limit extra-low voltage or
switchboard wiring.

### 1.3 Clause 3.5.2 — Neutral conductor

- **Single-phase two-wire**: neutral capacity ≥ the associated active, or the
  total current where there is more than one active.
- **Multiphase**: neutral capacity ≥ that of the largest associated active. Where
  more than one active is connected to a phase, the "associated active" is the
  **sum of the cross-sectional areas** on that phase.
- **Harmonics**: where a circuit supplies a substantial harmonic-generating load
  (the clause names computers, fluorescent lighting, soft starters and variable
  speed devices), the third and higher order harmonic current is **added to the
  maximum out-of-balance load**, taken as **100% of the highest load-generating
  harmonic current on any phase**. A harmonic load ≥ **40%** of the total load on
  any single phase is "substantial" (NOTE 1). Third harmonics are additive to the
  50 Hz current, so the neutral may need **greater** capacity than the actives
  (NOTE 2).
- **PEN conductors**: comply with the above *and* be no smaller than an earthing
  conductor per clause 5.3.3.

Exceptions 1–3 permit a *reduced* neutral (abnormal out-of-balance disregarded; a
detection device fitted; predominantly multiphase load). **Not implemented** —
the engine never sizes a neutral below its active.

### 1.4 Table 3.4 — Conductor colours

| Function | Insulation colour |
|---|---|
| Protective earth | Green/yellow |
| Equipotential bonding | Green/yellow |
| Neutral | Black or light blue |
| Active | Any colour other than green, yellow, green/yellow, black or light blue |

Recommended actives: red or brown single-phase; red, white or blue multiphase.
Green/yellow must have one colour covering 30–70% of the surface. In New Zealand
domestic installations the only permitted neutral colour is black.

### 1.5 Clauses 3.6.2 and 3.6.3 — Voltage drop

**5%** from the point of supply to *any* point in the installation. Exceptions:

- **Exception 1** — final subcircuits with distributed load may use half the
  protective device rating as the design current.
- **Exception 3** — **7%** where the point of supply is the LV terminals of a
  substation on the premises and dedicated to the installation.
- **Exception 4** — stand-alone systems, total 11% below nominal.

Design current need not exceed the connected load, the maximum demand, or the
protective device rating. Motor-starting transients are excluded.

**Clause 3.6.3** — parallel conductors are assessed as the drop in **one**
conductor carrying the circuit current divided by the number in parallel. This
confirmed the treatment the engine already used.

### 1.6 Table C8 and clause C4 — Simplified voltage drop

Formulas as printed:

```
C1:  Vd  = (L × I × Vc) / 1000
C2:  %Vd = (L × I × Vc) / (10 × Vo)
     (L × I) / %Vd = (10 × Vo) / Vc      [units: Am per %Vd]
```

where `Vc` is cable voltage drop in mV/A·m, tabulated in AS/NZS 3008.1.

Clause C4.1 states percentage drops for consumer mains, submains and final
subcircuits **"to be added together, regardless of whether it is single-phase or
three-phase."** This is the explicit basis for `voltage_drop_budget()`.

Table C8 — Am per %Vd, PVC/PVC at 75 °C, 230 V single-phase and 400 V three-phase:

| mm² | 1-phase | 3-phase | | mm² | 1-phase | 3-phase |
|---|---|---|---|---|---|---|
| 1 | 45 | 90 | | 16 | 818 | 1643 |
| 1.5 | 70 | 140 | | 25 | 1289 | 2588 |
| 2.5 | 128 | 256 | | 35 | 1773 | 3560 |
| 4 | 205 | 412 | | 50 | 2377 | 4772 |
| 6 | 306 | 615 | | 70 | 3342 | 6712 |
| 10 | 515 | 1034 | | 95 | 4445 | 8927 |

This table is used as an **independent cross-check**, not as a data source — the
engine does not read its values.

### 1.7 Tables C10–C12 — Conduit fill

Maximum number of cables per conduit. Captured for **heavy duty rigid UPVC**
(20, 25, 32, 40, 50, 63, 80, 100, 125, 150 mm, with separate AUS and NZ variants
at 80 and 100) and **Corflo** (100 AUS/NZ, 125, 150 mm).

> **Incomplete capture.** The *medium duty corrugated* and *medium duty rigid*
> columns were cut off at the right edge of the source images in all three
> tables and are **not** captured. `min_conduit_size()` therefore cannot return a
> medium-duty conduit.

| Table | Cables | Families captured | Size range |
|---|---|---|---|
| C10 | Single-core sheathed | PVC/PVC V90, XLPE/PVC | 1–16, 25–630 mm² |
| C11 | Two-core and earth | PVC/PVC V90, V75, V90 FLAT | 1–25 mm² |
| C12 | Four-core and earth | PVC/PVC V90, V75, XLPE/PVC | 1.5–120 mm² |

`>100` in the source means more than 100 cables fit; the accessor treats it as
100, which is conservative.

### 1.8 Clause 5.3.2.1.2 — Aluminium earthing conductors

Aluminium **may** be used as an earthing conductor provided:

- (a) conductors of **10 mm² or less shall be solid**;
- (b) **minimum 16 mm²** for main earthing conductors;
- (c) connection methods comply with Section 3;
- (d) installation prevents corrosion of conductor and connections;
- (e) **not installed underground or in damp situations** — *Exception*: permitted
  where designed and suitable for such use.

This answers one of the two open questions on aluminium earths. Note it is clause
**5.3.2.1.2**, distinct from the *sizing* rules at clause 5.3.3.

---

## 2. Captured but not encoded

Read from AS/NZS 3000:2018 and judged out of scope for a data centre sizing
engine. Recorded here so the capture record is complete.

| Reference | Title | Why not encoded |
|---|---|---|
| Table C6 | Simplified protective device selection, 1–25 mm², single-phase | V-90 2C+E final subcircuits; the engine sizes feeders, not domestic-scale final subcircuits |
| Table C7 | Simplified protective device selection, 1–25 mm², three-phase | As above, V-90 4C+E |
| Table C9 | Guidance on loading of points per final subcircuit | Socket-outlet, lighting and appliance point counts — domestic and commercial fit-out, not data centre distribution |
| Table D2 | Force exerted by aerial line conductors | Aerial line sag, tension and pole strength — no aerial distribution in scope |
| Clause 3.7 | Electrical connections | Qualitative workmanship requirements with no numeric data to encode |

Tables C6 and C7 are the most likely of these to be worth adding later, if the
scope extends to final subcircuits.

---

## 3. Still outstanding

| Reference | Standard | Blocks |
|---|---|---|
| **Clause 5.3.3** | AS/NZS 3000:2018 | Earthing conductor **sizing** — the last safety-critical unverified table. Also resolves whether the earth table specifies aluminium sizes at all, and its real upper bound (secondary sources say 120 mm² copper; encoded data runs to 630 mm²). |
| ~~Tables 4.1–4.2~~ | AS/NZS 3008.1.1:2025 | **CLOSED 2026-09-04.** Tables 4.1 to 4.4 read from the printed standard; reactance is now held per construction, formation and insulation, with the spacing correction. |
| ~~Tables 4.5–4.11~~ | AS/NZS 3008.1.1:2025 | **CLOSED 2026-09-04.** Tables 4.5 to 4.13 read from the printed standard. The AC/DC ratio at 630 mm² is **1.197** — neither 1.252 nor 1.120. |
| ~~Table 53 / 5.2~~ | AS/NZS 3008.1.1:2025 | **CLOSED 2026-09-04.** Table 5.2 read from the printed standard. Thermoplastic is **160 °C at or below 300 mm², 140 °C above it** — a size dependence the family assignment did not model — and R-S-150 is 350 °C, not 250 °C. |
| Derating tables | AS/NZS 3008.1.1 | Soil resistivity, burial depth, multi-tier, spacing. |
| Medium duty columns | AS/NZS 3000:2018 Tables C10–C12 | Cut off in the captured images. |

---

## 4. What the capture changed

| Finding | Effect |
|---|---|
| V-90 rates 75 °C in normal use | Confirmed the existing rating basis; would have been a 20% capacity error if wrong |
| Clause 3.5.2 harmonic rule | Closed a documented gap. A 250 kW PDU at 55% harmonic content takes a 300 mm² active but a **630 mm² neutral** |
| Clause 3.6.2 is cumulative | Revealed that per-segment checking is insufficient; added `voltage_drop_budget()` |
| Clause 3.6.2 Exception 3 | 7% allowance for a dedicated on-site substation — directly applicable |
| Table C8 implied reactance | ~~Multicore reactance is **0.105–0.114 Ω/km** (16–95 mm²), 33% above the 0.08 Ω/km fallback~~ **WITHDRAWN 2026-09-04.** See the correction below |
| Clause C4.2 examples | Reproduce **exactly** — both size selections and all three percentages |
| Clause 5.3.2.1.2 | Aluminium earths are permitted, with conditions now checked |
| Clause 3.5.3 → 5.3.3 | Corrected the earth sizing citation; "Table 5.1" was wrong |

### Correction — the Table C8 reactance back-calculation was wrong

The finding above inferred multicore reactance by subtracting resistance from the
impedance implied by Table C8, and recorded 0.105–0.114 Ω/km over 16–95 mm².
AS/NZS 3008.1.1:2025 **Table 4.1(B)**, read from the printed standard on
2026-09-04, gives **0.0805 Ω/km at 16 mm² falling to 0.0725 Ω/km at 95 mm²**. The
back-calculation runs **30–45% high**, and sits *below* the 0.08 Ω/km fallback it
was said to exceed by 33%, not above it.

Recomputed on the standard's own a.c. resistance (Table 4.7) rather than a
catalogue-derived ratio, the implied figure is not even constant — it runs 0.128
at 16 mm² down to 0.106 at 95 mm². A quantity varying 20% across the range is not
a reactance being recovered.

Table C8 is a simplified single-phase PVC method. It remains a sound end-to-end
cross-check on voltage drop and is no longer treated as a source of reactance.
Reactance now comes from Tables 4.1 to 4.4 in `as3008_impedance_tables.json`.

### Cross-check against Table C8

Resistance-only comparison (X = 0), showing where reactance starts to matter:

| Size range | Agreement | Reading |
|---|---|---|
| 2.5–25 mm² | within **0.7%** | Resistance model confirmed |
| 35–95 mm² | +1.6% to +9.4% high | Reactance is not negligible; closes when X ≈ 0.107 Ω/km is included |
| 1–1.5 mm² | +12% to +16% high | Table C8's `Vc` exceeds what IEC 60228 class 2 resistance predicts; unexplained, and below the sizes this engine targets |
