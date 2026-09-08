# AU013-143 — Concept A cooling: load check, redundancy options, hall fit

Cross-check of the ticket against the current `DAME_AU01_Building.FCStd` layout
(read live, 18 Aug 2026) and against what the `cfd-cabinet-cooling` hall model
can and cannot yet answer. Updated 18 Aug PM: FWCV figures verified against the
brochure PDF (Vendors/Schneider/ProductBrochures); all coolers confirmed on the
chilled water loop; ticket description corrected (45 kW spine, B300 HGX, 807.5,
hall clear width). Delta RowCool 95 kW and MCDU-40 remain as quoted.

## 1. Load sheet check

| Item | Air kW | Liquid kW |
|---|---|---|
| 16 racks × 8 B300 (36.75 / 68.25 per rack) | 588.0 | 1,092.0 |
| 2 × IB leaf @ 40 | 80.0 | — |
| 1 × IB spine | 45.0 | — |
| 1 × N/S ethernet | 13.8 | — |
| 1 × storage (TBC) | 15.0 | — |
| **Total** | **741.8** | **1,092.0** |

- The ticket's 741.8 kW air total only reconciles if the IB spine is **45 kW,
  not "45 W"** as originally written — with 45 W the total is 696.8. Fixed in
  the ticket 18 Aug; 741.8 is the right figure.
- Total IT 1,833.8 kW; air fraction 40 %.
- The ticket correctly flags that 741.8 excludes non-IT air loads. Items that
  land on the fan walls specifically: CDU standing losses to room air
  (~1–2 % of the 1,092 kW liquid loop ≈ 10–25 kW), TCS pipe/manifold gains,
  lighting, fabric gains. A working design figure of **~770–800 kW on the fan
  walls** is safer than 741.8. (FWCV "net sensible" ratings already net off
  their own fan heat; battery-room DX and the 2 × PTU CRAHs are separate
  systems and only show up as electrical load.)
- The worst **air** rack is the IB leaf at 40 kW — above the B300's 36.75. If
  the leaves split into 2 × 20 kW the worst air rack becomes the 45 kW spine,
  which then dominates hot-spot behaviour instead.
- Airflow demand at 741.8 kW: 151,000 m³/h at ΔT 15 K (42 m³/s), 113,000 m³/h
  at ΔT 20 K. The B300 air-side ΔT assumption needs pinning down before fan
  wall airflow (as opposed to kW) can be checked — this decided everything in
  the CFD sweeps.

## 2. Redundancy arithmetic (the ticket's headline question)

Against 741.8 kW IT air (first %) — remembering the real target is nearer
770–800 kW:

| Option | Installed | N ÷ load | N−1 | N−1 ÷ load |
|---|---|---|---|---|
| 4 × 36L1 (2 per end, single height) | 768.0 | 104 % | 576.0 | **78 % — not redundant** |
| 4 × 40L1 (2 per end) | 950.0 | 128 % | 712.5 | **96 % — 29 kW short of N+1** |
| ~~6 × 36L1 (3-high / 2+1 stacked)~~ | — | — | — | not a vendor option: L2 = 2 modules max |
| 8 × 36L1 = 2 × 36L2 per end | 1,536.0 | 207 % | 1,344.0 | 181 % — over-installed, and fails the eave check |
| 6 × 36L1 side-mounted (3/end, 2.0 w × 3.6 h) | 1,152.0 | 155 % | 960.0 | 129 % ✓ IF vendor approves side mounting (top water/electrical, condensate, fan orientation all argue against) |
| 4 × 40L1 + 2 × 95 kW in-row | 1,140.0 | 154 % | 902.5 | 122 % ✓ (single worst failure = one 40L1) |
| 10 × 95 kW in-row (4+1 per side) | 950.0 | 128 % | 855.0 | 115 % ✓; per side 5 × 95 = 475 vs ~371 |

- The ticket's combo figure "lose 1 fan wall and 1 in-row → 803 kW" recomputes
  as **807.5 kW** (1,140 − 237.5 − 95) — same conclusion, and note that is a
  double-failure case; the single-failure number is 902.5 kW.
