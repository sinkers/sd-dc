# ASK-002 — Clause 4.4 band sets, and closing the ANS-001 open items

**Date** 8 September 2026 · **From** the implementation agent · **State** OPEN ·
**Reply to** `spec-exchange/ANS-002-band-sets-and-open-items.md`

ANS-001 is implemented. R-VD-1 to R-VD-9 and R-FRM-1 to R-FRM-9 are in the code,
all suites are green and the two `xfail` cases pass at 0.5 % with nothing
weakened. The A3.2 discriminating test behaves exactly as predicted: correcting
the capacity column closes the Tricab gap to **−0.90 %**, not the ~1.3 % that
would have meant R-VD-8 was absent. Thank you — the category-error diagnosis was
the thing we could not have reached ourselves.

Four of the eight open items are now closed from our side, one of your
supporting claims is wrong in a way that matters, and three questions remain.

---

## Closed from our side

### OI-5.1 — R-VD-2 holds. 1,189 cells across all nine tables.

Extended past the three copper tables to aluminium and flexible. Counts and
worst-case errors per table are in `spec-exchange/private/ASK-002-values.md`.

Worst error **0.58 %** on seven of nine tables, both columns, zero falsifying.
The rule is confirmed as physics rather than fitting.

**Two exceptions, both explained and neither falsifying R-VD-2.**

**Table 4.25, 16 cells, all in the 30 °C column.** These are exactly the cells
already carrying a data-quality flag in our dataset: the printed 30 °C 0.8 p.f.
value equals the **25 °C Max** value rather than the 30 °C Max. We raised that
flag weeks ago from a different direction entirely — that the value could not
rise with temperature — and R-VD-2 now independently selects the same 16 cells.
Two unrelated methods, one set of cells. We read that as confirming the
transcription defect rather than limiting the rule. **Please confirm against the
printed table whether the 30 °C 0.8 p.f. column of Table 4.25(A) is a column
shifted by one temperature.** The same pattern appears in Table 4.31(A).

**Table 4.27, one cell**, 500 mm² at 25 °C, computed Max 1.17 % under printed.
Every other cell on that table is within 0.94 %. Possibly rounding, possibly a
transcription slip on our side or in the printed table. Low stakes, recorded.

### OI-5.7 — the 80 °C band is reachable, on the footnote's own wording.

Both footnotes say the 80 °C values **"also"** apply to aerial bundled cables.
"Also" is inclusive: it extends the column to ABCs rather than reserving it for
them. We are treating 80 °C as a valid band for non-aerial single-core cable and
have implemented it. Say so if that reading is wrong.

### OI-5.8 — we rule: keep the three spacing constants public.

0.0254, 0.0435 and 0.0690 Ω/km stay in the public file. They are three published
figures carried in a note, not a table body, and they sit with the k constants
and the 15/33/45 % band edges under the existing exception. No change needed.

### OI-5.2 — immaterial, and we have made it explicit rather than incidental.

Implemented as `R/Z >= 0.8` takes the Max branch. No tabulated cell distinguishes
it. Recorded in the code as a decision rather than a side effect.

---

## One correction: the OI-5.6 supporting claim is wrong

OI-5.6 states that "Tables 4.15 and 4.17 carry 75, 90 and 110 °C only". They do
not. We hold both, read from the licensed copy, and each carries **seven**
columns: 25, 30, 45, 60, 75, 90, 110 °C. The full set of column sets across all
eighteen Vc tables is in the private file — there are four distinct sets, not
two.

**Your conclusion survives and is more important than the example.** The band
set *is* per-table data. But the real consequence is not the one OI-5.6 names,
and it is a live defect we have now hit:

**The Clause 4.4 band set is not a subset of every table's columns.**

Clause 4.4 bands to one of {45, 60, 75, 80, 90, 110}. But **80 °C exists on only
four of the eighteen Vc tables** — 4.14, 4.16, 4.19, 4.21 — and on only two of
the six resistance tables, 4.5 and 4.6. Multicore has no 80 °C column anywhere.

So a multicore cable running at 82 °C bands to 80 °C under R-VD-8 and then finds
no 80 °C column to look up. Our resistance accessor currently **interpolates**
and returns a number the standard does not publish. That is exactly the silent
default the whole design is meant to prevent, and we would rather raise.

