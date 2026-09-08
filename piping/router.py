"""
A* Pipe Router for FreeCAD.

Finds orthogonal paths between two 3D points while avoiding obstacles.
Based on research from MrNorwayman/Automatic-Pipe-Routing (D* approach).

Key features:
- 6-directional orthogonal movement (Manhattan paths)
- Obstacle avoidance (equipment bounding boxes)
- Bend penalty (prefers straights over turns)
- Sequential routing (previously routed pipes become obstacles)
- Outputs waypoints compatible with create_pipe_run()

Usage:
    router = PipeRouter(grid_size=200)
    router.add_obstacle_box(equipment_min, equipment_max)

    # Route supply
    supply_wp = router.find_path(pump_discharge, hx_inlet)
    supply = create_pipe_run(doc, "Supply", 150, supply_wp)

    # Add supply as obstacle, then route return
    router.add_pipe_as_obstacle(supply, padding=300)
    return_wp = router.find_path(hx_outlet, pump_suction)
    ret = create_pipe_run(doc, "Return", 150, return_wp)
"""

import math
import heapq
import FreeCAD
import Part


class PipeRouter:
    """
    A* grid-based 3D pipe router with obstacle avoidance.
    """

    def __init__(self, grid_size=200, bend_penalty=2.5):
        """
        Args:
            grid_size: Cell size in mm. Smaller = more precise, slower.
                       200mm works well for DN100-DN300 pipes.
            bend_penalty: Cost multiplier for direction changes.
                          2.5 = bends cost 2.5x more than straights.
                          Higher values produce routes with fewer elbows.
        """
        self.grid_size = grid_size
        self.bend_penalty = bend_penalty
        self.obstacles = set()  # set of (gx, gy, gz) blocked cells

    def add_obstacle_box(self, min_pt, max_pt, padding=0):
        """
        Block a rectangular volume (equipment bounding box).

        Args:
            min_pt: FreeCAD.Vector or tuple - minimum corner
            max_pt: FreeCAD.Vector or tuple - maximum corner
            padding: Extra clearance around the box (mm)
        """
        gs = self.grid_size
        if hasattr(min_pt, 'x'):
            x0, y0, z0 = min_pt.x, min_pt.y, min_pt.z
            x1, y1, z1 = max_pt.x, max_pt.y, max_pt.z
        else:
            x0, y0, z0 = min_pt
            x1, y1, z1 = max_pt

        for x in range(int((x0 - padding) / gs), int((x1 + padding) / gs) + 1):
            for y in range(int((y0 - padding) / gs), int((y1 + padding) / gs) + 1):
                for z in range(int((z0 - padding) / gs), int((z1 + padding) / gs) + 1):
                    self.obstacles.add((x, y, z))

    def add_pipe_as_obstacle(self, route, padding=300):
        """
        Add a previously routed pipe as an obstacle for sequential routing.
        This forces subsequent pipes to take different paths.

        Args:
            route: PipeRoute object (must have segments built)
            padding: Clearance around the pipe (mm)
        """
        gs = self.grid_size
        # Sample points along each segment
        for seg in route.segments:
            if not hasattr(seg, 'start') or not hasattr(seg, 'end'):
                continue
            start = seg.start.pos
            end = seg.end.pos
            length = (end - start).Length
            steps = max(2, int(length / gs) + 1)

            for i in range(steps):
                t = i / max(1, steps - 1)
                pt = start + (end - start) * t
                # Block cells around this point
                cx, cy, cz = round(pt.x / gs), round(pt.y / gs), round(pt.z / gs)
                r = max(1, int(padding / gs))
                for dx in range(-r, r + 1):
                    for dy in range(-r, r + 1):
                        for dz in range(-r, r + 1):
                            self.obstacles.add((cx + dx, cy + dy, cz + dz))

    def add_floor(self, z_level=0):
        """Block everything at or below floor level."""
        # We don't block specific cells - just check z >= 0 in the search
        pass  # Handled in find_path via z < 0 check

    def find_path(self, start_pos, end_pos, max_iterations=500000):
        """
        Find optimal orthogonal path from start to end.

        Args:
            start_pos: FreeCAD.Vector - starting position
            end_pos: FreeCAD.Vector - ending position
            max_iterations: Safety limit to prevent infinite loops

        Returns:
            List of FreeCAD.Vector waypoints (simplified, only at direction changes)
            or None if no path found.
        """
        gs = self.grid_size
        start = (round(start_pos.x / gs), round(start_pos.y / gs), round(start_pos.z / gs))
        end = (round(end_pos.x / gs), round(end_pos.y / gs), round(end_pos.z / gs))

        # If start or end is blocked, find nearest free cell
        if start in self.obstacles:
            start = self._nearest_free(start)
        if end in self.obstacles:
            end = self._nearest_free(end)

        if start is None or end is None:
            return None

        # A* search
        counter = 0
        open_set = [(0, counter, start)]
        came_from = {}
        g_score = {start: 0}

        for _ in range(max_iterations):
            if not open_set:
                break

            _, _, current = heapq.heappop(open_set)

            if current == end:
                # Reconstruct path
                path = []
                while current in came_from:
                    path.append(FreeCAD.Vector(
                        current[0] * gs, current[1] * gs, current[2] * gs))
                    current = came_from[current]
                path.append(FreeCAD.Vector(
                    current[0] * gs, current[1] * gs, current[2] * gs))
                path.reverse()
                return self._simplify(path)

            # Expand 6 orthogonal neighbors
            for dx, dy, dz in [(1,0,0), (-1,0,0), (0,1,0), (0,-1,0), (0,0,1), (0,0,-1)]:
                neighbor = (current[0] + dx, current[1] + dy, current[2] + dz)

                # Skip if blocked or underground
                if neighbor in self.obstacles:
                    continue
                if neighbor[2] < 0:
                    continue

                # Calculate step cost with bend penalty
                step_cost = gs
                if current in came_from:
                    prev = came_from[current]
                    prev_dir = (current[0] - prev[0], current[1] - prev[1], current[2] - prev[2])
                    this_dir = (dx, dy, dz)
                    if prev_dir != this_dir:
                        step_cost *= self.bend_penalty

                tentative_g = g_score[current] + step_cost

                if tentative_g < g_score.get(neighbor, float('inf')):
                    came_from[neighbor] = current
                    g_score[neighbor] = tentative_g
                    h = (abs(neighbor[0] - end[0]) + abs(neighbor[1] - end[1]) +
                         abs(neighbor[2] - end[2])) * gs
                    counter += 1
                    heapq.heappush(open_set, (tentative_g + h, counter, neighbor))

        return None  # No path found within iteration limit

    def _nearest_free(self, cell):
        """Find nearest unblocked cell (spiral search)."""
        for r in range(1, 20):
            for dx in range(-r, r + 1):
                for dy in range(-r, r + 1):
                    for dz in range(0, r + 1):
                        c = (cell[0] + dx, cell[1] + dy, cell[2] + dz)
                        if c not in self.obstacles and c[2] >= 0:
                            return c
        return None

    def _simplify(self, path):
        """Remove collinear intermediate points, keeping only direction-change waypoints."""
        if len(path) < 3:
            return path

        result = [path[0]]
        for i in range(1, len(path) - 1):
            d1 = path[i] - path[i - 1]
            d2 = path[i + 1] - path[i]
            if d1.Length > 0.1:
                d1.normalize()
            if d2.Length > 0.1:
                d2.normalize()
            if (d1 - d2).Length > 0.01:
                result.append(path[i])
        result.append(path[-1])
        return result
