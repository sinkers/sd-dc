"""Cable tray runs and the supports that hold them up off the ground.

A tray run is routed by the same orthogonal router as a pipe (piping/core):
the tray is treated as a body whose envelope is its overall width, and its
bends take the fitting radius. What a tray adds is support. This module puts
ground-mounted posts under every horizontal run:

  1. Span. The cable load per metre, plus a growth allowance, picks the
     longest published span whose rated load covers it. The rating excludes
     the tray's own weight (the catalogue says so), so self weight is only
     added when sizing the support, not when choosing the span.
  2. Positions. One support within `near_fitting_mm` of each end of a run
     (a bend, riser or termination), then evenly spaced between, never more
     than one span apart.
  3. Splices. Standard lengths are laid from the start of each run; a splice
     that is not within a quarter span of a support gets one.
  4. Fit. Each support is a post, or a pair of posts, from the floor to the
     underside of the tray, with a base plate. Its footprint and column are
     checked against every obstacle; a blocked support tries the other side,
     then slides along the run as far as the span allows. One that still
     cannot stand is reported, with the obstacle in the way.
  5. Choice. A single post with a cantilever bracket where the tray is narrow
     enough and the load small enough; otherwise a goalpost (two posts and a
     cross member). Posts taller than `max_post_height_mm` are flagged for
     bracing.

Rules 2 and 3 follow common practice (NEMA VE 2 installation guidelines:
supports near fitting ends, splices between a support and the quarter-span
point). The defaults are options, and a project's own specification wins.
Support ratings come from whatever support table the caller passes; the ones
in SUPPORTS are the AU01-2 drawing values carried in
cable-tray-ezystrut/cable_tray_router.py and are not verified against a
datasheet. Results are drafts for an engineer, not a structural design.

Vertical runs (risers) are not ground supported. They are listed as open
items needing a wall, structure or equipment fixing.
"""
from __future__ import annotations

import math
import os
import sys
from dataclasses import asdict, dataclass, field

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.join(HERE, "..", "piping"))

from core.geom import Box, Nozzle  # noqa: E402
from core.router import RouteOptions, route_pipe  # noqa: E402

CATALOGUE = os.path.join(HERE, "..", "cable-tray-ezystrut",
                         "tray_catalogue.json")


# ------------------------------------------------------------------ types

@dataclass(frozen=True)
class TrayType:
    family: str
    width: float              # cable laying width, mm
    overall_width: float      # including side rails, mm
    side_height: float        # mm
    self_weight: float        # kg/m
    standard_length: float    # mm
    load_ratings: tuple       # ((span_mm, kg_per_m), ...), any order
    bend_radius: float = 0.0  # inner radius of a bend fitting, mm
    part: str = ""

    # The router reads these three as if this were a pipe.
    @property
    def radius(self) -> float:
        """The larger half-dimension. Routing uses _RouterSpec.envelope,
        which is tighter vertically; this is for messages and batches."""
        return max(self.overall_width, self.side_height) / 2

    @property
    def dn(self) -> int:
        return 0                # no smaller-size suggestions from the router

    @property
    def centre_bend_radius(self) -> float:
        return self.bend_radius + self.width / 2

    def as_dict(self):
        d = asdict(self)
        d["load_ratings"] = [list(x) for x in self.load_ratings]
        return d


class _RouterSpec:
    """What the pipe router needs: radius, bend radius, a dn, and the
    envelope, which lets it keep a flat tray's real clearance above and
    below instead of half its width."""

    def __init__(self, tray: TrayType):
        self.radius = tray.radius
        self.bend_radius = max(tray.centre_bend_radius, tray.radius)
        self.dn = 0
        self._half_w = tray.overall_width / 2
        self._half_h = tray.side_height / 2

    def envelope(self, ax):
        """Half-extents (x, y, z) of the tray on a run along axis ax. A
        horizontal run is flat: half its depth vertically, half its width
        sideways and, conservatively for the fittings, along the run. A
        riser's orientation is not tracked, so it gets half its width on
        every side."""
        return tuple(self._half_h if (k == 2 and ax != 2) else self._half_w
                     for k in range(3))


