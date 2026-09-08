#!/usr/bin/env python3
"""
Read an AU01 whitespace run and say whether the hall holds inside ASHRAE A2.

    ./plot_au01.py case-au01

Metrics are averaged over a window of the last samples rather than read off the
final iteration. The hall-end flow in this geometry does not settle to a steady
state - MODEL-REVIEW.md flagged that the previous study's numbers were
last-iteration snapshots of an oscillating solve - so a single sample carries
several tenths of a degree of noise on exactly the racks that decide the verdict.
"""

import glob
import json
import os
import sys

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

WINDOW = 50          # samples averaged at the tail of the run
CP = 1005.0


def read_params(path):
    out = {}
    for line in open(path):
        line = line.split('#', 1)[0].strip()
        if line:
            b = line.split(None, 1)
            if len(b) == 2:
                out[b[0]] = b[1].strip()
    return out


def series(case, name, col=1):
    """All (time, value) rows of a function object, oldest first."""
    hits = sorted(glob.glob(os.path.join(case, 'postProcessing', name, '*', '*.dat')),
                  key=lambda p: float(os.path.basename(os.path.dirname(p))))
    rows = []
    for f in hits:
        for line in open(f):
            if line.startswith('#') or not line.strip():
                continue
            p = line.split()
            if len(p) > col:
                rows.append((float(p[0]), float(p[col])))
    return rows


# Set from the parameter file: on a transient run the average is taken over the
# whole averaging window rather than a fixed number of samples, so it matches the
# window fieldAverage used for the written fields.
FROM = None


WINDOW_EMPTY = False


def _window(rows, w=WINDOW):
    global WINDOW_EMPTY
    if FROM is not None:
        sel = [(t, x) for t, x in rows if t >= FROM]
        if sel:
            return sel
        # Falling back silently here once reported a truncated 14 s run as
        # "time averaged from t = 35 s". Never do that quietly again.
        WINDOW_EMPTY = True
    return rows[-w:]


def tail_mean(rows, w=WINDOW):
    if not rows:
        return None, 0
    v = [x for _, x in _window(rows, w)]
    return sum(v) / len(v), len(v)


