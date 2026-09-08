#!/usr/bin/env python3
"""
Build a self-contained HTML viewer for the sweep animation, with the MP4 and the
optimisation curve embedded so the page works offline and can be published as an
Artifact.

Usage:
    ./build_viewer.py          # writes runs/viewer.html
"""

from __future__ import annotations

import base64
import csv
import sys
from pathlib import Path

RUNS = Path("runs")

VERDICT_CLASS = {"PASS": "ok", "MARGINAL": "warn", "FAIL": "bad"}


def data_uri(path: Path, mime: str) -> str:
    return f"data:{mime};base64," + base64.b64encode(path.read_bytes()).decode()


def rows() -> list[dict]:
    with (RUNS / "results.csv").open() as fh:
        out = [r for r in csv.DictReader(fh)
               if r.get("param") == "fanWallVelocity" and r.get("verdict")]
    out.sort(key=lambda r: float(r["value"]))
    return out


def findings(data: list[dict]) -> dict[str, str]:
    """Derive the headline numbers from the sweep instead of hardcoding them."""
    passes = [r for r in data if r["verdict"] == "PASS"]
    threshold = min(passes, key=lambda r: float(r["value"])) if passes else None

    # The run where mean and peak intake disagree most: the case that looks
    # acceptable on the average and is not.
    spread = max(data, key=lambda r: float(r["inletTmax_C"]) - float(r["inletT_C"]))

    top = max(data, key=lambda r: float(r["value"]))
    best = threshold or top

    return {
        "threshold": f'{float(threshold["value"]):g} m/s' if threshold else "not reached",
        "threshold_note": (
            f'supply {abs(float(threshold["supply_kgs"])):.2f} kg/s vs '
            f'demand {abs(float(threshold["through_kgs"])):.2f} kg/s'
            if threshold else "no run met the 27 &deg;C limit"
        ),
        "spread_value": f'{float(spread["value"]):g}',
        "spread_mean": f'{float(spread["inletT_C"]):.1f}',
        "spread_max": f'{float(spread["inletTmax_C"]):.1f}',
        "best_value": f'{float(best["value"]):g}',
        "top_value": f'{float(top["value"]):g}',
        "top_gap": f'{float(top["gap_kgs"]):+.2f}',
        "best_gap": f'{float(best["gap_kgs"]):+.2f}',
        "top_mean": f'{float(top["inletT_C"]):.1f}',
        "best_mean": f'{float(best["inletT_C"]):.1f}',
    }


def table_html(data: list[dict]) -> str:
    cells = []
    for r in data:
        v = float(r["value"])
        through = abs(float(r["through_kgs"]))
        pct = abs(float(r["supply_kgs"])) / through * 100 if through else 0.0
        gap = float(r["gap_kgs"])
        cls = VERDICT_CLASS[r["verdict"]]
        flow = "bypass" if gap >= 0 else "recirculating"
        cells.append(
            f'<tr class="{cls}">'
            f'<th scope="row">{v:g}</th>'
            f"<td>{pct:.0f}%</td>"
            f'<td>{float(r["inletT_C"]):.1f}</td>'
            f'<td class="peak">{float(r["inletTmax_C"]):.1f}</td>'
            f'<td>{float(r["outletT_C"]):.1f}</td>'
            f"<td>{gap:+.2f} <span class=\"dim\">{flow}</span></td>"
            f'<td><span class="chip {cls}">{r["verdict"]}</span></td>'
            "</tr>"
        )
    return "\n".join(cells)


