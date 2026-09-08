# ASK-003 — Transcribe Section 3, so capacity stops being the one unverified check

**Date** 8 September 2026 · **From** the implementation agent · **State** OPEN ·
**Reply to** `spec-exchange/ANS-003-section-3-transcription.md`

ANS-002 is implemented and closed. This is the last piece.

## The ask, in one line

Populate the Section 3 datasets from the licensed copy, into the CSV schemas
below, so the M4 acceptance cases V4-01 to V4-43 can run.

## Why this and not more analysis

Every other check is verified to better than 1 % against the standard's own
tables and three independent calculators. Capacity is verified against nothing,
and it is the check that picks the conductor.

We currently hold **one column of ten** — Table 3.14 column 5, air touching, and
that itself came from a third-party calculator rather than the standard. The
other nine arrangements are, as of today, that column scaled by the ratio to it
at 400 mm², using the ten values you gave in M4 Rev B §4.10.1. That is
estimation grade and it is marked as such in the data. It replaced something
worse — every arrangement returning the touching rating, up to 47 % optimistic
for thermal insulation — but it is a stopgap and should not survive contact with
a real design.

The transcription is the only thing that fixes it. Andrew's framing is right:
we should be doing capacity off the standard and using jCalc and ELEK to check
it, not the other way round.

## Schemas — these are live, please match them exactly

Regenerated from the manifest today, after the M4 Rev B key changes. Earlier
stubs carried the pre-Rev-B shape and would have landed in the wrong columns.

```
ccc.csv                  table,arrangement,material,size_mm2,current_a
ccc_reference.csv        table,reference_ambient_air_c,reference_ambient_soil_c,
                         reference_soil_resistivity_km_w,reference_depth_m,max_conductor_c
cf_ambient_air.csv       max_conductor_c,ambient_c,cf
cf_ambient_soil.csv      max_conductor_c,ambient_c,cf
cf_grouping.csv          grouping_code,circuits,cf
cf_depth.csv             table,axis_value,depth_m,cf
cf_soil_resistivity.csv  arrangement,resistivity_km_w,cf
cf_harmonic.csv          third_harmonic_fraction,basis,band_upper_fraction,cf
```

Notes on the ones that bite:

- **`ccc.csv` `table`** is "3.9" through "3.20" per R-TBL-1. `insulation`,
  `construction` and `cores_loaded` are NOT columns: R-TBL-1 resolves the first
  two into `table`, and `cores_loaded` is not an axis of any base table.
- **`arrangement`** takes the §4.4 enumeration verbatim: `air_spaced`,
  `air_spaced_from_surface`, `air_touching`, `air_exposed_to_sun`,
  `enclosed_conduit_in_air`, `insulation_partial`, `insulation_complete`,
  `buried_direct`, `buried_conduit_shared`, `buried_conduit_single_way` for
  single-core; the multicore set replaces `air_spaced_from_surface` and the two
  insulation values per §4.4.2.
- **A dash in the printed table is a missing row, not a zero.** Omit it.
- **`cf_depth.csv` `table`** is "3.46" or "3.47"; `axis_value` is the size band
  for 3.46 and single_core/multicore for 3.47, per R-ADM-1.
- **`cf_grouping.csv` `grouping_code`** carries the table and item identity —
  support type, circuit spacing and row count — with `circuits` as the banded
  axis. Name them however is natural and tell us the scheme; we will map to it.

These files are gitignored. `spec-exchange/private/` is available if you would
rather stage them there.

## Priority, if it cannot all be done at once

1. **Table 3.14, all ten arrangement columns, Cu and Al.** Unblocks V4-01 to
   V4-13 and replaces the derived ratios for the family we actually use.
2. **Tables 3.12 and 3.18.** Unblocks the Appendix A and B published answers,
   V4-36 to V4-43, which are the strongest acceptance cases we have.
3. **`cf_ambient_air` and `cf_grouping`.** The two factors every air circuit
   touches.
4. Everything else.

## Then we verify it, three ways

Once the data lands we will run, and report back:

- **The standard against itself.** V4-36 to V4-43 are the published worked
  answers from Appendix A.1.2 and B, carrying no DAME arithmetic.
- **jCalc.** Confirmed reachable and drivable today at
  `jcalc.net/cable-sizing-calculator-as3008`, defaulting to 2025 Australian
  conditions. It exposes conductor material, insulation, cable type, size,
  installation arrangement and derating inputs, so a matrix across sizes,
  arrangements, materials and insulation types is straightforward.
- **ELEK.** `elek.com/calculators/cable-sizing-as`, as a second independent
  implementation. Where the two calculators agree and we differ, we are wrong.

That is the same pattern that settled the impedance tables, where jCalc and ELEK
agreeing on 839 A was what gave us confidence before the printed column existed.

## One thing to confirm while you are in Section 3

**OI-6.3.** Is the 80 °C band reachable for any real cable? It exists on Tables
3.9–3.20's resistance counterparts and on four Vc tables, but no insulation type
has an 80 °C limit, so it is only reached by a 90 or 110 °C cable running near
80. If nothing can reach it, R-VD-11's candidate set shrinks and we can say so.
