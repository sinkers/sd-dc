"""Service layer: one implementation of every operation, three front ends.

`server.py` (HTML + REST), `mcp_server.py` (MCP over stdio) and any direct
caller all go through here, so a calculation cannot drift between the browser
and an agent. Everything in this module is plain dicts in and plain dicts out:
no HTTP, no JSON-RPC, no framework.
"""
from __future__ import annotations

import json
import os

import as3008
import cable_sizing as cs
import tables
import install_diagrams
import standards

HERE = os.path.dirname(os.path.abspath(__file__))
TRICAB_PATH = tables.path_for("tricab")
VERSION = "0.2.0"

# Loaded on first use, not at import: the vendor catalogues live outside the
# repository now, so importing this module must not require them. See tables.py.
_CATALOG = None


def CATALOG_():
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = cs.load_catalog()
    return _CATALOG


CATALOG = tables.LazyMapping(CATALOG_)
try:
    with open(TRICAB_PATH) as fh:
        TRICAB = json.load(fh)
except FileNotFoundError:
    TRICAB = {"families": [], "scope": "tricab_families.json not present"}


# --------------------------------------------------------- manufacturer match

def _family_kv(family):
    """Rated voltage of a family in kV, parsed from its label."""
    v = (family.get("voltage") or "").strip()
    try:
        if v.endswith("kV"):
            return float(v[:-2].strip().split("/")[-1])
        if v.endswith("V"):
            return float(v[:-1].strip().split("/")[-1]) / 1000.0
    except (ValueError, IndexError):
        pass
    return None


NOT_POWER = ("instrument", "control", "signal", "alarm", "telecom",
             "earthing & bonding", "welding")
TRICAB_CAP = 20


