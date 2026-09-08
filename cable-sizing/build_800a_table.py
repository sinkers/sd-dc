#!/usr/bin/env python3
"""Build an 800 A cable schedule page: 3 phase + neutral + earth, 5 m to 50 m.

  python3 build_800a_table.py [-o out.html]

Sizes a 100% neutral three-phase feeder over 5-50 m in flexible copper and in
aluminium, across a range of voltage drop budgets, and writes a self-contained
HTML page. Every number comes from cable_sizing.size_feeder.
"""
from __future__ import annotations

import argparse
import datetime
import html
import math
import os

import as3008
import cable_sizing as cs
import ezystrut
import install_diagrams
import service

AMPS = 800.0
VOLTAGE = 415.0
POWER_FACTOR = 0.9
LENGTHS = (5, 10, 15, 20, 25, 30, 35, 40, 45, 50)
VD_BUDGETS = (5.0, 2.5, 2.0, 1.0, 0.5)
STANDARD_VD = 5.0
AMBIENT = 40.0
N_CIRCUITS = 1
METHOD = "touching"
# Stated rather than implied, because it changes the answer more than anything
# else on this page: single-core cables laid touching in one layer on a
# perforated tray, and parallel runs counted as separate grouped bundles
# because that is what they physically are on that tray.
PARALLEL_RUNS_GROUPED = True
CORES_PER_RUN = 4          # three actives plus one neutral, at 100% neutral
TRAY_FAMILY = "ET5"        # the tray component recommends ET5 for power runs
TRAY_SPAN_MM = 3000.0      # support spacing the load check is made at
FAULT_KA = 50.0
CLEARING_S = 0.2
MAX_PARALLEL = 4
CLASS5_R_UPLIFT = 1.05      # bound for class 5 resistance over class 2

CATALOG = cs.load_catalog()

# Total conductor area per phase, runs x mm2, is what the colour encodes: it is
# the quantity that drives cost, mass and tray width, and it is monotone, so a
# sequential ramp is the right job. Five ordinal bands over the twelve distinct
# sizes the matrix produces (300 to 1890 mm2/phase).
#
# The steps are published points on one blue hue, chosen so the light end still
# clears the surface and every adjacent pair has a visible lightness gap. Both
# ramps pass the six-check validator in --ordinal mode; the dark column is the
# same hue re-stepped for the dark surface, not an automatic flip. Light runs
# pale to deep as the area rises; dark runs dim to bright, so in both modes more
# visual weight means more metal.
SIZE_BANDS = (
    (400.0,   "band-1", "up to 400"),
    (630.0,   "band-2", "480 to 630"),
    (1000.0,  "band-3", "800 to 1000"),
    (1260.0,  "band-4", "1200 to 1260"),
    (1e9,     "band-5", "1500 and above"),
)
BAND_HEX_LIGHT = ("#86b6ef", "#5598e7", "#2a78d6", "#1c5cab", "#0d366b")
BAND_HEX_DARK = ("#b7d3f6", "#6da7ec", "#3987e5", "#256abf", "#184f95")
AREA_MAX = 1890.0
# Circle diameters are scaled between these, so a circle's size reads as the
# cable's real outside diameter rather than an arbitrary rank.
OD_MIN_PX, OD_MAX_PX = 9.0, 19.0


_OD_SPAN = None


def od_span():
    """OD range of the cables this schedule actually selects.

    Scaling across the whole catalogue would include 8.6 mm cables that an
    800 A feeder never reaches, squashing every circle on the page into the top
    of the range. Scaling across the selections keeps the differences visible.
    """
    global _OD_SPAN
    if _OD_SPAN is None:
        ods = []
        for c in CONDUCTORS:
            for length in LENGTHS:
                for budget in VD_BUDGETS:
                    r = size(c["key"], length, budget)
                    if not r.passed:
                        continue
                    spec = CATALOG["cables"][c["key"]]["sizes"][
                        f"{r.active_area_mm2:g}"]
                    if spec.get("od_mm"):
                        ods.append(spec["od_mm"])
        _OD_SPAN = (min(ods), max(ods)) if ods else (OD_MIN_PX, OD_MAX_PX)
    return _OD_SPAN


def circle_px(od_mm):
    lo, hi = od_span()
    if hi <= lo:
        return OD_MIN_PX
    t = (od_mm - lo) / (hi - lo)
    return OD_MIN_PX + t * (OD_MAX_PX - OD_MIN_PX)


_DOT_CLASSES = {}


def dot_class(od_mm):
    """Class name for a circle at this cable OD, registering the size once.

    Every circle used to carry its own inline width and height, which was most
    of the page's weight for no benefit: there are only a handful of distinct
    diameters. This registers each one and returns a class.
    """
    px = round(circle_px(od_mm), 1)
    if px not in _DOT_CLASSES:
        _DOT_CLASSES[px] = f"z{len(_DOT_CLASSES) + 1}"
    return _DOT_CLASSES[px]


def dot_css():
    return "".join(f".dot.{name}{{width:{px}px;height:{px}px}}"
                   for px, name in sorted(_DOT_CLASSES.items()))


def band(total_mm2):
    for edge, cls, _ in SIZE_BANDS:
        if total_mm2 <= edge:
            return cls
    return SIZE_BANDS[-1][1]

CONDUCTORS = (
    {
        "key": "XHF110_4C1CE_CU",
        "label": "Flexible copper, 110 °C",
        "match": "exact",
        "note": "Class 5 flexible copper, X-110, single-core 4&times;1C+E. "
                "Ratings are AS/NZS 3008.1.1 <strong>Table 3.14 column 5</strong> "
                "&mdash; the four-loaded-core column, which is the right one for "
                "three phases plus a loaded neutral. jCalc and ELEK both report "
                "839 A at 400 mm&sup2; for this configuration and both select "
                "400 mm&sup2; for this feeder, and so does this engine. "
                "Diameters and masses come from the Nexans LFH cable of the same "
                "construction, because the standard tabulates ratings only.",
    },
    {
        "key": "XLPE_SDI_AL",
        "label": "Aluminium, 90 °C",
        "match": "substitute",
        "note": "The nearest aluminium in the catalogue. It is class 2 stranded, "
                "<strong>not flexible</strong>, and X-90 rated 90 °C, "
                "<strong>not high temperature</strong>. Both differences make it "
                "a conservative stand-in: a class 5 flexible conductor of the "
                "same area has a slightly higher resistance, and a 110 °C or "
                "125 °C insulation would carry more current. Treat the "
                "aluminium column as a floor, not an answer.",
    },
)


def source():
    return cs.Source("MSB-800", voltage_v=VOLTAGE, phase_mode="3-phase",
                     fault_level_ka=FAULT_KA, clearing_time_s=CLEARING_S)


def load(vd_limit):
    # 100% neutral: out_of_balance_pct 100 with no harmonics makes the neutral
    # design current equal the phase current, so AS/NZS 3000 clause 3.5.2 puts
    # the neutral at the active size.
    return cs.Load("Feeder", amps=AMPS, power_factor=POWER_FACTOR,
                   max_voltage_drop_pct=vd_limit, out_of_balance_pct=100.0,
                   harmonic_content_pct=0.0)


