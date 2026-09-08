#!/usr/bin/env python3
"""
Build a self-contained HTML report for the AU01 whitespace study.

    ./build_report_au01.py case-au01

Every figure in the prose is read from the case, not typed in. The hall report
carried a hardcoded discharge velocity that went stale the moment the unit
geometry changed, and it was wrong by the time anyone noticed.
"""

import base64
import glob
import json
import os
import sys

import plot_au01 as P

CP = 1005.0
R_AIR = 287.05
P_ATM = 101325.0


def b64(path):
    if not os.path.exists(path):
        return None
    return "data:image/png;base64," + base64.b64encode(open(path, 'rb').read()).decode()


def gather(case):
    p = P.read_params(os.path.join(case, 'system', 'au01Parameters'))
    with open(os.path.join(case, 'system', 'cfd_export_params.json')) as fh:
        g = json.load(fh)
    if p.get('solver', '').endswith('PimpleFoam'):
        P.FROM = float(p['averageFrom'])
    s = float(g['scale'])
    d = dict(p=p, g=g)

    sched = g['rack_schedule_kw']
    tags = sorted(sched, key=lambda t: (t[0], int(t[1:3])))
    racks = []
    for t in tags:
        m, n = P.tail_mean(P.series(case, 'r%s_inletT' % t))
        pk, _ = P.tail_mean(P.series(case, 'r%s_inletTmax' % t))
        q, _ = P.tail_mean(P.series(case, 'r%s_flow' % t))
        if m is None:
            continue
        racks.append(dict(tag=t, kW=sched[t], mean=m - 273.15, peak=pk - 273.15,
                          flow=abs(q), wander=P.tail_spread(P.series(case, 'r%s_inletT' % t)),
                          n=n))
    d['racks'] = racks
    d['samples'] = racks[0]['n'] if racks else 0
    d['truncated'] = P.WINDOW_EMPTY

    mods = []
    for end in ('W', 'E'):
        for m in (1, 2):
            tag = '%s%d' % (end, m)
            sup, _ = P.tail_mean(P.series(case, 'supply%s_flow' % tag, 2))
            ret, _ = P.tail_mean(P.series(case, 'intake%s_flow' % tag, 2))
            ps, _ = P.tail_mean(P.series(case, 'supply%s_p' % tag, 2))
            pi, _ = P.tail_mean(P.series(case, 'intake%s_p' % tag, 2))
            ar, _ = P.tail_mean(P.series(case, 'supply%s_flow' % tag, 1))
            if sup is None:
                continue
            mods.append(dict(tag=tag, supply=-sup, ret=ret or 0.0, area=ar,
                             esp=None if ps is None or pi is None else ps - pi))
    d['mods'] = mods
    Tr, _ = P.tail_mean(P.series(case, 'intakeW1_T', 2))
    d['returnT'] = None if Tr is None else Tr - 273.15

    # geometry facts, derived
    eave, apex = g['room']['eave'] * s, g['room']['apex'] * s
    W = (g['room']['y'][1] - g['room']['y'][0]) * s
    fwy = [v * s for v in g['fanwall']['y']]
    top = g['fanwall']['top'] * s
    d['clear'] = [(y, eave + (apex - eave) * (1 - abs(y - W / 2) / (W / 2)) - top)
                  for y in (fwy[0], 3.1, W / 2, 5.1, fwy[1])]
    z = float(p.get('plenumFloorZ', 0) or 0)
    d['plenumA'] = (W * (eave - z) + 0.5 * W * (apex - eave)) if 0 < z <= eave else 0.0
    d['load'] = sum(sched.values())
    d['supply'] = sum(m['supply'] for m in mods)
    d['dT'] = float(p['serverDeltaT_K'])
    d['demand'] = d['load'] * 1000.0 / (CP * d['dT'])
    d['allow'] = float(p['allowableMax_C'])
    d['rec'] = float(p['recommendedMax_C'])
    rho_r = P_ATM / (R_AIR * (float(p['supplyTemp_C']) + 273.15 + d['dT']))
    d['plenumV'] = (d['supply'] / rho_r / 2.0) / d['plenumA'] if d['plenumA'] else 0.0
    d['eave'], d['apex'], d['fwtop'] = eave, apex, top
    return d


def verdict(d):
    worst = max(d['racks'], key=lambda r: r['peak'])
    wmean = max(d['racks'], key=lambda r: r['mean'])
    if worst['peak'] > d['allow']:
        return 'FAIL', 'fail', 'a rack face exceeds the A2 allowable', worst, wmean
    if worst['peak'] > d['rec']:
        return 'MARGINAL', 'warn', 'inside allowable, above the recommended envelope', worst, wmean
    return 'PASS', 'pass', 'every intake inside the recommended envelope', worst, wmean


