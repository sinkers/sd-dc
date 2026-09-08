# Methodology Section 4 — Rating factors and current-carrying capacity

**Revision** B · **Date** 7 September 2026 · **Status** Working engineering
specification. Not an approved design.

**Scope.** Conventions and verification data for the step that converts a cable
type, size and installation arrangement into an allowable current, and compares
it against the design current produced by Methodology Section 3. Covers the base
capacity lookup, the correction factor set, band lookup direction, reference
conditions, and harmonic treatment for a.c. circuits at 0.6/1 kV.

**Not covered.** Design current (Methodology Section 3), voltage drop
(Section 5), short circuit (Section 6), earth fault loop (Section 7). d.c.
circuits, MIMS, aerial and flexible-cord ratings are named in §4.11 but not
specified here. Cyclic and short-term ratings remain out of scope per Section 1.

**Consumed standard.** AS/NZS 3008.1.1:2025, Section 3 (Current carrying
capacity), fourth edition, published 19 December 2025. Clause and table numbers
in this section refer to that document unless prefixed "M" for Methodology.

**Naming.** "M4" is this section. "S3" is Section 3 of AS/NZS 3008.1.1:2025,
which M4 consumes. Methodology Section 3 (Design Current) is "M3".

## 4.0 Changes at Rev B, and what this supersedes

This section supersedes nothing in code. `src/dame_cable/rating_factors.py` and
`src/dame_cable/current_capacity.py` are retained, with their public API
unchanged — `build_factor_set()`, `harmonic_treatment()`,
`tabulated_capacity()`, `capacity()`, `check_capacity()`. No new modules are
proposed. Rev B changes the data contract and four conventions:

1. `arrangement` becomes a real key on the base rating table, with four air
   arrangements for single-core tables and three for multicore (§4.4). The
   current single-column engine holds one column pair of ten and overstates six
   of the eight tabulated non-touching arrangements.
2. `cores_loaded` is removed from the `ccc` key. It is not an axis of any base
   table (§4.4.3).
3. Two of the seven planned correction factor families do not exist. Thermal
   insulation and solar radiation are base-rating columns, not factors (§4.6).
4. The harmonic band structure is four bands, not three (§4.8).

Six findings of fact that change the numbers are at §4.12.

## 4.1 Provenance of every figure in this section

| Class | Marking | Meaning |
|---|---|---|
| Standard, table value | `[T3.x c.n]` | Read from AS/NZS 3008.1.1:2025 Table 3.x, column n, on 7 September 2026 |
| Standard, clause rule | `[Cl 3.x]` | Stated requirement or note in the clause named |
| Standard, published answer | `[App A]` `[App B]` | Worked example with the standard's own arithmetic |
| DAME convention | `[M4 rule]` | Not in the standard. A DAME decision, recorded here so it is auditable |
| Third-party calculator | `[Tricab]` `[jCalc]` `[ELEK]` | Cross-check only. Never a source of truth |

No figure in this section is unmarked. Any figure that appears in the CSV
datasets without a marking is a defect.

## 4.2 Reference conditions

All base tables in the S3 3.9–3.20 family carry one headnote in the same form,
and the reference conditions do not vary within the family. `ccc_reference.csv`
takes one row per base table with these four fields.

| Field | Value | Source |
|---|---|---|
| Reference ambient, air | 40 °C | `[Cl 3.5.3]`, and each table headnote |
| Reference ambient, soil | 25 °C | `[Cl 3.5.3]`, and each table headnote |
| Reference depth of laying | 0.5 m | `[Cl 3.5.4]` |
| Reference soil thermal resistivity | 1.2 °C·m/W | `[Cl 3.5.5]` |
| Maximum conductor temperature | per table, below | table headnote |

Maximum conductor temperature by table: 75 °C for the thermoplastic tables
(3.9, 3.12, 3.15, 3.18); 90 °C for the cross-linked 90 °C tables (3.10, 3.13,
3.16, 3.19); 110 °C for the cross-linked 110 °C tables (3.11, 3.14, 3.17, 3.20).
The headnote wording is identical across the family: maximum conductor
temperature, then "Reference ambient: 40 °C in air, 25 °C in ground".

**R-REF-1.** Reference ambient does not differ between the air and soil table
families. One headnote carries both datums, for every table in the family. The
Rev A open item is closed. `[Cl 3.5.3]`

**R-REF-2.** Reference depth and reference soil resistivity are properties of
the buried columns only. They are recorded on every table row for uniformity,
but a factor keyed to them is inadmissible against an air arrangement (§4.6.2).

## 4.3 Base rating table selection

**R-TBL-1.** The base table is selected by (conductor grouping, insulation
material class), in that order. The insulation designation determines the
material class, not the temperature the cable is marketed at.

| Conductor grouping | Thermoplastic 75 °C | Cross-linked 90 °C | Cross-linked 110 °C |
|---|---|---|---|
| Two single-core | 3.9 | 3.10 | 3.11 |
| Three single-core | 3.12 | 3.13 | 3.14 |
| 2-core cable | 3.15 | 3.16 | 3.17 |
| 3-core and 4-core cable | 3.18 | 3.19 | 3.20 |

The 110 °C tables carry designations R-HF-110, R-E-110 and X-HF-110. X-HF-110 is
the DAME standing case; the three designations share one table.

**R-TBL-2.** Rows are tabulated conductor sizes. Every row of every table
carries a Cu value and an Al value, in that order, as adjacent columns. A dash
means the combination is not tabulated and is not available — it is not zero and
not a floor to interpolate onto.

