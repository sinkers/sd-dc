"""
Cable Tray Routing System for FreeCAD
=====================================

Scripted system to route cable tray from point A to point B using Ezystrut
NEMA3 ladder tray components. Generates 3D geometry and a bill of materials.

Usage:
    Run in FreeCAD Python console or as a macro.

    from cable_tray_router import CableTrayRoute, TraySpec, NEMA3_600, NEMA3_900

    route = CableTrayRoute("MSB1_to_DataHall")
    route.set_tray(NEMA3_600)
    route.start(x=0, y=0, z=3000)       # Start point and height
    route.straight(6000)                  # 6m straight run in current direction
    route.horizontal_bend("left", 90)    # 90° left turn
    route.straight(3000)                  # 3m toward building
    route.penetration("Building West Wall", thickness=200)
    route.straight(1000)                  # 1m inside
    route.vertical_bend("down", 90)      # Riser down
    route.straight_vertical(1500)         # 1.5m drop
    route.vertical_bend("down_to_horiz", 90)  # Back to horizontal
    route.straight(3000)                  # Lower level run
    route.tee("left")                     # T-junction
    route.end()

    route.build()                         # Generate FreeCAD geometry
    route.print_bom()                     # Print bill of materials
    route.print_supports()                # Print support schedule

Standards:
    - AS/NZS 3000 (Wiring Rules) cl. 3.9.5
    - Ezystrut ET3/ET5/NEMA product range
    - Support spacing per manufacturer load ratings

Reference:
    - AU01-2-ELE-xxx: NEMA3 600mm site runs, NEMA3 900mm TX-to-MSB
    - EZYSTRUT CB4-750H cantilever brackets
    - 150x150 and 100x100 mounting posts with 400x400x10 base plates
    - 41x41 channel strut bracing
    - Design load: 30 kg/m cable + 39.6 kg per 6m ladder self-weight
"""

import math
from dataclasses import dataclass, field
from typing import List, Tuple, Optional
from enum import Enum


# ============================================================
# TRAY SPECIFICATIONS (Ezystrut product range)
# ============================================================

@dataclass
class TraySpec:
    """Cable tray specification matching Ezystrut product catalogue."""
    name: str
    part_prefix: str
    width: float           # mm, cable laying width
    overall_width: float   # mm, including side returns
    side_height: float     # mm
    cable_depth: float     # mm, usable cable laying depth
    thickness: float       # mm, sheet steel
    standard_length: float # mm
    weight_per_m: float    # kg/m, tray self-weight
    bend_radius: float     # mm, inner radius for bends
    # Load rating: (span_mm, max_load_kg_per_m, deflection_mm)
    load_ratings: List[Tuple[float, float, float]] = field(default_factory=list)
    finish: str = "G"      # G=pre-galv, H=HDG, SS=stainless


# Ezystrut NEMA3 Ladder Tray (as used at AU01-2 and AU04)
NEMA3_600 = TraySpec(
    name="NEMA3 Cable Ladder 600mm",
    part_prefix="NEMA3-600",
    width=600,
    overall_width=660,    # 600 + 2x30mm side rails
    side_height=100,      # NEMA3 standard rail height
    cable_depth=75,
    thickness=2.0,
    standard_length=6000, # 6m lengths per AU04 docs (39.6 kg per 6m)
    weight_per_m=6.6,     # 39.6 kg / 6m
    bend_radius=600,      # typically equal to width for NEMA
    load_ratings=[
        (3000, 60, 15),
        (2500, 80, 12),
        (2000, 120, 8),
        (1500, 200, 5),
    ],
)

NEMA3_900 = TraySpec(
    name="NEMA3 Cable Ladder 900mm",
    part_prefix="NEMA3-900",
    width=900,
    overall_width=960,
    side_height=100,
    cable_depth=75,
    thickness=2.5,
    standard_length=6000,
    weight_per_m=9.5,
    bend_radius=900,
    load_ratings=[
        (3000, 50, 18),
        (2500, 70, 14),
        (2000, 100, 10),
        (1500, 170, 6),
    ],
)

# Ezystrut ET5 (for comparison / indoor use)
ET5_300 = TraySpec(
    name="ET5 Cable Tray 300mm",
    part_prefix="ET5300",
    width=300,
    overall_width=321,
    side_height=85,
    cable_depth=78,
    thickness=1.6,
    standard_length=3000,
    weight_per_m=3.8,
    bend_radius=300,
    load_ratings=[
        (3000, 60, 14),
        (2500, 82, 11),
        (2000, 128, 8),
        (1500, 227, 6),
    ],
)

ET5_600 = TraySpec(
    name="ET5 Cable Tray 600mm",
    part_prefix="ET5600",
    width=600,
    overall_width=621,
    side_height=85,
    cable_depth=78,
    thickness=1.6,
    standard_length=3000,
    weight_per_m=5.2,
    bend_radius=450,
    load_ratings=[
        (3000, 60, 14),
        (2500, 82, 11),
        (2000, 128, 8),
        (1500, 227, 6),
    ],
)


# ============================================================
# SUPPORT SPECIFICATIONS
# ============================================================

@dataclass
class SupportSpec:
    """Cable tray support specification."""
    name: str
    part_number: str
    type: str           # "trapeze", "cantilever", "post", "wall_bracket"
    max_tray_width: float
    working_load: float  # kg
    description: str


