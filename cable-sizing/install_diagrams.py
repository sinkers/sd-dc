"""Inline SVG diagrams for cable installation arrangements.

An installation method is a picture before it is a word: "unenclosed spaced"
and "enclosed in conduit" differ by how much still air surrounds the conductor
and what it can radiate to, which is exactly what sets the tabulated rating. So
each diagram draws the geometry that drives the number -- spacing, the surface,
the enclosure, the soil and the depth -- rather than being decoration.

Every diagram is a self-contained `<svg>` on a 200x136 viewBox, drawn with a
small set of CSS custom properties so it inherits the page's theme in both light
and dark rather than carrying baked-in colours.

The viewBox is split into a drawing band (y 0-100) and a caption band
(y 100-136) that nothing else is allowed to enter. That split exists because the
first version put captions over the hatched wall and soil fills, where they were
unreadable.

Conventions kept consistent across the set, so the pictures can be compared:
  conductor   filled circle, --dg-cu
  insulation  ring around the conductor, --dg-ins
  surface     hatched block, --dg-solid   (wall, floor, tray)
  soil        stippled fill, --dg-soil
  air gap     dimension line with arrows, --dg-dim
"""
from __future__ import annotations

W, H = 200, 136
DRAW_BOTTOM = 100      # nothing drawn below this; the caption band starts here
CAP_Y = 116            # first caption line
CAP_Y2 = 129           # second caption line

CSS = """
svg.dg{width:100%;height:auto;display:block;
  --dg-cu:#b5721f; --dg-ins:#7b8494; --dg-solid:#9aa4b2; --dg-soil:#8a7d63;
  --dg-dim:#0f5ea8; --dg-line:#5d6673}
@media (prefers-color-scheme:dark){svg.dg{
  --dg-cu:#d99a4e; --dg-ins:#8b95a5; --dg-solid:#6c7684; --dg-soil:#a3937a;
  --dg-dim:#63a8e8; --dg-line:#9aa4b2}}
svg.dg text{font:9px -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
  fill:var(--dg-line)}
svg.dg text.dim{fill:var(--dg-dim);font-weight:600}
"""

_DEFS = """<defs>
 <pattern id="hatch" width="6" height="6" patternTransform="rotate(45)"
   patternUnits="userSpaceOnUse">
  <line x1="0" y1="0" x2="0" y2="6" stroke="var(--dg-solid)" stroke-width="2.4"/>
 </pattern>
 <pattern id="soil" width="8" height="8" patternUnits="userSpaceOnUse">
  <circle cx="2" cy="2" r="1" fill="var(--dg-soil)"/>
  <circle cx="6" cy="5" r="1" fill="var(--dg-soil)"/>
 </pattern>
 <marker id="ar" viewBox="0 0 8 8" refX="4" refY="4" markerWidth="5"
   markerHeight="5" orient="auto">
  <path d="M0,1 L7,4 L0,7 z" fill="var(--dg-dim)"/>
 </marker>
</defs>"""


def _cable(cx, cy, r=11):
    """One single-core cable: conductor, insulation ring, sheath outline."""
    return (
        f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" '
        f'stroke="var(--dg-ins)" stroke-width="3"/>'
        f'<circle cx="{cx}" cy="{cy}" r="{r - 4.5}" fill="var(--dg-cu)"/>'
    )


def _dim(x1, x2, y, label):
    """A horizontal dimension line with arrowheads at both ends."""
    return (
        f'<line x1="{x1}" y1="{y}" x2="{x2}" y2="{y}" stroke="var(--dg-dim)" '
        f'stroke-width="1.1" marker-start="url(#ar)" marker-end="url(#ar)"/>'
        f'<text class="dim" x="{(x1 + x2) / 2}" y="{y - 4}" '
        f'text-anchor="middle">{label}</text>'
    )


def _cap(*lines):
    """Caption lines, in the reserved band below the drawing."""
    ys = (CAP_Y,) if len(lines) == 1 else (CAP_Y, CAP_Y2)
    return "".join(
        f'<text x="{W / 2}" y="{y}" text-anchor="middle">{t}</text>'
        for t, y in zip(lines, ys))


def _note(text, y=12):
    """A short note inside the drawing band, for use over empty air only."""
    return (f'<text x="{W / 2}" y="{y}" text-anchor="middle">{text}</text>')


def _svg(body, title):
    return (f'<svg class="dg" viewBox="0 0 {W} {H}" role="img" '
            f'aria-label="{title}">{_DEFS}{body}</svg>')


# --------------------------------------------------------------------- air