**R-TBL-3.** Tables 3.21–3.26 are the d.c. family, 3.27–3.28 flexible cords and
high-temperature cables, 3.29–3.30 MIMS, 3.31–3.32 aerial. None are in M4 scope.
A request that resolves to one of these raises, it does not fall back to the
a.c. tables. `[M4 rule]`

## 4.4 `arrangement` as a key on the base table

This replaces the single stored column. The mapping from arrangement to column
is **per-table data, not code**: single-core and multicore tables do not share a
column order, and one arrangement label ("conduit in air") denotes a different
enclosure between the thermoplastic and cross-linked tables.

### 4.4.1 Single-core tables — 3.9, 3.10, 3.11, 3.12, 3.13, 3.14

Confirmed by direct reading of the column headers of 3.11, 3.12 and 3.14.

| `arrangement` | Group header | Sub-header | Col Cu | Col Al | Geometry `[T3.5]` |
|---|---|---|---|---|---|
| `air_spaced` | Unenclosed | Spaced | 1 | 2 | Cables separated by D between surfaces, 0.3D clear of a vertical surface |
| `air_spaced_from_surface` | Unenclosed | Spaced from surface | 3 | 4 | Cables **touching each other**, trefoil or flat, held 0.3D clear of a vertical surface and D clear of a surface below |
| `air_touching` | Unenclosed | Touching | 5 | 6 | Cables touching each other and clipped direct to the surface |
| `air_exposed_to_sun` | Unenclosed | Exposed to sun | 7 | 8 | Cables touching, on a surface, in direct solar radiation |
| `enclosed_conduit_in_air` | Enclosed | Metallic conduit in air (3.10, 3.11, 3.13, 3.14) / PVC conduit in air (3.9, 3.12) | 9 | 10 | One circuit in one conduit in air |
| `insulation_partial` | Surrounded by thermal insulation | Partially | 11 | 12 | |
| `insulation_complete` | Surrounded by thermal insulation | Completely | 13 | 14 | Not tabulated for three single-core; dashes throughout |
| `buried_direct` | Buried direct in ground | — | 15 | 16 | |
| `buried_conduit_shared` | Buried in PVC underground conduit | — | 17 | 18 | All cables of the circuit in one conduit or duct `[App A]` |
| `buried_conduit_single_way` | Buried in PVC underground conduit | — | 19 | 20 | Each cable in its own single-way duct, ducts in trefoil `[App A]` |

The two buried-conduit pairs are distinguished only by their reference drawing
in the printed table. Appendix A.1 fixes them: Method A, "all cables in one
conduit or duct", cites Column 17; Method C, "trefoil groups of single-way
underground ducts", cites Column 19. `[App A]`

### 4.4.2 Multicore tables — 3.15, 3.16, 3.17, 3.18, 3.19, 3.20

Confirmed by direct reading of the column headers of 3.17, 3.18 and 3.20.
`air_spaced_from_surface` **does not exist** in this family, and the thermal
insulation block splits unenclosed from enclosed.

| `arrangement` | Col Cu | Col Al |
|---|---|---|
| `air_spaced` | 1 | 2 |
| `air_touching` | 3 | 4 |
| `air_exposed_to_sun` | 5 | 6 |
| `enclosed_conduit_in_air` | 7 | 8 |
| `insulation_partial_unenclosed` | 9 | 10 |
| `insulation_partial_enclosed` | 11 | 12 |
| `insulation_complete_unenclosed` | 13 | 14 |
| `insulation_complete_enclosed` | 15 | 16 |
| `buried_direct` | 17 | 18 |
| `buried_conduit` | 19 | 20 |

**R-ARR-1.** A request for `air_spaced_from_surface` against a multicore table
raises. It does not silently resolve to `air_touching`. `[M4 rule]`

**R-ARR-2.** Tables 3.5 to 3.8 are the authority on which physical installation
is deemed to fall in which column, and they list several installations per
column as "deemed to have the same CCC". The engine stores the column mapping
above; the arrangement-selection rules from Tables 3.5–3.8 are a separate
dataset (`installation_method.csv`), keyed by (installation description) →
(arrangement, CF table). `[Cl 3.1.1]`

**R-ARR-3.** Where a run uses more than one arrangement, the run's capacity is
the **lowest** of the values determined for each arrangement. Exceptions for
short lengths exist and are not implemented. `[Cl 3.4.6]`

### 4.4.3 `cores_loaded` is removed from the `ccc` key

No base table has a loaded-core axis. The number of loaded conductors is
encoded in the *table* — "two single-core", "three single-core", "2-core",
"3-core and 4-core" — and every table is calculated for three loaded conductors
in the three-phase case. A four-loaded-conductor rating is not tabulated; it is
**derived** from the three-loaded-conductor rating by the Table 3.4 harmonic
factor, which is the only mechanism the standard provides:

> the CFs "give the CCC of a cable with four loaded conductors" when applied to
> the three-loaded-conductor value `[Cl 3.5.9]`

Revised key:

```
ccc: key_columns  = ("table", "arrangement", "material", "size_mm2")
     value_column = "current_a"
```

`insulation` and `construction` are dropped as separate keys because R-TBL-1
already resolves them into `table`; retaining them permits two rows to disagree.
`cores_loaded` is dropped outright. The 74 existing tests that assert on
`cores_loaded` fixtures will need their fixtures rewritten; the four-loaded case
moves to `harmonic_treatment()`.