# Ezystrut supports from AU01-2 reference drawings
SUPPORTS = {
    "CB4-750H": SupportSpec(
        name="Cantilever Bracket CB4-750H",
        part_number="CB4-750H",
        type="cantilever",
        max_tray_width=750,
        working_load=150,
        description="Ezystrut CB4-750H cantilever bracket for wall/post mounting",
    ),
    "POST_150": SupportSpec(
        name="150x150 Steel Post",
        part_number="POST-150x150",
        type="post",
        max_tray_width=900,
        working_load=500,
        description="150x150 SHS post with 400x400x10 base plate, 41x41 strut bracing",
    ),
    "POST_100": SupportSpec(
        name="100x100 Steel Post",
        part_number="POST-100x100",
        type="post",
        max_tray_width=600,
        working_load=300,
        description="100x100 SHS post with 400x400x10 base plate, 41x41 strut bracing",
    ),
    "TB600G": SupportSpec(
        name="Trapeze Bracket 600mm",
        part_number="TB600G",
        type="trapeze",
        max_tray_width=600,
        working_load=34,
        description="Ezystrut standard trapeze bracket, ceiling hung from M12 rod",
    ),
}


# ============================================================
# ROUTE SEGMENT TYPES
# ============================================================

class Direction(Enum):
    POS_X = (1, 0, 0)
    NEG_X = (-1, 0, 0)
    POS_Y = (0, 1, 0)
    NEG_Y = (0, -1, 0)
    POS_Z = (0, 0, 1)
    NEG_Z = (0, 0, -1)


class SegmentType(Enum):
    STRAIGHT = "straight"
    HORIZONTAL_BEND = "horizontal_bend"
    VERTICAL_BEND_DOWN = "vertical_bend_down"       # horizontal to descending
    VERTICAL_BEND_UP = "vertical_bend_up"           # horizontal to ascending
    VERTICAL_BEND_TO_HORIZ = "vertical_to_horizontal"  # vertical to horizontal
    VERTICAL_STRAIGHT = "vertical_straight"
    TEE = "tee"
    CROSS = "cross"
    PENETRATION = "penetration"


@dataclass
class RouteSegment:
    """A single segment of cable tray route."""
    seg_type: SegmentType
    start_point: Tuple[float, float, float]
    end_point: Tuple[float, float, float]
    direction_in: Direction
    direction_out: Direction
    length: float        # mm (arc length for bends)
    angle: float = 90.0  # degrees (for bends)
    turn: str = ""       # "left", "right" for horizontal bends
    notes: str = ""      # penetration notes, obstacle notes


@dataclass
class SupportPoint:
    """A point where a support is required."""
    position: Tuple[float, float, float]
    support_type: str     # key into SUPPORTS dict
    segment_index: int    # which segment this support is on
    notes: str = ""


@dataclass
class BOMItem:
    """Bill of materials entry."""
    part_number: str
    description: str
    quantity: int
    unit: str = "ea"
    notes: str = ""


# ============================================================
# CABLE TRAY ROUTE CLASS
# ============================================================