def install(cable_type):
    return cs.Installation(method=METHOD, ambient_c=AMBIENT,
                           n_circuits=N_CIRCUITS, cable_type=cable_type,
                           max_parallel=MAX_PARALLEL,
                           parallel_runs_grouped=PARALLEL_RUNS_GROUPED)


def size(cable_type, length_m, vd_limit):
    return cs.size_feeder(source(), load(vd_limit), length_m,
                          install(cable_type), catalog=CATALOG)


def rx_at(cable_type, area_mm2, temp_c):
    """Resistance and reactance actually used, so the class 5 bound can be shown."""
    entry = CATALOG["cables"][cable_type]
    spec = entry["sizes"][f"{area_mm2:g}"]
    cond = as3008.CONDUCTORS[entry["conductor"]]
    ins = as3008.resolve_insulation(entry["insulation"])
    r, x, _ = cs._cable_electrical(entry, spec, area_mm2, cond,
                                   as3008.round_to_temp_column(temp_c),
                                   ins.max_temp_c)
    return r, x


def vd_with_uplift(r, x, length_m, parallel, uplift):
    """Voltage drop if resistance were `uplift` times higher. Reactance is
    unaffected, so the two terms cannot simply be scaled together."""
    phi = math.acos(POWER_FACTOR)
    z = r * uplift * POWER_FACTOR + x * math.sin(phi)
    return math.sqrt(3.0) * AMPS * length_m * z / 1000.0 / parallel


def bundle(cable_type, area_mm2, parallel, earth_mm2):
    """What is actually on the tray, and what it weighs per metre.

    A three-phase circuit with a 100% neutral is three actives and a neutral
    per parallel run, plus one earth for the circuit. Counting one conductor
    per run understates both the cable count and the tray load by four times.
    """
    sizes = CATALOG["cables"][cable_type]["sizes"]
    core = sizes[f"{area_mm2:g}"].get("weight_kg_100m")
    earth_w = sizes.get(f"{earth_mm2:g}", {}).get("weight_kg_100m")
    od = sizes[f"{area_mm2:g}"].get("od_mm")
    earth_od = sizes.get(f"{earth_mm2:g}", {}).get("od_mm")
    actives = 3 * parallel
    neutrals = parallel
    total_cores = actives + neutrals + 1
    mass = None
    if core is not None:
        mass = CORES_PER_RUN * parallel * core / 100.0
        if earth_w is not None:
            mass += earth_w / 100.0
    # Single layer touching: the tray must span every core side by side.
    width = None
    if od is not None:
        width = (actives + neutrals) * od + (earth_od or 0.0)
    return {"actives": actives, "neutrals": neutrals, "earths": 1,
            "total_cores": total_cores, "mass_kg_per_m": mass,
            "od_mm": od, "earth_od_mm": earth_od, "tray_width_mm": width}


def tray_section_svg(cable_type, area_mm2, parallel, earth_mm2):
    """Cross-section of the actual bundle: every core, touching, on a tray.

    The generic "touching" diagram draws three cables. This circuit has three
    actives and a neutral per run plus an earth, so a generic picture would
    misstate the very thing the page is about. Circles are drawn to the real
    outside diameters and to a common scale, so the earth reads as smaller
    because it is.
    """
    bd = bundle(cable_type, area_mm2, parallel, earth_mm2)
    od, e_od = bd["od_mm"], bd["earth_od_mm"] or 0.0
    n_power = bd["actives"] + bd["neutrals"]

    W, H = install_diagrams.W, install_diagrams.H
    inner = 168.0                      # px available between the tray lips
    gap_mm = 6.0                       # a small air gap before the earth
    span_mm = n_power * od + gap_mm + e_od
    k = min(inner / span_mm, 2.2)      # px per mm, capped so small runs are not huge
    r_p, r_e = od * k / 2.0, e_od * k / 2.0
    total_px = n_power * od * k + gap_mm * k + e_od * k
    x = (W - total_px) / 2.0
    base = 74.0                        # tray deck

    parts = []
    lip = 13.0
    parts.append(
        f'<path d="M16,{base} L16,{base - lip} M184,{base} L184,{base - lip}" '
        f'stroke="var(--dg-line)" stroke-width="1.8" fill="none"/>'
        f'<rect x="16" y="{base}" width="168" height="8" fill="url(#hatch)"/>'
        f'<line x1="16" y1="{base}" x2="184" y2="{base}" '
        f'stroke="var(--dg-line)" stroke-width="1.6"/>')

    def core(cx, r, label):
        cy = base - r
        return (f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{r:.1f}" fill="none" '
                f'stroke="var(--dg-ins)" stroke-width="{max(1.6, r * 0.28):.1f}"/>'
                f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{max(1.2, r - r * 0.34):.1f}" '
                f'fill="var(--dg-cu)"/>'
                + (f'<text x="{cx:.1f}" y="{base - 2 * r - 4:.1f}" '
                   f'text-anchor="middle" style="font-size:8px">{label}</text>'
                   if label else ""))

    # Three actives then the neutral, per run, all in contact.
    for i in range(n_power):
        cx = x + r_p + i * od * k
        per_run = 4
        idx = i % per_run
        lbl = ("A", "B", "C", "N")[idx] if n_power <= 8 else ""
        parts.append(core(cx, r_p, lbl))
    if r_e > 0:
        cx = x + n_power * od * k + gap_mm * k + r_e
        parts.append(core(cx, r_e, "E"))

    parts.append(
        f'<line x1="{x:.1f}" y1="{base + 14:.1f}" '
        f'x2="{x + total_px:.1f}" y2="{base + 14:.1f}" stroke="var(--dg-dim)" '
        f'stroke-width="1.1" marker-start="url(#ar)" marker-end="url(#ar)"/>'
        f'<text class="dim" x="{W / 2}" y="{base + 26:.1f}" text-anchor="middle">'
        f'{bd["tray_width_mm"]:.0f} mm</text>')
    parts.append(
        f'<text x="{W / 2}" y="14" text-anchor="middle">unenclosed, touching, '
        f'single layer</text>')

    body = "".join(parts)
    return (f'<svg class="dg" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="Cross-section of {bd["total_cores"]} cables touching '
            f'on a tray">{install_diagrams._DEFS}{body}</svg>')


def tray_cell(t):
    if not t["fits"]:
        return f'<span class="hot">{esc(t["reason"])}</span>'
    note = (' <span class="note">self-weight interpolated</span>'
            if t["self_weight_interpolated"] else '')
    return (f'{esc(t["part"])} <span class="note">{t["width_mm"]:.0f} mm, '
            f'{t["spare_width_mm"]:.0f} mm spare</span>{note}')