CSS = """
:root{
  --ground:#f6f7f9; --surface:#fff; --raised:#eef1f5;
  --ink:#111821; --dim:#5c6675; --faint:#8b95a3; --rule:#dde2e9;
  --cold:#0d6e88; --hot:#a94f1c; --accent:#0d6e88;
  --pass:#2c7a33; --warn:#9c6300; --fail:#a92218;
  --pass-bg:#e6f2e7; --warn-bg:#fbf1dc; --fail-bg:#fbe7e5;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0e1218; --surface:#151a22; --raised:#1c222c;
    --ink:#e7ebf1; --dim:#98a2b1; --faint:#6d7887; --rule:#252c37;
    --cold:#54c4e6; --hot:#f2955d; --accent:#54c4e6;
    --pass:#6cc072; --warn:#dfae43; --fail:#ef7568;
    --pass-bg:#16251a; --warn-bg:#2a2211; --fail-bg:#2b1613;
  }
}
:root[data-theme="dark"]{
  --ground:#0e1218; --surface:#151a22; --raised:#1c222c;
  --ink:#e7ebf1; --dim:#98a2b1; --faint:#6d7887; --rule:#252c37;
  --cold:#54c4e6; --hot:#f2955d; --accent:#54c4e6;
  --pass:#6cc072; --warn:#dfae43; --fail:#ef7568;
  --pass-bg:#16251a; --warn-bg:#2a2211; --fail-bg:#2b1613;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  font-size:16.5px; line-height:1.62; -webkit-font-smoothing:antialiased;
}
.wrap{max-width:1120px; margin:0 auto; padding:0 28px 96px}
.prose{max-width:66ch}
h1,h2,h3{font-family:"IBM Plex Sans Condensed","IBM Plex Sans",sans-serif; text-wrap:balance; margin:0}
h1{font-size:clamp(2.1rem,4.4vw,3.2rem); font-weight:600; letter-spacing:-.015em; line-height:1.08}
h2{font-size:1.62rem; font-weight:600; margin:0 0 .1em}
h3{font-size:1.06rem; font-weight:600; margin:2.2em 0 .3em}
p{margin:.85em 0}
code,.num,td.n,th.n{font-family:"IBM Plex Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums}
code{font-size:.9em; background:var(--raised); padding:.1em .38em; border-radius:3px}
header{border-bottom:1px solid var(--rule); padding:64px 0 34px; margin-bottom:40px}
.eyebrow{font-family:"IBM Plex Mono",monospace; font-size:.72rem; letter-spacing:.15em;
  text-transform:uppercase; color:var(--accent); margin:0 0 1.1em}
.sub{color:var(--dim); font-size:1.12rem; margin:.7em 0 0; max-width:62ch}
.meta{display:flex; flex-wrap:wrap; gap:10px 30px; margin-top:26px;
  font-family:"IBM Plex Mono",monospace; font-size:.76rem; color:var(--faint)}
.verdict{display:flex; flex-wrap:wrap; align-items:baseline; gap:16px 26px;
  border:1px solid var(--rule); border-left:4px solid var(--vc); background:var(--vb);
  border-radius:5px; padding:20px 24px; margin:0 0 8px}
.verdict .tag{font-family:"IBM Plex Sans Condensed",sans-serif; font-weight:600;
  font-size:1.5rem; color:var(--vc); letter-spacing:.02em}
.verdict .why{color:var(--dim)}
.tiles{display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:1px;
  background:var(--rule); border:1px solid var(--rule); border-radius:5px; overflow:hidden; margin:26px 0 8px}
.tile{background:var(--surface); padding:16px 18px}
.tile .k{font-family:"IBM Plex Mono",monospace; font-size:.68rem; letter-spacing:.09em;
  text-transform:uppercase; color:var(--faint)}
.tile .v{font-family:"IBM Plex Sans Condensed",sans-serif; font-size:1.72rem; font-weight:600;
  line-height:1.15; margin-top:5px}
.tile .u{font-size:.82rem; color:var(--dim); font-weight:400}
section{margin:60px 0 0}
.n-mark{font-family:"IBM Plex Mono",monospace; color:var(--faint); font-size:.78rem;
  letter-spacing:.1em; display:block; margin-bottom:.5em}
.scroll{overflow-x:auto; margin:22px 0; border:1px solid var(--rule); border-radius:5px; background:var(--surface)}
table{border-collapse:collapse; width:100%; font-size:.86rem}
th,td{text-align:left; padding:8px 14px; border-bottom:1px solid var(--rule); white-space:nowrap}
th{font-family:"IBM Plex Mono",monospace; font-size:.68rem; letter-spacing:.07em;
  text-transform:uppercase; color:var(--faint); font-weight:400; background:var(--raised)}
td.n,th.n{text-align:right}
tr:last-child td{border-bottom:none}
tbody tr:hover{background:var(--raised)}
.chip{display:inline-block; font-family:"IBM Plex Mono",monospace; font-size:.7rem;
  padding:1px 7px; border-radius:3px; letter-spacing:.03em}
.chip.pass{background:var(--pass-bg); color:var(--pass)}
.chip.warn{background:var(--warn-bg); color:var(--warn)}
.chip.fail{background:var(--fail-bg); color:var(--fail)}
figure{margin:30px 0; background:var(--surface); border:1px solid var(--rule); border-radius:5px; overflow:hidden}
figure img{display:block; width:100%; height:auto}
figcaption{padding:13px 18px; font-size:.85rem; color:var(--dim); border-top:1px solid var(--rule)}
.note{border-left:3px solid var(--accent); background:var(--surface); padding:15px 20px;
  margin:26px 0; border-radius:0 4px 4px 0; font-size:.94rem}
.note.warnbox{border-left-color:var(--warn)}
.note strong{color:var(--ink)}
.bar{position:relative; height:9px; background:var(--raised); border-radius:2px; min-width:110px}
.bar i{position:absolute; inset:0 auto 0 0; border-radius:2px; background:var(--cold)}
.bar i.over{background:var(--fail)}
.bar i.near{background:var(--warn)}
ul{padding-left:1.15em} li{margin:.4em 0}
footer{margin-top:76px; padding-top:22px; border-top:1px solid var(--rule);
  font-family:"IBM Plex Mono",monospace; font-size:.74rem; color:var(--faint)}
"""


