# ANS-001 — M5 voltage drop conventions, and cable formation as an input

**Date** 8 September 2026 · **From** the standards agent · **State** ANSWERED ·
**Answers** `spec-exchange/ASK-001-m5-voltage-drop-and-formation.md`

Read against AS/NZS 3008.1.1:2025 Section 4 and Appendix A, licensed reader
copy, 8 September 2026.

Table values supporting this answer are in
`spec-exchange/private/ANS-001-values.md`. Nothing below reproduces a column.

## What this answer implies for the code, and does not do

Three changes follow from it. None are made here, per
`spec-exchange/README.md`.

1. `mv_per_a_m` needs the `column` discriminator and the `mv_per_a_m_max()`
   function that `tests/test_verification.py` already names. A2 gives the rule
   for the second column; it is not the formula currently assumed.
2. The two `xfail` cases are asserting the wrong quantity, not asserting it too
   tightly. A1.4 says what to point them at. They should be seen to fail against
   the corrected expectation before they pass.
3. Formation becomes a required input on the voltage drop path with an
   interlock against `arrangement`. A2.3.

## Provenance marking

As M4 Rev B, with one addition.

| Class | Marking | Meaning |
|---|---|---|
| Standard, clause rule | `[Cl 4.x]` | Stated requirement or note in the clause named |
| Standard, table structure | `[T4.x]` | Column heading, headnote or note. Never a body value |
| Standard, published answer | `[App A]` | Worked example carrying the standard's own arithmetic |
| DAME convention | `[M5 rule]` | Not in the standard. A DAME decision |
| Reading validated against printed data | `[M5 reading]` | Not stated as a formula in the standard, but reproduces every printed cell tested. Evidence recorded with the rule |
| Third-party calculator | `[Tricab]` | Cross-check only |

---

## A1 — the two power factor columns

### A1.1 "Max" is √3·Zc, and there is a clause

**R-VD-1.** The Max column is √3·Zc where Zc = √(Rc² + Xc²).

> "the three-phase a.c. voltage drop (mV/A.m) values represent √3Zc"
> `[Cl 4.3.3]`

and the condition under which that is the maximum:

> "the maximum voltage drop in a cable, when the power factor of the cable is
> equal to the power factor of the load, is obtained by multiplying the cable
> impedance (Zc) by the length" `[Cl 4.3.1]`

The 0.46 % agreement already observed is confirmed and is the rounding of R and
X to three significant figures in the source tables, not a modelling difference.
Q1.1 is answered yes, with a clause.

### A1.2 The "0.8 p.f." column is neither a 0.8 p.f. value nor an artefact

**R-VD-2.** The column is the **worst case over load power factors in the
closed range 0.8 lagging to unity**. `[M5 reading]`

```
Vc_0.8pf = √3 · max{ Rc·cosθ + Xc·sinθ : cosθ ∈ [0.8, 1.0] }

         = √3 · √(Rc² + Xc²)        when Rc/Zc ≥ 0.8
         = √3 · (0.8·Rc + 0.6·Xc)   when Rc/Zc <  0.8
```

`Rc·cosθ + Xc·sinθ` peaks at `cosθ = Rc/Zc`, which is the cable's own power
factor. While the cable power factor lies inside [0.8, 1.0] the peak is interior
and the worst case is Zc, the Max value. Once the cable power factor falls below
0.8 the function is decreasing across the whole range and the worst case sits at
the 0.8 end.

This is Clause 4.2 in words. The tabulated values may not apply

> "Where the load power factor and cable power factor do not give rise to
> conditions for maximum voltage drop **or the load power factor for larger size
> conductors varies from 0.8 lagging**" `[Cl 4.2(a)]`

— maximum-drop conditions in general, and 0.8 lagging for larger conductors,
"larger" being exactly those whose cable power factor has dropped below 0.8.

