"""Port the licensed Section 4 JSON tables into the data/ CSV layer.

The Section 4 and 5 numbers were read from the licensed AS/NZS 3008.1.1:2025
on 2026-09-04 and landed as JSON beside the legacy engine. dame_cable reads
CSV. This moves the data across without going back to the printed standard,
so the transcription is not repeated and cannot drift.

    python3 tools_port_json_tables.py [data_dir]

Sources
    as3008_impedance_tables.json  4.1, 4.2   reactance
                                  4.5-4.10   a.c. resistance
    as3008_vc_tables.json         4.14-4.31  mV/A/m

Axes are taken from the standard, not from what the old manifest happened to
carry. Nothing is interpolated and nothing is defaulted; a cell absent from
the JSON is absent from the CSV.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
READ_ON = "2026-09-04"
EDITION = "AS/NZS 3008.1.1:2025"


def _load(name):
    return json.load(open(ROOT / name))


def _sizes(mapping):
    """Yield (size_mm2, value) skipping dashes and nulls."""
    for size, val in mapping.items():
        if val is None or val == "-" or val == "":
            continue
        yield float(size), float(val)


# ---------------------------------------------------------------- reactance
# 4.1 fixed wiring (excludes flexible, MIMS, aerial); 4.2 flexible.
# Both are keyed formation -> insulation class -> size for single-core, and
# conductor profile -> insulation class -> size for multicore.

def build_reactance(imp):
    rows = []
    for table_id, form_class in (("4.1", "fixed"), ("4.2", "flexible")):
        t = imp["tables"][table_id]
        sc = t.get("single_core", {})
        for formation, by_ins in sc.get("data", {}).items():
            for ins_class, sizes in by_ins.items():
                for size, val in _sizes(sizes):
                    rows.append({
                        "form_class": form_class,
                        "construction": formation,      # trefoil | flat_touching
                        "insulation_class": ins_class,  # Elastomer | PVC | XLPE
                        "size_mm2": size,
                        "x_ohm_per_km": val,
                        "source_table": table_id,
                    })
        mc = t.get("multicore", {})
        for profile, by_ins in mc.get("data", {}).items():
            for ins_class, sizes in by_ins.items():
                for size, val in _sizes(sizes):
                    rows.append({
                        "form_class": form_class,
                        "construction": profile,        # circular | shaped
                        "insulation_class": ins_class,
                        "size_mm2": size,
                        "x_ohm_per_km": val,
                        "source_table": table_id,
                    })
    return rows


def reactance_spacing_note(imp):
    """NOTE 1 of 4.1/4.2: additive correction for spaced single-core."""
    out = []
    for table_id in ("4.1", "4.2"):
        t = imp["tables"][table_id]
        corr = t.get("single_core", {}).get("spacing_correction_ohm_km") or \
               t.get("spacing_correction_ohm_km") or {}
        for spacing, val in corr.items():
            if spacing.startswith("_"):
                continue
            out.append((table_id, spacing, val))
    return out


# --------------------------------------------------------------- resistance
# a.c. only. 4.5 single-core, 4.7 multicore circular, 4.9 multicore shaped
# are fixed wiring; 4.10 is flexible (copper only) and splits single-core
# from multicore one level up.

AC_FIXED = {
    "4.5": "single-core",
    "4.7": "multicore-circular",
    "4.9": "multicore-shaped",
}
MATERIAL = {"Copper": "Cu", "Aluminium": "Al"}


def build_resistance(imp):
    rows = []
    for table_id, construction in AC_FIXED.items():
        t = imp["tables"][table_id]
        for material_name, by_temp in t["data"].items():
            for temp, sizes in by_temp.items():
                for size, val in _sizes(sizes):
                    rows.append({
                        "form_class": "fixed",
                        "construction": construction,
                        "material": MATERIAL[material_name],
                        "size_mm2": size,
                        "temperature_c": float(temp),
                        "r_ohm_per_km": val,
                        "source_table": table_id,
                    })

    flex = imp["tables"]["4.10"]
    for group, construction in (("single_core", "single-core"),
                                ("multicore", "multicore-circular")):
        by_temp = flex["data"].get(group, {})
        for temp, sizes in by_temp.items():
            for size, val in _sizes(sizes):
                rows.append({
                    "form_class": "flexible",
                    "construction": construction,
                    "material": "Cu",          # 4.10 is copper only
                    "size_mm2": size,
                    "temperature_c": float(temp),
                    "r_ohm_per_km": val,
                    "source_table": "4.10",
                })
    return rows


# ---------------------------------------------------------------- mv_per_a_m
# 4.14-4.31. Each table fixes conductor, construction and formation; the data
# is temperature -> size -> {max, pf_0_8}. `max` is the worst-case column and
# `pf_0_8` the 0.8 power factor column.

SKIPPED = []


def build_mv_per_a_m(vc):
    rows = []
    for table_id, t in vc["tables"].items():
        data = t.get("data")
        if not isinstance(data, dict):
            continue
        conductor = MATERIAL.get(t.get("conductor", ""), t.get("conductor", ""))
        for temp, sizes in data.items():
            if not isinstance(sizes, dict):
                continue
            for size, cell in sizes.items():
                if not isinstance(cell, dict):
                    continue
                try:
                    size_mm2 = float(size)
                except ValueError:
                    # Flexible-cord tables key rows by stranding ("7/1.00"),
                    # not by nominal area. The manifest holds size_mm2 as a
                    # number, so these rows cannot be represented and are
                    # skipped rather than coerced. Counted and reported.
                    SKIPPED.append((table_id, size))
                    continue
                for pf_label, column in (("max", "max"), ("0.8", "pf_0_8")):
                    val = cell.get(column)
                    if val is None:
                        continue
                    rows.append({
                        "system": t.get("current", ""),
                        "material": conductor,
                        "insulation": "",
                        "construction": t.get("construction", ""),
                        "formation": t.get("formation", ""),
                        "size_mm2": size_mm2,
                        "temperature_c": float(temp),
                        "power_factor": pf_label,
                        "mv_per_a_m": float(val),
                        "source_table": table_id,
                    })
    return rows


# --------------------------------------------------------------------- write

def write(path: Path, rows, header_lines, columns):
    with open(path, "w", newline="") as fh:
        for line in header_lines:
            fh.write(f"# {line}\n")
        w = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda r: tuple(str(r.get(c, "")) for c in columns)):
            w.writerow(r)
    print(f"{path.name}: {len(rows)} rows")


def main():
    out = Path(sys.argv[1] if len(sys.argv) > 1 else ROOT / "data")
    out.mkdir(parents=True, exist_ok=True)
    imp = _load("as3008_impedance_tables.json")
    vc = _load("as3008_vc_tables.json")

    react = build_reactance(imp)
    notes = [f"Spacing correction, Table {t} NOTE 1: add {v} ohm/km at {s}"
             for t, s, v in reactance_spacing_note(imp)]
    write(out / "reactance.csv", react, [
        "reactance",
        f"Source: {EDITION} Tables 4.1 (fixed wiring) and 4.2 (flexible),",
        f"read from the licensed copy {READ_ON}. Ported from",
        "as3008_impedance_tables.json by tools_port_json_tables.py -- not a",
        "second transcription, the same reading in the CSV layer.",
        "form_class: fixed (T4.1) | flexible (T4.2).",
        "construction: trefoil | flat_touching for single-core;",
        "              circular | shaped for multicore.",
        "insulation_class is the table's own axis (Elastomer|PVC|XLPE), NOT",
        "the Insulation enum -- one class serves several enum members.",
        "Tabulated values are for TOUCHING formation only.",
    ] + notes,
        ["form_class", "construction", "insulation_class", "size_mm2",
         "x_ohm_per_km", "source_table"])

    res = build_resistance(imp)
    write(out / "resistance.csv", res, [
        "resistance",
        f"Source: {EDITION} Section 4 a.c. resistance tables 4.5, 4.7, 4.9",
        f"(fixed wiring) and 4.10 (flexible, copper only), read from the",
        f"licensed copy {READ_ON}. Ported from as3008_impedance_tables.json",
        "by tools_port_json_tables.py.",
        "d.c. tables 4.6, 4.8, 4.11 are NOT ported; the engine is a.c.",
        "Tabulated at the standard's own operating temperatures. Reach an",
        "intermediate temperature with the alpha-20 correction in",
        "voltage_drop.resistance_at, never by interpolating this table.",
        "Tinned copper: multiply by 1.01 (fixed) or 1.02 (flexible).",
    ], ["form_class", "construction", "material", "size_mm2", "temperature_c",
        "r_ohm_per_km", "source_table"])

    mv = build_mv_per_a_m(vc)
    write(out / "mv_per_a_m_licensed.csv", mv, [
        "mv_per_a_m_licensed -- NOT YET IN THE MANIFEST.",
        "Wiring this to cross_check_mv_per_a_m needs a mapping layer: the",
        "tables key on ac/dc and on formation, the engine on SystemType,",
        "and each table fixes an insulation the rows do not carry.",
        f"Source: {EDITION} Section 4 Tables 4.14-4.31, read from the licensed",
        f"copy {READ_ON}. Ported from as3008_vc_tables.json by",
        "tools_port_json_tables.py.",
        "power_factor is 'max' (worst-case column) or '0.8'.",
        "Independent check only: voltage_drop computes from R and X and the",
        "verification suite confirms agreement against this table.",
    ], ["system", "material", "insulation", "construction", "formation",
        "size_mm2", "temperature_c", "power_factor", "mv_per_a_m",
        "source_table"])


if __name__ == "__main__":
    main()
