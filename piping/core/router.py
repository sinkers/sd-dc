"""One orthogonal pipe router, replacing the three in router.py, route_engine.py
and piping.auto_route for anything that only needs a centreline.

The search is A* over corners, not cells. A state is (corner, heading): the
point where an elbow sits and the direction the pipe was travelling when it
got there. A move is a whole straight run from one corner to the next, so the
rules that broke the old grid search are part of the move itself:

  - the first run leaves the outlet along its outward direction, and the last
    run arrives against the inlet's direction; endpoints are never snapped
  - each run is long enough for its elbows: 1 x BR next to a nozzle, 2 x BR
    between two elbows
  - every turn is 90 degrees, never 180
  - no run comes within pipe radius + clearance of an obstacle (geom.py)

Corners are drawn from a coordinate set per axis: the nozzles, the faces of
every grown obstacle, one bend radius out from each nozzle, and a regular grid.
Cost is run length plus a fixed cost per elbow, so of two routes the router
prefers the one with fewer elbows unless the other is much shorter.

A failure is returned as data with a reason, the nozzle and obstacle involved,
the shortfall and suggested fixes, so a caller (or an agent) can act on it.
"""
from __future__ import annotations

import bisect
import heapq
import math
import time
from dataclasses import dataclass, field

from .geom import (AXES, EPS, OWNER_TOL, Box, Nozzle, add, axis_of, dot,
                   manhattan, neg, segment_box, sign_of, travel)
from .specs import SCH10S, PipeSpec, spec_for


@dataclass
class RouteOptions:
    clearance_mm: float = 50.0       # gap kept between pipe surface and obstacles
    grid_mm: float = 250.0           # spacing of the regular corner grid
    bend_cost_mm: float = 1000.0     # an elbow costs as much as this much pipe
    margin_mm: float = 2000.0        # search box beyond the two nozzles
    max_expansions: int = 200_000    # search budget
    floor_z_mm: float | None = None  # pipe centreline stays at least r above this


@dataclass
class RouteResult:
    ok: bool
    points: list = field(default_factory=list)
    failure: dict | None = None
    expansions: int = 0
    ms: float = 0.0


class _Field:
    """Obstacles prepared for one pipe: grown boxes, owner boxes, bounds."""

    def __init__(self, spec, start, end, obstacles, opts):
        self.br = spec.bend_radius
        self.grow = spec.radius + opts.clearance_mm
        self.raw = list(obstacles)
        self.grown = [b.grown(self.grow) for b in obstacles]
        self.start_own = {i for i, b in enumerate(obstacles)
                          if b.contains(start.pos, OWNER_TOL)}
        self.end_own = {i for i, b in enumerate(obstacles)
                        if b.contains(end.pos, OWNER_TOL)}
        self.start_meet = {i for i, b in enumerate(obstacles)
                           if b.meets(start.pos)}
        self.end_meet = {i for i, b in enumerate(obstacles)
                         if b.meets(end.pos)}
        m = opts.margin_mm
        lo = [min(start.pos[i], end.pos[i]) - m for i in range(3)]
        hi = [max(start.pos[i], end.pos[i]) + m for i in range(3)]
        if opts.floor_z_mm is not None:
            lo[2] = max(lo[2], opts.floor_z_mm + spec.radius)
        self.lo, self.hi = lo, hi
        # Only obstacles that reach into the search box matter.
        self.active = [i for i, g in enumerate(self.grown)
                       if all(g.lo[k] < hi[k] and g.hi[k] > lo[k]
                              for k in range(3))]

    def skip(self, i, first, last):
        return (first and i in self.start_own) or (last and i in self.end_own)

    def reach(self, p, d, first=False, last=False):
        """Free travel from p along d, and the obstacle id that stops it."""
        ax, s = axis_of(d), sign_of(d)
        best = (self.hi[ax] - p[ax]) if s > 0 else (p[ax] - self.lo[ax])
        who = "search bounds"
        for i in self.active:
            if self.skip(i, first, last):
                continue
            meet = ((first and i in self.start_meet)
                    or (last and i in self.end_meet))
            t = travel(p, d, self.raw[i] if meet else self.grown[i])
            if t < best:
                best, who = t, self.raw[i].id
        return max(best, 0.0), who


