"""CI smoke suite: the package must work with no licensed data at all.

Runs against fixtures/, which holds invented numbers. It proves the code
assembles, imports and computes end to end; it proves nothing about agreement
with AS/NZS 3008.1.1, and the value suites skip themselves here for exactly
that reason.
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
os.environ["CABLE_SIZING_DATA_DIR"] = os.path.join(HERE, "fixtures")

import tables                                        # noqa: E402
import as3008                                        # noqa: E402
import as3008_2025                                   # noqa: E402
import cable_sizing as cs                            # noqa: E402

fails = []


def check(name, ok, detail=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f": {detail}" if detail else ""))
    if not ok:
        fails.append(name)


def raises(fn):
    try:
        fn()
        return False
    except tables.MissingTableData:
        return True


print("\n1. A checkout with no licensed data still works")
check("the active data is flagged synthetic", tables.is_synthetic())
missing = [c["file_id"] for c in tables.coverage()
           if c["licensed"] and not c["present"]]
check("every licensed file resolves to a fixture", not missing,
      f"missing: {missing}" if missing else "all five")
check("anything issuable is refused on synthetic data",
      raises(lambda: tables.require_real_data("a cable schedule")))


print("\n2. The engine runs end to end on invented numbers")
r = cs.size_feeder(
    cs.Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2),
    cs.Load("PDU-A1", kw=250, power_factor=0.95), 85,
    cs.Installation(method="touching", ambient_c=45, n_circuits=4))
check("size_feeder returns a result", r is not None)
check("it selected a size", r.active_area_mm2 > 0, f"{r.active_area_mm2:g} mm2")
names = [c.name for c in r.checks]
check("the three core checks ran",
      names == ["current capacity", "voltage drop", "short circuit"],
      ", ".join(names))
check("voltage drop was computed", r.voltage_drop_v > 0, f"{r.voltage_drop_v:.2f} V")
check("a K constant was derived", r.k_constant > 0, f"K={r.k_constant:.1f}")

print("\n3. Provenance is honest about what it is standing on")
rep = as3008.verification_report()
check("the report runs", len(rep) > 0, f"{len(rep)} entries")
check("nothing claims to be verified against a real standard",
      not any(e["verified"] and "printed standard" in str(e["source"])
              for e in rep) or tables.is_synthetic())

print("\n4. Section 4 lookups resolve")
check("reactance resolves", as3008_2025.reactance_ohm_km(240)[0] > 0)
check("a.c. resistance resolves", as3008_2025.resistance_ohm_km(240, 90)[0] > 0)
check("short-circuit limit resolves", as3008_2025.sc_limit_temp_c("V-90", 400) == 140.0)

print("\n" + "=" * 60)
if fails:
    print(f"{len(fails)} of the synthetic smoke checks FAILED:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print("All synthetic smoke checks passed "
      "(invented numbers -- proves assembly, not correctness).")