- **4 × 40L1 is tantalisingly close to N+1** (712.5 vs 741.8). If ~30 kW of
  air load can be moved to water (e.g. storage rack rear-door, or confirming
  the leaf racks' true dissipation), it becomes N+1 on IT load — but not
  against the 770–800 kW figure with parasitics. Treat it as N.
- All ratings are at brochure conditions (RAT 37 °C, EWT/LWT 20/30 °C).
  CONFIRMED 18 Aug: these coolers run on the **chilled water loop**, not the
  dry-cooler loop, so the 20/30 °C rating point is achievable and no
  water-temperature derate applies. (Brochure figures verified same day:
  36L1 = 192 kW / 50,000 m³/h; 40L1 = 237.5 kW / 62,500 m³/h; L2 = 2 stacked
  modules — 2-high is the product, 3-high is not a vendor option.)
- kW redundancy is necessary but not sufficient — the CFD showed intake
  temperature is decided by airflow balance and distribution, and losing one
  unit is asymmetric (one end of the hall loses half its supply). The N−1
  case needs a flow field, not just a capacity sum — see §4.

## 3. Fit against the current FreeCAD layout

What the model shows today: pod of 24 racks (2 × 12 at 610 pitch, run 7,320,
racks 600 × 1,200 × 2,000 H, 42U) at x 8,140–15,460; contained hot aisle 1.8 m
wide, HAC roof at 2.0 m; side aisles asymmetric — ~1.4 m south, ~2.6 m north;
rack CDU bay (2 rack-size CDUs + manifold) on the pod's west end at
x 6,640–7,440; one 3,600 × 1,600 × 2,500 H fan wall block per end (FW-1 face
at x 4,800, FW-2 face at 21,735); pod-2 CDU line at 26,535–27,435; pump room
wall at x 28,500; hall walls to z 4,138 (as-built eave ~4,090); comms room
as-built 1,400 deep at the west end (extent TBC).

Checks against the ticket's options:

1. **Width.** Clear width between wall faces in the model is **8,200 mm**
   (walls 150 thick set out on the 0/8,350 grid), not 8,350. Two 40L1 side by
   side = 8,000 leaves ~100 mm a side — not buildable. Two **36L1** = 7,200
   leaves ~500 mm a side — feasible but tight against girts/services.
2. **Stacking.** 2 × 2,000 H = 4,000 vs eave ~4,090 (model wall top 4,138):
   90–140 mm nominal, before purlins, bracing, seismic restraint or any top
   ducting. Stacking at the end walls is **not viable on current numbers**
   without a confirmed under-structure clearance survey at the end bays.
   6 × 36L1 (the first stack option that clears N+1 comfortably) therefore has
   no home unless the roof zone at the ends proves clearer than the eave line.
3. **Drawn fan walls are placeholders.** The two 3,600 × 2,500 blocks in the
   model match no catalogue unit (L1s are 2,000 H) and, read as 36L1s, give
   2 × 192 = 384 kW — **half the concept-A air load**. The model needs
   updating to whichever option survives.
4. **The pod CDU bay sits in FW-1's discharge.** CDU-009/010 (2,000 H) are
   1,840 mm in front of the west fan wall face, directly upstream of the
   west-end racks. The hall CFD's central finding was that **end racks are
   the starved, hottest ones** because the supply jet separates at the pod
   corners — a 2 m obstruction in front of the west end racks makes that
   worse. Either the CDU bay moves (e.g. east end, beside the pod-2 line) or
   the CFD must include it before concept A is signed off.
5. **Run lengths.** Between current FW faces there is 16,935 mm; at RD110-ish
   clearances (~4.8 m each end) the pod maxes out at ~7.3 m — exactly the
   24-rack run drawn. The 10 × in-row option (row grows to ~10.4 m) only fits
   because it deletes the fan walls; the combo (+1 in-row per row, ~7.9 m)
   fits with fan walls retained but eats the end clearance the fan walls need.
   These are mutually constraining — worth a set-out sketch per option.
6. **Rack positions vs load placement.** The model has NET racks at positions
   6/7 (mid-row) — consistent with the CFD recommendation to keep the
   heaviest air loads out of the end positions. Keep the 40/45 kW network
   racks mid-row in concept A; put storage/low-density at the ends.

## 4. What the CFD model needs before it can answer the ticket

The current `case-hall` demonstrated the method but models a different hall.
To answer "how much fan wall redundancy do we have for B300 HGX":

1. **Geometry to AU01:** hall clear width 8.2 m, wall/eave height ~4.1 m,
   asymmetric side aisles (1.4 / 2.6 m), hot aisle 1.8 m, HAC roof 2.0 m,
   racks 2.0 m at 610 pitch. **Delete the ceiling return plenum** — it does
   not exist at AU01; the return path is the open room above the containment.
2. **Real units:** model each fan wall module as its own supply/intake patch
   (2 × 36L1 or 40L1 per end, stacked variants if they survive the height
   check) so single-unit failure is a switch, not a re-mesh. Airflow and
   supply temperature from the brochure at the actual water temperatures, not
   an assumed 28 °C.
3. **Per-rack loads:** 36.75 kW × 16, leafs 40 (or 20 × 4), spine 45,
   ethernet 13.8, storage 15 — the hall generator currently only takes one
   uniform `rackLoad_kW`; port the row case's `row_loads.csv` mechanism.
4. **Include the CDU bay** (and pod-2 CDU line if in the flow path) as solid
   blocks.
5. **Scenarios that decide the ticket:** all units on; worst single unit off
   (west end, given the CDU obstruction); ΔT sensitivity 12/15/20 K on the
   B300 HGX air share. Verdict against A1 allowable with the peak metric
   window-averaged (per the model review).

## 5. Open items

1. FWCV brochure figures unverified from this session — pull 36L1/40L1
   airflow (m³/h), net sensible at design water temps, and unit weight (floor
   loading for stacking) from the PDF in the ticket.
2. B300 air-side ΔT / airflow per rack — needed to turn kW redundancy into
   airflow redundancy.
3. Under-structure clearance at the hall end bays (survey) before any stacked
   option is carried.
4. Fix "45W" → 45 kW in the ticket; confirm storage rack layout (flagged TBC).
5. Liquid side largely closes: 2 × MCDU-40 (1.2 MW each) N+1 against
   1,092 kW ✓ at nameplate — same water-temperature derate caveat applies.
6. Ticket asks for the power draw of the cooling system — fan wall fan kW,
   CDU pump kW and CR95 pump duty are all still unquantified; brochure +
   pump curves needed.