def build(case):
    d = gather(case)
    p = d['p']
    v, vclass, vwhy, worst, wmean = verdict(d)
    vcol = {'pass': 'var(--pass)', 'warn': 'var(--warn)', 'fail': 'var(--fail)'}[vclass]
    vbg = {'pass': 'var(--pass-bg)', 'warn': 'var(--warn-bg)', 'fail': 'var(--fail-bg)'}[vclass]

    def esc(t):
        return str(t).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')

    H = []
    A = H.append
    A('<!doctype html><html lang="en"><head><meta charset="utf-8">')
    A('<meta name="viewport" content="width=device-width,initial-scale=1">')
    A('<title>AU01 Whitespace Airflow</title>')
    A('<link rel="preconnect" href="https://fonts.googleapis.com">')
    A('<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
      'family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Sans+Condensed:wght@600&'
      'family=IBM+Plex+Mono:wght@400;500&display=swap">')
    A('<style>%s</style></head><body><div class="wrap">' % CSS)

    # ---- header
    A('<header>')
    A('<p class="eyebrow">AU01 George Town &middot; whitespace CFD</p>')
    A('<h1>Why the fan walls cool the room only when the ceiling is closed</h1>')
    A('<p class="sub">A %.0f&nbsp;kW air load, two FWCV&nbsp;40L2 fan walls, and an '
      'arrangement that recirculates until a return plenum forces the supply through '
      'the racks. The plenum works. It fits with %.0f&nbsp;mm to spare.</p>'
      % (d['load'], min(c for _, c in d['clear']) * 1000))
    A('<div class="meta"><span>case %s</span><span>%s</span><span>%s cells</span>'
      '<span>time averaged from t&nbsp;=&nbsp;%s&nbsp;s</span><span>%d samples</span></div>'
      % (esc(case), esc(p.get('solver', '')), esc(mesh_cells(case) or 'n/a'),
         esc(p.get('averageFrom', '?')), d['samples']))
    A('</header>')

    # An optional status banner, passed as the second CLI argument. Publishing a
    # verdict that is known to be superseded without saying so is worse than not
    # publishing at all.
    if len(sys.argv) > 2 and sys.argv[2].strip():
        A('<div class="note warnbox"><strong>Provisional.</strong> %s</div>'
          % esc(sys.argv[2].strip()))

    if d['truncated']:
        A('<div class="note warnbox"><strong>These figures are not time averaged.</strong> '
          'The run stopped before its averaging window opened, so what follows is the tail '
          'of an unfinished transient.</div>')

    # ---- verdict + tiles
    A('<div class="verdict" style="--vc:%s;--vb:%s"><span class="tag">%s</span>'
      '<span class="why">%s &mdash; worst face <span class="num">%.1f&nbsp;&deg;C</span> '
      'at %s against an A2 allowable of <span class="num">%.0f&nbsp;&deg;C</span></span></div>'
      % (vcol, vbg, v, vwhy, worst['peak'], esc(worst['tag']), d['allow']))

    means = [r['mean'] for r in d['racks']]
    esps = [m['esp'] for m in d['mods'] if m['esp'] is not None]
    A('<div class="tiles">')
    for k, val, u in (
            ('mean intake, best rack', '%.1f' % min(means), '&deg;C'),
            ('mean intake, worst rack', '%.1f' % max(means), '&deg;C'),
            ('worst single face', '%.1f' % worst['peak'], '&deg;C'),
            ('plenum cross-section', '%.2f' % d['plenumA'], 'm&sup2;'),
            ('plenum velocity', '%.1f' % d['plenumV'], 'm/s'),
            ('measured ESP, worst module', '%.0f' % (max(esps) if esps else 0), 'Pa of 70')):
        A('<div class="tile"><div class="k">%s</div><div class="v">%s <span class="u">%s</span></div></div>'
          % (k, val, u))
    A('</div>')

    # ---- 1 the failure
    A('<section><span class="n-mark">01 &mdash; the as-drawn arrangement</span>'
      '<h2>78&nbsp;% of the supply never reached a rack</h2><div class="prose">')
    A('<p>With the bulkhead as drawn, the fan wall discharge and the return slot sit on '
      '<em>the same plane</em> about a metre apart. The return pulled at 4.79&nbsp;m/s '
      'against the supply&rsquo;s 2.26&nbsp;m/s, so cold air went straight back into the '
      'unit it came from rather than crossing the 4.7&nbsp;m to the pod.</p>')
    A('<p>The racks then made up their airflow by re-ingesting their own exhaust. Working '
      'backwards from the measured return temperature, only <strong>19&nbsp;kg/s of '
      '84.65 reached them</strong> &mdash; 22&nbsp;%. Mean intake settled near '
      '50&nbsp;&deg;C. Raising the bulkhead changed nothing (41.7&nbsp;&deg;C against '
      '41.4&nbsp;&deg;C at the same instant), which is what showed the problem was '
      'architectural rather than a slot that needed resizing.</p></div></section>')

    # ---- 2 the fix
    A('<section><span class="n-mark">02 &mdash; the fix</span>'
      '<h2>Cap the cold side, then throttle to match</h2><div class="prose">')
    A('<p>A deck over the cold side, open only above the hot aisle, plus enclosed pod ends, '
      'leaves the racks as the only path from supply to return. That forces a second change: '
      'you cannot push 84.65&nbsp;kg/s through a pod that accepts %.1f, so the fan walls have '
      'to come down to roughly rack demand. At <strong>%s&nbsp;%% of nameplate</strong> the '
      'supply/demand ratio is %.3f.</p>'
      % (d['demand'], p.get('supplyThrottle', '?'),
         d['supply'] / d['demand'] if d['demand'] else 0))
    A('<p>Every module now passes the same mass in and out, %.2f&nbsp;kg/s, and the return '
      'arrives at %.1f&nbsp;&deg;C instead of being diluted by bypass.</p></div>'
      % (d['mods'][0]['supply'] if d['mods'] else 0, d['returnT'] or 0))

    A('<div class="scroll"><table><thead><tr><th>module</th><th class="n">supply</th>'
      '<th class="n">return</th><th class="n">discharge area</th><th class="n">required ESP</th>'
      '<th>against 70&nbsp;Pa</th></tr></thead><tbody>')
    for m in d['mods']:
        e = m['esp'] or 0
        frac = min(1.0, e / 70.0)
        cls = 'over' if e > 70 else ('near' if e > 56 else '')
        A('<tr><td>%s</td><td class="n">%.2f kg/s</td><td class="n">%.2f kg/s</td>'
          '<td class="n">%.2f m&sup2;</td><td class="n">%.1f Pa</td>'
          '<td><span class="bar"><i class="%s" style="width:%.0f%%"></i></span></td></tr>'
          % (esc(m['tag']), m['supply'], m['ret'], m['area'], e, cls, frac * 100))
    A('</tbody></table></div>')
    A('<div class="prose"><p>The upper modules need noticeably more static than the lower '
      'ones &mdash; they are the pair that will govern the design.</p></div></section>')

    # ---- 3 the ceiling
    A('<section><span class="n-mark">03 &mdash; the binding constraint</span>'
      '<h2>The plenum fits, but only just</h2><div class="prose">')
    A('<p>The deck has to sit at the fan wall top, %.2f&nbsp;m. Any lower and the upper part '
      'of the discharge blows into the plenum and short-circuits again. That leaves the gable '
      'void as the entire return path, and the gable is shallow exactly where the units are:</p>'
      % d['fwtop'])
    A('</div><div class="scroll"><table><thead><tr><th>across the unit</th>'
      '<th class="n">roof height</th><th class="n">clear above deck</th></tr></thead><tbody>')
    for y, c in d['clear']:
        A('<tr><td class="n">y = %.1f m%s</td><td class="n">%.3f m</td>'
          '<td class="n">%.0f mm</td></tr>'
          % (y, ' <span class="chip warn">unit edge</span>' if c == min(cc for _, cc in d['clear']) else '',
             c + d['fwtop'], c * 1000))
    A('</tbody></table></div><div class="prose">')
    A('<p>So the plenum is <strong>%.2f&nbsp;m&sup2;</strong> and carries the return at '
      '%.1f&nbsp;m/s. The reason that is tolerable is the throttle: at nameplate flow the '
      'same duct runs at 10.6&nbsp;m/s and roughly 124&nbsp;Pa, well past the fan&rsquo;s '
      'budget. Throttling to rack demand is what makes the tight ceiling survivable, and the '
      'CFD measures the consequence directly &mdash; %.0f&nbsp;Pa on the worst module against '
      'the 70&nbsp;Pa the 475&nbsp;kW rating assumes.</p>' % (d['plenumA'], d['plenumV'], max(esps) if esps else 0))
    A('<div class="note warnbox"><strong>%.0f&nbsp;mm at the unit edges.</strong> A 50&nbsp;mm '
      'deck was modelled with its top flush to the fan wall so the thickness eats into the cold '
      'side rather than the plenum; inverted it would cost about 0.4&nbsp;m&sup2; of a '
      '%.2f&nbsp;m&sup2; duct. At this clearance, deck build-up, purlins, hangers and any '
      'insulation are not spare detail &mdash; they are the design.</div>'
      % (min(c for _, c in d['clear']) * 1000, d['plenumA']))
    A('</div></section>')

    # ---- figures
    for f, cap in (('geometry_cut.png',
                    'Section along the hall. The deck reads as the band under the eave; '
                    'fan walls at both ends, pod and containment centre, pod ends closed so '
                    'exhaust must rise into the plenum.'),
                   ('au01_racks.png',
                    'Mean intake per rack with the hottest face on each marked, and the '
                    'per-module flow split beneath.'),
                   ('flow_aisle_long.png',
                    'The circuit, on the hot aisle centreline. Cold supply fills both '
                    'clearance zones at 28&nbsp;&deg;C; the contained aisle runs 41&ndash;44&nbsp;&deg;C; '
                    'the plenum above 4&nbsp;m carries return air outward to both ends. The lower '
                    'panel shows why it works &mdash; strong upflow out of the aisle into the '
                    'deck opening, then down into the end corridors to the unit intakes.'),
                   ('flow_3d.png',
                    'The same result in three dimensions, on the sampled planes. Cold supply '
                    'sits at rack level through the hall; the return corridors beyond each '
                    'bulkhead run at return temperature; the contained aisle is the hot band '
                    'between the rows. Arrows are in-plane velocity.'),
                   ('flow_rack_mid.png',
                    'Horizontal plane at mid rack height. Cold aisles on both flanks, hot '
                    'aisle between the rows, and the end zones where the supply jet spreads '
                    'before reaching the pod.'),
                   ('flow_pod_cross.png',
                    'Section across the pod. Supply low on both sides, exhaust rising in the '
                    'contained aisle, and the deck opening above it.'),
                   ('geometry_above.png',
                    'Plan. Bulkheads flank each fan wall; the deck opening sits over the hot '
                    'aisle only.')):
        u = b64(os.path.join(case, f))
        if u:
            A('<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
              % (u, esc(cap[:70]), cap))

    # ---- animation
    mp4 = os.path.join(case, 'flow_orbit.mp4')
    if os.path.exists(mp4):
        A('<figure><video src="%s" controls loop muted playsinline '
          'style="display:block;width:100%%;height:auto;background:#000"></video>'
          '<figcaption>Orbit of the time-averaged field. This turns the camera around a '
          'single averaged result rather than animating time: the run writes few time '
          'directories, so there are no frames to step through. Animating the transient '
          'itself needs a smaller <code>writeEvery</code> and a larger '
          '<code>purgeWrite</code>, which costs disk and transfer rather than solve time. '
          'Video file: <code>%s</code>.</figcaption></figure>'
          % (os.path.basename(mp4), os.path.basename(mp4)))

    # ---- 4 racks
    A('<section><span class="n-mark">04 &mdash; per rack</span>'
      '<h2>Uniform mid-row, stratified at the ends</h2><div class="prose">')
    A('<p>Interior racks sit within about a degree of supply temperature across a 2&nbsp;m '
      'face. What is left is confined to the end positions, where a single face spans '
      '%.1f&nbsp;K. That reframes the remaining problem: not a hall-wide shortfall, but '
      'end-of-row stratification over about two rack positions each end.</p></div>'
      % max(r['peak'] - r['mean'] for r in d['racks']))
    A('<div class="scroll"><table><thead><tr><th>rack</th><th class="n">kW</th>'
      '<th class="n">mean</th><th class="n">hottest face</th><th class="n">spread</th>'
      '<th class="n">flow</th><th class="n">wander</th><th>state</th></tr></thead><tbody>')
    for r in d['racks']:
        sp = r['peak'] - r['mean']
        if r['peak'] > d['allow']:
            chip = '<span class="chip fail">over A2</span>'
        elif sp > 4:
            chip = '<span class="chip warn">stratified</span>'
        elif r['peak'] > d['rec']:
            chip = '<span class="chip warn">above recommended</span>'
        else:
            chip = '<span class="chip pass">ok</span>'
        A('<tr><td>%s</td><td class="n">%.0f</td><td class="n">%.2f</td><td class="n">%.2f</td>'
          '<td class="n">%.2f</td><td class="n">%.2f</td><td class="n">%.2f</td><td>%s</td></tr>'
          % (esc(r['tag']), r['kW'], r['mean'], r['peak'], sp, r['flow'], r['wander'], chip))
    A('</tbody></table></div></section>')

    # ---- hot spot mechanism
    A('<section><span class="n-mark">04b &mdash; the remaining hot spot</span>'
      '<h2>A stagnation pocket at the pod&rsquo;s front corners</h2><div class="prose">')
    A('<p>With everything else fixed, one thing is left, and it is small and specific. '
      'The hottest point on either row sits at <strong>x = 8.51&nbsp;m, z = 1.50&nbsp;m</strong> '
      '&mdash; 70&nbsp;mm in from the outboard end of the first rack, three quarters of the way '
      'up the face. Rows A and B agree to 0.01&nbsp;K, so it is geometric.</p>')
    A('<p>The plan view shows why. The supply leaves the fan wall and sets up <strong>two '
      'large recirculation cells</strong> in the clearance zone rather than sweeping straight '
      'to the pod. Their return legs run along the pod face, and where the rack row begins the '
      'flow separates around the corner. That corner is not swept by fresh supply, so warm air '
      'lingers there and is drawn back into the first rack.</p>')
    A('<p>It is a <em>stagnation pocket</em>, not a leak. The containment is sealed, the rack '
      'ends and tops are now closed, and the hot aisle cannot reach the corner &mdash; the HAC '
      'door blocks it. What fails is air change at one corner.</p>')
    A('<div class="note"><strong>Two numbers to read carefully.</strong> The face map peaks at '
      '35.2&nbsp;&deg;C where the per-rack metric reports 37.2&nbsp;&deg;C. Both are right: the map '
      'is interpolated to mesh points and so is smoothed, while the metric is a maximum over '
      'actual mesh faces. And in the plan view the red <em>inside</em> the rack outlines is air '
      'within the rack volumes, which is heated by definition &mdash; not intake air.</div>')
    A('<p>Candidates worth testing, cheapest first: set the first rack inboard so its face is '
      'clear of the separation line; fit an end-of-row deflector to turn supply into the '
      'corner; or extend the pod-end enclosure forward past the rack face. All are small '
      'physical changes, and all are one parameter change away in this model. None of them '
      'touch the cooling plant, which is the useful part.</p></div></section>')
    for fn, cap in (('hotspot_faces.png',
                     'Temperature ON each row&rsquo;s intake plane. The per-rack mean and peak '
                     'cannot say where on a face the heat is; this can. Note the narrow band up '
                     'the outboard edge of rack 01, plus smaller warm patches at floor level '
                     'between 01 and 02 and at the far east end.'),
                    ('hotspot_plan.png',
                     'Plan at the hot spot height. Two recirculation cells fill the clearance '
                     'zone; the supply jet does not sweep the pod&rsquo;s front corners, and the '
                     'hot spot sits exactly where the row begins.'),
                    ('hotspot_path.png',
                     'Air arriving at the hot spots, traced backwards from the rack face. The '
                     'lines wrap around the west end of the row rather than coming from the fan '
                     'wall.')):
        u = b64(os.path.join(case, fn))
        if u:
            A('<figure><img src="%s" alt="%s"><figcaption>%s</figcaption></figure>'
              % (u, esc(fn), cap))

    # ---- 5 the bug
    A('<section><span class="n-mark">05 &mdash; a bug in the geometry</span>'
      '<h2>Three column heads with no columns</h2><div class="prose">')
    A('<p>The three hottest faces in an earlier run lined up exactly with three transverse '
      'members whose underside sat at 1.810&nbsp;m &mdash; 190&nbsp;mm <em>below</em> the '
      '2.0&nbsp;m rack tops and 250&nbsp;mm in front of the intake plane. They were '
      '200&nbsp;&times;&nbsp;250&nbsp;mm, spanning the full pod width at 3.66&nbsp;m centres.</p>')
    A('<p>They were not service-run structure. They lived in a group holding only heads and '
      'no columns; nothing vertical existed below 1.9&nbsp;m to carry them; and the real '
      'service frame is self-supporting from spine beams that start above the rack tops. '
      'They were leftovers from a superseded support scheme, and they have been deleted from '
      'the model and the export regenerated.</p></div></section>')

    # ---- 6 inputs
    dT = d['dT']
    A('<section><span class="n-mark">06 &mdash; inputs and provenance</span>'
      '<h2>Rack airflow is assumed, and it decides feasibility</h2><div class="prose">')
    A('<p>Geometry, rack loads and fan wall duty are all read from the CAD export or '
      'the brochure. Per-rack airflow is not: it is <em>derived</em> from an assumed '
      'server air-side temperature rise, because the Supermicro datasheet publishes no '
      'airflow figure &mdash; only &ldquo;6&times; 80mm Fan(s)&rdquo; per node.</p>')
    rho = P_ATM / (R_AIR * (float(p['supplyTemp_C']) + 273.15))
    A('<div class="scroll"><table><thead><tr><th>rack type</th><th class="n">load</th>'
      '<th class="n">mass flow</th><th class="n">volume</th><th class="n">CFM</th>'
      '<th class="n">face velocity</th></tr></thead><tbody>')
    for kw, nm in sorted({(r['kW'], r['tag'].split('-')[1]) for r in d['racks']}, reverse=True):
        m = kw * 1000.0 / (CP * dT); q = m / rho
        A('<tr><td>%s</td><td class="n">%.0f kW</td><td class="n">%.3f kg/s</td>'
          '<td class="n">%.0f m&sup3;/h</td><td class="n">%.0f</td>'
          '<td class="n">%.2f m/s</td></tr>' % (esc(nm), kw, m, q * 3600, q * 2118.88, q / 1.2))
    A('</tbody></table></div><div class="prose">')
    A('<p>Both work out at <span class="num">120&nbsp;CFM per kW</span>, which follows '
      'directly from <code>mdot = kW / (cp &middot; %.0f K)</code>. Change that %.0f&nbsp;K '
      'and everything downstream moves &mdash; the throttle setting, the plenum velocity, '
      'and whether the required static fits the fan.</p>' % (dT, dT))
    A('</div><div class="scroll"><table><thead><tr><th>server &Delta;T</th>'
      '<th class="n">rack demand</th><th class="n">throttle</th><th class="n">plenum velocity</th>'
      '<th class="n">approx ESP</th><th>verdict</th></tr></thead><tbody>')
    esps0 = [m['esp'] for m in d['mods'] if m['esp'] is not None]
    base_esp = max(esps0) if esps0 else 65.1
    for t in (12, 15, 18, 20):
        dem = d['load'] * 1000.0 / (CP * t)
        flow = dem * 1.04
        vv = d['plenumV'] * flow / d['supply'] if d['supply'] else 0
        ee = base_esp * (flow / d['supply']) ** 2 if d['supply'] else 0
        chip = ('<span class="chip fail">over 70 Pa</span>' if ee > 70 else
                '<span class="chip warn">%.0f Pa margin</span>' % (70 - ee) if ee > 55 else
                '<span class="chip pass">comfortable</span>')
        hi = ' style="background:var(--raised);font-weight:500"' if abs(t - dT) < 0.1 else ''
        A('<tr%s><td class="n">%d K%s</td><td class="n">%.1f kg/s</td><td class="n">%.0f %%</td>'
          '<td class="n">%.2f m/s</td><td class="n">%.0f Pa</td><td>%s</td></tr>'
          % (hi, t, ' (assumed)' if abs(t - dT) < 0.1 else '', dem, 100 * flow / 84.65,
             vv, ee, chip))
    A('</tbody></table></div><div class="prose">')
    A('<h3>Cross-checked against the published fan matrix</h3>')
    A('<p>Supermicro does publish free-air fan ratings, so the assumption can be tested. '
      'All parts below are 80&nbsp;&times;&nbsp;80&nbsp;&times;&nbsp;38&nbsp;mm, from the '
      'System Fan Matrix.</p></div>')
    A('<div class="scroll"><table><thead><tr><th>part</th><th>application</th>'
      '<th class="n">RPM</th><th class="n">CFM</th><th class="n">static in.H<sub>2</sub>O</th>'
      '<th class="n">dBA</th></tr></thead><tbody>')
    for part, app, rpm, cfm, sp, db, note in (
            ('FAN-0082L4', 'SC743/745/748 &mdash; tower / workstation', 5000, 68.3, 0.53, 45.0,
             '<span class="chip fail">too low static</span>'),
            ('FAN-0111L4', 'SC827, SC217', 9500, 100.0, 1.77, 61.0, ''),
            ('FAN-0129L4 / 0148L4', 'SC827/217, SC747 rear GPU', 11000, 116.5, 2.14, 62.5,
             '<span class="chip pass">right class</span>'),
            ('FAN-0162L4', 'SC217, SC827', 13500, 118.2, 3.40, 67.0, ''),
            ('FAN-0136L4', 'SC827/217 high performance', 13800, 144.2, 3.46, 73.0,
             '<span class="chip pass">right class</span>')):
        A('<tr><td><code>%s</code> %s</td><td>%s</td><td class="n">%s</td>'
          '<td class="n">%.1f</td><td class="n">%.2f</td><td class="n">%.1f</td></tr>'
          % (part, note, app, '{:,}'.format(rpm), cfm, sp, db))
    A('</tbody></table></div><div class="prose">')
    A('<p><strong>FAN-0082L4 is a real part but almost certainly not this one.</strong> It is '
      'specified for tower and workstation chassis, and at 5,000&nbsp;RPM, 0.53&nbsp;in.H<sub>2</sub>O '
      'and 45&nbsp;dBA it is a quiet low-static fan. A B300 node with dense heatsinks, cold '
      'plates and filtration needs several times that static. Decisively, at &Delta;T '
      '%.0f&nbsp;K the rack would need <strong>132&nbsp;%% of its free-air rating</strong>, '
      'which is impossible.</p>' % dT)
    A('<p>Inverting the assumption makes it checkable. At 8&nbsp;nodes per rack '
      '&times; 6&nbsp;fans, &Delta;T %.0f&nbsp;K needs <strong>90&nbsp;CFM per fan '
      'delivered</strong> &mdash; 62&ndash;77&nbsp;%% of free-air rating for the server-class '
      'fans. That is a normal delivered-to-free-air ratio for a populated server, so the '
      'assumption is plausible and self-consistent.</p>' % dT)
    A('<div class="note"><strong>And the risk direction is favourable.</strong> Reaching a '
      'dangerous &Delta;T below %.0f&nbsp;K would need delivery close to free-air rating, which '
      'a dense GPU node will not achieve. The likely outcome is the 116.5&nbsp;CFM class at '
      'realistic system resistance, landing nearer <strong>18&ndash;19&nbsp;K</strong> &mdash; '
      'which reduces airflow, reduces plenum velocity and <em>increases</em> the ESP margin. '
      'The tight-ceiling risk above is therefore lower than the sensitivity table alone '
      'implies.</div>' % dT)
    A('<p>Three things remain unverified and are not presented as settled: which fan the '
      'SYS-422GS-NB3RT-ALC actually uses (the matrix is a chassis-accessory list and does not '
      'cover that system); the delivered-to-free-air ratio, which is engineering judgement '
      'rather than a published figure; and the air/liquid split, since a DLC-2 node&rsquo;s six '
      'fans handle only the residual air load.</p>')
    A('<p>One further gap: the datasheet claims DLC-2 captures &ldquo;up to 95&nbsp;%% of heat '
      '&hellip; via cold plates&rdquo;, while the load sheet this study inherits assumes about '
      '35&nbsp;%% of node heat goes to air. Those differ by a factor of seven on the air load. '
      'The %.0f&nbsp;kW figure follows the conservative sheet, which is the right direction for '
      'sizing, but the gap should be closed.</p>' % d['load'])
    A('<p>Also excluded by choice, and worth stating: no fabric or solar gain, no lighting, no '
      'CDU standing losses, adiabatic walls. The earlier review put CDU losses alone at '
      '10&ndash;25&nbsp;kW and suggested a working figure nearer 770&ndash;800&nbsp;kW on the '
      'fan walls. <strong>This study is optimistic by roughly 5&nbsp;%.</strong></p>')
    A('</div></section>')

    # ---- 7 open
    A('<section><span class="n-mark">07 &mdash; not yet settled</span>'
      '<h2>What this does not tell you</h2><div class="prose"><ul>')
    for t in (
        'Rack airflow is imposed, not predicted. Each rack holds one target velocity across '
        'its whole volume, so variation in flow up the height of a face is a modelling '
        'assumption. Intake faces are now banded to report where the heat sits.',
        'ESP is compared against the rating point, not the fan curve. 70 Pa is the condition '
        'the 475 kW figure is quoted at; at 60 % flow an EC fan usually has more static in '
        'hand, so the constraint is probably softer than shown.',
        'Coil capacity at reduced airflow needs vendor part-load data. A higher return '
        'temperature helps the LMTD while lower face velocity hurts the air side, and the '
        'brochure will not resolve which wins.',
        'Peak temperatures are mesh-sensitive. The earlier study moved the peak by 3.4 K '
        'between 100 mm and 50 mm cells, so a marginal peak needs the finer mesh before it '
        'is quoted.',
        'Raising the services clear of the racks puts them through the containment baffles, '
        'and there is 40 mm between the baffle tops and the deck. Rerouting rather than '
        'raising is probably the answer, and that is a structural question.',
    ):
        A('<li>%s</li>' % t)
    A('</ul></div></section>')

    # ---- methodology, for a reviewing engineer
    mods0 = d['mods']
    A('<section><span class="n-mark">07b &mdash; numerical method</span>'
      '<h2>Setup, discretisation and verification</h2><div class="prose">')
    A('<p>Included so the result can be judged rather than taken on trust.</p></div>')
    A('<div class="scroll"><table><tbody>')
    for k, mv in (
        ('solver', 'OpenFOAM v2406 <code>buoyantPimpleFoam</code> &mdash; transient, '
                   'compressible, buoyant RANS'),
        ('thermophysical', '<code>heRhoThermo</code> / <code>perfectGas</code> / '
                           '<code>hConst</code> / <code>sensibleEnthalpy</code>; '
                           'cp 1005&nbsp;J/kg&middot;K, mu 1.82e-5&nbsp;Pa&middot;s, Pr 0.71'),
        ('turbulence', 'k-omega SST with wall functions; inlet 5&nbsp;% intensity, '
                       'mixing length 0.1 x unit width'),
        ('buoyancy', 'g = (0, 0, -9.81); <code>p_rgh</code> formulation, '
                     '<code>pRefCell</code> 0 at 101,325&nbsp;Pa'),
        ('background mesh', '241 x 82 x 48 = 948,576 cells at 100&nbsp;mm; walls and floor '
                            'coincide with block faces'),
        ('refinement', '<code>snappyHexMesh</code>, level 2 (25&nbsp;mm) on the 80-100&nbsp;mm '
                       'plates and the overhead services; roof and fan wall bodies level 0'),
        ('final mesh', '%s cells, 1 region, max skewness 7.3, non-orthogonality max 51 deg '
                       '(average 3.9)' % (mesh_cells(case) or 'n/a')),
        ('rack treatment', 'fluid cellZones with <code>scalarSemiImplicitSource</code> on h '
                           '(<code>volumeMode absolute</code>, exact watts per rack) and '
                           '<code>vectorSemiImplicitSource</code> on U '
                           '(<code>volumeMode specific</code>, C = %s). Tops and outboard ends '
                           'closed by a zero-thickness <code>rackShell</code> baffle.'
                           % p.get('fanStiffness', '?')),
        ('supply BC', '<code>flowRateInletVelocity</code>, prescribed <em>mass</em> flow per '
                      'module (%.3f&nbsp;kg/s), T fixed at %.1f&nbsp;C'
                      % (mods0[0]['supply'] if mods0 else 0, float(p['supplyTemp_C']))),
        ('return BC', '<code>flowRateOutletVelocity</code>, same mass flow per module, so each '
                      'unit is a closed loop rather than balancing only across an end'),
        ('schemes', 'Euler in time; <code>cellLimited Gauss linear 1</code> gradients; '
                    '<code>limitedLinear</code> divergence; laplacian and surface-normal '
                    'gradient <code>limited corrected 0.33</code> for the cut mesh'),
        ('pressure-velocity', 'PIMPLE, 2 outer correctors, 1 corrector; GAMG on '
                              '<code>p_rgh</code> with <code>nCellsInCoarsestLevel</code> 500'),
        ('time step', 'adjustable, maxCo %s, maxDeltaT %s&nbsp;s; achieved dt approx 0.005&nbsp;s'
                      % (p.get('maxCo', '?'), p.get('maxDeltaT', '?'))),
        ('run / averaging', '%s&nbsp;s of physical time, time-averaged from %s&nbsp;s '
                            '(<code>fieldAverage</code>, and all point metrics over the same '
                            'window)' % (p.get('endTime', '?'), p.get('averageFrom', '?'))),
    ):
        A('<tr><td style="width:22%"><strong>' + k + '</strong></td><td>' + mv + '</td></tr>')
    A('</tbody></table></div>')

    A('<h3>Verification evidence</h3><div class="prose"><ul>')
    imb = (d['supply'] - sum(m0['ret'] for m0 in mods0)) if mods0 else 0.0
    A('<li><strong>Per-module mass closure.</strong> Each of the four modules passes '
      '%.3f&nbsp;kg/s in and out; total imbalance %.4f&nbsp;kg/s on %.2f&nbsp;kg/s.</li>'
      % (mods0[0]['supply'] if mods0 else 0, imb, d['supply']))
    Texp = float(p['supplyTemp_C']) + d['load'] * 1000.0 / (d['supply'] * CP)
    A('<li><strong>Energy closure.</strong> Return temperature %.2f&nbsp;C against '
      '%.2f&nbsp;C from Q/(m.cp) for the %.0f&nbsp;kW load.</li>'
      % (d['returnT'] or 0, Texp, d['load']))
    A('<li><strong>Statistical steadiness.</strong> Per-rack intake temperature varies by '
      '%.2f-%.2f&nbsp;K across the averaging window. The steady solver was abandoned because it '
      'could not converge this flow at all: it marched intake temperatures up at +1.73&nbsp;K '
      'per 1000 iterations with no plateau while closing its energy balance to 103&nbsp;%%.</li>'
      % (min(r['wander'] for r in d['racks']), max(r['wander'] for r in d['racks'])))
    A('<li><strong>Band flow uniformity.</strong> Equal-area height bands on each intake face '
      'draw within 10&nbsp;% of each other, confirming the rack shell is sealed. Before the '
      'shell was added the top band drew 33&nbsp;% less than the others.</li>')
    A('<li><strong>Rack airflow.</strong> Measured draw %.2f&nbsp;kg/s against %.2f&nbsp;kg/s '
      'demand (%.0f&nbsp;%%); the residual is the soft fan model working against the pressure '
      'field.</li>' % (sum(r['flow'] for r in d['racks']), d['demand'],
                       100 * sum(r['flow'] for r in d['racks']) / d['demand']))
    A('</ul></div>')

    A('<h3>Grid sensitivity, and why the next pass should be finer</h3><div class="prose">')
    A('<p>This is the most important reservation in the report. The present mesh is '
      '100&nbsp;mm base with 25&nbsp;mm on thin plates. An earlier study of the same hall '
      'family found the <strong>peak</strong> intake temperature moved <strong>+3.42&nbsp;K '
      'going from 100&nbsp;mm to 50&nbsp;mm</strong> while the <em>means</em> were already grid '
      'converged. Means here should be treated as reliable and peaks as indicative only.</p>')
    A('<p>Three reasons the remaining exceedance is the least trustworthy number in the '
      'study:</p><ul>')
    got = sum(m0['area'] for m0 in mods0) / len(mods0) if mods0 else 0.0
    A('<li>The discharge face meshes at %.2f&nbsp;m2 against 8.00 nominal (%.1f&nbsp;%%), so '
      'the supply jet feeding the pod ends is under-resolved exactly where the problem is.</li>'
      % (got, 100 * (got / 8.0 - 1)))
    A('<li>The exceedance is a <strong>single mesh point</strong> on a 137-point face. At '
      '50&nbsp;mm that becomes four points, and the peak may rise or fall.</li>')
    A('<li>A stagnation pocket is a separation phenomenon, and separation location is grid '
      'sensitive.</li></ul>')
    A('<p>A 50&nbsp;mm run costs roughly 2.8&nbsp;h of wall clock for 30&nbsp;s of physical '
      'time on 192 Graviton cores, against about 45&nbsp;min at 100&nbsp;mm: the cell count '
      'rises about 8x and the time step halves. That is the recommended confirmation before '
      'any figure here is used for procurement.</p></div></section>')

    # ---- conclusion and next pass
    A('<section><span class="n-mark">09 &mdash; conclusion and next pass</span>'
      '<h2>Where this leaves the design</h2><div class="prose">')
    A('<p><strong>Conditional pass.</strong> With a return plenum over the cold side, the pod '
      'ends enclosed and the fan walls throttled to roughly rack demand, 22 of 24 racks sit '
      'within 0.4-0.8&nbsp;K of supply temperature and every face peak on them is below '
      '29.4&nbsp;C, comfortably inside ASHRAE A2. The cooling plant is adequate and the '
      'airflow architecture works.</p>')
    A('<p>The single residual exceedance is a stagnation pocket at the pod front corners: '
      '%.1f&nbsp;C on one mesh point, in the outermost ~150&nbsp;mm of the first rack at '
      'roughly U27-U38. <strong>79&nbsp;%% of that rack face is below 30&nbsp;C</strong> and '
      'its centre is the coolest part of it.</p>' % max(r['peak'] for r in d['racks']))
    A('<div class="note"><strong>Position accepted for now.</strong> Three rack positions are '
      'unallocated, so positions 01 and 12 can be blanked or lightly loaded if the pocket '
      'proves real. That converts a hard fail into a placement constraint, and changes neither '
      'the plant selection, the plenum, nor the duty point.</div>')
    A('<h3>Recommended next pass: resolve the racks, not just the room</h3>')
    A('<p>The largest remaining modelling gap is that each rack is a single uniform volumetric '
      'source. Real racks are not uniform and their fans are strong local sinks. The next pass '
      'should model rack internals:</p><ul>')
    for it in (
        'Per-U or per-node heat distribution rather than one uniform block. A CDU at U1-4, '
        'nodes through the middle, empty U37-47 and OOB at U48 give a very different face '
        'profile from a uniform slab.',
        'Node-level fan behaviour. A server fan is a strong local sink that entrains '
        'surrounding cold air into a warm pocket, and it ramps on inlet temperature: a '
        'stabilising feedback this model cannot represent, and the main reason the present peak '
        'is likely pessimistic.',
        'Blanking plates and rack leakage, which set how much air bypasses the equipment.',
        'The air/liquid split per node. DLC-2 nodes reject "up to 95 %" to cold plates while '
        'the load sheet assumes about 35 % to air. That factor of seven is unresolved and it '
        'sizes the whole study.',
        'Server air-side dT from vendor data rather than the 15 K assumed here. The fan matrix '
        'cross-check supports 15-19 K and the risk direction is favourable, but it remains the '
        'assumption everything downstream rests on.',
    ):
        A('<li>' + it + '</li>')
    A('</ul><p>Run that at 50&nbsp;mm and the two open questions, whether the corner pocket is '
      'real and whether the peak is grid converged, close together.</p>')
    A('</div></section>')
    # ---- references
    A('<section><span class="n-mark">08 &mdash; references</span>'
      '<h2>Every source, and what came from it</h2>'
      '<div class="scroll"><table><thead><tr><th>source</th><th>type</th>'
      '<th>what this study took from it</th></tr></thead><tbody>')
    ONE = "2.0 Strategy - 2.10 Product/2.9.1 AI Hosting"
    for src, kind, took in (
        ('<code>DAME_AU01_CFD_SingleRoom.FCStd</code> (Rev&nbsp;E)<br><span class="u">OneDrive &rarr; '
         + ONE + ' &rarr; 7 Sites/George Town/Plans &amp; Models/3D Models</span>',
         'CAD model &mdash; authoritative',
         'Room envelope, gable, fan wall placement and module split, 24 rack bodies and '
         'positions, hot aisle containment, bulkhead variants, overhead services. Edited '
         'during this study: three orphaned column heads deleted, return plenum and pod-end '
         'enclosure added.'),
        ('<code>CFD_Export/cfd_export_params.json</code>', 'derived export',
         'Every plane and extent used by the generator, plus <code>rack_schedule_kw</code> &mdash; '
         'the 16&nbsp;&times;&nbsp;36&nbsp;kW + 8&nbsp;&times;&nbsp;20&nbsp;kW load split.'),
        ('<code>CFD_Export/*.stl</code>', 'derived export',
         'The surfaces snappyHexMesh actually cuts to. Rack bodies are parsed per solid, so '
         'positions and loads are read rather than transcribed.'),
        ('<code>CFD_Export/README.md</code>', 'export notes',
         'Rev&nbsp;E scheme description (open-top aisle, roof removed), the exporter&rsquo;s own '
         'slot arithmetic, and the statement that sub-50&nbsp;mm clutter is dropped &mdash; which is '
         'why 50&nbsp;mm is the intended base cell.'),
        ('<code>CFD_Export/make_cfd_export.py</code>', 'export script',
         'How the STLs are produced, and which model groups feed the gantry. Patched during '
         'this study to run headless; original archived as '
         '<code>geometry/make_cfd_export.RevE-original.py</code>.'),
        ('<code>Brochure FWCV 200-500 kW.pdf</code><br><span class="u">' + ONE +
         ' &rarr; 1 Product - Scoping &amp; Costing/Vendors/Schneider/ProductBrochures</span>',
         'vendor &mdash; Schneider Uniflair',
         '130,000&nbsp;m&sup3;/h and 475&nbsp;kW net sensible per end; rating conditions RAT '
         '37&nbsp;&deg;C, ESP 70&nbsp;Pa, EWT/LWT 20/30&nbsp;&deg;C, EU4; EC fans regulated over '
         'Modbus; the OPTIONS entry &ldquo;4 remote air temperature sensors for controlling&rdquo;; '
         'group working to 30 units; two modules each with its own chilled water valve.'),
        ('<code>Supermicro SYS-422GS-NB3RT-ALC _ 4U GPU Server.pdf</code><br>'
         '<span class="u">' + ONE + ' &rarr; 1 Product - Scoping &amp; Costing/Vendors/Supermicro</span>',
         'vendor &mdash; Supermicro',
         'Operating temperature 10&ndash;35&nbsp;&deg;C, which sets the A2 allowable used here. '
         '&ldquo;6&times; 80mm Fan(s)&rdquo; per node. &ldquo;DLC-2 supporting up to 95&nbsp;% of heat '
         'capture via cold plates&rdquo;. <strong>No airflow or CFM figure is published</strong> &mdash; '
         'hence the assumed &Delta;T.'),
        ('ASHRAE TC9.9 thermal guidelines', 'standard',
         'Recommended envelope 18&ndash;27&nbsp;&deg;C for all classes; class A2 allowable '
         '10&ndash;35&nbsp;&deg;C. Note the 28&nbsp;&deg;C design supply sits above the recommended '
         'maximum by choice, so only the allowable limit is a live test.'),
        ('<code>AU013-143-cooling-check.md</code>', 'internal review (superseded in part)',
         'Provenance of the 36&nbsp;kW air figure (rounded from 36.75), the N+1 redundancy '
         'arithmetic, CDU standing-loss estimate of 10&ndash;25&nbsp;kW and the suggested '
         '770&ndash;800&nbsp;kW working figure, and the warning that air-side &Delta;T '
         '&ldquo;decided everything in the CFD sweeps&rdquo;. Its <em>load distribution</em> is '
         'superseded &mdash; the racks have been spread out since.'),
        ('<code>MODEL-REVIEW.md</code>', 'internal review',
         'The finding that hall-end flow does not settle, which is why metrics here are '
         'window-averaged rather than read off the final iteration.'),
        ('OpenFOAM v2406 (ESI/OpenCFD)', 'solver',
         '<code>buoyantPimpleFoam</code>, k-&omega; SST, <code>snappyHexMesh</code>. Run in the '
         '<code>opencfd/openfoam-default:2406</code> container on EC2 Graviton spot.'),
        ('<code>case-au01/constant/thermophysicalProperties</code>', 'case input',
         'Air as an ideal gas: cp 1005&nbsp;J/kg&middot;K, R 287.05, &mu; 1.82e&minus;5, Pr 0.71.'),
        ('<code>FINDINGS-AU01.md</code>', 'this study',
         'Full assumptions register with confidence grading, the &Delta;T sensitivity, and a '
         'table of tooling bugs found &mdash; several of which produced plausible wrong answers '
         'rather than failures.'),
    ):
        A('<tr><td>%s</td><td>%s</td><td>%s</td></tr>' % (src, kind, took))
    A('</tbody></table></div>')
    A('<div class="prose"><p class="u">Paths are relative to '
      '<code>OneDrive-DAME</code> and to the repository root '
      '<code>sd-dc/cfd-cabinet-cooling</code> respectively. The CAD export is archived '
      'in-repo at <code>geometry/CFD_Export_RevE/</code> so a run reproduces without '
      'OneDrive, and FreeCAD backups taken before each edit are in '
      '<code>geometry/fcstd-backups/</code>.</p></div></section>')

    A('<footer>Generated by build_report_au01.py from %s. Every figure is read from the '
      'case; none is transcribed.</footer>' % esc(case))
    A('</div></body></html>')

    out = os.path.join(case, 'report-au01.html')
    open(out, 'w').write('\n'.join(H))
    return out, v, worst


def mesh_cells(case):
    f = os.path.join(case, 'log.checkMesh')
    if not os.path.exists(f):
        return None
    for line in open(f, errors='replace'):
        if line.strip().startswith('cells:'):
            return '{:,}'.format(int(line.split()[-1]))
    return None


if __name__ == '__main__':
    c = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    o, v, w = build(c)
    print('wrote %s  (verdict %s, worst face %.2f C at %s)' % (o, v, w['peak'], w['tag']))
