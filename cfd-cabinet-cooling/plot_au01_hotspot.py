#!/usr/bin/env python3
"""
Locate the hot spot on the rack faces and show the airflow that creates it.

    .venv/bin/python plot_au01_hotspot.py case-au01

Two things, both from the reconstructed time-averaged field (TMean/UMean):

  1. Temperature ON the intake plane of each row, as a real 2D map. The per-rack
     mean/peak pair cannot say where on a face the heat is; this can.
  2. Streamlines seeded at the hottest patch and integrated BACKWARDS, so the
     lines answer "where did this air come from" rather than "where does it go".
"""

import os
import sys

import numpy as np
import pyvista as pv
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.colors as mc

pv.OFF_SCREEN = True


def params(case):
    out = {}
    for line in open(os.path.join(case, 'system', 'au01Parameters')):
        line = line.split('#', 1)[0].strip()
        if line:
            b = line.split(None, 1)
            if len(b) == 2:
                out[b[0]] = b[1].strip()
    return out


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    p = params(case)
    Tsup, allow = float(p['supplyTemp_C']), float(p['allowableMax_C'])

    foam = os.path.join(case, 'case.foam')
    open(foam, 'a').close()
    r = pv.OpenFOAMReader(foam)
    r.reader.UpdateInformation()
    r.set_active_time_value(list(r.time_values)[-1])
    r.cell_to_point_creation = True
    mesh = r.read()[0].cell_data_to_point_data()
    Tk = 'TMean' if 'TMean' in mesh.point_data else 'T'
    Uk = 'UMean' if 'UMean' in mesh.point_data else 'U'
    mesh.point_data['T_C'] = mesh.point_data[Tk] - 273.15
    mesh.point_data['Uv'] = mesh.point_data[Uk]
    print('  using %s / %s, %d cells' % (Tk, Uk, mesh.n_cells))

    ROWS = {'A': 2.0, 'B': 6.2}
    XR = (8.44, 15.75)
    lo, hi = Tsup - .5, max(allow + 3, 38.5)
    cmap = mc.LinearSegmentedColormap.from_list(
        'h', ['#123a4f', '#2d6a86', '#63a6b4', '#cdd9c8', '#e8c07a', '#cf8342', '#a33a20'])

    fig, axes = plt.subplots(2, 1, figsize=(13.2, 5.6))
    hot = {}
    for ax, (row, yv) in zip(axes, ROWS.items()):
        sl = mesh.slice(normal='y', origin=(12.0, yv, 1.0))
        pts, T = sl.points, sl.point_data['T_C']
        m = (pts[:, 0] > XR[0]) & (pts[:, 0] < XR[1]) & (pts[:, 2] < 2.0)
        x, z, t = pts[m, 0], pts[m, 2], T[m]
        im = ax.tricontourf(x, z, t, levels=np.linspace(lo, hi, 42), cmap=cmap, extend='both')
        ax.tricontour(x, z, t, levels=[allow], colors='#111111', linewidths=1.3)
        i = int(np.argmax(t))
        hot[row] = (x[i], yv, z[i], t[i])
        ax.plot(x[i], z[i], marker='o', ms=11, mfc='none', mec='#111111', mew=1.6)
        ax.annotate('%.1f C' % t[i], (x[i], z[i]), textcoords='offset points',
                    xytext=(14, 8), fontsize=9, fontweight='bold', color='#111111')
        for k in range(12):
            ax.axvline(8.44 + k * 0.61, color='#ffffff', lw=.6, alpha=.5)
        ax.set_xlim(*XR); ax.set_ylim(0, 2.0); ax.set_aspect('equal')
        ax.set_ylabel('height (m)', fontsize=8)
        ax.set_title('Row %s intake plane (y = %.1f m) - temperature ON the face. '
                     'Black contour is the %.0f C A2 allowable; circle is the hottest point.'
                     % (row, yv, allow), fontsize=9.5, loc='left')
        ax.tick_params(labelsize=7)
        ax.set_xticks([8.44 + k * 0.61 + .305 for k in range(12)])
        ax.set_xticklabels(['%s%02d' % (row, k + 1) for k in range(12)], fontsize=7)
    cb = fig.colorbar(im, ax=axes, pad=.012, aspect=30)
    cb.set_label('air temperature (C)', fontsize=8)
    cb.ax.tick_params(labelsize=7)
    out = os.path.join(case, 'hotspot_faces.png')
    fig.savefig(out, dpi=132, bbox_inches='tight')
    plt.close(fig)
    print('  wrote %s' % out)
    for row, (hx, hy, hz, ht) in hot.items():
        print('    row %s hottest point x %.3f  z %.3f  %.2f C' % (row, hx, hz, ht))

    # ---- zoomed plan at the hot spot height: the readable diagnostic ----
    hz = hot['A'][2]
    sl = mesh.slice(normal='z', origin=(12.0, 4.1, hz))
    pts = sl.points
    Tz = sl.point_data['T_C']
    Uz = sl.point_data['Uv']
    m = (pts[:, 0] > 3.4) & (pts[:, 0] < 11.0)
    fig2, ax = plt.subplots(figsize=(13.0, 5.4))
    im = ax.tricontourf(pts[m, 0], pts[m, 1], Tz[m],
                        levels=np.linspace(lo, hi, 42), cmap=cmap, extend='both')
    ax.tricontour(pts[m, 0], pts[m, 1], Tz[m], levels=[allow],
                  colors='#111111', linewidths=1.3)
    st = max(1, int(m.sum()) // 1100)
    ax.quiver(pts[m][::st, 0], pts[m][::st, 1], Uz[m][::st, 0], Uz[m][::st, 1],
              color='#f2f5f7', width=.0022, scale=34, alpha=.95)
    # geometry outlines at this height
    ax.add_patch(plt.Rectangle((2.0, 2.1), 1.6, 4.0, fill=False, ec='#111111', lw=1.4))
    ax.text(2.8, 4.1, 'fan wall W', ha='center', va='center', fontsize=8, rotation=90)
    for y0v, y1v, lab in ((2.0, 3.2, 'row A'), (5.0, 6.2, 'row B')):
        ax.add_patch(plt.Rectangle((8.44, y0v), 15.75 - 8.44, y1v - y0v,
                                   fill=False, ec='#111111', lw=1.2))
        ax.text(9.9, (y0v + y1v) / 2, lab, fontsize=8, va='center')
    ax.plot([3.6, 3.6], [0, 2.1], color='#111111', lw=2.2)
    ax.plot([3.6, 3.6], [6.1, 8.2], color='#111111', lw=2.2)
    ax.text(3.65, 1.0, 'bulkhead', fontsize=8, rotation=90, va='center')
    ax.add_patch(plt.Rectangle((8.335, 3.2), .1, 1.8, color='#00695c'))
    ax.text(8.2, 4.1, 'HAC door', fontsize=8, rotation=90, ha='right', va='center')
    for row in ('A', 'B'):
        hx, hy, hzz, ht = hot[row]
        ax.plot(hx, hy, marker='o', ms=12, mfc='none', mec='#111111', mew=1.8)
        ax.annotate('%.1f C' % ht, (hx, hy), textcoords='offset points',
                    xytext=(12, 8), fontsize=9, fontweight='bold')
    ax.set_xlim(3.4, 11.0); ax.set_ylim(0, 8.2); ax.set_aspect('equal')
    ax.set_xlabel('x along the hall (m)', fontsize=8)
    ax.set_ylabel('y across the hall (m)', fontsize=8)
    ax.set_title('Plan at the hot spot height, z = %.2f m - west end of the pod. '
                 'Arrows are in-plane velocity.' % hz, fontsize=9.5, loc='left')
    ax.tick_params(labelsize=7)
    cb2 = fig2.colorbar(im, ax=ax, pad=.01, aspect=26)
    cb2.set_label('air temperature (C)', fontsize=8)
    out3 = os.path.join(case, 'hotspot_plan.png')
    fig2.savefig(out3, dpi=132, bbox_inches='tight')
    plt.close(fig2)
    print('  wrote %s' % out3)

    # ---- where does that air come from -------------------------------
    seeds = []
    for row, (hx, hy, hz, ht) in hot.items():
        for dx in (-.06, 0, .06):
            for dz in (-.06, 0, .06):
                seeds.append((hx + dx, hy - 0.05 if row == 'A' else hy + 0.05, hz + dz))
    src = pv.PolyData(np.array(seeds))
    # pyvista integrates backwards natively; negating the field is unnecessary.
    # max_time was removed in favour of max_length.
    lines = mesh.streamlines_from_source(src, vectors='Uv', max_length=400.0,
                                         max_steps=25000,
                                         integration_direction='backward')
    print('  back-traced streamlines: %d points' % lines.n_points)

    pl = pv.Plotter(off_screen=True, window_size=(1900, 1000))
    pl.set_background('white')
    pl.add_mesh(mesh.slice(normal='y', origin=(12.0, 2.0, 1.0)), scalars='T_C', cmap=cmap,
                clim=[lo, hi], lighting=False, opacity=.9,
                scalar_bar_args=dict(title='air temperature (C)', color='#222222',
                                     vertical=False, width=.4, position_x=.3,
                                     position_y=.03, n_labels=6))
    tri = os.path.join(case, 'constant', 'triSurface')
    for fn, col, op in (('racks_body.stl', '#37474f', .5),
                        ('fanwall_w_body.stl', '#1c262b', .9),
                        ('hac.stl', '#00695c', .18),
                        ('pod_ends.stl', '#00695c', .45),
                        ('plenum_floor.stl', '#5c6bc0', .12),
                        ('bulkheads_%s.stl' % p['bulkhead'], '#546e7a', .3)):
        fp = os.path.join(tri, fn)
        if os.path.exists(fp):
            pl.add_mesh(pv.read(fp), color=col, opacity=op)
    if lines.n_points:
        pl.add_mesh(lines.tube(radius=.018), scalars='T_C', cmap=cmap, clim=[lo, hi],
                    show_scalar_bar=False)
    for row, (hx, hy, hz, ht) in hot.items():
        pl.add_mesh(pv.Sphere(radius=.085, center=(hx, hy, hz)), color='#111111')
    pl.add_text('Air arriving at the hot spots, traced backwards from the rack face',
                font_size=11, color='#222222')
    pl.camera_position = [(2.0, -12.0, 7.0), (9.6, 4.1, 1.4), (0, 0, 1)]
    out2 = os.path.join(case, 'hotspot_path.png')
    pl.screenshot(out2)
    pl.close()
    print('  wrote %s' % out2)


if __name__ == '__main__':
    main()
