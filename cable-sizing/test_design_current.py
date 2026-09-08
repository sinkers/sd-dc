"""Verification cases for design_current.py -- Methodology Section 3, Rev B."""
import math, os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from design_current import (
    Load, SystemType, DeclaredAs, LoadKind, design_current, board_design_current,
    true_power_factor, distortion_factor, neutral_to_phase_ratio,
    NEUTRAL_GOVERNS_THRESHOLD, unbalance_neutral_current, DesignCurrentError,
)

def approx(a, b, tol=1e-3):
    assert abs(a - b) < tol, f"{a} != {b}"

# 1. Basic three-phase real power
r = design_current(Load("L1", SystemType.THREE_PHASE, 400, DeclaredAs.KW_INPUT,
                        100, displacement_pf=0.9))
approx(r.i_phase, 100000/(math.sqrt(3)*400*0.9))
print(f"1. 100 kW, pf 0.9, 400 V 3ph      -> {r.i_phase:8.2f} A  ({r.apparent_power_kva:.1f} kVA)")

# 2. kVA declaration
r = design_current(Load("L2", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT, 250))
approx(r.i_phase, 250000/(math.sqrt(3)*400))
print(f"2. 250 kVA, 400 V 3ph             -> {r.i_phase:8.2f} A")

# 3. Motor: output power with efficiency
r = design_current(Load("M1", SystemType.THREE_PHASE, 400, DeclaredAs.KW_OUTPUT,
                        75, kind=LoadKind.MOTOR, displacement_pf=0.86,
                        efficiency=0.94))
expected = (75/0.94)*1000/(math.sqrt(3)*400*0.86)
approx(r.i_phase, expected)
print(f"3. 75 kW motor, eta 0.94, pf 0.86 -> {r.i_phase:8.2f} A")

# 4. True vs displacement power factor
lam = true_power_factor(0.98, 0.30)
approx(lam, 0.98/math.sqrt(1.09))
print(f"4. cos(phi1)=0.98, THDi=30%       -> lambda {lam:.4f}  (vs 0.98 displacement)")
r_disp = design_current(Load("X", SystemType.THREE_PHASE, 400, DeclaredAs.KW_INPUT,
                             100, displacement_pf=0.98))
r_true = design_current(Load("X", SystemType.THREE_PHASE, 400, DeclaredAs.KW_INPUT,
                             100, displacement_pf=0.98, thd_i=0.30))
print(f"   same 100 kW ignoring THD       -> {r_disp.i_phase:8.2f} A")
print(f"   same 100 kW with THD           -> {r_true.i_phase:8.2f} A  "
      f"(+{100*(r_true.i_phase/r_disp.i_phase-1):.1f}%)")

# 5. Neutral ratio crossover
approx(neutral_to_phase_ratio(NEUTRAL_GOVERNS_THRESHOLD), 1.0, 1e-9)
print(f"5. neutral governs above h3 =      {NEUTRAL_GOVERNS_THRESHOLD:.4f} "
      f"({NEUTRAL_GOVERNS_THRESHOLD:.1%})")
for h3 in (0.10, 0.15, 0.25, 0.3536, 0.45, 0.60):
    print(f"   h3={h3:5.1%}  In/IL = {neutral_to_phase_ratio(h3):.3f}")

# 6. Neutral governing case picked up automatically
r = design_current(Load("IT1", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT,
                        300, spectrum={3: 0.45, 5: 0.20, 7: 0.10}))
print(f"6. 300 kVA, h3=45%  phase {r.i_phase:.1f} A  neutral {r.i_neutral:.1f} A "
      f"-> governs: {r.governing_conductor}")
assert r.governing_conductor == "neutral"

# 7. UPS input with recharge
r = design_current(Load("UPS-A", SystemType.THREE_PHASE, 400, DeclaredAs.KW_OUTPUT,
                        500, kind=LoadKind.UPS_INPUT, displacement_pf=0.99,
                        efficiency=0.96, ups_recharge_fraction=0.10))
expected = (500/0.96*1.10)*1000/(math.sqrt(3)*400*0.99)
approx(r.i_phase, expected)
print(f"7. 500 kW UPS, eta 0.96, +10% chg -> {r.i_phase:8.2f} A")

# 8. Balanced load produces no fundamental neutral current
approx(unbalance_neutral_current(100, 100, 100), 0.0, 1e-9)
approx(unbalance_neutral_current(100, 0, 0), 100.0, 1e-9)
print("8. unbalance neutral: balanced -> 0.00 A, single phase 100 A -> 100.00 A")

# 9. Single phase
r = design_current(Load("S1", SystemType.SINGLE_PHASE_LN, 230, DeclaredAs.KW_INPUT,
                        7.2, displacement_pf=1.0))
approx(r.i_phase, 7200/230)
approx(r.i_neutral, r.i_phase)
print(f"9. 7.2 kW 1ph 230 V               -> {r.i_phase:8.2f} A (neutral equal)")

# 10. DC
r = design_current(Load("D1", SystemType.DC, 800, DeclaredAs.KW_INPUT, 250))
approx(r.i_phase, 250000/800)
print(f"10. 250 kW DC at 800 V            -> {r.i_phase:8.2f} A")

# 11. Board aggregation with diversity
loads = [
    Load("R1", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT, 100, diversity=1.0),
    Load("R2", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT, 100, diversity=1.0),
    Load("MECH", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT, 150, diversity=0.7),
]
b = board_design_current(loads, board_diversity=1.0)
print(f"11. board: 100+100+150x0.7 kVA    -> {b.i_phase:8.2f} A "
      f"({b.apparent_power_kva:.1f} kVA)")
approx(b.apparent_power_kva, 100+100+105)

# 12. Guard rails
for bad, desc in [
    (lambda: Load("E", SystemType.THREE_PHASE, 400, DeclaredAs.KVA_INPUT, 100,
                  displacement_pf=0.9), "pf set alongside kVA"),
    (lambda: Load("E", SystemType.THREE_PHASE, 400, DeclaredAs.KW_OUTPUT, 75,
                  kind=LoadKind.MOTOR), "motor output without efficiency"),
    (lambda: Load("E", SystemType.THREE_PHASE, -400, DeclaredAs.KVA_INPUT, 100),
     "negative voltage"),
]:
    try:
        bad(); raise AssertionError(f"should have rejected: {desc}")
    except DesignCurrentError:
        print(f"12. rejected: {desc}")

print("\nall checks passed")
