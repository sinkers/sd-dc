#!/usr/bin/env python3
"""
3D perspective view and orbit animation of the AU01 flow field.

    .venv/bin/python make_au01_3d.py case-au01

Built from the sampled planes plus the STL geometry, NOT from the OpenFOAM case
directly. The reason is practical: the reconstructed mesh was not being fetched
off the instance, so a 492 MB time directory of fields arrived with nothing to
read them against. That is fixed in remote/ec2-run.sh for future runs, but the
sampled planes are self-contained - they carry their own coordinates - so this
route works on any run, past or future, and needs no volume mesh.

The cost is that streamlines are not available: they need the volume field. What
you get instead is temperature on the cut planes with in-plane velocity vectors.
"""

import glob
import json
import os
import re
import sys

import numpy as np
import pyvista as pv

pv.OFF_SCREEN = True

# axis held constant on each sampled plane
PLANES = {'rack_mid': 2, 'aisle_long': 1, 'pod_cross': 0}


def params(case):
    out = {}
    for line in open(os.path.join(case, 'system', 'au01Parameters')):
        line = line.split('#', 1)[0].strip()
        if line:
            b = line.split(None, 1)
            if len(b) == 2:
                out[b[0]] = b[1].strip()
    return out


def plane_surface(xyz, scal):
    """Triangulate an axis-aligned point cloud, keeping it in 3D."""
    spread = xyz.max(axis=0) - xyz.min(axis=0)
    const = int(np.argmin(spread))
    keep = [i for i in range(3) or [] if i != const]
    flat = np.zeros_like(xyz)
    flat[:, 0] = xyz[:, keep[0]]
    flat[:, 1] = xyz[:, keep[1]]
    pd = pv.PolyData(flat)
    pd['T_C'] = scal
    surf = pd.delaunay_2d()
    pts = surf.points.copy()
    out = np.zeros_like(pts)
    out[:, keep[0]] = pts[:, 0]
    out[:, keep[1]] = pts[:, 1]
    out[:, const] = xyz[0, const]
    surf.points = out
    return surf


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    p = params(case)
    Tsup = float(p['supplyTemp_C'])
    allow = float(p['allowableMax_C'])
    tri = os.path.join(case, 'constant', 'triSurface')

    times = sorted(glob.glob(os.path.join(case, 'postProcessing', 'slices', '*')),
                   key=lambda q: float(os.path.basename(q)))
    if not times:
        sys.exit('no sampled planes - run: postProcess -func slices -latestTime')
    d = times[-1]
    t = float(os.path.basename(d))

    surfaces, arrows = [], []
    hi = allow + 4
    for name in PLANES:
        ft, fu = os.path.join(d, 'T_%s.raw' % name), os.path.join(d, 'U_%s.raw' % name)
        if not os.path.exists(ft):
            continue
        T = np.loadtxt(ft, comments='#')
        surfaces.append(plane_surface(T[:, :3], T[:, 3] - 273.15))
        hi = max(hi, float(np.percentile(T[:, 3] - 273.15, 99.5)))
        if os.path.exists(fu):
            U = np.loadtxt(fu, comments='#')
            step = max(1, len(U) // 900)
            pc = pv.PolyData(U[::step, :3])
            pc['U'] = U[::step, 3:6]
            arrows.append(pc.glyph(orient='U', scale=False, factor=.32,
                                   geom=pv.Arrow(tip_length=.3, shaft_radius=.035)))
    if not surfaces:
        sys.exit('no planes could be built')
    clim = [Tsup - 1, hi]
    print('  %d planes, t = %.2f s, T range %.1f-%.1f C' % (len(surfaces), t, clim[0], clim[1]))

    def scene(pl, with_arrows=True):
        pl.set_background('white')
        for i, s in enumerate(surfaces):
            pl.add_mesh(s, scalars='T_C', cmap='turbo', clim=clim, lighting=False,
                        show_scalar_bar=(i == 0),
                        scalar_bar_args=dict(title='air temperature (C)', color='#222222',
                                             n_labels=6, vertical=False, width=.42,
                                             position_x=.29, position_y=.03,
                                             title_font_size=16, label_font_size=13))
        if with_arrows:
            for a in arrows:
                pl.add_mesh(a, color='#22303c', opacity=.55, show_scalar_bar=False)
        for fn, col, op in (('racks_body.stl', '#37474f', .95),
                            ('fanwall_w_body.stl', '#1c262b', .95),
                            ('fanwall_e_body.stl', '#1c262b', .95),
                            ('pod_ends.stl', '#00695c', .6),
                            ('hac.stl', '#00695c', .22),
                            ('plenum_floor.stl', '#5c6bc0', .16),
                            ('bulkheads_%s.stl' % p['bulkhead'], '#546e7a', .3),
                            ('room_shell.stl', '#b0bec5', .05)):
            fp = os.path.join(tri, fn)
            if os.path.exists(fp):
                pl.add_mesh(pv.read(fp), color=col, opacity=op)

    b = surfaces[0].bounds
    xc, yc = 12.065, 4.1

    pl = pv.Plotter(off_screen=True, window_size=(1900, 1000))
    scene(pl)
    pl.add_text('AU01 whitespace - temperature on the sampled planes with in-plane flow, '
                't = %.0f s' % t, font_size=11, color='#222222')
    pl.camera_position = [(-12, -18, 14), (xc, yc, 1.7), (0, 0, 1)]
    out = os.path.join(case, 'flow_3d.png')
    pl.screenshot(out)
    pl.close()
    print('  wrote %s' % out)

    pl = pv.Plotter(off_screen=True, window_size=(1440, 810))
    scene(pl, with_arrows=False)
    mp4 = os.path.join(case, 'flow_orbit.mp4')
    try:
        pl.open_movie(mp4, framerate=24)
    except Exception as e:
        mp4 = os.path.join(case, 'flow_orbit.gif')
        print('  mp4 unavailable (%s), writing %s' % (type(e).__name__, mp4))
        pl.open_gif(mp4)
    n = 120
    for i in range(n):
        a = 2 * np.pi * i / n
        pl.camera_position = [(xc + 22 * np.cos(a), yc + 22 * np.sin(a),
                               7.5 + 4 * np.sin(a * 2)), (xc, yc, 1.7), (0, 0, 1)]
        pl.write_frame()
    pl.close()
    print('  wrote %s' % mp4)


if __name__ == '__main__':
    main()