**Evidence.** 117 printed cells across Tables 4.14(B), 4.15(B) and 4.17(B), both
columns, all reproduced to within 0.45 %, with **zero falsifying cells**. A
falsifying cell is one where the rule selects the Max branch but the printed
columns differ, or selects the 0.8 branch and the printed columns are equal for
a reason other than three-significant-figure rounding. Counts and worst-case
errors per table are in the private file.

The naive √3(0.8R + 0.6X) applied at all sizes reproduces 34 of 97 on the subset
tested. It is not what the column contains at any size.

So Q1.2 is answered: **deliberately conservative, not an artefact**, and the
conservatism has a precise meaning. The column is the correct worst case for a
load whose power factor is anywhere between 0.8 lagging and unity, which is the
design condition the table serves. Below the branch point the Clause 4.5 value
at exactly 0.8 is lower, legitimately, and a designer who knows the load power
factor is consistently 0.8 may use Clause 4.5 and take it.

### A1.3 The crossover is not at a fixed size

**R-VD-3.** The branch point is set by the cable power factor crossing 0.8 and
therefore moves with the cable.

| Table | first size on the 0.8 branch | cable p.f. there | cable p.f. one size down |
|---|---|---|---|
| 4.15(B) single-core flat touching, 90 °C | 185 mm² | 0.7939 | 0.8490 at 150 mm² |
| 4.14(B) single-core trefoil, 90 °C | 240 mm² | 0.7712 | 0.8395 at 185 mm² |
| 4.17(B) multicore, 90 °C | 300 mm² | 0.7556 | 0.8152 at 240 mm² |

The observation in ASK-001 that the two columns "only separate at 400 mm²" is
the *visible* onset, not the branch point. On the multicore table the branch
switches at 300 mm², but at 300 and at 240 the two branches agree to three
significant figures, so the change is invisible until 400. Reading the crossover
off the printed columns understates it by one or two sizes and gives a different
answer per table, which is why "below 240 mm²" appeared to be a rule and is not.

### A1.4 What a verification suite asserts, and the two xfail cases

**R-VD-4.** Assert the Max column as `√3·√(R² + X²)` at every size, tolerance
0.5 %. Clause-backed identity, and the strongest available check on the R and X
datasets. `[Cl 4.3.3]`

**R-VD-5.** Assert the 0.8 p.f. column with the R-VD-2 branch rule at every
size, tolerance 0.5 %. Do not assert `√3(0.8R + 0.6X)` against it below the
branch point.

**R-VD-6.** `√3(Rc·cosθ + Xc·sinθ)` is Clause 4.5(3) and is the correct
computation when the load power factor is known and consistent — Clause 4.2
NOTE 4 points to Clause 4.5 for that case. It is a **different quantity** from
the 0.8 p.f. table column. `[Cl 4.5]`

The two `xfail` cases at 4 and 35 mm² are comparing a Clause 4.5 computation
against a Clause 4.2 table column. Both values are correct and they are not the
same quantity, so this is a category error rather than a tolerance problem. At
both sizes the cable power factor is 0.9999 and 0.9932, inside [0.8, 1.0], so
the expected value under R-VD-2 is the Max value and the printed equality is
correct rather than conservative by accident.

Re-pointed at R-VD-2 both pass at 0.5 % with nothing weakened. The xfail reason
string as written is a fair description of the observation and a wrong inference
from it: the standard does not "repeat the Max value into the 0.8 p.f. column",
it puts the worst case of the range there, and below the branch point the worst
case *is* the Max value.

---

## A2 — cable formation

### A2.1 Tables 3.5–3.8 fix arrangement only, and discard formation deliberately

**R-FRM-1.** Those tables map a physical installation to a **rating column** and
collapse formation in doing so. Table 3.5 item 5 carries two reference drawings
for one entry — a trefoil bundle and a flat row of three touching cables — and
both map to the same pair of columns. The table's own heading is "Methods of
installation for cables deemed to have the same CCC". `[T3.5]`

Formation is not merely absent from those tables. It is discarded there, because
it does not change the current-carrying capacity. It cannot be recovered
downstream. The inference defect was not an oversight against available
information — the information is not present. Q2.1 is answered: **arrangement
only**.