def _coords(spec, start, end, fld, opts):
    """Candidate corner coordinates per axis, sorted."""
    br = spec.bend_radius
    sets = [set() for _ in range(3)]
    for k in range(3):
        sets[k].update((start.pos[k], end.pos[k],
                        start.pos[k] + start.dir[k] * br,
                        end.pos[k] + end.dir[k] * br))
        g = opts.grid_mm
        a = math.floor(fld.lo[k] / g) * g
        while a <= fld.hi[k] + EPS:
            sets[k].add(a)
            a += g
        for i in fld.active:
            b = fld.grown[i]
            sets[k].update((b.lo[k], b.hi[k]))
    return [sorted(c for c in s if fld.lo[k] - EPS <= c <= fld.hi[k] + EPS)
            for k, s in enumerate(sets)]


def _min_bends(p, heading, end, arrive):
    """A lower bound on elbows still needed from corner p travelling `heading`."""
    if heading == arrive:
        ax = axis_of(arrive)
        lined_up = all(abs(p[i] - end.pos[i]) < EPS for i in range(3) if i != ax)
        ahead = dot(tuple(end.pos[i] - p[i] for i in range(3)), arrive) > 0
        return 0 if lined_up and ahead else 2
    if heading == neg(arrive):
        return 2
    return 1


def route_pipe(spec: PipeSpec, start: Nozzle, end: Nozzle,
               obstacles: list[Box] = (), opts: RouteOptions | None = None
               ) -> RouteResult:
    opts = opts or RouteOptions()
    t0 = time.perf_counter()
    fld = _Field(spec, start, end, obstacles, opts)
    coords = _coords(spec, start, end, fld, opts)
    br = spec.bend_radius
    arrive = neg(end.dir)
    bend = opts.bend_cost_mm

    def h(p, heading):
        return manhattan(p, end.pos) + bend * _min_bends(p, heading, end, arrive)

    # Heap entries: (f, tiebreak, g, point, heading, goal_parent).
    # A state is (point, heading); heading None marks the outlet itself.
    # goal_parent is set only on the entry that finishes at the inlet.
    origin = (start.pos, None)
    counter = 0
    heap = [(h(start.pos, start.dir), 0, 0.0, start.pos, None, None)]
    best = {origin: 0.0}
    parent = {origin: None}
    expansions = 0

    while heap:
        _, _, g, p, heading, goal_parent = heapq.heappop(heap)
        if goal_parent is not None:
            pts = [end.pos]
            k = goal_parent
            while k is not None:
                pts.append(k[0])
                k = parent[k]
            pts.reverse()
            return RouteResult(True, pts, None, expansions,
                               (time.perf_counter() - t0) * 1000)
        state = (p, heading)
        if best.get(state, math.inf) < g - EPS:
            continue                      # a cheaper way here was found later
        expansions += 1
        if expansions > opts.max_expansions:
            fail = _diagnose(spec, start, end, fld, coords, opts,
                             budget_hit=True, expansions=expansions)
            return RouteResult(False, [], fail, expansions,
                               (time.perf_counter() - t0) * 1000)

        is_start = heading is None
        turns = [start.dir] if is_start else [d for d in AXES
                                               if dot(d, heading) == 0]
        for d in turns:
            ax, s = axis_of(d), sign_of(d)
            # Finish: a straight run into the inlet.
            if d == arrive:
                lined_up = all(abs(p[i] - end.pos[i]) < EPS
                               for i in range(3) if i != ax)
                L = (end.pos[ax] - p[ax]) * s
                need = 0.0 if is_start else br
                if lined_up and L > EPS and L + EPS >= need:
                    reach, _ = fld.reach(p, d, first=is_start, last=True)
                    if L <= reach + EPS:
                        counter += 1
                        heapq.heappush(heap, (g + L, counter, g + L, end.pos,
                                              d, state))
            # Or run on to a corner and turn there.
            reach, _ = fld.reach(p, d, first=is_start)
            need = br if is_start else 2 * br
            if reach + EPS < need:
                continue
            line = coords[ax]
            if s > 0:
                stops = line[bisect.bisect_left(line, p[ax] + need - EPS):
                             bisect.bisect_right(line, p[ax] + reach + EPS)]
            else:
                stops = line[bisect.bisect_left(line, p[ax] - reach - EPS):
                             bisect.bisect_right(line, p[ax] - need + EPS)]
            for c in stops:
                q = tuple(c if i == ax else p[i] for i in range(3))
                g2 = g + abs(c - p[ax]) + bend
                nxt = (q, d)
                if g2 + EPS < best.get(nxt, math.inf):
                    best[nxt] = g2
                    parent[nxt] = state
                    counter += 1
                    heapq.heappush(heap, (g2 + h(q, d), counter, g2, q, d,
                                          None))

    fail = _diagnose(spec, start, end, fld, coords, opts, budget_hit=False,
                     expansions=expansions)
    return RouteResult(False, [], fail, expansions,
                       (time.perf_counter() - t0) * 1000)