def spaced():
    """Single-core cables in free air, spaced from each other and the surface."""
    y = 52
    body = (
        f'<rect x="0" y="84" width="{W}" height="16" fill="url(#hatch)"/>'
        f'<line x1="0" y1="84" x2="{W}" y2="84" stroke="var(--dg-line)" '
        f'stroke-width="1.4"/>'
        + "".join(_cable(x, y) for x in (48, 100, 152))
        + _dim(59, 89, y, "&#8805;1 D")
        + f'<line x1="152" y1="63" x2="152" y2="84" stroke="var(--dg-dim)" '
          f'stroke-width="1.1" marker-start="url(#ar)" marker-end="url(#ar)"/>'
        + f'<text class="dim" x="157" y="76">&#8805;1 D</text>'
        + _note("free air all round")
        + _cap("spaced from each other and the surface")
    )
    return _svg(body, "Cables spaced apart in free air, clear of a surface")


def touching():
    """Single-core cables laid flat and touching, single layer on a tray."""
    y = 54
    body = (
        f'<path d="M20,78 L20,62 M180,78 L180,62" stroke="var(--dg-line)" '
        f'stroke-width="1.8" fill="none"/>'
        f'<rect x="20" y="70" width="160" height="8" fill="url(#hatch)"/>'
        f'<line x1="20" y1="70" x2="180" y2="70" stroke="var(--dg-line)" '
        f'stroke-width="1.6"/>'
        + "".join(_cable(x, y) for x in (78, 100, 122))
        + _note("cables in contact")
        + _cap("single layer on a tray or ladder")
    )
    return _svg(body, "Cables touching in a single layer on a tray")


def trefoil():
    """Three single-core cables bunched in trefoil formation."""
    body = (
        f'<path d="M20,84 L20,68 M180,84 L180,68" stroke="var(--dg-line)" '
        f'stroke-width="1.8" fill="none"/>'
        f'<rect x="20" y="76" width="160" height="8" fill="url(#hatch)"/>'
        f'<line x1="20" y1="76" x2="180" y2="76" stroke="var(--dg-line)" '
        f'stroke-width="1.6"/>'
        + _cable(90, 42) + _cable(110, 42) + _cable(100, 59)
        + _note("three cables bunched")
        + _cap("trefoil, touching, in free air")
    )
    return _svg(body, "Three cables bunched in a trefoil formation")


def clipped_direct():
    """Cables clipped hard against a surface, with no air gap behind."""
    y = 54
    body = (
        f'<rect x="0" y="72" width="{W}" height="28" fill="url(#hatch)"/>'
        f'<line x1="0" y1="72" x2="{W}" y2="72" stroke="var(--dg-line)" '
        f'stroke-width="1.4"/>'
        + "".join(_cable(x, y) for x in (70, 100, 130))
        # Saddle clips, drawn as a bracket over the top of each cable. Earlier
        # these were full semicircles, which read as a second insulation ring.
        + "".join(
            f'<path d="M{x - 14},{y + 4} L{x - 14},{y - 6} '
            f'Q{x},{y - 17} {x + 14},{y - 6} L{x + 14},{y + 4}" '
            f'stroke="var(--dg-line)" stroke-width="1.5" fill="none"/>'
            for x in (70, 100, 130))
        + _note("no gap behind the cable")
        + _cap("clipped direct to the surface")
    )
    return _svg(body, "Cables clipped directly against a wall surface")


def tray_perforated():
    """Perforated tray: air moves through the support as well as around it."""
    y = 50
    perfs = "".join(
        f'<circle cx="{x}" cy="74" r="2.1" fill="var(--dg-line)" opacity="0.55"/>'
        for x in range(32, 176, 14))
    body = (
        f'<path d="M20,82 L20,62 M180,82 L180,62" stroke="var(--dg-line)" '
        f'stroke-width="1.8" fill="none"/>'
        f'<rect x="20" y="68" width="160" height="12" fill="url(#hatch)" '
        f'opacity="0.7"/>'
        f'<line x1="20" y1="68" x2="180" y2="68" stroke="var(--dg-line)" '
        f'stroke-width="1.6"/>' + perfs
        + "".join(_cable(x, y) for x in (66, 100, 134))
        + _note("free air rating")
        + _cap("perforated tray, air through and around")
    )
    return _svg(body, "Cables on a perforated cable tray in free air")


def conduit_air():
    """Cables inside a conduit surrounded by air on every side."""
    body = (
        f'<circle cx="100" cy="52" r="33" fill="none" stroke="var(--dg-solid)" '
        f'stroke-width="4.5"/>'
        + _cable(100, 39, 10) + _cable(88, 61, 10) + _cable(112, 61, 10)
        + f'<text x="150" y="24">conduit</text>'
        + f'<line x1="149" y1="27" x2="127" y2="37" stroke="var(--dg-line)" '
          f'stroke-width="1"/>'
        + _cap("conduit surrounded by air")
    )
    return _svg(body, "Cables enclosed in a conduit surrounded by air")


