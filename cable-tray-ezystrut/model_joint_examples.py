"""
Cable Tray Joint Examples - Every Join Type for FreeCAD
=======================================================

Generates a gallery of every cable tray joint type, correctly modelled
with proper connection hardware (splices, radius plates, taper fits).

Based on Ezystrut ET5, CT, and NEMA3 systems.
Reference: JOINING_RULES.md

Usage in FreeCAD:
    exec(open('/Users/andrewsinclair/workspace/sd-dc/cable-tray-ezystrut/model_joint_examples.py').read())
    build_all_joints()

Coordinate system: X = run direction, Y = lateral, Z = height (mm)
"""

import os

# FreeCAD's exec() context has no __file__, so fall back to the install path.
_THIS_DIR = (os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir()
             else '/Users/andrewsinclair/workspace/sd-dc/cable-tray-ezystrut')
import math

try:
    import FreeCAD
    import Part
    HAS_FREECAD = True
except ImportError:
    HAS_FREECAD = False
    print("[joints] FreeCAD not available")


# =============================================================================
# TRAY PROFILE DIMENSIONS
# =============================================================================

# ET5 Cable Tray (primary system for data centres)
ET5_WIDTH = 600          # mm cable laying width
ET5_OVERALL = 621        # mm including flanges
ET5_SIDE_HEIGHT = 85     # mm side rail height
ET5_DEPTH = 78           # mm cable laying depth
ET5_THICKNESS = 1.6      # mm sheet steel
ET5_LENGTH = 3000        # mm standard length
ET5_FLANGE = 10.5        # mm top return flange

# NEMA3 Cable Ladder
NEMA3_WIDTH = 600
NEMA3_OVERALL = 660
NEMA3_RAIL_HEIGHT = 130
NEMA3_RAIL_WIDTH = 30
NEMA3_RUNG_DIA = 12
NEMA3_RUNG_SPACING = 300
NEMA3_LENGTH = 6000

# CT Perforated Tray
CT_WIDTH = 300
CT_SIDE_HEIGHT = 20
CT_THICKNESS = 1.0
CT_LENGTH = 2400
CT_FITTING_RADIUS = 150  # ALL CT fittings use 150mm radius

# Splice dimensions
SPLICE_LENGTH = 150      # mm overlap per side
SPLICE_THICKNESS = 3     # mm
SPLICE_GAP = 5           # mm gap between tray ends at joint

# Colours
COL_TRAY = (0.75, 0.75, 0.75)       # light grey - galvanised steel
COL_SPLICE = (0.85, 0.85, 0.2)      # yellow - highlight hardware
COL_RADIUS_PLATE = (0.2, 0.7, 0.2)  # green - radius plate
COL_TX_BRACKET = (0.2, 0.5, 0.85)   # blue - tee/cross bracket
COL_RISER_LINK = (0.85, 0.4, 0.2)   # orange - riser link
COL_CT_FITTING = (0.6, 0.6, 0.65)   # slightly different grey for CT fittings


# =============================================================================
# PRIMITIVE BUILDERS
# =============================================================================

