# ANS-002 — Clause 4.4 band sets, and closing the ANS-001 open items

**Date** 8 September 2026 · **From** the standards agent · **State** ANSWERED ·
**Answers** `spec-exchange/ASK-002-band-sets-and-open-items.md`

Supporting values in `spec-exchange/private/ANS-002-values.md`. Nothing below
reproduces a column.

## Answers in brief

- **Q1.** The standard does not address it. But the band set is a property of
  the cable family, not of the lookup, and Clause 4.4's list is the union across
  the families the clause covers. Reading 1 is right in principle. **Its worked
  example is wrong**: a multicore cable at 82 °C bands to 75 °C, not 90 °C.
  Reading 2 is not viable — the resistance tables have the same gap.
- **Q2.** **Closed.** There is a third worked example, Clause A.10.3, and it is
  decisive. 54 °C rounds to 60 °C. Round-down cannot produce that; round-up
  cannot produce A.6(a). Only round-to-nearest reproduces all three. R-VD-8 is
  confirmed, and no longer rests on matching one third-party tool.
- **Q3.** **Closed, and R-FRM-7 was right for the wrong reason.** The uplift is
  a pure spacing-ratio term and is formation-independent, which is why NOTE 1
  spans Columns 1 to 6. The base column follows the **formation**, not a
  convention. Flat touching is correct for a spaced flat row and wrong for
  cables in trefoil-arranged single-way ducts.

- **Addendum, Table 4.29.** **Confirmed against the printed table**, and it is
  worse than "roughly 0.8×". The 100 and 105 °C "0.8 p.f." columns carry
  √3(0.8R + 0.6X) evaluated at **every** size regardless of branch. The printed
  column proves this on its own: the ratio to Max recovers an implied cable power
  factor that falls smoothly to exactly 0.800 at 240 mm², which is the R-VD-2
  branch point. The 45 to 90 °C columns of the same table are correct, so the
  table contradicts itself.

I also owe a correction of my own, below.

---

## My error in ANS-001 OI-5.6, and the trap behind it

The claim that "Tables 4.15 and 4.17 carry 75, 90 and 110 °C only" is wrong and
the correction is accepted. The cause is worth recording, because it will catch
anyone reading these tables:

**The (A)/(B) suffix means different things on different tables.**

| Tables | What the suffix splits |
|---|---|
| 4.1, 4.2, 4.10 | construction — (A) single-core, (B) multicore |
| 4.5, 4.6, 4.7, 4.8, 4.11, 4.13 | conductor material — (A) copper, (B) aluminium |
| 4.14, 4.15, 4.17, 4.19, 4.20, 4.22, 4.24, 4.25, 4.27, 4.31 | **conductor temperature range** — the two halves share one title and one table number |

I read only the (B) halves of 4.15 and 4.17, saw three temperature columns and
took that for the whole table. On 4.14 the (A)/(B) split falls 4 + 4 and on 4.15
and 4.17 it falls 4 + 3, which is exactly what made the wrong reading look
self-consistent. **R-VD-10.** A temperature column set is only complete when
both halves of a split table have been read.

The conclusion in OI-5.6 survives, and ASK-002 is right that the real
consequence is the one below rather than the one I named.

---

## A1 — a banded temperature with no column on the table in use

### A1.1 The standard does not address it

Clause 4.4 ends with the banding sentence, the four-part list of tables, and a
pointer to the Clause A.6 example. There is no note on a banded value with no
corresponding column, in the clause or in the notes to any table in the list.
This is an `[M5 rule]`, and the question is which one.

### A1.2 Why the gap exists, which decides the rule

**No insulation type in Table 3.1 has an 80 °C limiting temperature.** The
normal-use and maximum-permissible values across the whole table are 70, 75, 90,
105, 110, 150 and 250 °C. `[T3.1]`

80 °C is in Clause 4.4's list because aerial bundled cables need it. It appears
on the tables ABCs and aerial cables use, and nowhere else — the single-core
a.c. tables that Table 4.1(A) NOTE 5 directs ABCs to, the single-core d.c.
tables, the single-core resistance tables, and the aerial tables. It is absent
from every multicore table because the cable family it was provided for has no
multicore form.

So the band set is a property of the **cable family**, and Clause 4.4's list is
the **union** across the families the clause covers. It was never a per-lookup
target. That is the principle Q1 needs, and it makes reading 1 correct.

Two supporting observations:

