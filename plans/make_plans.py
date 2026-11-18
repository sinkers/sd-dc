#!/usr/bin/env python3
"""Floor plans for review, straight to DXF, from a FreeCAD site model.

    python3 make_plans.py --geometry plan_geometry.json --config sheets.json --out <dir>

`extract_plan_geometry.py` (run in FreeCAD) cuts every solid in the model at
each storey's cut height and writes the section loops, plus a mid-height
outline of everything that sits below the cut, to plan_geometry.json. This
script turns that into one DXF per sheet (R2018, true mm in modelspace, an A3
border scaled by the sheet's denominator, the classic model-space-with-scaled-
border workflow) and renders the same modelspace to an A3 PDF and a PNG. One
source, three outputs. Cut solids are poched, things below the cut are thin
grey, the title block follows the DAME sheet style.

The config holds everything project-specific: the sheets, scale, which cut,
which parts, the layer rules, room labels, dimensions and title block text.
"""

import argparse
import json
import math
import os
import re
import sys

import ezdxf
from ezdxf import colors
from ezdxf.enums import TextEntityAlignment

PALETTE = {"ink": "1F1C1A", "green": "2A5A3D", "ochre": "B5450A", "grey": "8A847A",
           "rule": "E2DDD4", "ground": "F4F1EB", "blue": "4A7A9A", "white": "FFFFFF"}

LAYERS = {  # name: (colour key, lineweight 1/100 mm)
    "ARCH-CUT": ("ink", 50), "ARCH-POCHE": ("ink", 0), "ARCH-GLAZ": ("blue", 25),
    "ARCH-BELOW": ("grey", 13), "PART-CUT": ("ink", 35), "PART-POCHE": ("grey", 0),
    "EQUIP": ("green", 25), "EQUIP-IT": ("ink", 18), "EQUIP-BELOW": ("grey", 13),
    "CIVIL": ("grey", 13), "SITE": ("ochre", 35), "SITE-CONTEXT": ("grey", 13),
    "CONTOUR": ("ochre", 9), "VEHICLE": ("grey", 13),
    "ROOM-TEXT": ("ink", 0), "TAG": ("green", 0), "DIM": ("ink", 13), "NOTE": ("ink", 0),
    "DRAW-BORDER": ("ink", 50), "DRAW-RULE": ("rule", 18), "DRAW-BAND": ("green", 0),
    "DRAW-TEXT": ("white", 0), "DRAW-TEXT-SEC": ("ink", 0),
}


def rgb(key):
    h = PALETTE[key]
    return colors.rgb2int((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))