def make_et5_section(name, length, position, direction=(1, 0, 0), doc=None):
    """
    Create an ET5 cable tray section (U-channel profile extruded along direction).
    Profile: flat base + two side walls with return flanges.
    """
    t = ET5_THICKNESS
    w = ET5_WIDTH
    h = ET5_SIDE_HEIGHT
    f = ET5_FLANGE

    # Build profile as a wire in YZ plane (base at Z=0, sides go UP)
    # Left wall outer → top flange → inner wall → base → right inner → top flange → right outer
    pts = [
        FreeCAD.Vector(0, -w/2 - t, 0),          # left wall bottom outer
        FreeCAD.Vector(0, -w/2 - t, h),           # left wall top outer
        FreeCAD.Vector(0, -w/2 - t + f, h),       # left flange end
        FreeCAD.Vector(0, -w/2 - t + f, h - t),   # left flange inner
        FreeCAD.Vector(0, -w/2, h - t),            # left wall top inner
        FreeCAD.Vector(0, -w/2, t),                # left wall bottom inner
        FreeCAD.Vector(0, w/2, t),                 # right wall bottom inner
        FreeCAD.Vector(0, w/2, h - t),             # right wall top inner
        FreeCAD.Vector(0, w/2 + t - f, h - t),     # right flange inner
        FreeCAD.Vector(0, w/2 + t - f, h),         # right flange end
        FreeCAD.Vector(0, w/2 + t, h),             # right wall top outer
        FreeCAD.Vector(0, w/2 + t, 0),             # right wall bottom outer
        FreeCAD.Vector(0, -w/2 - t, 0),            # close
    ]

    edges = [Part.makeLine(pts[i], pts[i+1]) for i in range(len(pts)-1)]
    profile = Part.Wire(edges)
    face = Part.Face(profile)

    # Extrude along direction
    dir_vec = FreeCAD.Vector(*direction).normalize() * length
    shape = face.extrude(dir_vec)

    # Position
    shape.translate(FreeCAD.Vector(*position))

    obj = doc.addObject("Part::Feature", name)
    obj.Shape = shape
    obj.ViewObject.ShapeColor = COL_TRAY
    return obj


def make_nema3_section(name, length, position, direction=(1, 0, 0), doc=None):
    """
    Create a NEMA3 cable ladder section (two C-channel rails + rungs).
    """
    rw = NEMA3_RAIL_WIDTH
    rh = NEMA3_RAIL_HEIGHT
    w = NEMA3_WIDTH
    pos = FreeCAD.Vector(*position)
    dir_vec = FreeCAD.Vector(*direction).normalize()

    group = doc.addObject("App::DocumentObjectGroup", name)

    # Left rail (C-channel approximated as box)
    left_rail = Part.makeBox(length, rw, rh,
                             pos + FreeCAD.Vector(0, -w/2 - rw, 0))
    obj_l = doc.addObject("Part::Feature", f"{name}_Rail_L")
    obj_l.Shape = left_rail
    obj_l.ViewObject.ShapeColor = COL_TRAY
    group.addObject(obj_l)

    # Right rail
    right_rail = Part.makeBox(length, rw, rh,
                              pos + FreeCAD.Vector(0, w/2, 0))
    obj_r = doc.addObject("Part::Feature", f"{name}_Rail_R")
    obj_r.Shape = right_rail
    obj_r.ViewObject.ShapeColor = COL_TRAY
    group.addObject(obj_r)

    # Rungs
    n_rungs = int(length / NEMA3_RUNG_SPACING) + 1
    for i in range(n_rungs):
        rx = i * NEMA3_RUNG_SPACING
        rung_start = pos + FreeCAD.Vector(rx, -w/2, rh/2)
        rung = Part.makeCylinder(NEMA3_RUNG_DIA/2, w + 2*rw,
                                 rung_start, FreeCAD.Vector(0, 1, 0))
        obj = doc.addObject("Part::Feature", f"{name}_Rung_{i}")
        obj.Shape = rung
        obj.ViewObject.ShapeColor = (0.6, 0.6, 0.6)
        group.addObject(obj)

    return group


def make_splice_plates(name, position, tray_height, tray_width, doc=None):
    """
    Create splice plates (2 per joint, one each side) highlighted in yellow.
    """
    pos = FreeCAD.Vector(*position)
    hw = tray_width / 2

    group = doc.addObject("App::DocumentObjectGroup", name)

    # Left splice plate
    left = Part.makeBox(SPLICE_LENGTH * 2, SPLICE_THICKNESS, tray_height * 0.8,
                        pos + FreeCAD.Vector(-SPLICE_LENGTH, -hw - ET5_THICKNESS - SPLICE_THICKNESS, tray_height * 0.1))
    obj_l = doc.addObject("Part::Feature", f"{name}_L")
    obj_l.Shape = left
    obj_l.ViewObject.ShapeColor = COL_SPLICE
    group.addObject(obj_l)

    # Right splice plate
    right = Part.makeBox(SPLICE_LENGTH * 2, SPLICE_THICKNESS, tray_height * 0.8,
                         pos + FreeCAD.Vector(-SPLICE_LENGTH, hw + ET5_THICKNESS, tray_height * 0.1))
    obj_r = doc.addObject("Part::Feature", f"{name}_R")
    obj_r.Shape = right
    obj_r.ViewObject.ShapeColor = COL_SPLICE
    group.addObject(obj_r)

    return group