**R-FRM-2.** Section 4 does not collapse formation. It is a table-selection
axis. `[T4.14, T4.15, T4.19, T4.20, T4.1(A)]`

| Formation | Single-core Cu | Single-core Al | Reactance columns |
|---|---|---|---|
| Trefoil | Table 4.14 | Table 4.19 | Table 4.1(A) Columns 1–3 |
| Flat touching, or touching inside a common wiring enclosure | Table 4.15 | Table 4.20 | Table 4.1(A) Columns 4–6 |

Clause 4.3.1 NOTE 2 states the reason: "Cable reactance is a function of the
conductor shape and spacing." `[Cl 4.3.1]`

**R-FRM-3.** Two formations are tabulated and no others. There is no spaced
voltage drop table and no spaced reactance column.

### A2.2 The default is defensible, and the standard says so

**R-FRM-4.** Flat touching is sanctioned as the conservative estimate:

> Table 4.1(A) NOTE 4 — the flat touching values "may also be used as
> conservative estimate for cables that are not strictly arranged 'flat
> touching', e.g. where cables are installed in a common wiring enclosure"

Default to flat and warn is correct and should be kept. Q2.2 is answered: a
default exists and it is the one already chosen. The warning earns its place —
at 400 mm² XLPE the flat reactance is 19.1 % above trefoil and that carries
through to **+9.25 %** on the 0.8 p.f. voltage drop column and **+12.36 %** on
Max. The voltage drop ratio is smaller than the reactance ratio because
resistance carries the balance.

**R-FRM-5.** The default applies to the voltage drop path only. It must not
propagate into a capacity lookup, where formation is not an axis at all and a
defaulted value would be meaningless.

### A2.3 The interlock — `air_spaced` excludes both formations

**R-FRM-6.** Trefoil means the three cables are mutually touching; flat touching
means the same in a row. M4 R-SPC-2 defines `air_spaced` as cables separated by
D between surfaces, so it is neither. The standard closes this:

> "Vc values are only applied for single-core cables installed strictly in
> touching formation. Where single-core cables are spaced apart or in single-way
> ducts, the Vc is calculated using the impedance of the cable (see Clause 4.3)
> using the revised value of reactance detailed in notes to Tables 4.1 and 4.2."
> `[T4.14 NOTE 2]`

`air_spaced` therefore has **no tabulated mV/A.m at all** and must route through
Clause 4.3. Requesting a voltage drop table for it should raise. Q2.3 is
answered: separating the phases excludes trefoil by definition, and excludes the
tabulated route entirely.

**R-FRM-7.** The reactance uplift is **additive**, not a multiplier, and is
keyed to separation in cable diameters: 0.5D, 1D and 2D add 0.0254, 0.0435 and
0.0690 Ω/km respectively to the Table 4.1 or 4.2 value. D is the diameter of the
single-core cable; for cables in single-way ducts D remains the cable diameter,
not the duct diameter. `[T4.1(A) NOTE 1, NOTE 2]`

These three constants are published in a note rather than a table body, and are
carried here on the same footing as the k constants and the 15/33/45 % band
edges under the `README.md` exception. If the implementation side reads that
exception more narrowly, move them to the private file — flagged as OI-5.8.

**R-FRM-8.** No uplift is required below 25 mm² for separations up to 5D; the
effect is under 2.5 % and the tabulated route may be used directly.
`[T4.1(A) NOTE 3, T4.14 NOTE 3]`

**R-FRM-9.** The R-SPC-2 interlock extends to formation, asymmetrically.

| M4 `arrangement` | Permitted formation | Voltage drop route |
|---|---|---|
| `air_spaced` | neither — the cables are separated | Clause 4.3, X = flat touching value + R-FRM-7 uplift |
| `air_spaced_from_surface` | trefoil or flat touching, **must be stated** | Table 4.14 / 4.15 / 4.19 / 4.20 |
| `air_touching` | trefoil or flat touching, **must be stated** | Table 4.14 / 4.15 / 4.19 / 4.20 |
| `enclosed_conduit_in_air` | treated as touching | Table 4.15 / 4.20 per T4.1(A) NOTE 4 |