def tray_load(t):
    if not t["fits"] or t["load_limit_kg_per_m"] is None:
        return "&mdash;"
    return (f'{t["load_utilisation_pct"]:.0f} % '
            f'<span class="note">of {t["load_limit_kg_per_m"]:.0f} kg/m</span>')


def tray_class(t):
    if not t["fits"] or t["load_utilisation_pct"] is None:
        return ""
    u = t["load_utilisation_pct"]
    return "hot" if u > 100 else ("tight" if u >= 80 else "")


def esc(s):
    return html.escape(str(s), quote=True)


def matrix_rows(cable_type):
    """One row per route length. Each cell carries what the colour needs."""
    out = []
    for length in LENGTHS:
        cells = []
        for budget in VD_BUDGETS:
            r = size(cable_type, length, budget)
            if not r.passed:
                cells.append(None)
                continue
            total = r.parallel * r.active_area_mm2
            bd = bundle(cable_type, r.active_area_mm2, r.parallel,
                        r.earth_area_mm2)
            cells.append({
                # Three actives per run, not one. The old label read "1 x 300"
                # for a three-phase circuit, which understated the cable count
                # fourfold.
                "label": f"{bd['actives']} &times; {r.active_area_mm2:g}",
                "runs_note": (f"{r.parallel} per phase"
                              if r.parallel > 1 else "1 per phase"),
                "total": total,
                "band": band(total),
                "budget": budget,
                "vd_pct": r.voltage_drop_pct,
                "capacity": r.derated_capacity_a,
                "runs": r.parallel,
                "area": r.active_area_mm2,
                "bundle": bd,
                "od": bd["od_mm"],
            })
        out.append((length, cells))
    return out


def detail_rows(cable_type):
    out = []
    for length in LENGTHS:
        r = size(cable_type, length, STANDARD_VD)
        if not r.passed:
            out.append({"length": length, "failed": r.failure_reason})
            continue
        rr, xx = rx_at(cable_type, r.active_area_mm2, r.operating_temp_c)
        vd5 = vd_with_uplift(rr, xx, length, r.parallel, CLASS5_R_UPLIFT)
        bind = min(r.checks, key=lambda c: c.margin_pct)
        ins = as3008.resolve_insulation(
            CATALOG["cables"][cable_type]["insulation"])
        out.append({
            "length": length, "failed": None,
            "runs": r.parallel, "active": r.active_area_mm2,
            "neutral": r.neutral_area_mm2, "earth": r.earth_area_mm2,
            "capacity": r.derated_capacity_a,
            "utilisation": 100.0 * AMPS / r.derated_capacity_a,
            "vd_v": r.voltage_drop_v, "vd_pct": r.voltage_drop_pct,
            "vd_pct_c5": 100.0 * vd5 / VOLTAGE,
            "op_temp": r.operating_temp_c, "max_temp": ins.max_temp_c,
            "od": r.od_mm,
            "bundle": (bd := bundle(cable_type, r.active_area_mm2, r.parallel,
                                    r.earth_area_mm2)),
            "tray": ezystrut.select(bd["tray_width_mm"], bd["mass_kg_per_m"],
                                    family_id=TRAY_FAMILY,
                                    span_mm=TRAY_SPAN_MM),
            "bind": bind.name, "bind_margin": bind.margin_pct,
            "r": rr, "x": xx,
        })
    return out


def tricab_flexible_al():
    """Public Tricab families that are flexible aluminium above 90 C."""
    out = []
    for fam in service.TRICAB.get("families", []):
        if fam.get("conductor") != "Aluminium":
            continue
        if (fam.get("max_conductor_temp_c") or 0) <= 90:
            continue
        blurb = f"{fam.get('construction') or ''} {fam.get('name') or ''}".lower()
        if "flexible" not in blurb:
            continue
        key = (fam.get("code"), fam.get("construction"),
               fam.get("max_conductor_temp_c"))
        if key in {(o["code"], o["construction"], o["temp"]) for o in out}:
            continue
        out.append({"code": fam.get("code"), "construction": fam.get("construction"),
                    "voltage": fam.get("voltage"),
                    "temp": fam.get("max_conductor_temp_c"),
                    "url": fam.get("url")})
    return sorted(out, key=lambda o: (-(o["temp"] or 0), o["code"] or "zz"))


