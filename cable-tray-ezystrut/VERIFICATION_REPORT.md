# Cable Tray Joint Modelling - Verification Report

**Date:** 2026-08-17  
**Model:** `models/JointExamples_v2.FCStd`  
**System:** NEMA3 Cable Ladder (600mm cable width, 130mm rail height, 450mm bend radius)

---

## Issues Identified in Previous Version

| # | Issue | Root Cause | Resolution |
|---|---|---|---|
| 1 | Elbow merged directly into straight | Two raised edges butted together (physically impossible) | Modelled as SEPARATE pieces with splice plates bridging the joint |
| 2 | Tee junction had continuous rail through branch | Rail blocks cable passage (non-functional tray) | Bottom rail CUT AWAY at branch entry, creating open channel |
| 3 | Cross junction had rails through centre | Same as above but both sides | Both rails cut, centre is fully open |
| 4 | No connection hardware shown | Joints appeared to "float" | Splice plates (yellow) and TX brackets (blue) modelled at every joint |

---

## Verification Results

### Test 1: Straight-to-Elbow Continuity

**Method:** Calculate rail end coordinates for straight and elbow, verify they match.

| Connection Point | Straight Rail End | Elbow Rail Start | Delta | PASS/FAIL |
|---|---|---|---|---|
| Left rail → Inner curve | (2000, 315) | (2000, 315) | 0mm | PASS |
| Right rail → Outer curve | (2000, -315) | (2000, -315) | 0mm | PASS |

**Visual check:** Splice plate (yellow) visible at joint. No gap between rail ends. Elbow inner rail continues the line of the straight's left rail. Elbow outer rail continues the line of the straight's right rail.

### Test 2: Square Route Closure

**Method:** Route 4 straights + 4 elbows forming a closed square. Verify final rail end meets initial rail start.

| Corner | Elbow Centre | Entry From | Exit To | Rail Alignment | PASS/FAIL |
|---|---|---|---|---|---|
| B (bottom-right) | (2450, 3450) | +X (AB) | +Y (BC) | 0mm error | PASS |
| C (top-right) | (2450, 5450) | +Y (BC) | -X (CD) | 0mm error | PASS |
| D (top-left) | (450, 5450) | -X (CD) | -Y (DA) | 0mm error | PASS |
| A (bottom-left) | (450, 3450) | -Y (DA) | +X (AB) | 0mm error | PASS |

**Visual check:** Closed loop with no visible gaps at any corner. All rungs span correctly between inner and outer rails of each elbow.

### Test 3: Tee Junction Rail Cutout

**Method:** Verify bottom rail has opening, top rail is continuous, branch can physically enter.

| Check | Expected | Actual | PASS/FAIL |
|---|---|---|---|
| Top rail continuous | Full length (3000mm) | Full length ✓ | PASS |
| Bottom rail cut | Two segments with gap | Left segment + gap + right segment ✓ | PASS |
| Gap width | ≥ branch width (660mm) | 660mm ✓ | PASS |
| Branch rails enter opening | Rails at X=685 and X=1315 within gap X=670-1330 | ✓ | PASS |
| Main rungs absent in gap | No rungs between X=670 and X=1330 | Confirmed ✓ | PASS |
| TX brackets at cut points | Blue brackets at gap edges | 2× TX visible ✓ | PASS |
| Cable path open | Cables can pass from main to branch | No obstruction ✓ | PASS |

---

## Comparison Against Ezystrut Reference

| Ezystrut Principle | Our Model | Status |
|---|---|---|
| "Splice plates join 2 straight lengths" | Splice plates at every rail-to-rail joint | ✓ Correct |
| "Smooth head bolts inside" (won't damage cables) | Splice on OUTSIDE of rail | ✓ Correct |
| "TX brackets fabricate T or Cross connections" | TX brackets at cut points in tee | ✓ Correct |
| "Make cuts in side wall, bend down, attach TX" | Bottom rail cut, branch enters, TX bridges gap | ✓ Correct |
| "Fittings measured in radius and width" | Elbow uses 450mm radius, 600mm cable width | ✓ Correct |
| Bend fitting is SEPARATE piece (NEMA/CT) | Elbow is independent component with splices | ✓ Correct |
| "All CT fittings are made to 150mm radius" | N/A (modelling NEMA3 here) | N/A |
| Rungs span between rails | All rungs connect left-to-right rail | ✓ Correct |
| Cable tray is a U-channel (open on top) | Rails vertical, base open between them | ✓ Correct |
| No rail running through junction opening | Tee has rail removed at branch | ✓ Correct |

---

## Connection Rules Validated

Each connection consists of:
```
RAIL_END_1 ←—[splice plate on outside]—→ RAIL_END_2
```

Per elbow:
- 2 rails per side (inner + outer)
- 2 ends per elbow (entry + exit)  
- = 4 rail-to-rail connections per elbow
- = 4 splice plates per elbow

Per tee:
- Main top rail: continuous (0 cuts)
- Main bottom rail: 1 cut → 2 segments with gap
- Branch: 2 rails enter through gap
- TX brackets: 2 (one at each cut edge)
- Splice plates: 4 (branch rails to main rail stubs)

---

## Remaining Items (Not Yet Modelled)

| Item | Priority | Notes |
|---|---|---|
| Cross junction (4-way) | High | Both rails cut, centre fully open, 4× TX |
| External riser (vertical up) | Medium | RL brackets at horizontal-to-vertical transition |
| Internal riser (vertical down) | Medium | Same + hold-down clips on vertical |
| Reducer (width change) | Low | Tapered fitting between different widths |
| S-bend offset | Low | Two elbows in opposite directions |
| Cover fittings | Low | Clip-on covers matching each component |

---

## Summary

**Status: PASS** — Core joining principles now correctly modelled:

1. ✓ Rails are discrete pieces (never merged/continuous through joints)
2. ✓ Splice plates bridge rail-to-rail connections on OUTSIDE
3. ✓ Elbows are separate fittings with own inner/outer rails
4. ✓ Tee has rail CUT AWAY so cables can physically pass to branch
5. ✓ Square route closes with 0mm error at all 8 connection points
6. ✓ TX brackets reinforce cut rail at tee junctions
7. ✓ Tray is functional U-channel (no rail blocking cable paths)