## 4.5 The `DeclaredAs` device — factor admissibility

The M3 Rev B `DeclaredAs` table made double-counting impossible by declaring
what the design current already contained. The same device applies here to the
base rating: a base column already accounts for certain influences, and a factor
for an influence the column already carries is **inadmissible**, not merely
redundant.

`build_factor_set()` shall reject an inadmissible factor rather than multiply
by it.

| `arrangement` | Already in the base column | Admissible factor families | Inadmissible |
|---|---|---|---|
| `air_spaced`, `air_spaced_from_surface`, `air_touching` | 40 °C air | ambient air (3.44), grouping in air (3.33–3.35), harmonic (3.4), drum/reel (3.3) | ambient soil, depth, soil resistivity, solar, thermal insulation |
| `air_exposed_to_sun` | 40 °C air **and direct solar radiation** | ambient air (3.44) on measured ambient, grouping in air, harmonic | **solar uplift of any kind**, including the Cl 3.5.8(b) +20 °C proxy; ambient soil, depth, resistivity, insulation |
| `enclosed_conduit_in_air` | 40 °C air, the conduit | ambient air (3.44), grouping (3.33), harmonic | as for air arrangements, plus any second enclosure factor |
| `insulation_partial*`, `insulation_complete*` | 40 °C air, **the thermal insulation** | ambient air (3.44), harmonic | **thermal insulation factor of any kind**; grouping is undefined and raises |
| `buried_direct` | 25 °C soil, 0.5 m depth, ρ 1.2 | ambient soil (3.45), depth (3.46), soil resistivity (3.48), grouping buried (3.36–3.39), harmonic | ambient air, solar, insulation, air grouping |
| `buried_conduit_shared`, `buried_conduit_single_way`, `buried_conduit` | 25 °C soil, 0.5 m depth, ρ 1.2, the conduit | ambient soil (3.45), depth (3.47), soil resistivity (3.48), grouping in enclosures (3.40–3.43), harmonic | ambient air, solar, insulation, air grouping, depth table 3.46 |

**R-ADM-1.** The depth family splits by arrangement: Table 3.46 applies to
cables buried direct, Table 3.47 to cables in underground wiring enclosures.
They are not interchangeable and carry different axes — 3.46 is keyed by
conductor size band, 3.47 by single-core versus multicore. `[T3.46, T3.47]`

**R-ADM-2.** Ambient correction uses Table 3.44 for air and heated concrete
slabs, Table 3.45 for cables buried direct or in underground wiring enclosures.
Selecting the table by arrangement, not by the caller, is what prevents an air
cable being corrected off the soil datum. `[Cl 3.5.3]`

**R-ADM-3.** Solar radiation is not a correction factor. Where the cable type
is in the 3.9–3.20, 3.31 or 3.32 family, the exposed-to-sun rating is a base
column and no uplift applies. Only for cable types **outside** those tables may
solar be approximated, by taking a Table 3.44 factor at 20 °C above the
measured ambient. That path is out of M4 scope and raises. `[Cl 3.5.8]`

**R-ADM-4.** Thermal insulation is not a correction factor. Contact is
expressed by selecting the partially or completely surrounded column.
`[Cl 3.5.7]`

**R-ADM-5.** Factors, once admissible, combine multiplicatively against the
base capacity. Appendix A.1 applies them as `base × n_circuits × CF`; Appendix B
applies the harmonic factor as a division of the design current. The two are
algebraically the same comparison and the engine shall implement the
capacity-side form, `I_design ≤ CCC × ΠCF`. `[App A, App B]`

**R-ADM-6.** A single circuit is not automatically CF 1.00. Table 3.14 NOTE 4
requires a Table 3.34 factor for a single circuit on cable tray, applied to
columns 3 and 4, and a Table 3.33 factor for a single circuit fixed to the
underside of a ceiling, applied to columns 5 and 6. A single circuit on an
unperforated tray takes 0.95, on a perforated tray 0.97, on ladder, racks or
cleats 1.00, and under a ceiling touching 0.95. `build_factor_set()` shall
require a support type for every air arrangement, with no default.
`[T3.14 NOTE 4, T3.33, T3.34]`

## 4.6 Correction factor families that exist

Five, not seven. `manifest.csv` shall carry five factor datasets plus Table 3.4.

| Family | Tables | Axes | Datum |
|---|---|---|---|
| Ambient air | 3.44 | conductor temperature × ambient air temperature | 40 °C → 1.00 |
| Ambient soil | 3.45 | conductor temperature × soil ambient temperature | 25 °C → 1.00 |
| Grouping, air | 3.33 (bunched, single layer), 3.34 (single-core on trays and supports), 3.35 (multicore on trays and supports) | see §4.6.1 | 1 circuit → 1.00 for 3.33 items 1–4 only |
| Grouping, buried | 3.36, 3.37 (single-core, single and multiple rows), 3.38, 3.39 (multicore), 3.40–3.43 (underground enclosures) | number of circuits, rows, spacing | — |
| Depth of laying | 3.46 (buried direct), 3.47 (underground enclosures) | depth × size band (3.46), depth × core count (3.47) | 0.5 m → 1.00 |
| Soil thermal resistivity | 3.48 | resistivity × (construction, core count, buried direct or enclosed) | 1.2 °C·m/W → 1.00 |
| Harmonic | 3.4 | third harmonic content band | ≤15 % → 1.00 |
| Drum and reel | 3.3 | out of M4 scope | — |