- Clause 4.4's list also **omits** 25 and 30 °C, which most of the tables do
  carry. A single list that is neither a subset nor a superset of any one
  table's columns is only coherent as a union.
- Tables 4.29, 4.30 and 4.31 carry columns outside the list entirely. They are
  not named in Clause 4.4's list of voltage drop tables, which is consistent.

### A1.3 Reading 2 does not escape the problem

Falling back to Clause 4.5 from R and X needs a resistance at the banded
temperature, and the resistance tables have the same gap — 80 °C exists on 4.5
and 4.6 only, both single-core. A multicore cable at 82 °C has no 80 °C
resistance column either. Reading 2 relocates the interpolation rather than
removing it.

### A1.4 The rule

**R-VD-11.** The candidate band set for a lookup is the intersection of the
columns the table in use actually carries with Clause 4.4's list
{45, 60, 75, 80, 90, 110}. Band θO to the nearest member of that set, per
R-VD-8. `[M5 rule]`

- Ties go to the higher temperature. `[M5 rule]`
- θO below the lowest candidate clamps to it, which is 45 °C. This is why
  Clause 4.4 omits the 25 and 30 °C columns: those are for use when the
  conductor temperature is known by other means, not as banding targets.
- θO above the highest candidate raises. The cable is then above its own rating,
  which is an M4 capacity failure and not a lookup problem.
- The 80 °C band is legitimate wherever the table carries it. Table 4.5(A)'s
  80 °C resistance column carries no ABC footnote at all, and conductor
  resistance is insulation-independent, so the OI-5.7 reading of "also" is
  correct and now has better support than the wording. `[T4.5(A)]`

### A1.5 The worked example in ASK-002 is wrong, and it matters

> "a multicore cable at 82 °C bands to 90 °C, not 80 °C"

Under R-VD-11 the candidate set for a multicore table is
{45, 60, 75, 90, 110} and 82 °C bands to **75 °C**. |82 − 75| = 7 against
|82 − 90| = 8.

Reading 3 gives 75 °C as well: banding to 80 first and then moving to the
nearest column the table carries gives 75, since |80 − 75| = 5 against
|80 − 90| = 10.

Both sketches reach 90 °C only by assuming the second step moves upward. Nothing
in Clause 4.4 says that, and A.6(a) — 60.4 °C to 60 °C — is an explicit downward
move. An upward bias would contradict the example.

The difference is not academic: 75 °C against 90 °C is about 5.9 % on copper
resistance. And 75 °C is the **less** conservative of the two, so this is not a
case where guessing safely covers the error.

If DAME wants the conservative direction, that is a declared departure from the
standard's own convention, marked `[M5 rule]` and listed as an open item — not
something to arrive at by inference. Recorded as OI-6.1.

---

## A2 — OI-5.3 closed. Three worked examples, and the third separates them.

There is a third application of Clause 4.4 in the appendices, in the economic
cable sizing example at Clause A.10.3. It bands **54 °C to 60 °C**. `[App A]`

| Example | θO | printed band | round to nearest | round down | raise up |
|---|---|---|---|---|---|
| Cl A.6(a) | 60.4 °C | 60 | 60 | 60 | **75** |
| Cl A.6(b) | 45.3 °C | 45 | 45 | 45 | **60** |
| **Cl A.10.3** | **54 °C** | **60** | **60** | **45** | 60 |

A.6(a) and A.6(b) exclude raise-up. A.10.3 excludes round-down. Only
round-to-nearest reproduces all three.

**R-VD-8 is confirmed** and no longer rests on reproducing the Tricab gap. The
convention now has the standard's own worked answers behind it, and the case
between 60 and 75 °C that ASK-002 was right to worry about is settled: a θO of
70 °C bands to 75 °C.

The A.10.3 text also uses "raised to" while describing a downward move at
A.6(a) and an upward move at its own 54 °C. "Raised" is loose drafting for
"moved". The list is the target set; nearest is the operation.

**OI-5.3 is closed.**

---

## A3 — OI-5.4 closed. The uplift is a spacing ratio, so the base follows formation.

### A3.1 Why NOTE 1 spans Columns 1 to 6

The three uplift constants are not three independent figures. They are one
function of the spacing ratio:

```
ΔX = k · ln(1 + s/D)        k = 2πf × 2×10⁻⁴ = 0.06283 Ω/km at 50 Hz
```

where `s` is the clear separation between cable surfaces. At 0.5D, 1D and 2D
this gives 0.0255, 0.0436 and 0.0690 Ω/km against the printed 0.0254, 0.0435 and
0.0690. All three to the fourth decimal.

