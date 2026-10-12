"""Points, axis directions, nozzles and boxes, as plain tuples in mm.

Clearance rule used by both the router and the validator: a pipe centreline
must stay out of the open interior of every obstacle box grown by the pipe's
radius plus the clearance. Touching the grown face is allowed. The one
exception is the obstacle a nozzle sits on (its "owner": any box containing
the nozzle point, to within 1 mm). The run leaving or entering that nozzle
ignores its owner, because headers, tees and the end of an earlier pipe put
the nozzle on or inside the owner's box. Every other run still clears it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

EPS = 1e-6
#: How close a nozzle must be to a box to count as sitting on it.
OWNER_TOL = 1.0

AXES = ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))


def axis_dir(v, what="direction") -> tuple[int, int, int]:
    """Snap a direction to a unit axis vector, or refuse."""
    if len(v) != 3:
        raise ValueError(f"{what} must have 3 components, got {v!r}")
    n = math.sqrt(sum(float(c) ** 2 for c in v))
    if n < EPS:
        raise ValueError(f"{what} {list(v)} has zero length")
    u = [float(c) / n for c in v]
    for a in AXES:
        if sum(x * y for x, y in zip(u, a)) > 0.999:
            return a
    raise ValueError(f"{what} {list(v)} is not along an axis; nozzles and "
                     f"pipe runs are orthogonal")


def point(v, what="point") -> tuple[float, float, float]:
    if len(v) != 3:
        raise ValueError(f"{what} must have 3 components, got {v!r}")
    p = tuple(float(c) for c in v)
    if not all(math.isfinite(c) for c in p):
        raise ValueError(f"{what} {list(v)} is not finite")
    return p


def axis_of(d) -> int:
    return next(i for i in range(3) if d[i] != 0)


def sign_of(d) -> int:
    return d[axis_of(d)]


def add(p, d, t):
    return (p[0] + d[0] * t, p[1] + d[1] * t, p[2] + d[2] * t)


def sub(a, b):
    return (a[0] - b[0], a[1] - b[1], a[2] - b[2])


def dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


def neg(d):
    return (-d[0], -d[1], -d[2])


def manhattan(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def dist(a, b):
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


@dataclass(frozen=True)
class Nozzle:
    """A pipe end: centre of the connection face and its outward direction."""
    id: str
    pos: tuple[float, float, float]
    dir: tuple[int, int, int]


@dataclass(frozen=True)
class Box:
    """Axis-aligned obstacle, mm.

    `nodes` are the end points of the pipe a box belongs to, if it is one.
    A new pipe that ends at one of those points meets that pipe at a fitting
    there, so the run into that fitting only has to avoid touching the other
    pipe, not keep the full clearance from it.
    """
    id: str
    lo: tuple[float, float, float]
    hi: tuple[float, float, float]
    nodes: tuple = ()

    def grown(self, by: float) -> "Box":
        return Box(self.id, tuple(c - by for c in self.lo),
                   tuple(c + by for c in self.hi), self.nodes)

    def meets(self, p, tol=OWNER_TOL) -> bool:
        return any(dist(n, p) <= tol for n in self.nodes)

    def contains(self, p, tol=0.0) -> bool:
        return all(self.lo[i] - tol <= p[i] <= self.hi[i] + tol for i in range(3))


def segment_box(a, b, r: float, id: str, nodes=()) -> Box:
    """The box a straight pipe of radius r occupies from a to b."""
    lo = tuple(min(a[i], b[i]) for i in range(3))
    hi = tuple(max(a[i], b[i]) for i in range(3))
    ax = next((i for i in range(3) if abs(a[i] - b[i]) > EPS), None)
    lo = tuple(c if i == ax else c - r for i, c in enumerate(lo))
    hi = tuple(c if i == ax else c + r for i, c in enumerate(hi))
    return Box(id, lo, hi, tuple(nodes))


def travel(p, d, box: Box) -> float:
    """How far from p along axis d before entering box's open interior.

    0 if p is already inside, inf if the ray never enters.
    """
    ax = axis_of(d)
    s = d[ax]
    for i in range(3):
        if i != ax and not (box.lo[i] + EPS < p[i] < box.hi[i] - EPS):
            return math.inf
    if box.lo[ax] + EPS < p[ax] < box.hi[ax] - EPS:
        return 0.0
    if s > 0:
        return box.lo[ax] - p[ax] if box.lo[ax] >= p[ax] - EPS else math.inf
    return p[ax] - box.hi[ax] if box.hi[ax] <= p[ax] + EPS else math.inf


def segment_hits(a, b, box: Box) -> bool:
    """True if the straight centreline a->b enters box's open interior."""
    for i in range(3):
        lo, hi = min(a[i], b[i]), max(a[i], b[i])
        if hi <= box.lo[i] + EPS or lo >= box.hi[i] - EPS:
            return False
    return True