def make_radius_plate(name, position, radius, angle_deg, tray_width, doc=None):
    """
    Create a radius plate (curved plate under the tray base at a bend).
    Shown in green.
    """
    pos = FreeCAD.Vector(*position)
    angle_rad = math.radians(angle_deg)

    # Radius plate is a curved sheet under the base
    # Create arc and extrude across width
    arc_inner = Part.makeCircle(radius, pos, FreeCAD.Vector(0, 0, 1),
                                0, angle_deg)
    arc_outer = Part.makeCircle(radius + tray_width + 2*ET5_THICKNESS, pos,
                                FreeCAD.Vector(0, 0, 1), 0, angle_deg)

    # Simple box approximation for the plate
    plate_length = radius * angle_rad
    plate = Part.makeBox(plate_length, tray_width + 2*ET5_THICKNESS, SPLICE_THICKNESS,
                         pos + FreeCAD.Vector(0, -tray_width/2 - ET5_THICKNESS, -SPLICE_THICKNESS))

    obj = doc.addObject("Part::Feature", name)
    obj.Shape = plate
    obj.ViewObject.ShapeColor = COL_RADIUS_PLATE
    obj.ViewObject.Transparency = 30
    return obj


# =============================================================================
# JOINT TYPE BUILDERS
# =============================================================================

def joint_01_straight_splice(doc, origin=(0, 0, 0)):
    """
    Joint 1: Straight-to-Straight Splice
    Two ET5 tray sections joined end-to-end with splice plates.
    """
    ox, oy, oz = origin
    label = doc.addObject("App::Annotation", "Label_J1")
    label.LabelText = ["JOINT 1: Straight Splice (ET5S)"]
    label.Position = FreeCAD.Vector(ox + 500, oy, oz + 200)

    # Tray section 1 (left)
    make_et5_section("J1_Tray_Left", 800, (ox, oy, oz), doc=doc)

    # Gap
    gap_x = ox + 800 + SPLICE_GAP

    # Tray section 2 (right)
    make_et5_section("J1_Tray_Right", 800, (gap_x, oy, oz), doc=doc)

    # Splice plates bridging the joint
    splice_x = ox + 800 + SPLICE_GAP/2
    make_splice_plates("J1_Splice", (splice_x, oy, oz), ET5_SIDE_HEIGHT, ET5_WIDTH, doc=doc)