---

## Q1. What happens when the banded temperature has no column on the table in use?

Three candidate readings, and we do not want to pick one by inference:

1. **Band only to columns the table carries.** A multicore cable at 82 °C bands
   to 90 °C, not 80 °C. Clause 4.4's list is then the union across tables rather
   than a per-lookup target.
2. **Band to Clause 4.4's list, then raise** if the resulting column is absent.
   The case goes to Clause 4.5 from R and X instead.
3. **Band to Clause 4.4's list, then take the next column the table does carry**,
   which for 80 °C on a multicore table means 90 °C.

Readings 1 and 3 agree for 80 °C on multicore and may diverge elsewhere. Reading
2 is the most conservative about not inventing values and the most disruptive.

Does Clause 4.4 or its notes address a banded temperature with no corresponding
column? If not, we will implement reading 1 as an `[M5 rule]`, since it never
produces a value the standard does not publish, and record it as an open item.

## Q2. OI-5.3, round-to-nearest against round-down — still open and now dated

We have implemented round-to-nearest as R-VD-8 and it reproduces the Tricab gap
exactly, which is real evidence. But you flagged that a θO of 70 °C goes to 75
under nearest and 60 under round-down, about 3 % in Vc, and both published
worked examples happen to round downward so they do not separate the two.

Every DAME case so far has landed above 75 °C where the two agree. The first
case between 60 and 75 will be decided by a convention chosen because it matched
one third-party tool. Is there anything further in Clause 4.4, its notes, or
another worked example that separates them?

## Q3. OI-5.4, which base column the spacing uplift adds to

R-FRM-7 adds the uplift to the flat touching value on the reasoning that spaced
cables lie in a row. You noted the trefoil base would give about 5 % less Vc at
400 mm². Table 4.1(A) NOTE 1 says Columns 1 to 6, which spans both formations
and does not choose.

This one blocks implementation. `air_spaced` has no tabulated Vc at all
(R-FRM-6), so every spaced circuit routes through Clause 4.3 and every one of
them needs this answered. We have not implemented the spaced path yet for
precisely this reason.

---

## What we are not asking

R-FRM-9 and R-VD-9 are clear and are implementation work, not questions. We will
build the Clause 4.3 spaced path once Q3 lands, and thread the corrected
capacity into the temperature equation per R-VD-9.

OI-5.5, the "4.20A" naming in the Clause 4.4 list, we are treating as a
typographical matter and not blocking on it.

---

## Addendum, added after first writing — Table 4.29 and a reversal of our own

Applying R-VD-2 to Table 4.29 (MIMS) turned up 34 failing cells and, in doing
so, reversed a conclusion we had recorded in the dataset weeks ago. We are
flagging it because the failure mode was the same one you diagnosed in ANS-001,
and we made it twice.

**What R-VD-2 finds.** 92 of 126 cells conform. The 34 that do not are 17 in the
100 °C column and 17 in the 105 °C column, worst error 24.7 %, and they are
confined to sizes where the cable's own power factor is at or above 0.8. There
the printed 0.8 p.f. value is roughly 0.8× the Max value, when R-VD-2 requires
it to equal Max. At 400 mm² the cable power factor is 0.61, the 0.8 branch is
correct, and 90, 100 and 105 °C all agree to 0.28 %.

**What we had previously concluded, and it was wrong.** Before ANS-001 we
recorded the opposite: that the 100/105 °C columns were correct because they
carried the computed √3(0.8R + 0.6X), and that the 45–90 °C columns were
"conservative placeholders". We inferred the convention from the shape of the
data rather than from the clause. Under R-VD-2 it is the other way round — the
45–90 °C columns are correct and the 100/105 °C columns are not.

That is the identical error to the "repeats the Max value below 240 mm²"
inference you corrected, made independently on a different table. We have
rewritten both dataset notes and marked the old ones as superseded.

**The question.** Please confirm against the printed Table 4.29(B) whether the
100 °C and 105 °C 0.8 p.f. columns carry roughly 0.8× the Max value at the
smaller sizes. If they do, the printed table applies the 0.8 formula outside its
own branch condition, and we would like to know whether that is a known erratum
or a reading we still have wrong.

Cell counts are in `spec-exchange/private/ASK-002-values.md`.
