"""
Parametric Piping System for FreeCAD.

Rules:
- All pipe segments have two connection points (start, end)
- Each connection point has a position (Vector) and direction (Vector, outward-facing)
- Two segments connect when their connection points are coincident and directions are opposite
- Straight sections: cylinder along a direction vector
- Elbows: toroidal arc between two directions at a fixed bend radius
- The bend radius is a function of pipe diameter (typically 1.5D for long-radius elbows)

Coordinate convention:
- Positions in mm
- Directions are unit vectors pointing OUT from the connection face
- When two pieces connect: point_A.pos == point_B.pos AND point_A.dir == -point_B.dir
"""

import FreeCAD
import Part
import math
from dataclasses import dataclass
from typing import Optional


# =============================================================================
# CORE DATA TYPES
# =============================================================================

@dataclass
class ConnectionPoint:
    """A pipe connection point (flange face)."""
    pos: FreeCAD.Vector
    direction: FreeCAD.Vector  # unit vector pointing OUT from the face

    def matches(self, other: 'ConnectionPoint', tolerance: float = 1.0) -> bool:
        """Check if this connection point mates with another."""
        pos_match = (self.pos - other.pos).Length < tolerance
        dir_match = (self.direction + other.direction).Length < tolerance  # opposite dirs
        return pos_match and dir_match


@dataclass
class PipeSpec:
    """Pipe specification."""
    od: float           # outer diameter mm
    wall: float         # wall thickness mm
    bend_radius: float  # centerline bend radius for elbows (typically 1.5 * od)
    material: str = "carbon_steel"
    schedule: str = "10S"

    @property
    def id(self) -> float:
        """Inner diameter."""
        return self.od - 2 * self.wall

    @classmethod
    def from_dn(cls, dn: int, schedule: str = "10S") -> 'PipeSpec':
        """Create spec from nominal diameter (DN in mm)."""
        # Common pipe sizes (DN -> OD mm, wall for Sch 10S)
        table = {
            25:  (33.7,   2.77),
            32:  (42.4,   2.77),
            40:  (48.3,   2.77),
            50:  (60.3,   2.77),
            65:  (76.1,   2.77),
            80:  (88.9,   3.05),
            100: (114.3,  3.05),
            125: (139.7,  3.40),
            150: (168.3,  3.40),
            200: (219.1,  3.76),
            250: (273.0,  4.19),
            300: (323.9,  4.57),
            350: (355.6,  4.78),
            400: (406.4,  4.78),
            450: (457.2,  4.78),
            500: (508.0,  5.54),
            600: (609.6,  5.54),
        }
        if dn not in table:
            raise ValueError(f"DN{dn} not in table. Available: {list(table.keys())}")
        od, wall = table[dn]
        bend_radius = 1.5 * od  # long-radius elbow
        return cls(od=od, wall=wall, bend_radius=bend_radius, schedule=schedule)


# =============================================================================
# PIPE SEGMENTS
# =============================================================================

class PipeSegment:
    """Base class for pipe segments."""

    def __init__(self, spec: PipeSpec):
        self.spec = spec
        self.start: Optional[ConnectionPoint] = None
        self.end: Optional[ConnectionPoint] = None
        self.shape: Optional[Part.Shape] = None

    def get_connections(self) -> tuple:
        return (self.start, self.end)


class StraightPipe(PipeSegment):
    """A straight pipe section."""

    def __init__(self, spec: PipeSpec, start_pos: FreeCAD.Vector,
                 direction: FreeCAD.Vector, length: float):
        super().__init__(spec)
        self.length = length

        direction = direction.normalize()
        end_pos = start_pos + direction * length

        # Connection points: direction faces OUTWARD from each end
        self.start = ConnectionPoint(pos=start_pos, direction=-direction)
        self.end = ConnectionPoint(pos=end_pos, direction=direction)

        # Create geometry - hollow cylinder
        self._build_shape(start_pos, direction)

    def _build_shape(self, start_pos, direction):
        """Build the 3D shape."""
        outer = Part.makeCylinder(
            self.spec.od / 2, self.length, start_pos, direction
        )
        inner = Part.makeCylinder(
            self.spec.id / 2, self.length, start_pos, direction
        )
        self.shape = outer.cut(inner)


