"""
Orthogonal Pipe Route Engine.

Routes pipes between equipment nozzles using only 90-degree elbows.
Handles obstacles by routing around or over them.

Key principles:
- Only 90° elbows (orthogonal grid-aligned movement)
- Every pipe part chains: part[i].exit_pos == part[i+1].entry_pos (zero gap)
- Elbow geometry: center = entry_pos + turn_dir * BEND_R
                  exit_pos = center + entry_dir * BEND_R
- Each elbow consumes BEND_R along both entry and exit directions
- MINIMUM SEGMENT LENGTH CONSTRAINT:
    Interior segments (elbow on both ends): length > 2 * BEND_R
    First/last segments (elbow on one end): length > 1 * BEND_R
  Violating this means the elbows overlap and the pipe can't be built.

Usage:
    engine = RouteEngine(od=114.3, bend_radius=171.5)
    engine.add_obstacle(min_pt, max_pt)
    parts = engine.route(start_pos, start_dir, end_pos, arrive_dir)
    # parts is a list of dicts with shape, entry_pos, exit_pos, etc.

Waypoint usage (simpler API):
    waypoints = [start, corner1, corner2, ..., end]
    parts = engine.waypoints_to_pipe(waypoints, doc, "PipeName")
    # All segments must be orthogonal (move on exactly one axis)
    # All segments must meet minimum length constraint
"""

import FreeCAD
import Part
import heapq


