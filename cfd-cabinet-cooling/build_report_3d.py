#!/usr/bin/env python3
"""
Build the 3D report as a self-contained HTML page, ready to publish.

Per-cabinet numbers are parsed out of verification/*.txt rather than retyped, so
the page cannot drift from the runs it describes.

    ./build_report_3d.py        ->  verification/report-3d.html
"""
from __future__ import annotations

import base64
import re
import sys
from pathlib import Path

V = Path("verification")
W = V / "web"


def uri(name: str, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode((W / name).read_bytes()).decode()


def cabinets(txt: str) -> list[dict]:
    rows = []
    for m in re.finditer(
            r"^\s*(\d+)\s+(\d+)\s+([\d.]+)C\s+([\d.]+)C\s+([\d.]+)\s+(\w+)\s*$",
            txt, re.M):
        rows.append(dict(i=int(m[1]), kw=int(m[2]), mean=float(m[3]),
                         peak=float(m[4]), flow=float(m[5]), verdict=m[6]))
    if not rows:
        raise SystemExit("could not parse the per-cabinet table")
    return rows


def agg(txt: str, label: str) -> str:
    m = re.search(re.escape(label) + r"\s+(-?[\d.]+)", txt)
    return m[1] if m else "?"


CLS = {"PASS": "ok", "MARGINAL": "warn", "FAIL": "bad"}

mixed = (V / "phase3b_mixedload.txt").read_text()
uniform = (V / "phase3a_percabinet_uniform.txt").read_text()
cabs = cabinets(mixed)
ucabs = cabinets(uniform)

body_rows = "\n".join(
    f'<tr class="{CLS[c["verdict"]]}"><th scope="row">{c["i"]}</th>'
    f'<td>{c["kw"]}</td><td>{c["mean"]:.2f}</td>'
    f'<td class="peak">{c["peak"]:.2f}</td><td>{c["flow"]:.3f}</td>'
    f'<td><span class="chip {CLS[c["verdict"]]}">{c["verdict"]}</span></td></tr>'
    for c in cabs)

uni_rows = "\n".join(
    f'<tr><th scope="row">{c["i"]}</th><td>{c["kw"]}</td>'
    f'<td>{c["mean"]:.2f}</td><td>{c["peak"]:.2f}</td><td>{c["flow"]:.3f}</td></tr>'
    for c in ucabs)

sm = re.search(r'spread across the row: ([\d.]+) K on the mean, ([\d.]+) K', mixed)
spread_mean, spread_peak = (sm[1], sm[2]) if sm else ('?', '?')

hottest = max(cabs, key=lambda c: c["kw"])
coolest = min(cabs, key=lambda c: c["kw"])
lowest_mean = min(cabs, key=lambda c: c["mean"])
flow_gap = 100 * (coolest["flow"] - hottest["flow"]) / hottest["flow"]

HTML = f"""<title>3D Cabinet Row</title>
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
body {{
  background:var(--ground); color:var(--ink);
  font-family:var(--sans); line-height:1.62; margin:0;
  padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 5rem;
  display:flex; flex-direction:column; align-items:center;
}}
.wrap {{ width:100%; max-width:64rem; display:flex; flex-direction:column; gap:2.9rem; }}
.prose {{ max-width:38rem; }}

.eyebrow {{ font-family:var(--mono); font-size:.72rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted); margin:0; }}
h1 {{ font-family:var(--mono); font-size:clamp(1.6rem,4.2vw,2.4rem); font-weight:600;
  letter-spacing:-.015em; line-height:1.12; margin:0; text-wrap:balance; }}
h2 {{ font-family:var(--mono); font-size:.82rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted); margin:0 0 1rem;
  padding-bottom:.5rem; border-bottom:1px solid var(--edge); }}
h3 {{ font-family:var(--mono); font-size:.95rem; font-weight:600; margin:0 0 .4rem; }}
header {{ display:flex; flex-direction:column; gap:.9rem; }}
p {{ margin:0 0 1rem; }} p:last-child {{ margin-bottom:0; }}
.lede {{ font-size:1.06rem; color:var(--muted); max-width:44rem; margin:0; }}
strong {{ font-weight:600; }}
code {{ font-family:var(--mono); font-size:.88em; }}
section {{ display:flex; flex-direction:column; }}

figure {{ margin:0; display:flex; flex-direction:column; gap:.7rem; }}
video, figure img {{ width:100%; height:auto; display:block; border:1px solid var(--edge);
  border-radius:3px; background:var(--surface); }}
figcaption {{ font-size:.85rem; color:var(--muted); max-width:44rem; }}

.note {{ border-left:2px solid var(--accent); padding:.15rem 0 .15rem 1rem;
  color:var(--muted); font-size:.94rem; max-width:44rem; }}
.note strong {{ color:var(--ink); }}

.scroll {{ overflow-x:auto; border:1px solid var(--edge); border-radius:3px;
  background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; font-size:.88rem; min-width:34rem; }}
caption {{ caption-side:bottom; text-align:left; padding:.75rem .9rem;
  color:var(--muted); font-size:.82rem; }}
th,td {{ padding:.58rem .9rem; text-align:right; font-variant-numeric:tabular-nums; }}
thead th {{ font-family:var(--mono); font-size:.67rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--muted); font-weight:500;
  border-bottom:1px solid var(--edge); white-space:nowrap; }}
thead th:first-child, tbody th {{ text-align:left; }}
tbody th {{ font-family:var(--mono); font-weight:600; }}
tbody tr {{ border-top:1px solid var(--edge); }}
tbody tr:first-child {{ border-top:0; }}
tbody td:last-child {{ text-align:left; }}
td.peak {{ font-weight:600; }}
tr.bad td.peak {{ color:var(--bad); }} tr.warn td.peak {{ color:var(--warn); }}

.chip {{ font-family:var(--mono); font-size:.67rem; letter-spacing:.07em;
  padding:.16rem .5rem; border-radius:2px; white-space:nowrap; }}
.chip.ok {{ background:var(--ok-bg); color:var(--ok); }}
.chip.warn {{ background:var(--warn-bg); color:var(--warn); }}
.chip.bad {{ background:var(--bad-bg); color:var(--bad); }}

/* The verification ladder: a real sequence, each rung licensing the next. */
.ladder {{ display:flex; flex-direction:column; gap:0; border:1px solid var(--edge);
  border-radius:3px; overflow:hidden; }}
.rung {{ display:grid; grid-template-columns:3.3rem 1fr auto; gap:1rem;
  padding:1.05rem 1.15rem; background:var(--surface); align-items:start;
  border-top:1px solid var(--edge); }}
.rung:first-child {{ border-top:0; }}
.rung .step {{ font-family:var(--mono); font-size:.72rem; letter-spacing:.08em;
  color:var(--muted); padding-top:.15rem; }}
.rung .what {{ display:flex; flex-direction:column; gap:.3rem; }}
.rung .crit {{ font-size:.86rem; color:var(--muted); }}
.rung .crit b {{ font-family:var(--mono); color:var(--ink); font-weight:600; }}

.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(13rem,1fr)); gap:1px;
  background:var(--edge); border:1px solid var(--edge); border-radius:3px; overflow:hidden; }}
.stat {{ background:var(--surface); padding:1rem 1.1rem; display:flex;
  flex-direction:column; gap:.28rem; }}
.stat .k {{ font-family:var(--mono); font-size:.65rem; letter-spacing:.11em;
  text-transform:uppercase; color:var(--muted); }}
.stat .v {{ font-family:var(--mono); font-size:1.45rem; font-weight:600;
  font-variant-numeric:tabular-nums; }}
.stat .s {{ font-size:.8rem; color:var(--dim); }}
.stat.hot .v {{ color:var(--accent); }} .stat.cool .v {{ color:var(--cold); }}

.two {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(19rem,1fr)); gap:1.5rem; }}
footer {{ font-size:.82rem; color:var(--dim); border-top:1px solid var(--edge);
  padding-top:1rem; }}
ul {{ margin:0 0 1rem; padding-left:1.15rem; }} li {{ margin-bottom:.4rem; }}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">OpenFOAM &middot; buoyantSimpleFoam &middot; 430,080 cells &middot; 4-cabinet row</p>
    <h1>3D Cabinet Row</h1>
    <p class="lede">The cabinet cooling case widened from a 2D slab to a row of four
    cabinets, verified against the 2D answer at every step &mdash; and the first three
    results that a 2D model could not have produced.</p>
  </header>

  <figure>
    <video controls autoplay loop muted playsinline>
      <source src="{uri('perspective.mp4','video/mp4')}" type="video/mp4">
      Your browser cannot play this video; it is also at <code>case/perspective.mp4</code>.
    </video>
    <figcaption>The pod in perspective, mixed-load case. Streamlines are seeded across
    the fan wall supply opening and coloured by air temperature: cold air crosses the
    4&nbsp;m aisle, passes through the cabinets, and returns hot through the ceiling
    plenum to the intake on top of the unit. The grey plane is the plenum floor; the
    faint white surface is the 27&nbsp;&deg;C ASHRAE limit.</figcaption>
  </figure>

  <section class="prose">
    <h2>What changed</h2>
    <p>Nothing was rewritten. The case was already built on dimension-agnostic tooling,
    so going to 3D meant parametrising the width and splitting one cabinet into a row.
    The 2D slab is still there &mdash; it is <code>nCabinets 1</code>, and it survives as a
    two-and-a-half minute regression test rather than as dead code.</p>
    <p>Each cabinet now carries its own cell zone, heat source, fan source and metrics,
    generated from <code>nCabinets</code> and an optional per-cabinet load table. At four
    cabinets that is 4 zones, 8 source terms and 12 function objects, which is past the
    point of hand-writing.</p>
  </section>

  <section>
    <h2>Verification ladder</h2>
    <div class="ladder">
      <div class="rung">
        <div class="step">1</div>
        <div class="what">
          <h3>Width parametrised</h3>
          <div class="crit">The derived tolerances resolve to exactly the literals they
          replaced, so this must be a no-op. Every reported figure came back
          <b>identical</b> to the 2D reference.</div>
        </div>
        <span class="chip ok">PASS</span>
      </div>
      <div class="rung">
        <div class="step">2</div>
        <div class="what">
          <h3>Widened to four cabinets</h3>
          <div class="crit">Still a wider slab of an identical problem, so temperatures
          must not move and mass flows must scale exactly 4&times;. Got
          <b>&minus;0.01&nbsp;K</b> on intake temperature (limit 0.1&nbsp;K) and
          <b>&minus;0.1&nbsp;%</b> on flow (limit 2&nbsp;%). This is the load-bearing
          test.</div>
        </div>
        <span class="chip ok">PASS</span>
      </div>
      <div class="rung">
        <div class="step">3</div>
        <div class="what">
          <h3>Per-cabinet zones, uniform load</h3>
          <div class="crit">Zone sizes came out at 12,672 cells and 528 inlet faces each,
          identical to the single-cabinet values. <b>Zero spread</b> across the row, every
          per-cabinet flow positive, and the four flows sum to the Phase&nbsp;2
          aggregate.</div>
        </div>
        <span class="chip ok">PASS</span>
      </div>
    </div>

    <div class="scroll" style="margin-top:1.4rem">
      <table>
        <caption>Phase 3 control run: four identical 30&nbsp;kW cabinets. Any spread here
        would have meant a bug in the generated zones, not physics.</caption>
        <thead><tr><th scope="col">Cabinet</th><th scope="col">kW</th>
          <th scope="col">Intake mean &deg;C</th><th scope="col">Intake peak &deg;C</th>
          <th scope="col">Flow kg/s</th></tr></thead>
        <tbody>
{uni_rows}
        </tbody>
      </table>
    </div>

    <p class="note" style="margin-top:1.4rem"><strong>Phase 2 caught a real bug.</strong>
    The heat source uses <code>volumeMode absolute</code>, meaning a total over the zone.
    Widening the row made the zone four times bigger while leaving the total at 30&nbsp;kW
    &mdash; 7.5&nbsp;kW per cabinet instead of 30. Fixed by deriving
    <code>rowHeatLoad = nCabinets &times; heatLoad</code>. Without it, Phase&nbsp;2 would
    have &ldquo;passed&rdquo; on temperatures for entirely the wrong reason.</p>
  </section>

  <section>
    <h2>The first genuinely 3D result</h2>
    <p class="prose">Loads of {hottest['kw']}&nbsp;/&nbsp;30&nbsp;/&nbsp;30&nbsp;/&nbsp;{coolest['kw']}&nbsp;kW
    &mdash; the same {sum(c['kw'] for c in cabs)}&nbsp;kW total as the control, so the aggregate is
    directly comparable &mdash; with supply dropped to 93&nbsp;% of demand so the
    containment gap actually recirculates ({agg(mixed,'containment gap')}&nbsp;kg/s).</p>

    <div class="scroll">
      <table>
        <caption>Every cabinet passes on the mean and fails on the peak. Same total load
        as the control run above; only its distribution and the supply rate changed.</caption>
        <thead><tr><th scope="col">Cabinet</th><th scope="col">kW</th>
          <th scope="col">Intake mean &deg;C</th><th scope="col">Intake peak &deg;C</th>
          <th scope="col">Flow kg/s</th><th scope="col">Verdict</th></tr></thead>
        <tbody>
{body_rows}
        </tbody>
      </table>
    </div>

    <div class="two" style="margin-top:1.5rem">
      <figure>
        <img src="{uri('phase3b_row_mixedload.png','image/png')}"
             alt="Per-cabinet intake temperature along the row for the mixed-load case:
             peak intake falls monotonically from cabinet 0 to cabinet 3 while the mean
             stays flat, with load and airflow bars beneath.">
        <figcaption>Mixed load. Peak intake (red) orders cleanly by load; the mean (blue)
        does not.</figcaption>
      </figure>
      <figure>
        <img src="{uri('phase3a_row.png','image/png')}"
             alt="Per-cabinet intake temperature for the uniform control run: both mean
             and peak are perfectly flat across all four cabinets.">
        <figcaption>Uniform control. Flat, as it must be &mdash; this is what makes the
        mixed-load ordering believable.</figcaption>
      </figure>
    </div>

    <h2 style="margin-top:2.4rem">Three things 2D could not show</h2>
    <div class="grid">
      <div class="stat hot">
        <span class="k">Peak intake, {hottest['kw']} kW cabinet</span>
        <span class="v">{hottest['peak']:.2f} &deg;C</span>
        <span class="s">vs {coolest['peak']:.2f} &deg;C at the {coolest['kw']} kW cabinet</span>
      </div>
      <div class="stat">
        <span class="k">Lowest mean intake</span>
        <span class="v">{lowest_mean['mean']:.2f} &deg;C</span>
        <span class="s">at cabinet {lowest_mean['i']}, a {lowest_mean['kw']} kW cabinet &mdash; not the coolest</span>
      </div>
      <div class="stat cool">
        <span class="k">Airflow deficit, hottest cabinet</span>
        <span class="v">&minus;{flow_gap:.1f}&nbsp;%</span>
        <span class="s">{hottest['flow']:.3f} vs {coolest['flow']:.3f} kg/s</span>
      </div>
    </div>

    <ul class="prose" style="margin-top:1.5rem">
      <li><strong>Peak intake tracks load.</strong> The hottest cabinet's own exhaust
      drives slightly worse local recirculation, so it partly poisons itself.</li>
      <li><strong>Mean intake does not.</strong> The lowest mean belongs to a
      {lowest_mean['kw']}&nbsp;kW cabinet. The mean blends two air populations that never
      mix and lands in the gap between them &mdash; the same trap the 2D sweep found.</li>
      <li><strong>The hottest cabinet gets the least air.</strong> The server fans hold a
      target <em>velocity</em>, and hotter air is less dense, so the cabinet that needs the
      most cooling receives {flow_gap:.1f}&nbsp;% less mass flow than its coolest
      neighbour. A compounding penalty, and purely a multi-cabinet effect.</li>
    </ul>

    <p class="note" style="margin-top:1.4rem">The spread is modest &mdash;
    {spread_mean}&nbsp;K on the mean, {spread_peak}&nbsp;K on the peak &mdash; because symmetry planes on both side walls make the row repeat
    infinitely, which limits how far air can migrate along it. <strong>Expect a larger
    spread once real row ends exist</strong>, which is the next step.</p>
  </section>

  <section class="prose">
    <h2>What this cost, and where it should run</h2>
    <p>The 4-cabinet run is 430,080 cells and took <strong>545&nbsp;s on 8 ranks</strong>
    on a laptop. Measured scaling peaks at 8 ranks and then collapses &mdash; 12 ranks is
    1.9&times; <em>slower</em> than 6 &mdash; so the rule is
    <code>ranks &approx; cells / 20,000</code>, capped by physical cores.</p>
    <p>A GPU would not help. Profiling puts <strong>70&nbsp;%</strong> of the runtime in
    matrix assembly, gradients, thermophysical updates and turbulence, all of which stay
    on the CPU; linear algebra is only 28&nbsp;%, giving a hard Amdahl ceiling of
    <strong>1.39&times;</strong> for a solver that takes zero time. Individual solves are
    ~5&nbsp;ms, far too small to amortise a PCIe round trip. The full 12-cabinet row is
    a ~20&nbsp;minute, ~$0.03 job on Arm CPU Spot instances.</p>
  </section>

  <section class="prose">
    <h2>Still open</h2>
    <ul>
      <li><strong>Real row ends.</strong> Replace the symmetry planes with room walls,
      add end panels and hot aisle doors, and cut the plenum floor around the hot aisle
      footprint. This is where the end-of-row penalty finally becomes visible.</li>
      <li><strong>Discrete fan wall units.</strong> Split the supply into individually
      controllable units, which is what makes the fan-failure question askable at all.
      It needs the full row: a failed fan is asymmetric, so lateral symmetry is invalid.</li>
      <li><strong>Transient.</strong> Every result here is a steady state. A failed fan
      as a <em>new steady state</em> says nothing about how long the racks have before
      they overheat.</li>
    </ul>
  </section>

  <footer>
    Steady-state RANS, k-&omega; SST, uniform 50&nbsp;mm mesh, 3,000 SIMPLE iterations.
    Fan wall unit with a top intake, 4&nbsp;m cold aisle, hot aisle contained to a ceiling
    return plenum, 0.2&nbsp;m containment leakage gap. Reproduce with
    <code>./run.sh</code>, then <code>./plot_row.py case</code> and
    <code>make_3d_video.py case</code>.
  </footer>
</div>
"""

out = V / "report-3d.html"
out.write_text(HTML)
print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB)")
sys.exit(0)