def joint_02_horizontal_90_bend_nema(doc, origin=(0, 0, 0)):
    """
    Joint 2: Horizontal 90° Bend (NEMA3 - factory fitting + splices)
    Straight → Splice → Bend Fitting → Splice → Straight
    """
    ox, oy, oz = origin
    radius = 450  # mm

    label = doc.addObject("App::Annotation", "Label_J2")
    label.LabelText = ["JOINT 2: 90deg Bend (NEMA3 with splices)"]
    label.Position = FreeCAD.Vector(ox + 300, oy - 200, oz + 250)

    # Straight section 1 (approaching bend)
    make_nema3_section("J2_Straight_In", 1000, (ox, oy, oz), doc=doc)

    # Splice plate at entry to bend
    make_splice_plates("J2_Splice_In", (ox + 1000, oy, oz),
                       NEMA3_RAIL_HEIGHT, NEMA3_WIDTH, doc=doc)

    # Bend fitting (approximated as arc of boxes for the two rails)
    bend_cx = ox + 1000  # centre of bend arc
    bend_cy = oy - radius
    n_segments = 9  # segments to approximate 90° arc

    group = doc.addObject("App::DocumentObjectGroup", "J2_Bend_Fitting")
    for i in range(n_segments):
        angle1 = math.radians(90 * i / n_segments)
        angle2 = math.radians(90 * (i + 1) / n_segments)

        # Left rail (outer)
        r_outer = radius + NEMA3_WIDTH/2 + NEMA3_RAIL_WIDTH
        x1 = bend_cx + r_outer * math.sin(angle1)
        y1 = bend_cy + r_outer * math.cos(angle1)
        x2 = bend_cx + r_outer * math.sin(angle2)
        y2 = bend_cy + r_outer * math.cos(angle2)

        seg_len = math.sqrt((x2-x1)**2 + (y2-y1)**2)
        seg = Part.makeBox(seg_len, NEMA3_RAIL_WIDTH, NEMA3_RAIL_HEIGHT,
                           FreeCAD.Vector(x1, y1, oz))
        # Rotate to follow arc
        mid_angle = (angle1 + angle2) / 2
        seg.rotate(FreeCAD.Vector(x1, y1, oz), FreeCAD.Vector(0, 0, 1),
                   -math.degrees(mid_angle))

        obj = doc.addObject("Part::Feature", f"J2_Bend_OuterRail_{i}")
        obj.Shape = seg
        obj.ViewObject.ShapeColor = COL_CT_FITTING
        group.addObject(obj)

        # Right rail (inner)
        r_inner = radius - NEMA3_WIDTH/2
        x1i = bend_cx + r_inner * math.sin(angle1)
        y1i = bend_cy + r_inner * math.cos(angle1)

        seg_i = Part.makeBox(seg_len, NEMA3_RAIL_WIDTH, NEMA3_RAIL_HEIGHT,
                             FreeCAD.Vector(x1i, y1i, oz))
        seg_i.rotate(FreeCAD.Vector(x1i, y1i, oz), FreeCAD.Vector(0, 0, 1),
                     -math.degrees(mid_angle))

        obj_i = doc.addObject("Part::Feature", f"J2_Bend_InnerRail_{i}")
        obj_i.Shape = seg_i
        obj_i.ViewObject.ShapeColor = COL_CT_FITTING
        group.addObject(obj_i)

    # Straight section 2 (exiting bend, now running in -Y direction)
    exit_x = bend_cx + radius
    exit_y = bend_cy
    make_nema3_section("J2_Straight_Out", 1000, (exit_x, exit_y, oz),
                       direction=(0, -1, 0), doc=doc)

    # Splice at exit
    make_splice_plates("J2_Splice_Out", (exit_x, exit_y, oz),
                       NEMA3_RAIL_HEIGHT, NEMA3_WIDTH, doc=doc)


def joint_03_et5_field_bend(doc, origin=(0, 0, 0)):
    """
    Joint 3: ET5 Field-Fabricated Horizontal Bend
    Continuous tray base with RP underneath and splice plates on cut rails.
    """
    ox, oy, oz = origin
    radius = 450

    label = doc.addObject("App::Annotation", "Label_J3")
    label.LabelText = ["JOINT 3: ET5 Field Bend (RP + splice)"]
    label.Position = FreeCAD.Vector(ox + 300, oy, oz + 200)

    # Tray section 1 (approaching bend)
    make_et5_section("J3_Tray_Approach", 1000, (ox, oy, oz), doc=doc)

    # Radius plate underneath at bend point (green)
    rp_x = ox + 1000
    plate = Part.makeBox(700, ET5_WIDTH + 2*ET5_THICKNESS + 20, 3,
                         FreeCAD.Vector(rp_x - 100, oy - ET5_WIDTH/2 - ET5_THICKNESS - 10, oz - 3))
    obj_rp = doc.addObject("Part::Feature", "J3_RadiusPlate")
    obj_rp.Shape = plate
    obj_rp.ViewObject.ShapeColor = COL_RADIUS_PLATE

    # Splice plates at cut points in side rails (yellow)
    make_splice_plates("J3_CutSplice_1", (rp_x, oy, oz), ET5_SIDE_HEIGHT, ET5_WIDTH, doc=doc)
    make_splice_plates("J3_CutSplice_2", (rp_x + 500, oy, oz), ET5_SIDE_HEIGHT, ET5_WIDTH, doc=doc)

    # Tray section 2 (after bend - angled)
    make_et5_section("J3_Tray_Exit", 1000, (rp_x + 600, oy - 200, oz),
                     direction=(0.7, -0.7, 0), doc=doc)


