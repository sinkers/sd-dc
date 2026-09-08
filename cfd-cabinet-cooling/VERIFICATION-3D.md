# 3D verification record

Phases 1–3 of `PLAN-3D.md`, run locally. Raw outputs in `verification/`.

## Phase 1 — width parametrised, 2D result must be unchanged

`nCabinets 1`, `endClearance 0`, symmetry sides. The derived tolerances resolve
to `rowY0M = -0.01`, `rowY1P = 0.61` — byte-identical to the literals they
replaced, so this should be a provable no-op.

| quantity | 2D reference | Phase 1 | |
|---|---|---|---|
| intake mean | 20.19 °C | 20.19 °C | identical |
| intake peak | 20.22 °C | 20.22 °C | identical |
| exhaust | 36.21 °C | 36.21 °C | identical |
| supply | 2.037 kg/s | 2.037 kg/s | identical |
| through servers | 1.847 kg/s | 1.847 kg/s | identical |
| gap flow | +0.191 kg/s | +0.191 kg/s | identical |

**PASS** — every reported figure unchanged.

## Phase 2 — widen to 4 cabinets, symmetry retained

430,080 cells, 8 ranks, 545 s. The row still spans the full width, so this is a
wider slab of an identical problem: temperatures must not move, and mass flows
must scale exactly 4×.

| quantity | Phase 1 | Phase 2 | ÷4 | delta | tolerance |
|---|---|---|---|---|---|
| intake mean | 20.19 | 20.18 | — | −0.01 K | ≤ 0.1 K **PASS** |
| intake peak | 20.22 | 20.22 | — | 0.00 K | ≤ 0.1 K **PASS** |
| exhaust | 36.21 | 36.21 | — | 0.00 K | ≤ 0.1 K **PASS** |
| supply | 2.037 | 8.148 | 2.037 | +0.0 % | ≤ 2 % **PASS** |
| through | 1.847 | 7.384 | 1.846 | −0.1 % | ≤ 2 % **PASS** |
| gap | 0.191 | 0.764 | 0.191 | +0.0 % | ≤ 2 % **PASS** |

**PASS.** This is the load-bearing test: it proves the 3D generalisation is
sound before any new physics is introduced.

### One real bug caught here

`heatLoad` is consumed by a `scalarSemiImplicitSource` with
`volumeMode absolute`, which means *total over the zone*. Widening the row made
the zone 4× bigger while leaving the total at 30 kW — i.e. 7.5 kW per cabinet.
Fixed by deriving `rowHeatLoad = nCabinets × heatLoad`. Without that, Phase 2
would have "passed" on temperatures for entirely the wrong reason.

## Phase 3a — per-cabinet zones, uniform load

`make_row_dicts.py` generates one cell zone, one heat source, one fan source and
three metrics per cabinet. Zone sizes came out at 12,672 cells and 528 inlet
faces each — identical to the single-cabinet values, so the ±0.01 m band
tolerance does not let neighbours claim each other's cells.

| cabinet | load | intake mean | intake peak | flow |
|---|---|---|---|---|
| 0 | 30 kW | 20.19 °C | 20.22 °C | 1.846 kg/s |
| 1 | 30 kW | 20.19 °C | 20.22 °C | 1.846 kg/s |
| 2 | 30 kW | 20.19 °C | 20.22 °C | 1.846 kg/s |
| 3 | 30 kW | 20.19 °C | 20.22 °C | 1.846 kg/s |

**PASS** — zero spread, all flows positive (so no face-zone `flip` errors), and
4 × 1.846 = 7.384 kg/s matches the Phase 2 aggregate exactly.

## Phase 3b — mixed-load row: the first genuinely 3D result

Loads 45 / 30 / 30 / 15 kW (120 kW total, so directly comparable to Phase 3a)
with supply dropped to 1.15 m/s so the containment gap actually recirculates
(−0.515 kg/s, supply/demand 0.93).

| cabinet | load | intake mean | intake peak | flow | verdict |
|---|---|---|---|---|---|
| 0 | 45 kW | 22.06 °C | **36.97 °C** | 1.777 kg/s | MARGINAL |
| 1 | 30 kW | 21.99 °C | 36.54 °C | 1.788 kg/s | MARGINAL |
| 2 | 30 kW | 22.29 °C | 36.47 °C | 1.793 kg/s | MARGINAL |
| 3 | 15 kW | 22.43 °C | 36.26 °C | 1.803 kg/s | MARGINAL |

Three things here were invisible to the 2D case:

1. **Peak intake orders cleanly by load** — 36.97 °C at the 45 kW cabinet down to
   36.26 °C at the 15 kW one. The hottest cabinet's own exhaust drives slightly
   worse local recirculation, so it partly poisons itself.
2. **Mean intake does not order by load at all** — the 30 kW cabinet 1 has the
   *lowest* mean (21.99 °C). Another instance of the mean being the wrong metric.
3. **The highest-load cabinet gets the least mass flow** (1.777 vs 1.803 kg/s).
   The server fans hold a target *velocity*, and hotter air is less dense, so the
   cabinet that needs the most cooling receives ~1.5 % less air than its coolest
   neighbour. A compounding penalty, and a purely multi-cabinet effect.

The spread is modest (0.44 K mean, 0.71 K peak) because symmetry side planes make
the row repeat infinitely, which limits lateral redistribution. **Expect a larger
spread once Phase 4 introduces real row ends** — that is the next step.

## Acceptance criteria from PLAN-3D.md

| # | Criterion | Status |
|---|---|---|
| 1 | `nCabinets 1` reproduces the 2D result exactly | **PASS** |
| 2 | Phase 2 matches Phase 1 within 0.1 K / 2 % | **PASS** |
| 3 | `checkMesh` clean, zero `empty` patches | **PASS** |
| 4 | Mass balance closes | **PASS** |
| 5 | Energy balance closes to ~1 % (118.9 vs 120 kW) | **PASS** |
| 6 | Every per-cabinet inlet flow positive | **PASS** |
| 7 | Supply split into `nFanUnits` changes nothing | not yet — Phase 5 |
| 8 | `plot_row.py` identifies the worst cabinet | **PASS** |
| 9 | Full row run under 30 min | **PASS** (545 s at 430 k cells) |

Still open: **Phase 4** (real row ends, `endClearance > 0`, side walls instead of
symmetry) and **Phase 5** (discrete fan wall units, fan-failure scenarios).