The ambient tables share a shape: rows are conductor temperature, columns are
ambient temperature. Table 3.44 runs 15 °C to 90 °C in 5 °C steps then 100 °C to
140 °C in 10 °C steps, with rows 150, 110, 90, 80 and 75 °C. Table 3.45 runs
10 °C to 40 °C in 5 °C steps. Values below the datum exceed 1.00 and shall be
applied, not clamped. `[T3.44, T3.45]`

### 4.6.1 Grouping axes differ by table, and the difference is load-bearing

**Table 3.33** — one axis, number of circuits, tabulated at
1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 12, 14, 16, 18 and ≥20, by arrangement item
(bunched in air; bunched on a surface or enclosed; single layer on wall or
floor, touching or spaced; single layer under ceiling, touching or spaced).
The bunched-in-air item terminates at 6 circuits.

**Table 3.34** — 22 items on four axes:

| Axis | Values |
|---|---|
| Support type | unperforated trays, perforated trays, ladder supports/racks/cleats, vertical perforated trays |
| Circuit-to-circuit spacing | **touching** (items 1–11) or **spaced** (items 12–22) |
| Number of rows or tiers | 1, 2, 3 |
| Number of circuits per tier or row | 1, 2, 3 **only** |

Circuit arrangement within the tier is not an axis: every item reads "2 or 3
cables in horizontal formation" or "in vertical formation". Trefoil is not
distinguished (OI-4.12).

**R-GRP-1.** Table 3.34 tabulates no more than three circuits per tier. A
fourth circuit per tier is not off the top of a band — it is outside the table.
The engine raises and the case goes to IEC 60287 calculation. `[T3.34]`

**R-GRP-1a.** Circuit-to-circuit spacing is a required input, not a default.
"Spaced" carries the Table 3.33 NOTE 5 meaning: a clearance of one cable
diameter between the surfaces of adjacent cables, taken on the largest cable
diameter where sizes differ. At one circuit per tier the two branches agree
(0.97 on a perforated tray either way); at two circuits they diverge by 4.5 %
(0.89 touching against 0.93 spaced). `[T3.33 NOTE 5, T3.34]`

**R-GRP-1b.** The Table 3.34 factors are conditional on tray geometry:
vertical spacing of horizontal trays and ladder supports not less than 300 mm,
and horizontal spacing of back-to-back vertical trays not less than 230 mm.
Below either, the table does not apply and the engine raises. These conditions
bind the multi-row cases in particular. `[T3.34 footnotes b, c]`

**R-GRP-1c.** More than one layer of cables on the same tray or ladder support
is outside Table 3.34; Table 3.33 is used instead. `[T3.34 NOTE 1]`

**R-GRP-2.** Earthing conductors, lightly loaded neutrals of three-phase a.c.
circuits, and conductors subject only to momentary loading are not counted in
the circuit count. "Lightly loaded" is loading below 35 % of the neutral's own
CCC, taking single-phase load and harmonics into account. At or above 35 %, the
neutral is placed adjacent to the actives with the same clearance and **is**
counted. `[T3.33 NOTE 2, Cl 3.5.2.3]`

**R-GRP-3.** For single-core arrangements a substantially loaded neutral is
handled as a counted conductor in the group, through R-GRP-2. It is not handled
by Table 3.4, which is restricted to four- and five-core cables (§4.8).

**R-GRP-4.** Grouping correction is not required where cables are grouped over
a limited length: 1 m for sizes below 300 mm² aluminium or below 150 mm²
copper, 3 m at or above those sizes. `[Cl 3.5.2.2(b)]`

**R-GRP-5.** No grouping factor applies where circuits are separated by at
least the minimum spacings of Table 3.2, or, buried, by at least 2 m.
`[T3.33 NOTE 6, Cl 3.5.2.6, Cl 3.5.2.7]`

## 4.7 Band lookup direction

The word "interpolate" does not appear anywhere in AS/NZS 3008.1.1:2025. The
standard states no lookup rule for a value between tabulated entries, in either
the base tables or the factor tables. Every band rule below is therefore a DAME
convention, recorded as such.

**R-BAND-1 (ambient).** Round the ambient temperature **up** to the next
tabulated column. 43 °C air on a 110 °C conductor takes the 45 °C column, CF
0.96, not the 40 °C column, CF 1.00. This is the conservative direction because
the factor decreases as ambient rises. Rev A behaviour is confirmed correct.
Linear interpolation would give 0.976; the step gives 0.96, a 1.6 % margin.
`[M4 rule]`

**R-BAND-2 (grouping).** Round the circuit count **up** to the next tabulated
entry. Rev A rounds down, and rounding down is the **anti-conservative**
direction: the factor decreases as circuits increase, so 11 circuits bunched on
a surface takes 0.45 (the 12-circuit entry), not 0.48 (the 10-circuit entry).
This is a live defect, not a convention to confirm. Note also that circuit
counts 1 through 10 are each tabulated in Table 3.33, so the Rev A worked
example — "5 circuits take the 4-circuit row" — was rounding a value that needs
no rounding. `[M4 rule, T3.33]`

**R-BAND-3 (depth, soil resistivity).** Round depth **up** and soil resistivity
**up** to the next tabulated entry. Both factors decrease as the variable
increases. `[M4 rule]`

**R-BAND-4 (conductor size).** Step, never interpolate. The next larger
tabulated size is selected. A dash is not a value and does not participate in
the step. `[M4 rule]`

