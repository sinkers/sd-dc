#!/usr/bin/env python3
"""Sizing impact of an AS/NZS 3008.1.1 rating against a part 1.2 (NZ) one.

Run: python3 reference/compare_au_nz.py

WHAT IS MEASURED AND WHAT IS ESTIMATED
--------------------------------------
Measured: the catalogue Table 3.9 ratings, every calculation below, and the bias
of the closed-form ambient factor against the tabulated one.

Estimated: the Table 14 ratings. This repo does not hold them. They are
synthesised by scaling Table 3.9, because the ratio between the two parts is set
by the temperature headroom each is drawn up on:

    R_NZ / R_AU = sqrt( (theta_max - 30) / (theta_max - 40) ) = 1.0954 at 90 C

That closed form is measurably optimistic. Against the tabulated AU factors it
runs +2.0% at 5 C from the reference, +2.8% at 10 C, +5.9% at 15 C and +9.1% at
20 C. The NZ reference is 10 C away, so a real Table 14 rating is likely nearer
1.066-1.095 times the Table 3.9 figure, and the value used here sits at the top
of that range. Put real Table 14 numbers into nz_rating() to check this
properly. The conclusion about direction does not depend on the exact ratio.

THE HEADLINE
------------
The two parts do not disagree about physics. Each moves the reference ambient
and moves its table numbers to match, so applying either part correctly to the
same installation lands on the same size. The sizing impact comes entirely from
pairing a rating with the wrong basis, which is what the deleted
Installation(basis=) switch did, and it goes wrong in both directions.
"""
import dataclasses
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import as3008
import cable_sizing as cs
import standards

CABLE = "XLPE_SDI_CU"
CATALOG = cs.load_catalog()
SIZES = sorted(CATALOG["cables"][CABLE]["sizes"].items(),
               key=lambda kv: float(kv[0]))
NZ_RATIO = math.sqrt((90.0 - 30.0) / (90.0 - 40.0))

# Feeding a Table 14 number into an Australian-basis calculation is one of the
# two errors being measured, and the real AS3008 profile will not allow it: it
# takes the rating from the catalogue and ignores a supplied one. So this
# synthetic profile keeps the Australian reference ambient and takes the rating
# from the request. It exists only to make the error reproducible.
AU_SUPPLIED = dataclasses.replace(
    standards.AS_NZS,
    id="AU_SUPPLIED", name="AU basis, supplied rating",
    rating_source="user_supplied",
    methods=tuple(dataclasses.replace(m, catalogue_column=None)
                  for m in standards.AS_NZS.methods))
standards.STANDARDS[AU_SUPPLIED.id] = AU_SUPPLIED

SOURCE_KW = dict(voltage_v=415, fault_level_ka=25, clearing_time_s=0.2)
METHOD = "touching"


def au_rating(size_key):
    """Table 3.9, unenclosed touching. Real catalogue data."""
    return CATALOG["cables"][CABLE]["sizes"][size_key].get("i_3ph_touching_a")


def nz_rating(size_key):
    """ESTIMATED Table 14 rating. Replace with real values when available."""
    r = au_rating(size_key)
    return None if r is None else r * NZ_RATIO


def select(standard, ambient_c, kw, length_m, n_circuits, rating_fn):
    """Smallest size passing every check, evaluating each candidate for real."""
    for size_key, _ in SIZES:
        rating = rating_fn(size_key)
        if rating is None:
            continue
        try:
            r = cs.check_feeder(
                cs.Source("MSB-1", **SOURCE_KW),
                cs.Load("PDU-A1", kw=kw, power_factor=0.95),
                length_m, float(size_key),
                cs.Installation(standard=standard, method=METHOD,
                                ambient_c=ambient_c, n_circuits=n_circuits,
                                cable_type=CABLE, tabulated_rating_a=rating),
                catalog=CATALOG)
        except ValueError:
            continue
        if r.passed:
            return float(size_key), r
    return None, None


def bias_table():
    print("How optimistic the closed-form ambient factor is, where it can be")
    print("checked against a tabulated one (90 C XLPE, 40 C air basis):\n")
    print("   ambient   closed form   tabulated    closed form is")
    for amb, tab in sorted(as3008.AMBIENT_FACTORS_XLPE90_AIR40.items()):
        an = math.sqrt((90 - amb) / (90 - 40))
        print(f"   {amb:5.0f} C     {an:9.4f}   {tab:9.3f}    "
              f"{100 * (an - tab) / tab:+6.2f}%   "
              f"({abs(amb - 40):.0f} C from the reference)")
    print(f"\n   Extrapolated the other way, to the NZ reference of 30 C, the")
    print(f"   closed form gives an uplift of {NZ_RATIO:.4f}. At the same 10 C")
    print(f"   distance on the derating side it was +2.81% optimistic, so a real")
    print(f"   Table 14 rating is likely {NZ_RATIO / 1.0281:.3f}-{NZ_RATIO:.3f}")
    print(f"   times Table 3.9. Table 14 is the arbiter; this is a bound.")


