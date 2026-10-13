"""Draw routes for review: plan, elevations and an isometric, as one SVG sheet.

No FreeCAD and no plotting library. A reviewer, or an agent that can look at
an image, should be able to see what the router did without a CAD session:
which way each pipe goes, what it goes round, and where it failed or broke a
rule. Pipes are drawn to scale (stroke = OD) with their elbows filleted at
the bend radius; obstacles are the same boxes the router saw.

This is a schematic. It shows the router's world, which is only as complete
as the obstacles it was given. Shaded renders of the built solids come from
the CAD host, not from here.

  svg = render_sheet(obstacles, pipes, views=("plan", "front", "iso"))
  png = svg_to_png(svg)          # None when rsvg-convert is not installed
"""
from __future__ import annotations

import math
import os
import shutil
import subprocess
from html import escape

VIEWS = {
    "plan": "Plan (looking down)",
    "front": "Elevation (looking north, +y)",
    "side": "Elevation (looking west, -x)",
    "iso": "Isometric (from south-west)",
}

_C30, _S30 = math.cos(math.radians(30)), math.sin(math.radians(30))

SERVICE_COLOURS = {
    "CHW-S": "#1f6fd1", "CHW-R": "#d1402b",
    "LTHW-S": "#e08a00", "LTHW-R": "#b0569b",
    "CW-S": "#1b9e77", "CW-R": "#7f6a3a",
}
PALETTE = ["#1f6fd1", "#d1402b", "#1b9e77", "#e08a00", "#7b4fc9",
           "#00838f", "#b0569b", "#5d7a1f", "#c2185b", "#455a64"]
FAIL = "#e00000"


def _project(view, p):
    x, y, z = p
    if view == "plan":
        return x, y
    if view == "front":
        return x, z
    if view == "side":
        return -y, z
    return (x - y) * _C30, z + (x + y) * _S30


def _near(view, p):
    """Bigger is nearer the viewer; draw in ascending order."""
    x, y, z = p
    if view == "plan":
        return z
    if view == "front":
        return -y
    if view == "side":
        return -x
    return z - x - y


def _corners(lo, hi):
    return [(x, y, z) for x in (lo[0], hi[0]) for y in (lo[1], hi[1])
            for z in (lo[2], hi[2])]