class RouteEngine:
    """Grid-based orthogonal pipe router with obstacle avoidance."""

    def __init__(self, od=114.3, bend_radius=171.5, grid_size=200):
        self.od = od
        self.bend_radius = bend_radius
        self.grid_size = grid_size
        self.obstacles = []  # list of (min_vec, max_vec) bounding boxes

    def add_obstacle(self, min_pt, max_pt, padding=100):
        """Add an axis-aligned bounding box obstacle with padding."""
        if isinstance(min_pt, (list, tuple)):
            min_pt = FreeCAD.Vector(*min_pt)
        if isinstance(max_pt, (list, tuple)):
            max_pt = FreeCAD.Vector(*max_pt)
        padded_min = min_pt - FreeCAD.Vector(padding, padding, padding)
        padded_max = max_pt + FreeCAD.Vector(padding, padding, padding)
        self.obstacles.append((padded_min, padded_max))

    def _is_blocked(self, point):
        """Check if a point is inside any obstacle."""
        for mn, mx in self.obstacles:
            if (mn.x <= point.x <= mx.x and
                mn.y <= point.y <= mx.y and
                mn.z <= point.z <= mx.z):
                return True
        return False

    def _segment_blocked(self, p1, p2):
        """Check if a straight segment passes through any obstacle."""
        # Sample along segment
        length = (p2 - p1).Length
        steps = max(2, int(length / (self.grid_size / 2)))
        for i in range(steps + 1):
            t = i / steps
            pt = p1 + (p2 - p1) * t
            if self._is_blocked(pt):
                return True
        return False

    def route(self, start_pos, start_dir, end_pos, arrive_dir):
        """
        Find a route from start to end using only 90° turns.

        Args:
            start_pos: FreeCAD.Vector - pipe start position (at nozzle face)
            start_dir: FreeCAD.Vector - initial flow direction (away from equipment)
            end_pos: FreeCAD.Vector - pipe end position (at destination nozzle)
            arrive_dir: FreeCAD.Vector - direction pipe is traveling when it arrives

        Returns:
            List of part dicts with 'type', 'entry_pos', 'exit_pos', 'entry_dir',
            'exit_dir', 'shape', or None if no route found.
        """
        start_dir = FreeCAD.Vector(start_dir).normalize()
        arrive_dir = FreeCAD.Vector(arrive_dir).normalize()

        # Try direct route first (no obstacles in the way)
        plan = self._plan_route(start_pos, start_dir, end_pos, arrive_dir)
        if plan and not self._plan_blocked(plan, start_pos, start_dir):
            return self._plan_to_parts(plan, start_pos, start_dir)

        # If blocked, use A* grid search then convert to pipe parts
        waypoints = self._astar_route(start_pos, start_dir, end_pos, arrive_dir)
        if waypoints:
            return self._waypoints_to_parts(waypoints, start_dir, arrive_dir)

        return None

    def _plan_route(self, start_pos, start_dir, end_pos, arrive_dir):
        """
        Plan a direct route (no obstacles considered).
        Returns list of ('straight', length) or ('elbow', turn_dir) steps.
        """
        delta = end_pos - start_pos
        sx = FreeCAD.Vector(start_dir).normalize()
        ax = FreeCAD.Vector(arrive_dir).normalize()
        br = self.bend_radius

        # Case 1: Same direction, offset on one cross-axis → Z-shape (2 elbows)
        if abs(sx.dot(ax) - 1.0) < 0.01:
            cross_offset = delta - sx * delta.dot(sx)
            if cross_offset.Length < 0.5:
                # Perfectly aligned - single straight
                length = delta.dot(sx)
                if length > 0:
                    return [('straight', length)]
                return None

            cross_dir = FreeCAD.Vector(cross_offset).normalize()
            cross_dist = cross_offset.Length
            total_along = delta.dot(sx)

            cross_straight = cross_dist - 2 * br
            remaining_along = total_along - 2 * br

            if cross_straight < 10 or remaining_along < 10:
                return None

            # Place turn at 1/3 of the way along
            first_straight = max(200, remaining_along / 3)
            last_straight = remaining_along - first_straight

            if first_straight < 50 or last_straight < 50:
                return None

            return [
                ('straight', first_straight),
                ('elbow', cross_dir),
                ('straight', cross_straight),
                ('elbow', sx),
                ('straight', last_straight)
            ]

        # Case 2: Opposite directions → U-shape (needs extra axis)
        elif abs(sx.dot(ax) + 1.0) < 0.01:
            # Need to go sideways, then back
            # Find a perpendicular direction to go around
            # Use +Z if possible, otherwise +Y
            perp = FreeCAD.Vector(0, 0, 1)
            if abs(sx.dot(perp)) > 0.9:
                perp = FreeCAD.Vector(0, 1, 0)
            # Cross product gives perpendicular in the plane
            side = sx.cross(perp).normalize()

            offset_dist = 500  # how far to the side
            along_start = abs(delta.dot(sx))

            return [
                ('straight', 300),
                ('elbow', side),
                ('straight', offset_dist),
                ('elbow', ax),  # now going opposite to start
                ('straight', along_start + 600 - 4 * br),
                ('elbow', side * -1),
                ('straight', offset_dist),
                ('elbow', ax),
                ('straight', 300)
            ]

        # Case 3: Perpendicular → L-shape (1 elbow)
        else:
            # After straight L1, elbow adds br in both dirs
            L1 = delta.dot(sx) - br
            L2 = delta.dot(ax) - br

            if L1 < 50 or L2 < 50:
                return None

            # Check no offset on third axis
            third_axis = sx.cross(ax)
            third_offset = abs(delta.dot(third_axis))
            if third_offset > 0.5:
                return None

            return [
                ('straight', L1),
                ('elbow', ax),
                ('straight', L2)
            ]

    def _plan_blocked(self, plan, start_pos, start_dir):
        """Check if a planned route passes through obstacles."""
        pos = FreeCAD.Vector(start_pos)
        direction = FreeCAD.Vector(start_dir).normalize()
        br = self.bend_radius

        for step in plan:
            if step[0] == 'straight':
                end = pos + direction * step[1]
                if self._segment_blocked(pos, end):
                    return True
                pos = end
            elif step[0] == 'elbow':
                turn_to = FreeCAD.Vector(step[1]).normalize()
                center = pos + turn_to * br
                exit_pos = center + direction * br
                # Check a few points on the arc
                for t in [0.25, 0.5, 0.75]:
                    mid = pos + (exit_pos - pos) * t
                    if self._is_blocked(mid):
                        return True
                pos = exit_pos
                direction = turn_to

        return False

    def _astar_route(self, start_pos, start_dir, end_pos, arrive_dir):
        """
        A* pathfinding on a 3D grid. Returns simplified waypoints (direction changes only).
        Only moves in 6 orthogonal directions.
        """
        gs = self.grid_size

        start = (round(start_pos.x / gs), round(start_pos.y / gs), round(start_pos.z / gs))
        end = (round(end_pos.x / gs), round(end_pos.y / gs), round(end_pos.z / gs))

        def is_free(cell):
            pt = FreeCAD.Vector(cell[0] * gs, cell[1] * gs, cell[2] * gs)
            return not self._is_blocked(pt) and cell[2] >= 0

        if not is_free(start):
            start = self._find_free_near(start, gs)
        if not is_free(end):
            end = self._find_free_near(end, gs)
        if start is None or end is None:
            return None

        # A* with bend penalty
        counter = 0
        open_set = [(0, counter, start, None)]  # (f, count, cell, prev_dir)
        came_from = {}
        g_score = {start: 0}
        bend_penalty = 2.5

        directions = [(1,0,0), (-1,0,0), (0,1,0), (0,-1,0), (0,0,1), (0,0,-1)]

        for _ in range(300000):
            if not open_set:
                break

            _, _, current, prev_dir = heapq.heappop(open_set)

            if current == end:
                # Reconstruct
                path = [current]
                while current in came_from:
                    current = came_from[current]
                    path.append(current)
                path.reverse()
                # Convert to world coords and simplify
                world_path = [FreeCAD.Vector(c[0]*gs, c[1]*gs, c[2]*gs) for c in path]
                return self._simplify_path(world_path)

            for dx, dy, dz in directions:
                neighbor = (current[0]+dx, current[1]+dy, current[2]+dz)
                if not is_free(neighbor):
                    continue

                this_dir = (dx, dy, dz)
                step_cost = gs
                if prev_dir and prev_dir != this_dir:
                    step_cost *= bend_penalty

                tentative_g = g_score[current] + step_cost
                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    h = (abs(neighbor[0]-end[0]) + abs(neighbor[1]-end[1]) + abs(neighbor[2]-end[2])) * gs
                    counter += 1
                    heapq.heappush(open_set, (tentative_g + h, counter, neighbor, this_dir))

        return None

    def _find_free_near(self, cell, gs):
        """Find nearest free cell."""
        for r in range(1, 15):
            for dx in range(-r, r+1):
                for dy in range(-r, r+1):
                    for dz in range(0, r+1):
                        c = (cell[0]+dx, cell[1]+dy, cell[2]+dz)
                        pt = FreeCAD.Vector(c[0]*gs, c[1]*gs, c[2]*gs)
                        if not self._is_blocked(pt) and c[2] >= 0:
                            return c
        return None

    def _simplify_path(self, path):
        """Remove collinear points, keep only direction-change waypoints."""
        if len(path) < 3:
            return path
        result = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = path[i] - path[i-1]
            d2 = path[i+1] - path[i]
            if d1.Length > 0.1:
                d1.normalize()
            if d2.Length > 0.1:
                d2.normalize()
            if (d1 - d2).Length > 0.01:
                result.append(path[i])
        result.append(path[-1])
        return result

    def _waypoints_to_parts(self, waypoints, start_dir, arrive_dir):
        """
        Convert A* waypoints to pipe parts (straights + elbows).
        Waypoints are at direction-change points.
        """
        if len(waypoints) < 2:
            return None

        parts = []
        br = self.bend_radius

        for i in range(len(waypoints) - 1):
            p1 = waypoints[i]
            p2 = waypoints[i + 1]
            seg_dir = (p2 - p1)
            seg_length = seg_dir.Length
            seg_dir.normalize()

            # Shorten segment for adjacent elbows
            actual_start = FreeCAD.Vector(p1)
            actual_length = seg_length

            if i > 0:
                # Previous segment had an elbow at its end → this segment starts after elbow exit
                actual_start = p1  # Already adjusted by elbow placement
                actual_length -= br

            if i < len(waypoints) - 2:
                # Next waypoint has a direction change → elbow at end of this segment
                actual_length -= br

            if actual_length < 10:
                continue  # Skip very short segments

            # Build straight
            shape = Part.makeCylinder(self.od/2, actual_length, actual_start, seg_dir)
            parts.append({
                'type': 'straight',
                'entry_pos': FreeCAD.Vector(actual_start),
                'exit_pos': actual_start + seg_dir * actual_length,
                'entry_dir': FreeCAD.Vector(seg_dir),
                'exit_dir': FreeCAD.Vector(seg_dir),
                'shape': shape
            })

            # Add elbow if direction changes at next waypoint
            if i < len(waypoints) - 2:
                next_dir = (waypoints[i+2] - waypoints[i+1]).normalize()
                elbow_entry = actual_start + seg_dir * actual_length
                center = elbow_entry + next_dir * br
                elbow_exit = center + seg_dir * br

                mid_vec = ((elbow_entry - center) + (elbow_exit - center)).normalize()
                arc_mid = center + mid_vec * br

                try:
                    arc = Part.Arc(elbow_entry, arc_mid, elbow_exit)
                    wire = Part.Wire([arc.toShape()])
                    circle = Part.makeCircle(self.od/2, elbow_entry, seg_dir)
                    circle_wire = Part.Wire([circle])
                    elbow_shape = wire.makePipeShell([circle_wire], True, True)

                    parts.append({
                        'type': 'elbow',
                        'entry_pos': FreeCAD.Vector(elbow_entry),
                        'exit_pos': FreeCAD.Vector(elbow_exit),
                        'entry_dir': FreeCAD.Vector(seg_dir),
                        'exit_dir': FreeCAD.Vector(next_dir),
                        'shape': elbow_shape
                    })
                except Exception:
                    pass  # Skip failed elbows

        return parts if parts else None

    def _plan_to_parts(self, plan, start_pos, start_dir):
        """Convert a route plan to pipe part geometry."""
        parts = []
        pos = FreeCAD.Vector(start_pos)
        direction = FreeCAD.Vector(start_dir).normalize()
        br = self.bend_radius

        for step in plan:
            if step[0] == 'straight':
                length = step[1]
                exit_pos = pos + direction * length
                shape = Part.makeCylinder(self.od/2, length, pos, direction)
                parts.append({
                    'type': 'straight',
                    'entry_pos': FreeCAD.Vector(pos),
                    'exit_pos': exit_pos,
                    'entry_dir': FreeCAD.Vector(direction),
                    'exit_dir': FreeCAD.Vector(direction),
                    'shape': shape
                })
                pos = FreeCAD.Vector(exit_pos)

            elif step[0] == 'elbow':
                turn_to = FreeCAD.Vector(step[1]).normalize()
                center = pos + turn_to * br
                exit_pos = center + direction * br

                mid_vec = ((pos - center) + (exit_pos - center)).normalize()
                arc_mid = center + mid_vec * br

                try:
                    arc = Part.Arc(pos, arc_mid, exit_pos)
                    wire = Part.Wire([arc.toShape()])
                    circle = Part.makeCircle(self.od/2, pos, direction)
                    circle_wire = Part.Wire([circle])
                    shape = wire.makePipeShell([circle_wire], True, True)

                    parts.append({
                        'type': 'elbow',
                        'entry_pos': FreeCAD.Vector(pos),
                        'exit_pos': FreeCAD.Vector(exit_pos),
                        'entry_dir': FreeCAD.Vector(direction),
                        'exit_dir': FreeCAD.Vector(turn_to),
                        'shape': shape
                    })
                except Exception as e:
                    return None  # Elbow failed

                pos = FreeCAD.Vector(exit_pos)
                direction = FreeCAD.Vector(turn_to)

        return parts