def joint_04_tee_junction(doc, origin=(0, 0, 0)):
    """
    Joint 4: Tee Junction (ET5 with TX brackets)
    Main run continues, branch exits at 90° with TX brackets at junction.
    """
    ox, oy, oz = origin

    label = doc.addObject("App::Annotation", "Label_J4")
    label.LabelText = ["JOINT 4: Tee Junction (ET5TX brackets)"]
    label.Position = FreeCAD.Vector(ox + 800, oy, oz + 200)

    # Main run (continuous through)
    make_et5_section("J4_Main_Left", 800, (ox, oy, oz), doc=doc)
    make_et5_section("J4_Main_Right", 800, (ox + 850, oy, oz), doc=doc)

    # Branch (perpendicular, exits toward -Y)
    branch_x = ox + 800
    make_et5_section("J4_Branch", 800, (branch_x, oy - ET5_WIDTH/2 - 50, oz),
                     direction=(0, -1, 0), doc=doc)

    # TX brackets (blue) at junction - one each side of cut
    tx_w = 100
    tx_h = ET5_SIDE_HEIGHT
    tx1 = Part.makeBox(tx_w, 5, tx_h,
                       FreeCAD.Vector(branch_x - tx_w/2, oy - ET5_WIDTH/2 - ET5_THICKNESS - 5, oz))
    obj_tx1 = doc.addObject("Part::Feature", "J4_TX_Left")
    obj_tx1.Shape = tx1
    obj_tx1.ViewObject.ShapeColor = COL_TX_BRACKET

    tx2 = Part.makeBox(tx_w, 5, tx_h,
                       FreeCAD.Vector(branch_x - tx_w/2, oy + ET5_WIDTH/2 + ET5_THICKNESS, oz))
    obj_tx2 = doc.addObject("Part::Feature", "J4_TX_Right")
    obj_tx2.Shape = tx2
    obj_tx2.ViewObject.ShapeColor = COL_TX_BRACKET


def joint_05_cross_junction(doc, origin=(0, 0, 0)):
    """
    Joint 5: Cross Junction (4-way)
    Main run + two branches at 90°.
    """
    ox, oy, oz = origin

    label = doc.addObject("App::Annotation", "Label_J5")
    label.LabelText = ["JOINT 5: Cross Junction (4-way)"]
    label.Position = FreeCAD.Vector(ox + 500, oy + 500, oz + 200)

    # 4 arms from centre
    cx, cy = ox + 800, oy
    arm_len = 600

    make_et5_section("J5_Arm_East", arm_len, (cx + 50, cy, oz), direction=(1, 0, 0), doc=doc)
    make_et5_section("J5_Arm_West", arm_len, (cx - 50 - arm_len, cy, oz), direction=(1, 0, 0), doc=doc)
    make_et5_section("J5_Arm_North", arm_len, (cx, cy + 50, oz), direction=(0, 1, 0), doc=doc)
    make_et5_section("J5_Arm_South", arm_len, (cx, cy - 50 - arm_len, oz), direction=(0, 1, 0), doc=doc)

    # TX brackets at each cut point (4 pairs)
    for label_suffix, bx, by in [("E", cx+40, cy), ("W", cx-40, cy), ("N", cx, cy+40), ("S", cx, cy-40)]:
        tx = Part.makeBox(80, 5, ET5_SIDE_HEIGHT,
                          FreeCAD.Vector(bx - 40, by, oz))
        obj = doc.addObject("Part::Feature", f"J5_TX_{label_suffix}")
        obj.Shape = tx
        obj.ViewObject.ShapeColor = COL_TX_BRACKET


