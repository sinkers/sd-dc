#!/usr/bin/env python3
"""
Turn the sampled planes into airflow diagrams.

    ./plot_au01_slices.py case-au01

Three planes come out of the `slices` function object: a horizontal one at
mid-rack height, a vertical one along the hall on the hot aisle centreline, and a
vertical one across the pod. Each is drawn twice - temperature, and speed with
flow direction - because the interesting question is not how hot the air is but
where it goes.
"""

import glob
import json
import os
import sys

import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
from scipy.interpolate import griddata

# cold -> warm, deliberately not jet: a perceptually ordered ramp so a reader
# cannot invent structure that is not in the data
COOL = LinearSegmentedColormap.from_list('coolwarm_dc', [
    '#0b3b52', '#186b8a', '#41a3b8', '#a8cfc4', '#efe0a8',
    '#e0a45c', '#c2622f', '#8f2f1c'])


def read_raw(path):
    d = np.loadtxt(path, comments='#')
    return d


def params(case):
    out = {}
    for line in open(os.path.join(case, 'system', 'au01Parameters')):
        line = line.split('#', 1)[0].strip()
        if line:
            b = line.split(None, 1)
            if len(b) == 2:
                out[b[0]] = b[1].strip()
    return out


def grid(x, y, v, n=(900, 320)):
    xi = np.linspace(x.min(), x.max(), n[0])
    yi = np.linspace(y.min(), y.max(), n[1])
    X, Y = np.meshgrid(xi, yi)
    Z = griddata((x, y), v, (X, Y), method='linear')
    return X, Y, Z


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    p = params(case)
    with open(os.path.join(case, 'system', 'cfd_export_params.json')) as fh:
        g = json.load(fh)
    s = float(g['scale'])
    Tsup = float(p['supplyTemp_C'])
    allow = float(p['allowableMax_C'])

    times = sorted(glob.glob(os.path.join(case, 'postProcessing', 'slices', '*')),
                   key=lambda q: float(os.path.basename(q)))
    if not times:
        sys.exit('no sampled slices - run: postProcess -func slices -latestTime')
    d = times[-1]
    t = float(os.path.basename(d))

    # plane -> (horizontal axis index, vertical axis index, labels, aspect)
    planes = {
        'rack_mid':   (0, 1, 'x along the hall (m)', 'y across the hall (m)',
                       'horizontal plane at mid rack height, z = 1.0 m'),
        'aisle_long': (0, 2, 'x along the hall (m)', 'z height (m)',
                       'vertical plane along the hall on the hot aisle centreline'),
        'pod_cross':  (1, 2, 'y across the hall (m)', 'z height (m)',
                       'vertical plane across the pod at mid length'),
    }

    made = []
    for name, (ia, ib, xl, yl, title) in planes.items():
        ft = os.path.join(d, 'T_%s.raw' % name)
        fu = os.path.join(d, 'U_%s.raw' % name)
        if not (os.path.exists(ft) and os.path.exists(fu)):
            continue
        T = read_raw(ft)
        U = read_raw(fu)
        xa, ya, Tv = T[:, ia], T[:, ib], T[:, 3] - 273.15
        ua, va = U[:, ia], U[:, ib]
        Uv = np.linalg.norm(U[:, 3:6], axis=1)
        # in-plane components for the arrows
        cu, cv = U[:, 3 + ia], U[:, 3 + ib]

        span = (xa.max() - xa.min()) / max(1e-9, (ya.max() - ya.min()))
        h = 4.2 if span > 4 else 6.0
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(13.4, h * 1.45))

        X, Y, Z = grid(xa, ya, Tv)
        lo, hi = Tsup - 0.5, max(allow + 2, np.nanpercentile(Z, 99.5))
        im = a1.pcolormesh(X, Y, Z, cmap=COOL, vmin=lo, vmax=hi, shading='auto')
        cs = a1.contour(X, Y, Z, levels=[allow], colors='#111', linewidths=1.1)
        a1.clabel(cs, fmt='%.0f C allowable', fontsize=7)
        cb = fig.colorbar(im, ax=a1, pad=.01, aspect=32)
        cb.set_label('air temperature (C)', fontsize=8)
        a1.set_title('%s  -  temperature, t = %.1f s' % (title, t), fontsize=10)

        Xu, Yu, Zu = grid(ua, va, Uv)
        im2 = a2.pcolormesh(Xu, Yu, Zu, cmap='BuPu', vmin=0,
                            vmax=np.nanpercentile(Zu, 99), shading='auto')
        cb2 = fig.colorbar(im2, ax=a2, pad=.01, aspect=32)
        cb2.set_label('air speed (m/s)', fontsize=8)
        # decimate to a readable arrow field
        step = max(1, len(ua) // 1400)
        a2.quiver(ua[::step], va[::step], cu[::step], cv[::step],
                  color='#f4f6f8', width=.0016, scale=52, alpha=.85)
        a2.set_title('%s  -  speed and direction' % title, fontsize=10)

        for ax in (a1, a2):
            ax.set_xlabel(xl, fontsize=8)
            ax.set_ylabel(yl, fontsize=8)
            ax.set_aspect('equal')
            ax.tick_params(labelsize=7)
        fig.tight_layout()
        out = os.path.join(case, 'flow_%s.png' % name)
        fig.savefig(out, dpi=125)
        plt.close(fig)
        made.append(out)
        print('  wrote %s' % out)
    if not made:
        sys.exit('no planes could be drawn')


if __name__ == '__main__':
    main()