**R-BAND-5 (running off the top of a band).** Clamp only where the table itself
declares an open interval — Table 3.33's "≥ 20 circuits" column, and Table
3.4's "> 45 %" row. Everywhere else, running past the last tabulated entry
raises. Table 3.34 beyond 3 circuits per tier, Table 3.44 beyond the last
populated column for the conductor temperature in use, and Table 3.46 beyond
its deepest row all raise. `[M4 rule]`

**R-BAND-6 (below the bottom of a band).** Ambient below the lowest tabulated
column is clamped to the lowest column, which yields a factor above 1.00. It is
not extrapolated. `[M4 rule]`

## 4.8 Harmonic bands and the comparison basis

Table 3.4 has **four** bands, not three, and the fourth reverses the factor
while keeping the neutral basis. The factor and the basis are independent
outputs and `harmonic_treatment()` shall return both.

| Third harmonic content of phase current | Factor | Basis for the comparison | `harmonic_treatment()` |
|---|---|---|---|
| ≤ 15 % | 1.00 | phase current | `(1.00, "phase")` |
| > 15 % and ≤ 33 % | 0.86 | phase current | `(0.86, "phase")` |
| > 33 % and ≤ 45 % | 0.86 | **neutral current** | `(0.86, "neutral")` |
| > 45 % | 1.00 | **neutral current** | `(1.00, "neutral")` |

Source: Table 3.4 rows "0–15", "15–33", "33–45", "> 45" and clause 3.5.9. The
clause text resolves the closed and open edges: the middle regime is "between
15 % and 33 %", the third is "greater than 33 %", the fourth "greater than
45 %". Boundary values 15, 33 and 45 therefore belong to the lower band.
`[T3.4, Cl 3.5.9]`

**R-HRM-1 (neutral current).** Where the basis is neutral, the neutral current
is three times the third-harmonic component of the phase current:
`I_N = 3 × I_phase × THD3`. Appendix B computes 35 × 0.44 × 3 = 46.2 A.
`[App B]`

**R-HRM-2 (what is derated).** The factor is applied to the
three-loaded-conductor base capacity, and the result is the capacity of the
same cable with four loaded conductors. In the 15–33 % band that corrected
capacity is compared against the **phase** current. Above 33 % it is compared
against the **neutral** current, and the phase and neutral conductors are then
sized together on that basis. Above 45 % no factor applies, because the phase
conductors are no longer fully loaded and the reduction in phase heating offsets
the neutral heating. The Rev A open item — phase, neutral, or both — is closed:
one factor, one capacity, and the basis flag selects which current it is
compared against. `[Cl 3.5.9]`

**R-HRM-3 (scope).** Table 3.4 applies only to balanced three-phase circuits
where the neutral is a core of a **four- or five-core cable** of the same
material and cross-sectional area as the phases. It does not apply to three
single-core actives plus a single-core neutral; that case is handled by
R-GRP-2/R-GRP-3. A request outside scope raises. `[Cl 3.5.9]`

**R-HRM-4 (out of scope, named).** Lower factors than Table 3.4 apply, and are
not tabulated, where ninth or twelfth harmonics exceed 10 % of phase current, or
where only two of three phases are loaded, or where phase imbalance exceeds
50 %. The engine raises on a declared imbalance above 50 % rather than returning
a Table 3.4 factor. `[Cl 3.5.9 NOTE 1, NOTE 2]`

**R-HRM-5 (band edge versus physics).** The physical crossover at which neutral
current overtakes phase current is 1/√8 = 35.36 %. The standard's edge is 33 %,
which moves to the neutral basis before the physical crossover and is therefore
conservative by 2.36 percentage points. The standard's edge governs. The
coincidence between 1/√8 and the 35 % "substantially loaded" neutral threshold
of clause 3.5.2.3 is not a stated relationship and shall not be relied on.

## 4.9 What "spaced" means — resolved

The DAME conclusion in Rev A is correct, and the standard carries **both**
geometries as separate arrangements with separate columns.

| | `air_spaced` (cols 1–2) | `air_spaced_from_surface` (cols 3–4) |
|---|---|---|
| Cable-to-cable | separated by D between surfaces | **touching**, trefoil or flat |
| Cable-to-surface | 0.3D clear of a vertical surface | 0.3D clear of a vertical surface, D clear of a surface below |
| Table 3.5 wording | "minimum cable separation in air" | "minimum cable spacings in air" |
| Reactance to use | the 1D-spaced value | the touching-trefoil value |
| Cu 400 mm², X-HF-110 | 1069 A `[T3.14 c.1]` | 902 A `[T3.14 c.3]` |

The reference drawings settle it: the column 1–2 drawing shows three cables
separated from one another and clear of the wall; the column 3–4 drawing shows
three cables touching, as a trefoil bundle or a flat row, held clear of the
wall and of the surface below.

**R-SPC-1.** `air_spaced_from_surface` is a clearance to the surface, and the
cables of the circuit touch. The reactance spacing correction does not apply,
and 0.080 Ω/km — the touching-trefoil value — is correct. Using the 1D-spaced
0.123 Ω/km against this arrangement is a 55 % error in the reactive term.
`[T3.5, T3.14]`

**R-SPC-2.** `air_spaced` is a separation between cables and does require the
spaced reactance. An arrangement that separates the phases carries both the
higher capacity and the higher reactance, and the two shall be keyed off the
same `arrangement` value so they cannot disagree. This is the M4/M5 interlock.
`[M4 rule]`