class CableTrayRoute:
    """
    Cable tray routing engine.

    Builds a route as a sequence of segments, calculates support positions,
    generates FreeCAD geometry, and produces a bill of materials.
    """

    def __init__(self, name: str, cable_load_kg_per_m: float = 30.0):
        self.name = name
        self.cable_load = cable_load_kg_per_m  # from AU04 reference: 30 kg/m
        self.tray: Optional[TraySpec] = None
        self.segments: List[RouteSegment] = []
        self.supports: List[SupportPoint] = []
        self.penetrations: List[dict] = []
        self.obstacles: List[dict] = []

        # Current routing state
        self._pos = (0.0, 0.0, 0.0)
        self._direction = Direction.POS_X
        self._started = False
        self._support_spacing = 2500  # mm, default

    def set_tray(self, spec: TraySpec):
        """Set the cable tray specification."""
        self.tray = spec
        # Calculate appropriate support spacing based on load
        total_load = self.cable_load + spec.weight_per_m
        for span, max_load, defl in spec.load_ratings:
            if max_load >= total_load:
                self._support_spacing = span
                break
        else:
            self._support_spacing = spec.load_ratings[-1][0]  # smallest span
        print(f"Tray: {spec.name}")
        print(f"  Total load: {total_load:.1f} kg/m (cable {self.cable_load} + tray {spec.weight_per_m})")
        print(f"  Support spacing: {self._support_spacing} mm")

    def set_support_spacing(self, spacing_mm: float):
        """Override calculated support spacing."""
        self._support_spacing = spacing_mm

    def start(self, x: float, y: float, z: float, direction: Direction = Direction.POS_X):
        """Set the starting point and initial direction."""
        self._pos = (x, y, z)
        self._direction = direction
        self._started = True
        print(f"Start: ({x}, {y}, {z}) heading {direction.name}")

    def straight(self, length: float, notes: str = ""):
        """Add a straight tray section."""
        if not self._started:
            raise ValueError("Call start() before adding segments")

        dx, dy, dz = self._direction.value
        end = (
            self._pos[0] + dx * length,
            self._pos[1] + dy * length,
            self._pos[2] + dz * length,
        )

        seg = RouteSegment(
            seg_type=SegmentType.STRAIGHT,
            start_point=self._pos,
            end_point=end,
            direction_in=self._direction,
            direction_out=self._direction,
            length=length,
            notes=notes,
        )
        self.segments.append(seg)
        self._pos = end
        print(f"  Straight {length}mm → ({end[0]:.0f}, {end[1]:.0f}, {end[2]:.0f})")

    def straight_vertical(self, length: float, direction: str = "down", notes: str = ""):
        """Add a vertical straight section."""
        if direction == "down":
            self._direction = Direction.NEG_Z
        else:
            self._direction = Direction.POS_Z

        dx, dy, dz = self._direction.value
        end = (
            self._pos[0] + dx * length,
            self._pos[1] + dy * length,
            self._pos[2] + dz * length,
        )

        seg = RouteSegment(
            seg_type=SegmentType.VERTICAL_STRAIGHT,
            start_point=self._pos,
            end_point=end,
            direction_in=self._direction,
            direction_out=self._direction,
            length=length,
            notes=notes,
        )
        self.segments.append(seg)
        self._pos = end
        print(f"  Vertical {direction} {length}mm → ({end[0]:.0f}, {end[1]:.0f}, {end[2]:.0f})")

    def horizontal_bend(self, turn: str, angle: float = 90.0, notes: str = ""):
        """
        Add a horizontal bend.

        Args:
            turn: "left" or "right" relative to current travel direction
            angle: bend angle in degrees (default 90)
        """
        R = self.tray.bend_radius if self.tray else 300
        arc_length = (angle / 360) * 2 * math.pi * (R + self.tray.overall_width / 2)

        # Calculate new direction after turn
        new_dir = self._turn_horizontal(self._direction, turn, angle)

        # Calculate end point (center of tray at bend exit)
        end = self._calc_bend_endpoint(self._pos, self._direction, new_dir, R)

        seg = RouteSegment(
            seg_type=SegmentType.HORIZONTAL_BEND,
            start_point=self._pos,
            end_point=end,
            direction_in=self._direction,
            direction_out=new_dir,
            length=arc_length,
            angle=angle,
            turn=turn,
            notes=notes,
        )
        self.segments.append(seg)
        self._pos = end
        self._direction = new_dir
        print(f"  Bend {turn} {angle}° → heading {new_dir.name}, at ({end[0]:.0f}, {end[1]:.0f}, {end[2]:.0f})")

    def vertical_bend(self, bend_type: str, angle: float = 90.0, notes: str = ""):
        """
        Add a vertical bend (riser).

        Args:
            bend_type: "up" (horizontal to ascending), "down" (horizontal to descending),
                      "up_to_horiz" (ascending to horizontal), "down_to_horiz" (descending to horizontal)
        """
        R = self.tray.bend_radius if self.tray else 300
        arc_length = (angle / 360) * 2 * math.pi * (R + self.tray.overall_width / 2)

        if bend_type == "down":
            new_dir = Direction.NEG_Z
            seg_type = SegmentType.VERTICAL_BEND_DOWN
        elif bend_type == "up":
            new_dir = Direction.POS_Z
            seg_type = SegmentType.VERTICAL_BEND_UP
        elif bend_type in ("down_to_horiz", "up_to_horiz"):
            new_dir = self._direction  # will be overridden
            seg_type = SegmentType.VERTICAL_BEND_TO_HORIZ
        else:
            raise ValueError(f"Unknown bend_type: {bend_type}")

        # For vertical bends, we need to track which horizontal direction
        # was active before going vertical
        if bend_type == "down":
            # End point is offset in current direction by R, then down by R
            dx, dy, dz = self._direction.value
            end = (
                self._pos[0] + dx * R,
                self._pos[1] + dy * R,
                self._pos[2] - R,
            )
            new_dir = Direction.NEG_Z
        elif bend_type == "up":
            dx, dy, dz = self._direction.value
            end = (
                self._pos[0] + dx * R,
                self._pos[1] + dy * R,
                self._pos[2] + R,
            )
            new_dir = Direction.POS_Z
        elif bend_type == "down_to_horiz":
            # Coming from NEG_Z, going to horizontal
            # Need to know previous horizontal direction - store it
            new_dir = self._prev_horiz_direction if hasattr(self, '_prev_horiz_direction') else Direction.POS_X
            dx, dy, dz = new_dir.value
            end = (
                self._pos[0] + dx * R,
                self._pos[1] + dy * R,
                self._pos[2] - R,
            )
        elif bend_type == "up_to_horiz":
            new_dir = self._prev_horiz_direction if hasattr(self, '_prev_horiz_direction') else Direction.POS_X
            dx, dy, dz = new_dir.value
            end = (
                self._pos[0] + dx * R,
                self._pos[1] + dy * R,
                self._pos[2] + R,
            )

        # Store previous horizontal direction before going vertical
        if self._direction in (Direction.POS_X, Direction.NEG_X, Direction.POS_Y, Direction.NEG_Y):
            self._prev_horiz_direction = self._direction

        seg = RouteSegment(
            seg_type=seg_type,
            start_point=self._pos,
            end_point=end,
            direction_in=self._direction,
            direction_out=new_dir,
            length=arc_length,
            angle=angle,
            turn=bend_type,
            notes=notes,
        )
        self.segments.append(seg)
        self._pos = end
        self._direction = new_dir
        print(f"  Vertical bend ({bend_type}) → heading {new_dir.name}, at ({end[0]:.0f}, {end[1]:.0f}, {end[2]:.0f})")

    def penetration(self, wall_name: str, thickness: float = 200, notes: str = ""):
        """Mark a wall/floor penetration at the current position."""
        seg = RouteSegment(
            seg_type=SegmentType.PENETRATION,
            start_point=self._pos,
            end_point=self._pos,  # zero-length marker
            direction_in=self._direction,
            direction_out=self._direction,
            length=0,
            notes=f"PENETRATION: {wall_name} (thickness={thickness}mm). {notes}",
        )
        self.segments.append(seg)
        self.penetrations.append({
            "position": self._pos,
            "wall": wall_name,
            "thickness": thickness,
            "direction": self._direction,
            "notes": notes,
        })
        print(f"  *** PENETRATION: {wall_name} at ({self._pos[0]:.0f}, {self._pos[1]:.0f}, {self._pos[2]:.0f}) ***")

    def over_obstacle(self, name: str, clearance: float = 300, obstacle_height: float = 0, notes: str = ""):
        """Mark where tray goes OVER an obstacle (e.g., pipe, duct)."""
        self.obstacles.append({
            "position": self._pos,
            "type": "over",
            "name": name,
            "clearance": clearance,
            "obstacle_height": obstacle_height,
            "notes": notes,
        })
        print(f"  *** OVER: {name} (clearance {clearance}mm) ***")

    def under_obstacle(self, name: str, clearance: float = 150, notes: str = ""):
        """Mark where tray goes UNDER an obstacle (e.g., beam, duct)."""
        self.obstacles.append({
            "position": self._pos,
            "type": "under",
            "name": name,
            "clearance": clearance,
            "notes": notes,
        })
        print(f"  *** UNDER: {name} (clearance {clearance}mm) ***")

    def tee(self, branch_direction: str, notes: str = ""):
        """Add a T-junction."""
        seg = RouteSegment(
            seg_type=SegmentType.TEE,
            start_point=self._pos,
            end_point=self._pos,
            direction_in=self._direction,
            direction_out=self._direction,
            length=0,
            turn=branch_direction,
            notes=notes,
        )
        self.segments.append(seg)
        print(f"  T-junction (branch {branch_direction})")

    def end(self):
        """Finalise the route."""
        print(f"\nRoute complete: {self.name}")
        print(f"  Total segments: {len(self.segments)}")
        total_length = sum(s.length for s in self.segments)
        print(f"  Total route length: {total_length:.0f} mm ({total_length/1000:.1f} m)")
        print(f"  Penetrations: {len(self.penetrations)}")
        print(f"  Obstacles: {len(self.obstacles)}")

    # ---- Support Calculation ----

    def calculate_supports(self, default_support: str = "POST_150"):
        """
        Calculate support positions along the route.

        Rules (per AS/NZS 3000 cl. 3.9.5 and manufacturer recommendations):
        - Supports at intervals not exceeding the calculated max span
        - Additional support within 300mm of any direction change
        - Additional support within 300mm of any termination
        - Vertical runs: hold-down clips at max 1500mm intervals
        """
        self.supports = []

        for i, seg in enumerate(self.segments):
            if seg.seg_type == SegmentType.STRAIGHT:
                # Place supports along straight sections
                n_supports = max(2, math.ceil(seg.length / self._support_spacing) + 1)
                spacing = seg.length / (n_supports - 1) if n_supports > 1 else 0

                dx, dy, dz = seg.direction_in.value
                for j in range(n_supports):
                    dist = j * spacing
                    pos = (
                        seg.start_point[0] + dx * dist,
                        seg.start_point[1] + dy * dist,
                        seg.start_point[2] + dz * dist,
                    )
                    self.supports.append(SupportPoint(
                        position=pos,
                        support_type=default_support,
                        segment_index=i,
                        notes=f"Straight section, {spacing:.0f}mm spacing",
                    ))

            elif seg.seg_type == SegmentType.VERTICAL_STRAIGHT:
                # Wall brackets for vertical sections at 1500mm max
                n_supports = max(2, math.ceil(seg.length / 1500) + 1)
                spacing = seg.length / (n_supports - 1) if n_supports > 1 else 0

                dx, dy, dz = seg.direction_in.value
                for j in range(n_supports):
                    dist = j * spacing
                    pos = (
                        seg.start_point[0] + dx * dist,
                        seg.start_point[1] + dy * dist,
                        seg.start_point[2] + dz * dist,
                    )
                    self.supports.append(SupportPoint(
                        position=pos,
                        support_type="CB4-750H",  # wall bracket for vertical
                        segment_index=i,
                        notes="Vertical section, wall bracket",
                    ))

            elif seg.seg_type in (SegmentType.HORIZONTAL_BEND,
                                   SegmentType.VERTICAL_BEND_DOWN,
                                   SegmentType.VERTICAL_BEND_UP,
                                   SegmentType.VERTICAL_BEND_TO_HORIZ):
                # Support within 300mm of bend on each side
                self.supports.append(SupportPoint(
                    position=seg.start_point,
                    support_type=default_support,
                    segment_index=i,
                    notes="Within 300mm of bend (entry side)",
                ))
                self.supports.append(SupportPoint(
                    position=seg.end_point,
                    support_type=default_support,
                    segment_index=i,
                    notes="Within 300mm of bend (exit side)",
                ))

        print(f"\nSupport calculation: {len(self.supports)} support points")
        return self.supports

    # ---- Bill of Materials ----

    def generate_bom(self) -> List[BOMItem]:
        """Generate bill of materials from the route."""
        bom = []

        if not self.tray:
            return bom

        # Count tray lengths needed
        total_straight = sum(s.length for s in self.segments
                           if s.seg_type in (SegmentType.STRAIGHT, SegmentType.VERTICAL_STRAIGHT))
        n_lengths = math.ceil(total_straight / self.tray.standard_length)
        bom.append(BOMItem(
            part_number=f"{self.tray.part_prefix}G",
            description=f"{self.tray.name} straight {self.tray.standard_length}mm (pre-galv)",
            quantity=n_lengths,
            notes=f"Total straight: {total_straight:.0f}mm",
        ))

        # Splices (one per joint between lengths)
        n_splices = max(0, n_lengths - 1)
        bom.append(BOMItem(
            part_number=f"{self.tray.part_prefix}-SPLICE",
            description="Splice plate",
            quantity=n_splices,
        ))

        # Bends
        h_bends = sum(1 for s in self.segments if s.seg_type == SegmentType.HORIZONTAL_BEND)
        if h_bends:
            bom.append(BOMItem(
                part_number=f"{self.tray.part_prefix}-BEND90",
                description=f"90° horizontal bend, R={self.tray.bend_radius}mm",
                quantity=h_bends,
            ))

        # Vertical bends (risers)
        v_bends_down = sum(1 for s in self.segments if s.seg_type == SegmentType.VERTICAL_BEND_DOWN)
        v_bends_up = sum(1 for s in self.segments if s.seg_type == SegmentType.VERTICAL_BEND_UP)
        v_bends_to_h = sum(1 for s in self.segments if s.seg_type == SegmentType.VERTICAL_BEND_TO_HORIZ)

        if v_bends_down + v_bends_up:
            bom.append(BOMItem(
                part_number=f"{self.tray.part_prefix}-RISER-EXT",
                description="90° external riser (horizontal to vertical)",
                quantity=v_bends_down + v_bends_up,
            ))
        if v_bends_to_h:
            bom.append(BOMItem(
                part_number=f"{self.tray.part_prefix}-RISER-INT",
                description="90° internal riser (vertical to horizontal)",
                quantity=v_bends_to_h,
            ))

        # Tees
        tees = sum(1 for s in self.segments if s.seg_type == SegmentType.TEE)
        if tees:
            bom.append(BOMItem(
                part_number=f"{self.tray.part_prefix}-TEE",
                description="T-junction fitting",
                quantity=tees,
            ))

        # Supports
        support_counts = {}
        for sp in self.supports:
            support_counts[sp.support_type] = support_counts.get(sp.support_type, 0) + 1
        for st, count in support_counts.items():
            spec = SUPPORTS.get(st)
            if spec:
                bom.append(BOMItem(
                    part_number=spec.part_number,
                    description=spec.description,
                    quantity=count,
                ))

        # Fire collars for penetrations
        if self.penetrations:
            bom.append(BOMItem(
                part_number="FC-COLLAR",
                description=f"Fire collar / intumescent wrap for {self.tray.width}mm tray penetration",
                quantity=len(self.penetrations),
                notes="Verify fire rating requirement per AS/NZS 3013",
            ))

        return bom

    def print_bom(self):
        """Print formatted bill of materials."""
        bom = self.generate_bom()
        print(f"\n{'='*70}")
        print(f"BILL OF MATERIALS: {self.name}")
        print(f"{'='*70}")
        print(f"{'Part Number':<25} {'Qty':>4} {'Unit':<4} {'Description'}")
        print(f"{'-'*70}")
        for item in bom:
            print(f"{item.part_number:<25} {item.quantity:>4} {item.unit:<4} {item.description}")
            if item.notes:
                print(f"{'':>35} Note: {item.notes}")
        print(f"{'='*70}")

    def print_supports(self):
        """Print support schedule."""
        print(f"\n{'='*70}")
        print(f"SUPPORT SCHEDULE: {self.name}")
        print(f"{'='*70}")
        print(f"{'#':<4} {'X':>8} {'Y':>8} {'Z':>8} {'Type':<15} {'Notes'}")
        print(f"{'-'*70}")
        for i, sp in enumerate(self.supports):
            x, y, z = sp.position
            print(f"{i+1:<4} {x:>8.0f} {y:>8.0f} {z:>8.0f} {sp.support_type:<15} {sp.notes}")
        print(f"{'='*70}")

    def print_penetrations(self):
        """Print penetration schedule."""
        if not self.penetrations:
            print("No penetrations in this route.")
            return
        print(f"\n{'='*70}")
        print(f"PENETRATION SCHEDULE: {self.name}")
        print(f"{'='*70}")
        for i, p in enumerate(self.penetrations):
            x, y, z = p["position"]
            print(f"  {i+1}. {p['wall']}")
            print(f"     Position: ({x:.0f}, {y:.0f}, {z:.0f})")
            print(f"     Wall thickness: {p['thickness']}mm")
            print(f"     Direction: {p['direction'].name}")
            print(f"     Requires: Fire collar, intumescent wrap, or fire-rated pillows")
            print(f"     Standard: AS/NZS 3013 (verify classification)")
            if p["notes"]:
                print(f"     Notes: {p['notes']}")
        print(f"{'='*70}")

    def print_route_summary(self):
        """Print complete route summary with all annotations."""
        print(f"\n{'#'*70}")
        print(f"# CABLE TRAY ROUTE: {self.name}")
        print(f"# Tray: {self.tray.name if self.tray else 'Not set'}")
        print(f"# Cable load: {self.cable_load} kg/m")
        print(f"# Support spacing: {self._support_spacing} mm")
        print(f"{'#'*70}")

        print(f"\n--- ROUTE SEGMENTS ---")
        for i, seg in enumerate(self.segments):
            if seg.seg_type == SegmentType.PENETRATION:
                print(f"\n  [{i}] *** {seg.notes} ***")
            else:
                sx, sy, sz = seg.start_point
                ex, ey, ez = seg.end_point
                print(f"\n  [{i}] {seg.seg_type.value}")
                print(f"      From: ({sx:.0f}, {sy:.0f}, {sz:.0f})")
                print(f"      To:   ({ex:.0f}, {ey:.0f}, {ez:.0f})")
                print(f"      Length: {seg.length:.0f} mm")
                if seg.turn:
                    print(f"      Turn: {seg.turn}")
                if seg.notes:
                    print(f"      Notes: {seg.notes}")

        self.print_penetrations()

        if self.obstacles:
            print(f"\n--- OBSTACLE CROSSINGS ---")
            for obs in self.obstacles:
                x, y, z = obs["position"]
                print(f"  {obs['type'].upper()}: {obs['name']} at ({x:.0f}, {y:.0f}, {z:.0f})")
                print(f"    Clearance: {obs['clearance']}mm")

    # ---- Internal helpers ----

    def _turn_horizontal(self, current: Direction, turn: str, angle: float) -> Direction:
        """Calculate new direction after a horizontal turn."""
        # Only handles 90° for now
        turns_left = {
            Direction.POS_X: Direction.POS_Y,
            Direction.POS_Y: Direction.NEG_X,
            Direction.NEG_X: Direction.NEG_Y,
            Direction.NEG_Y: Direction.POS_X,
        }
        turns_right = {
            Direction.POS_X: Direction.NEG_Y,
            Direction.NEG_Y: Direction.NEG_X,
            Direction.NEG_X: Direction.POS_Y,
            Direction.POS_Y: Direction.POS_X,
        }

        if turn == "left":
            return turns_left.get(current, current)
        else:
            return turns_right.get(current, current)

    def _calc_bend_endpoint(self, start, dir_in, dir_out, radius):
        """Calculate the endpoint of a 90° bend."""
        R = radius + (self.tray.overall_width / 2 if self.tray else 160)

        dx_in, dy_in, _ = dir_in.value
        dx_out, dy_out, _ = dir_out.value

        # The endpoint is R along the input direction + R along the output direction from start
        end = (
            start[0] + dx_in * R + dx_out * R,
            start[1] + dy_in * R + dy_out * R,
            start[2],  # horizontal bend, Z unchanged
        )
        return end