HTML = """<title>Cabinet Cooling Sweep</title>
<style>
:root {{
  --ground:#eef1f5; --surface:#ffffff; --edge:#d5dce5;
  --ink:#0f141a; --muted:#5b6774; --dim:#8a95a3;
  --accent:#c2410c; --cold:#1d4ed8;
  --ok:#15803d; --warn:#b45309; --bad:#b91c1c;
  --ok-bg:#e4f2e8; --warn-bg:#fbeedb; --bad-bg:#fbe4e4;
  --mono:ui-monospace,"SF Mono",SFMono-Regular,Menlo,Consolas,monospace;
  --sans:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif;
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
  font-family:var(--sans); line-height:1.6;
  margin:0; padding:clamp(1.5rem,4vw,3.5rem) clamp(1rem,4vw,2rem) 5rem;
  display:flex; flex-direction:column; align-items:center; gap:2.75rem;
}}
.wrap {{ width:100%; max-width:64rem; display:flex; flex-direction:column; gap:2.75rem; }}
.prose {{ max-width:38rem; }}

header {{ display:flex; flex-direction:column; gap:.9rem; }}
.eyebrow {{
  font-family:var(--mono); font-size:.72rem; letter-spacing:.16em;
  text-transform:uppercase; color:var(--muted); margin:0;
}}
h1 {{
  font-family:var(--mono); font-size:clamp(1.6rem,4.2vw,2.4rem);
  font-weight:600; letter-spacing:-.01em; line-height:1.15;
  margin:0; text-wrap:balance;
}}
h2 {{
  font-family:var(--mono); font-size:.82rem; letter-spacing:.14em;
  text-transform:uppercase; color:var(--muted);
  margin:0 0 .9rem; padding-bottom:.5rem; border-bottom:1px solid var(--edge);
}}
p {{ margin:0 0 1rem; }}
p:last-child {{ margin-bottom:0; }}
strong {{ font-weight:650; }}

.lede {{ font-size:1.06rem; color:var(--muted); max-width:44rem; margin:0; }}

figure {{ margin:0; display:flex; flex-direction:column; gap:.7rem; }}
video, .fig img {{
  width:100%; height:auto; display:block;
  border:1px solid var(--edge); border-radius:3px; background:var(--surface);
}}
figcaption {{ font-size:.85rem; color:var(--muted); max-width:44rem; }}

.note {{
  border-left:2px solid var(--accent); padding:.15rem 0 .15rem 1rem;
  color:var(--muted); font-size:.94rem; max-width:44rem;
}}
.note strong {{ color:var(--ink); }}

.scroll {{ overflow-x:auto; border:1px solid var(--edge); border-radius:3px; background:var(--surface); }}
table {{ border-collapse:collapse; width:100%; font-size:.88rem; min-width:44rem; }}
caption {{ caption-side:bottom; text-align:left; padding:.75rem .9rem; color:var(--muted); font-size:.82rem; }}
th, td {{ padding:.6rem .9rem; text-align:right; font-variant-numeric:tabular-nums; }}
thead th {{
  font-family:var(--mono); font-size:.68rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--muted); font-weight:500;
  border-bottom:1px solid var(--edge); text-align:right; white-space:nowrap;
}}
thead th:first-child, tbody th {{ text-align:left; }}
tbody th {{ font-family:var(--mono); font-weight:600; }}
tbody tr {{ border-top:1px solid var(--edge); }}
tbody tr:first-child {{ border-top:0; }}
tbody td:last-child {{ text-align:left; }}
td.peak {{ font-weight:650; }}
tr.bad td.peak {{ color:var(--bad); }}
tr.warn td.peak {{ color:var(--warn); }}
.dim {{ color:var(--dim); font-size:.82em; }}

.chip {{
  font-family:var(--mono); font-size:.68rem; letter-spacing:.08em;
  padding:.18rem .5rem; border-radius:2px; white-space:nowrap;
}}
.chip.ok {{ background:var(--ok-bg); color:var(--ok); }}
.chip.warn {{ background:var(--warn-bg); color:var(--warn); }}
.chip.bad {{ background:var(--bad-bg); color:var(--bad); }}

.grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(13rem,1fr)); gap:1px; background:var(--edge);
  border:1px solid var(--edge); border-radius:3px; overflow:hidden; }}
.stat {{ background:var(--surface); padding:1rem 1.1rem; display:flex; flex-direction:column; gap:.3rem; }}
.stat .k {{ font-family:var(--mono); font-size:.66rem; letter-spacing:.11em; text-transform:uppercase; color:var(--muted); }}
.stat .v {{ font-family:var(--mono); font-size:1.5rem; font-weight:600; font-variant-numeric:tabular-nums; }}
.stat .s {{ font-size:.8rem; color:var(--dim); }}
.stat.hot .v {{ color:var(--accent); }}
.stat.cool .v {{ color:var(--cold); }}

footer {{ font-size:.82rem; color:var(--dim); border-top:1px solid var(--edge); padding-top:1rem; }}
code {{ font-family:var(--mono); font-size:.88em; }}
@media (prefers-reduced-motion:reduce) {{ * {{ animation:none !important; transition:none !important; }} }}
</style>

<div class="wrap">
  <header>
    <p class="eyebrow">OpenFOAM &middot; buoyantSimpleFoam &middot; 30 kW rack, hot-aisle containment</p>
    <h1>Cabinet Cooling Sweep</h1>
    <p class="lede">Six converged CFD runs, swept across fan wall velocity, showing where
    a 30&nbsp;kW cabinet stops being cooled and starts ingesting its own exhaust.</p>
  </header>

  <figure>
    <video controls autoplay loop muted playsinline poster="">
      <source src="{mp4}" type="video/mp4">
      Your browser cannot play this video. The file is also at <code>runs/sweep.mp4</code>.
    </video>
    <figcaption>Centreline air temperature and airflow. Each frame is one fully converged
    run, not a moment in time &mdash; the simulation is steady-state, so what is animated is
    the design parameter, sweeping up and back down. Fixed 18&ndash;40&nbsp;&deg;C colour
    scale throughout, so frames are directly comparable.</figcaption>
  </figure>

  <section class="prose">
    <h2>What to watch</h2>
    <p>At low supply velocity the servers draw more air than the unit delivers, so they make
    up the shortfall from the only other source available &mdash; their own exhaust, pulled
    back through the containment gap. Watch the hot layer spread left under the plenum floor
    and the white 27&nbsp;&deg;C line drop into the cold aisle.</p>
    <p>As velocity rises past the balance point the layer retreats, the cold aisle goes
    uniformly blue across all 4&nbsp;m, and flow through the gap reverses into harmless
    bypass into the hot aisle.</p>
  </section>

  <section>
    <h2>Converged results</h2>
    <div class="scroll">
      <table>
        <caption>Negative gap flow is hot air recirculating into the cold aisle; positive is
        cold air bypassing into the hot aisle. Limits are ASHRAE&nbsp;TC9.9 class&nbsp;A1:
        27&nbsp;&deg;C recommended, 32&nbsp;&deg;C allowable.</caption>
        <thead>
          <tr>
            <th scope="col">Fan wall<br>m/s</th>
            <th scope="col">Supply<br>% demand</th>
            <th scope="col">Intake mean<br>&deg;C</th>
            <th scope="col">Intake peak<br>&deg;C</th>
            <th scope="col">Exhaust<br>&deg;C</th>
            <th scope="col">Gap flow<br>kg/s</th>
            <th scope="col">Verdict</th>
          </tr>
        </thead>
        <tbody>
{table}
        </tbody>
      </table>
    </div>
  </section>

  <section>
    <h2>The finding that matters</h2>
    <div class="grid">
      <div class="stat cool">
        <span class="k">Lowest passing supply</span>
        <span class="v">{threshold}</span>
        <span class="s">{threshold_note}</span>
      </div>
      <div class="stat">
        <span class="k">Intake mean at {spread_value} m/s</span>
        <span class="v">{spread_mean} &deg;C</span>
        <span class="s">the number an average would report</span>
      </div>
      <div class="stat hot">
        <span class="k">Intake peak, same run</span>
        <span class="v">{spread_max} &deg;C</span>
        <span class="s">what the top of the rack actually breathes</span>
      </div>
    </div>
    <p class="note" style="margin-top:1.25rem"><strong>Read peak intake next to the
    mean.</strong> The recirculating plume is buoyant, so it rides along the underside of
    the plenum floor and is drawn into the top of the rack while the bottom still breathes
    clean supply air. Averaging across the cabinet face hides that split behind a single
    comfortable-looking number.</p>
  </section>

  <section>
    <h2>Optimisation curve</h2>
    <figure class="fig">
      <img src="{png}" alt="Server intake temperature and containment gap flow plotted
      against fan wall velocity, showing the knee at 1.29 m/s where gap flow crosses zero.">
      <figcaption>The knee in intake temperature and the zero crossing of gap flow are the
      same point. Above roughly 1.4&nbsp;m/s nothing improves thermally while bypass keeps
      growing &mdash; 1.83&nbsp;m/s is thermally identical to 1.41&nbsp;m/s for about
      2.2&times; the fan power.</figcaption>
    </figure>
  </section>

  <section class="prose">
    <h2>Recommendation</h2>
    <p>The lowest supply velocity that keeps the servers inside the recommended range is
    <strong>{threshold}</strong>. Running there leaves no margin for filter loading, fan
    degradation or load growth, none of which are modelled here, so size the fan wall a step
    above it.</p>
    <p>Pushing well past it stops helping: at {top_value}&nbsp;m/s the intake sits at
    {top_mean}&nbsp;&deg;C against {best_mean}&nbsp;&deg;C at {best_value}&nbsp;m/s, while
    flow through the containment gap grows from {best_gap} to {top_gap}&nbsp;kg/s. That
    surplus is cold air pushed straight into the hot aisle without passing a server, and fan
    power scales with roughly the cube of flow.</p>
    <p>The cheaper lever is the containment itself. Every failure above is air crossing one
    0.2&nbsp;m gap; sealing it to the plenum floor removes the recirculation path entirely,
    which is what <code>containmentTopZ</code> exists to test.</p>
  </section>

  <footer>
    Steady-state RANS, k-&omega; SST, 107,520 cells, 3,000 SIMPLE iterations per run.
    Fan wall unit with a top intake, 4.0 m cold aisle, hot aisle contained to a
    ceiling return plenum.
    Regenerate with <code>./sweep.sh</code> then <code>./make_animation.py</code>.
    A time-resolved animation &mdash; warm-up, fan failure, cooling outage &mdash; needs a
    transient solver and is not what this case runs.
  </footer>
</div>
"""


def main() -> int:
    if not (RUNS / "sweep.mp4").is_file():
        raise SystemExit("runs/sweep.mp4 not found - run ./make_animation.py first")

    data = rows()
    out = RUNS / "viewer.html"
    out.write_text(HTML.format(
        mp4=data_uri(RUNS / "sweep.mp4", "video/mp4"),
        png=data_uri(RUNS / "sweep.png", "image/png"),
        table=table_html(data),
        **findings(data),
    ))
    print(f"wrote {out}  ({out.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