Arrangement constrains formation without determining it, except for
`air_spaced`, where it excludes both. `[M5 rule]`

---

## A3 — the residual

### A3.1 The reasoning is right and one link short

Clause 4.4(1) gives the operating temperature:

```
(Io / IR)² = (θO − θA) / (θR − θA)
```

`[Cl 4.4]`

Both reported temperatures reproduce from it exactly with θR = 110 °C and
θA = 40 °C. A stated 95.1 °C on the column 3 capacity implies a load of 800.3 A,
and the same load on the column 5 capacity gives 103.69 °C against the reported
103.6 °C.

The missing link is what Clause 4.4 does next:

> "The calculated operating temperature (θO) is then raised to the nearest
> temperature 45 °C, 60 °C, 75 °C, 80 °C, 90 °C or 110 °C for use with … Tables
> 4.14, 4.15, 4.17, 4.19, 4.20A, 4.22, 4.24, 4.25 and 4.27 to determine cable
> a.c. three-phase voltage drop" `[Cl 4.4]`

Capacity does not reach voltage drop through a continuous resistance. It reaches
it through a **six-valued band**, and the consequence is discrete:

| banding convention | 95.1 °C → | 103.69 °C → | difference in Vc at 400 mm², T4.14(B) 0.8 p.f. |
|---|---|---|---|
| round to nearest | 90 °C | 110 °C | **+2.89 %** |
| round down | 90 °C | 90 °C | 0.00 % |
| raise to next | 110 °C | 110 °C | 0.00 % |

**R-VD-7.** The reported 2.9 % is reproduced exactly, and only, by
round-to-nearest. A continuous-temperature calculation gives +1.32 % and cannot
account for it. The instinct that the residual exceeded what a resistance change
explains was right; the excess is the band jump.

### A3.2 Confirmation, and the test that settles it

Q3 is answered: the reasoning is complete, nothing else differs, and the
mechanism is the temperature band rather than the resistance curve.

The prediction is specific. Correcting the capacity column moves θO from
103.69 °C to 95.1 °C, which moves the band from 110 °C to 90 °C, which closes
the gap to **zero within table rounding** — not to 1.3 %. If it instead closes
to roughly 1.3 %, the engine is using the continuous operating temperature and
R-VD-8 is not implemented. That is the discriminating test, and it closes ASK-001
Q3 and the M4 capacity-column defect together.

**R-VD-8.** Round the operating temperature to the nearest member of
{45, 60, 75, 80, 90, 110} °C before any resistance or voltage drop lookup, and
use the same rounded value for both. `[Cl 4.4]`

The clause wording "raised to the nearest" is ambiguous between raise and round.
The two published worked examples both round rather than raise. `[App A, Cl A.6]`
Both happen to round downward, so they do not by themselves separate
round-to-nearest from round-down — but round-to-nearest fits both and is the
only one of the three conventions that reproduces the observed Tricab gap.
Recorded as OI-5.3.

**R-VD-9.** The rated current IR in Clause 4.4(1) is the **corrected** capacity,
not the tabulated one:

> "relevant CFs obtained from Tables 3.33 to 3.48 shall be used to correct the
> rated current in Tables 3.9 to 3.32" `[Cl 4.4]`

This makes the M4 factor set an input to voltage drop, and it is why the M4
grouping-direction defect propagates into M5.

---

## Verification cases

Expected values are in `spec-exchange/private/ANS-001-values.md` under the
matching case ID. Cases are single-core or multicore copper, three-phase, at
tabulated conditions unless stated.

### The power factor branch, including below the branch point