@dataclass(frozen=True)
class SupportType:
    id: str
    kind: str                  # "cantilever" (one post) or "goalpost"
    post_mm: float             # square post size
    max_tray_width: float      # overall tray width it takes, mm
    working_load_kg: float     # per support
    base_plate_mm: float = 400.0
    description: str = ""


#: AU01-2 drawing values as carried in cable_tray_router.py. Not verified
#: against a datasheet: a support schedule from these is a draft.
SUPPORTS = (
    SupportType("POST100-CB4", "cantilever", 100, 750, 150,
                description="100x100 SHS post, 400x400x10 base plate, "
                            "CB4-750H cantilever bracket"),
    SupportType("POST150-CB4", "cantilever", 150, 750, 150,
                description="150x150 SHS post, 400x400x10 base plate, "
                            "CB4-750H cantilever bracket"),
    SupportType("GOAL100", "goalpost", 100, 1200, 300,
                description="two 100x100 SHS posts, 400x400x10 base plates, "
                            "41x41 strut cross member"),
    SupportType("GOAL150", "goalpost", 150, 1200, 500,
                description="two 150x150 SHS posts, 400x400x10 base plates, "
                            "41x41 strut cross member"),
)


@dataclass
class SupportOptions:
    growth: float = 0.25              # spare capacity on the cable load
    near_fitting_mm: float = 600.0    # support within this of a run end
    splice_fraction: float = 0.25     # splice within this x span of support
    floor_z_mm: float = 0.0
    clearance_mm: float = 50.0        # post and plate to any obstacle
    post_gap_mm: float = 50.0         # tray edge to the face of a post
    slide_step_mm: float = 100.0
    max_post_height_mm: float = 4000.0
    supports: tuple = SUPPORTS


def tray_from_catalogue(catalogue: dict, family: str, width: int,
                        bend_radius: float | None = None) -> TrayType:
    """A TrayType from cable-tray-ezystrut/tray_catalogue.json."""
    fams = catalogue["families"]
    if family not in fams:
        raise ValueError(f"tray family {family!r} not held; have {sorted(fams)}")
    f = fams[family]
    if width not in f["widths_mm"]:
        raise ValueError(f"{family} comes in {f['widths_mm']} mm, not {width}")
    ratings = tuple((p["span_mm"], p["load_kg_per_m"])
                    for p in f["load_ratings"])
    return TrayType(
        family=family, width=width,
        overall_width=width + f.get("overall_width_allowance_mm", 0),
        side_height=f["side_height_mm"],
        self_weight=f["self_weight_kg_per_m"][str(width)],
        standard_length=f["standard_length_mm"], load_ratings=ratings,
        # Bend radius is not in the catalogue. The router this replaces
        # assumed radius = width for ladder; callers should pass the real
        # fitting radius.
        bend_radius=width if bend_radius is None else bend_radius,
        part=f.get("part_pattern", "{width}").format(width=width))


# ------------------------------------------------------------------- span

def choose_span(tray: TrayType, load_kg_per_m: float):
    """Longest published span whose rated load covers the cable load."""
    ok = [(s, r) for s, r in tray.load_ratings if r >= load_kg_per_m]
    if not ok:
        return None
    return max(ok)


# -------------------------------------------------------------- geometry

def _unit(a, b):
    d = [b[i] - a[i] for i in range(3)]
    n = math.dist(a, b)
    return tuple(c / n for c in d), n