**R-SPC-3.** The Tricab caveat is retired. 902 A is Table 3.14 column 3 and
837 A is Table 3.14 column 4 at 500 mm². Both third-party figures are the
standard's own table values, not product data. `[T3.14, Tricab]`

## 4.10 Numeric verification cases

Every expected value below is either read directly from a table or computed
from quoted table values by the stated arithmetic. The base cable for the
unenclosed cases is Cu or Al, X-HF-110, three single-core, Table 3.14, at
reference conditions: 40 °C air, 25 °C soil, 0.5 m, 1.2 °C·m/W, single circuit,
no harmonics, unless the case says otherwise.

### 4.10.1 Base lookup, one case per arrangement

| ID | `arrangement` | Material | Size | Expected | Source |
|---|---|---|---|---|---|
| V4-01 | `air_spaced` | Cu | 400 | 1069 A | `[T3.14 c.1]` |
| V4-02 | `air_spaced_from_surface` | Cu | 400 | 902 A | `[T3.14 c.3]`, `[Tricab]` |
| V4-03 | `air_touching` | Cu | 400 | 839 A | `[T3.14 c.5]`, `[jCalc]`, `[ELEK]` |
| V4-04 | `air_exposed_to_sun` | Cu | 400 | 673 A | `[T3.14 c.7]` |
| V4-05 | `enclosed_conduit_in_air` | Cu | 400 | 714 A | `[T3.14 c.9]` |
| V4-06 | `insulation_partial` | Cu | 400 | 571 A | `[T3.14 c.11]` |
| V4-07 | `insulation_complete` | Cu | 400 | not tabulated — raise | `[T3.14 c.13]` |
| V4-08 | `buried_direct` | Cu | 400 | 744 A | `[T3.14 c.15]` |
| V4-09 | `buried_conduit_shared` | Cu | 400 | 628 A | `[T3.14 c.17]` |
| V4-10 | `buried_conduit_single_way` | Cu | 400 | 702 A | `[T3.14 c.19]` |
| V4-11 | `air_spaced_from_surface` | Al | 500 | 837 A | `[T3.14 c.4]`, `[Tricab]` |
| V4-12 | `air_touching` | Al | 400 | 664 A | `[T3.14 c.6]` |
| V4-13 | `air_spaced_from_surface` | Cu | 500 | 1046 A | `[T3.14 c.3]` |

V4-02 against V4-03 pins the spaced-from-surface to touching ratio at
902 / 839 = 1.0751. V4-01 against V4-03 pins the fully-spaced ratio at
1069 / 839 = 1.2741.

An engine holding only column 5 returns 839 A for all of these. Against the
Cu 400 mm² row of Table 3.14 the error is:

| Case | Correct | Error of returning 839 A |
|---|---|---|
| V4-01 `air_spaced` | 1069 A | −21.5 %, conservative |
| V4-02 `air_spaced_from_surface` | 902 A | −7.0 %, conservative |
| V4-04 `air_exposed_to_sun` | 673 A | **+24.7 %, optimistic** |
| V4-05 `enclosed_conduit_in_air` | 714 A | **+17.5 %, optimistic** |
| V4-06 `insulation_partial` | 571 A | **+46.9 %, optimistic** |
| V4-08 `buried_direct` | 744 A | **+12.8 %, optimistic** |
| V4-09 `buried_conduit_shared` | 628 A | **+33.6 %, optimistic** |
| V4-10 `buried_conduit_single_way` | 702 A | **+19.5 %, optimistic** |

Six of the eight tabulated non-touching arrangements are overstated, not
understated. The 7 % conservatism observed against the Tricab spaced case is
the benign end of the range, not representative of it.

### 4.10.2 Grouping and support type

| ID | Case | Arithmetic | Expected |
|---|---|---|---|
| V4-14 | V4-02, single circuit on **perforated** tray, 1 row | 902 × 0.97 | 874.94 A |
| V4-15 | V4-02, single circuit on **unperforated** tray, 1 row | 902 × 0.95 | 856.90 A |
| V4-16 | V4-02, single circuit on **ladder support** | 902 × 1.00 | 902.00 A |
| V4-17 | V4-02, **two** circuits per tier **touching**, perforated tray, 1 row | 902 × 0.89 | 802.78 A |
| V4-17a | as V4-17 but circuits **spaced** 1D | 902 × 0.93 | 838.86 A |
| V4-18 | V4-02, **three** circuits per tier touching, perforated tray, 1 row | 902 × 0.87 | 784.74 A |
| V4-19 | V4-02, two circuits per tier touching, perforated tray, **2 rows** | 902 × 0.85 | 766.70 A |
| V4-20 | V4-02, **four** circuits per tier, any tray | — | raise, R-GRP-1 |
| V4-20a | V4-02, two circuits per tier, trays at 250 mm vertical pitch | — | raise, R-GRP-1b |
| V4-21 | V4-03, single circuit fixed under a ceiling, touching | 839 × 0.95 | 797.05 A |

Factors from `[T3.34]` items 1, 4, 7 and 15 for V4-14 to V4-19, and `[T3.33]`
item 5 for V4-21. Expected values are the exact products; assertions on computed
cases use a tolerance of 0.01 A. V4-17 against V4-17a is the case that catches
an engine treating circuit-to-circuit spacing as optional. V4-14 against V4-16 is the case that catches an engine defaulting
grouping to 1.00: the support type changes the answer by 3.0 % with one circuit
on the tray.

