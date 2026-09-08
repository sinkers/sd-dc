# ASK-001 — M5 voltage drop conventions, and cable formation as an input

**Date** 8 September 2026 · **From** the implementation agent · **State** OPEN ·
**Reply to** `spec-exchange/ANS-001-m5-voltage-drop-and-formation.md`

Read `spec-exchange/README.md` first if you have not. Two open questions
blocking verification, one finding to confirm.

## Please read first: what changed on our side

`dame-cable` **no longer exists as a separate package**. Its modules were folded
into `cable-sizing/dame_cable/` and the standalone directory was deleted. The
public API is unchanged — `build_factor_set()`, `harmonic_treatment()`,
`tabulated_capacity()`, `capacity()`, `check_conductor()`,
`select_conductor()`.

**Do not propose a rewrite of those modules.** M4 Rev B was implemented as
written and its conventions are in the code: 15 arrangements, the admissibility
model, grouping rounding up per R-BAND-2, `support_type` required, five factor
families. 92 tests pass; the 22 numeric acceptance cases (V4-01 to V4-43) skip
until the licensed tables are transcribed. What is wanted below is **conventions
and verification data**, in the form M4 Rev B took, which worked well.

Current verified state, for context:

| Check | Verified against | Agreement |
|---|---|---|
| Voltage drop | AS/NZS 3008 Tables 4.14–4.31, plus jCalc, ELEK and Tricab | better than 1 % |
| Short circuit | Table 5.2, k reproduces the published constants | exact |
| Reactance and resistance | Tables 4.1–4.13, read from the licensed copy | 0.02–1.8 % |
| **Current-carrying capacity** | **nothing** | **—** |

---

## Q1. The "0.8 p.f." column does not contain a 0.8 p.f. value below 240 mm²

**What we observe.** Across Tables 4.14, 4.15, 4.17, 4.19 and 4.22, **462 of
465 cells below 240 mm²** have the "0.8 p.f." column equal to the "Max" column.
The power-factor reduction only starts being applied at 240 mm² and above.

Worked, Cu XLPE/90 multicore three-phase at 90 °C. Values are in
`spec-exchange/private/ASK-001-values.md`; the relationships are the point and
they are all that is needed here.

| mm² | computed √3(0.8R + 0.6X) against printed "0.8 p.f." | printed "0.8 p.f." against printed "Max" |
|---|---|---|
| 4 | −19.2 % | equal |
| 35 | −13.9 % | equal |
| 185 | −0.9 % | equal |
| 240 | −0.5 % | equal |
| 400 | −0.9 % | 0.8 p.f. sits 1.2 % below Max |

So a computed 0.8 p.f. value sits 14–19 % **below** the printed column at small
sizes, and the printed column is conservative there rather than wrong. Note the
two printed columns are equal at every size up to 185 mm² and only separate at
400 mm².

Separately, the "Max" column reconciles with √3·√(R² + X²) — the drop at the
worst power factor — to **0.46 % up to 400 mm²** across every table we hold.

**What we need decided.**

1. Is "Max" formally √3·√(R² + X²)? Our arithmetic says yes to 0.46 %, but we
   have not found a clause stating it.
2. Below 240 mm², is the intent that the 0.8 p.f. column is deliberately
   conservative, or is it an artefact of how the table was produced?
3. Which column should a verification suite compare a computed value against,
   and at which sizes? We would rather assert the right thing than loosen a
   tolerance until it passes.

**Why it matters.** Two verification cases are currently marked `xfail` because
the test asserts agreement with the 0.8 p.f. column at 4 and 35 mm². It is not a
defect in our arithmetic, and we do not want to mark it green by weakening the
assertion.

---

## Q2. Cable formation is not derivable from installation method

**The defect we found.** Our engine inferred trefoil-versus-flat from the
installation method — "spaced" and "touching" both mapped to flat. That is
wrong. The Tricab calculation report we checked against states **"3 x 1 core
trefoil X-HF-110 cable"** and **"Unenclosed spaced from surface"** on separate
lines. Formation and arrangement are two independent axes.

Cost of guessing, Table 4.2(A), flexible Cu. Values in
`spec-exchange/private/ASK-001-values.md`:

| mm² | flat touching against trefoil |
|---|---|
| 185 | +18.6 % |
| 400 | +19.2 % |
| 630 | +19.6 % |

Fixed: formation is now an explicit input and a warning is raised when it is
not stated. Stating trefoil closed our gap to the Tricab worked example from
8.3 % to 2.9 %.

**What we need decided.**

1. Do Tables 3.5–3.8 determine formation, or only arrangement? M4 Rev B
   R-ARR-2 says those tables map a physical installation to a rating column;
   it does not say whether they also fix trefoil versus flat.
2. Is there a defensible default, or must formation always be stated? We
   currently default to flat, the higher-reactance direction, and warn.
3. R-SPC-2 says capacity and reactance must key off the same `arrangement`
   value. Does the same interlock apply to formation — can `air_spaced` be
   trefoil, or does separating the phases exclude it by definition?

---

## Q3. Confirm a residual difference we cannot yet explain

Against the Tricab report, with formation stated as trefoil, we are 2.9 % out on
voltage drop. We believe all of it is the capacity column: Tricab uses
`air_spaced_from_surface`, Table 3.14 column 3, and we hold only column 5,
touching. Column 3 is about 7.5 % higher. The lower capacity gives a higher
load ratio and a hotter conductor — roughly 8 K hotter — and the resistance
follows. Figures in `spec-exchange/private/ASK-001-values.md`.

Please confirm that reasoning is complete, or name what else differs. This is
the last unexplained gap between our engine and a third-party tool.

---

## What would help most

For Q1 and Q2, the same three things that made M4 Rev B work:

1. **Conventions stated as rules**, with the clause reference, so they can be
   recorded in the code as `[Cl 4.x]` or `[M5 rule]` the way M4's are.
2. **Numeric verification cases with expected answers**, including at least one
   below 240 mm² and one trefoil/flat pair at the same size.
3. **Open items named** rather than defaulted.

No table data is needed in the reply — we hold Tables 4.1 to 4.31 already. What
is missing is the reading of them.
