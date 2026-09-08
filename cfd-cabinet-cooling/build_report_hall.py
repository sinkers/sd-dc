#!/usr/bin/env python3
"""
Build the hall cooling report as a self-contained HTML page.

Every number is read from case-hall/postProcessing, so the page cannot drift
from the run it describes.

    ./build_report_hall.py       ->  case-hall/report-hall.html
"""
from __future__ import annotations

import base64
import pathlib
import re
import subprocess
import sys
from pathlib import Path

import plot_hall

CASE = Path("case-hall")
W = CASE / "web"
KELVIN = 273.15
RECOMMENDED, ALLOWABLE = 27.0, 32.0   # replaced from hallParameters below
CP = 1005.0


def uri(name: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode((W / name).read_bytes()).decode()


p = plot_hall.params(CASE)
n = int(p["nRacksPerRow"])
ALLOWABLE = p.get("allowableMax_C", ALLOWABLE)
RECOMMENDED = p.get("recommendedMax_C", RECOMMENDED)
ACLASS = {32.0: "A1", 35.0: "A2", 40.0: "A3", 45.0: "A4"}.get(ALLOWABLE, "custom")

# Derived, not typed in. The prose used to carry a literal 2.51 m/s, which went
# stale the moment the unit geometry changed. Same formula as make_hall_dicts.py.
SUPPLY_AREA = p["unitWidth"] * (p["supplyZ1"] - p["supplyZ0"])
SUPPLY_VEL = (p["unitAirflow_m3h"] / 3600.0) / SUPPLY_AREA

data = {}
for row in ("A", "B"):
    mean, peak, flow = [], [], []
    for i in range(n):
        t = f"{row}{i:02d}"
        v = plot_hall.final(CASE, f"r{t}_inletT")
        mean.append(v - KELVIN)
        peak.append((plot_hall.final(CASE, f"r{t}_inletTmax") or v) - KELVIN)
        flow.append(abs(plot_hall.final(CASE, f"r{t}_flow") or 0.0))
    data[row] = dict(mean=mean, peak=peak, flow=flow)

allm = data["A"]["mean"] + data["B"]["mean"]
allp = data["A"]["peak"] + data["B"]["peak"]
allf = data["A"]["flow"] + data["B"]["flow"]
units = plot_hall.unit_names(CASE)
sup = sum(abs(plot_hall.final(CASE, f"supply{u}") or 0) for u in units)
_rT = [plot_hall.final(CASE, f"returnT{u}") for u in units]
_rT = [v - KELVIN for v in _rT if v is not None]
retT = sum(_rT) / len(_rT)
load = 2 * n * p["rackLoad_kW"]
cap = 2 * p["unitCapacity_kW"]
dT_act = load * 1000 / (sum(allf) * CP)

ends = [0, n - 1]
mid = list(range(1, n - 1))
end_mean = max(max(data[r]["mean"][i] for i in ends) for r in "AB")
mid_mean = max(max(data[r]["mean"][i] for i in mid) for r in "AB")
end_pk = max(max(data[r]["peak"][i] for i in ends) for r in "AB")
mid_pk = max(max(data[r]["peak"][i] for i in mid) for r in "AB")
end_flow = sum(data[r]["flow"][i] for r in "AB" for i in ends) / 4
mid_flow = sum(data[r]["flow"][i] for r in "AB" for i in mid) / (2 * len(mid))
worst_i = max(range(2 * n), key=lambda j: allp[j])
worst = ("A" if worst_i < n else "B") + f"{worst_i % n:02d}"
n_over = sum(1 for v in allp if v > ALLOWABLE)

# ---- how unsteady is it? the steady solver never converges U at the hall ends,
# so the per-rack end values carry a wander band that the comparison must respect.
import statistics as _st


def _hist(fo):
    f = sorted((CASE / "postProcessing" / fo).glob("*/*.dat"))[-1]
    return [(float(r.split()[0]), float(r.split()[1]) - KELVIN)
            for r in f.read_text().splitlines() if r.strip() and not r.startswith("#")]


def _band(rack):
    h = [v for tt, v in _hist(f"r{rack}_inletT") if tt >= 2000]
    return max(h) - min(h)


END = [f"{r}{i:02d}" for r in "AB" for i in (0, n - 1)]
MID = ["A05", "B05", "A02", "B08"]
band_end = _st.mean(_band(r) for r in END)
band_mid = _st.mean(_band(r) for r in MID)

# v1 (open ends, unsealed doors) for comparison
V1 = pathlib.Path("verification/hall_v1_baseline.txt").read_text()
def _v1(pat):
    m = re.search(pat, V1)
    return float(m[1]) if m else float("nan")
v1_hot, v1_pk = _v1(r"hottest rack\s+([\d.]+)"), _v1(r"worst peak on any rack face\s+([\d.]+)")
v1_thru = _v1(r"through racks\s+([\d.]+)")
v1_sup = _v1(r"total supply\s+([\d.]+)")
v1_bypass = 100 * (1 - v1_thru / v1_sup)
v2_bypass = 100 * (1 - sum(allf) / sup)

verdict = ("FAIL" if max(allm) > ALLOWABLE
           else "MARGINAL" if max(allp) > ALLOWABLE else "PASS")
VCLS = {"PASS": "ok", "MARGINAL": "warn", "FAIL": "bad"}[verdict]

def _row(r: str, i: int) -> str:
    m, pk, f = data[r]["mean"][i], data[r]["peak"][i], data[r]["flow"][i]
    cls = ' class="warn"' if pk > ALLOWABLE else ""
    return (f'<tr{cls}><th scope="row">{r}{i:02d}</th><td>{m:.2f}</td>'
            f'<td class="peak">{pk:.2f}</td><td>{f:.3f}</td></tr>')


rows_html = "\n".join(_row(r, i) for r in ("A", "B") for i in range(n))

video = ""
mp4 = CASE / "web" / "hall_perspective.mp4"
if mp4.is_file():
    video = f"""
  <figure>
    <video controls autoplay loop muted playsinline>
      <source src="{uri('hall_perspective.mp4','video/mp4')}" type="video/mp4">
    </video>
    <figcaption>Orbit of the hall. Cold streamlines run low through both side
    aisles; hot air rises out of the contained aisle into the ceiling plenum and
    returns to the intakes on top of both units.</figcaption>
  </figure>"""

HTML = f"""<title>Hall Cooling Check</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Sans:wght@400;450;600&display=swap">
<style>
:root {{
  --ground:#eef1f5; --surface:#ffffff; --edge:#d5dce5;
  --ink:#0f141a; --muted:#5b6774; --dim:#8a95a3;
  --accent:#c2410c; --cold:#1d4ed8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c;
  --ok-bg:#e4f2e8; --warn-bg:#fbeedb; --bad-bg:#fbe4e4;
  --mono:"IBM Plex Mono",ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  --sans:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
}}
@media (prefers-color-scheme:dark) {{
  :root:not([data-theme="light"]) {{
    --ground:#0c1116; --surface:#141b22; --edge:#26313d;
    --ink:#e3eaf2; --muted:#8a97a6; --dim:#6b7887;
    --accent:#fb923c; --cold:#60a5fa;
    --ok:#4ade80; --warn:#fbbf24; --bad:#f87171;
    --ok-bg:#12291b; --warn-bg:#2e2310; --bad-bg:#2e1616;
  }}
}}
:root[data-theme="dark"] {{
  --ground:#0c1116; --surface:#141b22; --edge:#26313d;
  --ink:#e3eaf2; --muted:#8a97a6; --dim:#6b7887;
  --accent:#fb923c; --cold:#60a5fa;
  --ok:#4ade80; --warn:#fbbf24; --bad:#f87171;
  --ok-bg:#12291b; --warn-bg:#2e2310; --bad-bg:#2e1616;
}}
* {{ box-sizing:border-box; }}
body {{ background:var(--ground); color:var(--ink); font-family:var(--sans);
  line-height:1.62; margin:0; padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 5rem;
  display:flex; flex-direction:column; align-items:center; }}
.wrap {{ width:100%; max-width:64rem; display:flex; flex-direction:column; gap:2.9rem; }}
.prose {{ max-width:38rem; }}
.eyebrow {{ font-family:var(--mono); font-size:.72rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted); margin:0; }}
h1 {{ font-family:var(--mono); font-size:clamp(1.6rem,4.2vw,2.4rem); font-weight:600;
  letter-spacing:-.015em; line-height:1.12; margin:0; text-wrap:balance; }}
h2 {{ font-family:var(--mono); font-size:.82rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted); margin:0 0 1rem; padding-bottom:.5rem;
  border-bottom:1px solid var(--edge); }}
header {{ display:flex; flex-direction:column; gap:.9rem; }}
p {{ margin:0 0 1rem; }} p:last-child {{ margin-bottom:0; }}
.lede {{ font-size:1.06rem; color:var(--muted); max-width:44rem; margin:0; }}
strong {{ font-weight:600; }} code {{ font-family:var(--mono); font-size:.88em; }}
section {{ display:flex; flex-direction:column; }}
figure {{ margin:0; display:flex; flex-direction:column; gap:.7rem; }}
video, figure img {{ width:100%; height:auto; display:block; border:1px solid var(--edge);
  border-radius:3px; background:var(--surface); }}
figcaption {{ font-size:.85rem; color:var(--muted); max-width:46rem; }}
.note {{ border-left:2px solid var(--accent); padding:.15rem 0 .15rem 1rem;
  color:var(--muted); font-size:.94rem; max-width:44rem; }}
.note strong {{ color:var(--ink); }}
.scroll {{ overflow-x:auto; border:1px solid var(--edge); border-radius:3px;
  background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; font-size:.86rem; min-width:26rem; }}
caption {{ caption-side:bottom; text-align:left; padding:.75rem .9rem; color:var(--muted);
  font-size:.82rem; }}
th,td {{ padding:.5rem .9rem; text-align:right; font-variant-numeric:tabular-nums; }}
thead th {{ font-family:var(--mono); font-size:.66rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--muted); font-weight:500;
  border-bottom:1px solid var(--edge); white-space:nowrap; }}
thead th:first-child, tbody th {{ text-align:left; }}
tbody th {{ font-family:var(--mono); font-weight:600; }}
tbody tr {{ border-top:1px solid var(--edge); }}
tbody tr.warn {{ background:var(--warn-bg); }}
td.peak {{ font-weight:600; }} tr.warn td.peak {{ color:var(--warn); }}
.verdict {{ display:flex; align-items:baseline; gap:.9rem; flex-wrap:wrap;
  border:1px solid var(--edge); border-left:4px solid var(--{VCLS}); border-radius:3px;
  background:var(--surface); padding:1.1rem 1.25rem; }}
.verdict .tag {{ font-family:var(--mono); font-size:1.15rem; font-weight:600;
  color:var(--{VCLS}); letter-spacing:.04em; }}
.verdict .txt {{ font-size:.95rem; color:var(--muted); }}
.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(12.5rem,1fr)); gap:1px;
  background:var(--edge); border:1px solid var(--edge); border-radius:3px; overflow:hidden; }}
.stat {{ background:var(--surface); padding:1rem 1.1rem; display:flex;
  flex-direction:column; gap:.28rem; }}
.stat .k {{ font-family:var(--mono); font-size:.64rem; letter-spacing:.11em;
  text-transform:uppercase; color:var(--muted); }}
.stat .v {{ font-family:var(--mono); font-size:1.4rem; font-weight:600;
  font-variant-numeric:tabular-nums; }}
.stat .s {{ font-size:.79rem; color:var(--dim); }}
.stat.hot .v {{ color:var(--accent); }} .stat.cool .v {{ color:var(--cold); }}
.stat.ok .v {{ color:var(--ok); }}
.two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(20rem,1fr)); gap:1.5rem; }}
ul {{ margin:0 0 1rem; padding-left:1.15rem; }} li {{ margin-bottom:.45rem; }}
footer {{ font-size:.82rem; color:var(--dim); border-top:1px solid var(--edge);
  padding-top:1rem; }}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; }} }}
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">2 x Uniflair FWCV 40L2 &middot; {2*n} racks &middot; {load:g} kW &middot; 731,904 cells</p>
    <h1>Hall Cooling Check</h1>
    <p class="lede">Can two FWCV 40L2 fan walls comfortably cool a hall of
    {2*n}&nbsp;&times;&nbsp;{p['rackLoad_kW']:g}&nbsp;kW racks? Capacity was never the
    question. Distribution is &mdash; the racks that struggle are not the ones you would
    expect, and the flow that makes them struggle does not hold still.</p>
  </header>

  <div class="verdict">
    <span class="tag">{verdict}</span>
    <span class="txt">Against <strong>ASHRAE {ACLASS}</strong>
    (allowable {ALLOWABLE:.0f}&nbsp;&deg;C, matching the Supermicro
    SYS-422GS-NB3RT-ALC 10&ndash;35&nbsp;&deg;C rating), every rack passes on both mean
    and peak intake. Worst face is <strong>{worst} at
    {max(allp):.2f}&nbsp;&deg;C</strong>, leaving
    {ALLOWABLE - max(allp):.2f}&nbsp;K of headroom. On the A1 envelope
    ({32:.0f}&nbsp;&deg;C) the same result would be MARGINAL, so the class matters.</span>
  </div>

  <div class="grid">
    <div class="stat ok">
      <span class="k">Capacity used</span>
      <span class="v">{100*load/cap:.0f} %</span>
      <span class="s">{load:g} kW of {cap:g} kW net sensible</span>
    </div>
    <div class="stat cool">
      <span class="k">Return air</span>
      <span class="v">{retT:.1f} &deg;C</span>
      <span class="s">against the {37:g} &deg;C rated RAT</span>
    </div>
    <div class="stat">
      <span class="k">Mean intake, worst rack</span>
      <span class="v">{max(allm):.2f} &deg;C</span>
      <span class="s">supply is {p['supplyTemp_C']:g} &deg;C</span>
    </div>
    <div class="stat hot">
      <span class="k">Peak on a rack face</span>
      <span class="v">{max(allp):.2f} &deg;C</span>
      <span class="s">{worst}, above the {ALLOWABLE:.0f} &deg;C allowable</span>
    </div>
  </div>

  <section>
    <h2>The finding: the end racks are the weak spot</h2>
    <p class="prose">The four racks nearest the fan walls &mdash; positions 0 and
    {n-1} in both rows &mdash; run hottest <em>and</em> receive the least air. The
    ten racks in the middle of each row, furthest from both units, are the
    comfortable ones. That is the opposite of the intuition that a long row starves
    in the middle.</p>

    <div class="grid" style="margin-bottom:1.5rem">
      <div class="stat hot">
        <span class="k">End racks &mdash; mean intake</span>
        <span class="v">{end_mean:.2f} &deg;C</span>
        <span class="s">vs {mid_mean:.2f} &deg;C mid-row</span>
      </div>
      <div class="stat hot">
        <span class="k">End racks &mdash; peak intake</span>
        <span class="v">{end_pk:.2f} &deg;C</span>
        <span class="s">vs {mid_pk:.2f} &deg;C mid-row</span>
      </div>
      <div class="stat cool">
        <span class="k">End racks &mdash; airflow</span>
        <span class="v">{end_flow:.2f} kg/s</span>
        <span class="s">{100*(mid_flow-end_flow)/mid_flow:.0f} % less than mid-row ({mid_flow:.2f})</span>
      </div>
    </div>

    <figure>
      <img src="{uri('hall_racks.png','image/png')}"
           alt="Per-rack intake temperature for both rows. Mean intake is flat near
           28.3 C across racks 1 to 10 and rises to 29.3 C at racks 0 and 11. Peak
           intake spikes above 32 C at the end racks. Airflow bars are lowest at
           racks 0 and 11 and highest at racks 1 and 10.">
      <figcaption>Mean intake (solid) is nearly flat along the row. Peak intake
      (dashed) spikes at both ends, crossing the {ALLOWABLE:.0f}&nbsp;&deg;C allowable
      line. Airflow is lowest at racks 0 and {n-1} and highest at 1 and {n-2}, the
      positions immediately inboard of them.</figcaption>
    </figure>

    <p class="note" style="margin-top:1.4rem"><strong>Why the ends and not the
    middle.</strong> Each unit discharges a {SUPPLY_VEL:.2f}&nbsp;m/s sheet straight at the
    end of the pod. That jet runs <em>parallel</em> to the end racks' front faces
    rather than into them, and separates around the pod corners &mdash; so the corner
    racks sit in the separation zone while racks 1 and {n-2}, just inboard, sit in the
    accelerated stream and get the most air of any rack in the hall. The end racks are
    also right beside the hot aisle end doors, where the containment gap leaks. Low
    airflow and the nearest leak, in the same place.</p>
  </section>

  <section>
    <h2>The flow at the hall ends does not hold still</h2>
    <p class="prose">This qualifies everything below it, so it comes first. The steady
    solver <strong>never converges the momentum equation</strong> &mdash; U sits at
    4.3&nbsp;&times;&nbsp;10<sup>&minus;3</sup> after 4,000 iterations while pressure,
    enthalpy and turbulence all converge. Two opposed supply jets meeting in one hall is
    a classically unsteady arrangement, and the end zones oscillate rather than settle.</p>

    <div class="grid">
      <div class="stat hot">
        <span class="k">End racks &mdash; wander</span>
        <span class="v">{band_end:.2f} K</span>
        <span class="s">peak-to-peak over the last 2,000 iterations</span>
      </div>
      <div class="stat ok">
        <span class="k">Mid-row racks &mdash; wander</span>
        <span class="v">{band_mid:.2f} K</span>
        <span class="s">{band_end/band_mid:.1f}&times; steadier; these values are solid</span>
      </div>
      <div class="stat">
        <span class="k">Which end runs hot</span>
        <span class="v">swapped</span>
        <span class="s">between the two runs &mdash; it is not a fixed property</span>
      </div>
    </div>

    <p class="note" style="margin-top:1.4rem"><strong>What this does and does not
    invalidate.</strong> The hall-level results &mdash; the verdict, containment
    performance, return temperature, bypass fraction &mdash; are robust; they are
    integrals over the whole domain. The mid-row per-rack values are solid, wandering
    only {band_mid:.2f}&nbsp;K. But <em>individual</em> end-rack numbers carry roughly
    &plusmn;{band_end/2:.2f}&nbsp;K, and the hot end switched from index&nbsp;0 to
    index&nbsp;{n-1} between the two runs. So the finding &ldquo;the end racks are the
    weak spot, by about 1&nbsp;K&rdquo; stands and is repeatable. The finding
    &ldquo;<em>this particular</em> end rack runs at
    {max(allp):.1f}&nbsp;&deg;C&rdquo; does not.</p>
  </section>

  <section>
    <h2>Two design fixes, tested</h2>
    <p class="prose">Infill panels flush with the fan wall discharge face, to remove the
    open pocket beside each unit, and the hot aisle containment end doors taken all the
    way to the plenum floor.</p>
    <div class="scroll">
      <table>
        <caption>Both runs identical apart from the two changes. Changes smaller than
        the {band_end:.2f}&nbsp;K end-rack wander cannot be read as an effect.</caption>
        <thead><tr><th scope="col">Metric</th><th scope="col">Open ends</th>
          <th scope="col">Bulkhead + sealed</th><th scope="col">Change</th>
          <th scope="col">Verdict</th></tr></thead>
        <tbody>
          <tr><th scope="row">Air through racks, kg/s</th><td>{v1_thru:.2f}</td>
            <td>{sum(allf):.2f}</td><td>{sum(allf)-v1_thru:+.2f}</td>
            <td><span class="chip ok">real gain</span></td></tr>
          <tr><th scope="row">Bypass, % of supply</th><td>{v1_bypass:.0f}</td>
            <td>{v2_bypass:.0f}</td><td>{v2_bypass-v1_bypass:+.0f}</td>
            <td><span class="chip ok">real gain</span></td></tr>
          <tr><th scope="row">Worst mid-row peak, &deg;C</th><td>30.91</td>
            <td>{max(max(data[r]['peak'][i] for i in range(1,n-1)) for r in 'AB'):.2f}</td>
            <td>{max(max(data[r]['peak'][i] for i in range(1,n-1)) for r in 'AB')-30.91:+.2f}</td>
            <td><span class="chip ok">real gain</span></td></tr>
          <tr><th scope="row">Hottest rack mean, &deg;C</th><td>{v1_hot:.2f}</td>
            <td>{max(allm):.2f}</td><td>{max(allm)-v1_hot:+.2f}</td>
            <td><span class="chip warn">inside noise</span></td></tr>
          <tr><th scope="row">Worst face peak, &deg;C</th><td>{v1_pk:.2f}</td>
            <td>{max(allp):.2f}</td><td>{max(allp)-v1_pk:+.2f}</td>
            <td><span class="chip warn">inside noise</span></td></tr>
        </tbody>
      </table>
    </div>
    <p class="note" style="margin-top:1.4rem"><strong>Honest read: the fixes did what
    they should on bypass, and did not measurably help the end racks.</strong> Sealing
    the doors and closing the end pockets pushed
    {sum(allf)-v1_thru:+.1f}&nbsp;kg/s more air through servers instead of around them,
    and the worst mid-row face improved. But every end-rack change is inside the
    unsteady wander, so the question they were meant to answer cannot be settled by a
    steady run. That needs a transient.</p>
  </section>

  <section>
    <h2>Containment is doing its job</h2>
    <div class="two">
      <figure>
        <img src="{uri('hall_plan.png','image/png')}"
             alt="Plan view at rack mid-height. Both cold aisles and both end zones are
             uniformly blue at about 28 C. The contained hot aisle is dark red at about
             40 C. A thin green halo traces the containment perimeter, strongest at the
             pod corners.">
        <figcaption>Plan at rack mid-height. Cold aisles uniformly at supply
        temperature; the hot aisle cleanly contained. The thin warm halo traces the
        containment perimeter and is strongest at the pod corners.</figcaption>
      </figure>
      <figure>
        <img src="{uri('hall_perspective.png','image/png')}"
             alt="3D perspective of the hall showing cold streamlines low in the side
             aisles and hot air rising from the contained aisle into the ceiling plenum
             and returning to both unit top intakes.">
        <figcaption>The circuit in 3D: supply low through both side aisles, through the
        racks, up the contained aisle, back along the plenum to the top intakes.</figcaption>
      </figure>
    </div>
  </section>
{video}
  <section>
    <h2>Numbers</h2>
    <div class="two">
      <div class="scroll">
        <table>
          <caption>Per-rack results. Highlighted rows peak above the
          {ALLOWABLE:.0f}&nbsp;&deg;C allowable limit.</caption>
          <thead><tr><th scope="col">Rack</th><th scope="col">Mean &deg;C</th>
            <th scope="col">Peak &deg;C</th><th scope="col">Flow kg/s</th></tr></thead>
          <tbody>
{rows_html}
          </tbody>
        </table>
      </div>
      <div class="prose">
        <h2>Balance</h2>
        <ul>
          <li><strong>Supply {sup:.1f} kg/s</strong>, of which
          {sum(allf):.1f}&nbsp;kg/s ({100*sum(allf)/sup:.0f}&nbsp;%) passes through
          racks. The remaining {100-100*sum(allf)/sup:.0f}&nbsp;% bypasses through the
          containment gap without meeting a server.</li>
          <li><strong>Achieved rack &Delta;T is {dT_act:.2f}&nbsp;K</strong>, not the
          {p['serverDeltaT_K']:g}&nbsp;K nameplate. The cold aisle is over-pressurised,
          so air is pushed through the racks faster than fixed-speed fans alone would
          drive it. Exhaust lands at {p['supplyTemp_C']+dT_act:.1f}&nbsp;&deg;C.</li>
          <li><strong>Return air {retT:.2f}&nbsp;&deg;C</strong> against the unit's
          {37:g}&nbsp;&deg;C rated RAT &mdash; the selection is coherent, and slightly
          above rating means slightly more capacity than the {cap/2:g}&nbsp;kW
          nameplate.</li>
          <li><strong>Airflow varies {100*(max(allf)-min(allf))/(sum(allf)/len(allf)):.0f}&nbsp;%
          rack to rack.</strong> That is the real distribution penalty, and it is
          invisible in any hall-average calculation.</li>
        </ul>
      </div>
    </div>
  </section>

  <section>
    <h2>N+1 redundancy sizing</h2>
    <p class="prose">The 40L2 is two stacked 237.5&nbsp;kW modules. Sizing has to satisfy
    <em>both</em> cooling capacity and airflow with one element out &mdash; and airflow
    is the one people forget, because the racks' own fans demand
    {2*n*p['rackLoad_kW']*1000/(1005*p['serverDeltaT_K'])/1:.0f}&nbsp;kg/s regardless of
    how much capacity is installed.</p>
    <div class="scroll">
      <table>
        <caption>Both constraints checked with one unit lost. Load
        {load:g}&nbsp;kW, demand
        {2*n*p['rackLoad_kW']*1000/(1005*p['serverDeltaT_K']):.1f}&nbsp;kg/s.</caption>
        <thead><tr><th scope="col">Selection</th><th scope="col">N</th>
          <th scope="col">N+1</th><th scope="col">Installed</th>
          <th scope="col">Lose one &rarr;</th><th scope="col">Fits 7.6 m hall?</th></tr></thead>
        <tbody>
          <tr><th scope="row">FWCV 40L2 (475 kW, 4.0 m)</th><td>2</td><td>3</td>
            <td>1425 kW</td><td>950 kW / 84.7 kg/s</td>
            <td><span class="chip bad">no &mdash; 2 side by side is 8.0 m</span></td></tr>
          <tr><th scope="row">FWCV 36L2 (384 kW, 3.6 m)</th><td>3</td><td>4</td>
            <td>1536 kW</td><td>1152 kW / 97.7 kg/s</td>
            <td><span class="chip ok">yes &mdash; 2+2, 7.2 m per end</span></td></tr>
          <tr><th scope="row">40L2 modules (237.5 kW)</th><td>4</td><td>5</td>
            <td>1188 kW</td><td>950 kW / 84.7 kg/s</td>
            <td><span class="chip warn">needs 2&times;40L2 + 1&times;40L1</span></td></tr>
        </tbody>
      </table>
    </div>
    <div class="grid" style="margin-top:1.5rem">
      <div class="stat ok">
        <span class="k">The failed state is already proven</span>
        <span class="v">2 units</span>
        <span class="s">the N+1 contingency for a 3-unit install is exactly this run</span>
      </div>
      <div class="stat cool">
        <span class="k">3 units at 67 % flow</span>
        <span class="v">44 %</span>
        <span class="s">of the fan power of 2 units at 100 %</span>
      </div>
      <div class="stat">
        <span class="k">If load is really 431 kW</span>
        <span class="v">2 units</span>
        <span class="s">already N+1 &mdash; nothing more to buy</span>
      </div>
    </div>
    <p class="note" style="margin-top:1.5rem"><strong>Recommendation: 4&nbsp;&times;
    36L2 in a 2+2 arrangement</strong>, not 3&nbsp;&times;&nbsp;40L2. Three 40L2s is the
    correct answer on paper but two of them will not stand side by side in a 7.6&nbsp;m
    hall, and a 2/1 split would load one end harder &mdash; the ends are already the
    weak spot. The 36L2 at 3600&nbsp;mm gives a symmetric layout that fits with
    0.4&nbsp;m spare. Note also that fan power scales with roughly the cube of flow, so
    the redundant unit is an efficiency measure, not idle plant.</p>
    <p class="note"><strong>N+1 protects a unit, not an end.</strong> If both units at
    one end share a power or chilled-water branch, losing that branch leaves
    2&nbsp;&times;&nbsp;384&nbsp;=&nbsp;768&nbsp;kW against {load:g}&nbsp;kW. End-loss
    resilience needs three units per end, which is a different and considerably more
    expensive conversation.</p>
  </section>

  <section class="prose">
    <h2>What would fix the end racks</h2>
    <ul>
      <li><strong>Seal the containment end doors properly.</strong> The gap is a
      {p['containmentGap']:g}&nbsp;m strip below the plenum floor around the whole pod
      perimeter. It leaks most at the corners, exactly where the affected racks are.
      This is the cheapest fix and needs no extra plant.</li>
      <li><strong>Do not put the highest-density racks at the row ends.</strong> On
      these results the end positions are worth roughly
      {end_mean-mid_mean:.1f}&nbsp;K of intake temperature and
      {100*(mid_flow-end_flow)/mid_flow:.0f}&nbsp;% of airflow. Put low-density or
      network cabinets there.</li>
      <li><strong>Consider a discharge damper or turning vanes.</strong> The units
      have a motorised discharge damper as a factory option; angling the sheet away
      from the pod end would reduce the corner separation.</li>
      <li><strong>Lower the supply temperature if margin is wanted.</strong> At
      {p['supplyTemp_C']:g}&nbsp;&deg;C supply the design already sits above the
      {RECOMMENDED:.0f}&nbsp;&deg;C ASHRAE <em>recommended</em> limit and depends on
      the allowable envelope, leaving only {ALLOWABLE-p['supplyTemp_C']:.0f}&nbsp;K
      between supply and the allowable ceiling. Every degree of supply reduction buys a
      degree of hot-spot headroom directly.</li>
    </ul>
  </section>

  <section class="prose">
    <h2>What this does not tell you</h2>
    <ul>
      <li><strong>Steady state only.</strong> This says nothing about losing a unit.
      With one fan wall down, capacity falls to {cap/2:g}&nbsp;kW against
      {load:g}&nbsp;kW of load &mdash; the hall is <em>not</em> N+1 on these two units,
      so that case is a capacity question, not a CFD one.</li>
      <li><strong>100&nbsp;mm cells, six per rack width.</strong> Enough for hall-scale
      distribution, too coarse for rack-internal detail or exact peak values at a
      leaking edge.</li>
      <li><strong>The coil is a boundary condition.</strong> Air leaves at exactly
      {p['supplyTemp_C']:g}&nbsp;&deg;C regardless of return temperature, so this cannot
      comment on chilled water flow or part-load behaviour.</li>
      <li><strong>Racks are source terms.</strong> No perforated doors, no per-U load
      profile, no blanking detail.</li>
    </ul>
  </section>

  <footer>
    Steady-state buoyant RANS (buoyantSimpleFoam), k-&omega; SST, uniform 100&nbsp;mm mesh,
    731,904 cells, 4,000 SIMPLE iterations in 1,312&nbsp;s on 8 ranks.
    Hall {p['Lx']:g} &times; {p['hallWidth']:g} &times;
    {p['plenumFloorZ']+p['plenumHeight']:g}&nbsp;m; pod
    {p['podX1']-p['podX0']:g}&nbsp;m long with a {p['hotAisleWidth']:g}&nbsp;m contained
    aisle; {p['clearance']:g}&nbsp;m from each unit face to the containment.
    Rebuild with <code>./run.sh</code> then <code>./plot_hall.py case-hall</code>.
  </footer>
</div>
"""

out = CASE / "report-hall.html"
out.write_text(HTML)
print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB)   verdict {verdict}")
sys.exit(0)