def _suggest_sizes(spec, room, clearance):
    """Smaller DNs whose first elbow fits in `room` mm of straight run."""
    out = []
    for dn in sorted((d for d in SCH10S if d < spec.dn), reverse=True):
        s = spec_for(dn)
        need = s.bend_radius + s.radius + clearance
        if need <= room:
            out.append(f"use DN{dn}, which needs {need:.0f} mm")
            break
    return out


def _blocked(spec, nozzle, side, fld, opts, reach, who):
    br = spec.bend_radius
    role = "outlet" if side == "start" else "inlet"
    if who == "search bounds":
        return {"reason": "no_path", "nozzle": nozzle.id,
                "detail": f"search box ends {reach:.0f} mm from {role} "
                          f"{nozzle.id}; raise margin_mm",
                "suggest": [f"set margin_mm to at least {2 * br:.0f}"]}
    i = next(k for k, b in enumerate(fld.raw) if b.id == who)
    gap = travel(nozzle.pos, nozzle.dir, fld.raw[i])
    need = br + fld.grow
    if math.isinf(gap):
        return {"reason": "blocked_nozzle", "nozzle": nozzle.id,
                "obstacle": who,
                "detail": f"{who} runs alongside the first {br:.0f} mm from "
                          f"{role} {nozzle.id}, inside the {fld.grow:.0f} mm "
                          f"the pipe needs (radius + clearance)",
                "suggest": [f"move {who} sideways",
                            "lower clearance_mm"]}
    short = need - gap
    suggest = [f"move {who} at least {short:.0f} mm further from {nozzle.id}"]
    if br + spec.radius <= gap:
        suggest.append(f"reduce clearance_mm to {gap - br - spec.radius:.0f}")
    suggest += _suggest_sizes(spec, gap, opts.clearance_mm)
    return {"reason": "blocked_nozzle", "nozzle": nozzle.id, "obstacle": who,
            "detail": f"{who} is {gap:.0f} mm from the face of {role} "
                      f"{nozzle.id}; the first elbow needs {need:.0f} mm "
                      f"(BR {br:.1f} + radius {spec.radius:.1f} + clearance "
                      f"{opts.clearance_mm:.0f})",
            "measured": {"gap_mm": round(gap, 1), "need_mm": round(need, 1),
                         "short_mm": round(short, 1)},
            "suggest": suggest}


def _enclosed(spec, nozzle, side, fld, coords, reach):
    """True if no corner on the nozzle's straight run can turn away."""
    br = spec.bend_radius
    ax, s = axis_of(nozzle.dir), sign_of(nozzle.dir)
    line = coords[ax]
    p0 = nozzle.pos[ax]
    for c in line:
        t = (c - p0) * s
        if t < br - EPS or t > reach + EPS:
            continue
        q = tuple(c if i == ax else nozzle.pos[i] for i in range(3))
        for d in AXES:
            if d[ax] == 0 and fld.reach(q, d)[0] + EPS >= 2 * br:
                return False
    return True


