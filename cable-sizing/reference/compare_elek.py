#!/usr/bin/env python3
"""Cross-check our AS/NZS 3008 primitives against ELEK's published worked example.

Source: https://elek.com/calculators/cable-sizing-as, captured 2026-09-02 into
reference/elek-cable-sizing-as.txt. ELEK publishes every intermediate quantity
of one calculation plus the equations behind it, which makes it an independent
check on our own implementation rather than just another opinion.

Their stated inputs: 100 A load at pf 0.9 lagging, single phase 230 V, 50 m run,
PVC V-75 copper single core, unenclosed spaced (Table 3.9), ambient 40 C,
tabulated rating 187 A, correction factor 1.00, fault level 3 kA, t = 0.1 s.

Run: python3 reference/compare_elek.py
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import as3008

CU = as3008.CONDUCTORS["Copper"]
TOL_PCT = 0.5
results = []


def check(label, ours, elek, unit=""):
    delta = 100.0 * (ours - elek) / elek if elek else 0.0
    ok = abs(delta) < TOL_PCT
    results.append(ok)
    print(f"  [{'MATCH' if ok else 'DIFF '}] {label:<34} "
          f"ours={ours:10.4f}{unit}  elek={elek:9.4f}{unit}  {delta:+7.2f}%")
    return delta


print(__doc__.split("Run:")[0].strip())
print("\n--- shared formulas: these should agree ---")
t_op = as3008.operating_temperature(40, 75, 100, 187)
check("operating temperature", t_op, 50.01, " C")

z = as3008.cable_impedance(0.433, 0.0962, power_factor=0.9)
vd = as3008.voltage_drop("1-phase", 100, 50, z, parallel=1)
check("voltage drop", vd, 4.32, " V")
check("voltage drop percent", 100.0 * vd / 230.0, 1.88, " %")

# ELEK reports Kph=129.02 alongside an operating temperature of 50.01 C, and
# KE=135.9 for the earth. Both fall out of our K formula exactly, which pins
# down their initial temperatures: the phase starts at its operating
# temperature and the earth starts at ambient, because it carries no load.
check("K phase  (Cu 50.01 -> 160)", as3008.k_constant(CU, t_op, 160), 129.02)
check("K earth  (Cu 40    -> 160)", as3008.k_constant(CU, 40, 160), 135.90)

print("\n--- fault path, replaying ELEK's own method ---")
c, v_pn = 1.1, 230.0
zn = c * v_pn / (3.0 * 1000.0)
check("network impedance Zn", zn, 0.0843, " ohm")
# Resistance at ambient, not at operating temperature: a colder conductor has
# the lower resistance that maximises fault current. And a single-phase loop
# runs out along the active and back along the neutral, so it is counted twice.
z_one = math.hypot(0.418 * 50 / 1000.0, 0.0962 * 50 / 1000.0)
ipn = c * v_pn / (zn + 2 * z_one)
check("phase-to-neutral fault Ipn", ipn, 1988.89, " A")
check("min phase area Sph", as3008.min_area_for_fault(ipn, 0.1, 129.02), 4.87, " mm2")

print("\n--- fault path, our engine's method, same inputs ---")
i_ours = as3008.prospective_fault_current(
    v_pn, v_pn / (3.0 * 1000.0), math.hypot(0.433, 0.0962) * 50 / 1000.0)
d_i = check("fault current", i_ours, 1988.89, " A")
check("min phase area", as3008.min_area_for_fault(i_ours, 0.1, 129.02), 4.87, " mm2")
print(f"  -> we read {d_i:+.1f}% on a SINGLE-PHASE fault because we count the")
print("     cable impedance once and omit the c=1.1 voltage factor. Higher")
print("     fault current means a larger required area, so this oversizes.")

print("\n--- the same two differences on a THREE-PHASE fault ---")
# A three-phase symmetrical fault returns through the star point, so counting
# the phase conductor once is right here. Only the c factor is left, and it
# now runs the other way: it raises ELEK's answer above ours.
v_ph, i_f_ka, zc = 415.0 / math.sqrt(3.0), 50.0, math.hypot(0.247, 0.08) * 10 / 1000.0
ours_3ph = v_ph / (v_ph / (i_f_ka * 1000.0) + zc)
elek_3ph = c * v_ph / (c * v_ph / (i_f_ka * 1000.0) + zc)
print(f"  ours={ours_3ph:10.1f} A   elek={elek_3ph:10.1f} A   "
      f"{100.0*(ours_3ph-elek_3ph)/elek_3ph:+.2f}%")
print("  -> on three-phase faults we sit BELOW ELEK, so the c factor is the")
print("     one difference that makes us less conservative, not more.")

print(f"\n{sum(results)}/{len(results)} cross-checks within {TOL_PCT}%.")