# ============================================================
# FREECAD GEOMETRY BUILDER (Cable Ladder Style)
# ============================================================

class FreeCADBuilder:
    """
    Generates FreeCAD 3D geometry from a CableTrayRoute.

    Creates cable ladder geometry: two parallel side rails with cross-rungs,
    matching Ezystrut NEMA3 cable ladder product appearance.
    """

    # Ladder geometry constants (visual overrides for clarity at typical viewing distance)
    RAIL_T = 15.0      # rail thickness (exaggerated from 1.6mm for visibility)
    RUNG_DIA = 12.0    # rung diameter
    RUNG_SPACING = 250.0  # rung centre-to-centre

    def __init__(self, route: CableTrayRoute):
        self.route = route
        self.doc = None

    def build(self, doc_name: str = None):
        """Build the FreeCAD model."""
        try:
            import FreeCAD
            import Part
        except ImportError:
            print("ERROR: Must be run inside FreeCAD")
            return

        if doc_name is None:
            doc_name = self.route.name.replace(" ", "_")

        self.doc = FreeCAD.newDocument(doc_name)
        tray = self.route.tray

        W = tray.width          # internal width between rails
        H = tray.side_height    # rail height
        R = tray.bend_radius

        tray_color = (0.72, 0.72, 0.70, 1.0)
        bend_color = (0.72, 0.72, 0.70, 1.0)
        support_color = (0.55, 0.55, 0.52, 1.0)

        for i, seg in enumerate(self.route.segments):
            if seg.seg_type == SegmentType.STRAIGHT:
                self._build_straight(i, seg, W, H, tray_color)
            elif seg.seg_type == SegmentType.VERTICAL_STRAIGHT:
                self._build_vertical_straight(i, seg, W, H, tray_color)
            elif seg.seg_type == SegmentType.HORIZONTAL_BEND:
                self._build_horizontal_bend(i, seg, W, H, R, bend_color)
            elif seg.seg_type in (SegmentType.VERTICAL_BEND_DOWN,
                                   SegmentType.VERTICAL_BEND_UP,
                                   SegmentType.VERTICAL_BEND_TO_HORIZ):
                self._build_vertical_bend(i, seg, W, H, R, bend_color)

        # Build supports
        for i, sp in enumerate(self.route.supports):
            self._build_support(i, sp, support_color)

        self.doc.recompute()
        print(f"\nFreeCAD model built: {doc_name} ({len(self.doc.Objects)} objects)")
        return self.doc

    def _make_ladder_straight(self, length, W, H, direction):
        """
        Create a straight cable ladder section (two rails + rungs).

        The ladder is built along the local X axis, then rotated/placed by caller.
        Returns a compound shape.

        Args:
            length: section length in mm
            W: internal width between rails
            H: rail height
            direction: Direction enum for the segment
        """
        import FreeCAD
        import Part

        T = self.RAIL_T
        shapes = []

        # Two side rails along X
        shapes.append(Part.makeBox(length, T, H))
        shapes.append(Part.makeBox(length, T, H, FreeCAD.Vector(0, W + T, 0)))

        # Cross-rungs (cylinders along Y)
        n_rungs = max(1, int(length / self.RUNG_SPACING))
        actual_spacing = length / (n_rungs + 1)
        for i in range(n_rungs):
            x = actual_spacing * (i + 1)
            shapes.append(Part.makeCylinder(
                self.RUNG_DIA / 2, W,
                FreeCAD.Vector(x, T, H / 2),
                FreeCAD.Vector(0, 1, 0)
            ))

        return Part.makeCompound(shapes)

    def _build_straight(self, idx, seg, W, H, color):
        """Build a straight ladder tray section."""
        import FreeCAD
        import Part

        dx, dy, dz = seg.direction_in.value
        length = seg.length
        sx, sy, sz = seg.start_point

        ladder = self._make_ladder_straight(length, W, H, seg.direction_in)

        obj = self.doc.addObject("Part::Feature", f"Tray_{idx:02d}_straight")
        obj.Shape = ladder

        # Rotate from local-X to actual travel direction, then position
        if dx == 1:    # POS_X: local X = world X, no rotation
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)
        elif dx == -1: # NEG_X: rotate 180° around Z
            ladder.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 180)
            obj.Shape = ladder
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)
        elif dy == 1:  # POS_Y: rotate 90° CCW around Z
            ladder.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
            obj.Shape = ladder
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)
        elif dy == -1: # NEG_Y: rotate 270° around Z
            ladder.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 270)
            obj.Shape = ladder
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)

        obj.ViewObject.ShapeColor = color

    def _build_vertical_straight(self, idx, seg, W, H, color):
        """Build a vertical straight ladder tray section."""
        import FreeCAD
        import Part

        T = self.RAIL_T
        length = seg.length
        sx, sy, sz = seg.start_point
        dz = seg.direction_in.value[2]  # +1 or -1

        shapes = []
        # Two side rails along Z (vertical)
        shapes.append(Part.makeBox(T, T, length, FreeCAD.Vector(0, 0, 0)))
        shapes.append(Part.makeBox(T, T, length, FreeCAD.Vector(0, W + T, 0)))

        # Cross-rungs (horizontal, along Y)
        n_rungs = max(1, int(length / self.RUNG_SPACING))
        actual_spacing = length / (n_rungs + 1)
        for i in range(n_rungs):
            z = actual_spacing * (i + 1)
            shapes.append(Part.makeCylinder(
                self.RUNG_DIA / 2, W,
                FreeCAD.Vector(T / 2, T, z),
                FreeCAD.Vector(0, 1, 0)
            ))

        ladder = Part.makeCompound(shapes)
        obj = self.doc.addObject("Part::Feature", f"Tray_{idx:02d}_vertical")
        obj.Shape = ladder

        if dz == -1:
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz - length)
        else:
            obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)

        obj.ViewObject.ShapeColor = color

    def _build_horizontal_bend(self, idx, seg, W, H, R, color):
        """Build a horizontal 90° bend with curved rails and radial rungs."""
        import FreeCAD
        import Part

        T = self.RAIL_T

        shapes = []

        # Inner rail arc (annular sector, axis = +Z)
        r_in_i = R
        r_in_o = R + T
        cyl_out = Part.makeCylinder(r_in_o, H, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
        cyl_in = Part.makeCylinder(r_in_i, H, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
        shapes.append(cyl_out.cut(cyl_in))

        # Outer rail arc
        r_out_i = R + T + W
        r_out_o = R + 2 * T + W
        cyl_out2 = Part.makeCylinder(r_out_o, H, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
        cyl_in2 = Part.makeCylinder(r_out_i, H, FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), 90)
        shapes.append(cyl_out2.cut(cyl_in2))

        # Radial rungs
        n_rungs = 4
        for i in range(n_rungs):
            angle = (i + 0.5) * (90.0 / n_rungs)
            angle_rad = math.radians(angle)
            # Rung from inner rail outer edge to outer rail inner edge
            x_start = (R + T) * math.cos(angle_rad)
            y_start = (R + T) * math.sin(angle_rad)
            # Direction: radial outward
            dx = math.cos(angle_rad)
            dy = math.sin(angle_rad)
            shapes.append(Part.makeCylinder(
                self.RUNG_DIA / 2, W,
                FreeCAD.Vector(x_start, y_start, H / 2),
                FreeCAD.Vector(dx, dy, 0)
            ))

        bend_shape = Part.makeCompound(shapes)

        # The raw bend: arc from 0° to 90° in XY plane.
        # At 0°: tray runs in +Y direction (tangent = +Y).
        # At 90°: tray runs in -X direction (tangent = -X).
        # So raw bend = entering from +X direction, exiting toward +Y = LEFT turn when entering POS_X.

        dir_in = seg.direction_in
        turn = seg.turn

        if turn == "right":
            # Mirror across X axis to flip chirality
            bend_shape = bend_shape.mirror(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0))

        # Rotation to align entry direction
        rotation_map_left = {
            Direction.POS_X: 0,
            Direction.POS_Y: 90,
            Direction.NEG_X: 180,
            Direction.NEG_Y: 270,
        }
        rotation_map_right = {
            Direction.POS_X: 270,
            Direction.POS_Y: 0,
            Direction.NEG_X: 90,
            Direction.NEG_Y: 180,
        }

        if turn == "left":
            rot_angle = rotation_map_left.get(dir_in, 0)
        else:
            rot_angle = rotation_map_right.get(dir_in, 0)

        bend_shape.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 0, 1), rot_angle)

        obj = self.doc.addObject("Part::Feature", f"Tray_{idx:02d}_bend_{turn}")
        obj.Shape = bend_shape

        sx, sy, sz = seg.start_point
        obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)
        obj.ViewObject.ShapeColor = color

    def _build_vertical_bend(self, idx, seg, W, H, R, color):
        """Build a vertical 90° bend (riser) with curved rails in XZ plane."""
        import FreeCAD
        import Part

        T = self.RAIL_T
        shapes = []

        # Two curved rails in XZ plane (arc axis = Y)
        for rail_offset in [0, W + T]:
            r_in = R
            r_out = R + T
            cyl_out = Part.makeCylinder(r_out, T, FreeCAD.Vector(0, rail_offset, 0), FreeCAD.Vector(0, 1, 0), 90)
            cyl_in = Part.makeCylinder(r_in, T, FreeCAD.Vector(0, rail_offset, 0), FreeCAD.Vector(0, 1, 0), 90)
            shapes.append(cyl_out.cut(cyl_in))

        # Radial rungs in the XZ plane
        n_rungs = 3
        for i in range(n_rungs):
            angle = (i + 0.5) * (90.0 / n_rungs)
            angle_rad = math.radians(angle)
            x = (R + T / 2) * math.cos(angle_rad)
            z = (R + T / 2) * math.sin(angle_rad)
            shapes.append(Part.makeCylinder(
                self.RUNG_DIA / 2, W,
                FreeCAD.Vector(x, T, z),
                FreeCAD.Vector(0, 1, 0)
            ))

        bend_shape = Part.makeCompound(shapes)

        # Position based on bend type
        sx, sy, sz = seg.start_point
        dir_in = seg.direction_in
        bend_type = seg.turn

        if bend_type == "down":
            # Rotate so entry is horizontal, exit is downward
            bend_shape.rotate(FreeCAD.Vector(0, 0, 0), FreeCAD.Vector(0, 1, 0), -90)

        obj = self.doc.addObject("Part::Feature", f"Tray_{idx:02d}_riser")
        obj.Shape = bend_shape
        obj.Placement.Base = FreeCAD.Vector(sx, sy, sz)
        obj.ViewObject.ShapeColor = color

    def _build_support(self, idx, sp, color):
        """Build a support post/bracket."""
        import FreeCAD
        import Part

        x, y, z = sp.position
        spec = SUPPORTS.get(sp.support_type)
        if not spec:
            return

        if spec.type == "post":
            # Post from ground to tray level
            post_size = 150 if "150" in spec.part_number else 100
            half = post_size / 2
            post_height = z  # from ground to tray base

            if post_height <= 0:
                return

            # Post (SHS)
            post = Part.makeBox(post_size, post_size, post_height,
                               FreeCAD.Vector(x - half, y - half, 0))
            # Base plate
            base = Part.makeBox(400, 400, 10,
                               FreeCAD.Vector(x - 200, y - 200, -10))

            compound = Part.makeCompound([post, base])
            obj = self.doc.addObject("Part::Feature", f"Support_{idx:03d}_post")
            obj.Shape = compound
            obj.ViewObject.ShapeColor = color

        elif spec.type == "cantilever":
            # CB4-750H style cantilever bracket
            arm_length = 300
            arm = Part.makeBox(arm_length, 50, 8, FreeCAD.Vector(x, y - 25, z - 8))
            obj = self.doc.addObject("Part::Feature", f"Support_{idx:03d}_bracket")
            obj.Shape = arm
            obj.ViewObject.ShapeColor = color