def tail_spread(rows, w=WINDOW):
    if not rows:
        return 0.0
    v = [x for _, x in _window(rows, w)]
    return max(v) - min(v)


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    p = read_params(os.path.join(case, 'system', 'au01Parameters'))
    with open(os.path.join(case, 'system', 'cfd_export_params.json')) as fh:
        g = json.load(fh)
    sched = g['rack_schedule_kw']
    global FROM
    if p.get('solver', '').endswith('PimpleFoam'):
        FROM = float(p['averageFrom'])
    allow = float(p['allowableMax_C'])
    rec = float(p['recommendedMax_C'])
    dT = float(p['serverDeltaT_K'])
    load = sum(sched.values())

    def order(tag):
        return (tag[0], int(tag[1:3]))

    tags = sorted(sched, key=order)

    # ---- per rack -----------------------------------------------------
    racks = []
    for tag in tags:
        mean, n = tail_mean(series(case, 'r%s_inletT' % tag))
        peak, _ = tail_mean(series(case, 'r%s_inletTmax' % tag))
        flow, _ = tail_mean(series(case, 'r%s_flow' % tag))
        if mean is None:
            sys.exit('no metrics for rack %s - did the run write postProcessing?' % tag)
        racks.append(dict(tag=tag, kW=sched[tag], n=n,
                          mean=mean - 273.15, peak=peak - 273.15,
                          flow=abs(flow),
                          wander=tail_spread(series(case, 'r%s_inletT' % tag))))

    # ---- fan wall -----------------------------------------------------
    mods = []
    for end in ('W', 'E'):
        for m in (1, 2):
            s, _ = tail_mean(series(case, 'supply%s%d_flow' % (end, m), 2))
            i, _ = tail_mean(series(case, 'intake%s%d_flow' % (end, m), 2))
            a, _ = tail_mean(series(case, 'supply%s%d_flow' % (end, m), 1))
            if s is not None:
                mods.append(dict(tag='%s%d' % (end, m), supply=-s,
                                 intake=i if i is not None else 0.0, area=a))
    # measured external static per module: discharge p_rgh less return p_rgh
    for m in mods:
        # the _p function objects inherit writeArea from _flow, so the value
        # sits in column 2, and they write their own directory
        ps, _ = tail_mean(series(case, 'supply%s_p' % m['tag'], 2))
        pi, _ = tail_mean(series(case, 'intake%s_p' % m['tag'], 2))
        m['esp'] = (ps - pi) if (ps is not None and pi is not None) else None

    supply = sum(m['supply'] for m in mods)
    intake = sum(m['intake'] for m in mods)

    # ---- integrity checks --------------------------------------------
    problems = []

    if mods:
        imbal = (supply - intake) / supply
        if abs(imbal) > 0.01:
            problems.append('mass imbalance %.2f %% of supply' % (100 * imbal))
        # The flow rate is prescribed, so a short area does not under-supply the
        # hall - but it does mean the discharge face, and therefore the supply
        # jet that feeds the end racks, is poorly resolved.
        got = sum(m['area'] for m in mods) / len(mods)
        if abs(got / 8.0 - 1.0) > 0.02:
            problems.append('discharge face meshed at %.2f m2 vs 8.00 nominal '
                            '(%.1f %%) - the supply jet is under-resolved, '
                            'refine before trusting end-rack numbers'
                            % (got, 100 * (got / 8.0 - 1.0)))
    tmax, _ = tail_mean(series(case, 'roomT'))
    if tmax is not None and tmax > 372.0:
        problems.append('room T is at the 373 K limiter - the guard is binding, '
                        'so the field is not trustworthy')

    rflow = sum(r['flow'] for r in racks)
    demand = load * 1000.0 / (CP * dT)

    # ---- verdict ------------------------------------------------------
    worst = max(racks, key=lambda r: r['peak'])
    worst_mean = max(racks, key=lambda r: r['mean'])
    if worst['peak'] > allow:
        verdict, why = 'FAIL', 'a rack face exceeds A2 allowable'
    elif worst_mean['mean'] > allow:
        verdict, why = 'FAIL', 'a rack mean intake exceeds A2 allowable'
    elif worst['peak'] > rec:
        verdict, why = 'MARGINAL', 'inside allowable but above the recommended envelope'
    else:
        verdict, why = 'PASS', 'every intake is inside the recommended envelope'

    # ---- report -------------------------------------------------------
    print('AU01 whitespace - %s' % case)
    print('  load %.0f kW air over %d racks, supply %.1f C, dT %.1f K'
          % (load, len(racks), float(p['supplyTemp_C']), dT))
    print('  bulkhead %s, gantry %s, units off: %s'
          % (p['bulkhead'], 'in' if p.get('gantry', '1') != '0' else 'out',
             p.get('unitsOff', 'none')))
    if FROM is not None and not WINDOW_EMPTY:
        print('  time averaged over %d samples from t = %.0f s (matches fieldAverage)'
              % (racks[0]['n'], FROM))
    elif WINDOW_EMPTY:
        last = max(t for t, _ in series(case, 'r%s_inletT' % tags[0]))
        print('  *** NOT TIME AVERAGED: the run reached only t = %.2f s, and the'
              % last)
        print('  *** averaging window starts at %.0f s. Showing the last %d'
              % (FROM, WINDOW))
        print('  *** samples instead. These are not converged figures.')
    else:
        print('  averaged over the last %d samples' % racks[0]['n'])
    print()
    print('  supply %.2f kg/s   return %.2f kg/s   rack draw %.2f kg/s (demand %.2f)'
          % (supply, intake, rflow, demand))
    for m in mods:
        esp = '' if m.get('esp') is None else '   ESP %6.1f Pa' % m['esp']
        print('    module %-3s supply %6.2f  return %6.2f kg/s%s'
              % (m['tag'], m['supply'], m['intake'], esp))
    esps = [m['esp'] for m in mods if m.get('esp') is not None]
    if esps:
        print('    worst module ESP %.1f Pa against a 70 Pa budget' % max(esps))
        if max(esps) > 70.0:
            problems.append('required ESP %.0f Pa exceeds the 70 Pa the 475 kW '
                            'rating assumes - the duty point is not achievable '
                            'as modelled' % max(esps))
    print()
    print('  %-10s %5s %7s %7s %7s' % ('rack', 'kW', 'mean C', 'peak C', 'wander'))
    for r in racks:
        flag = '  <-- worst' if r['tag'] == worst['tag'] else ''
        print('  %-10s %5.0f %7.2f %7.2f %7.2f%s'
              % (r['tag'], r['kW'], r['mean'], r['peak'], r['wander'], flag))
    # Height bands: a whole-face average cannot say WHERE the heat is, and the
    # end racks turn out to be stratified rather than uniformly warm.
    nb = int(float(p.get('intakeBands', 0)))
    if nb:
        band = {}
        for r in racks:
            vals = []
            for b in range(1, nb + 1):
                T, _ = tail_mean(series(case, 'r%s_b%d_T' % (r['tag'], b)))
                Q, _ = tail_mean(series(case, 'r%s_b%d_flow' % (r['tag'], b)))
                vals.append((None if T is None else T - 273.15,
                             None if Q is None else abs(Q)))
            band[r['tag']] = vals
        got = [t for t in band if band[t] and band[t][0][0] is not None]
        if got:
            print()
            print('  intake face by height band (band 1 = floor, %d = rack top)' % nb)
            print('  %-10s %s' % ('rack', '  '.join('b%d T / kg/s' % b
                                                    for b in range(1, nb + 1))))
            order = sorted(got, key=lambda t: -(max(v[0] for v in band[t])
                                                - min(v[0] for v in band[t])))
            for tag in order[:6] + ['--'] + order[-2:]:
                if tag == '--':
                    print('  %-10s ...' % '')
                    continue
                cells = '  '.join('%5.2f /%5.2f' % (v[0], v[1]) for v in band[tag])
                sp = max(v[0] for v in band[tag]) - min(v[0] for v in band[tag])
                print('  %-10s %s   spread %.2f K' % (tag, cells, sp))

    print()
    print('  worst mean %.2f C at %s;  worst face %.2f C at %s'
          % (worst_mean['mean'], worst_mean['tag'], worst['peak'], worst['tag']))
    print('  A2 allowable %.1f C, recommended %.1f C' % (allow, rec))
    print('  VERDICT: %s - %s' % (verdict, why))
    if WINDOW_EMPTY:
        problems.append('run did not reach its averaging window - these are '
                        'tail samples of an unfinished transient, not a time '
                        'average, and the peaks in particular are still developing')
    drift = max(r['wander'] for r in racks)
    if drift > 2.0:
        problems.append('rack intake temperatures swing by up to %.1f K within the '
                        'averaging window - the flow has not settled, so treat the '
                        'per-rack figures as indicative only' % drift)
    if problems:
        print()
        print('  CHECK THESE BEFORE QUOTING ANY OF THE ABOVE:')
        for w in problems:
            print('    - %s' % w)

    # ---- chart --------------------------------------------------------
    # Two earlier versions of this chart were misleading and both are worth
    # recording. The first coloured bars by rack LOAD, which put red on the cool
    # middle racks and blue on the hot end ones - it read backwards from the
    # finding. The second fixed the colour but kept an absolute temperature axis
    # from zero, which squashed the entire result into a 4 K band near the top.
    #
    # This one plots RISE ABOVE SUPPLY, which has a real zero, so the variation
    # is the thing you see. Note the recommended 27 C envelope sits BELOW the
    # 28 C supply, so it is unattainable by choice of supply temperature, not by
    # anything the airflow does - plotting it as a threshold would imply a test
    # the design cannot pass and was never trying to.
    Tsup = float(p['supplyTemp_C'])
    allow_rise = allow - Tsup
    fig, (ax, bx) = plt.subplots(2, 1, figsize=(13, 7.6),
                                 gridspec_kw=dict(height_ratios=[3, 1.15]))
    xs = list(range(len(racks)))

    def state(v_abs):
        return '#b3261e' if v_abs > allow else ('#c9871a' if v_abs > allow - 3 else '#41708c')

    ax.bar(xs, [r['mean'] - Tsup for r in racks],
           color=[state(r['mean']) for r in racks], label='mean intake rise')
    ax.scatter(xs, [r['peak'] - Tsup for r in racks], marker='v', s=46, zorder=3,
               facecolors=[state(r['peak']) for r in racks],
               edgecolors='#1b2430', linewidths=.7, label='hottest face on the rack')
    ax.axhline(allow_rise, color='#b3261e', ls='--', lw=1.4,
               label='A2 allowable, %.0f C = +%.0f K on supply' % (allow, allow_rise))
    ax.set_xticks(xs)
    ax.set_xticklabels([r['tag'] for r in racks], rotation=90, fontsize=7)
    ax.set_ylabel('intake temperature rise above %.0f C supply (K)' % Tsup)
    ax.set_ylim(0, max(allow_rise, max(r['peak'] for r in racks) - Tsup) * 1.12)
    ax.set_title('%s  |  %.0f kW air, %s, %s%% of nameplate airflow  |  VERDICT %s'
                 % (case, load, p['bulkhead'], p.get('supplyThrottle', '?'), verdict))
    ax.legend(fontsize=8, loc='upper center', ncol=3, framealpha=.95)
    ax.grid(axis='y', alpha=.3)
    ax.margins(x=.01)

    # Per-module flow is balanced by construction now, so plotting it says
    # nothing. Required external static is the per-module number that matters.
    esps = [m.get('esp') for m in mods]
    if any(e is not None for e in esps):
        tags = [m['tag'] for m in mods]
        vals = [e or 0 for e in esps]
        bx.bar(tags, vals, color=['#b3261e' if v > 70 else
                                  ('#c9871a' if v > 56 else '#41708c') for v in vals])
        bx.axhline(70, color='#b3261e', ls='--', lw=1.4)
        bx.text(len(tags) - .45, 70, ' 70 Pa rating point', va='center',
                fontsize=8, color='#b3261e')
        for i, v in enumerate(vals):
            bx.text(i, v + 1.5, '%.0f' % v, ha='center', fontsize=8)
        bx.set_ylabel('required ESP (Pa)')
        bx.set_ylim(0, max(80, max(vals) * 1.25))
        bx.set_title('external static each module must provide - the upper modules govern',
                     fontsize=9)
    else:
        bx.bar([m['tag'] for m in mods], [m['supply'] for m in mods], color='#41708c')
        bx.set_ylabel('supply kg/s')
    bx.grid(axis='y', alpha=.3)

    fig.tight_layout()
    out = os.path.join(case, 'au01_racks.png')
    fig.savefig(out, dpi=130)
    print()
    print('  chart: %s' % out)


if __name__ == '__main__':
    main()
