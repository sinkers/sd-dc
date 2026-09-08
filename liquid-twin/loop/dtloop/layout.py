"""The plant layout, as data. One source for the geometry and the physics.

SPEC.md section 9 argues that the hydraulic graph and the render geometry should
come from the same routed network, so a layout change updates the physics and
the picture together. This module is that source. It holds no FreeCAD import and
no numpy dependency - just coordinates and connectivity - so it can be read by

  * geometry/model_loop.py   to build solids and export STEP
  * viewer/prepare_geometry.py to pack meshes for the browser
  * network.py (Phase 2)     to build the Network the solver runs on

Topology follows Schneider RD110 rev 3 (`RD110_3.2_Mech_Piping_EN_R1`): four
high-temperature chillers in N+1 on a common facility header, nine
liquid-to-liquid CDUs in three pods of three, and 48 liquid-cooled racks with one
control valve each - RD110's PCV01..PCV48.

Coordinates are millimetres, X = width, Y = depth, Z = height, matching the rest
of the toolkit (see cooling-model/README.md). The origin is the near-left corner
of the first pod.

Every segment is named and carries its service, so nothing downstream has to
guess which pipe is which: a viewer colours by `service` until Phase 2 gives it
real temperatures, and the solver reads `dn` and `length_mm` for its loss
coefficients.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# -- services ------------------------------------------------------------
# The four pipe services, with the RD110 design temperature each runs at.
# Phase 2 replaces the fixed temperature with the transported one; until then
# this is what the viewer colours by.
SERVICES = {
    "facility_supply": {"design_c": 37.0, "label": "Facility supply (CDU CW in)"},
    "facility_return": {"design_c": 47.0, "label": "Facility return (CDU CW out)"},
    "tcs_supply": {"design_c": 40.0, "label": "TCS supply (cold plate in)"},
    "tcs_return": {"design_c": 50.0, "label": "TCS return (cold plate out)"},
}

# -- geometry constants --------------------------------------------------
RACK_W, RACK_D, RACK_H = 600, 1200, 2200          # NetShelter MGX, per RD110_4.2
RACKS_PER_ROW = 8
HOT_AISLE_W = 2000                                 # RD110: "2 m wide ducted hot aisle"
POD_PITCH_Y = 10000
POD_COUNT = 3
CDU_W, CDU_D, CDU_H = 1200, 1000, 2000             # Motivair MCDU-50, floor mounted
CDU_PER_POD = 3
CHILLER_L, CHILLER_W, CHILLER_H = 12000, 2500, 2600   # Uniflair XRAF4242A EHT
CHILLER_COUNT = 4                                  # N+1
CHILLER_PITCH_Y = 7000

# Chilled water pumps. RD110_3.3 lists seven CWPs across the two water systems,
# "to be sized upon design implementation"; four of them serve the HT circuit,
# one per chiller, which is the arrangement drawn here.
PUMP_W, PUMP_D, PUMP_H = 1500, 1000, 1400
PUMP_X = 16800

# Flow meters, one per CDU per side. Drawn as a short collar on the pipe rather
# than a box beside it, because that is what a magnetic or ultrasonic meter is:
# a spool piece in the line.
FM_LENGTH = 300
FM_RADIUS_FACTOR = 1.45

RACK_X0 = 2000
CDU_X0 = 9000
CDU_PITCH_X = 1600
FACILITY_X_SUPPLY = 15000
FACILITY_X_RETURN = 15900
CHILLER_X0 = 19000

TCS_HEADER_Z = 3800        # overhead, above the pods
FACILITY_HEADER_Z = 4400   # above the TCS headers, so crossings are clear
RACK_TOP_Z = RACK_H
POD_DEPTH = RACK_D + HOT_AISLE_W + RACK_D

# Pipe sizes.
#
# DN150 is the only callout on RD110_3.2, and applying it to the facility mains
# as well as the branch runs was wrong: the mains carry all 540 m3/h, which at
# DN150 is 8.5 m/s. That is four times a sensible design velocity, and it was
# the flow display that caught it - the number had been sitting in
# loop_params.json as hydraulic.design_velocity_ms, unused, the whole time.
#
# Everything is now sized against V_MAX. RD110's DN150 turns out to be
# consistent with the chiller branches and the TCS headers at about 2.8 m/s;
# only the mains needed to go up, to DN300 at 2.1 m/s.
V_MAX = 3.0  # m/s. Common upper bound for chilled water. Grade L.

# Standard DN ladder, ISO 6708.
DN_LADDER = (25, 32, 40, 50, 65, 80, 100, 125, 150, 200, 250, 300, 350, 400, 500)


def size_dn(q_m3s: float, v_max: float = V_MAX) -> int:
    """Smallest standard DN whose bore keeps velocity at or below `v_max`.

    Uses the DN as the bore, which is a simplification - real DN300 schedule 10
    has a 307 mm inside diameter, not 300 - but the error is under 3 % and
    always on the conservative side of the velocity check.
    """
    import math as _math
    for dn in DN_LADDER:
        area = _math.pi * (dn / 1000.0) ** 2 / 4.0
        if q_m3s / area <= v_max:
            return dn
    return DN_LADDER[-1]


# Design flows, from the RD110 duty at a 10 K rise on both loops. Repeated here
# rather than imported from plant.py, because plant.py imports this module and
# a cycle for four constants is not worth it. test_layout pins them together.
_Q_FACILITY_M3S = 540.2 / 3600.0
_Q_CHILLER_BRANCH_M3S = 180.1 / 3600.0
_Q_TCS_POD_M3S = 179.3 / 3600.0
_Q_CDU_M3S = 60.0 / 3600.0
_Q_RACK_M3S = 11.2 / 3600.0

DN_FACILITY_MAIN = size_dn(_Q_FACILITY_M3S)     # 300
DN_CHILLER_BRANCH = size_dn(_Q_CHILLER_BRANCH_M3S)  # 150 - matches RD110
DN_TCS_HEADER = size_dn(_Q_TCS_POD_M3S)         # 150 - matches RD110
DN_CDU_TIE = size_dn(_Q_CDU_M3S)                # 100
DN_RACK_DROP = size_dn(_Q_RACK_M3S)             # 50


@dataclass(frozen=True)
class Point:
    x: float
    y: float
    z: float

    def as_tuple(self) -> tuple[float, float, float]:
        return (self.x, self.y, self.z)


@dataclass
class Equipment:
    """A box of plant. `kind` drives the material in the viewer."""

    name: str
    kind: str  # rack | cdu | chiller | pump
    origin: Point  # near-left-bottom corner
    size: tuple[float, float, float]
    label: str = ""
    pod: int | None = None
    # Set on pumps and flow meters: the branch whose solved flow they report.
    reads_branch: str = ""

    def centre(self) -> Point:
        return Point(
            self.origin.x + self.size[0] / 2,
            self.origin.y + self.size[1] / 2,
            self.origin.z + self.size[2] / 2,
        )


@dataclass
class Segment:
    """One pipe run: an ordered polyline, a bore, and a service.

    `waypoints` are the centreline. Consecutive points must differ in exactly
    one axis - the runs are orthogonal, as `piping/` builds them - which
    `validate` checks, because a diagonal here would silently produce a pipe
    that no fabricator could make.
    """

    name: str
    service: str
    dn: int
    waypoints: list[Point]
    from_node: str = ""
    to_node: str = ""
    valve: str = ""  # RD110 tag, where the segment carries one
    meter: str = ""  # flow meter tag, where the segment carries one
    pod: int | None = None

    def length_mm(self) -> float:
        total = 0.0
        for a, b in zip(self.waypoints, self.waypoints[1:]):
            total += abs(b.x - a.x) + abs(b.y - a.y) + abs(b.z - a.z)
        return total

    def elbows(self) -> int:
        """Direction changes along the run - the fitting count the solver needs."""
        if len(self.waypoints) < 3:
            return 0
        turns = 0
        for a, b, c in zip(self.waypoints, self.waypoints[1:], self.waypoints[2:]):
            d1 = (b.x - a.x, b.y - a.y, b.z - a.z)
            d2 = (c.x - b.x, c.y - b.y, c.z - b.z)
            if _axis(d1) != _axis(d2):
                turns += 1
        return turns


def route(*points: Point) -> list[Point]:
    """A centreline with zero-length steps removed.

    Worth having rather than being careful by hand: a tie-in that happens to
    arrive exactly on the header line produces a repeated waypoint, which is
    geometrically harmless but makes `validate` report a step that moves along
    no axis - indistinguishable, in the message, from a genuine diagonal. This
    filters the harmless case so the check keeps meaning what it says.
    """
    out: list[Point] = []
    for p in points:
        if not out or (p.x, p.y, p.z) != (out[-1].x, out[-1].y, out[-1].z):
            out.append(p)
    if len(out) < 2:
        raise ValueError("a route needs at least two distinct points")
    return out


def _axis(d: tuple[float, float, float]) -> int:
    """Which axis a step moves along. -1 if it moves along none or several."""
    moving = [i for i, v in enumerate(d) if abs(v) > 1e-9]
    return moving[0] if len(moving) == 1 else -1


@dataclass
class LoopLayout:
    name: str = "RD110-AU01"
    equipment: list[Equipment] = field(default_factory=list)
    segments: list[Segment] = field(default_factory=list)

    def by_kind(self, kind: str) -> list[Equipment]:
        return [e for e in self.equipment if e.kind == kind]

    def by_service(self, service: str) -> list[Segment]:
        return [s for s in self.segments if s.service == service]

    def total_pipe_m(self) -> float:
        return sum(s.length_mm() for s in self.segments) / 1000.0

    def bounds(self) -> tuple[Point, Point]:
        xs, ys, zs = [], [], []
        for e in self.equipment:
            xs += [e.origin.x, e.origin.x + e.size[0]]
            ys += [e.origin.y, e.origin.y + e.size[1]]
            zs += [e.origin.z, e.origin.z + e.size[2]]
        for s in self.segments:
            for p in s.waypoints:
                xs.append(p.x)
                ys.append(p.y)
                zs.append(p.z)
        return Point(min(xs), min(ys), min(zs)), Point(max(xs), max(ys), max(zs))

    def validate(self) -> list[str]:
        """Problems a reviewer would otherwise have to spot in the 3D view."""
        problems: list[str] = []
        seen: set[str] = set()
        for e in self.equipment:
            if e.name in seen:
                problems.append(f"duplicate equipment name {e.name!r}")
            seen.add(e.name)
        for s in self.segments:
            if s.name in seen:
                problems.append(f"duplicate segment name {s.name!r}")
            seen.add(s.name)
            if s.service not in SERVICES:
                problems.append(f"{s.name}: unknown service {s.service!r}")
            if len(s.waypoints) < 2:
                problems.append(f"{s.name}: needs at least two waypoints")
                continue
            for i, (a, b) in enumerate(zip(s.waypoints, s.waypoints[1:])):
                d = (b.x - a.x, b.y - a.y, b.z - a.z)
                if _axis(d) < 0:
                    problems.append(
                        f"{s.name}: step {i} from {a.as_tuple()} to {b.as_tuple()} "
                        f"is not an orthogonal move"
                    )
        return problems


# -- the layout ----------------------------------------------------------

def pod_y0(pod: int) -> float:
    return pod * POD_PITCH_Y


def build_layout() -> LoopLayout:
    """RD110's two-loop plant, laid out for review.

    Read top to bottom it is the flow path: chillers make 37 C water, the
    facility mains carry it to the CDUs, each CDU hands 40 C to its pod's TCS
    headers, and 48 rack drops take it to the cold plates and back.
    """
    lay = LoopLayout()
    eq, seg = lay.equipment, lay.segments

    # --- chillers, on the facility side -------------------------------
    for i in range(CHILLER_COUNT):
        eq.append(Equipment(
            name=f"HT_CH-{i + 1}" if i < CHILLER_COUNT - 1 else "HT_CH-N+1",
            kind="chiller",
            origin=Point(CHILLER_X0, i * CHILLER_PITCH_Y, 0),
            size=(CHILLER_L, CHILLER_W, CHILLER_H),
            label="Uniflair XRAF4242A EHT high-temperature chiller",
        ))

    # Facility mains: two vertical-plane runs down the length of the plant, one
    # at 37 C out of the chillers, one at 47 C back. Everything taps off these.
    y_lo, y_hi = -1500.0, (CHILLER_COUNT - 1) * CHILLER_PITCH_Y + CHILLER_W + 1500
    seg.append(Segment(
        name="FAC_SUPPLY_MAIN", service="facility_supply", dn=DN_FACILITY_MAIN,
        from_node="chiller_hdr_supply", to_node="cdu_hdr_supply",
        waypoints=route(Point(FACILITY_X_SUPPLY, y_hi, FACILITY_HEADER_Z),
                   Point(FACILITY_X_SUPPLY, y_lo, FACILITY_HEADER_Z)),
    ))
    seg.append(Segment(
        name="FAC_RETURN_MAIN", service="facility_return", dn=DN_FACILITY_MAIN,
        from_node="cdu_hdr_return", to_node="chiller_hdr_return",
        waypoints=route(Point(FACILITY_X_RETURN, y_lo, FACILITY_HEADER_Z),
                   Point(FACILITY_X_RETURN, y_hi, FACILITY_HEADER_Z)),
    ))

    # Chiller connections, each through its own pump. CV01..CV04 in RD110_3.2
    # are the control valves on these circuits, one per chiller.
    for i in range(CHILLER_COUNT):
        cy = i * CHILLER_PITCH_Y + CHILLER_W / 2
        tag = f"CH{i + 1}"
        pump = f"CWP-{i + 1}"
        eq.append(Equipment(
            name=pump, kind="pump",
            origin=Point(PUMP_X, cy - PUMP_D / 2, 0),
            size=(PUMP_W, PUMP_D, PUMP_H),
            label="Chilled water pump, HT circuit",
            reads_branch=f"{pump}_UNIT",
        ))
        seg.append(Segment(
            name=f"{tag}_TO_PUMP", service="facility_supply", dn=DN_CHILLER_BRANCH,
            from_node=f"chiller{i + 1}_out", to_node=f"pump{i + 1}_in",
            waypoints=route(Point(CHILLER_X0 + 500, cy, CHILLER_H),
                       Point(CHILLER_X0 + 500, cy, FACILITY_HEADER_Z),
                       Point(PUMP_X + PUMP_W, cy, FACILITY_HEADER_Z),
                       Point(PUMP_X + PUMP_W, cy, PUMP_H)),
        ))
        seg.append(Segment(
            name=f"{tag}_PUMP_OUT", service="facility_supply", dn=DN_CHILLER_BRANCH,
            from_node=f"pump{i + 1}_out", to_node="chiller_hdr_supply",
            valve=f"CV{i + 1:02d}",
            waypoints=route(Point(PUMP_X, cy, PUMP_H),
                       Point(PUMP_X, cy, FACILITY_HEADER_Z),
                       Point(FACILITY_X_SUPPLY, cy, FACILITY_HEADER_Z)),
        ))
        seg.append(Segment(
            name=f"{tag}_RETURN", service="facility_return", dn=DN_CHILLER_BRANCH,
            from_node="chiller_hdr_return", to_node=f"chiller{i + 1}_in",
            waypoints=route(Point(FACILITY_X_RETURN, cy + 900, FACILITY_HEADER_Z),
                       Point(CHILLER_X0 + 1600, cy + 900, FACILITY_HEADER_Z),
                       Point(CHILLER_X0 + 1600, cy + 900, CHILLER_H)),
        ))

    # --- pods: CDUs, TCS headers, rack drops --------------------------
    for pod in range(POD_COUNT):
        y0 = pod_y0(pod)
        _add_pod(lay, pod, y0)

    return lay


def _add_pod(lay: LoopLayout, pod: int, y0: float) -> None:
    eq, seg = lay.equipment, lay.segments

    row_a_y = y0
    row_b_y = y0 + RACK_D + HOT_AISLE_W
    tcs_supply_y = y0 + RACK_D + HOT_AISLE_W * 0.35
    tcs_return_y = y0 + RACK_D + HOT_AISLE_W * 0.65

    # 16 racks, two rows of eight facing the hot aisle.
    for row, ry in (("A", row_a_y), ("B", row_b_y)):
        for i in range(RACKS_PER_ROW):
            eq.append(Equipment(
                name=f"P{pod + 1}{row}{i + 1:02d}",
                kind="rack",
                origin=Point(RACK_X0 + i * RACK_W, ry, 0),
                size=(RACK_W, RACK_D, RACK_H),
                label="142 kW GB300 NVL72 in NetShelter MGX",
                pod=pod,
            ))

    # Three CDUs per pod, N+1.
    for i in range(CDU_PER_POD):
        eq.append(Equipment(
            name=f"CDU-{pod * CDU_PER_POD + i + 1}",
            kind="cdu",
            origin=Point(CDU_X0 + i * CDU_PITCH_X, y0 + POD_DEPTH / 2 - CDU_D / 2, 0),
            size=(CDU_W, CDU_D, CDU_H),
            label="Motivair MCDU-50 liquid-to-liquid, 1.7 MW",
            pod=pod,
        ))

    # TCS headers: overhead down the hot aisle, 40 C out and 50 C back.
    x_end = RACK_X0 - 600
    x_start = CDU_X0 - 600
    seg.append(Segment(
        name=f"P{pod + 1}_TCS_SUPPLY_HDR", service="tcs_supply", dn=DN_TCS_HEADER,
        from_node=f"pod{pod + 1}_cdu_out", to_node=f"pod{pod + 1}_supply_hdr",
        waypoints=route(Point(x_start, tcs_supply_y, TCS_HEADER_Z),
                   Point(x_end, tcs_supply_y, TCS_HEADER_Z)),
        pod=pod,
    ))
    seg.append(Segment(
        name=f"P{pod + 1}_TCS_RETURN_HDR", service="tcs_return", dn=DN_TCS_HEADER,
        from_node=f"pod{pod + 1}_return_hdr", to_node=f"pod{pod + 1}_cdu_in",
        waypoints=route(Point(x_end, tcs_return_y, TCS_HEADER_Z),
                   Point(x_start, tcs_return_y, TCS_HEADER_Z)),
        pod=pod,
    ))

    # CDU tie-ins, both sides. The facility side is where each pod taps the
    # 37/47 C mains; the secondary side is the pod's own 40/50 C loop.
    for i in range(CDU_PER_POD):
        n = pod * CDU_PER_POD + i + 1
        cx = CDU_X0 + i * CDU_PITCH_X + CDU_W / 2
        cy = y0 + POD_DEPTH / 2
        seg.append(Segment(
            name=f"CDU{n}_FAC_IN", service="facility_supply", dn=DN_CDU_TIE,
            meter=f"FM-F{n:02d}",
            from_node="cdu_hdr_supply", to_node=f"cdu{n}_fac_in",
            waypoints=route(Point(FACILITY_X_SUPPLY, cy - 200, FACILITY_HEADER_Z),
                       Point(cx - 200, cy - 200, FACILITY_HEADER_Z),
                       Point(cx - 200, cy - 200, CDU_H)),
            pod=pod,
        ))
        seg.append(Segment(
            name=f"CDU{n}_FAC_OUT", service="facility_return", dn=DN_CDU_TIE,
            from_node=f"cdu{n}_fac_out", to_node="cdu_hdr_return",
            waypoints=route(Point(cx + 200, cy + 200, CDU_H),
                       Point(cx + 200, cy + 200, FACILITY_HEADER_Z),
                       Point(FACILITY_X_RETURN, cy + 200, FACILITY_HEADER_Z)),
            pod=pod,
        ))
        seg.append(Segment(
            name=f"CDU{n}_TCS_OUT", service="tcs_supply", dn=DN_CDU_TIE,
            meter=f"FM-T{n:02d}",
            from_node=f"cdu{n}_tcs_out", to_node=f"pod{pod + 1}_cdu_out",
            waypoints=route(Point(cx, cy - 300, CDU_H),
                       Point(cx, cy - 300, TCS_HEADER_Z),
                       Point(x_start, cy - 300, TCS_HEADER_Z),
                       Point(x_start, tcs_supply_y, TCS_HEADER_Z)),
            pod=pod,
        ))
        seg.append(Segment(
            name=f"CDU{n}_TCS_IN", service="tcs_return", dn=DN_CDU_TIE,
            from_node=f"pod{pod + 1}_cdu_in", to_node=f"cdu{n}_tcs_in",
            waypoints=route(Point(x_start, tcs_return_y, TCS_HEADER_Z),
                       Point(x_start, cy + 300, TCS_HEADER_Z),
                       Point(cx, cy + 300, TCS_HEADER_Z),
                       Point(cx, cy + 300, CDU_H)),
            pod=pod,
        ))

    # Rack drops. One pair per rack, and the supply drop carries the rack's
    # control valve - RD110's PCV01..PCV48, in rack order.
    for row, ry, y_face in (("A", row_a_y, row_a_y + RACK_D), ("B", row_b_y, row_b_y)):
        for i in range(RACKS_PER_ROW):
            rack = f"P{pod + 1}{row}{i + 1:02d}"
            pcv = _pcv_tag(pod, row, i)
            x = RACK_X0 + i * RACK_W + RACK_W / 2
            sx, rx = x - 120, x + 120
            seg.append(Segment(
                name=f"{rack}_DROP_S", service="tcs_supply", dn=DN_RACK_DROP,
                from_node=f"pod{pod + 1}_supply_hdr", to_node=f"{rack}_in",
                valve=pcv, pod=pod,
                waypoints=route(Point(sx, tcs_supply_y, TCS_HEADER_Z),
                           Point(sx, y_face, TCS_HEADER_Z),
                           Point(sx, y_face, RACK_TOP_Z)),
            ))
            seg.append(Segment(
                name=f"{rack}_DROP_R", service="tcs_return", dn=DN_RACK_DROP,
                from_node=f"{rack}_out", to_node=f"pod{pod + 1}_return_hdr",
                pod=pod,
                waypoints=route(Point(rx, y_face, RACK_TOP_Z),
                           Point(rx, y_face, TCS_HEADER_Z),
                           Point(rx, tcs_return_y, TCS_HEADER_Z)),
            ))


def _pcv_tag(pod: int, row: str, i: int) -> str:
    """PCV01..PCV48 in rack order, matching RD110_3.2's 48 control valves."""
    n = pod * 2 * RACKS_PER_ROW + (0 if row == "A" else RACKS_PER_ROW) + i + 1
    return f"PCV{n:02d}"


def summary(lay: LoopLayout) -> str:
    lo, hi = lay.bounds()
    counts = {k: len(lay.by_kind(k)) for k in ("chiller", "pump", "cdu", "rack")}
    lines = [
        f"{lay.name}: {counts['chiller']} chillers, {counts['pump']} pumps, "
        f"{counts['cdu']} CDUs, {counts['rack']} racks",
        f"  {len(lay.segments)} pipe segments, {lay.total_pipe_m():.1f} m total, "
        f"{sum(s.elbows() for s in lay.segments)} elbows",
        f"  valves: {len([s for s in lay.segments if s.valve])}, "
        f"flow meters: {len([s for s in lay.segments if s.meter])}",
        f"  extent: {(hi.x - lo.x) / 1000:.1f} x {(hi.y - lo.y) / 1000:.1f} x "
        f"{(hi.z - lo.z) / 1000:.1f} m",
    ]
    for svc in SERVICES:
        segs = lay.by_service(svc)
        lines.append(
            f"  {svc:16s} {len(segs):3d} segments, "
            f"{sum(s.length_mm() for s in segs) / 1000:7.1f} m @ "
            f"{SERVICES[svc]['design_c']:.0f} C"
        )
    return "\n".join(lines)
