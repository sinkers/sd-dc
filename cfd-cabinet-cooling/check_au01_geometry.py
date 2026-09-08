#!/usr/bin/env python3
"""
Render the AU01 STL assembly so the model can be eyeballed against the CAD.

    .venv/bin/python check_au01_geometry.py case-au01

This is a verification step, not a picture for a report. A misplaced solid is
cheap to spot here and expensive to spot after a 45 minute solve, and the STL
bounding boxes alone do not show whether the return path is actually open.
"""

import json
import os
import sys

import pyvista as pv

pv.OFF_SCREEN = True

# name -> (file, colour, opacity). Order matters only for readability.
PARTS = [
    ('room',      'room_shell.stl',   '#cfd8dc', 0.10),
    ('gantry',    'gantry.stl',       '#8d6e63', 0.55),
    ('fan wall W', 'fanwall_w_body.stl', '#37474f', 0.85),
    ('fan wall E', 'fanwall_e_body.stl', '#37474f', 0.85),
    ('bulkheads', None,               '#546e7a', 0.75),   # variant, filled below
    ('containment', 'hac.stl',        '#00897b', 0.55),
    ('racks',     'racks_body.stl',   '#455a64', 0.95),
    ('plenum deck', 'plenum_floor.stl', '#5c6bc0', 0.45),
    ('pod ends',  'pod_ends.stl',     '#00695c', 0.75),
]
SUPPLY = ['fw_w_supply_m1.stl', 'fw_w_supply_m2.stl',
          'fw_e_supply_m1.stl', 'fw_e_supply_m2.stl']
INTAKE = ['fw_w_intake_m1.stl', 'fw_w_intake_m2.stl',
          'fw_e_intake_m1.stl', 'fw_e_intake_m2.stl']


def read_params(path):
    out = {}
    for line in open(path):
        line = line.split('#', 1)[0].strip()
        if line:
            b = line.split(None, 1)
            if len(b) == 2:
                out[b[0]] = b[1].strip()
    return out


def main():
    case = sys.argv[1] if len(sys.argv) > 1 else 'case-au01'
    tri = os.path.join(case, 'constant', 'triSurface')
    p = read_params(os.path.join(case, 'system', 'au01Parameters'))
    with open(os.path.join(case, 'system', 'cfd_export_params.json')) as fh:
        g = json.load(fh)

    parts = list(PARTS)
    for i, (n, f, c, o) in enumerate(parts):
        if n == 'bulkheads':
            parts[i] = (n, 'bulkheads_%s.stl' % p['bulkhead'], c, o)

    views = {
        'iso':   dict(cpos=[(-14, -18, 14), (12.0, 4.1, 1.6), (0, 0, 1)]),
        'west':  dict(cpos=[(-11, 4.1, 3.0), (12.0, 4.1, 1.6), (0, 0, 1)]),
        'above': dict(cpos=[(12.0, 4.05, 26), (12.0, 4.1, 1.0), (0, 1, 0)]),
        'cut':   dict(cpos=[(12.0, -22, 6.0), (12.0, 4.1, 2.0), (0, 0, 1)]),
    }

    for view, kw in views.items():
        pl = pv.Plotter(off_screen=True, window_size=(1800, 950))
        pl.set_background('white')
        for name, fn, colour, opacity in parts:
            path = os.path.join(tri, fn)
            if not os.path.exists(path):
                print('missing %s' % fn)
                continue
            # the room shell would hide everything, so show it as edges only
            style = 'wireframe' if name == 'room' else 'surface'
            pl.add_mesh(pv.read(path), color=colour, opacity=opacity,
                        style=style, line_width=1, label=name)
        for fn in SUPPLY:
            pl.add_mesh(pv.read(os.path.join(tri, fn)), color='#1e88e5', opacity=0.95)
        for fn in INTAKE:
            pl.add_mesh(pv.read(os.path.join(tri, fn)), color='#e53935', opacity=0.95)
        pl.camera_position = kw['cpos']
        pl.add_text('AU01 whitespace - %s bulkhead - blue = supply, red = return'
                    % p['bulkhead'], font_size=11, color='black')
        out = os.path.join(case, 'geometry_%s.png' % view)
        pl.screenshot(out)
        pl.close()
        print('wrote %s' % out)

    # the checks a picture cannot make for you
    s = float(g['scale'])
    bh = float(p['bulkhead'][1:]) * s * 1000 / 1000.0
    eave, apex = g['room']['eave'] * s, g['room']['apex'] * s
    W = (g['room']['y'][1] - g['room']['y'][0]) * s
    fwW = (g['fanwall']['y'][1] - g['fanwall']['y'][0]) * s
    fwTop = g['fanwall']['top'] * s
    gable = 0.5 * W * (apex - eave)
    slot = W * (eave - bh) + gable - fwW * max(0.0, fwTop - bh)
    print()
    print('return slot over the %s bulkhead: %.2f m2' % (p['bulkhead'], slot))
    print('  = %.1f x (%.2f - %.2f) + %.3f gable - %.1f x (%.2f - %.2f) fan wall'
          % (W, eave, bh, gable, fwW, fwTop, bh))
    q = float(p['unitAirflow_m3h']) / 3600.0
    print('  at nameplate %.0f m3/h per end, both slots: %.2f m/s'
          % (float(p['unitAirflow_m3h']), 2 * q / (2 * slot)))


if __name__ == '__main__':
    main()
