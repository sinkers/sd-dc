"""
Closed-loop cooling system model for FreeCAD.
Components:
- 1x 2.5MW Dry Cooler (large outdoor unit with fan array)
- 3x Pumps in parallel (on supply manifold)
- 3x Vertiv XDU 1350 CDUs (rack-mounted cooling distribution units)
- Supply and return piping with headers/manifolds

Coordinate system: X = width, Y = depth, Z = height (mm)
"""

import FreeCAD
import Part
import math

# =============================================================================
# DIMENSIONS (all in mm)
# =============================================================================

# Dry Cooler - 2.5MW class (e.g., similar to BAC VXT series)
# Typical: ~12m long, ~2.5m wide, ~3.5m tall
DC_LENGTH = 12000
DC_WIDTH = 2500
DC_HEIGHT = 3500
DC_FAN_DIAMETER = 1800
DC_FAN_COUNT = 6  # 6 fans in a row

# Vertiv XDU 1350 CDU
# Approx dimensions: 600mm W x 1070mm D x 1997mm H (42U rack)
XDU_WIDTH = 600
XDU_DEPTH = 1070
XDU_HEIGHT = 1997
XDU_COUNT = 3
XDU_SPACING = 2000  # center-to-center

# Pumps - inline centrifugal, ~500mm cube envelope
PUMP_WIDTH = 500
PUMP_DEPTH = 700
PUMP_HEIGHT = 500
PUMP_COUNT = 3
PUMP_SPACING = 1500

# Piping
MAIN_HEADER_DIA = 300  # 300mm / DN300 main headers
BRANCH_DIA = 150       # 150mm / DN150 branches to each unit
PIPE_WALL = 6          # wall thickness

# Layout spacing
DC_TO_PUMP_DIST = 5000    # distance from dry cooler to pump rack
PUMP_TO_XDU_DIST = 8000   # distance from pumps to XDU row


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================

def make_box(name, length, width, height, position=(0, 0, 0), doc=None):
    """Create a box shape and add to document."""
    obj = doc.addObject("Part::Box", name)
    obj.Length = length
    obj.Width = width
    obj.Height = height
    obj.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*position),
        FreeCAD.Rotation(0, 0, 0)
    )
    return obj


def make_cylinder(name, radius, height, position=(0, 0, 0), direction=(0, 0, 1), doc=None):
    """Create a cylinder shape."""
    obj = doc.addObject("Part::Cylinder", name)
    obj.Radius = radius
    obj.Height = height
    obj.Placement = FreeCAD.Placement(
        FreeCAD.Vector(*position),
        FreeCAD.Rotation(FreeCAD.Vector(*direction), 0) if direction != (0, 0, 1)
        else FreeCAD.Rotation(0, 0, 0)
    )
    return obj