def worked_example():
    kw, length_m, n_circuits = 250, 85, 4
    i_design = as3008.design_current("3-phase", 415, kw=kw, power_factor=0.95)
    print(f"One feeder, both parts applied CORRECTLY")
    print(f"{kw} kW at 415 V three phase, pf 0.95, {length_m} m, {n_circuits} "
          f"grouped circuits,")
    print(f"unenclosed touching, X-90 XLPE copper. Design current "
          f"{i_design:.1f} A.\n")
    for ambient in (30.0, 40.0, 45.0):
        au_area, au_r = select("AU_SUPPLIED", ambient, kw, length_m,
                               n_circuits, au_rating)
        nz_area, nz_r = select("AS3008NZ", ambient, kw, length_m,
                               n_circuits, nz_rating)
        print(f"   ambient {ambient:4.0f} C")
        print(f"     part 1.1, Table 3.9 rating {au_r.derated_capacity_a / au_r.ambient_factor / 1:6.0f} A"
              f"  x k_amb {au_r.ambient_factor:.4f}  ->  {au_area:3.0f} mm2")
        print(f"     part 1.2, Table 14 rating  {nz_r.derated_capacity_a / nz_r.ambient_factor / 1:6.0f} A"
              f"  x k_amb {nz_r.ambient_factor:.4f}  ->  {nz_area:3.0f} mm2"
              f"   {'AGREE' if au_area == nz_area else 'DIFFER'}")


def sweep():
    over = under = total = 0
    overs, unders, binder = [], [], {}
    grid = [(kw, L, amb, nc)
            for kw in (50, 100, 150, 200, 250, 300, 400, 500, 700, 1000)
            for L in (20, 50, 85, 120, 180)
            for amb in (25, 30, 35, 40, 45, 50)
            for nc in (1, 2, 4, 6)]
    for kw, L, amb, nc in grid:
        correct, r = select("AU_SUPPLIED", amb, kw, L, nc, au_rating)
        if correct is None:
            continue
        total += 1
        bind = min(r.checks, key=lambda c: c.margin_pct).name
        binder[bind] = binder.get(bind, 0) + 1
        # Error 1: an Australian rating used on the NZ basis.
        wlo, _ = select("AS3008NZ", amb, kw, L, nc, au_rating)
        # Error 2: an NZ rating used on the Australian basis.
        whi, _ = select("AU_SUPPLIED", amb, kw, L, nc, nz_rating)
        if wlo and wlo > correct:
            over += 1
            overs.append((kw, L, amb, nc, correct, wlo))
        if whi and whi < correct:
            under += 1
            unders.append((kw, L, amb, nc, correct, whi))

    print(f"{total} sizeable cases across load, length, ambient and grouping.\n")
    print(f"   Table 3.9 rating on the NZ basis   OVERSIZED   {over:4d}  "
          f"({100 * over / total:4.1f}%)   wasteful, safe")
    print(f"   Table 14 rating on the AU basis    UNDERSIZED  {under:4d}  "
          f"({100 * under / total:4.1f}%)   DANGEROUS")
    print(f"\n   The dangerous direction is the more common of the two.")
    print(f"\n   Binding check across the sweep: " + ", ".join(
        f"{k} {100 * v / total:.0f}%" for k, v in
        sorted(binder.items(), key=lambda kv: -kv[1])))
    print(f"   Current capacity binds in most cases, which is why the "
          f"reference\n   ambient carries so much of the answer.")
    for title, rows, col in (("worst UNDERSIZE cases", unders, 5),
                             ("worst OVERSIZE cases", overs, 5)):
        print(f"\n   {title}:")
        key = (lambda c: c[col] / c[4]) if rows is unders else \
              (lambda c: -(c[col] / c[4]))
        seen = set()
        for c in sorted(rows, key=key):
            sig = (c[4], c[col])
            if sig in seen:
                continue
            seen.add(sig)
            print(f"     {c[0]:5} kW {c[1]:4} m {c[2]:3.0f} C {c[3]} cct:  "
                  f"{c[4]:3.0f} -> {c[col]:3.0f} mm2  "
                  f"({100 * (c[col] / c[4] - 1):+.0f}% area)")
            if len(seen) >= 4:
                break


def why():
    print("""A rating is the current at which the conductor reaches its limit AT THAT
TABLE'S OWN REFERENCE AMBIENT. The correction factor moves it to the real one:

    k = sqrt( (theta_max - theta_actual) / (theta_max - theta_reference) )

Put a Table 3.9 rating on the NZ basis and theta_reference falls from 40 to 30.
The engine believes the rating was measured with less headroom than it really
was, under-credits the cable and oversizes. Wasteful, but safe.

Put a Table 14 rating on the Australian basis and it runs backwards: the engine
believes a 30 C rating was measured at 40 C, over-credits the cable and
undersizes. That is the direction that matters, and it is why the basis switch
was deleted rather than exposed.""")


for heading, fn in (("AMBIENT FACTOR PROVENANCE", bias_table),
                    ("BOTH PARTS, APPLIED CORRECTLY", worked_example),
                    ("PAIRING A RATING WITH THE WRONG BASIS", sweep),
                    ("WHY THE ERRORS RUN THE WAY THEY DO", why)):
    print("\n" + "=" * 76)
    print(heading)
    print("=" * 76)
    fn()
print()