def match_manufacturers(result, install, source):
    """Match the chosen or checked size against both catalogues."""
    entry = CATALOG["cables"][install.cable_type]
    size_key = f"{result.active_area_mm2:g}"
    spec = entry["sizes"].get(size_key, {})
    insulation = as3008.resolve_insulation(entry["insulation"])
    column = install.method_spec().catalogue_column

    nexans = {
        "catalogue": CATALOG.get("source", "unknown"),
        "family": entry.get("name"),
        "type_code": install.cable_type,
        "conductor": entry.get("conductor"),
        "insulation": entry.get("insulation"),
        "voltage_kv": entry.get("voltage_kv"),
        "max_temp_c": entry.get("max_temp_c"),
        "size_mm2": result.active_area_mm2,
        "rated_data": {
            "tabulated_rating_a": spec.get(column) if column else None,
            "rating_is_user_supplied": column is None,
            "r_ac_ohm_km": spec.get("r_ac_ohm_km"),
            "r_dc_ohm_km": spec.get("r_dc_ohm_km"),
            "x_ohm_km": spec.get("x_ohm_km"),
            "od_mm": spec.get("od_mm"),
            "weight_kg_100m": spec.get("weight_kg_100m"),
            "bend_installed_mm": spec.get("bend_installed_mm"),
        },
        "drives_sizing": column is not None,
    }

    circuit_kv = source.voltage_v / 1000.0
    # A family has to be rated for the circuit, but one rated far above it is
    # the wrong product rather than a safe choice: without this ceiling a 415 V
    # feeder gets offered 6.6 kV and 11 kV mining trailing cables.
    kv_ceiling = max(circuit_kv * 3.0, circuit_kv + 0.6)
    want_cond = entry.get("conductor")
    cands = []
    for fam in TRICAB.get("families", []):
        if fam.get("conductor") != want_cond:
            continue
        kv = _family_kv(fam)
        if kv is None or kv < circuit_kv or kv > kv_ceiling:
            continue
        temp = fam.get("max_conductor_temp_c")
        if temp is None or temp < insulation.max_temp_c:
            continue
        blurb = f"{fam.get('construction') or ''} {fam.get('name') or ''}".lower()
        # "Power & Control" is a power cable, so an explicit "power" in the
        # description outranks the control/instrumentation words.
        is_power = "power" in blurb or not any(w in blurb for w in NOT_POWER)
        cands.append({
            "code": fam.get("code"),
            "name": fam.get("name"),
            "construction": fam.get("construction"),
            "voltage": fam.get("voltage"),
            "max_conductor_temp_c": temp,
            "conductor": fam.get("conductor"),
            "url": fam.get("url"),
            "temp_headroom_c": temp - insulation.max_temp_c,
            "power_family": is_power,
        })
    cands.sort(key=lambda c: (not c["power_family"], c["temp_headroom_c"],
                              c["code"] or "zz"))
    seen, uniq = set(), []
    for c in cands:
        key = (c["code"], c["construction"], c["voltage"],
               c["max_conductor_temp_c"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    return {
        "nexans": nexans,
        "tricab": {
            "catalogue": TRICAB.get("source", "Tricab"),
            "matches": uniq[:TRICAB_CAP],
            "match_count": len(uniq),
            "shown_count": len(uniq[:TRICAB_CAP]),
            "voltage_ceiling_kv": kv_ceiling,
            "per_size_data_public": False,
            "caveat": "Construction and rating match only. Tricab gates "
                      "per-size current ratings, resistance, reactance, "
                      "diameter and mass behind a trade login, so this tool "
                      "cannot size on Tricab data or confirm that a given "
                      "family is offered in this exact size.",
            "drives_sizing": False,
        },
    }


# ------------------------------------------------------------ request mapping

def _f(p, key, default=None):
    v = p.get(key, "")
    if v in ("", None):
        return default
    return float(v)


def _build(p):
    """Map a request payload onto the engine's dataclasses."""
    source = cs.Source(
        name=p.get("source_name") or "Source",
        voltage_v=_f(p, "voltage_v", 415.0),
        phase_mode=p.get("phase_mode") or "3-phase",
        fault_level_ka=_f(p, "fault_level_ka", 25.0),
        clearing_time_s=_f(p, "clearing_time_s", 0.2),
        protection_type=p.get("protection_type") or None,
        mcb_curve=p.get("mcb_curve") or "C",
        mcb_rating_a=_f(p, "mcb_rating_a"),
    )
    rating = p.get("rating_kind") or "kw"
    load = cs.Load(
        name=p.get("load_name") or "Load",
        kw=_f(p, "rating_value") if rating == "kw" else None,
        kva=_f(p, "rating_value") if rating == "kva" else None,
        amps=_f(p, "rating_value") if rating == "amps" else None,
        power_factor=_f(p, "power_factor", 0.9),
        max_voltage_drop_pct=_f(p, "max_voltage_drop_pct"),
        harmonic_content_pct=_f(p, "harmonic_content_pct", 0.0),
        out_of_balance_pct=_f(p, "out_of_balance_pct", 100.0),
    )
    std_id = p.get("standard") or standards.DEFAULT
    default_method = standards.get(std_id).methods[0].id
    install = cs.Installation(
        method=p.get("method") or default_method,
        # Formation is a second axis, not a consequence of the method: single
        # core in trefoil on an "unenclosed touching" tray is the normal case
        # here. Left unset the engine guesses and warns, and the guess is worth
        # about 19 % on reactance, so it is worth passing.
        formation=p.get("formation") or None,
        ambient_c=_f(p, "ambient_c"),
        n_circuits=int(_f(p, "n_circuits", 1)),
        max_parallel=int(_f(p, "max_parallel", 4)),
        cable_type=p.get("cable_type") or "XLPE_SDI_CU",
        circuit_use=p.get("circuit_use") or "other_circuits",
        dedicated_onsite_substation=bool(p.get("dedicated_onsite_substation")),
        standard=std_id,
        tabulated_rating_a=_f(p, "tabulated_rating_a"),
        vd_supply=p.get("vd_supply") or "public",
        vd_use=p.get("vd_use") or "other",
    )
    return source, load, install, _f(p, "route_length_m", 50.0)


def _serialise(r, source, install, route_length_m, mode):
    std = install.profile()
    m = install.method_spec()
    out = {
        "mode": mode,
        "passed": r.passed,
        "failure_reason": r.failure_reason,
        "standard": {"id": std.id, "name": std.name,
                     "rating_source": std.rating_source,
                     "rating_table_ref": std.rating_table_ref,
                     "selects_size": std.selects_size,
                     "voltage_factor_c": std.voltage_factor_c,
                     "area_unit": std.area_unit,
                     "extra_rules": list(std.extra_rules)},
        "installation": {"method": m.id, "label": m.label, "ref": m.ref,
                         "medium": m.medium, "diagram": m.diagram,
                         "note": m.note,
                         # Report what was actually used, guessed or not, so a
                         # reader never has to infer it from the warnings.
                         "formation": install.formation,
                         "formation_stated": install.formation is not None},
        "inputs": {"route_length_m": route_length_m,
                   "voltage_v": source.voltage_v,
                   "phase_mode": source.phase_mode,
                   "ambient_c": install.effective_ambient_c(),
                   "base_ambient_c": install.base_ambient_c(),
                   "n_circuits": install.n_circuits,
                   "tabulated_rating_a": install.tabulated_rating_a},
        "sizes": {"active_mm2": r.active_area_mm2,
                  "neutral_mm2": r.neutral_area_mm2,
                  "earth_mm2": r.earth_area_mm2,
                  "parallel_runs": r.parallel},
        "currents": {"design_a": r.design_current_a,
                     "required_capacity_a": r.required_capacity_a,
                     "derated_capacity_a": r.derated_capacity_a,
                     "neutral_a": r.neutral_current_a,
                     "substantial_harmonics": r.substantial_harmonics},
        "derating": {"ambient": r.ambient_factor,
                     "grouping": r.grouping_factor,
                     "total": r.derating_factor},
        "voltage_drop": {"volts": r.voltage_drop_v,
                         "percent": r.voltage_drop_pct,
                         "limit_percent": r.voltage_drop_limit_pct},
        "fault": {"current_a": r.fault_current_a,
                  "min_area_mm2": r.min_fault_area_mm2, "k": r.k_constant},
        "thermal": {"operating_temp_c": r.operating_temp_c},
        "geometry": {"od_mm": r.od_mm, "weight_kg_per_m": r.weight_kg_per_m,
                     "bend_radius_mm": r.bend_radius_mm},
        "max_loop_length_m": r.max_loop_length_m,
        "checks": [{"name": c.name, "passed": c.passed, "detail": c.detail,
                    "margin_pct": c.margin_pct} for c in r.checks],
        "warnings": list(r.warnings),
        "summary_text": r.summary() if r.passed else None,
    }
    if r.active_area_mm2:
        out["manufacturers"] = match_manufacturers(r, install, source)
    return out


# ------------------------------------------------------------------ operations

def size(payload):
    """Select the smallest size that passes every check. AS/NZS only."""
    source, load, install, length = _build(payload)
    r = cs.size_feeder(source, load, length, install=install, catalog=CATALOG)
    return _serialise(r, source, install, length, "select")


def check(payload):
    """Check a nominated size. Works under every standard."""
    source, load, install, length = _build(payload)
    area = payload.get("area_mm2")
    if area in (None, ""):
        raise ValueError("area_mm2 is required when checking a nominated size")
    parallel = int(_f(payload, "parallel", 1))
    r = cs.check_feeder(source, load, length, float(area), install=install,
                        catalog=CATALOG, parallel=parallel)
    return _serialise(r, source, install, length, "check")


def list_standards():
    return {"standards": standards.catalogue(), "default": standards.DEFAULT}


def list_cable_types():
    return {sid: {"name": v.get("name"), "conductor": v.get("conductor"),
                  "insulation": v.get("insulation"),
                  "max_temp_c": v.get("max_temp_c"),
                  "voltage_kv": v.get("voltage_kv"),
                  "sizes": sorted(v["sizes"], key=float)}
            for sid, v in CATALOG["cables"].items()}


def list_diagrams():
    return install_diagrams.all_svg()


def diagram(key):
    return install_diagrams.svg(key)


def meta():
    return {
        "version": VERSION,
        "standards": standards.catalogue(),
        "default_standard": standards.DEFAULT,
        "cable_types": list_cable_types(),
        "phase_modes": sorted(as3008.VD_FACTOR),
        "circuit_uses": sorted(
            as3008.TABLES["min_conductor_size_as3000_table_3_3"]["data"]),
        "catalogue_source": CATALOG.get("source"),
        "tricab": {"source": TRICAB.get("source"),
                   "families": len(TRICAB.get("families", [])),
                   "scope": TRICAB.get("scope")},
        "unverified_tables": as3008.unverified_tables(),
        "diagram_css": install_diagrams.CSS,
    }


def health():
    return {"status": "ok", "version": VERSION,
            "standards": sorted(standards.STANDARDS),
            "cable_types": sorted(CATALOG["cables"]),
            "tricab_families": len(TRICAB.get("families", []))}