def joint_06_external_riser(doc, origin=(0, 0, 0)):
    """
    Joint 6: External Riser (cable on outside of bend - going UP)
    Horizontal tray transitions to vertical via riser link.
    """
    ox, oy, oz = origin
    radius = 300

    label = doc.addObject("App::Annotation", "Label_J6")
    label.LabelText = ["JOINT 6: External Riser (up)"]
    label.Position = FreeCAD.Vector(ox + 300, oy, oz + 600)

    # Horizontal section
    make_et5_section("J6_Horizontal", 800, (ox, oy, oz), doc=doc)

    # Riser link (orange bracket at transition)
    rl_x = ox + 800
    rl = Part.makeBox(5, ET5_WIDTH + 2*ET5_THICKNESS, 200,
                      FreeCAD.Vector(rl_x, oy - ET5_WIDTH/2 - ET5_THICKNESS, oz))
    obj_rl = doc.addObject("Part::Feature", "J6_RiserLink_L")
    obj_rl.Shape = rl
    obj_rl.ViewObject.ShapeColor = COL_RISER_LINK

    # Vertical section (going up)
    vert_base = FreeCAD.Vector(rl_x + 50, oy - ET5_WIDTH/2 - ET5_THICKNESS, oz + ET5_SIDE_HEIGHT)
    vert = Part.makeBox(ET5_WIDTH + 2*ET5_THICKNESS, ET5_THICKNESS, 600, vert_base)
    obj_v = doc.addObject("Part::Feature", "J6_Vertical_Wall_L")
    obj_v.Shape = vert
    obj_v.ViewObject.ShapeColor = COL_TRAY

    vert2 = Part.makeBox(ET5_WIDTH + 2*ET5_THICKNESS, ET5_THICKNESS, 600,
                         vert_base + FreeCAD.Vector(0, ET5_WIDTH + ET5_THICKNESS, 0))
    obj_v2 = doc.addObject("Part::Feature", "J6_Vertical_Wall_R")
    obj_v2.Shape = vert2
    obj_v2.ViewObject.ShapeColor = COL_TRAY


def joint_07_internal_riser(doc, origin=(0, 0, 0)):
    """
    Joint 7: Internal Riser (cable on inside of bend - going DOWN)
    """
    ox, oy, oz = origin

    label = doc.addObject("App::Annotation", "Label_J7")
    label.LabelText = ["JOINT 7: Internal Riser (down)"]
    label.Position = FreeCAD.Vector(ox + 300, oy, oz + 200)

    # Horizontal section (elevated)
    make_et5_section("J7_Horizontal", 800, (ox, oy, oz + 600), doc=doc)

    # Riser link at drop point
    rl_x = ox + 800
    rl = Part.makeBox(5, ET5_WIDTH + 2*ET5_THICKNESS, 200,
                      FreeCAD.Vector(rl_x, oy - ET5_WIDTH/2 - ET5_THICKNESS, oz + 400))
    obj_rl = doc.addObject("Part::Feature", "J7_RiserLink")
    obj_rl.Shape = rl
    obj_rl.ViewObject.ShapeColor = COL_RISER_LINK

    # Vertical section (going down)
    make_et5_section("J7_Vertical", 500, (rl_x + 20, oy, oz), direction=(0, 0, 1), doc=doc)