def _support_boxes(tray, pos, along, side, st: SupportType, floor, gap):
    """Post columns and base plates for a support at `pos` on a run along
    `along` (unit, horizontal). side is +1 or -1 for a cantilever."""
    perp = (-along[1], along[0], 0.0)
    under = pos[2] - tray.side_height / 2
    offset = tray.overall_width / 2 + gap + st.post_mm / 2
    sides = [side] if st.kind == "cantilever" else [1, -1]
    posts, plates = [], []
    for s in sides:
        c = [pos[i] + perp[i] * s * offset for i in range(2)]
        h = st.post_mm / 2
        posts.append(Box("post", (c[0] - h, c[1] - h, floor),
                         (c[0] + h, c[1] + h, under)))
        b = st.base_plate_mm / 2
        plates.append(Box("plate", (c[0] - b, c[1] - b, floor),
                          (c[0] + b, c[1] + b, floor + 10)))
    # The bracket (cantilever) or cross member (goalpost) sits directly
    # under the tray, from the post to the far edge or from post to post.
    reach = offset + st.post_mm / 2
    if st.kind == "cantilever":
        span = (-tray.overall_width / 2, reach) if side > 0 else \
            (-reach, tray.overall_width / 2)
    else:
        span = (-reach, reach)
    ends = [[pos[i] + perp[i] * o + along[i] * t for i in range(2)]
            for o in span for t in (-21, 21)]
    xs, ys = [e[0] for e in ends], [e[1] for e in ends]
    arm = [Box("arm", (min(xs), min(ys), under - 41),
               (max(xs), max(ys), under))]
    return posts, plates, arm


def _clash(boxes, obstacles, clearance):
    for b in boxes:
        g = Box(b.id, tuple(c - clearance for c in b.lo),
                tuple(c + clearance for c in b.hi))
        for o in obstacles:
            if all(g.lo[i] < o.hi[i] and g.hi[i] > o.lo[i] for i in range(3)):
                return o.id
    return None


# --------------------------------------------------------------- supports

def _runs(points):
    """Horizontal and vertical runs with their end conditions."""
    out = []
    n = len(points) - 1
    for i in range(n):
        a, b = points[i], points[i + 1]
        u, length = _unit(a, b)
        out.append({"index": i, "a": a, "b": b, "dir": u, "length": length,
                    "vertical": abs(u[2]) > 0.5,
                    "start_fitting": i > 0, "end_fitting": i < n - 1})
    return out


def support_run(points, tray: TrayType, cable_kg_per_m: float,
                obstacles=(), opts: SupportOptions | None = None,
                run_id: str = "T-1") -> dict:
    """Ground supports for a routed tray. points are corner points, mm."""
    opts = opts or SupportOptions()
    obstacles = list(obstacles)
    design = cable_kg_per_m * (1 + opts.growth)
    pick = choose_span(tray, design)
    result = {"id": run_id, "tray": tray.as_dict(),
              "cable_kg_per_m": round(cable_kg_per_m, 2),
              "design_kg_per_m": round(design, 2),
              "growth": opts.growth, "supports": [], "issues": [],
              "open_items": []}
    if pick is None:
        best = max(r for _, r in tray.load_ratings)
        result["issues"].append({
            "code": "overloaded",
            "message": f"{design:.1f} kg/m with growth exceeds the "
                       f"{tray.family} {tray.width:g} rating at every "
                       f"published span (best {best:g} kg/m); use a "
                       f"heavier or wider tray or split the cables"})
        return result
    span, rating = pick
    result.update(span_mm=span, rating_kg_per_m=rating,
                  utilisation=round(design / rating, 2))
    R = tray.centre_bend_radius
    total_w = design + tray.self_weight

    for run in _runs(points):
        if run["vertical"]:
            result["open_items"].append({
                "code": "riser_fixing", "run": run["index"],
                "message": f"run {run['index']} is vertical "
                           f"({run['length']:.0f} mm); fix it to a wall, "
                           f"structure or the equipment"})
            continue
        # Straight tray lies between the fittings at each end.
        s0 = R if run["start_fitting"] else 0.0
        s1 = run["length"] - (R if run["end_fitting"] else 0.0)
        if s1 - s0 < 1:
            continue
        sups, issues = _place(run, s0, s1, span, tray, total_w, obstacles,
                              opts)
        sups, more = _splices(run, s0, s1, span, sups, tray, total_w,
                              obstacles, opts)
        issues += more
        result["supports"] += sups
        result["issues"] += issues
    for k, s in enumerate(result["supports"], 1):
        s["id"] = f"{run_id}-S{k:02d}"
    result["bom"] = bom(result["supports"], points, tray)
    return result


