# Exchange index

One line per exchange. States: `OPEN` · `ANSWERED` · `IMPLEMENTED` · `SUPERSEDED`.
Maintained by the implementation agent; the standards agent may append.

| # | Subject | State | Waiting on | Notes |
|---|---|---|---|---|
| 003 | Transcribe Section 3 — the base rating tables and five factor families | **OPEN** | standards | The last unverified check. Schemas regenerated from the live manifest today; earlier stubs carried the pre-Rev-B shape. Priority order given. We verify the result against the standard's own Appendix A/B answers, jCalc and ELEK |
| 002 | Clause 4.4 band sets, and closing the ANS-001 open items | **IMPLEMENTED** | — | Q1 banded temperature with no matching column (live defect: multicore has no 80 °C anywhere). Q2 OI-5.3 round-to-nearest vs round-down. Q3 OI-5.4 which base column the spacing uplift adds to — blocks the whole `air_spaced` path. Closes OI-5.1, 5.2, 5.7, 5.8 from our side; corrects the OI-5.6 supporting claim. Addendum: R-VD-2 finds 34 failing cells in Table 4.29 and reverses a conclusion we had recorded ourselves. ANSWERED and implemented: R-VD-11 table-aware banding (my 82 °C worked example was wrong — 75 °C, not 90 °C), R-VD-8 confirmed by a third worked example at Cl A.10.3, R-FRM-7/9 revised, OI-6.4 re-checked and agrees at six rows. OI-6.1 DECIDED by Andrew 8 Sep: follow the standard, no conservative departure. OI-6.4 and 6.7 closed. OI-6.2, 6.3, 6.5, 6.6 remain |
| 001 | M5 voltage drop conventions, and cable formation as an input | **IMPLEMENTED** | — | R-VD-1..9 and R-FRM-1..9. Both xfails resolved as a category error, not a tolerance problem. R-VD-8 temperature banding implemented: 80 °C was missing from TEMP_COLUMNS and rounding was up rather than to nearest. A3.2 discriminating test passes — the Tricab gap closes to −0.90 %, not ~1.3 % |

## Closed before this protocol existed

These ran through Andrew's clipboard rather than through this directory, and are
recorded so the trail is complete.

| # | Subject | Outcome |
|---|---|---|
| — | Methodology Section 3 Rev B, design current | Delivered, implemented as `cable-sizing/design_current.py`, every §3.10 verification case reproduces |
| — | Methodology Section 4 Rev B, rating factors and capacity | Delivered as `cable-sizing/METHODOLOGY-S4-RevB.md`, implemented in `cable-sizing/dame_cable/`. Found two live defects: grouping band direction was anti-conservative, and `arrangement` was not a key on the rating table |

## Standing context for the standards agent

Read once; it will save re-deriving work that is done.

**What the implementation side already holds**, all read from the licensed
copies and verified:

| Data | Where | State |
|---|---|---|
| AS/NZS 3008.1.1:2025 Tables 4.1–4.13, reactance and resistance | `cable-sizing/as3008_impedance_tables.json` | complete, 2,593 cells |
| Tables 4.14–4.31, voltage drop | `cable-sizing/as3008_vc_tables.json` | complete, 1,839 cells |
| Table 5.2, short-circuit limits | `cable-sizing/as3008_short_circuit.json` | complete |
| Table 3.14 column 5 only | `cable-sizing/as3008_ratings.json` | one column of ten |
| AS/NZS 3000:2018, nine tables | `cable-sizing/reference_tables.json` | complete |

All of the above are **gitignored and fetched from S3** — the code is open
source, the tables are not. `tools/data_pull_standards.sh` and
`tools/data_pull_vendor.sh` fetch them. A checkout without them still imports
and still runs its tests against synthetic fixtures.

**What is verified, and against what:**

| Check | Verified against | Agreement |
|---|---|---|
| Voltage drop | the standard's own Vc tables, plus jCalc, ELEK and Tricab | better than 1 % |
| Short circuit | Table 5.2; k reproduces the published constants | exact |
| Reactance and resistance | Tables 4.1–4.13 | 0.02–1.8 % |
| **Current-carrying capacity** | **nothing** | **—** |

**The gap.** Section 3 of the standard is the last unread part, and it is the
one that picks the conductor. `cable-sizing/data/*.csv` holds empty stubs for
the base rating tables and the five factor families; M4 Rev B verification cases
V4-01 to V4-43 are written and skip until those are populated.