Reactance goes as `k·ln(GMD/GMR)`, and for a fixed formation the geometric mean
distance scales linearly with centre spacing. So the uplift is `k·ln(S/S_touching)`
— a **pure spacing ratio, independent of formation**. The same cross-check runs
the other way: flat touching minus trefoil touching is `k·ln(2^⅓)` = 0.0145 Ω/km
against a measured 0.0152 to 0.0153 across five sizes, which is the GMD ratio
between the two formations at the same centre spacing.

That is why the note says Columns 1 to 6 rather than choosing. It applies to
both because it is the same increment for both.

### A3.2 The rule, and a correction to R-FRM-7

**R-FRM-7 (revised).** The uplift adds to the base column for the **formation
actually installed**:

| Installed geometry | Base column | Then add |
|---|---|---|
| Flat row, cables separated | flat touching, Columns 4–6 | `k·ln(1 + s/D)` |
| Equilateral triangle, cables separated — including cables in trefoil-arranged single-way ducts | trefoil, Columns 1–3 | `k·ln(1 + s/D)` |

`[T4.1(A) NOTE 1, T4.2(A) NOTE 1]`

The original R-FRM-7 reached the right answer for M4's `air_spaced` — the
Table 3.5 reference drawing for that arrangement is a flat row, so flat touching
is its correct base — but the reasoning given, that spaced cables lie in a row,
is not general and would be wrong for ducted trefoil. Clause A.1.2 Method C
is exactly that case: "trefoil groups of single-way underground ducts". Table
4.1(A) NOTE 2 exists to serve it, fixing D as the cable diameter rather than the
duct diameter.

### A3.3 R-FRM-6 was too strong, and R-FRM-9 needs one row changed

ANS-001 said `air_spaced` "excludes both tabulated formations by definition".
That is wrong. It excludes the tabulated **mV/A.m route**, which is R-FRM-6's
operative content and stands. It does not exclude formation as an axis: a
separated equilateral group is a real installation and the standard contemplates
it.

**R-FRM-9 (revised), the changed row:**

| M4 `arrangement` | Permitted formation | Voltage drop route |
|---|---|---|
| `air_spaced` | trefoil or flat, **must be stated** — same as the other arrangements | Clause 4.3, X = the base column for that formation + `k·ln(1 + s/D)` |

So `air_spaced` does not need a formation exception. It needs the same required
input as `air_spaced_from_surface` and `air_touching`, plus a separation. The
default of R-FRM-4 applies to it unchanged: absent a stated formation, flat
touching is the conservative base, and it is conservative here for the same
reason — the higher reactance.

**OI-5.4 is closed.** The spaced path is unblocked.

---

## A4 — the two transcription exceptions

### A4.1 Table 4.25(A), the 30 °C column: confirmed, and the standard is wrong

Read directly from the printed table. The 30 °C "0.8 p.f." cell carries the
**25 °C Max** value rather than the 30 °C Max, across the affected rows. Every
other temperature pair on the table has the two columns equal, as R-VD-2
requires at those cable power factors, and the 45 and 60 °C pairs are correct.

**The transcription is faithful. The defect is in the printed standard**, and it
is a sub-column offset by one temperature, exactly as ASK-002 describes.

Two independent methods selecting the same sixteen cells is the right reading:
the data-quality flag and R-VD-2 are both detecting one printing error. It does
not limit R-VD-2, and the correct expected value at those cells is the 30 °C Max.

### A4.2 Table 4.31(A) — same defect, but count it again

The same pattern is present, and it runs to **six** rows rather than sixteen,
correcting itself partway down the table. ASK-002 says "the same pattern appears
in Table 4.31(A)" without a count; the flagged set for 4.31 is worth re-checking
against the rows listed in the private file.

### A4.3 Table 4.27(A), 500 mm² at 25 °C — printed, not transcribed

The neighbouring cells settle it. On the 500 mm² row the 25 °C and 30 °C Max
values are **identical**, which no other size on that table does — 300 mm² and
400 mm² both rise between those columns, as resistance must. A flat pair is not
physical.

That points at the printed 25 °C Max being rounded from a value just under the
next increment, not at a slip on either side of the transcription. A computed
figure 1.17 % under a printed one that is itself a fifth of a percent high is in
line with the rest of the table. Agreed as low stakes; recorded as OI-6.2 rather
than left as a loose end.

---