def make_pipe(name, start, end, outer_dia, doc=None):
    """Create a pipe (hollow cylinder) between two points."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dz = end[2] - start[2]
    length = math.sqrt(dx*dx + dy*dy + dz*dz)

    # Create outer cylinder
    wire = Part.makeWire([
        Part.makeLine(FreeCAD.Vector(*start), FreeCAD.Vector(*end))
    ])
    pipe = Part.Wire(wire).makePipe(Part.makeCircle(outer_dia / 2))

    obj = doc.addObject("Part::Feature", name)
    obj.Shape = pipe
    return obj


def make_pipe_simple(name, start, end, diameter, doc=None):
    """Create a solid pipe (cylinder) between two points."""
    start_v = FreeCAD.Vector(*start)
    end_v = FreeCAD.Vector(*end)
    direction = end_v - start_v
    length = direction.Length

    # Create cylinder along the direction
    cylinder = Part.makeCylinder(diameter / 2, length, start_v, direction)
    obj = doc.addObject("Part::Feature", name)
    obj.Shape = cylinder
    return obj


# =============================================================================
# MODEL CREATION
# =============================================================================

def create_cooling_system():
    """Create the full closed-loop cooling system model."""

    # Create document
    if FreeCAD.ActiveDocument:
        FreeCAD.closeDocument(FreeCAD.ActiveDocument.Name)
    doc = FreeCAD.newDocument("CoolingSystem")

    # =========================================================================
    # DRY COOLER
    # =========================================================================
    # Position at origin, represents outdoor equipment
    dc_x = -DC_LENGTH / 2
    dc_y = 0
    dc_z = 0

    # Main body (coil housing)
    make_box("DryCooler_Body", DC_LENGTH, DC_WIDTH, DC_HEIGHT * 0.7,
             position=(dc_x, dc_y, dc_z), doc=doc)

    # Fan shroud section on top
    make_box("DryCooler_FanDeck", DC_LENGTH, DC_WIDTH, DC_HEIGHT * 0.3,
             position=(dc_x, dc_y, dc_z + DC_HEIGHT * 0.7), doc=doc)

    # Individual fan cylinders
    fan_spacing = DC_LENGTH / DC_FAN_COUNT
    for i in range(DC_FAN_COUNT):
        fan_x = dc_x + fan_spacing * (i + 0.5)
        fan_y = dc_y + DC_WIDTH / 2
        fan_z = dc_z + DC_HEIGHT * 0.85
        cyl = doc.addObject("Part::Cylinder", f"DryCooler_Fan_{i+1}")
        cyl.Radius = DC_FAN_DIAMETER / 2
        cyl.Height = 200
        cyl.Placement = FreeCAD.Placement(
            FreeCAD.Vector(fan_x, fan_y, fan_z),
            FreeCAD.Rotation(0, 0, 0)
        )

    # Connection stubs on dry cooler (supply out, return in)
    dc_supply_out = (dc_x + DC_LENGTH * 0.25, dc_y + DC_WIDTH, dc_z + DC_HEIGHT * 0.3)
    dc_return_in = (dc_x + DC_LENGTH * 0.75, dc_y + DC_WIDTH, dc_z + DC_HEIGHT * 0.3)

    # =========================================================================
    # PUMPS (3 in parallel)
    # =========================================================================
    pump_row_y = dc_y + DC_WIDTH + DC_TO_PUMP_DIST
    pump_row_x_start = -((PUMP_COUNT - 1) * PUMP_SPACING) / 2

    pump_positions = []
    for i in range(PUMP_COUNT):
        px = pump_row_x_start + i * PUMP_SPACING
        py = pump_row_y
        pz = 500  # elevated on base

        # Pump body (cylinder)
        pump = doc.addObject("Part::Cylinder", f"Pump_{i+1}_Body")
        pump.Radius = PUMP_WIDTH / 2
        pump.Height = PUMP_DEPTH
        pump.Placement = FreeCAD.Placement(
            FreeCAD.Vector(px, py, pz),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )

        # Motor housing
        motor = doc.addObject("Part::Cylinder", f"Pump_{i+1}_Motor")
        motor.Radius = PUMP_WIDTH * 0.35
        motor.Height = 400
        motor.Placement = FreeCAD.Placement(
            FreeCAD.Vector(px, py + PUMP_DEPTH, pz),
            FreeCAD.Rotation(FreeCAD.Vector(1, 0, 0), 90)
        )

        pump_positions.append((px, py, pz))

    # =========================================================================
    # VERTIV XDU 1350 CDUs (3 units)
    # =========================================================================
    xdu_row_y = pump_row_y + PUMP_TO_XDU_DIST
    xdu_row_x_start = -((XDU_COUNT - 1) * XDU_SPACING) / 2

    xdu_positions = []
    for i in range(XDU_COUNT):
        xx = xdu_row_x_start + i * XDU_SPACING - XDU_WIDTH / 2
        xy = xdu_row_y
        xz = 0

        # Main cabinet
        make_box(f"XDU1350_{i+1}_Cabinet", XDU_WIDTH, XDU_DEPTH, XDU_HEIGHT,
                 position=(xx, xy, xz), doc=doc)

        # Top section (controls/display)
        make_box(f"XDU1350_{i+1}_Top", XDU_WIDTH * 0.8, XDU_DEPTH * 0.3, 100,
                 position=(xx + XDU_WIDTH * 0.1, xy, xz + XDU_HEIGHT), doc=doc)

        xdu_positions.append((xx + XDU_WIDTH / 2, xy, xz))

    # =========================================================================
    # PIPING - Supply side (DC → Pumps → XDUs)
    # =========================================================================

    # Supply header from dry cooler
    supply_header_y = pump_row_y - 500
    supply_header_start = (pump_row_x_start - 1000, supply_header_y, 800)
    supply_header_end = (pump_row_x_start + (PUMP_COUNT - 1) * PUMP_SPACING + 1000, supply_header_y, 800)
    make_pipe_simple("Supply_Header", supply_header_start, supply_header_end,
                     MAIN_HEADER_DIA, doc=doc)

    # Pipe from DC to supply header
    make_pipe_simple("Supply_DC_to_Header",
                     dc_supply_out,
                     (supply_header_start[0] + 500, supply_header_y, 800),
                     MAIN_HEADER_DIA, doc=doc)

    # Branch pipes from supply header to each pump
    for i, (px, py, pz) in enumerate(pump_positions):
        make_pipe_simple(f"Supply_Branch_Pump_{i+1}",
                         (px, supply_header_y, 800),
                         (px, py - 100, pz),
                         BRANCH_DIA, doc=doc)

    # Discharge header after pumps
    discharge_header_y = pump_row_y + PUMP_DEPTH + 500
    discharge_header_start = (pump_row_x_start - 1000, discharge_header_y, 800)
    discharge_header_end = (pump_row_x_start + (PUMP_COUNT - 1) * PUMP_SPACING + 1000, discharge_header_y, 800)
    make_pipe_simple("Discharge_Header", discharge_header_start, discharge_header_end,
                     MAIN_HEADER_DIA, doc=doc)

    # Branch pipes from each pump to discharge header
    for i, (px, py, pz) in enumerate(pump_positions):
        make_pipe_simple(f"Discharge_Branch_Pump_{i+1}",
                         (px, py + PUMP_DEPTH + 100, pz),
                         (px, discharge_header_y, 800),
                         BRANCH_DIA, doc=doc)

    # Supply to XDU header
    xdu_supply_header_y = xdu_row_y - 500
    xdu_supply_start = (xdu_row_x_start - 1000, xdu_supply_header_y, 800)
    xdu_supply_end = (xdu_row_x_start + (XDU_COUNT - 1) * XDU_SPACING + 1000, xdu_supply_header_y, 800)
    make_pipe_simple("XDU_Supply_Header", xdu_supply_start, xdu_supply_end,
                     MAIN_HEADER_DIA, doc=doc)

    # Connect discharge header to XDU supply header
    make_pipe_simple("Supply_Discharge_to_XDU",
                     ((discharge_header_start[0] + discharge_header_end[0]) / 2, discharge_header_y, 800),
                     ((xdu_supply_start[0] + xdu_supply_end[0]) / 2, xdu_supply_header_y, 800),
                     MAIN_HEADER_DIA, doc=doc)

    # Branch pipes from XDU supply header to each XDU
    for i, (xx, xy, xz) in enumerate(xdu_positions):
        make_pipe_simple(f"Supply_Branch_XDU_{i+1}",
                         (xx, xdu_supply_header_y, 800),
                         (xx, xy, XDU_HEIGHT * 0.7),
                         BRANCH_DIA, doc=doc)

    # =========================================================================
    # PIPING - Return side (XDUs → DC)
    # =========================================================================

    # Return header after XDUs
    xdu_return_header_y = xdu_row_y + XDU_DEPTH + 500
    xdu_return_start = (xdu_row_x_start - 1000, xdu_return_header_y, 500)
    xdu_return_end = (xdu_row_x_start + (XDU_COUNT - 1) * XDU_SPACING + 1000, xdu_return_header_y, 500)
    make_pipe_simple("XDU_Return_Header", xdu_return_start, xdu_return_end,
                     MAIN_HEADER_DIA, doc=doc)

    # Branch pipes from each XDU to return header
    for i, (xx, xy, xz) in enumerate(xdu_positions):
        make_pipe_simple(f"Return_Branch_XDU_{i+1}",
                         (xx, xy + XDU_DEPTH, XDU_HEIGHT * 0.3),
                         (xx, xdu_return_header_y, 500),
                         BRANCH_DIA, doc=doc)

    # Return pipe back to dry cooler
    make_pipe_simple("Return_to_DC",
                     ((xdu_return_start[0] + xdu_return_end[0]) / 2, xdu_return_header_y, 500),
                     dc_return_in,
                     MAIN_HEADER_DIA, doc=doc)

    # =========================================================================
    # Recompute and save
    # =========================================================================
    doc.recompute()
    print(f"Cooling system model created: {len(doc.Objects)} objects")
    print("Components:")
    print(f"  - 1x 2.5MW Dry Cooler ({DC_LENGTH}mm x {DC_WIDTH}mm x {DC_HEIGHT}mm)")
    print(f"  - {PUMP_COUNT}x Pumps in parallel")
    print(f"  - {XDU_COUNT}x Vertiv XDU 1350 CDUs")
    print(f"  - Supply/Return piping (DN{MAIN_HEADER_DIA} headers, DN{BRANCH_DIA} branches)")

    return doc


# Run if executed directly
if __name__ == "__main__" or True:
    result = create_cooling_system()
