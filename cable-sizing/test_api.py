

#!/usr/bin/env python3
"""Checks for the multi-standard layer, the diagrams, the REST API and MCP.

`test_cable_sizing.py` covers the engine. This covers what was added around it,
and in particular the two properties that matter most:

  1. Adding the standards layer did not move an AS/NZS answer.
  2. No standard whose rating table is absent can produce a size.

Run: python3 test_api.py
"""
from __future__ import annotations

import json
import subprocess
import sys
import xml.dom.minidom

import as3008
import cable_sizing as cs
import install_diagrams
import mcp_server
import openapi
import service
import standards

# ---------------------------------------------------------------------------
# These assertions check real AS/NZS 3008.1.1 and AS/NZS 3000 values, so they
# need the licensed data. On a checkout without it -- a contributor with no
# licence, or CI with no credentials -- skip rather than fail. test_synthetic.py
# is the suite that runs everywhere and proves the package still assembles.
# ---------------------------------------------------------------------------
import tables as _tables

_missing = [c["file_id"] for c in _tables.coverage()
            if c["licensed"] and not c["present"]]
if _missing or _tables.is_synthetic():
    _why = ("the data directory holds synthetic fixtures"
            if _tables.is_synthetic() else f"licensed data absent: {_missing}")
    print(f"SKIP {__file__.split('/')[-1]}: {_why}.")
    print("     Run test_synthetic.py for the credential-free suite.")
    raise SystemExit(0)

CATALOG = service.CATALOG

PASS = FAIL = 0