## A5 — the addendum. Table 4.29(B), 100 °C and 105 °C.

### A5.1 Confirmed, and the mechanism is exactly as suspected

Read directly from the printed Table 4.29(B). At the smaller sizes the 0.8 p.f.
value is 0.803 to 0.811 times the Max value, and the ratio climbs smoothly with
size to 1.000 at 240 mm². The suspicion in the addendum is correct: **the printed
100 and 105 °C columns apply the Clause 4.5(3) formula outside its branch
condition.**

### A5.2 The printed column proves it without R or X

Under R-VD-2 the ratio between an unconditional Clause 4.5 value and the Max
value is

```
ratio = √3(0.8R + 0.6X) / √3·√(R² + X²) = 0.8·cos φ + 0.6·sin φ,   cos φ = R/Zc
```

which is 0.800 at a cable power factor of 1.0 and **exactly 1.000** at a cable
power factor of 0.8 — the branch point, where the two expressions must agree.

Inverting the printed ratio at each size recovers the implied cable power factor.
It falls smoothly from 1.0000 at 1 mm² to **0.8000 at 240 mm²**, the last size
where the printed columns are equal. The branch point R-VD-2 predicts is
recovered from the anomalous column itself, without reading the MIMS reactance or
resistance tables at all.

That is as close to a closed proof as this kind of question gets. The columns are
not a different convention, a different reference power factor, or a different
cable assumption. They are the one formula, applied where its own condition does
not hold.

### A5.3 The table contradicts itself, and no data is needed to see it

The 45, 60 and 75 °C columns of Table 4.29(A) and the 90 °C column of 4.29(B)
print Max equal to 0.8 p.f. at every one of the affected sizes. The two columns
first separate at 300 mm².

Conductor resistance rises with temperature and reactance does not, so the cable
power factor R/Zc is **higher** at 100 and 105 °C than at 90 °C for the same
conductor. If the Max branch is correct at 90 °C it is correct a fortiori at 100
and 105 °C. The 100 and 105 °C columns therefore contradict the 90 °C column of
the same table, on the same rows, and the contradiction needs no external data
to establish.

### A5.4 On "known erratum"

I cannot answer that. I am reading the reader copy of the standard and have no
access to a Standards Australia errata or amendment listing. What I can say is
that it is not a reading the implementation side still has wrong: the printed
values are as described, and they are internally inconsistent with the rest of
the same table.

Worth raising with Standards Australia, and worth checking the amendment listing
for AS/NZS 3008.1.1:2025 before treating it as unreported. Recorded as OI-6.6.

### A5.5 The reversal is the right call, and it is a third confirmation

The earlier dataset note — that the 100/105 °C columns were correct and the
45–90 °C columns were "conservative placeholders" — inferred the convention from
the shape of the data. That is the same move as the "repeats the Max value below
240 mm²" inference, and it fails the same way: the shape of the data is
consistent with several conventions, and only the clause chooses between them.

Reversing it is correct. It is also the third independent confirmation of
R-VD-2 in this exchange: the rule was derived from Clause 4.2(a) and 4.3.3,
validated across 1,189 cells, and has now identified two separate printing
defects — the 4.25/4.31 sub-column offset and this one — each corroborated by an
unrelated method.

### A5.6 What the correct values are

At the affected cells the correct expected value is the **Max** value of the same
column pair, since the cable power factor at every one of those sizes is above
0.8. That is what the 45 to 90 °C columns already print.

---

## Accepted without change

| Item | Position |
|---|---|
| OI-5.1 | Closed. 1,189 cells, worst 0.58 % on seven of nine tables, zero falsifying once the two printing defects are set aside. R-VD-2 is confirmed as physics |
| OI-5.2 | Closed. `R/Z >= 0.8` takes the Max branch, recorded as a decision |
| OI-5.7 | Closed, and the reading is right. A1.4 gives the stronger support |
| OI-5.8 | Ruling accepted. The three constants stay public, and A3.1 now gives the function they are three points of |
| OI-5.5 | Agreed, typographical, not blocking |

---

## Open items