def _diagnose(spec, start, end, fld, coords, opts, budget_hit, expansions):
    br = spec.bend_radius
    for nozzle, side in ((start, "start"), (end, "end")):
        reach, who = fld.reach(nozzle.pos, nozzle.dir, first=side == "start",
                               last=side == "end")
        if reach + EPS < br:
            out = _blocked(spec, nozzle, side, fld, opts, reach, who)
            out["side"] = side
            return out
    for nozzle, side in ((end, "end"), (start, "start")):
        reach, who = fld.reach(nozzle.pos, nozzle.dir, first=side == "start",
                               last=side == "end")
        if _enclosed(spec, nozzle, side, fld, coords, reach):
            role = "inlet" if side == "end" else "outlet"
            return {"reason": f"enclosed_{role}", "nozzle": nozzle.id,
                    "side": side,
                    "detail": f"no corner on the straight run from {role} "
                              f"{nozzle.id} ({reach:.0f} mm free, stopped by "
                              f"{who}) can turn away for {2 * br:.0f} mm",
                    "obstacle": who,
                    "suggest": [f"open a side of the enclosure around "
                                f"{nozzle.id}",
                                f"turn {nozzle.id} to face an open side"]}
    if budget_hit:
        return {"reason": "no_path_within_budget",
                "detail": f"stopped after {expansions} expansions",
                "suggest": ["raise max_expansions",
                            "raise grid_mm to search fewer corners"]}
    return {"reason": "no_path",
            "detail": f"every route within {opts.margin_mm:.0f} mm of the "
                      f"nozzles is blocked ({expansions} corners searched)",
            "suggest": ["raise margin_mm", "lower clearance_mm",
                        "move an obstacle"]}


def centreline_parts(points, spec: PipeSpec) -> list[dict]:
    """Straights cut back by BR at every elbow, and the elbows themselves."""
    br = spec.bend_radius
    pts = [tuple(p) for p in points]
    n = len(pts) - 1
    dirs = []
    for i in range(n):
        a, b = pts[i], pts[i + 1]
        ax = max(range(3), key=lambda k: abs(b[k] - a[k]))
        dirs.append(tuple((1 if b[ax] > a[ax] else -1) if k == ax else 0
                          for k in range(3)))
    parts = []
    for i in range(n):
        a, b, d = pts[i], pts[i + 1], dirs[i]
        s = add(a, d, br) if i > 0 else a
        e = add(b, d, -br) if i < n - 1 else b
        length = abs(dot(tuple(e[k] - s[k] for k in range(3)), d))
        parts.append({"type": "straight", "start": _r(s), "end": _r(e),
                      "dir": list(d), "length_mm": round(length, 1)})
        if i < n - 1:
            d2 = dirs[i + 1]
            entry, exit_ = add(b, d, -br), add(b, d2, br)
            parts.append({"type": "elbow", "angle_deg": 90,
                          "bend_radius_mm": round(br, 2),
                          "entry": _r(entry), "exit": _r(exit_),
                          "corner": _r(b), "centre": _r(add(entry, d2, br)),
                          "dir_in": list(d), "dir_out": list(d2),
                          "arc_mm": round(math.pi / 2 * br, 1)})
    return parts


def _r(p):
    return [round(c, 2) for c in p]


def route_network(items, obstacles: list[Box] = (),
                  opts: RouteOptions | None = None) -> list[tuple]:
    """Route pipes in order; each routed pipe is an obstacle to the next.

    items: (id, spec, start Nozzle, end Nozzle). Returns (id, RouteResult).
    A failed pipe does not stop the rest.
    """
    opts = opts or RouteOptions()
    placed = list(obstacles)
    out = []
    for pid, spec, start, end in items:
        res = route_pipe(spec, start, end, placed, opts)
        out.append((pid, res))
        if res.ok:
            for i in range(len(res.points) - 1):
                placed.append(segment_box(res.points[i], res.points[i + 1],
                                          spec.radius, f"{pid}/run{i}",
                                          (start.pos, end.pos)))
    return out