CSS = """
:root{--bg:#f6f7f9;--panel:#fff;--ink:#14181f;--dim:#5d6673;--line:#dde1e7;
  --accent:#0f5ea8;--ok:#1a7f4b;--bad:#b3261e;--warn:#8a5a00;--chip:#eef1f5;
  --cu:#b5721f;--al:#5a7f9e}
/* Dark values are declared under both scopes: the media query covers the OS
   setting, the data-theme scope covers a viewer theme toggle, and the
   :not([data-theme="light"]) guard lets an explicit light stamp beat OS dark.
   Without the second scope the chart colours would switch and the page around
   them would not, which is what happened first time. */
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){
  --bg:#12151a;--panel:#1a1e25;
  --ink:#e8ebf0;--dim:#9aa4b2;--line:#2b313b;--accent:#63a8e8;--ok:#5fd39b;
  --bad:#f2857c;--warn:#e0b055;--chip:#242a33;--cu:#d99a4e;--al:#8fb2cc}}
:root[data-theme="dark"]{--bg:#12151a;--panel:#1a1e25;
  --ink:#e8ebf0;--dim:#9aa4b2;--line:#2b313b;--accent:#63a8e8;--ok:#5fd39b;
  --bad:#f2857c;--warn:#e0b055;--chip:#242a33;--cu:#d99a4e;--al:#8fb2cc}
*{box-sizing:border-box}
html{background:var(--bg)}
body{margin:0;background:var(--bg);color:var(--ink);
  font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}
.page{max-width:1180px;margin:0 auto;padding:26px 22px 60px}
h1{font-size:23px;margin:0 0 4px;letter-spacing:-.3px}
.sub{color:var(--dim);font-size:14px;margin:0 0 22px}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
  margin:0 0 12px;font-weight:600}
h3{font-size:15px;margin:22px 0 8px}
.card{background:var(--panel);border:1px solid var(--line);border-radius:10px;
  padding:17px 19px;margin-bottom:18px}
.brief{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px}
.b{background:var(--chip);border-radius:8px;padding:10px 12px}
.b .k{font-size:10.5px;text-transform:uppercase;letter-spacing:.07em;color:var(--dim)}
.b .v{font-size:17px;font-weight:650;margin-top:2px;letter-spacing:-.3px}
.b .v small{font-size:12px;font-weight:400;color:var(--dim)}
table{width:100%;border-collapse:collapse;font-size:13.5px}
th,td{text-align:left;padding:7px 9px;border-bottom:1px solid var(--line)}
th{font-size:10.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);
  font-weight:600;vertical-align:bottom}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
td.num{white-space:nowrap}
tr:last-child td{border-bottom:0}
tbody tr:hover{background:var(--chip)}
.scroll{overflow-x:auto}
.cu{color:var(--cu);font-weight:650}
.al{color:var(--al);font-weight:650}
.pill{display:inline-block;font-size:10.5px;padding:2px 8px;border-radius:20px;
  background:var(--chip);color:var(--dim);margin-left:7px;vertical-align:2px}
.exact{color:var(--ok);border:1px solid color-mix(in srgb,var(--ok) 40%,transparent)}
.sub2{color:var(--warn);border:1px solid color-mix(in srgb,var(--warn) 40%,transparent)}
.note{font-size:12.5px;color:var(--dim);margin:9px 0 0}
.warn,.err{border-left:3px solid var(--warn);padding:11px 13px;border-radius:0 7px 7px 0;
  font-size:13.5px;margin:10px 0 0;
  background:color-mix(in srgb,var(--warn) 11%,transparent)}
.err{border-left-color:var(--bad);
  background:color-mix(in srgb,var(--bad) 11%,transparent)}
.hot{color:var(--bad);font-weight:650}
.tight{color:var(--warn);font-weight:650}
code{font:12.5px ui-monospace,SFMono-Regular,Menlo,monospace;background:var(--chip);
  padding:1px 5px;border-radius:4px}
.legend{display:flex;flex-wrap:wrap;gap:16px;font-size:12.5px;color:var(--dim);
  margin-top:10px}

/* --- size heatmap ------------------------------------------------------
   Colour encodes total conductor area per phase on one blue hue. The label
   stays in text ink and the bar carries the encoding, so nothing depends on
   text sitting legibly on a coloured fill. Bar WIDTH repeats the same
   quantity, which keeps the steps readable without colour at all. */
.viz{--band-1:#86b6ef;--band-2:#5598e7;--band-3:#2a78d6;--band-4:#1c5cab;
     --band-5:#104281;--step-rule:#0f5ea8;--track:#eef1f5}
@media (prefers-color-scheme:dark){:root:where(:not([data-theme="light"])) .viz{
  --band-1:#9ec5f4;--band-2:#6da7ec;--band-3:#3987e5;--band-4:#256abf;
  --band-5:#184f95;--step-rule:#63a8e8;--track:#242a33}}
:root[data-theme="dark"] .viz{
  --band-1:#9ec5f4;--band-2:#6da7ec;--band-3:#3987e5;--band-4:#256abf;
  --band-5:#184f95;--step-rule:#63a8e8;--track:#242a33}
.viz td.c{padding:6px 9px}
.cell{display:flex;flex-direction:column;align-items:flex-end;gap:3px}
.cell .lbl{font-variant-numeric:tabular-nums;color:var(--ink);font-size:13px;
  font-weight:600;white-space:nowrap}
.cell .runs{font-size:10.5px;color:var(--dim);white-space:nowrap}
/* One circle per active conductor, drawn to the cable's real outside
   diameter. Count answers "how many", size answers "how big", and the fill
   carries total conductor area per phase. Three redundant channels, so the
   escalation reads without relying on any one of them. */
.dots{display:flex;align-items:flex-end;gap:2px;margin-top:1px;flex-wrap:nowrap}
.dot{border-radius:50%;display:inline-block;flex:0 0 auto;
  box-shadow:0 0 0 1.5px var(--panel)}
.band-1 .dot{background:var(--band-1)} .band-2 .dot{background:var(--band-2)}
.band-3 .dot{background:var(--band-3)} .band-4 .dot{background:var(--band-4)}
.band-5 .dot{background:var(--band-5)}
.swatches{display:flex;flex-wrap:wrap;gap:16px;margin-top:12px;font-size:12px;
  color:var(--dim);align-items:center}
.sw{display:inline-flex;align-items:center;gap:6px}
.sw i{width:13px;height:13px;border-radius:50%;display:inline-block}
.sw.s1 i{background:var(--band-1)} .sw.s2 i{background:var(--band-2)}
.sw.s3 i{background:var(--band-3)} .sw.s4 i{background:var(--band-4)}
.sw.s5 i{background:var(--band-5)}
.sizedemo{display:inline-flex;align-items:flex-end;gap:3px}
.sizedemo i{border-radius:50%;background:var(--band-3);display:inline-block}
footer{color:var(--dim);font-size:12px;margin-top:8px}
a{color:var(--accent)}
"""