class Elbow(PipeSegment):
    """A pipe elbow (bend)."""

    def __init__(self, spec: PipeSpec, center: FreeCAD.Vector,
                 start_dir: FreeCAD.Vector, end_dir: FreeCAD.Vector,
                 bend_radius: Optional[float] = None):
        """
        Create an elbow.

        Args:
            spec: Pipe specification
            center: Center point of the bend arc
            start_dir: Direction the pipe is coming FROM (into the elbow) - points away from elbow
            end_dir: Direction the pipe is going TO (out of the elbow) - points away from elbow
            bend_radius: Override bend radius (defaults to spec.bend_radius)

        Geometry:
            For a circular arc with center C and radius R:
            - At any point P on the arc, the tangent T is perpendicular to (P - C)
            - The radius vector (P - C) has length R
            - So: P = C + R * unit_vector_perpendicular_to_T

            For the start connection:
            - Flow direction INTO the elbow is (-start_dir)
            - Tangent at start point is (-start_dir)
            - (start_pos - center) must be ⊥ to (-start_dir)
            - |start_pos - center| = R
            - start_pos = center + R * n  where n ⊥ (-start_dir), |n|=1

            For the end connection:
            - Flow direction OUT of elbow is end_dir
            - Tangent at end point is end_dir
            - (end_pos - center) must be ⊥ to end_dir
            - end_pos = center + R * m  where m ⊥ end_dir, |m|=1
        """
        super().__init__(spec)
        self.bend_radius = bend_radius or spec.bend_radius

        start_dir = start_dir.normalize()
        end_dir = end_dir.normalize()

        # Flow directions
        flow_in = -start_dir    # direction of flow entering the elbow
        flow_out = end_dir      # direction of flow leaving the elbow

        # Bend angle (between flow directions)
        cos_angle = max(-1.0, min(1.0, flow_in.dot(flow_out)))
        self.angle = math.acos(cos_angle)

        # Bend plane normal (right-hand rule: flow_in × flow_out)
        self.normal = flow_in.cross(flow_out)
        if self.normal.Length < 1e-6:
            raise ValueError("Directions are parallel - no elbow needed")
        self.normal.normalize()

        # Start point on the arc:
        # (start_pos - center) must be perpendicular to flow_in (tangent condition)
        # and point AWAY from center (toward the pipe).
        # The direction from center to start is: -cross(normal, flow_in)
        # (rotate flow_in by -90° in the bend plane to get the radial direction)
        radial_start = flow_in.cross(self.normal)
        radial_start.normalize()
        start_pos = center + radial_start * self.bend_radius

        # End point on the arc:
        # (end_pos - center) must be perpendicular to flow_out
        radial_end = flow_out.cross(self.normal)
        radial_end.normalize()
        end_pos = center + radial_end * self.bend_radius

        # Connection points (direction points AWAY from the elbow = out of the face)
        self.start = ConnectionPoint(pos=start_pos, direction=start_dir)
        self.end = ConnectionPoint(pos=end_pos, direction=end_dir)

        self._build_shape(center, start_dir, end_dir)

    def _build_shape(self, center, start_dir, end_dir):
        """Build the toroidal arc shape."""
        # Use the connection points already calculated
        arc_start = self.start.pos
        arc_end = self.end.pos

        # Mid-point of the arc: average of the two radius vectors, normalized to br
        vec_start = arc_start - center
        vec_end = arc_end - center
        mid_vec = (vec_start + vec_end)
        if mid_vec.Length > 1e-6:
            mid_vec.normalize()
            arc_mid = center + mid_vec * self.bend_radius
        else:
            # 180° bend (unusual) - use normal to find midpoint
            arc_mid = center + self.normal.cross(vec_start).normalize() * self.bend_radius

        # Create arc path
        arc = Part.Arc(arc_start, arc_mid, arc_end)
        arc_edge = arc.toShape()
        path_wire = Part.Wire(arc_edge)

        # Profile at start (circle perpendicular to incoming pipe direction)
        # The pipe direction at start is (-start_dir) = the direction of flow
        pipe_dir_at_start = -start_dir
        profile = Part.makeCircle(self.spec.od / 2, arc_start, pipe_dir_at_start)
        profile_wire = Part.Wire(profile)

        # Sweep outer profile along arc
        try:
            outer_sweep = path_wire.makePipeShell([profile_wire], True, True)
        except Exception:
            # Fallback: use makePipe
            outer_sweep = Part.Wire(profile).makePipe(path_wire)

        # Inner profile for hollow pipe
        inner_profile = Part.makeCircle(self.spec.id / 2, arc_start, pipe_dir_at_start)
        inner_wire = Part.Wire(inner_profile)

        try:
            inner_sweep = path_wire.makePipeShell([inner_wire], True, True)
            self.shape = outer_sweep.cut(inner_sweep)
        except Exception:
            # If boolean fails, just use the solid sweep
            self.shape = outer_sweep