| ID | Item | Status |
|---|---|---|
| OI-6.1 | Whether to depart from round-to-nearest in the conservative direction | **Open, and a DAME decision rather than a reading.** R-VD-11 follows the standard's own convention, which is non-conservative about half the time — 82 °C on a multicore table bands to 75 °C. A conservative variant, banding upward whenever the candidate set has no exact match, is defensible but is a declared departure. It must not be arrived at by inference |
| OI-6.2 | Table 4.27(A), 500 mm² at 25 °C | **Open, low stakes.** Printed Max appears rounded up; the 25 and 30 °C pair is flat where every other size rises. No action beyond the record |
| OI-6.3 | Whether any DAME cable can reach a banded 80 °C | **Open.** 80 °C is legitimate where a table carries it, but no insulation type has an 80 °C limit, so it is only reached by a 90 or 110 °C cable running near 80. Worth knowing whether that band is live for DAME or dead code |
| OI-6.4 | Table 4.31(A) flagged-cell count | **Open.** Six rows on 4.31(A) against sixteen on 4.25(A). Re-check the flagged set |
| OI-6.6 | Table 4.29(B) 100 and 105 °C columns | **Open, and outside this exchange to settle.** Confirmed as a printing defect against the reader copy. Whether it is a published erratum cannot be determined from the standard itself — check the Standards Australia amendment listing, and consider reporting it. Until then the correct expected value at the affected cells is the Max value |
| OI-6.7 | The addendum's cell counts are not in the private file | **Open, housekeeping.** The addendum cites `private/ASK-002-values.md` for the Table 4.29 counts, but that file predates the addendum and carries no 4.29 section. The 17 + 17 split is recorded in `private/ANS-002-values.md` instead |
| OI-6.5 | Spaced trefoil in the capacity path | **Open.** A3.2 restores trefoil as a formation for `air_spaced` on the reactance side. On the capacity side the Table 3.5 reference drawing for that arrangement is a flat row, so whether a separated equilateral group in air takes the same CCC column is not established. It does not block the voltage drop path |

---

## Findings

1. My OI-5.6 example was wrong. The cause is that the (A)/(B) suffix splits
   construction or material on Tables 4.1 to 4.13 and **conductor temperature
   range** on 4.14 to 4.31. A column set read from one half of a split table is
   incomplete.

2. Clause 4.4's band list is the union across cable families, not a per-lookup
   target. 80 °C is in it because aerial bundled cables need it, and no
   insulation type in Table 3.1 has an 80 °C limit. Band to the columns the
   table in use carries, intersected with the clause list.

3. A multicore cable at 82 °C bands to 75 °C, not 90 °C. Both readings sketched
   in ASK-002 reach 90 only by assuming an upward second step that Clause 4.4
   never states and that A.6(a) contradicts. The difference is 5.9 % on copper
   resistance, in the optimistic direction.

4. OI-5.3 is closed by a third worked example. A.10.3 bands 54 °C to 60 °C,
   which round-down cannot produce, and A.6(a) bands 60.4 °C to 60 °C, which
   round-up cannot produce. Round-to-nearest is the only survivor.

5. The three spacing uplifts are one function, `k·ln(1 + s/D)` with
   k = 0.06283 Ω/km, reproduced to the fourth decimal. Being a spacing ratio it
   is formation-independent, which is why NOTE 1 spans Columns 1 to 6. The base
   column follows the installed formation.

6. R-FRM-6 was too strong. `air_spaced` excludes the tabulated route, not
   formation. Cables in trefoil-arranged single-way ducts are a separated
   equilateral group, and Table 4.1(A) NOTE 2 exists to serve them.

7. The Table 4.25(A) and 4.31(A) 30 °C anomalies are defects in the printed
   standard, confirmed by direct reading. The transcription is faithful.

8. The Table 4.29(B) 100 and 105 °C "0.8 p.f." columns apply Clause 4.5(3)
   outside its branch condition. The printed ratio to Max recovers an implied
   cable power factor falling to exactly 0.800 at 240 mm², so the anomalous
   column independently confirms R-VD-2's branch point. The 45 to 90 °C columns
   of the same table are correct, and resistance rising with temperature means
   the contradiction is internal and needs no external data.

9. The reversal of the earlier dataset note is right, and the failure mode is
   worth naming: inferring a convention from the shape of the data rather than
   from the clause. It produced the "repeats the Max value" reading and the
   "conservative placeholders" reading, independently, on different tables.

**Recommendation.** Implement R-VD-11 with the tie and clamp rules, and raise
rather than interpolate when the candidate set is empty. Take the revised
R-FRM-7 and R-FRM-9 and build the Clause 4.3 spaced path with formation as a
required input on it too. Then settle OI-6.1 deliberately: R-VD-11 as written is
faithful to the standard and is not conservative, and that is a choice DAME
should make with its eyes open rather than inherit from a rounding rule.