def joint_08_ct_taper_bend(doc, origin=(0, 0, 0)):
    """
    Joint 8: CT Taper-Fit Bend
    Shows how CT tray telescopes into CTB bend fitting.
    """
    ox, oy, oz = origin

    label = doc.addObject("App::Annotation", "Label_J8")
    label.LabelText = ["JOINT 8: CT Taper-Fit Bend (150mm R)"]
    label.Position = FreeCAD.Vector(ox + 200, oy, oz + 100)

    # CT straight section (thinner, lower profile)
    ct_t = CT_THICKNESS
    ct_w = CT_WIDTH
    ct_h = CT_SIDE_HEIGHT

    # Simplified CT as a box
    ct1 = Part.makeBox(600, ct_w + 2*ct_t, ct_h,
                       FreeCAD.Vector(ox, oy - ct_w/2 - ct_t, oz))
    obj1 = doc.addObject("Part::Feature", "J8_CT_Straight")
    obj1.Shape = ct1
    obj1.ViewObject.ShapeColor = COL_TRAY

    # CTB bend fitting (different shade to show it's a separate piece)
    # Approximated as a quarter-arc box
    bend_x = ox + 600
    bend = Part.makeBox(CT_FITTING_RADIUS, CT_FITTING_RADIUS, ct_h,
                        FreeCAD.Vector(bend_x, oy - ct_w/2 - ct_t, oz))
    obj_b = doc.addObject("Part::Feature", "J8_CTB_Bend")
    obj_b.Shape = bend
    obj_b.ViewObject.ShapeColor = COL_CT_FITTING

    # Overlap zone (taper) shown as thin strip
    taper = Part.makeBox(40, ct_w + 2*ct_t, ct_h,
                         FreeCAD.Vector(bend_x - 40, oy - ct_w/2 - ct_t, oz))
    obj_t = doc.addObject("Part::Feature", "J8_Taper_Zone")
    obj_t.Shape = taper
    obj_t.ViewObject.ShapeColor = COL_SPLICE


def joint_09_reducer(doc, origin=(0, 0, 0)):
    """
    Joint 9: Straight Reducer (width change)
    600mm tray reduces to 300mm via tapered fitting.
    """
    ox, oy, oz = origin

    label = doc.addObject("App::Annotation", "Label_J9")
    label.LabelText = ["JOINT 9: Straight Reducer (600->300mm)"]
    label.Position = FreeCAD.Vector(ox + 500, oy, oz + 200)

    # Wide section (600mm)
    make_et5_section("J9_Wide", 600, (ox, oy, oz), doc=doc)

    # Reducer (tapered trapezoid shape)
    reducer_len = 600
    rx = ox + 600 + SPLICE_GAP
    w1 = ET5_WIDTH  # 600
    w2 = 300        # target width

    # Approximate as box that narrows
    pts = [
        FreeCAD.Vector(rx, -w1/2, oz),
        FreeCAD.Vector(rx, w1/2, oz),
        FreeCAD.Vector(rx + reducer_len, w2/2, oz),
        FreeCAD.Vector(rx + reducer_len, -w2/2, oz),
        FreeCAD.Vector(rx, -w1/2, oz),
    ]
    # Make base face
    edges = [Part.makeLine(pts[i], pts[i+1]) for i in range(4)]
    wire = Part.Wire(edges)
    face = Part.Face(wire)
    reducer_shape = face.extrude(FreeCAD.Vector(0, 0, ET5_SIDE_HEIGHT))

    obj = doc.addObject("Part::Feature", "J9_Reducer")
    obj.Shape = reducer_shape
    obj.ViewObject.ShapeColor = COL_CT_FITTING

    # Narrow section (300mm) - simplified box
    narrow_x = rx + reducer_len + SPLICE_GAP
    narrow = Part.makeBox(600, 300 + 2*ET5_THICKNESS, ET5_SIDE_HEIGHT,
                          FreeCAD.Vector(narrow_x, -150 - ET5_THICKNESS, oz))
    obj_n = doc.addObject("Part::Feature", "J9_Narrow")
    obj_n.Shape = narrow
    obj_n.ViewObject.ShapeColor = COL_TRAY

    # Splice plates at each end
    make_splice_plates("J9_Splice_Wide", (rx, oy, oz), ET5_SIDE_HEIGHT, w1, doc=doc)
    make_splice_plates("J9_Splice_Narrow", (narrow_x, oy, oz), ET5_SIDE_HEIGHT, w2, doc=doc)