# =============================================================================
# PIPE ROUTE - chains segments together
# =============================================================================

class PipeRoute:
    """A connected chain of pipe segments forming a complete route."""

    def __init__(self, spec: PipeSpec, name: str = "PipeRoute"):
        self.spec = spec
        self.name = name
        self.segments: list = []
        self._current_pos: Optional[FreeCAD.Vector] = None
        self._current_dir: Optional[FreeCAD.Vector] = None

    def start_at(self, pos: FreeCAD.Vector, direction: FreeCAD.Vector) -> 'PipeRoute':
        """Set the starting point and direction."""
        self._current_pos = pos
        self._current_dir = direction.normalize()
        return self

    def straight(self, length: float) -> 'PipeRoute':
        """Add a straight section of given length."""
        if self._current_pos is None:
            raise ValueError("Must call start_at() first")
        if length < 1.0:
            return self  # skip degenerate segments

        seg = StraightPipe(self.spec, self._current_pos, self._current_dir, length)
        self.segments.append(seg)

        # Advance position
        self._current_pos = seg.end.pos
        # Direction stays the same (straight)
        return self

    def elbow(self, new_direction: FreeCAD.Vector, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """Add an elbow to change direction."""
        if self._current_pos is None:
            raise ValueError("Must call start_at() first")

        new_direction = new_direction.normalize()
        br = bend_radius or self.spec.bend_radius

        # The flow arrives at current_pos along current_dir.
        # In the Elbow class, the radial_start direction is:
        #   radial_start = flow_in.cross(normal)
        # where flow_in = current_dir (= -start_dir since start_dir = -current_dir)
        # and normal = flow_in.cross(flow_out) = current_dir.cross(new_direction)
        #
        # The center is at: current_pos - radial_start * br
        # (center is on the opposite side of the radial from the connection point)
        #
        # Let's compute it directly:
        flow_in = self._current_dir
        flow_out = new_direction

        normal = flow_in.cross(flow_out)
        if normal.Length < 1e-6:
            raise ValueError("Cannot create elbow: directions are parallel")
        normal.normalize()

        # Radial direction from center toward the start connection point
        radial_start = flow_in.cross(normal)
        radial_start.normalize()

        # Center = start_pos - radial_start * br
        center = self._current_pos - radial_start * br

        # Create the elbow
        # start_dir points AWAY from the elbow (out of the connection face) = -current_dir
        seg = Elbow(self.spec, center, -self._current_dir, new_direction, br)
        self.segments.append(seg)

        # Advance position and direction
        self._current_pos = seg.end.pos
        self._current_dir = new_direction
        return self

    def elbow_up(self, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """Shortcut: bend upward (+Z)."""
        return self.elbow(FreeCAD.Vector(0, 0, 1), bend_radius)

    def elbow_down(self, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """Shortcut: bend downward (-Z)."""
        return self.elbow(FreeCAD.Vector(0, 0, -1), bend_radius)

    def elbow_left(self, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """Shortcut: bend left (rotate 90° around Z from current XY direction)."""
        # Rotate current direction 90° around Z
        new_dir = FreeCAD.Vector(-self._current_dir.y, self._current_dir.x, 0)
        return self.elbow(new_dir, bend_radius)

    def elbow_right(self, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """Shortcut: bend right (rotate -90° around Z from current XY direction)."""
        new_dir = FreeCAD.Vector(self._current_dir.y, -self._current_dir.x, 0)
        return self.elbow(new_dir, bend_radius)

    def to_point(self, target: FreeCAD.Vector, bend_radius: Optional[float] = None) -> 'PipeRoute':
        """
        Route to a target point using at most 2 elbows (L-shaped or Z-shaped path).
        Uses Manhattan-style routing: go straight, elbow, go straight, elbow, go straight.
        """
        br = bend_radius or self.spec.bend_radius
        delta = target - self._current_pos

        # Project delta onto current direction to find the "forward" component
        forward = delta.dot(self._current_dir)

        # Lateral component (perpendicular to current direction)
        lateral_vec = delta - self._current_dir * forward

        if lateral_vec.Length < 1.0:
            # Target is directly ahead - just go straight
            self.straight(forward)
            return self

        lateral_dir = lateral_vec.normalize()
        lateral_dist = lateral_vec.Length

        # Route: straight (forward - br), elbow to lateral, straight (lateral - 2*br),
        # This is a simple L-route for now
        if forward > br:
            self.straight(forward - br)
        self.elbow(lateral_dir, br)
        if lateral_dist > 2 * br:
            self.straight(lateral_dist - 2 * br)

        return self

    def build(self, doc) -> list:
        """Build all segments as FreeCAD objects in the given document."""
        objects = []
        for i, seg in enumerate(self.segments):
            if seg.shape is None:
                continue
            type_name = "Str" if isinstance(seg, StraightPipe) else "Elb"
            obj_name = f"{self.name}_{type_name}_{i+1:03d}"
            obj = doc.addObject("Part::Feature", obj_name)
            obj.Shape = seg.shape
            objects.append(obj)
        doc.recompute()
        return objects

    def get_total_length(self) -> float:
        """Calculate total pipe length (centerline)."""
        total = 0
        for seg in self.segments:
            if isinstance(seg, StraightPipe):
                total += seg.length
            elif isinstance(seg, Elbow):
                total += seg.angle * seg.bend_radius
        return total

    def validate(self) -> list:
        """Check that all connections mate properly."""
        issues = []
        for i in range(len(self.segments) - 1):
            end = self.segments[i].end
            start = self.segments[i + 1].start
            if not end.matches(start):
                gap = (end.pos - start.pos).Length
                issues.append(f"Gap at joint {i+1}: {gap:.1f}mm")
        return issues


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def create_pipe_run(doc, name: str, dn: int, waypoints: list,
                    start_dir: FreeCAD.Vector = None) -> PipeRoute:
    """
    Create a pipe run through a series of waypoints.
    Automatically inserts elbows at direction changes.

    Args:
        doc: FreeCAD document
        name: Name prefix for objects
        dn: Nominal diameter (DN25, DN50, etc.)
        waypoints: List of FreeCAD.Vector points
        start_dir: Initial direction (auto-calculated if None)

    Returns:
        PipeRoute with all segments built
    """
    spec = PipeSpec.from_dn(dn)
    route = PipeRoute(spec, name)

    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")

    # Calculate initial direction from first two points
    if start_dir is None:
        start_dir = (waypoints[1] - waypoints[0]).normalize()

    route.start_at(waypoints[0], start_dir)

    for i in range(1, len(waypoints)):
        target = waypoints[i]
        delta = target - route._current_pos

        if delta.Length < 1.0:
            continue  # skip duplicate points

        new_dir = delta.normalize()

        # Check if direction change is needed
        angle_diff = math.acos(max(-1, min(1, route._current_dir.dot(new_dir))))

        if angle_diff < 0.01:
            # Same direction - just go straight
            route.straight(delta.Length)
        else:
            # Need an elbow then straight
            route.elbow(new_dir)
            # Calculate remaining straight distance after elbow
            remaining = target - route._current_pos
            straight_len = remaining.dot(new_dir)
            if straight_len > 1.0:
                route.straight(straight_len)

    route.build(doc)
    return route


# =============================================================================
# AUTO-ROUTE: Point-to-point routing with strategy
# =============================================================================

def auto_route(start: 'FreeCAD.Vector', start_dir: 'FreeCAD.Vector',
               end: 'FreeCAD.Vector', end_dir: 'FreeCAD.Vector',
               dn: int, routing: str = "overhead", header_height: float = 2500,
               name: str = "AutoRoute") -> PipeRoute:
    """
    Automatically route a pipe between two connection points.

    The pipe exits 'start' in direction 'start_dir' and must arrive at 'end'
    such that the final flow direction equals (-end_dir). (end_dir points OUT
    of the receiving equipment, so flow arrives in the -end_dir direction.)

    Routing strategies:
      - "overhead": rise to header_height, run horizontally, drop to target
      - "direct": Manhattan path with fewest elbows (no forced height)
      - "ring": route around a rectangular perimeter (for ring mains)

    Args:
        start: Starting connection point position
        start_dir: Direction pipe exits (unit vector, away from equipment)
        end: Target connection point position
        end_dir: Direction pointing OUT of the target nozzle face
                 (pipe flow arrives in -end_dir direction)
        dn: Nominal pipe diameter
        routing: Strategy ("overhead", "direct")
        header_height: Preferred Z for horizontal runs (mm)
        name: Name prefix for FreeCAD objects

    Returns:
        PipeRoute (not yet built — call .build(doc) yourself)
    """
    spec = PipeSpec.from_dn(dn)
    route = PipeRoute(spec, name)
    br = spec.bend_radius

    start_dir = start_dir.normalize()
    end_dir = end_dir.normalize()

    # The flow must arrive at 'end' going in direction (-end_dir)
    arrival_dir = -end_dir

    route.start_at(start, start_dir)

    if routing == "overhead":
        _route_overhead(route, start, start_dir, end, arrival_dir, header_height, br)
    elif routing == "direct":
        _route_direct(route, start, start_dir, end, arrival_dir, br)
    else:
        _route_direct(route, start, start_dir, end, arrival_dir, br)

    return route


def _route_overhead(route: PipeRoute, start, start_dir, end, arrival_dir, header_height, br):
    """
    Overhead routing: rise to header height, run horizontally, drop to target.

    Strategy: plan the route in 5 segments working from both ends toward the middle:
      1. Start riser: from start, going start_dir, elbow up, rise to header_height
      2. Start elbow: turn from vertical to horizontal (toward target)
      3. Horizontal run: at header_height, covering the XY distance
      4. End elbow: turn from horizontal to vertical (going down)
      5. End drop: descend to target height, final elbow to match arrival_dir

    The key is computing the horizontal run length exactly so the drop lands on target.
    """
    min_straight = 2.0 * br

    # --- PHASE 1: Get from start to header height, going up ---
    if abs(start_dir.z) > 0.9 and start_dir.z > 0:
        # Already going up — just rise
        rise = header_height - route._current_pos.z - br  # leave room for elbow
        if rise > 1.0:
            route.straight(rise)
    elif abs(start_dir.z) > 0.9 and start_dir.z < 0:
        # Going down — short straight then U-turn up
        route.straight(min_straight)
        lateral = FreeCAD.Vector(1, 0, 0)
        if abs(end.x - start.x) < abs(end.y - start.y):
            lateral = FreeCAD.Vector(0, 1 if end.y > start.y else -1, 0)
        route.elbow(lateral)
        route.straight(min_straight)
        route.elbow(FreeCAD.Vector(0, 0, 1))
        rise = header_height - route._current_pos.z - br
        if rise > 1.0:
            route.straight(rise)
    else:
        # Horizontal start — straight to clear equipment, then elbow up
        route.straight(min_straight)
        route.elbow(FreeCAD.Vector(0, 0, 1))
        rise = header_height - route._current_pos.z - br
        if rise > 1.0:
            route.straight(rise)

    # --- PHASE 2: Turn to horizontal, aimed at the target XY position ---
    # Recalculate XY distance from CURRENT position (after Phase 1)
    current_xy = FreeCAD.Vector(route._current_pos.x, route._current_pos.y, 0)
    target_xy = FreeCAD.Vector(end.x, end.y, 0)
    delta_xy = target_xy - current_xy

    if delta_xy.Length > 2 * br:
        horiz_dir = delta_xy.normalize()

        # Elbow from vertical to horizontal (only if currently going vertical)
        if abs(route._current_dir.z) > 0.9:
            route.elbow(horiz_dir)

        # --- PHASE 3: Horizontal run ---
        # Recalculate after elbow (position changed due to bend offset)
        current_xy = FreeCAD.Vector(route._current_pos.x, route._current_pos.y, 0)
        remaining_xy = (target_xy - current_xy).Length
        # Stop short by br for the down-elbow's tangent offset
        run_length = remaining_xy - br
        if run_length > 1.0:
            route.straight(run_length)
    else:
        # Target is almost directly below — just elbow down
        if abs(route._current_dir.z) > 0.9:
            horiz_dir = FreeCAD.Vector(1, 0, 0) if delta_xy.Length < 1.0 else delta_xy.normalize()
            route.elbow(horiz_dir)
            route.straight(min_straight)

    # --- PHASE 4: Drop to target height ---
    if abs(route._current_dir.z) < 0.1:  # currently horizontal
        route.elbow(FreeCAD.Vector(0, 0, -1))

    # Calculate how far to drop
    drop = route._current_pos.z - end.z
    if abs(arrival_dir.z) > 0.9:
        # Arriving vertically — just drop all the way
        if drop > 1.0:
            route.straight(drop)
    else:
        # Arriving horizontally — drop to target height + br (room for final elbow)
        drop_to = drop - br
        if drop_to > 1.0:
            route.straight(drop_to)

        # --- PHASE 5: Final elbow to match arrival direction ---
        if route._current_dir.dot(arrival_dir) < 0.99:
            try:
                route.elbow(arrival_dir)
            except ValueError:
                pass

        # Final straight to reach end point
        remaining = end - route._current_pos
        dist = remaining.dot(arrival_dir)
        if dist > 1.0:
            route.straight(dist)


def _route_direct(route: PipeRoute, start, start_dir, end, arrival_dir, br):
    """
    Direct Manhattan routing: decompose into axis-aligned segments.
    Uses fewest elbows possible.
    """
    min_straight = 2.5 * br

    # Go straight in start_dir to clear equipment
    route.straight(min_straight)

    # Calculate remaining delta
    delta = end - route._current_pos

    # Decompose into components along each axis
    # Priority: match horizontal first, then vertical
    components = []
    if abs(delta.x) > br:
        components.append(('x', delta.x, FreeCAD.Vector(1 if delta.x > 0 else -1, 0, 0)))
    if abs(delta.y) > br:
        components.append(('y', delta.y, FreeCAD.Vector(0, 1 if delta.y > 0 else -1, 0)))
    if abs(delta.z) > br:
        components.append(('z', delta.z, FreeCAD.Vector(0, 0, 1 if delta.z > 0 else -1)))

    for axis, dist, direction in components:
        # Skip if already going this direction
        if route._current_dir.dot(direction) > 0.99:
            route.straight(abs(dist))
        elif route._current_dir.dot(direction) < -0.99:
            # Going opposite — need two elbows (U-turn)
            perp = FreeCAD.Vector(0, 0, 1) if abs(direction.z) < 0.5 else FreeCAD.Vector(1, 0, 0)
            try:
                route.elbow(perp)
                route.straight(min_straight)
                route.elbow(direction)
                remaining = abs(dist) - min_straight
                if remaining > 1.0:
                    route.straight(remaining)
            except ValueError:
                pass
        else:
            # 90° change
            try:
                route.elbow(direction)
                remaining = abs(dist) - br
                if remaining > 1.0:
                    route.straight(remaining)
            except ValueError:
                pass

    # Final approach to match arrival direction
    if route._current_dir.dot(arrival_dir) < 0.99:
        try:
            route.elbow(arrival_dir)
            remaining = end - route._current_pos
            dist = remaining.dot(arrival_dir)
            if dist > 1.0:
                route.straight(dist)
        except ValueError:
            pass


def auto_route_loop(source_out: tuple, source_in: tuple,
                    loads: list, dn_header: int, dn_branch: int,
                    supply_height: float = 2800, return_height: float = 2400,
                    name: str = "Loop") -> dict:
    """
    Route a complete closed loop: source → header → N loads → return header → source.

    Args:
        source_out: (Vector pos, Vector dir) — source equipment outlet
        source_in: (Vector pos, Vector dir) — source equipment inlet
        loads: list of dicts with "supply": (pos, dir) and "return": (pos, dir)
        dn_header: Header pipe size
        dn_branch: Branch pipe size
        supply_height: Z height for supply header
        return_height: Z height for return header
        name: Name prefix

    Returns:
        dict with keys: "supply_header", "return_header", "supply_branches",
        "return_branches", "supply_riser", "return_riser" — each a PipeRoute
    """
    routes = {}

    # Sort loads by position for clean header routing
    loads_sorted = sorted(loads, key=lambda l: l["supply"][0].y)

    # Supply riser: source outlet → up to supply header height
    routes["supply_riser"] = auto_route(
        start=source_out[0], start_dir=source_out[1],
        end=FreeCAD.Vector(source_out[0].x, source_out[0].y, supply_height),
        end_dir=FreeCAD.Vector(0, 0, 1),
        dn=dn_header, routing="direct", name=f"{name}_SupplyRiser"
    )

    # Supply header: runs at supply_height across all loads
    first_load_y = loads_sorted[0]["supply"][0].y
    last_load_y = loads_sorted[-1]["supply"][0].y
    header_x = loads_sorted[0]["supply"][0].x  # assume loads aligned in X

    supply_header_start = FreeCAD.Vector(source_out[0].x, source_out[0].y, supply_height)
    supply_header_end = FreeCAD.Vector(header_x, last_load_y + 500, supply_height)

    routes["supply_header"] = auto_route(
        start=supply_header_start, start_dir=FreeCAD.Vector(1, 0, 0),
        end=supply_header_end, end_dir=FreeCAD.Vector(1, 0, 0),
        dn=dn_header, routing="direct", name=f"{name}_SupplyHeader"
    )

    # Supply branches: header → each load
    routes["supply_branches"] = []
    for i, load in enumerate(loads_sorted):
        load_pos, load_dir = load["supply"]
        branch_start = FreeCAD.Vector(header_x, load_pos.y, supply_height)
        branch = auto_route(
            start=branch_start, start_dir=FreeCAD.Vector(0, 0, -1),
            end=load_pos, end_dir=load_dir,
            dn=dn_branch, routing="direct", name=f"{name}_SupplyBranch_{i+1}"
        )
        routes["supply_branches"].append(branch)

    # Return branches: each load → return header height
    routes["return_branches"] = []
    for i, load in enumerate(loads_sorted):
        load_pos, load_dir = load["return"]
        branch_end = FreeCAD.Vector(load_pos.x, load_pos.y, return_height)
        branch = auto_route(
            start=load_pos, start_dir=load_dir,
            end=branch_end, end_dir=FreeCAD.Vector(0, 0, 1),
            dn=dn_branch, routing="direct", name=f"{name}_ReturnBranch_{i+1}"
        )
        routes["return_branches"].append(branch)

    # Return header: collects from loads back toward source
    return_header_start = FreeCAD.Vector(header_x, last_load_y + 500, return_height)
    return_header_end = FreeCAD.Vector(source_in[0].x, source_in[0].y, return_height)

    routes["return_header"] = auto_route(
        start=return_header_start, start_dir=FreeCAD.Vector(-1, 0, 0),
        end=return_header_end, end_dir=FreeCAD.Vector(-1, 0, 0),
        dn=dn_header, routing="direct", name=f"{name}_ReturnHeader"
    )

    # Return riser: return header → source inlet
    routes["return_riser"] = auto_route(
        start=FreeCAD.Vector(source_in[0].x, source_in[0].y, return_height),
        start_dir=FreeCAD.Vector(0, 0, -1),
        end=source_in[0], end_dir=source_in[1],
        dn=dn_header, routing="direct", name=f"{name}_ReturnRiser"
    )

    return routes