# ============================================================
# CONVENIENCE FUNCTION
# ============================================================

def example_route():
    """
    Example: Route cable tray from outdoor substation to data hall MSB.
    Based on AU01-2 George Town reference design.
    """
    route = CableTrayRoute("TX1_to_MSB1", cable_load_kg_per_m=30)
    route.set_tray(NEMA3_600)

    # Start at transformer TX1 cable box, 3m height on outdoor support posts
    route.start(x=0, y=0, z=3000, direction=Direction.POS_X)

    # Run along outdoor posts toward data hall (6m, two standard lengths)
    route.straight(6000, notes="Outdoor run on 150x150 posts, peaked cover required")

    # Turn left toward building
    route.horizontal_bend("left", 90)

    # Approach building wall
    route.straight(3000, notes="Approaching data hall west wall")

    # Penetrate building wall
    route.penetration("Data Hall West Wall", thickness=200,
                     notes="Fire-rated penetration required. Coordinate with structural.")

    # Short run inside at ceiling level
    route.straight(2000, notes="Internal ceiling run, cantilever brackets off wall")

    # Turn right toward MSB location
    route.horizontal_bend("right", 90)

    # Run to above MSB
    route.straight(4000, notes="Internal run to MSB location")

    # Vertical riser down to MSB top entry
    route.vertical_bend("down", 90, notes="External riser - top entry to MSB")

    # Drop to MSB entry height
    route.straight_vertical(1500, "down", notes="Vertical drop to MSB top entry")

    # End at MSB
    route.end()

    # Calculate supports and BOM
    route.calculate_supports(default_support="POST_150")
    route.print_route_summary()
    route.print_bom()
    route.print_supports()

    return route


if __name__ == "__main__":
    route = example_route()