def _fits(run, s, tray, total_w, tributary, obstacles, opts, prefer=1):
    """The first support type and side that stands at s, or the obstacle."""
    pos = tuple(run["a"][i] + run["dir"][i] * s for i in range(3))
    height = pos[2] - tray.side_height / 2 - opts.floor_z_mm
    if height <= 0:
        return None, "below_floor"
    load = total_w * tributary / 1000
    blocker = None
    for st in opts.supports:
        if tray.overall_width > st.max_tray_width or load > st.working_load_kg:
            continue
        for side in ((prefer, -prefer) if st.kind == "cantilever" else (1,)):
            posts, plates, arm = _support_boxes(tray, pos, run["dir"], side,
                                                st, opts.floor_z_mm,
                                                opts.post_gap_mm)
            hit = _clash(posts + plates, obstacles, opts.clearance_mm)
            if hit is None:
                return {"run": run["index"], "s_mm": round(s, 1),
                        "pos": [round(c, 1) for c in pos], "type": st.id,
                        "kind": st.kind, "side": side,
                        "post_height_mm": round(height),
                        "load_kg": round(load, 1),
                        "boxes": [{"id": b.id, "min": list(b.lo),
                                   "max": list(b.hi)}
                                  for b in posts + plates + arm]}, None
            blocker = blocker or hit
    if blocker is None:
        return None, "no_support_type"
    return None, blocker


def _place(run, s0, s1, span, tray, total_w, obstacles, opts):
    """Supports from s0 to s1 along a run, evenly spaced, slid if blocked."""
    near = min(opts.near_fitting_mm, (s1 - s0) / 2)
    length = s1 - s0
    # Ends sit `near` in from each end of the straight, or at the middle of
    # a short run. Between them, the fewest supports at no more than span.
    first, last = s0 + min(near, 150.0), s1 - min(near, 150.0)
    # Spacing that divides a standard length, so splices (laid from s0)
    # land next to supports instead of needing posts of their own.
    pitch = tray.standard_length / math.ceil(tray.standard_length / span
                                             - 1e-9)
    if last - first < 1:
        ideal = [(s0 + s1) / 2]
    else:
        ideal = [first]
        while last - ideal[-1] > pitch + 1e-6:
            ideal.append(ideal[-1] + pitch)
        # A short last gap is left short: moving the support before it
        # would pull it off a splice.
        ideal.append(last)
    sups, issues = [], []
    prev = None
    k = 0
    while k < len(ideal):
        s = ideal[k]
        final = k == len(ideal) - 1
        if prev is not None and s > prev + span + 1e-6:
            # An earlier support slid back; re-space the rest from it.
            n = max(1, math.ceil((last - prev) / pitch - 1e-9))
            ideal = ideal[:k] + [prev + (last - prev) * j / n
                                 for j in range(1, n + 1)]
            s = ideal[k]
            final = k == len(ideal) - 1
        # Window this support may slide in: within span of the one behind
        # it, inside the straight, and the end ones near their ends.
        lo = s0 if prev is None else prev + min(300.0, span / 4)
        hi = s1
        if k == 0:
            hi = min(s1, s0 + near)
        if final:
            lo = max(lo, s1 - near)
        if prev is not None:
            hi = min(hi, prev + span)
        trib = (span if 0 < k and not final else span / 2 + near)
        trib = min(trib, length)
        placed, why = _slide(run, s, lo, hi, tray, total_w, trib, obstacles,
                             opts)
        k += 1
        if placed is None:
            issues.append({"code": "support_blocked", "run": run["index"],
                           "s_mm": round(s), "obstacle": why,
                           "message": f"no support fits on run "
                                      f"{run['index']} between "
                                      f"{lo:.0f} and {hi:.0f} mm "
                                      f"({why})"})
            # Carry on as if it stood where it was wanted, so one blocked
            # support is reported once and the rest of the run is still
            # supported.
            prev = s
            continue
        sups.append(placed)
        prev = placed["s_mm"]
        if final and s1 - prev > near + 1e-6:
            # The last one could not get near the end; keep going.
            ideal.append(last)
    # Check the gaps actually achieved.
    ss = [s["s_mm"] for s in sups]
    for a, b in zip(ss, ss[1:]):
        if b - a > span + 1:
            issues.append({"code": "span_exceeded", "run": run["index"],
                           "s_mm": round(a), "gap_mm": round(b - a),
                           "message": f"supports at {a:.0f} and {b:.0f} mm "
                                      f"on run {run['index']} are "
                                      f"{b - a:.0f} mm apart; span is "
                                      f"{span:g}"})
    return sups, issues