def ck(label, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [PASS] {label}")
    else:
        FAIL += 1
        print(f"  [FAIL] {label}{'  ' + detail if detail else ''}")


def near(label, got, want, tol_pct=0.05):
    d = abs(got - want) / want * 100 if want else abs(got - want)
    ck(f"{label}: {got:.4g} vs {want:.4g}", d <= tol_pct, f"off by {d:.3f}%")


print("standard profiles")
ck("five standards are defined", len(standards.STANDARDS) == 5)
ck("AS/NZS is the default", standards.DEFAULT == standards.AS_NZS.id)
ck("only AS/NZS selects a size",
   [s.id for s in standards.STANDARDS.values() if s.selects_size]
   == [standards.AS_NZS.id])
for s in standards.STANDARDS.values():
    ck(f"{s.name}: every method resolves to a real diagram",
       all(m.diagram in install_diagrams.DIAGRAMS for m in s.methods))
    ck(f"{s.name}: every method has a distinct id",
       len({m.id for m in s.methods}) == len(s.methods))
    ck(f"{s.name}: carries a rating table reference", bool(s.rating_table_ref))
    ck(f"{s.name}: names its source", bool(s.source))
    ck(f"{s.name}: is not claimed as verified", s.verified is False)
    ck(f"{s.name}: only AS/NZS methods map to catalogue columns",
       all((m.catalogue_column is not None) == (s.id == standards.AS_NZS.id)
           for m in s.methods))
ck("the NZ part is a separate profile, not a basis switch",
   standards.AS_NZS_NZ.id in standards.STANDARDS
   and standards.AS_NZS_NZ.id != standards.AS_NZS.id)
ck("the NZ part is cooler than the Australian part on air, soil and rho",
   standards.AS_NZS_NZ.air_c < standards.AS_NZS.air_c
   and standards.AS_NZS_NZ.soil_c < standards.AS_NZS.soil_c
   and standards.AS_NZS_NZ.soil_resistivity != standards.AS_NZS.soil_resistivity)
ck("the NZ part is 30 C air / 15 C soil",
   (standards.AS_NZS_NZ.air_c, standards.AS_NZS_NZ.soil_c) == (30.0, 15.0))
ck("the NZ part cites its own rating table, not Table 3.9",
   "Table 14" in standards.AS_NZS_NZ.rating_table_ref
   and "3.9" not in standards.AS_NZS_NZ.rating_table_ref)
ck("the NZ part cannot select, having no rating table here",
   standards.AS_NZS_NZ.selects_size is False)
ck("the NZ part warns that an Australian rating is not valid for it",
   any("NOT valid" in r for r in standards.AS_NZS_NZ.extra_rules))
ck("Installation no longer accepts a basis switch",
   "basis" not in cs.Installation.__dataclass_fields__)
# The optimistic closed form must announce itself off the Australian basis.
_nzw = cs.check_feeder(
    cs.Source("S"), cs.Load("L", kw=90), 60, 95,
    cs.Installation(standard="AS3008NZ", method="touching", ambient_c=40,
                    tabulated_rating_a=250)).warnings
ck("an untabulated ambient factor is flagged as optimistic",
   any("optimistic" in w for w in _nzw))
ck("the tabulated Australian basis is not flagged",
   not any("optimistic" in w for w in cs.size_feeder(
       cs.Source("S"), cs.Load("L", kw=90), 60,
       cs.Installation(method="touching", ambient_c=45)).warnings))
ck("IEC and BS share the 30 C / 20 C reference basis",
   (standards.IEC.air_c, standards.IEC.soil_c)
   == (standards.BS.air_c, standards.BS.soil_c) == (30.0, 20.0))
ck("AS/NZS reference basis is 40 C air, 25 C soil",
   (standards.AS_NZS.air_c, standards.AS_NZS.soil_c) == (40.0, 25.0))
ck("IEC lighting limit is 3% and other is 5%",
   (standards.IEC.vd_limit_pct("public", "lighting"),
    standards.IEC.vd_limit_pct("public", "other")) == (3.0, 5.0))
ck("IEC private supply relaxes to 6% and 8%",
   (standards.IEC.vd_limit_pct("private", "lighting"),
    standards.IEC.vd_limit_pct("private", "other")) == (6.0, 8.0))
ck("AS/NZS substation exception is 7%",
   standards.AS_NZS.vd_limit_pct("substation") == 7.0)
ck("c = 1.1 for the IEC-harmonised standards, 1.0 otherwise",
   [s.voltage_factor_c for s in (standards.AS_NZS, standards.IEC,
                                 standards.BS, standards.NEC)]
   == [1.0, 1.1, 1.1, 1.0])
ck("the NEC profile warns that terminal temperature is not applied",
   any("TERMINAL" in r or "terminal" in r for r in standards.NEC.extra_rules))
try:
    standards.get("NOPE")
    ck("an unknown standard is rejected", False)
except ValueError:
    ck("an unknown standard is rejected", True)
try:
    standards.method(standards.IEC.id, "touching")
    ck("a method from the wrong standard is rejected", False)
except ValueError:
    ck("a method from the wrong standard is rejected", True)

print("\ninstallation diagrams")
ck("twelve diagrams", len(install_diagrams.DIAGRAMS) == 12)
for key, svg in install_diagrams.all_svg().items():
    try:
        xml.dom.minidom.parseString(svg)
        wellformed = True
    except Exception:
        wellformed = False
    ck(f"{key}: well-formed SVG", wellformed)
ck("every diagram declares the shared viewBox",
   all(f'viewBox="0 0 {install_diagrams.W} {install_diagrams.H}"' in v
       for v in install_diagrams.all_svg().values()))
ck("every diagram carries an aria-label",
   all('aria-label="' in v for v in install_diagrams.all_svg().values()))
ck("no diagram hard-codes a hex colour outside the CSS block",
   all("#" not in v.split("<defs>")[0] for v in install_diagrams.all_svg().values()))
# The caption band exists so text is never drawn over a hatch or stipple fill.
import re
intrusions = []
for key, svg in install_diagrams.all_svg().items():
    for tag in re.findall(r"<(?:rect|circle|line|path)[^>]*>", svg):
        for yv in re.findall(r'(?:y|cy|y1|y2)="([\d.]+)"', tag):
            if float(yv) > install_diagrams.DRAW_BOTTOM:
                intrusions.append((key, tag[:40]))
ck("nothing is drawn inside the caption band", not intrusions, str(intrusions[:2]))

# These moved twice, both times for a real reason, and the selected size never
# changed.
#
# First, when reactance stopped being a 0.08 ohm/km nominal and came from
# AS/NZS 3008.1.1:2025 Table 4.1(A): 0.0961 ohm/km at 300 mm2 single-core XLPE
# flat touching, 20 % above the old nominal, so drop rose and fault current
# fell. 5.3594 -> 5.7290 V, 12747.5 -> 11844.0 A.
#
# Then again on ANS-001 R-VD-8. Clause 4.4 bands the operating temperature to
# the nearest of 45, 60, 75, 80, 90 or 110 C before any resistance lookup. Two
# defects were fixed together: 80 C was missing from TEMP_COLUMNS, and the
# rounding was UP rather than to nearest. This circuit runs at 84.6 C, which
# previously rounded up to 90 C and now bands to 80 C -- a cooler conductor, so
# lower resistance, lower drop, higher fault current, and a higher K because k
# is computed from the initial temperature. 5.7290 -> 5.6160 V,
# 11844.0 -> 11910.0 A, K 142.874 -> 148.3.
print("\nthe AS/NZS answer did not move")
r = cs.size_feeder(
    cs.Source("MSB-1", voltage_v=415, fault_level_ka=25, clearing_time_s=0.2),
    cs.Load("PDU-A1", kw=250, power_factor=0.95), 85,
    cs.Installation(method="touching", ambient_c=45, n_circuits=4))
ck("documented example still selects 300 mm2 active", r.active_area_mm2 == 300.0)
ck("documented example still selects 120 mm2 earth", r.earth_area_mm2 == 120.0)
near("design current", r.design_current_a, 366.1, 0.05)
near("derating factor", r.derating_factor, 0.7161, 0.05)
near("voltage drop", r.voltage_drop_v, 5.6160, 0.05)
near("fault current", r.fault_current_a, 11910.0, 0.05)
near("K constant", r.k_constant, 148.3, 0.05)

print("\nno standard without a rating table can select a size")
for sid in ("IEC60364", "BS7671", "NEC"):
    std = standards.get(sid)
    try:
        cs.size_feeder(cs.Source("S"), cs.Load("L", kw=100), 50,
                       cs.Installation(standard=sid, method=std.methods[0].id))
        ck(f"{std.name}: select mode refused", False)
    except ValueError as exc:
        ck(f"{std.name}: select mode refused, naming the table",
           std.rating_table_ref[:12] in str(exc))

print("\ncheck mode")
src = cs.Source("S", voltage_v=400, fault_level_ka=10, clearing_time_s=0.1)
ld = cs.Load("L", kw=90, power_factor=0.87)
chk = cs.check_feeder(src, ld, 60, 95, cs.Installation(
    standard="BS7671", method="C", ambient_c=30, n_circuits=1,
    tabulated_rating_a=270))
ck("checks the size it was given, not another", chk.active_area_mm2 == 95.0)
ck("uses the supplied rating", abs(chk.derated_capacity_a - 270.0) < 1e-9)
ck("applies the BS private-supply limit when asked",
   cs.check_feeder(src, ld, 60, 95, cs.Installation(
       standard="BS7671", method="C", tabulated_rating_a=270,
       vd_supply="private")).voltage_drop_limit_pct == 8.0)
# A failing candidate must still report every check, which is the whole point
# of checking a size rather than selecting one.
bad = cs.check_feeder(src, cs.Load("Big", kw=400, power_factor=0.9), 60, 95,
                      cs.Installation(standard="BS7671", method="C",
                                      tabulated_rating_a=270))
ck("a failing check still returns every check", len(bad.checks) >= 3)
ck("a failing check reports which check failed",
   bad.passed is False and "current capacity" in (bad.failure_reason or ""))
ck("a failing check reports a negative margin",
   any(c.margin_pct < 0 for c in bad.checks))
try:
    cs.check_feeder(src, ld, 60, 95,
                    cs.Installation(standard="BS7671", method="C"))
    ck("check mode without a rating is refused", False)
except ValueError:
    ck("check mode without a rating is refused", True)

print("\nthe IEC voltage factor is applied, and only where it belongs")
faults = {}
for sid, meth in (("AS3008", "touching"), ("IEC60364", "F_flat"),
                  ("BS7671", "C"), ("NEC", "tray")):
    faults[sid] = cs.check_feeder(
        cs.Source("S", voltage_v=415, fault_level_ka=50, clearing_time_s=0.2),
        cs.Load("L", kw=100, power_factor=0.9), 10, 95,
        cs.Installation(standard=sid, method=meth, ambient_c=40,
                        n_circuits=1, tabulated_rating_a=300)).fault_current_a
ck("NEC and AS/NZS agree, both having c = 1.0",
   abs(faults["NEC"] - faults["AS3008"]) < 1e-9)
ck("IEC and BS agree, both having c = 1.1",
   abs(faults["IEC60364"] - faults["BS7671"]) < 1e-9)
# c scales the driving voltage and the network impedance, so the two only fail
# to cancel once cable impedance is in the denominator. REVIEW-ELEK.md measures
# the same effect at -3.19% against ELEK's three-phase case.
lift = 100 * (faults["IEC60364"] - faults["AS3008"]) / faults["AS3008"]
ck(f"c = 1.1 lifts the three-phase fault current by {lift:.2f}%, near the "
   f"3.19% measured against ELEK", 2.5 < lift < 3.5)

print("\nservice layer")
ck("health reports the loaded data", service.health()["status"] == "ok")
sel = service.size({"rating_value": 250, "power_factor": 0.95,
                    "voltage_v": 415, "route_length_m": 85, "ambient_c": 45,
                    "n_circuits": 4, "method": "touching"})
ck("service.size selects through the same engine",
   sel["sizes"]["active_mm2"] == 300.0 and sel["mode"] == "select")
ck("the result names the diagram for its method",
   sel["installation"]["diagram"] in install_diagrams.DIAGRAMS)
ck("Nexans is marked as driving the sizing",
   sel["manufacturers"]["nexans"]["drives_sizing"] is True)
ck("Tricab is marked as not driving the sizing",
   sel["manufacturers"]["tricab"]["drives_sizing"] is False)
ck("Tricab per-size data is declared absent",
   sel["manufacturers"]["tricab"]["per_size_data_public"] is False)
ck("no Tricab match is offered above the voltage ceiling",
   all(("kV" not in (m["voltage"] or "")) or
       float(m["voltage"].replace("kV", "").strip().split("/")[-1])
       <= sel["manufacturers"]["tricab"]["voltage_ceiling_kv"] + 1e-9
       for m in sel["manufacturers"]["tricab"]["matches"]))
chk2 = service.check({"standard": "IEC60364", "method": "F_flat",
                      "area_mm2": 185, "tabulated_rating_a": 456,
                      "rating_value": 90, "voltage_v": 400,
                      "route_length_m": 60, "ambient_c": 35, "n_circuits": 2,
                      "power_factor": 0.87})
ck("service.check runs in check mode", chk2["mode"] == "check")
ck("service.check reports the standard it used",
   chk2["standard"]["id"] == "IEC60364")
ck("every service payload is JSON-serialisable with no NaN",
   bool(json.dumps(sel, allow_nan=False) and json.dumps(chk2, allow_nan=False)))
ck("meta is JSON-serialisable", bool(json.dumps(service.meta(),
                                                allow_nan=False)))

print("\nharmonics")
h = service.size({"rating_value": 250, "power_factor": 0.95, "voltage_v": 415,
                  "route_length_m": 85, "ambient_c": 45, "n_circuits": 4,
                  "method": "touching", "harmonic_content_pct": 45})
ck("substantial harmonics are flagged",
   h["currents"]["substantial_harmonics"] is True)
ck("the neutral is upsized above the active for 45% harmonics",
   h["sizes"]["neutral_mm2"] > h["sizes"]["active_mm2"])
ck("the upsizing is explained in a warning",
   any("neutral upsized" in w for w in h["warnings"]))
# Without a per-size rating table the neutral cannot be upsized, so it must come
# back null with a warning rather than silently equal to the active.
hn = service.check({"standard": "BS7671", "method": "C", "area_mm2": 185,
                    "tabulated_rating_a": 456, "rating_value": 90,
                    "voltage_v": 400, "route_length_m": 60,
                    "harmonic_content_pct": 45})
ck("an unsizeable neutral is null, not silently equal to the active",
   hn["sizes"]["neutral_mm2"] is None)
ck("and it says why", any("not been checked" in w for w in hn["warnings"]))

print("\nagainst two independent AS/NZS 3008 calculators")
# jCalc (Single-cores 4x1C+E, flexible Cu, X-110, touching, 2025 AU) and ELEK
# both report 839 A at 400 mm2 from Table 3.14 col 5, and both select 400 mm2
# for this feeder. Screenshots supplied 2026-09-03; table in as3008_ratings.json.
_src = cs.Source("S", voltage_v=415, fault_level_ka=3.0, clearing_time_s=0.1)
_std = cs.size_feeder(
    _src, cs.Load("L", amps=800, power_factor=0.9, max_voltage_drop_pct=3.0), 40,
    cs.Installation(method="touching", ambient_c=40, n_circuits=1,
                    cable_type="XHF110_4C1CE_CU"))
ck("reproduces the 400 mm2 both calculators select",
   _std.active_area_mm2 == 400.0, f"{_std.active_area_mm2:g}")
ck("reproduces their 120 mm2 earth", _std.earth_area_mm2 == 120.0)
near("rated current at 400 mm2", _std.derated_capacity_a, 839.0, 0.2)
near("operating temperature", _std.operating_temp_c, 104.0, 1.0)
# The same feeder on the manufacturer-rated family comes out one size small,
# which is the defect that comparison exposed.
_mfr = cs.size_feeder(
    _src, cs.Load("L", amps=800, power_factor=0.9, max_voltage_drop_pct=3.0), 40,
    cs.Installation(method="touching", ambient_c=40, n_circuits=1,
                    cable_type="LFH_SINGLE"))
ck("the manufacturer-rated family still selects one size smaller",
   _mfr.active_area_mm2 == 300.0, f"{_mfr.active_area_mm2:g}")
ck("and its catalogue rating exceeds the standard's table by over 10%",
   (CATALOG["cables"]["LFH_SINGLE"]["sizes"]["400"]["i_3ph_touching_a"]
    / 839.0 - 1) > 0.10)
# Formula-level agreement, using jCalc's own R and X so only the maths is tested.
_z = as3008.cable_impedance(0.0583, 0.0714, power_factor=None)
near("voltage drop matches jCalc given its own impedances",
     as3008.voltage_drop("3-phase", 800, 40, _z), 5.1, 2.0)
near("operating temperature matches jCalc's worked figure",
     as3008.operating_temperature(40, 110, 800, 853), 102.0, 1.0)
ck("the standards family declares its rating source",
   "Table 3.14" in CATALOG["cables"]["XHF110_4C1CE_CU"]["rating_source"])
ck("and that it is a four-loaded-core column",
   CATALOG["cables"]["XHF110_4C1CE_CU"]["loaded_cores"] == 4)

print("\nezystrut tray selection")
import ezystrut

_tc = ezystrut.load()
ck("the tray catalogue is read from the sibling component",
   "cable-tray-ezystrut" in ezystrut.CATALOGUE_PATH)
ck("it is not claimed as verified", _tc["verified"] is False)
ck("ET5 is the heavy-duty family recommended for power",
   _tc["families"]["ET5"]["duty"] == "heavy")
_sel = ezystrut.select(162.0, 16.2)
ck("162 mm of cable selects the 300 mm ET5",
   _sel["fits"] and _sel["part"] == "ET5300G", str(_sel.get("part")))
ck("the load check includes the tray's own weight",
   _sel["total_load_kg_per_m"] > _sel["cable_mass_kg_per_m"])
ck("and passes at a 3 m span", _sel["load_ok"] is True)
# Width, not fill depth, is the binding dimension for a single layer.
ck("clearance is added each side, not a fill ratio",
   abs(_sel["required_width_mm"] - (162.0 + 2 * ezystrut.SIDE_CLEARANCE_MM)) < 1e-9)
_wide = ezystrut.select(700.0, 20.0)
ck("a bundle wider than the range is refused with a reason",
   _wide["fits"] is False and "split the run" in _wide["reason"])
ck("a span longer than the published points returns no rating, not a guess",
   ezystrut.rating_at_span(_tc["families"]["ET5"], 6000)[0] is None)
ck("a span between published points takes the conservative shorter one",
   ezystrut.rating_at_span(_tc["families"]["ET5"], 2750)[0] == 82)
_heavy = ezystrut.select(446.0, 46.2)
ck("the three-run bundle is flagged as heavily loaded",
   _heavy["load_utilisation_pct"] > 80, f"{_heavy['load_utilisation_pct']:.0f}%")

print("\nopenapi")
spec = openapi.spec()
ck("declares OpenAPI 3.1", spec["openapi"].startswith("3.1"))
ck("version matches the service", spec["info"]["version"] == service.VERSION)
ck("nine operations", sum(len(v) for v in spec["paths"].values()) == 9)
ck("every operation has an operationId",
   all("operationId" in op for ops in spec["paths"].values()
       for op in ops.values()))
ck("every operation has a summary",
   all("summary" in op for ops in spec["paths"].values()
       for op in ops.values()))
ck("every $ref resolves",
   all(r.split("/")[-1] in spec["components"]["schemas"]
       for r in re.findall(r'"\$ref": "([^"]+)"', json.dumps(spec))))
ck("the spec says /api/size is restricted to AS/NZS",
   "AS/NZS 3008.1.1 only"
   in spec["paths"]["/api/size"]["post"]["description"])
ck("the spec warns that no ampacity is derived",
   "No ampacity is ever derived" in spec["info"]["description"])
ck("spec is JSON-serialisable", bool(json.dumps(spec, allow_nan=False)))

print("\nmcp server")
ck("five tools", len(mcp_server.TOOLS) == 5)
ck("every tool has a schema and a description",
   all(t.get("inputSchema") and t.get("description")
       for t in mcp_server.TOOLS))
init = mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                          "params": {"protocolVersion": "2024-11-05"}})
ck("initialize echoes a protocol version the client asked for",
   init["result"]["protocolVersion"] == "2024-11-05")