def joint_10_offset_sbend(doc, origin=(0, 0, 0)):
    """
    Joint 10: Offset / S-Bend
    Two opposing bends to shift the tray laterally (e.g., around an obstruction).
    """
    ox, oy, oz = origin
    offset_dist = 400  # lateral shift

    label = doc.addObject("App::Annotation", "Label_J10")
    label.LabelText = ["JOINT 10: Offset S-Bend (2x RP)"]
    label.Position = FreeCAD.Vector(ox + 500, oy + 300, oz + 200)

    # Section 1
    make_et5_section("J10_Section1", 600, (ox, oy, oz), doc=doc)

    # First radius plate
    rp1 = Part.makeBox(200, ET5_WIDTH + 20, 3,
                       FreeCAD.Vector(ox + 600, oy - ET5_WIDTH/2 - 10, oz - 3))
    obj_rp1 = doc.addObject("Part::Feature", "J10_RP1")
    obj_rp1.Shape = rp1
    obj_rp1.ViewObject.ShapeColor = COL_RADIUS_PLATE

    # Angled section (offset piece)
    make_et5_section("J10_Offset", 500, (ox + 700, oy + 50, oz),
                     direction=(0.8, 0.6, 0), doc=doc)

    # Second radius plate
    rp2 = Part.makeBox(200, ET5_WIDTH + 20, 3,
                       FreeCAD.Vector(ox + 1100, oy + offset_dist - ET5_WIDTH/2 - 10, oz - 3))
    obj_rp2 = doc.addObject("Part::Feature", "J10_RP2")
    obj_rp2.Shape = rp2
    obj_rp2.ViewObject.ShapeColor = COL_RADIUS_PLATE

    # Section 2 (offset from section 1)
    make_et5_section("J10_Section2", 600, (ox + 1200, oy + offset_dist, oz), doc=doc)


# =============================================================================
# MAIN - BUILD ALL JOINTS IN A GALLERY
# =============================================================================

def build_all_joints():
    """Generate all joint examples in a gallery layout."""
    if not HAS_FREECAD:
        print("[joints] Cannot build - FreeCAD not available")
        return

    # Close existing
    for d in FreeCAD.listDocuments():
        if d == "JointExamples":
            FreeCAD.closeDocument(d)

    doc = FreeCAD.newDocument("JointExamples")

    # Layout joints in a grid (spacing 2500mm between each)
    spacing_x = 2500
    spacing_y = 2500

    print("Building joint examples...")

    joint_01_straight_splice(doc, origin=(0, 0, 0))
    print("  1/10 Straight splice")

    joint_02_horizontal_90_bend_nema(doc, origin=(spacing_x, 0, 0))
    print("  2/10 Horizontal 90° bend (NEMA)")

    joint_03_et5_field_bend(doc, origin=(2*spacing_x, 0, 0))
    print("  3/10 ET5 field bend (RP)")

    joint_04_tee_junction(doc, origin=(0, spacing_y, 0))
    print("  4/10 Tee junction (TX)")

    joint_05_cross_junction(doc, origin=(spacing_x, spacing_y, 0))
    print("  5/10 Cross junction")

    joint_06_external_riser(doc, origin=(2*spacing_x, spacing_y, 0))
    print("  6/10 External riser (up)")

    joint_07_internal_riser(doc, origin=(0, 2*spacing_y, 0))
    print("  7/10 Internal riser (down)")

    joint_08_ct_taper_bend(doc, origin=(spacing_x, 2*spacing_y, 0))
    print("  8/10 CT taper-fit bend")

    joint_09_reducer(doc, origin=(2*spacing_x, 2*spacing_y, 0))
    print("  9/10 Straight reducer")

    joint_10_offset_sbend(doc, origin=(0, 3*spacing_y, 0))
    print("  10/10 Offset S-bend")

    doc.recompute()

    # Save
    save_path = os.path.join(_THIS_DIR, "models", "JointExamples.FCStd")
    doc.saveAs(save_path)
    print(f"\nSaved: {save_path}")
    print(f"Objects: {len(doc.Objects)}")
    print("\nColour key:")
    print("  Grey   = Cable tray sections")
    print("  Yellow = Splice plates (joining hardware)")
    print("  Green  = Radius plates (bend support)")
    print("  Blue   = TX brackets (tee/cross)")
    print("  Orange = Riser links")

    return doc


# Run if executed
if HAS_FREECAD:
    build_all_joints()