class Sheet:
    def __init__(self, cfg, project):
        self.cfg = cfg
        self.project = project
        self.scale = float(cfg["scale"])            # denominator
        self.rot = math.radians(cfg.get("rotate_deg", 0.0))
        self.doc = ezdxf.new("R2018", setup=True)
        self.doc.units = ezdxf.units.MM
        self.msp = self.doc.modelspace()
        for name, (col, lw) in LAYERS.items():
            layer = self.doc.layers.add(name)
            layer.rgb = tuple(int(PALETTE[col][i:i + 2], 16) for i in (0, 2, 4))
            layer.dxf.lineweight = lw
        for style, font in (("MONO", "DejaVuSansMono.ttf"), ("SERIF", "DejaVuSerif.ttf"),
                            ("SANS", "DejaVuSans.ttf")):
            self.doc.styles.add(style, font=font)
        self.origin = (0.0, 0.0)

    # model (layout-frame mm) -> drawing mm, rotated about the sheet centre
    def T(self, p):
        x, y = p[0] - self.cx, p[1] - self.cy
        c, s = math.cos(self.rot), math.sin(self.rot)
        return (c * x - s * y, s * x + c * y)

    def set_centre(self, bounds):
        self.cx = (bounds[0] + bounds[2]) / 2
        self.cy = (bounds[1] + bounds[3]) / 2

    def poly(self, pts, layer, closed=False, dashed=False):
        if len(pts) < 2:
            return
        e = self.msp.add_lwpolyline([self.T(p) for p in pts], close=closed,
                                    dxfattribs={"layer": layer})
        if dashed:
            e.dxf.linetype = "DASHED"
            e.dxf.ltscale = self.scale / 10

    def hatch(self, loops, layer, colour=None):
        h = self.msp.add_hatch(color=7, dxfattribs={"layer": layer})
        h.rgb = tuple(int(PALETTE[colour or LAYERS[layer][0]][i:i + 2], 16) for i in (0, 2, 4))
        for pts in loops:
            if len(pts) >= 3:
                h.paths.add_polyline_path([self.T(p) for p in pts], is_closed=True)

    def text(self, s, p, h_mm, layer, style="MONO", align="MIDDLE_CENTER", rot=0.0):
        t = self.msp.add_text(s, height=h_mm * self.scale,
                              dxfattribs={"layer": layer, "style": style,
                                          "rotation": rot})
        t.set_placement(self.T(p), align=getattr(TextEntityAlignment, align))
        return t

    def dim(self, p1, p2, offset_mm, label=None):
        """Aligned dimension between two model points, offset in paper mm."""
        a, b = self.T(p1), self.T(p2)
        dx, dy = b[0] - a[0], b[1] - a[1]
        n = math.hypot(dx, dy) or 1.0
        nx, ny = -dy / n, dx / n
        off = offset_mm * self.scale
        d = self.msp.add_aligned_dim(p1=a, p2=b, distance=off, dimstyle="EZDXF",
                                     override={"dimtxt": 2.0 * self.scale, "dimasz": 1.6 * self.scale,
                                               "dimexo": 1.0 * self.scale, "dimexe": 1.0 * self.scale,
                                               "dimgap": 0.6 * self.scale, "dimtxsty": "MONO",
                                               "dimdec": 0, "dimtad": 1, "dimlfac": 1.0, "dimclrd": 7, "dimclre": 7},
                                     dxfattribs={"layer": "DIM"})
        # Always write the text: the measured value is in model mm whatever the
        # dimstyle's scale factor says, and DAME sheets use thousands separators.
        dist = math.hypot(p2[0] - p1[0], p2[1] - p1[1])
        d.set_text(label or "{:,.0f}".format(dist))
        d.render()

    # ---------------------------------------------------------------- frame
    def border(self, number, title, subtitle):
        S = self.scale
        W, H = 420.0 * S, 297.0 * S
        x0, y0 = -W / 2, -H / 2 + 0.0
        m = 10.0 * S
        self.msp.add_lwpolyline([(x0, y0), (x0 + W, y0), (x0 + W, y0 + H), (x0, y0 + H)], close=True,
                                dxfattribs={"layer": "DRAW-RULE"})
        self.msp.add_lwpolyline([(x0 + m, y0 + m), (x0 + W - m, y0 + m), (x0 + W - m, y0 + H - m),
                                 (x0 + m, y0 + H - m)], close=True, dxfattribs={"layer": "DRAW-BORDER"})
        band = 22.0 * S
        h = self.msp.add_hatch(dxfattribs={"layer": "DRAW-BAND"})
        h.rgb = (0x2A, 0x5A, 0x3D)
        h.paths.add_polyline_path([(x0, y0), (x0 + W, y0), (x0 + W, y0 + band), (x0, y0 + band)], is_closed=True)

        def txt(s, x, y, hmm, style, align, layer="DRAW-TEXT"):
            t = self.msp.add_text(s, height=hmm * S, dxfattribs={"layer": layer, "style": style})
            t.set_placement((x, y), align=getattr(TextEntityAlignment, align))
        txt("DAME", x0 + 14 * S, y0 + band / 2, 6.5, "SANS", "MIDDLE_LEFT")
        txt(title, x0 + 52 * S, y0 + 13.5 * S, 4.2, "SERIF", "MIDDLE_LEFT")
        txt(subtitle, x0 + 52 * S, y0 + 6.5 * S, 2.3, "SANS", "MIDDLE_LEFT")
        txt(number, x0 + W - 14 * S, y0 + 13.5 * S, 3.8, "MONO", "MIDDLE_RIGHT")
        txt(self.project["rev_line"] + " · 1:%d at A3 · dimensions mm" % self.scale,
            x0 + W - 14 * S, y0 + 6.5 * S, 2.1, "MONO", "MIDDLE_RIGHT")
        # status strap, top right
        txt(self.project.get("status", "DRAFT FOR REVIEW"), x0 + W - 14 * S, y0 + H - 16 * S, 3.2,
            "SANS", "MIDDLE_RIGHT", "NOTE")
        txt(self.project.get("source_line", ""), x0 + W - 14 * S, y0 + H - 21 * S, 1.8,
            "MONO", "MIDDLE_RIGHT", "NOTE")
        self.paper = (x0, y0, W, H, band)

    def scale_bar(self, at_paper, length_m):
        S = self.scale
        x0, y0 = at_paper
        L = length_m * 1000.0
        n = 5
        for i in range(n):
            h = self.msp.add_hatch(dxfattribs={"layer": "DRAW-TEXT-SEC"})
            h.rgb = (0x1F, 0x1C, 0x1A) if i % 2 == 0 else (0xF4, 0xF1, 0xEB)
            a = x0 + L * i / n
            h.paths.add_polyline_path([(a, y0), (a + L / n, y0), (a + L / n, y0 + 1.6 * S), (a, y0 + 1.6 * S)],
                                      is_closed=True)
        self.msp.add_lwpolyline([(x0, y0), (x0 + L, y0), (x0 + L, y0 + 1.6 * S), (x0, y0 + 1.6 * S)],
                                close=True, dxfattribs={"layer": "DRAW-TEXT-SEC"})
        for v in (0, length_m):
            t = self.msp.add_text("%g m" % v, height=1.8 * S, dxfattribs={"layer": "DRAW-TEXT-SEC", "style": "MONO"})
            t.set_placement((x0 + v * 1000.0, y0 - 1.2 * S), align=TextEntityAlignment.TOP_CENTER)

    def north_arrow(self, at_paper, north_local):
        """north_local: unit vector of true north in the model frame."""
        S = self.scale
        c, s = math.cos(self.rot), math.sin(self.rot)
        nx, ny = c * north_local[0] - s * north_local[1], s * north_local[0] + c * north_local[1]
        x0, y0 = at_paper
        L = 12 * S
        tip = (x0 + nx * L, y0 + ny * L)
        left = (x0 - ny * 2.5 * S, y0 + nx * 2.5 * S)
        right = (x0 + ny * 2.5 * S, y0 - nx * 2.5 * S)
        h = self.msp.add_hatch(dxfattribs={"layer": "NOTE"})
        h.rgb = (0x1F, 0x1C, 0x1A)
        h.paths.add_polyline_path([tip, left, (x0, y0), ], is_closed=True)
        self.msp.add_lwpolyline([tip, left, (x0, y0), right, tip], dxfattribs={"layer": "NOTE"})
        t = self.msp.add_text("N", height=3.2 * S, dxfattribs={"layer": "NOTE", "style": "SANS"})
        t.set_placement((x0 + nx * (L + 4 * S), y0 + ny * (L + 4 * S)), align=TextEntityAlignment.MIDDLE_CENTER)