def render():
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    i_design = as3008.design_current("3-phase", VOLTAGE, amps=AMPS,
                                     power_factor=POWER_FACTOR)
    p = []
    p.append(f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>800 A feeder schedule</title>
<style>{CSS}{install_diagrams.CSS}</style></head><body>
<div class="page">
<h1>800 A feeder, 3 phase + neutral + earth</h1>
<p class="sub">Cable sizing 5 m to 50 m in flexible copper and in aluminium,
   to AS/NZS 3008.1.1. Generated {now} from the repo catalogue and engine.</p>

<div class="card"><h2>The brief, as sized</h2>
<div class="brief">
  <div class="b"><div class="k">Load</div><div class="v">{AMPS:.0f} <small>A</small></div></div>
  <div class="b"><div class="k">System</div><div class="v">{VOLTAGE:.0f} <small>V, 3ph + N + E</small></div></div>
  <div class="b"><div class="k">Neutral</div><div class="v">100 <small>% of active</small></div></div>
  <div class="b"><div class="k">Power factor</div><div class="v">{POWER_FACTOR}</div></div>
  <div class="b"><div class="k">Design current</div><div class="v">{i_design:.0f} <small>A</small></div></div>
  <div class="b"><div class="k">Route</div><div class="v">5&ndash;50 <small>m</small></div></div>
</div>
<p class="note"><strong>Assumptions I had to make, because the brief did not
  set them.</strong> Ambient {AMBIENT:.0f} &deg;C, which is the AS/NZS 3008.1.1
  reference for air. Unenclosed single-core cables touching in a single layer on
  a tray or ladder, {N_CIRCUITS} circuit, so no grouping factor applies. Fault
  level {FAULT_KA:.0f} kA cleared in {CLEARING_S:g} s. Up to
  {MAX_PARALLEL} parallel runs per phase. Change any of these and the sizes
  move; the ambient and the grouping move them most.</p>
</div>""")

    # ---- what matches the brief and what does not
    p.append('<div class="card"><h2>How well the catalogue matches the brief</h2>')
    for c in CONDUCTORS:
        e = CATALOG["cables"][c["key"]]
        pill = ('<span class="pill exact">exact match</span>' if c["match"] == "exact"
                else '<span class="pill sub2">substitute</span>')
        p.append(f"""<h3>{esc(c['label'])}{pill}</h3>
<p class="note"><code>{esc(c['key'])}</code> &mdash; {esc(e['name'])}.
   {esc(e['insulation'])}, {esc(e['conductor'])} class {e['class']},
   {e['max_temp_c']:.0f} &deg;C, {e['voltage_kv']} kV.<br>{c['note']}</p>""")
    p.append(f"""<div class="warn"><strong>Neither cable carries resistance or
  reactance in the catalogue.</strong> Both fall back to IEC 60228
  <em>class 2</em> DC resistance with an AC/DC uplift, and a nominal
  0.08 &Omega;/km reactance. For the aluminium that is the right conductor
  class. For the flexible copper it is not: a class 5 conductor has more, finer
  strands and a longer lay, so its resistance is <em>higher</em> than class 2 of
  the same nominal area. Using class 2 therefore <strong>understates voltage
  drop</strong> for the flexible copper. The detail table below carries a column
  showing the drop if class 5 resistance is {100 * (CLASS5_R_UPLIFT - 1):.0f} %
  higher, so you can see whether it would change a size. Reactance is
  formation-dependent and the nominal value is not a substitute for a tabulated
  one.</div>
<div class="warn">Voltage drop is the one quantity here that is sensitive to
  those two fallbacks. Current-carrying capacity, the check that governs almost
  every row below, comes straight from published catalogue ratings and is not
  affected.</div>
</div>""")

    # ---- how it is laid out
    ref = size(CONDUCTORS[0]["key"], LENGTHS[-1], STANDARD_VD)
    bd = bundle(CONDUCTORS[0]["key"], ref.active_area_mm2, ref.parallel,
                ref.earth_area_mm2)
    ungrouped = cs.size_feeder(
        source(), load(STANDARD_VD), LENGTHS[-1],
        cs.Installation(method=METHOD, ambient_c=AMBIENT, n_circuits=N_CIRCUITS,
                        cable_type=CONDUCTORS[1]["key"],
                        max_parallel=MAX_PARALLEL,
                        parallel_runs_grouped=False), catalog=CATALOG)
    grouped = size(CONDUCTORS[1]["key"], LENGTHS[-1], STANDARD_VD)
    p.append(f"""<div class="card">
<h2>How this is laid out</h2>
<div style="display:flex;gap:22px;align-items:flex-start;flex-wrap:wrap">
  <div style="flex:0 0 240px">{tray_section_svg(CONDUCTORS[0]["key"],
      ref.active_area_mm2, ref.parallel, ref.earth_area_mm2)}</div>
  <div style="flex:1;min-width:280px">
    <p class="note" style="margin-top:0"><strong>Single-core cables laid
      touching, in one layer, on a cable tray or ladder.</strong> Unenclosed,
      at {AMBIENT:.0f} &deg;C ambient. That is AS/NZS 3008.1.1 Table 3.9,
      <em>unenclosed touching</em>, which is the rating column every number on
      this page is drawn from. Touching is the conservative assumption for a
      tray: spacing the cables by a diameter would raise the rating, and this
      does not claim that benefit.</p>
    <p class="note">A three-phase circuit with a 100 % neutral is not one cable.
      Per parallel run it is <strong>three actives and one neutral</strong>,
      and the circuit carries <strong>one earth</strong>. At
      {LENGTHS[-1]} m and the {STANDARD_VD:g} % limit the copper answer is
      {bd["actives"]} actives, {bd["neutrals"]} neutral and
      {bd["earths"]} earth &mdash; <strong>{bd["total_cores"]} cables</strong>
      side by side, {bd["mass_kg_per_m"]:.1f} kg/m on the tray, needing about
      <strong>{bd["tray_width_mm"]:.0f} mm</strong> of tray width laid touching.
      Add the tray's own fixing allowance on top.</p>
  </div>
</div>
<div class="warn"><strong>Parallel runs are counted as grouped bundles.</strong>
  Three runs touching on a tray are three bundles of loaded cores warming each
  other, so the grouping factor has to see them. The engine did not do this: it
  took the declared circuit count and ignored the run count it had chosen
  itself, which the designer cannot pre-empt because the run count is the
  answer, not the input. It now has an explicit
  <code>parallel_runs_grouped</code> option, defaulting on, which jCalc's
  AS/NZS 3008 documentation confirms is the standard's own reading: the number
  of circuits "includes parallel cables in this circuit ... And the standard
  treats parallel cables as multiple circuits."
  <br><br>It changes answers. The aluminium at {LENGTHS[-1]} m and
  {STANDARD_VD:g} % moves from
  <strong>{3 * ungrouped.parallel} &times; {ungrouped.active_area_mm2:g} mm&sup2;</strong>
  ungrouped to
  <strong>{3 * grouped.parallel} &times; {grouped.active_area_mm2:g} mm&sup2;</strong>
  grouped, because the grouping factor drops from
  {ungrouped.grouping_factor:.3f} to {grouped.grouping_factor:.3f}. The copper
  is unaffected at this budget.
  <br><br>Applying it also removed a known divergence elsewhere: the published
  worked example in the validation set selects 3 &times; 630 mm&sup2;, and the
  engine used to answer 3 &times; 500 and call it a cheaper valid alternative.
  With parallel runs grouped, 3 &times; 500 reads 3.25 % against a 3.2 % limit
  and is rejected, so the engine now reproduces the published size. That is
  corroboration rather than proof, since the paper's own capacity figure of
  2460 A is ungrouped. One caveat stands: the grouping table here comes from
  the catalogue and is <strong>not</strong> verified against the printed
  standard, so the correction factor tables in AS/NZS 3008.1 remain the
  arbiter.</div>
</div>

<div class="card">
<h2>Selected size against route length and voltage drop budget</h2>
<p class="note">Each cell is <em>number of active conductors &times;
   mm&sup2;</em> &mdash; three actives per parallel run, since this is a
   three-phase circuit &mdash; and the smallest that passes current capacity,
   voltage drop, short-circuit withstand and the AS/NZS 3000 minimum size. The
   neutral matches the active throughout, as a 100 % neutral requires, and is
   additional to the actives shown. The figure under each is the whole bundle's
   mass per metre of route: actives, neutral and earth.</p>""")
    for c in CONDUCTORS:
        cls = "cu" if "copper" in c["label"].lower() else "al"
        p.append(f'<h3 class="{cls}">{esc(c["label"])}</h3>'
                 '<div class="scroll"><table class="viz">'
                 '<thead><tr><th class="num">Route</th>')
        for b in VD_BUDGETS:
            star = " *" if b == STANDARD_VD else ""
            p.append(f'<th class="num">{b:g} %{star}</th>')
        p.append('</tr></thead><tbody>')
        for length, cells in matrix_rows(c["key"]):
            p.append(f'<tr><td class="num">{length} m</td>')
            for cell in cells:
                if cell is None:
                    p.append('<td class="num">&mdash;</td>')
                    continue
                bd = cell["bundle"]
                dz = dot_class(cell["od"])
                dots = f'<span class="dot {dz}"></span>' * bd["actives"]
                tip = (
                    f'{bd["actives"]} active + {bd["neutrals"]} neutral + '
                    f'{bd["earths"]} earth = {bd["total_cores"]} cables. '
                    f'{cell["runs"]} run(s) per phase of {cell["area"]:g} mm2, '
                    f'{cell["total"]:g} mm2 per phase. '
                    f'OD {cell["od"]:.1f} mm each. '
                    f'{bd["mass_kg_per_m"]:.1f} kg/m on the tray, '
                    f'{bd["tray_width_mm"]:.0f} mm of tray width touching. '
                    f'{cell["budget"]:g}% budget, {cell["vd_pct"]:.2f}% actual. '
                    f'Derated capacity {cell["capacity"]:.0f} A.')
                p.append(
                    f'<td class="c num {cell["band"]}" title="{esc(tip)}">'
                    f'<span class="cell">'
                    f'<span class="lbl">{cell["label"]}</span>'
                    f'<span class="runs">{esc(cell["runs_note"])} &middot; '
                    f'{bd["mass_kg_per_m"]:.1f} kg/m</span>'
                    f'<span class="dots">{dots}</span></span></td>')
            p.append('</tr>')
        p.append('</tbody></table></div>')
    sw = "".join(
        f'<span class="sw s{i + 1}"><i></i>{esc(label)}</span>'
        for i, (_, _, label) in enumerate(SIZE_BANDS))
    lo, hi = od_span()
    p.append(f"""<div class="swatches">
  <span style="color:var(--ink);font-weight:600">Total mm&sup2; per phase</span>
  {sw}</div>
<div class="swatches">
  <span style="color:var(--ink);font-weight:600">Circles</span>
  <span>one per active conductor, drawn to the cable's real outside diameter</span>
  <span class="sizedemo">
    <i style="width:{circle_px(lo):.0f}px;height:{circle_px(lo):.0f}px"></i>
    <i style="width:{circle_px((lo + hi) / 2):.0f}px;height:{circle_px((lo + hi) / 2):.0f}px"></i>
    <i style="width:{circle_px(hi):.0f}px;height:{circle_px(hi):.0f}px"></i>
  </span>
  <span>{lo:.1f} to {hi:.1f} mm</span></div>
<p class="note">Count, circle size and fill all carry the escalation, so it
   reads three ways over. The number beside each cell is
   <em>actives &times; mm&sup2;</em> &mdash; three actives per parallel run,
   because this is a three-phase circuit &mdash; with the tray load per metre
   beneath it. Hover any cell for the full bundle, tray width and actual drop.</p>
<div class="legend">
  <span>* {STANDARD_VD:g} % is the AS/NZS 3000 clause 3.6.2 limit for the whole
    installation.</span>
  <span>0.5&ndash;2 % are the design budgets normally allotted to consumers
    mains and submains.</span></div>
<p class="note">At the full {STANDARD_VD:g} % limit the size does not change
   with length at all: current-carrying capacity governs every row, and 50 m is
   far too short for voltage drop to bind at this current. Length only starts to
   drive the size once the budget is squeezed to about 1 %, which is where a real
   submain allocation usually sits. That is the useful reading of this table.</p>
</div>""")

    # ---- detail at the standard limit
    p.append(f"""<div class="card">
<h2>Detail at the {STANDARD_VD:g} % limit</h2>
<p class="note">Mass is the whole route: three phases plus neutral, times the
   number of runs, plus one earth. It is the one column where the aluminium wins
   outright: two runs of aluminium come in lighter than one run of copper, so
   the tray carries less even though there is twice as much cable on it.</p>
<p class="note"><strong>Tray selection is real product, not a rule of thumb.</strong>
   The smallest {TRAY_FAMILY} width that takes the cables side by side with
   {ezystrut.SIDE_CLEARANCE_MM:.0f} mm clearance each side, from the Ezystrut
   range in <code>../cable-tray-ezystrut/</code>, with the load check against
   the published rating at a {TRAY_SPAN_MM / 1000:g} m support span and
   including the tray's own weight. {TRAY_FAMILY} is what that component's
   guidelines recommend for power runs. The 50 % fill rule in those same
   guidelines is deliberately <em>not</em> applied: it is for bunched cables
   filling a tray's depth, and these are a single layer touching, which is the
   arrangement the AS/NZS 3008 rating assumes. Applying it would widen the tray
   for no thermal reason and contradict the rating the cable was sized on.</p>""")
    for c in CONDUCTORS:
        cls = "cu" if "copper" in c["label"].lower() else "al"
        rows = detail_rows(c["key"])
        p.append(f'<h3 class="{cls}">{esc(c["label"])}</h3><div class="scroll">'
                 '<table><thead><tr>'
                 '<th class="num">Route</th><th class="num">Actives</th>'
                 '<th class="num">Neutral</th><th class="num">Earth</th>'
                 '<th class="num">Cables</th>'
                 '<th class="num">Mass on tray</th><th class="num">Cables span</th>'
                 '<th>Ezystrut tray</th><th class="num">Tray loaded</th>'
                 '<th class="num">Capacity</th><th class="num">Used</th>'
                 '<th class="num">V drop</th><th class="num">%</th>'
                 '<th class="num">% at cl.5 R</th><th class="num">Cond. temp</th>'
                 '<th>Governed by</th></tr></thead><tbody>')
        for r in rows:
            if r["failed"]:
                p.append(f'<tr><td class="num">{r["length"]} m</td>'
                         f'<td colspan="15">{esc(r["failed"])}</td></tr>')
                continue
            head = 100.0 * r["op_temp"] / r["max_temp"]
            tcls = "hot" if head >= 97 else ("tight" if head >= 90 else "")
            ucls = "tight" if r["utilisation"] >= 95 else ""
            bd = r["bundle"]
            p.append(
                f'<tr><td class="num">{r["length"]} m</td>'
                f'<td class="num">{bd["actives"]} &times; {r["active"]:g}</td>'
                f'<td class="num">{bd["neutrals"]} &times; {r["neutral"]:g}</td>'
                f'<td class="num">1 &times; {r["earth"]:g}</td>'
                f'<td class="num">{bd["total_cores"]}</td>'
                f'<td class="num"><strong>{bd["mass_kg_per_m"]:.1f}</strong> kg/m</td>'
                f'<td class="num">{bd["tray_width_mm"]:.0f} mm</td>'
                f'<td>{tray_cell(r["tray"])}</td>'
                f'<td class="num {tray_class(r["tray"])}">{tray_load(r["tray"])}</td>'
                f'<td class="num">{r["capacity"]:.0f} A</td>'
                f'<td class="num {ucls}">{r["utilisation"]:.0f} %</td>'
                f'<td class="num">{r["vd_v"]:.2f} V</td>'
                f'<td class="num">{r["vd_pct"]:.2f}</td>'
                f'<td class="num">{r["vd_pct_c5"]:.2f}</td>'
                f'<td class="num {tcls}">{r["op_temp"]:.0f} / {r["max_temp"]:.0f} &deg;C</td>'
                f'<td>{esc(r["bind"])} <span class="note">'
                f'{r["bind_margin"]:+.1f} %</span></td></tr>')
        p.append('</tbody></table></div>')
        warm = [r for r in rows if not r["failed"]
                and 100.0 * r["op_temp"] / r["max_temp"] >= 93]
        hot = [r for r in warm
               if 100.0 * r["op_temp"] / r["max_temp"] >= 97]
        if warm and not hot:
            r = warm[0]
            p.append(f"""<div class="warn"><strong>Little thermal headroom.</strong>
  {r["runs"] * 3} &times; {r["active"]:g} mm&sup2; carries {AMPS:.0f} A against
  {r["capacity"]:.0f} A, which is {r["utilisation"]:.0f} % utilisation, so the
  conductor settles at {r["op_temp"]:.0f} &deg;C against a
  {r["max_temp"]:.0f} &deg;C limit &mdash; about
  {r["max_temp"] - r["op_temp"]:.0f} &deg;C of margin. This is the size both
  ELEK and jCalc select for the same inputs, so it is the standard's own answer
  rather than an aggressive one. Worth knowing all the same: a continuously
  loaded feeder at 95 % of rating has little left for a hot spot, a poor
  termination or load growth.</div>""")
        if hot:
            r = hot[0]
            p.append(f"""<div class="err"><strong>Running at the insulation
  limit.</strong> {r["runs"]} &times; {r["active"]:g} mm&sup2; carries
  {AMPS:.0f} A against a derated capacity of {r["capacity"]:.0f} A, which is
  {r["utilisation"]:.0f} % utilisation, so the conductor settles at
  {r["op_temp"]:.0f} &deg;C against a {r["max_temp"]:.0f} &deg;C limit. It
  passes, on a margin of {r["bind_margin"]:+.1f} %. Whether you would issue it
  is a different question: continuous operation within a couple of degrees of
  the insulation rating leaves nothing for a hot spot, a dirty termination or a
  future load increase, and accelerates ageing. Going up one size, or to two
  runs, buys the headroom cheaply.</div>""")
    p.append('</div>')
    return p


TX_NO_LOAD_V = 433.0
TX_CASES = ((4.5, 1.10), (5.0, 1.15), (5.75, 1.20), (6.0, 1.25))
# Design allocation recommended below, as a percentage of nominal.
ALLOCATION = (
    ("Transformer LV terminals to main switchboard", 0.5,
     "Short, and usually busway or a very large cable, so it is cheap to keep "
     "tight."),
    ("Main switchboard to sub-board or PDU (submain)", 2.0,
     "The 800 A feeder in this schedule. 1 &times; 300 mm&sup2; flexible copper "
     "holds this to 50 m."),
    ("Final subcircuit", 2.0,
     "Whatever the downstream board feeds."),
)


def tx_regulation(pct_z, pct_r, load_pu, pf=POWER_FACTOR):
    """Approximate transformer voltage regulation, per unit.

    reg ~ load x (%R cos(phi) + %X sin(phi)), with %X from %Z and %R. Good
    enough to set a budget; the nameplate and tap position settle the real
    figure.
    """
    pct_x = math.sqrt(max(pct_z ** 2 - pct_r ** 2, 0.0))
    return load_pu * (pct_r * pf + pct_x * math.sin(math.acos(pf))) / 100.0


def voltage_budget_card(p):
    v_pn_nl = TX_NO_LOAD_V / math.sqrt(3)
    worst = max(tx_regulation(z, r, 1.0) for z, r in TX_CASES)
    board_full = TX_NO_LOAD_V * (1 - worst)
    best = min(tx_regulation(z, r, 0.25) for z, r in TX_CASES)
    board_light = TX_NO_LOAD_V * (1 - best)
    alloc_total = sum(a for _, a, _ in ALLOCATION)

    p.append(f"""<div class="card"><h2>How much voltage drop to accept, from a
  {TX_NO_LOAD_V:.0f} V transformer</h2>
<p class="note">Two separate questions get run together here, and only one of
   them is the law.</p>

<h3>1. The compliance limit, and why {TX_NO_LOAD_V:.0f} V does not raise it</h3>
<p class="note">AS/NZS 3000 clause 3.6.2 caps the drop between the point of
   supply and <em>any</em> point in the installation at <strong>5 %</strong>,
   rising to <strong>7 %</strong> where the point of supply is the LV terminals
   of a substation on the premises and dedicated to it. Those figures are
   verified against the printed standard in this repo. If the transformer is
   yours and on site, <strong>7 % is your ceiling</strong>, not 5 %.</p>
<p class="note">But the percentage is of the <strong>nominal</strong> voltage of
   the point of supply, not of the {TX_NO_LOAD_V:.0f} V tap. So the tap buys you
   nothing on compliance:</p>
<div class="scroll"><table><thead><tr><th>Nominal</th>
  <th class="num">5 % limit</th><th class="num">7 % limit</th></tr></thead><tbody>
  <tr><td>400 V (AS 60038 nominal)</td><td class="num">20.0 V</td>
    <td class="num">28.0 V</td></tr>
  <tr><td>415 V (if that is what you declare)</td><td class="num">20.8 V</td>
    <td class="num">29.1 V</td></tr>
</tbody></table></div>

<h3>2. What the tap does buy: real volts at the load</h3>
<p class="note">{TX_NO_LOAD_V:.0f} V no-load is
   {100 * (TX_NO_LOAD_V / 400 - 1):+.2f} % against 400 V nominal and
   {100 * (TX_NO_LOAD_V / 415 - 1):+.2f} % against 415 V. Subtract the
   transformer's own regulation and the board sits here:</p>
<div class="scroll"><table><thead><tr><th class="num">%Z</th>
  <th class="num">25 % load</th><th class="num">50 %</th><th class="num">75 %</th>
  <th class="num">100 %</th></tr></thead><tbody>""")
    for z, r in TX_CASES:
        row = f'<tr><td class="num">{z:.2f}</td>'
        for load in (0.25, 0.5, 0.75, 1.0):
            row += (f'<td class="num">'
                    f'{TX_NO_LOAD_V * (1 - tx_regulation(z, r, load)):.1f} V</td>')
        p.append(row + '</tr>')
    p.append(f"""</tbody></table></div>
<p class="note">At pf {POWER_FACTOR}. Worst case, a {TX_CASES[-1][0]:.0f} % Z unit
   at full load, puts <strong>{board_full:.1f} V</strong> at the board. Spend the
   whole 7 % from there and the far end still sees
   {board_full - 400 * 0.07:.1f} V, which is above 400 V &minus; 6 % and well
   above a &minus;10 % equipment tolerance. <strong>Steady-state undervoltage is
   not your binding constraint.</strong></p>

<div class="warn"><strong>3. The constraint nobody budgets for: overvoltage at
  light load.</strong> At 25 % load the board sits at about
  {board_light:.0f} V line-line, {board_light / math.sqrt(3):.1f} V
  phase-neutral. At no load it is {v_pn_nl:.1f} V. Against a 230 V nominal with
  AS 60038's +10 % allowance of 253 V that leaves only
  {253 - v_pn_nl:.1f} V of headroom. A data centre spends much of its life below
  half load, so this is the live case, not a corner. It has two consequences
  worth stating plainly: a <em>small</em> voltage drop is helping you here, so
  chasing drop down to 0.5 % is counterproductive; and the transformer tap wants
  checking against light-load conditions, not just full load. The +10 % / &minus;6 %
  figures are AS 60038 and are <strong>not</strong> among this repo's verified
  tables, so confirm them before relying on them.</div>

<h3>The answer</h3>
<p class="note">Design to about <strong>{alloc_total:g} %</strong> total and
   hold the 7 % as headroom rather than as a target. Suggested split:</p>
<div class="scroll"><table><thead><tr><th>Segment</th>
  <th class="num">Allow</th><th>Why</th></tr></thead><tbody>""")
    for name, pct, why in ALLOCATION:
        p.append(f'<tr><td>{name}</td><td class="num">{pct:g} %</td>'
                 f'<td class="note" style="margin:0">{why}</td></tr>')
    p.append(f"""<tr><td><strong>Total</strong></td>
  <td class="num"><strong>{alloc_total:g} %</strong></td>
  <td class="note" style="margin:0">Leaves
    {7 - alloc_total:g} % of the 7 % ceiling for load growth, tap changes,
    unbalance and the segments nobody drew yet.</td></tr>
</tbody></table></div>
<p class="note">For <strong>this</strong> feeder that means the
   <strong>2 % column</strong> above is the one to read, not 5 % and not 0.5 %.
   In flexible copper that is 1 &times; 300 mm&sup2; at every length to 50 m; in
   aluminium, 2 &times; 300 mm&sup2;. Both are unchanged from the 5 % column, so
   the tighter budget costs nothing here &mdash; which is the useful result.</p>
<p class="note">Two things that would change this answer. If motor starting dips
   matter (chillers, large pumps), the transient dip at the board can govern and
   it is not modelled here at all. And if the copper is taken at
   1 &times; 300 mm&sup2; it runs at 108 &deg;C, so the thermal case pushes you
   to two runs or a larger size anyway &mdash; at which point the voltage drop
   headroom comes free.</p>
</div>""")


def render_tail():
    p = []
    voltage_budget_card(p)
    fams = tricab_flexible_al()
    al = size("XLPE_SDI_AL", LENGTHS[-1], STANDARD_VD)
    earth_al = al.earth_area_mm2 if al.passed else 0
    p.append('<div class="card"><h2>Getting the aluminium right</h2>')
    if fams:
        p.append(f"""<p class="note">The brief asked for flexible aluminium with a
  high-temperature sheath and the catalogue has none, so the aluminium column
  above is a 90 &deg;C class 2 stand-in. Tricab publish
  {len(fams)} flexible aluminium famil{"y" if len(fams) == 1 else "ies"} above
  90 &deg;C, but <strong>no per-size electrical data</strong>: current ratings,
  resistance, reactance, diameter and mass are all behind a trade login. So
  these are construction candidates to get real ratings for, not a source of
  numbers.</p><div class="scroll"><table><thead><tr><th>Code</th>
  <th>Construction</th><th>Voltage</th><th class="num">Temp</th>
  </tr></thead><tbody>""")
        for f in fams:
            code = esc(f["code"] or "?")
            link = (f'<a href="{esc(f["url"])}" target="_blank" '
                    f'rel="noopener">{code}</a>' if f["url"] else code)
            p.append(f'<tr><td>{link}</td><td>{esc(f["construction"] or "")}</td>'
                     f'<td>{esc(f["voltage"] or "")}</td>'
                     f'<td class="num">{f["temp"]} &deg;C</td></tr>')
        p.append('</tbody></table></div>')
    else:
        p.append('<p class="note">No flexible aluminium family above 90 &deg;C '
                 'in the captured Tricab set.</p>')
    p.append(f"""<p class="note">Once you have a real rating, the size can be
  confirmed without waiting on a catalogue rebuild. Both the REST API and the
  MCP server take a tabulated rating and check a nominated size against it:</p>
<pre style="overflow-x:auto"><code>curl -sS -X POST localhost:8765/api/check \\
  -H 'Content-Type: application/json' \\
  -d '{{"standard":"AS3008","method":"touching","area_mm2":300,
       "tabulated_rating_a":&lt;from the datasheet&gt;,
       "rating_value":800,"rating_kind":"amps","voltage_v":415,
       "route_length_m":50,"ambient_c":40,"power_factor":0.9}}'</code></pre>