### 4.10.3 Non-reference conditions

| ID | Case | Arithmetic | Expected |
|---|---|---|---|
| V4-22 | V4-03 at 50 °C air ambient | 839 × 0.93 | 780.27 A |
| V4-23 | V4-03 at 43 °C air ambient, R-BAND-1 | 839 × 0.96 | 805.44 A |
| V4-24 | V4-03 at 25 °C air ambient | 839 × 1.10 | 922.90 A |
| V4-25 | V4-08 at 35 °C soil ambient | 744 × 0.94 | 699.36 A |
| V4-26 | V4-08 at 1.0 m depth, >300 mm² band | 744 × 0.92 | 684.48 A |
| V4-27 | V4-08 at 35 °C soil and 1.0 m depth | 744 × 0.94 × 0.92 | 643.41 A |
| V4-28 | V4-03 with a soil ambient factor requested | — | raise, R-ADM-2 |
| V4-29 | V4-04 with a solar uplift requested | — | raise, R-ADM-3 |

Factors from `[T3.44]` 110 °C row for V4-22 to V4-24, `[T3.45]` 110 °C row for
V4-25, `[T3.46]` >300 mm² column for V4-26. V4-24 confirms factors above 1.00
are applied, not clamped. V4-27 exercises two admissible factors in series.

### 4.10.4 Harmonics

Base cable for V4-30 to V4-32 is Cu 185 mm², X-HF-110, 4-core, `air_touching`,
Table 3.20 column 3, base 479 A.

| ID | THD3 | Factor, basis | Corrected capacity | Compared against |
|---|---|---|---|---|
| V4-30 | 25 % | 0.86, phase | 411.94 A | phase current |
| V4-31 | 40 % | 0.86, neutral | 411.94 A | neutral current |
| V4-32 | 50 % | 1.00, neutral | 479.00 A | neutral current |
| V4-33 | 15 % | 1.00, phase | 479.00 A | phase current |
| V4-34 | 33 % | 0.86, phase | 411.94 A | phase current |
| V4-35 | 45 % | 0.86, neutral | 411.94 A | neutral current |

V4-33 to V4-35 are the band-edge cases and fix the closed edges of R-HRM-2.
V4-31 against V4-30 is the case that catches an engine ignoring the basis flag:
the corrected capacity is identical and only the current it is compared against
changes.

### 4.10.5 Published answers from the standard

These are the standard's own worked results and are the strongest available
check. Base cable is Cu 400 mm², V-75, three single-core, Table 3.12.

| ID | Case | Standard's arithmetic | Published |
|---|---|---|---|
| V4-36 | Five circuits, all cables in one underground conduit | 492 × 5 × 0.60 | 1476 A |
| V4-37 | Four conduits or ducts, touching, one circuit each | 492 × 4 × 0.79 | 1554 A |
| V4-38 | Four trefoil groups of single-way underground ducts | 553 × 4 × 0.74 | 1636.9 A |
| V4-39 | Three trefoil groups buried direct, spaced 0.60 m | 593 × 3 × 0.87 | 1547.7 A |

Base values `[T3.12 c.17]` = 492 A, `[T3.12 c.19]` = 553 A, `[T3.12 c.15]` =
593 A. Factors from `[T3.33]` item 2 at 5 circuits, `[T3.42]`, `[T3.40]`,
`[T3.36]`. All four are `[App A]` clause A.1.2, expressions A.1 to A.4.

V4-37 recomputes to 1554.72 A and the standard publishes 1554 A, while V4-38
and V4-39 are published to one decimal. The standard's own rounding is
inconsistent here. The engine shall carry full precision internally and V4-37
shall assert to a tolerance of 1 A rather than to the printed figure.

Harmonic worked example, 4-core PVC Cu clipped to a wall, Table 3.18 column 3,
design load 35 A. `[App B]`

| ID | THD3 | Standard's arithmetic | Design load | Size selected |
|---|---|---|---|---|
| V4-40 | none | — | 35 A | 6 mm², 37 A |
| V4-41 | 20 % | 35 / 0.86 | 41 A | 10 mm², 51 A |
| V4-42 | 44 % | (35 × 0.44 × 3) / 0.86 = 46.2 / 0.86 | 53.7 A | 16 mm², 68 A |
| V4-43 | 50 % | 35 × 0.50 × 3, factor 1.0 | 52.5 A | 16 mm², 68 A |

Base values `[T3.18 c.3]`: 6 mm² 37 A, 10 mm² 51 A, 16 mm² 68 A. V4-41
recomputes to 40.70 A and the standard publishes 41 A; the size selected is
10 mm² either way. V4-41 to V4-43 together exercise all four Table 3.4 bands
except the ≤15 % band, which V4-33 covers, and confirm both the neutral current
formula of R-HRM-1 and the divide-the-design-current form of R-ADM-5.

## 4.11 Open items