def classify(label, rules):
    for r in rules:
        if re.search(r["match"], label):
            return r
    return None


def bounds_of(polys):
    xs = [p[0] for pl in polys for p in pl]
    ys = [p[1] for pl in polys for p in pl]
    return (min(xs), min(ys), max(xs), max(ys))


def build_sheet(cfg, geo, project, out_dir):
    sh = Sheet(cfg, project)
    cut = cfg["cut"]                          # "L1", "L2" or "site"
    rules = cfg["layers"]
    include = re.compile(cfg.get("include", ".*"))
    exclude = re.compile(cfg["exclude"]) if cfg.get("exclude") else None

    draw = []   # (layer, loops, poche, dashed)
    for it in geo["items"]:
        lab = it["label"]
        if not include.search(lab) or (exclude and exclude.search(lab)):
            continue
        r = classify(lab, rules)
        if r is None:
            continue
        loops_cut = it["cuts"].get(cut) if cut in ("L1", "L2") else None
        if loops_cut:
            draw.append((r.get("cut", r["layer"]), [l["pts"] for l in loops_cut], r.get("poche"), False))
        elif it["mid"] and (cut == "site" or it["z"][1] <= cfg.get("below_max_z", 1e9)):
            draw.append((r.get("below", r["layer"]), [l["pts"] for l in it["mid"]], None, r.get("dashed_below", False)))
    for lab, layer in cfg.get("site_lines", {}).items():
        for l in geo["site"].get(lab, []):
            draw.append((layer, [l["pts"]], None, layer == "SITE-CONTEXT"))

    if cfg.get("extents"):
        b = cfg["extents"]
    else:
        b = bounds_of([pl for _, loops, _, _ in draw for pl in loops])
    sh.set_centre(b)
    sh.border(cfg["number"], cfg["title"], cfg["subtitle"])

    for layer, loops, poche, dashed in draw:
        if poche:
            sh.hatch(loops, poche)
        for pl in loops:
            closed = len(pl) > 2 and abs(pl[0][0] - pl[-1][0]) < 1 and abs(pl[0][1] - pl[-1][1]) < 1
            sh.poly(pl, layer, closed=closed, dashed=dashed)

    for lab in cfg.get("labels", []):
        # With a sub line, the label sits on the point and the sub hangs below it.
        align = lab.get("align", "BOTTOM_CENTER" if lab.get("sub") else "MIDDLE_CENTER")
        sh.text(lab["text"], lab["xy"], lab.get("h", 2.0), lab.get("layer", "ROOM-TEXT"),
                style=lab.get("style", "SANS"), align=align, rot=lab.get("rot", 0.0))
        if lab.get("sub"):
            sh.text(lab["sub"], (lab["xy"][0], lab["xy"][1]), lab.get("h", 2.0) * 0.8, "TAG", style="MONO",
                    align="TOP_CENTER", rot=lab.get("rot", 0.0))
    if cfg.get("model_labels"):
        for t in geo["labels"]:
            if t["level"] != cfg["model_labels"]:
                continue
            txt = t["text"][0]
            num, _, name = txt.partition(" ")
            # Draft text is placed at its start; shift to the room centre if the
            # model offset it by a per-character amount to centre it.
            shift = cfg.get("model_label_char_shift", 0.0) * len(txt)
            t = dict(t, xy=[t["xy"][0] + shift, t["xy"][1]])
            sh.text(name, t["xy"], 1.6, "ROOM-TEXT", style="SANS", align="BOTTOM_CENTER")
            sh.text(num, t["xy"], 1.4, "TAG", style="MONO", align="TOP_CENTER")
    for d in cfg.get("dims", []):
        sh.dim(d["p1"], d["p2"], d.get("offset_mm", 8), d.get("label"))
    for n in cfg.get("notes", []):
        x0, y0, W, H, band = sh.paper
        S = sh.scale
        y = y0 + H - 16 * S
        for i, line in enumerate(n["lines"]):
            t = sh.msp.add_text(line, height=n.get("h", 2.0) * S, dxfattribs={"layer": "NOTE", "style": "SANS"})
            t.set_placement((x0 + 14 * S, y - i * n.get("h", 2.0) * 1.7 * S), align=TextEntityAlignment.TOP_LEFT)
    x0, y0, W, H, band = sh.paper
    S = sh.scale
    sh.scale_bar((x0 + 14 * S, y0 + band + 8 * S), cfg.get("scale_bar_m", 10))
    sh.north_arrow((x0 + W - 20 * S, y0 + H - 48 * S), project["north_local"])

    base = os.path.join(out_dir, cfg["file"])
    sh.doc.saveas(base + ".dxf")
    render(sh.doc, base, (x0, y0, W, H))
    return base