ck("initialize falls back for an unknown protocol version",
   mcp_server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                      "params": {"protocolVersion": "1999-01-01"}}
                     )["result"]["protocolVersion"]
   in mcp_server.PROTOCOL_VERSIONS)
ck("initialize carries usage instructions",
   "check_cable_size" in init["result"]["instructions"])
ck("a notification is not answered",
   mcp_server.handle({"jsonrpc": "2.0",
                      "method": "notifications/initialized"}) is None)
ck("an unknown method is a JSON-RPC error",
   "error" in mcp_server.handle({"jsonrpc": "2.0", "id": 2,
                                 "method": "nope"}))
call = mcp_server.handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
                          "params": {"name": "size_cable",
                                     "arguments": {"rating_value": 250,
                                                   "method": "touching"}}})
ck("size_cable returns content", bool(call["result"]["content"]))
refused = mcp_server.handle({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
                             "params": {"name": "size_cable",
                                        "arguments": {"standard": "NEC",
                                                      "rating_value": 250}}})
ck("a refusal is a tool error the model can read, not a protocol error",
   refused["result"].get("isError") is True
   and "Table 310.16" in refused["result"]["content"][0]["text"])
ck("an unknown tool is reported as a tool error",
   mcp_server.handle({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
                      "params": {"name": "bogus"}})["result"]["isError"])