def _slide(run, s, lo, hi, tray, total_w, trib, obstacles, opts):
    if hi < lo:
        return None, "no room"
    s = min(max(s, lo), hi)
    why = None
    step = opts.slide_step_mm
    for k in range(int((hi - lo) / step) + 2):
        for t in ((s,) if k == 0 else (s + k * step, s - k * step)):
            if lo - 1e-6 <= t <= hi + 1e-6:
                got, w = _fits(run, t, tray, total_w, trib, obstacles, opts)
                if got:
                    return got, None
                why = why or w
    return None, why


def _splices(run, s0, s1, span, sups, tray, total_w, obstacles, opts):
    """Lay standard lengths from s0; give every splice a nearby support."""
    issues = []
    reach = opts.splice_fraction * span
    s = s0 + tray.standard_length
    while s < s1 - 1:
        if not any(abs(x["s_mm"] - s) <= reach for x in sups):
            got, why = _slide(run, s, max(s0, s - reach), min(s1, s + reach),
                              tray, total_w, span, obstacles, opts)
            if got:
                got["note"] = "at splice"
                sups.append(got)
            else:
                issues.append({"code": "splice_unsupported",
                               "run": run["index"], "s_mm": round(s),
                               "message": f"splice at {s:.0f} mm on run "
                                          f"{run['index']} has no support "
                                          f"within {reach:.0f} mm ({why})"})
        s += tray.standard_length
    sups.sort(key=lambda x: x["s_mm"])
    for x in sups:
        if x["post_height_mm"] > opts.max_post_height_mm:
            x["flag"] = "tall post: bracing and footing need an engineer"
    return sups, issues


# -------------------------------------------------------------------- bom

def bom(supports, points, tray: TrayType):
    n = len(points) - 1
    runs = _runs(points)
    R = tray.centre_bend_radius
    straight = 0.0
    for r in runs:
        straight += max(0.0, r["length"] - R * r["start_fitting"]
                        - R * r["end_fitting"])
    lengths = math.ceil(straight / tray.standard_length - 1e-9)
    elbows = {"horizontal bend 90": 0, "riser 90": 0}
    for i in range(1, n):
        a, b = runs[i - 1]["dir"], runs[i]["dir"]
        if abs(a[2]) > 0.5 or abs(b[2]) > 0.5:
            elbows["riser 90"] += 1
        else:
            elbows["horizontal bend 90"] += 1
    joints = max(0, lengths - 1) + 2 * (n - 1)
    out = [{"item": f"{tray.part or tray.family} straight, "
                    f"{tray.standard_length:g} mm", "count": lengths,
            "length_m": round(straight / 1000, 2)}]
    for k, v in elbows.items():
        if v:
            out.append({"item": f"{tray.family} {tray.width:g} {k}",
                        "count": v})
    out.append({"item": "splice plate pair", "count": joints})
    by = {}
    for s in supports:
        posts = 1 if s["kind"] == "cantilever" else 2
        key = s["type"]
        e = by.setdefault(key, {"item": f"support {key}", "count": 0,
                                "posts": 0, "post_m": 0.0})
        e["count"] += 1
        e["posts"] += posts
        e["post_m"] += posts * s["post_height_mm"] / 1000
    for e in by.values():
        e["post_m"] = round(e["post_m"], 2)
        out.append(e)
    out.append({"item": "base plate 400x400x10",
                "count": sum(1 if s["kind"] == "cantilever" else 2
                             for s in supports)})
    return out


# ------------------------------------------------------------------ route

def route_tray(tray: TrayType, start: Nozzle, end: Nozzle, obstacles=(),
               opts: RouteOptions | None = None):
    """Route a tray run with the pipe router. Returns the RouteResult."""
    return route_pipe(_RouterSpec(tray), start, end, list(obstacles),
                      opts or RouteOptions())