| ID | Item | Status |
|---|---|---|
| OI-4.1 | Reference ambient in air versus soil families | **Closed.** One headnote carries both, 40 °C and 25 °C, for every table in the family. `[Cl 3.5.3]` |
| OI-4.2 | Behaviour between tabulated values | **Closed as a DAME convention.** The standard contains no interpolation rule; "interpolate" does not appear in the document. R-BAND-1 to R-BAND-6 are DAME decisions and are marked as such |
| OI-4.3 | Whether the harmonic factor derates phase, neutral or both | **Closed.** One factor on the three-loaded-conductor capacity; the basis flag selects the current compared. R-HRM-2 |
| OI-4.4 | Cyclic and short-term ratings for generator and UPS bypass circuits | **Open, out of scope.** Clause 3.5.6 addresses varying loads and states that factors for circuits under intermittent or varying load may be higher, but tabulates nothing. A cyclic rating requires IEC 60287 and IEC 60853 and is a separate methodology section, not an M4 extension. Recommend it be raised as M9 rather than continue to recur against M4 |
| OI-4.5 | Table 3.34 axis semantics | **Open.** "No. of rows" and "Number of circuits per tier or row" are distinct axes. Whether DAME's tray stacks are one row of three circuits or three rows of one circuit changes the factor from 0.87 to 0.93. Needs a decision recorded against the AU04 tray layout before the dataset is populated |
| OI-4.6 | Table 3.2 minimum spacings | **Open.** The spacing values are given as dimensioned drawings in D multiples, not as numbers in cells. They must be read off the printed figures to populate the "no correction required" test of R-GRP-5 |
| OI-4.7 | Two buried-conduit column pairs on multicore tables | **Open.** Single-core tables have two buried-conduit pairs, distinguished by Appendix A as shared conduit versus single-way ducts. Multicore tables have one. Confirm no multicore case needs the distinction |
| OI-4.8 | Grouping against thermal insulation columns | **Open.** No grouping table is nominated for cables surrounded by thermal insulation. R-ADM-1 raises. Confirm this is correct rather than an omission |
| OI-4.9 | Table 3.44 columns above 90 °C | **Open.** The 110 °C conductor row terminates at 100 °C ambient; the 150 °C row runs to 140 °C. R-BAND-5 raises past the last populated entry. Confirm no DAME case needs an ambient above the populated range |
| OI-4.10 | New Zealand conditions | **Open, out of scope.** Clause 3.5.3 NOTE 1 gives 30 °C air and 15 °C soil for New Zealand and directs to AS/NZS 3008.1.2 for a complete alternative table set. If DAME ever sites in New Zealand this is a second base dataset, not a factor |
| OI-4.11 | Rounding of the final answer | **Open.** The standard publishes 41 A for 40.70 and 1554 A for 1554.72, but 1636.9 and 1547.7 to one decimal. No rounding rule is stated. Recommend full internal precision and a stated display precision |
| OI-4.12 | Trefoil on a tray | **Open.** Table 3.34 has no trefoil axis; every item reads horizontal or vertical formation, and NOTE 1 says the factors apply to "single layers of cables or trefoil groups". A trefoil bundle on a tray therefore takes the horizontal-formation factor. Recommend this be recorded as the reading rather than left implicit |
| OI-4.13 | Which grouping table applies to `air_spaced` | **Open, and the standard is not self-consistent.** Table 3.5 items 1–2 nominate Table 3.34 as the CF table for columns 1 and 2. Table 3.34 NOTE 3 states its factors apply to circuits whose single-circuit CCC comes from Tables 3.12–3.14 **columns 3 and 4**, which excludes columns 1 and 2. Until resolved, `air_spaced` with more than one circuit raises rather than silently borrowing the column 3–4 factors |

## 4.12 Findings

1. `arrangement` must be a key on the base rating table, and the mapping from
   arrangement to column is per-table data. Single-core tables carry four air
   arrangements — spaced, spaced from surface, touching, exposed to sun —
   and multicore tables carry three. The current engine holds one column pair of
   ten, so nine arrangements return a touching rating, and three of the four
   installation methods the tool offers are affected. At Cu 400 mm² the error
   ranges from 21.5 % conservative to 46.9 % optimistic, and six of the eight
   tabulated non-touching arrangements are overstated. The 7 % figure observed
   against Tricab is the benign end of the range.

2. The Tricab figures are the standard's own values. 902 A is Table 3.14
   column 3 and 837 A is column 4 at 500 mm². The product-data caveat is
   retired, and the three independent calculators and the standard now agree on
   both the touching and the spaced-from-surface arrangements.

3. Rev A's grouping band direction is anti-conservative and is a defect, not a
   convention. Rounding the circuit count down raises the factor. Rev A's
   ambient direction is correct.

4. Two of the seven planned correction factor families do not exist. Thermal
   insulation contact and solar radiation are base-rating columns, so the
   manifest carries five factor families plus Table 3.4, and a factor for either
   influence must be rejected rather than defaulted to 1.00.

5. A single circuit is not CF 1.00. Support type carries a factor between 0.95
   and 1.00 with one circuit on the support, so `build_factor_set()` must
   require a support type with no default.

6. `cores_loaded` is not an axis of any base table and is removed from the
   `ccc` key. Four loaded conductors is a derived state reached only through
   Table 3.4, which is itself restricted to four- and five-core cables.

**Recommendation.** Populate `ccc_reference.csv` and the five factor datasets
against the arrangement enumeration of §4.4, correct the band direction per
R-BAND-2, and gate the existing 74 tests behind the revised `ccc` key before
any capacity number is used for procurement. Verification cases V4-36 to V4-43
are the acceptance gate: they are the standard's own published answers and
carry no DAME arithmetic.

---

*DAME Technologies Pty Ltd — Methodology Section 4, Revision B — 7 September
2026. Table and clause references are to AS/NZS 3008.1.1:2025, read under DAME's
Standards Australia licence on 7 September 2026. Table data is not reproduced
here; the datasets must be populated from the licensed copy.*
