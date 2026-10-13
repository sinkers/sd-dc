"""Check a centreline someone drew: the same rules `route_engine.validate_waypoints`
enforces, returned as structured issues instead of strings, plus clearance.

Rules (piping/README.md):
  - first point on the outlet nozzle, first run along its outward direction
  - last point on the inlet nozzle, last run arriving against its direction
  - every run on one axis; consecutive runs at 90 degrees, never 180
  - first and last runs >= 1 x BR, interior runs >= 2 x BR
  - no run inside an obstacle grown by pipe radius + clearance (geom.py)
"""
from __future__ import annotations

from .geom import (EPS, OWNER_TOL, Box, Nozzle, dist, dot, grow_box, neg,
                   segment_hits)
from .specs import PipeSpec

POS_TOL = 1.0


def _unit(a, b):
    d = [b[i] - a[i] for i in range(3)]
    moving = [i for i in range(3) if abs(d[i]) > 0.5]
    if len(moving) != 1:
        return None, len(moving)
    u = [0, 0, 0]
    u[moving[0]] = 1 if d[moving[0]] > 0 else -1
    return tuple(u), 1


def validate_route(points, spec: PipeSpec, start: Nozzle | None = None,
                   end: Nozzle | None = None, obstacles: list[Box] = (),
                   clearance: float = 0.0) -> list[dict]:
    """Return a list of issues; empty means the route can be built."""
    issues = []

    def issue(code, message, **extra):
        issues.append({"code": code, "message": message, **extra})

    pts = [tuple(float(c) for c in p) for p in points]
    if len(pts) < 2:
        issue("too_few_points", "a route needs at least 2 points")
        return issues
    br = spec.bend_radius
    n = len(pts) - 1
    dirs = []
    for i in range(n):
        u, k = _unit(pts[i], pts[i + 1])
        if u is None:
            issue("not_orthogonal",
                  f"run {i} moves on {k} axes; runs must follow one axis",
                  segment=i)
        dirs.append(u)

    if start is not None:
        gap = dist(pts[0], start.pos)
        if gap > POS_TOL:
            issue("start_off_nozzle",
                  f"first point is {gap:.1f} mm from outlet {start.id}",
                  nozzle=start.id, gap_mm=round(gap, 1))
        if dirs[0] is not None and dirs[0] != start.dir:
            issue("start_direction",
                  f"first run goes {list(dirs[0])}, outlet {start.id} faces "
                  f"{list(start.dir)}", nozzle=start.id, segment=0)
    if end is not None:
        gap = dist(pts[-1], end.pos)
        if gap > POS_TOL:
            issue("end_off_nozzle",
                  f"last point is {gap:.1f} mm from inlet {end.id}",
                  nozzle=end.id, gap_mm=round(gap, 1))
        if dirs[-1] is not None and dirs[-1] != neg(end.dir):
            issue("end_direction",
                  f"last run goes {list(dirs[-1])}, must arrive "
                  f"{list(neg(end.dir))} into inlet {end.id}",
                  nozzle=end.id, segment=n - 1)

    for i in range(n - 1):
        a, b = dirs[i], dirs[i + 1]
        if a is not None and b is not None and dot(a, b) < -0.5:
            issue("reversal",
                  f"runs {i} and {i + 1} reverse on one axis; a 90 degree "
                  f"elbow cannot do that, add a perpendicular run",
                  segment=i + 1)
        if a is not None and b is not None and a == b:
            issue("collinear_point",
                  f"point {i + 1} sits mid-run; drop it", segment=i + 1)

    for i in range(n):
        length = dist(pts[i], pts[i + 1])
        ends = (i > 0) + (i < n - 1)        # elbows on this run
        need = ends * br
        if length + EPS < need:
            issue("segment_too_short",
                  f"run {i} is {length:.0f} mm; needs {need:.0f} mm for "
                  f"{ends} elbow(s) at BR {br:.1f}",
                  segment=i, length_mm=round(length, 1),
                  min_mm=round(need, 1))

    if obstacles:
        grow = spec.radius + clearance
        for i in range(n):
            for box in obstacles:
                own = ((i == 0 and start is not None
                        and box.contains(start.pos, OWNER_TOL))
                       or (i == n - 1 and end is not None
                           and box.contains(end.pos, OWNER_TOL)))
                meet = ((i == 0 and start is not None
                         and box.meets(start.pos))
                        or (i == n - 1 and end is not None
                            and box.meets(end.pos)))
                env = getattr(spec, "envelope", None)
                if meet:
                    test = box
                elif env is None:
                    test = box.grown(grow)
                else:
                    ax = next((k for k in range(3)
                               if abs(pts[i + 1][k] - pts[i][k]) > 1e-6), 0)
                    test = grow_box(box, tuple(e + clearance
                                               for e in env(ax)))
                if not own and segment_hits(pts[i], pts[i + 1], test):
                    issue("collision",
                          f"run {i} passes within {grow:.0f} mm of {box.id}",
                          segment=i, obstacle=box.id)
    return issues
