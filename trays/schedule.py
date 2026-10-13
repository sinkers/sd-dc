"""Cable schedule for a tray run, as CSV and Markdown.

One row per circuit from the tray service's "circuits": what the cable is,
how long, how much current it carries against what it can, voltage drop
against its limit, fault level and whether every check passed.
"""
from __future__ import annotations

import csv
import io

COLUMNS = [
    ("id", "Circuit"), ("from", "From"), ("to", "To"),
    ("load", "Load"), ("cable", "Cable"), ("voltage_v", "V"),
    ("length_m", "Length m"), ("design_a", "Design A"),
    ("capacity_a", "Capacity A"), ("utilisation", "Util."),
    ("vd_v", "VD V"), ("vd_pct", "VD %"), ("vd_limit_pct", "VD limit %"),
    ("fault_a", "Fault A"), ("operating_temp_c", "Temp °C"),
    ("mass_kg_per_m", "kg/m"), ("width_mm", "Width mm"),
    ("passed", "Checks"),
]


def _cell(row, key):
    v = row.get(key)
    if key == "load" and isinstance(v, dict):
        return ", ".join(f"{x:g} {k.upper().replace('KW', 'kW').replace('KVA', 'kVA').replace('AMPS', 'A')}"
                         for k, x in v.items())
    if key == "passed":
        return "pass" if v else "FAIL: " + ", ".join(row.get("failed_checks")
                                                     or ["sizing"])
    if isinstance(v, float):
        return f"{v:g}"
    return "" if v is None else str(v)


def to_csv(rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow([h for _, h in COLUMNS])
    for r in rows:
        w.writerow([_cell(r, k) for k, _ in COLUMNS])
    return buf.getvalue()


def to_markdown(result):
    rows = result.get("circuits") or []
    t = result.get("cable_totals") or {}
    lines = [f"# Cable schedule: tray {result['id']}", ""]
    tray = result.get("tray", {})
    lines.append(f"Tray {tray.get('family')} {tray.get('width'):g}, "
                 f"{result.get('tray_length_m')} m route, "
                 f"{t.get('circuits')} circuits, {t.get('grouped_runs')} runs "
                 f"grouped for derating, {t.get('mass_kg_per_m')} kg/m of "
                 f"cable, {t.get('width_mm')} mm of tray width used.")
    lines += ["", "| " + " | ".join(h for _, h in COLUMNS) + " |",
              "|" + "---|" * len(COLUMNS)]
    for r in rows:
        lines.append("| " + " | ".join(_cell(r, k).replace("|", "/")
                                       for k, _ in COLUMNS) + " |")
    if result.get("cable_bom"):
        lines += ["", "## Cable to order", "", "| Type | Size mm² | Use | m |",
                  "|---|---|---|---|"]
        for b in result["cable_bom"]:
            lines.append(f"| {b['cable_type']} | {b['area_mm2']:g} | "
                         f"{b['use']} | {b['metres']:g} |")
    issues = (result.get("cable_issues") or []) + (result.get("issues") or [])
    if issues:
        lines += ["", "## Issues", ""] + [f"- {i['message']}"
                                          for i in issues]
    lines += ["", "Sized with sd-dc cable-sizing (AS/NZS 3008.1.1). Lengths "
              "are the tray route plus tails. Draft for an engineer."]
    return "\n".join(lines) + "\n"
