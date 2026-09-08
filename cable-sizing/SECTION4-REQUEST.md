# Spec request: Methodology Section 4 — Rating Factors and Current-Carrying Capacity

Please produce **Methodology Section 4, Revision B**, in the same form as
Section 3 Rev B (Design Current), which worked well: the module built from it
reproduced every verification case first time.

## Naming trap — please read first

"Section 3" is ambiguous and has already cost us once.

- **Methodology Section 3** is *Design Current*. Delivered as Rev B, implemented
  as `design_current.py`, all verification cases passing.
- **Section 3 of AS/NZS 3008.1.1:2025** is *current-carrying capacity*, which the
  Methodology consumes in **Section 4**.

This request is for **Methodology Section 4**, consuming AS/NZS 3008.1.1:2025
Section 3 tables.

## What already exists — please supersede deliberately, not by accident

`dame-cable` already implements this and is blocked only on data:

    src/dame_cable/rating_factors.py     261 lines
    src/dame_cable/current_capacity.py   178 lines

Public API: `build_factor_set()`, `harmonic_treatment()`, `tabulated_capacity()`,
`capacity()`, `check_capacity()`. 74 tests pass against synthetic fixtures.

Its CSV table schema already has the right key:

    ccc: key_columns = ("arrangement", "material", "insulation",
                        "construction", "cores_loaded", "size_mm2")
         value_column = "current_a"

So what is wanted is **the spec that pins the conventions and supplies numeric
verification cases**, not a fresh implementation. If new modules are proposed,
say explicitly what they replace and why.

## Please include all three of these

1. **Conventions stated as rules**, not prose. The `DeclaredAs` table in Rev B is
   why double-counting derating factors is now impossible by construction. Do the
   same for this section.
2. **Numeric verification cases with expected answers.** Section 3.10 of Rev B is
   the reason the implementation could be called verified rather than plausible.
3. **Named open items**, so gaps are recorded rather than silently defaulted.

## Conventions that must be pinned

### 1. `arrangement` must be a real axis on the rating table

This is a live bug. The existing engine holds only Table 3.14 **column 5
(touching)** and copies that single column into all four installation-method
slots, so it returns a touching rating for a spaced installation.

Confirmed against the Tricab calculator on 2026-09-07: 839 A where the tool
gives 902 A for the same cable spaced. About 7 % conservative, but silently
wrong for three of the four methods offered.

The spec must state, for each installation arrangement, **which table and which
column** supplies its rating.

### 2. Band lookup direction, stated per table

`dame-cable` currently assumes:
- ambient temperature rounds **up** to the next band (43 °C takes the 45 °C row)
- grouping rounds **down** to the listed row (5 circuits take the 4-circuit row)

Both are the conservative direction. Please confirm both against the printed
tables, and state whether running off the top of a band should raise or clamp.

### 3. Reference conditions per rating table

The ambient correction has no datum without them. `ccc_reference.csv` exists for
this and is empty. State what headnote data each capacity table carries:
reference ambient, reference soil resistivity, reference depth.

### 4. What "spaced" means

We concluded it is clearance **to the surface**, not separation between phases,
so the NOTE 1 reactance spacing correction does **not** apply. The Tricab
calculator agrees: it uses 0.080 Ω/km, which is the touching-trefoil value. The
1D-spaced value would be 0.123 Ω/km — 55 % out. Please state this rather than
leaving it to be inferred.

### 5. Harmonic bands — the highest-value missing dataset

Clause 3.5.9 / Table 3.4. The band edges are 15 % and 33 % third-harmonic
content, while the physical crossover where neutral current overtakes phase
current is 1/√8 = 35.36 %. The standard's edge governs and is slightly
conservative of the physics.

The spec must say **which current the corrected capacity is compared against**
on each side of the band. `harmonic_treatment()` already returns a basis flag
for this. This is the dataset that governs most data centre distribution
circuits and no default is defensible in either direction.

## Verification cases we need

Please supply expected numbers. These are what can already be checked against:

| Source | Case | Expected |
|---|---|---|
| Tricab calculator, 2026-09-07 | Cu flex, 400 mm², X-HF-110, 3×1C trefoil, unenclosed **spaced from surface**, 40 °C, no grouping | **902 A** |
| Tricab calculator, 2026-09-07 | Al, 500 mm², same arrangement | **837 A** |
| AS/NZS 3008.1.1 Table 3.14 col 5 | Cu X-HF-110, 400 mm², **touching**, 4 loaded cores | **839 A** |
| jCalc and ELEK, already in the repo | same as above | 839 A |

The 902 / 839 pair is the most useful: it pins the spaced-to-touching ratio at
about 1.075.

Caveat to carry: 902 A is Tricab KL-series product data and may not be the
standard's own table figure.

Please provide at least:
- one case per installation arrangement
- one case with a grouping factor applied
- one case at an ambient other than the reference
so the correction chain is exercised and not just the base lookup.

## Table shopping list

For each, please give the **table number, its column headings, and its reference
conditions**:

- Tables 3.1–3.15, current-carrying capacity, and critically **which column
  corresponds to which installation arrangement**
- Ambient air correction (the manifest currently guesses Table 3.44 — confirm)
- Ambient soil correction
- Grouping, for each arrangement
- Depth of burial
- Soil thermal resistivity
- Thermal insulation contact
- Solar radiation
- Table 3.4 harmonic bands, per clause 3.5.9

Seven correction factors plus the base tables. All seven are empty today.

## Open items to name

- Whether reference ambient differs between the air and soil table families
- Behaviour between tabulated sizes: interpolate or step, and in which direction
- Whether the harmonic factor derates the phase capacity, the neutral, or both
- Cyclic and short-term ratings for generator and UPS bypass circuits, currently
  out of scope in Section 1 but the question keeps recurring

## Why this is the priority

Section 4 is the last unread part of the standard, and it is the one that picks
the conductor. Everything downstream — voltage drop, short circuit, earth fault
— is now verified to better than 1 % against the standard's own published
answers and against three independent calculators. Capacity is verified against
nothing.
