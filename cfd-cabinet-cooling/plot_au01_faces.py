#!/usr/bin/env python3
"""
Draw the rack intake faces to scale and mark where the heat is.

    ./plot_au01_faces.py case-au01

The per-rack metrics are a mean and a max over each face's mesh faces, so the
faces are drawn filled at their mean with the peak called out separately. The
height of the peak within a face is NOT resolved by those two numbers - the
height bands added on 20 Aug are what will place it - so this deliberately does
not pretend to know. What it does add is the measured mid-height profile along
each row, which is real spatial data from the sampled plane.
"""

import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle

import plot_au01 as P

STEEL, AMBER, RED = '#41708c', '#c9871a', '#b3261e'


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    p = P.read_params(os.path.join(case, 'system', 'au01Parameters'))
    with open(os.path.join(case, 'system', 'cfd_export_params.json')) as fh:
        g = json.load(fh)
    if p.get('solver', '').endswith('PimpleFoam'):
        P.FROM = float(p['averageFrom'])
    Tsup = float(p['supplyTemp_C'])
    allow = float(p['allowableMax_C'])
    s = float(g['scale'])

    # real rack geometry, per solid
    solids = []
    name = None
    bb = {}
    for line in open(os.path.join(case, 'constant', 'triSurface', 'racks_body.stl'),
                     errors='replace'):
        t = line.strip()
        if t.startswith('solid'):
            name = t[5:].strip()
            bb[name] = [1e30, -1e30, 1e30, -1e30, 1e30, -1e30]
        elif t.startswith('vertex') and name:
            v = [float(q) for q in t.split()[1:4]]
            b = bb[name]
            for i in range(3):
                b[2 * i] = min(b[2 * i], v[i]); b[2 * i + 1] = max(b[2 * i + 1], v[i])
    racks = {}
    for n, b in bb.items():
        tag = n.split('_', 1)[1]
        racks[tag] = dict(x0=b[0], x1=b[1], z1=b[5], row=tag[0])

    for tag in racks:
        m, _ = P.tail_mean(P.series(case, 'r%s_inletT' % tag))
        pk, _ = P.tail_mean(P.series(case, 'r%s_inletTmax' % tag))
        racks[tag]['mean'] = None if m is None else m - 273.15
        racks[tag]['peak'] = None if pk is None else pk - 273.15
    have = [t for t in racks if racks[t]['mean'] is not None]
    if not have:
        sys.exit('no per-rack metrics found')

    lo = Tsup - 0.5
    hi = max(allow + 1, max(racks[t]['peak'] for t in have))

    def col(v):
        return RED if v > allow else (AMBER if v > allow - 3 else STEEL)

    import matplotlib.colors as mc
    cmap = mc.LinearSegmentedColormap.from_list(
        'f', ['#123a4f', '#2d6a86', '#63a6b4', '#cdd9c8', '#e8c07a', '#cf8342', '#a33a20'])
    norm = mc.Normalize(vmin=lo, vmax=hi)

    fig = plt.figure(figsize=(13.6, 8.6))
    gs = fig.add_gridspec(3, 1, height_ratios=[1.35, 1.35, 1.3], hspace=.55)
    axes = [fig.add_subplot(gs[0]), fig.add_subplot(gs[1])]
    prof = fig.add_subplot(gs[2])

    for ax, row in zip(axes, ('A', 'B')):
        tags = sorted([t for t in have if racks[t]['row'] == row],
                      key=lambda t: racks[t]['x0'])
        for t in tags:
            r = racks[t]
            w = r['x1'] - r['x0']
            ax.add_patch(Rectangle((r['x0'], 0), w, r['z1'],
                                   facecolor=cmap(norm(r['mean'])),
                                   edgecolor='#1b2430', linewidth=.8))
            ax.text(r['x0'] + w / 2, -0.17, t.split('-')[0], ha='center',
                    va='top', fontsize=7.5, rotation=0)
            ax.text(r['x0'] + w / 2, r['z1'] / 2, '%.1f' % r['mean'], ha='center',
                    va='center', fontsize=7.5,
                    color='white' if r['mean'] > allow - 6 else '#eef3f6')
            # peak called out above the face; its height within the face is unknown
            pk = r['peak']
            ax.plot([r['x0'] + w / 2], [r['z1'] + .22], marker='v', ms=8,
                    color=col(pk), markeredgecolor='#1b2430', markeredgewidth=.6)
            ax.text(r['x0'] + w / 2, r['z1'] + .40, '%.1f' % pk, ha='center',
                    va='bottom', fontsize=7.5, color=col(pk),
                    fontweight='bold' if pk > allow else 'normal')
        x0 = min(racks[t]['x0'] for t in tags)
        x1 = max(racks[t]['x1'] for t in tags)
        ax.set_xlim(x0 - .12, x1 + .12)
        ax.set_ylim(-.45, racks[tags[0]]['z1'] + .95)
        ax.set_aspect('equal')
        ax.set_yticks([0, 1, 2])
        ax.set_ylabel('height (m)', fontsize=8)
        ax.tick_params(labelsize=7)
        ax.set_title('Row %s intake faces, drawn to scale - fill is the face mean, '
                     'marker above is the hottest ~60 mm patch on that face'
                     % row, fontsize=9.5, loc='left')
        for sp in ('top', 'right'):
            ax.spines[sp].set_visible(False)

    # measured mid-height profile from the sampled plane
    times = sorted(glob.glob(os.path.join(case, 'postProcessing', 'slices', '*')),
                   key=lambda q: float(os.path.basename(q)))
    drawn = False
    if times:
        f = os.path.join(times[-1], 'T_rack_mid.raw')
        if os.path.exists(f):
            T = np.loadtxt(f, comments='#')
            x, y, tt = T[:, 0], T[:, 1], T[:, 3] - 273.15
            rows = g['racks']['rows']
            for row, c in (('A', '#1f6f8b'), ('B', '#a3562a')):
                iy = rows[row]['intake_y'] * s
                m = np.abs(y - iy) < 0.09
                o = np.argsort(x[m])
                prof.plot(x[m][o], tt[m][o], lw=1.4, color=c, label='row %s' % row)
            prof.axhline(allow, color=RED, ls='--', lw=1.2,
                         label='A2 allowable %.0f C' % allow)
            prof.axhline(Tsup, color='#41708c', ls=':', lw=1.2,
                         label='supply %.0f C' % Tsup)
            prof.set_xlim(axes[0].get_xlim())
            prof.set_xlabel('x along the row (m)', fontsize=8)
            prof.set_ylabel('air temperature (C)', fontsize=8)
            prof.set_title('Measured temperature just in front of the intake planes at '
                           'mid height (z = 1.0 m) - real spatial data, one height only',
                           fontsize=9.5, loc='left')
            prof.legend(fontsize=7.5, ncol=4)
            prof.grid(alpha=.3)
            prof.tick_params(labelsize=7)
            drawn = True
    if not drawn:
        prof.axis('off')

    sm = plt.cm.ScalarMappable(norm=norm, cmap=cmap)
    cb = fig.colorbar(sm, ax=axes, orientation='vertical', pad=.012, aspect=26)
    cb.set_label('face mean intake temperature (C)', fontsize=8)
    cb.ax.tick_params(labelsize=7)

    out = os.path.join(case, 'face_map.png')
    fig.savefig(out, dpi=130, bbox_inches='tight')
    print('  wrote %s' % out)


if __name__ == '__main__':
    main()