def validate_waypoints(waypoints, bend_radius, start_nozzle=None, end_nozzle=None):
    """
    Check that waypoints form a valid orthogonal pipe route.

    Rules:
    - Each segment must move on exactly one axis (orthogonal)
    - Interior segments must be >= 2 * bend_radius (room for elbow at each end)
    - First/last segments must be >= 1 * bend_radius (elbow on one end only)
    - First segment must be collinear with start nozzle direction (nozzle alignment)
    - Last segment must be collinear with end nozzle direction (nozzle alignment)

    Args:
        waypoints: list of FreeCAD.Vector
        bend_radius: elbow centerline bend radius (mm)
        start_nozzle: optional (pos, direction) tuple - the departure nozzle
        end_nozzle: optional (pos, direction) tuple - the arrival nozzle

    Returns list of error strings (empty = valid).
    """
    errors = []

    if len(waypoints) < 2:
        errors.append("Need at least 2 waypoints")
        return errors

    # --- Nozzle alignment checks ---
    # A nozzle accepts connection on exactly one axis (its direction vector).
    # The pipe segment at that nozzle must travel along that same axis.
    #
    # Start nozzle: pipe DEPARTS in nozzle.direction
    #   → first segment direction must equal nozzle.direction
    #   → first waypoint must equal nozzle.pos
    #
    # End nozzle: pipe ARRIVES opposite to nozzle.direction
    #   → last segment direction must equal -nozzle.direction
    #   → last waypoint must equal nozzle.pos

    if start_nozzle is not None:
        nozzle_pos, nozzle_dir = start_nozzle
        nozzle_dir = FreeCAD.Vector(nozzle_dir).normalize()

        # Check position
        pos_gap = (waypoints[0] - FreeCAD.Vector(nozzle_pos)).Length
        if pos_gap > 1.0:
            errors.append(
                f"Start: first waypoint {waypoints[0]} != nozzle pos {nozzle_pos} "
                f"(gap {pos_gap:.1f}mm)"
            )

        # Check direction alignment
        first_seg = waypoints[1] - waypoints[0]
        if first_seg.Length > 0.1:
            first_dir = FreeCAD.Vector(first_seg).normalize()
            dot = abs(first_dir.dot(nozzle_dir))
            if dot < 0.99:
                errors.append(
                    f"Start: first segment direction {first_dir} not aligned with "
                    f"nozzle direction {nozzle_dir} (dot={dot:.3f}, need 1.0)"
                )
            # Also check same sense (not going backwards into the nozzle)
            if first_dir.dot(nozzle_dir) < 0:
                errors.append(
                    f"Start: pipe goes OPPOSITE to nozzle direction "
                    f"(into equipment instead of away)"
                )

    if end_nozzle is not None:
        nozzle_pos, nozzle_dir = end_nozzle
        nozzle_dir = FreeCAD.Vector(nozzle_dir).normalize()

        # Check position
        pos_gap = (waypoints[-1] - FreeCAD.Vector(nozzle_pos)).Length
        if pos_gap > 1.0:
            errors.append(
                f"End: last waypoint {waypoints[-1]} != nozzle pos {nozzle_pos} "
                f"(gap {pos_gap:.1f}mm)"
            )

        # Check direction alignment
        # Pipe must ARRIVE opposite to nozzle outward direction
        # i.e. last segment direction = -nozzle_dir
        last_seg = waypoints[-1] - waypoints[-2]
        if last_seg.Length > 0.1:
            last_dir = FreeCAD.Vector(last_seg).normalize()
            # last_dir should equal -nozzle_dir (arriving INTO the nozzle face)
            expected_arrive = nozzle_dir * -1
            dot = last_dir.dot(expected_arrive)
            if dot < 0.99:
                errors.append(
                    f"End: last segment direction {last_dir} not aligned with "
                    f"arrival direction {expected_arrive} "
                    f"(nozzle faces {nozzle_dir}, pipe must arrive opposite)"
                )

    # --- Segment checks ---
    for i in range(len(waypoints) - 1):
        seg = waypoints[i+1] - waypoints[i]
        seg_len = seg.Length

        # Check orthogonal (only one axis moves)
        non_zero = sum(1 for v in [abs(seg.x), abs(seg.y), abs(seg.z)] if v > 0.5)
        if non_zero != 1:
            errors.append(f"Segment {i}->{i+1}: not orthogonal (moves on {non_zero} axes)")

        # Check no 180° reversals (consecutive segments on same axis, opposite direction)
        # A 90° elbow cannot make a 180° turn. Use a perpendicular intermediate segment.
        if i < len(waypoints) - 2:
            next_seg = waypoints[i+2] - waypoints[i+1]
            if seg.Length > 0.1 and next_seg.Length > 0.1:
                seg_dir = FreeCAD.Vector(seg).normalize()
                next_dir = FreeCAD.Vector(next_seg).normalize()
                if seg_dir.dot(next_dir) < -0.99:
                    errors.append(
                        f"Segment {i}->{i+1} to {i+1}->{i+2}: 180° reversal "
                        f"(not possible with 90° elbow, add perpendicular step)"
                    )

        # Check minimum length
        is_first = (i == 0)
        is_last = (i == len(waypoints) - 2)
        if is_first or is_last:
            min_len = bend_radius
        else:
            min_len = 2 * bend_radius

        if seg_len < min_len:
            errors.append(
                f"Segment {i}->{i+1}: length {seg_len:.0f}mm < minimum {min_len:.0f}mm"
            )

    return errors