def conduit_wall():
    """Conduit fixed to a solid wall, so heat sinks into the wall on one side."""
    body = (
        f'<rect x="0" y="80" width="{W}" height="20" fill="url(#hatch)"/>'
        f'<line x1="0" y1="80" x2="{W}" y2="80" stroke="var(--dg-line)" '
        f'stroke-width="1.4"/>'
        f'<circle cx="100" cy="50" r="28" fill="none" stroke="var(--dg-solid)" '
        f'stroke-width="4.5"/>'
        + _cable(100, 38, 9) + _cable(90, 58, 9) + _cable(110, 58, 9)
        + _note("conduit on the wall face")
        + _cap("solid wall, or in trunking")
    )
    return _svg(body, "Conduit mounted on a solid wall")


def conduit_insulated_wall():
    """Conduit buried in a thermally insulated wall: the worst case for cooling."""
    body = (
        f'<rect x="0" y="20" width="{W}" height="80" fill="url(#hatch)" '
        f'opacity="0.4"/>'
        f'<rect x="0" y="20" width="{W}" height="80" fill="none" '
        f'stroke="var(--dg-line)" stroke-width="1.4"/>'
        f'<circle cx="100" cy="60" r="27" fill="none" stroke="var(--dg-solid)" '
        f'stroke-width="4.5"/>'
        + _cable(100, 48, 9) + _cable(90, 68, 9) + _cable(110, 68, 9)
        + _note("thermal insulation all round")
        + _cap("in a thermally insulated wall",
               "least favourable for cooling")
    )
    return _svg(body, "Conduit inside a thermally insulated wall")


def messenger():
    """Cables supported from a messenger wire in open air."""
    y = 62
    body = (
        f'<path d="M8,26 Q100,42 192,26" stroke="var(--dg-line)" '
        f'stroke-width="2.2" fill="none"/>'
        f'<circle cx="8" cy="26" r="3.2" fill="var(--dg-line)"/>'
        f'<circle cx="192" cy="26" r="3.2" fill="var(--dg-line)"/>'
        # Drop wires run from the catenary down to each cable, so they have to
        # start at the curve's actual height, not a flat guess.
        + "".join(
            f'<line x1="{x}" y1="{yc}" x2="{x}" y2="{y - 11}" '
            f'stroke="var(--dg-line)" stroke-width="1.3"/>'
            for x, yc in ((66, 37), (100, 39), (134, 37)))
        + "".join(_cable(x, y) for x in (66, 100, 134))
        + _note("messenger wire", 18)
        + _cap("suspended in open air")
    )
    return _svg(body, "Cables suspended from a messenger wire in open air")


# -------------------------------------------------------------------- soil

def buried_direct():
    """Cables laid direct in soil at the standard depth of burial."""
    y = 70
    body = (
        f'<rect x="0" y="30" width="{W}" height="70" fill="url(#soil)"/>'
        f'<rect x="0" y="30" width="{W}" height="4" fill="var(--dg-soil)"/>'
        f'<line x1="0" y1="30" x2="{W}" y2="30" stroke="var(--dg-line)" '
        f'stroke-width="1.4"/>'
        + "".join(_cable(x, y) for x in (72, 100, 128))
        + f'<line x1="34" y1="30" x2="34" y2="{y}" stroke="var(--dg-dim)" '
          f'stroke-width="1.1" marker-start="url(#ar)" marker-end="url(#ar)"/>'
        + f'<text class="dim" x="39" y="53">depth</text>'
        + _note("ground level", 24)
        + _cap("laid direct in soil")
    )
    return _svg(body, "Cables buried directly in soil below ground level")


def buried_ducts():
    """Cables in underground ducts: the air inside the duct adds resistance."""
    y = 68
    body = (
        f'<rect x="0" y="30" width="{W}" height="70" fill="url(#soil)"/>'
        f'<rect x="0" y="30" width="{W}" height="4" fill="var(--dg-soil)"/>'
        f'<line x1="0" y1="30" x2="{W}" y2="30" stroke="var(--dg-line)" '
        f'stroke-width="1.4"/>'
        + "".join(
            f'<circle cx="{x}" cy="{y}" r="17" fill="none" '
            f'stroke="var(--dg-solid)" stroke-width="3.4"/>' + _cable(x, y, 9)
            for x in (58, 100, 142))
        + _note("ground level", 24)
        + _cap("separate underground ducts")
    )
    return _svg(body, "Cables in separate underground ducts")


def generic():
    body = _cap("no diagram for this arrangement")
    return _svg(body, "No diagram available")


DIAGRAMS = {
    "spaced": spaced,
    "touching": touching,
    "trefoil": trefoil,
    "clipped_direct": clipped_direct,
    "tray_perforated": tray_perforated,
    "conduit_air": conduit_air,
    "conduit_wall": conduit_wall,
    "conduit_insulated_wall": conduit_insulated_wall,
    "messenger": messenger,
    "buried_direct": buried_direct,
    "buried_ducts": buried_ducts,
    "generic": generic,
}


def svg(key):
    """SVG markup for a diagram key, falling back to a labelled placeholder."""
    return DIAGRAMS.get(key, generic)()


def all_svg():
    return {k: fn() for k, fn in DIAGRAMS.items()}