def _box_faces(view, lo, hi):
    """Polygons (3D) for the faces of a box the view can see."""
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    top = [(x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    if view == "plan":
        return [("top", top)]
    south = [(x0, y0, z0), (x1, y0, z0), (x1, y0, z1), (x0, y0, z1)]
    if view == "front":
        return [("side", south)]
    west = [(x0, y0, z0), (x0, y1, z0), (x0, y1, z1), (x0, y0, z1)]
    if view == "side":
        east = [(x1, y0, z0), (x1, y1, z0), (x1, y1, z1), (x1, y0, z1)]
        return [("side", east)]
    return [("west", west), ("south", south), ("top", top)]


def _nice(span):
    """A round scale-bar length about a fifth of the span."""
    target = span / 5
    mag = 10 ** math.floor(math.log10(max(target, 1)))
    for m in (1, 2, 5, 10):
        if m * mag >= target:
            return m * mag
    return 10 * mag


def _fillet(pts2, radii):
    """SVG path through 2D corners, each interior corner rounded."""
    keep = [pts2[0]]
    rk = [0.0]
    for i in range(1, len(pts2)):
        if math.dist(pts2[i], keep[-1]) > 1e-6:
            keep.append(pts2[i])
            rk.append(radii[i] if i < len(radii) else 0.0)
    if len(keep) == 1:
        x, y = keep[0]
        return f"M{x:.1f},{y:.1f}l0.01,0"
    d = [f"M{keep[0][0]:.1f},{keep[0][1]:.1f}"]
    for i in range(1, len(keep) - 1):
        a, p, b = keep[i - 1], keep[i], keep[i + 1]
        la, lb = math.dist(a, p), math.dist(p, b)
        # Collinear in this projection (a run along the view axis): no fillet.
        cross = (p[0] - a[0]) * (b[1] - p[1]) - (p[1] - a[1]) * (b[0] - p[0])
        r = min(rk[i], la / 2, lb / 2)
        if abs(cross) < 1e-6 * la * lb or r <= 0.5:
            d.append(f"L{p[0]:.1f},{p[1]:.1f}")
            continue
        p1 = (p[0] + (a[0] - p[0]) / la * r, p[1] + (a[1] - p[1]) / la * r)
        p2 = (p[0] + (b[0] - p[0]) / lb * r, p[1] + (b[1] - p[1]) / lb * r)
        d.append(f"L{p1[0]:.1f},{p1[1]:.1f}Q{p[0]:.1f},{p[1]:.1f} "
                 f"{p2[0]:.1f},{p2[1]:.1f}")
    d.append(f"L{keep[-1][0]:.1f},{keep[-1][1]:.1f}")
    return "".join(d)


def _run_paths(pts2, r):
    """One SVG path per run, each ending with the elbow at its far corner."""
    n = len(pts2) - 1
    trim_in, trim_out = {}, {}
    for i in range(1, n):
        a, p, b = pts2[i - 1], pts2[i], pts2[i + 1]
        la, lb = math.dist(a, p), math.dist(p, b)
        cross = ((p[0] - a[0]) * (b[1] - p[1])
                 - (p[1] - a[1]) * (b[0] - p[0]))
        ri = min(r, la / 2, lb / 2)
        # A run along the view axis projects to a point: no visible elbow.
        if la < 1e-6 or lb < 1e-6 or abs(cross) < 1e-6 * la * lb or ri < 0.5:
            trim_in[i] = trim_out[i] = p
            continue
        trim_in[i] = (p[0] + (a[0] - p[0]) / la * ri,
                      p[1] + (a[1] - p[1]) / la * ri)
        trim_out[i] = (p[0] + (b[0] - p[0]) / lb * ri,
                       p[1] + (b[1] - p[1]) / lb * ri)
    out = []
    for i in range(n):
        s = trim_out.get(i, pts2[i])
        e = trim_in.get(i + 1, pts2[i + 1])
        d = f"M{s[0]:.1f},{s[1]:.1f}L{e[0]:.1f},{e[1]:.1f}"
        if i + 1 < n and trim_out[i + 1] != pts2[i + 1]:
            c, t = pts2[i + 1], trim_out[i + 1]
            d += f"Q{c[0]:.1f},{c[1]:.1f} {t[0]:.1f},{t[1]:.1f}"
        out.append(d)
    return out


def _colour(pipe, k, assigned):
    if pipe.get("colour"):
        return pipe["colour"]
    svc = pipe.get("service")
    if svc in SERVICE_COLOURS:
        return SERVICE_COLOURS[svc]
    key = svc or pipe["id"]
    if key not in assigned:
        assigned[key] = PALETTE[len(assigned) % len(PALETTE)]
    return assigned[key]


class _Panel:
    def __init__(self, view, x, y, w, h, pts3):
        self.view, self.x, self.y, self.w, self.h = view, x, y, w, h
        pts = [_project(view, p) for p in pts3] or [(0, 0), (1000, 1000)]
        u0 = min(p[0] for p in pts)
        u1 = max(p[0] for p in pts)
        v0 = min(p[1] for p in pts)
        v1 = max(p[1] for p in pts)
        pad = 0.04 * max(u1 - u0, v1 - v0, 1000)
        u0, u1, v0, v1 = u0 - pad, u1 + pad, v0 - pad, v1 + pad
        top, bottom = 34, 30
        self.s = min((w - 20) / (u1 - u0), (h - top - bottom) / (v1 - v0))
        self.ox = x + (w - (u1 - u0) * self.s) / 2 - u0 * self.s
        self.oy = (y + top + (h - top - bottom - (v1 - v0) * self.s) / 2
                   + v1 * self.s)
        self.span = u1 - u0

    def xy(self, p):
        u, v = _project(self.view, p)
        return self.ox + u * self.s, self.oy - v * self.s


def _panel_svg(pn, obstacles, pipes, ghosts, labels):
    view, out, items = pn.view, [], []
    shade = {"top": "#d9dde3", "south": "#b8bec7", "west": "#c8cdd4",
             "side": "#c8cdd4"}
    for b in obstacles:
        lo, hi = tuple(b["min"]), tuple(b["max"])
        centre = tuple((lo[i] + hi[i]) / 2 for i in range(3))
        for face, poly in _box_faces(view, lo, hi):
            near = _near(view, centre) if view != "plan" else hi[2]
            pts = " ".join(f"{a:.1f},{c:.1f}" for a, c in map(pn.xy, poly))
            items.append((near, 0,
                          f'<polygon points="{pts}" fill="{shade[face]}" '
                          f'fill-opacity="0.75" stroke="#59616b" '
                          f'stroke-width="0.6"/>'))
    for g in ghosts:
        if not g.get("points"):
            continue
        d = _fillet([pn.xy(p) for p in g["points"]],
                    [g.get("bend_radius", 0) * pn.s] * len(g["points"]))
        w = max(g["od"] * pn.s, 1.0)
        items.append((math.inf, 1,
                      f'<path d="{d}" fill="none" stroke="#6b7280" '
                      f'stroke-width="{w:.2f}" stroke-dasharray="6 4" '
                      f'stroke-opacity="0.8" stroke-linejoin="round"/>'))
    for p in pipes:
        w = max(p["od"] * pn.s, 1.4)
        if p.get("points"):
            pts = p["points"]
            # One item per run so the painter's sort can put a run behind a
            # box it passes behind. Each run carries the elbow at its end.
            runs = _run_paths([pn.xy(q) for q in pts],
                              p.get("bend_radius", 0) * pn.s)
            for i, d in enumerate(runs):
                mid = tuple((pts[i][k] + pts[i + 1][k]) / 2 for k in range(3))
                items.append((_near(view, mid), 2,
                              f'<path d="{d}" fill="none" stroke="#1d232b" '
                              f'stroke-width="{w + 1.6:.2f}" '
                              f'stroke-linecap="round"/>'
                              f'<path d="{d}" fill="none" '
                              f'stroke="{p["colour"]}" '
                              f'stroke-width="{w:.2f}" '
                              f'stroke-linecap="round"/>'))
            for i in sorted({iss["segment"] for iss in p.get("issues", [])
                             if "segment" in iss}):
                if i + 1 < len(pts):
                    (x0, y0), (x1, y1) = pn.xy(pts[i]), pn.xy(pts[i + 1])
                    items.append((math.inf, 3,
                                  f'<line x1="{x0:.1f}" y1="{y0:.1f}" '
                                  f'x2="{x1:.1f}" y2="{y1:.1f}" '
                                  f'stroke="{FAIL}" stroke-width="{w + 5:.1f}" '
                                  f'stroke-opacity="0.45"/>'))
        elif p.get("from_pos") and p.get("to_pos"):
            (x0, y0), (x1, y1) = pn.xy(p["from_pos"]), pn.xy(p["to_pos"])
            items.append((math.inf, 3,
                          f'<line x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" '
                          f'y2="{y1:.1f}" stroke="{FAIL}" stroke-width="2" '
                          f'stroke-dasharray="3 3"/>'))
        for key, fill in (("from_pos", "#ffffff"), ("to_pos", "#1d232b")):
            if p.get(key):
                cx, cy = pn.xy(p[key])
                items.append((math.inf, 4,
                              f'<circle cx="{cx:.1f}" cy="{cy:.1f}" '
                              f'r="{max(w / 2 + 1, 2.5):.1f}" fill="{fill}" '
                              f'stroke="#1d232b" stroke-width="1"/>'))
    items.sort(key=lambda t: (t[1] >= 3, t[0], t[1]))
    out += [s for _, _, s in items]

    if labels:
        # Greedy placement: a label that would overlap one already placed
        # tries the pipe's other runs, then is left off. Pipe ids first,
        # since they are what a reviewer refers to.
        placed = []

        def free(x, y, text, size):
            w, h = 0.6 * size * len(text) + 4, size + 3
            box = (x - w / 2, y - h, x + w / 2, y + 2)
            if any(not (box[2] < o[0] or box[0] > o[2] or box[3] < o[1]
                        or box[1] > o[3]) for o in placed):
                return False
            placed.append(box)
            return True

        for p in pipes:
            tag = p["id"] + ("" if p.get("points") else
                             f' ({p.get("reason", "failed")})')
            fill = FAIL if (not p.get("points") or p.get("issues")) \
                else "#1d232b"
            for x, y in _label_spots(pn, p):
                if free(x, y - 4, tag, 10):
                    out.append(f'<text x="{x:.1f}" y="{y - 4:.1f}" '
                               f'class="pl" fill="{fill}">{escape(tag)}'
                               f'</text>')
                    break
        for b in obstacles:
            lo, hi = b["min"], b["max"]
            top_c = ((lo[0] + hi[0]) / 2, (lo[1] + hi[1]) / 2, hi[2])
            cx, cy = pn.xy(top_c)
            name = str(b.get("id", ""))
            if free(cx, cy + 3, name, 9):
                out.append(f'<text x="{cx:.1f}" y="{cy + 3:.1f}" class="ob">'
                           f'{escape(name)}</text>')

    # Frame, title and a scale bar.
    out.insert(0, f'<rect x="{pn.x}" y="{pn.y}" width="{pn.w}" '
                  f'height="{pn.h}" fill="#ffffff" stroke="#c4c9d0"/>')
    out.append(f'<text x="{pn.x + 10}" y="{pn.y + 20}" class="vt">'
               f'{escape(VIEWS[view])}</text>')
    bar = _nice(pn.span)
    bx, by = pn.x + 12, pn.y + pn.h - 12
    out.append(f'<line x1="{bx}" y1="{by}" x2="{bx + bar * pn.s:.1f}" '
               f'y2="{by}" stroke="#1d232b" stroke-width="2"/>'
               f'<text x="{bx + bar * pn.s + 6:.1f}" y="{by + 4}" class="sb">'
               f'{bar / 1000:g} m</text>')
    return "\n".join(out)


def _label_spots(pn, p):
    """Candidate label positions, best first: along each run, longest run
    first, at the middle then the quarter points."""
    if p.get("points"):
        pts = [pn.xy(q) for q in p["points"]]
    elif p.get("from_pos") and p.get("to_pos"):
        pts = [pn.xy(p["from_pos"]), pn.xy(p["to_pos"])]
    else:
        return []
    runs = sorted(range(len(pts) - 1),
                  key=lambda i: -math.dist(pts[i], pts[i + 1]))
    out = []
    for t in (0.5, 0.25, 0.75):
        for i in runs:
            a, b = pts[i], pts[i + 1]
            if math.dist(a, b) > 20:
                out.append((a[0] + (b[0] - a[0]) * t,
                            a[1] + (b[1] - a[1]) * t))
    return out


def render_sheet(obstacles, pipes, views=("plan", "front", "iso"),
                 title="", notes=(), ghosts=(), labels=("plan",),
                 focus=None, width=1600) -> str:
    """One SVG sheet with a panel per view.

    obstacles: [{id, min, max}]
    pipes:     [{id, od, bend_radius, points | None, from_pos, to_pos,
                 service?, colour?, issues?, reason?}]
    ghosts:    pipes drawn dashed grey underneath, e.g. the hand routes when
               reviewing the router against them.
    labels:    the views that get pipe and obstacle ids.
    focus:     ([x,y,z], [x,y,z]) to draw only that region, or None to fit
               everything. Obstacles outside it are left out and pipes are
               clipped at the panel edge.
    """
    for v in views:
        if v not in VIEWS:
            raise ValueError(f"unknown view {v!r}; expected {list(VIEWS)}")
    if not views:
        raise ValueError("ask for at least one view")
    assigned = {}
    pipes = [{**p, "colour": _colour(p, k, assigned)}
             for k, p in enumerate(pipes)]
    if focus is not None:
        lo, hi = tuple(focus[0]), tuple(focus[1])
        obstacles = [b for b in obstacles
                     if all(b["min"][i] <= hi[i] and b["max"][i] >= lo[i]
                            for i in range(3))]
    pts3 = []
    for b in obstacles:
        pts3 += _corners(tuple(b["min"]), tuple(b["max"]))
    for p in list(pipes) + list(ghosts):
        pts3 += [tuple(q) for q in (p.get("points") or [])]
        pts3 += [tuple(p[k]) for k in ("from_pos", "to_pos") if p.get(k)]
    if focus is not None:
        pts3 = _corners(lo, hi)

    head = 64 + 16 * len(notes)
    b = [_project("plan", p) for p in pts3] or [(0, 0), (1, 1)]
    aspect = ((max(q[1] for q in b) - min(q[1] for q in b) + 1)
              / (max(q[0] for q in b) - min(q[0] for q in b) + 1))
    # A long thin site reads better with every view at full width.
    cols = 1 if len(views) == 1 or aspect < 0.4 else 2
    pw = (width - 30) / cols if cols > 1 else width - 20
    ph = max(360, min(900, pw * aspect + 70)) if "plan" in views \
        else pw * 0.62
    def view_h(v, w):
        q = [_project(v, p) for p in pts3] or [(0, 0), (1, 1)]
        a = ((max(t[1] for t in q) - min(t[1] for t in q) + 1)
             / (max(t[0] for t in q) - min(t[0] for t in q) + 1))
        return max(260, min(900, (w - 20) * a * 1.08 + 70))

    # In one column each panel is as tall as its own view needs; in two,
    # a row is as tall as its taller panel.
    slots, y = [], head
    for r0 in range(0, len(views), cols):
        row = views[r0:r0 + cols]
        alone = len(row) == 1
        w = width - 20 if alone else pw
        h = ph if (cols > 1 and not alone) else view_h(row[0], w)
        if cols > 1 and not alone:
            h = max(view_h(v, w) for v in row)
        for j, v in enumerate(row):
            slots.append((v, 10 + j * (pw + 10), y, w, h))
        y += h + 10
    legend_h = 40
    height = y + legend_h

    body = []
    for k, (v, x, y, w, h) in enumerate(slots):
        pn = _Panel(v, x, y, w, h, pts3)
        body.append(f'<clipPath id="c{k}"><rect x="{x}" y="{y}" '
                    f'width="{w}" height="{h}"/></clipPath>'
                    f'<g clip-path="url(#c{k})">'
                    + _panel_svg(pn, obstacles, pipes, ghosts, v in labels)
                    + "</g>")

    legend, lx = [], 14
    ly = height - legend_h + 22
    seen = {}
    for p in pipes:
        seen.setdefault(p.get("service") or "pipe", p["colour"])
    for name, colour in seen.items():
        legend.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 26}" '
                      f'y2="{ly - 4}" stroke="{colour}" stroke-width="6"/>'
                      f'<text x="{lx + 32}" y="{ly}" class="lg">'
                      f'{escape(name)}</text>')
        lx += 46 + 8 * len(name)
    extras = [("#ffffff", "outlet"), ("#1d232b", "inlet")]
    for fill, name in extras:
        legend.append(f'<circle cx="{lx + 6}" cy="{ly - 4}" r="5" '
                      f'fill="{fill}" stroke="#1d232b"/>'
                      f'<text x="{lx + 16}" y="{ly}" class="lg">{name}</text>')
        lx += 74
    legend.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 26}" y2="{ly - 4}" '
                  f'stroke="{FAIL}" stroke-width="7" stroke-opacity="0.45"/>'
                  f'<text x="{lx + 32}" y="{ly}" class="lg">rule broken'
                  f'</text>')
    lx += 120
    legend.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 26}" y2="{ly - 4}" '
                  f'stroke="{FAIL}" stroke-width="2" stroke-dasharray="3 3"/>'
                  f'<text x="{lx + 32}" y="{ly}" class="lg">not routed</text>')
    lx += 120
    if ghosts:
        legend.append(f'<line x1="{lx}" y1="{ly - 4}" x2="{lx + 26}" '
                      f'y2="{ly - 4}" stroke="#6b7280" stroke-width="3" '
                      f'stroke-dasharray="6 4"/><text x="{lx + 32}" y="{ly}" '
                      f'class="lg">reference route</text>')

    note_svg = "".join(
        f'<text x="14" y="{56 + 16 * i}" class="nt">{escape(n)}</text>'
        for i, n in enumerate(notes))
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" '
        f'height="{height:.0f}" viewBox="0 0 {width} {height:.0f}" '
        f'font-family="Helvetica, Arial, sans-serif">\n'
        f'<style>.tt{{font-size:20px;font-weight:600;fill:#1d232b}}'
        f'.nt{{font-size:12.5px;fill:#3b4350}}'
        f'.vt{{font-size:13px;font-weight:600;fill:#3b4350}}'
        f'.sb,.lg{{font-size:12px;fill:#3b4350}}'
        f'.ob{{font-size:9px;fill:#4b5563;text-anchor:middle}}'
        f'.pl{{font-size:10px;font-weight:600;text-anchor:middle;'
        f'paint-order:stroke;stroke:#fff;stroke-width:3px}}</style>\n'
        f'<rect width="100%" height="100%" fill="#f4f5f7"/>\n'
        f'<text x="14" y="32" class="tt">{escape(title)}</text>{note_svg}\n'
        + "\n".join(body) + "\n" + "".join(legend) + "\n</svg>\n")


def png_available() -> bool:
    return bool(os.environ.get("PIPING_RSVG") or shutil.which("rsvg-convert"))


def svg_to_png(svg: str, width: int | None = None) -> bytes | None:
    """Rasterise with rsvg-convert. None when it is not installed."""
    exe = os.environ.get("PIPING_RSVG") or shutil.which("rsvg-convert")
    if not exe:
        return None
    cmd = [exe, "-f", "png"] + (["-w", str(width)] if width else [])
    out = subprocess.run(cmd, input=svg.encode(), capture_output=True,
                         timeout=60, check=True)
    return out.stdout