def waypoints_to_pipe(waypoints, doc, name_prefix, od=114.3, bend_radius=171.5,
                      start_nozzle=None, end_nozzle=None):
    """
    Convert orthogonal waypoints to pipe geometry (straights + elbows).

    Each waypoint is a direction-change point. Segments between waypoints
    must be axis-aligned and meet minimum length constraints. The first/last
    segments must align with their respective nozzle directions.

    Args:
        waypoints: list of FreeCAD.Vector - corner points of the route
        doc: FreeCAD document to add objects to
        name_prefix: string prefix for object names
        od: outer diameter in mm
        bend_radius: elbow centerline bend radius in mm
        start_nozzle: optional (pos, direction) - departure nozzle.
            First waypoint must equal pos, first segment must go in direction.
        end_nozzle: optional (pos, direction) - arrival nozzle.
            Last waypoint must equal pos, last segment must arrive opposite to direction.

    Returns:
        (objects, errors) - list of FreeCAD objects, list of error strings
    """
    errors = validate_waypoints(waypoints, bend_radius, start_nozzle, end_nozzle)
    if errors:
        return [], errors

    objects = []
    br = bend_radius

    for i in range(len(waypoints) - 1):
        p1 = waypoints[i]
        p2 = waypoints[i + 1]
        seg_vec = p2 - p1
        seg_len = seg_vec.Length
        seg_dir = FreeCAD.Vector(seg_vec).normalize()

        # Trim for elbows
        trim_start = br if i > 0 else 0
        trim_end = br if i < len(waypoints) - 2 else 0
        straight_len = seg_len - trim_start - trim_end

        start_pt = p1 + seg_dir * trim_start
        end_pt = start_pt + seg_dir * straight_len

        # Build straight section
        shape = Part.makeCylinder(od / 2, straight_len, start_pt, seg_dir)
        obj = doc.addObject("Part::Feature", f"{name_prefix}_{i:02d}_str")
        obj.Shape = shape
        objects.append(obj)

        # Build elbow at end (if direction changes)
        if i < len(waypoints) - 2:
            next_dir = (waypoints[i + 2] - waypoints[i + 1]).normalize()
            elbow_entry = end_pt
            center = elbow_entry + next_dir * br
            elbow_exit = center + seg_dir * br

            mid_vec = ((elbow_entry - center) + (elbow_exit - center)).normalize()
            arc_mid = center + mid_vec * br

            try:
                arc = Part.Arc(elbow_entry, arc_mid, elbow_exit)
                wire = Part.Wire([arc.toShape()])
                circle = Part.makeCircle(od / 2, elbow_entry, seg_dir)
                circle_wire = Part.Wire([circle])
                elbow_shape = wire.makePipeShell([circle_wire], True, True)

                obj = doc.addObject("Part::Feature", f"{name_prefix}_{i:02d}_elb")
                obj.Shape = elbow_shape
                objects.append(obj)
            except Exception as e:
                errors.append(f"Elbow {i} failed: {e}")

    return objects, errors


def build_and_validate(parts, doc, name_prefix):
    """Add pipe parts to FreeCAD document and validate chain alignment."""
    errors = []
    objects = []

    for i, part in enumerate(parts):
        if i > 0:
            gap = (part['entry_pos'] - parts[i-1]['exit_pos']).Length
            if gap > 0.5:
                errors.append(f"Part {i}: {gap:.1f}mm gap")

        obj = doc.addObject("Part::Feature", f"{name_prefix}_{i:02d}_{part['type']}")
        obj.Shape = part['shape']
        objects.append(obj)

    return objects, errors