| ID | Table | mm² | °C | cable p.f. | branch | asserts |
|---|---|---|---|---|---|---|
| V5-01 | 4.17(B) | 4 | 90 | 0.9999 | Max | currently `xfail` |
| V5-02 | 4.17(B) | 35 | 90 | 0.9932 | Max | currently `xfail` |
| V5-03 | 4.17(B) | 185 | 90 | 0.8732 | Max | strongest small-size case |
| V5-04 | 4.17(B) | 400 | 90 | 0.6828 | 0.8 | columns visibly separate |
| V5-05 | 4.14(B) | 185 | 90 | 0.8395 | Max | |
| V5-06 | 4.14(B) | 240 | 90 | 0.7712 | 0.8 | branch flip, trefoil |
| V5-07 | 4.15(B) | 150 | 90 | 0.8490 | Max | branch flip, flat, low side |
| V5-08 | 4.15(B) | 185 | 90 | 0.7939 | 0.8 | branch flip, flat, high side |

V5-03 is the case a naive suite fails correctly: the branch is Max, the
Clause 4.5 value is about 0.9 % lower, and a suite asserting the Clause 4.5
value fails because that value is not what the column contains.

V5-07 against V5-08 is a branch flip at adjacent sizes on one table, and V5-08 is
the masked case — both branches round to the same printed figure, so an engine
that infers the branch from printed equality gets it wrong.

### Trefoil against flat at the same size

| ID | Case |
|---|---|
| V5-09 | 400 mm², 90 °C, **trefoil**, Table 4.14(B), both columns |
| V5-10 | 400 mm², 90 °C, **flat touching**, Table 4.15(B), both columns |
| V5-11 | ratio V5-10 / V5-09 — **+12.36 %** on Max, **+9.25 %** on 0.8 p.f. |
| V5-12 | reactance behind the pair, Table 4.1(A) XLPE 400 mm² — flat is **+19.1 %** |
| V5-13 | 400 mm², 90 °C, `air_spaced`, tabulated route requested → raise, R-FRM-6 |
| V5-14 | 400 mm², 90 °C, formation not stated → flat touching used, warning raised, R-FRM-4 |

### Spaced, via Clause 4.3

| ID | Separation |
|---|---|
| V5-15 | flat touching, datum — recomputes V5-10 from R and X |
| V5-16 | 0.5D |
| V5-17 | 1D — **+23.9 %** on the touching value |
| V5-18 | 2D |

### The operating temperature chain

| ID | Case | Expected |
|---|---|---|
| V5-19 | Io 800.3 A on the column 3 capacity, θR 110, θA 40 | 95.10 °C → band **90 °C** |
| V5-20 | Io 800.3 A on the column 5 capacity, θR 110, θA 40 | 103.69 °C → band **110 °C** |
| V5-21 | V5-19 against V5-20 at 400 mm² trefoil, 0.8 p.f. column | **+2.89 %** |
| V5-22 | Published, Cl A.6(a): two 16 mm² Cu V-75 single-core, unenclosed on a wall, 55 A, ambient 40 °C | **60.4 °C**, rounded to 60 °C |
| V5-23 | V5-22, three-phase Vc from Table 4.15 converted to single-phase by 1.155 | published figure |
| V5-24 | Published, Cl A.6(b): same at ambient 25 °C with the Table 3.44 factor | **45.3 °C**, rounded to 45 °C |

V5-22 to V5-24 are the standard's own published answers and carry no DAME
arithmetic. `[App A]` They are the acceptance gate for the temperature chain,
and V5-22 and V5-24 are also the evidence behind OI-5.3.

---

## Open items