def render(doc, base, paper):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import RenderContext, Frontend
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    from ezdxf.addons.drawing.config import Configuration, LineweightPolicy, BackgroundPolicy, ColorPolicy

    x0, y0, W, H = paper
    fig = plt.figure(figsize=(16.535, 11.693))
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    fig.patch.set_facecolor("#" + PALETTE["ground"])
    cfg = Configuration(lineweight_policy=LineweightPolicy.ABSOLUTE, lineweight_scaling=1.0,
                        background_policy=BackgroundPolicy.CUSTOM, custom_bg_color="#" + PALETTE["ground"],
                        color_policy=ColorPolicy.COLOR)
    ctx = RenderContext(doc)
    Frontend(ctx, MatplotlibBackend(ax), config=cfg).draw_layout(doc.modelspace(), finalize=False)
    ax.set_xlim(x0, x0 + W)
    ax.set_ylim(y0, y0 + H)
    ax.set_aspect("equal")
    fig.savefig(base + ".pdf", facecolor=fig.get_facecolor())
    fig.savefig(base + ".png", dpi=150, facecolor=fig.get_facecolor())
    plt.close(fig)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--geometry", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    geo = json.load(open(a.geometry))
    conf = json.load(open(a.config))
    os.makedirs(a.out, exist_ok=True)
    proj = conf["project"]
    if "north_local" not in proj:
        yaw = math.radians(geo.get("frame_yaw_deg", 0.0))
        # true north (site +y) expressed in the layout frame: R(-yaw) applied to (0, 1)
        proj["north_local"] = (math.sin(yaw), math.cos(yaw))
    proj.setdefault("source_line", "Cut from %s (saved %s)" % (geo["model"], geo["saved"]))
    for s in conf["sheets"]:
        if a.only and a.only not in s["file"]:
            continue
        base = build_sheet(s, geo, proj, a.out)
        print("wrote", base + ".dxf / .pdf / .png")


if __name__ == "__main__":
    main()