ck("resources are listed", len(mcp_server.handle(
    {"jsonrpc": "2.0", "id": 6, "method": "resources/list"}
)["result"]["resources"]) == 3)
ck("a resource reads back as JSON", bool(json.loads(mcp_server.handle(
    {"jsonrpc": "2.0", "id": 7, "method": "resources/read",
     "params": {"uri": "cable-sizing://standards"}}
)["result"]["contents"][0]["text"])))

print("\nmcp over a real subprocess")
msgs = "\n".join(json.dumps(m) for m in (
    {"jsonrpc": "2.0", "id": 1, "method": "initialize",
     "params": {"protocolVersion": "2025-06-18"}},
    {"jsonrpc": "2.0", "method": "notifications/initialized"},
    {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
    {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
     "params": {"name": "check_cable_size",
                "arguments": {"standard": "IEC60364", "method": "C",
                              "area_mm2": 95, "tabulated_rating_a": 240,
                              "rating_value": 60}}},
))
proc = subprocess.run([sys.executable, "mcp_server.py"], input=msgs,
                      capture_output=True, text=True, timeout=60)
lines = [json.loads(x) for x in proc.stdout.splitlines() if x.strip()]
ck("three responses for three requests and one notification", len(lines) == 3)
ck("stderr is quiet", proc.stderr.strip() == "", proc.stderr[:200])
ck("the subprocess sized under IEC",
   json.loads(lines[2]["result"]["content"][0]["text"])["standard"]["id"]
   == "IEC60364")
bad_json = subprocess.run([sys.executable, "mcp_server.py"], input="{oh no\n",
                          capture_output=True, text=True, timeout=60)
ck("malformed input gets a JSON-RPC parse error, not a crash",
   json.loads(bad_json.stdout)["error"]["code"] == -32700)

print("\n" + "=" * 60)
print(f"{PASS} passed, {FAIL} failed.")
sys.exit(1 if FAIL else 0)