| ID | Item | Status |
|---|---|---|
| OI-5.1 | Whether R-VD-2 holds on the aluminium and flexible tables | **Open.** Validated on 4.14(B), 4.15(B) and 4.17(B), all copper — 117 cells, zero falsifying. Tables 4.19, 4.20, 4.22, 4.24, 4.25, 4.27 and 4.29 to 4.31 are untested. The rule is physics rather than fitting, so it should hold, but it has not been checked. The implementation side holds all of these and can test it cheaply |
| OI-5.2 | Exact branch edge at cable p.f. = 0.8 | **Open.** No tabulated cell sits close enough to distinguish `≥ 0.8` from `> 0.8`; the nearest observed are 0.8152 on the Max branch and 0.7939 on the 0.8 branch. Immaterial for every size tested, recorded so it is not silently defaulted |
| OI-5.3 | "Raised to the nearest" | **Open.** Clause 4.4 says "raised to the nearest" of six values. The two Cl A.6 examples round rather than raise, and both round downward, so they fit round-to-nearest and round-down equally. Round-to-nearest is adopted as R-VD-8 because it is the only convention reproducing the Tricab gap. A θO of 70 °C would go to 75 under round-to-nearest and 60 under round-down, about 3 % in Vc. Needs a decision before the first case lands between 60 and 75 |
| OI-5.4 | Which base column the spacing uplift adds to | **Open.** Table 4.1(A) NOTE 1 says to add the uplift to Columns 1 to 6, covering both formations, without saying which applies to a spaced installation. R-FRM-7 uses the flat touching value since spaced cables lie in a row. The trefoil base would give a lower X and about 5 % less Vc at 400 mm² |
| OI-5.5 | Table 4.20 variant in the Clause 4.4 list | **Open.** The Clause 4.4 list names "4.20A", not 4.20. Whether the (B) variant is excluded deliberately or by typographical slip is not determinable from the text |
| OI-5.6 | Temperature band sets differ between tables | **Open.** Table 4.14 carries 25, 30, 45, 60, 75, 80, 90 and 110 °C; Tables 4.15 and 4.17 carry 75, 90 and 110 °C only. A band that exists on one table may not exist on another, so the band set is per-table data and R-VD-8 must resolve against the table in use. See also the resistance-table column-index warning in the private file |
| OI-5.7 | Whether the 80 °C band is in DAME scope | **Open.** Table 4.14 marks 80 °C with a footnote tying it to aerial bundled cables, which are out of M4 scope. Confirm whether 80 °C is reachable for any DAME cable |
| OI-5.8 | Whether the three spacing-uplift constants belong in the public file | **Open, for the implementation side to rule on.** Carried publicly here under the `README.md` exception for published figures that are facts rather than tables. Move to the private file if that reads too broadly |

---

## Findings

1. Max is √3·Zc by Clause 4.3.3, not by inference. The 0.46 % agreement is the
   rounding of the source R and X tables.

2. The 0.8 p.f. column is the worst case over load power factors from 0.8
   lagging to unity, not the 0.8 lagging value. 117 of 117 printed cells to
   within 0.45 %, zero falsifying; the naive formula reproduces 34 of 97.
   Deliberately conservative, with a precise meaning, and not an artefact.

3. The two `xfail` cases assert a Clause 4.5 computation against a Clause 4.2
   table column. Both values are right and they are different quantities.
   Re-pointing at R-VD-2 passes them at 0.5 % with nothing weakened.

4. The branch point is the cable power factor crossing 0.8 and moves per table —
   185 mm² flat, 240 mm² trefoil, 300 mm² multicore. Reading it off the printed
   columns understates it, because rounding masks the first size or two. "Below
   240 mm²" is an artefact of the reading, not a property of the tables.

5. Formation is discarded by Tables 3.5–3.8 by design and is a table-selection
   axis in Section 4. It was never recoverable from installation method. Flat
   touching is the standard's own conservative estimate, so default-and-warn is
   correct as implemented.

6. `air_spaced` has no tabulated voltage drop at all and must route through
   Clause 4.3 with an additive reactance uplift.

7. The 2.9 % residual is fully explained and the mechanism is a six-valued
   temperature band, not a continuous resistance. Correcting the capacity column
   should close it to zero rather than to 1.3 %.

**Recommendation.** Implement R-VD-2 as the expected-value function behind the
`column` discriminator, re-point the two `xfail` cases at it, add formation as a
required input with the R-FRM-9 interlock, then confirm R-VD-8 is
round-to-nearest and re-run the Tricab comparison. The residual going to zero
rather than 1.3 % is the single result that closes Q3 and the M4 capacity-column
defect at once.