</div>

<div class="card"><h2>Three things this table does not cover</h2>
<p class="note"><strong>Harmonics.</strong> A 100 % neutral was specified, and
   that is what is sized: the neutral matches the active on every row. That is
   correct for a balanced or intermittently unbalanced load. It is
   <em>not</em> sufficient where third-and-higher-order harmonic current runs at
   or above 40 % of phase current, which IT loads, VSDs and switch-mode supplies
   routinely do. There the neutral carries more than the phases and AS/NZS 3000
   clause 3.5.2 requires it larger than the active, not equal to it. If this
   feeder serves that kind of load, say so and it can be re-sized.</p>
<p class="note"><strong>Protective device coordination.</strong> No device was
   declared, so the earth fault loop impedance check did not run, and this
   engine does not implement the AS/NZS 3000 zone A/B/C coordination rules at
   all. See <code>REVIEW-ELEK.md</code> finding 5. A cable can pass every check
   above and still be improperly protected.</p>
<p class="note"><strong>Whether an aluminium earth is permitted where this route
   runs.</strong> The aluminium rows carry an aluminium earth conductor, and
   AS/NZS 3000 clause 5.3.2.1.2 puts conditions on that: solid conductors at or
   below 10 mm&sup2;, a 16 mm&sup2; floor for a main earthing conductor, no more
   than three connections per section, corrosion to be prevented, and
   <strong>not permitted underground or in damp situations</strong> unless
   designed and suitable for it. This repo holds that clause verified against
   the printed standard in <code>as3008.check_aluminium_earth</code>, but
   <code>size_feeder</code> does not call it, so nothing above enforces it. At
   {earth_al:g} mm&sup2; in air the check returns no objection; if any part of
   this route is buried or damp, it does. Worth wiring into the engine rather
   than remembering.</p>
</div>

<footer>Sizes from <code>cable_sizing.size_feeder</code> against
  <code>{esc(CATALOG.get("source", ""))}</code>. Regenerate with
  <code>python3 build_800a_table.py</code>. Provenance for every quantity is in
  <code>README.md</code>; the unverified reference tables are listed by
  <code>as3008.unverified_tables()</code>.</footer>
</div></body></html>""")
    return p


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("-o", "--out", default="out/800A-feeder-schedule.html")
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out) or ".", exist_ok=True)
    doc = "\n".join(render() + render_tail())
    # Circle sizes are only known once every cell has been built, so the rules
    # are appended to the stylesheet after the fact.
    doc = doc.replace("</style>", dot_css() + "</style>", 1)
    with open(a.out, "w", encoding="utf-8") as fh:
        fh.write(doc)
    print(f"wrote {a.out}  ({len(doc) / 1024:.0f} KiB)")
    return a.out


if __name__ == "__main__":
    main()
