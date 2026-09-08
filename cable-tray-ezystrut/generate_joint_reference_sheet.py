"""
Generate an Excel reference sheet showing all cable tray joint types,
how they are constructed, and where they are used.
"""

import os
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

OUTPUT_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
               "Cable_Tray_Joint_Reference.xlsx")

wb = openpyxl.Workbook()

# =============================================================================
# SHEET 1: Joint Type Reference
# =============================================================================
ws = wb.active
ws.title = "Joint Types"

# Styles
header_font = Font(bold=True, size=11, color="FFFFFF")
header_fill = PatternFill(start_color="CC0000", end_color="CC0000", fill_type="solid")
subheader_font = Font(bold=True, size=10)
subheader_fill = PatternFill(start_color="F2F2F2", end_color="F2F2F2", fill_type="solid")
wrap_align = Alignment(wrap_text=True, vertical="top")
thin_border = Border(
    left=Side(style="thin"),
    right=Side(style="thin"),
    top=Side(style="thin"),
    bottom=Side(style="thin"),
)

# Headers
headers = [
    "Joint #",
    "Joint Type",
    "Applicable Systems",
    "Connection Method",
    "Hardware Required",
    "Key Dimensions",
    "Construction Steps",
    "Data Centre Application",
    "3D Model Notes",
    "Ezystrut Part Codes",
]

for col, header in enumerate(headers, 1):
    cell = ws.cell(row=1, column=col, value=header)
    cell.font = header_font
    cell.fill = header_fill
    cell.alignment = Alignment(wrap_text=True, vertical="center")
    cell.border = thin_border

# Column widths
col_widths = [8, 22, 18, 28, 22, 22, 40, 35, 30, 20]
for i, w in enumerate(col_widths, 1):
    ws.column_dimensions[get_column_letter(i)].width = w

# Data rows
joints = [
    {
        "num": 1,
        "type": "Straight Splice",
        "systems": "ET3, ET5, NEMA, CT",
        "method": "Splice plates on OUTSIDE of both side rails, bridging the gap between two tray ends.",
        "hardware": "2x splice plates (one per side)\nSBH smooth-head bolts\nCNH cage nuts\n4 bolts per side minimum",
        "dimensions": "Splice overlap: 75mm each side of joint\nGap between tray ends: 3-5mm\nSplice plate height: 80% of rail height",
        "steps": "1. Butt two tray sections end-to-end (3-5mm gap)\n2. Place splice plate centred on joint, outside of side rail\n3. Insert SBH bolts through pre-punched holes (smooth head INSIDE)\n4. Secure with CNH cage nuts\n5. Repeat on other side\n6. Check electrical continuity (star washer if pre-galv)",
        "application": "Every straight run >3m (ET) or >6m (NEMA) requires splices. In data centres: along corridors, within data halls, between switchrooms.",
        "model_notes": "Model as: Tray_1 | 5mm gap | Tray_2\nSplice plates visible as yellow rectangles on outside of rails.\nSmooth bolt heads NOT visible from inside.",
        "parts": "ET5S (ET5 splice)\nET3S (ET3 splice)\nSBH + CNH fasteners",
    },
    {
        "num": 2,
        "type": "Horizontal 90° Bend\n(Factory Fitting)",
        "systems": "NEMA, CT",
        "method": "Separate pre-made bend FITTING connects to straights via splice plates (NEMA) or taper-fit (CT).\n\nThe bend is its own piece - NOT part of the straight tray.",
        "hardware": "NEMA: 1x bend fitting + 4x splice plates (2 per end)\nCT: 1x CTB fitting + M6x10 WIZZ screws + M6 flanged nuts",
        "dimensions": "Radius: 300mm (NEMA1) or 450mm (NEMA2/3/4)\nCT: Fixed 150mm radius (all CT fittings)\nAngle: 90° standard\nCustom: 600, 900mm radius available",
        "steps": "NEMA:\n1. Position bend fitting between two straight sections\n2. Splice plate on each rail at each end (4 total)\n3. Bolt through with SBH/CNH\n\nCT:\n1. Slide tapered end of CTB into straight CT\n2. Align base perforations\n3. Fix with M6x10 WIZZ screws through base holes",
        "application": "Direction changes in cable routes. In data centres: turning corners in corridors, routing around columns, entering/exiting rooms at 90°.",
        "model_notes": "THREE separate pieces in the model:\nStraight_1 → [splice] → Bend_Fitting → [splice] → Straight_2\n\nBend fitting has CURVED rungs (NEMA) or curved perforated base (CT).\nNever model as a single piece bending.",
        "parts": "NEMA3 bend (by width+radius)\nCTB (CT bend)\nWIZZ fasteners (CT)",
    },
    {
        "num": 3,
        "type": "Horizontal Bend\n(ET Field-Fabricated)",
        "systems": "ET3, ET5",
        "method": "Tray is CUT at the bend point and the BASE is bent in-situ. A Radius Plate (RP) supports the curve from UNDERNEATH. Cut side rails are re-closed with splice plates.",
        "hardware": "1x Radius Plate (RP) - 2m length, cut to suit\n2-4x splice plates for rail cuts\nSBH + CNH fasteners",
        "dimensions": "Radius: Adjustable (set by RP position)\nTypical: 300-600mm\nRP sits flush under tray base\nCut in rail: ~50-100mm opening per side",
        "steps": "1. Mark bend location using RP as template\n2. Cut BOTH side rails at bend point (tin snips or grinder)\n3. Position RP underneath tray base, curved to desired radius\n4. Bend tray base over the RP to desired angle\n5. Bolt RP to tray base through pre-punched holes\n6. Close rail cuts with splice plates on outside\n7. Secure all with SBH/CNH",
        "application": "Any angle bend in ET systems. Preferred for non-90° angles and adjustable radii. In data centres: routing around services, angled entries to switchboards, custom angles for site geometry.",
        "model_notes": "CONTINUOUS tray base (no gap at bend).\nRP visible as green plate UNDER the base at the curve.\nSplice plates visible as yellow on the rail cuts.\nRail has visible cut lines at start/end of curve.",
        "parts": "ET5RP (radius plate)\nET3RP (radius plate)\nET5S / ET3S (splices for cuts)",
    },
    {
        "num": 4,
        "type": "Tee Junction\n(T-intersection)",
        "systems": "ET3, ET5, NEMA, CT",
        "method": "ET: Main tray rail is CUT to create opening. Branch tray enters the cut. TX bracket bolts across joint on both sides.\n\nNEMA/CT: Pre-made tee fitting with 3 splice/taper connections.",
        "hardware": "ET: 2x TX brackets + splice bolts\nNEMA: 1x tee fitting + 6x splice plates\nCT: 1x CTT fitting + WIZZ screws",
        "dimensions": "Branch width: same or narrower than main\nRadius at branch entry: 150mm (CT) or 300-450mm (NEMA)\nET: Opening in main rail = branch width + 10mm",
        "steps": "ET:\n1. Mark branch entry point on main tray rail\n2. Cut side rail at mark (branch-width opening)\n3. Bend cut flap DOWN (out of cable path)\n4. Insert branch tray into opening\n5. Bolt TX bracket across joint (both sides)\n\nCT/NEMA:\n1. Position tee fitting at junction point\n2. Connect all 3 arms via splice/taper",
        "application": "Splitting cable routes. In data centres: main corridor feeds branching into each row, PDU feeds branching from sub-mains, BMS tray splitting to zones.",
        "model_notes": "Main tray is CONTINUOUS (base unbroken).\nBranch enters through CUT in main rail.\nTX brackets (blue) visible on both sides of the cut.\nBranch tray base aligns with main tray base (flush).",
        "parts": "ET5TX (tee/cross bracket)\nET3TX\nCTT (CT tee fitting)",
    },
    {
        "num": 5,
        "type": "Cross Junction\n(4-way intersection)",
        "systems": "ET3, ET5, NEMA, CT",
        "method": "Same as Tee but BOTH rails of main tray are cut. Two branches enter from opposite sides. TX brackets on all 4 cut points.",
        "hardware": "ET: 4x TX brackets + splice bolts\nNEMA: 1x cross fitting + 8x splice plates\nCT: 1x CTC fitting + WIZZ screws",
        "dimensions": "All 4 arms same width (standard)\nRadius at each entry: per system standard\nCentre area: open (cables cross freely)",
        "steps": "ET:\n1. Cut BOTH side rails at cross point\n2. Bend flaps down on all 4 cuts\n3. Insert branch trays from both sides\n4. TX bracket on each of the 4 cut points\n\nCT/NEMA:\n1. Position cross fitting\n2. Connect all 4 arms via splice/taper",
        "application": "Major distribution intersections. In data centres: where main N-S and E-W cable routes cross, central distribution points, above MSB areas.",
        "model_notes": "4 tray arms meeting at centre.\nTX brackets (blue) at all 4 rail cuts.\nCentre area is OPEN (no rungs/base obstructing cable crossover).\nAll 4 arms at same height (flush).",
        "parts": "ET5TX (×4)\nET3TX (×4)\nCTC (CT cross fitting)",
    },
    {
        "num": 6,
        "type": "External Riser\n(Vertical UP - cable on outside)",
        "systems": "ET3, ET5, NEMA, CT",
        "method": "Horizontal tray transitions to vertical. Riser Link (RL) brackets connect the two planes. Cable sits on OUTSIDE of the bend curve (tension side).",
        "hardware": "ET: 2x Riser Links (one per side) + bolts\nNEMA: 1x external riser fitting + splice plates\nCT: 1x CTER fitting + WIZZ screws",
        "dimensions": "Radius: 300-600mm (must suit largest cable)\nVertical section height: as required\nRL bracket length: varies with angle\nSupport within 300mm of direction change (AS/NZS 3000)",
        "steps": "ET:\n1. Cut tray at transition point\n2. Form vertical section (separate tray piece)\n3. Bolt RL bracket on each side, bridging horizontal to vertical\n4. Ensure minimum radius suits cable\n\nCT/NEMA:\n1. Splice/taper external riser fitting between horizontal and vertical straights",
        "application": "Cable riser going UP from a lower level. In data centres: from basement to ground floor, from under-floor to overhead tray, from transformer pit up to cable corridor.",
        "model_notes": "Two tray planes at 90° (horizontal + vertical).\nRL bracket (orange) visible on each side at the corner.\nCable path is on the OUTSIDE of the curve.\nSupport bracket modelled within 300mm of bend.",
        "parts": "ET5RL (riser link)\nET3RL\nCTER (CT external riser)",
    },
    {
        "num": 7,
        "type": "Internal Riser\n(Vertical DOWN - cable on inside)",
        "systems": "ET3, ET5, NEMA, CT",
        "method": "Horizontal tray transitions to vertical going DOWN. Cable sits on INSIDE of bend curve (compression side). Same hardware as external riser but inverted geometry.",
        "hardware": "ET: 2x Riser Links (one per side) + bolts\nNEMA: 1x internal riser fitting + splice plates\nCT: 1x CTIR fitting + WIZZ screws",
        "dimensions": "Same as external riser.\nCable bend radius is SMALLER than external (cable on inside = tighter bend for same fitting radius).\nMust verify cable bend radius is still met.",
        "steps": "Same as external riser but:\n- Cables experience compression not tension\n- Gravity assists cable in staying in tray\n- Hold-down clips recommended on vertical section",
        "application": "Cable drop from overhead tray to equipment. In data centres: overhead tray dropping down to switchboard, tray dropping into under-floor space, drops to rack-mounted PDUs.",
        "model_notes": "Two tray planes at 90° (horizontal → vertical down).\nRL bracket (orange) on each side.\nCable path on INSIDE of curve.\nHold-down clips on vertical section.",
        "parts": "ET5RL (riser link)\nET3RL\nCTIR (CT internal riser)",
    },
    {
        "num": 8,
        "type": "CT Taper-Fit\n(Telescope Connection)",
        "systems": "CT only",
        "method": "CT tray and all CT fittings have TAPERED fold edges. One end tapers inward, the other outward. They telescope together (slide-fit) and are screwed through the base perforations.",
        "hardware": "M6 x 10 screws + M6 flanged nuts\nOrdering code: WIZZ\nMinimum 2 screws per joint",
        "dimensions": "Overlap: 30-50mm\nTaper angle: ~5° fold on side wall edges\nSide wall: 20mm height (low profile)\nBase: continuously perforated (screw anywhere)",
        "steps": "1. Identify tapered-IN end and tapered-OUT end\n2. Slide OUT taper of one piece INTO the IN taper of the next\n3. Overlap ~30-50mm until edges are flush\n4. Align base holes\n5. Insert M6x10 screw from below\n6. Secure with M6 flanged nut on top\n7. Minimum 2 fixings per joint",
        "application": "ALL CT system connections. CT is light-duty only. In data centres: data/comms cable trays, fibre trays, BMS/control cable trays, security cable routes. NOT for heavy power cables.",
        "model_notes": "Overlap zone visible as slightly thicker area where two pieces telescope.\nNo separate splice plate - the tray edges ARE the connection.\nLow profile (20mm sides) - distinct from ET/NEMA.\nPerforated base pattern visible.",
        "parts": "CT (straight)\nCTB (bend)\nCTT (tee)\nCTC (cross)\nCTER / CTIR (risers)\nWIZZ fasteners",
    },
    {
        "num": 9,
        "type": "Straight Reducer\n(Width Transition)",
        "systems": "NEMA, ET (field-cut)",
        "method": "Tapered fitting transitions between two different tray widths. Connects via splices at each end. One end matches width W1, other matches width W2.",
        "hardware": "NEMA: 1x reducer fitting + 4x splice plates\nET: Field-cut taper in tray + splice plates\nAlternatively: left-hand or right-hand reducer (asymmetric)",
        "dimensions": "W1 (wide end): e.g. 600mm\nW2 (narrow end): e.g. 300mm\nLength: typically 600mm transition\nAngle: determined by (W1-W2)/2 ÷ length",
        "steps": "NEMA:\n1. Splice wide tray to wide end of reducer\n2. Splice narrow tray to narrow end of reducer\n\nET field-cut:\n1. Cut tray sides at angle from W1 to W2\n2. Bend side walls to follow new width\n3. Splice plates at transition points",
        "application": "Where cable count reduces (fewer cables = narrower tray). In data centres: main corridor (900mm) reducing at each branch after cables peel off, approaching a switchboard where only a few cables remain.",
        "model_notes": "Trapezoidal shape in plan view.\nWide end flush with wide tray.\nNarrow end flush with narrow tray.\nSplice plates at both ends.\nBase is continuous (single piece).",
        "parts": "NEMA reducer (by W1 x W2)\nLeft/Right hand variants\nET5S splices at cuts",
    },
    {
        "num": 10,
        "type": "Offset / S-Bend\n(Lateral Shift)",
        "systems": "ET3, ET5, NEMA",
        "method": "Two opposing bends (one left, one right) connected by a short straight, shifting the tray laterally. Uses 2x radius plates (ET) or 2x bend fittings + 3x splice sets (NEMA).",
        "hardware": "ET: 2x RP + 4x splice plates\nNEMA: 2x bend fittings + 6x splice plates",
        "dimensions": "Lateral offset: typically 200-600mm\nAngle: usually 30° or 45° each bend\nStraight between bends: min 300mm\nTotal length: offset/sin(angle) + 2×radius×tan(angle/2)",
        "steps": "1. First bend (angle away from centreline)\n2. Short straight at the offset angle\n3. Second bend (angle back to original direction)\n\nResult: tray exits parallel to entry but shifted laterally.",
        "application": "Avoiding obstructions. In data centres: routing around columns, dodging ductwork, shifting tray alignment between rooms, accommodating structural beams.",
        "model_notes": "Three-section assembly: Bend_1 + Angled_Straight + Bend_2.\nRP (green) visible under each bend.\nEntry and exit straights are PARALLEL but offset.\nAll sections at same height (horizontal offset only).",
        "parts": "2x ET5RP (radius plates)\n4x ET5S (splices)\nOr 2x NEMA bend fittings",
    },
]

# Write data rows
for row_idx, joint in enumerate(joints, 2):
    ws.cell(row=row_idx, column=1, value=joint["num"]).border = thin_border
    ws.cell(row=row_idx, column=2, value=joint["type"]).border = thin_border
    ws.cell(row=row_idx, column=3, value=joint["systems"]).border = thin_border
    ws.cell(row=row_idx, column=4, value=joint["method"]).border = thin_border
    ws.cell(row=row_idx, column=5, value=joint["hardware"]).border = thin_border
    ws.cell(row=row_idx, column=6, value=joint["dimensions"]).border = thin_border
    ws.cell(row=row_idx, column=7, value=joint["steps"]).border = thin_border
    ws.cell(row=row_idx, column=8, value=joint["application"]).border = thin_border
    ws.cell(row=row_idx, column=9, value=joint["model_notes"]).border = thin_border
    ws.cell(row=row_idx, column=10, value=joint["parts"]).border = thin_border

    for col in range(1, 11):
        ws.cell(row=row_idx, column=col).alignment = wrap_align

# Set row heights for readability
for row in range(2, 12):
    ws.row_dimensions[row].height = 120

# Freeze header
ws.freeze_panes = "A2"


# =============================================================================
# SHEET 2: Connection Rules Matrix
# =============================================================================
ws2 = wb.create_sheet("Connection Rules")

ws2.cell(row=1, column=1, value="CONNECTION RULES MATRIX").font = Font(bold=True, size=14)
ws2.cell(row=2, column=1, value="What can connect to what, and what goes between them").font = Font(italic=True)

# Rule matrix
rules_headers = ["From Component", "To Component", "Connection Piece", "System", "Rule"]
for col, h in enumerate(rules_headers, 1):
    cell = ws2.cell(row=4, column=col, value=h)
    cell.font = header_font
    cell.fill = header_fill
    cell.border = thin_border

ws2.column_dimensions["A"].width = 20
ws2.column_dimensions["B"].width = 20
ws2.column_dimensions["C"].width = 25
ws2.column_dimensions["D"].width = 15
ws2.column_dimensions["E"].width = 50

rules = [
    ("Straight", "Straight", "Splice plate (S)", "All", "ALWAYS required. Cannot butt tray ends directly. Splice bridges the gap on OUTSIDE of rails."),
    ("Straight", "90° Bend", "Splice plate (S)", "NEMA", "Bend is separate fitting. Splice on each rail at each end of bend."),
    ("Straight", "90° Bend", "Radius Plate (RP)", "ET3/ET5", "NO separate bend piece. Cut tray rails, bend base in-situ, RP underneath."),
    ("Straight", "90° Bend", "Taper slide-fit", "CT", "CTB bend telescopes into CT straight. WIZZ screws through base."),
    ("Straight", "Tee branch", "TX Bracket", "ET3/ET5", "Cut main rail. Branch enters cut. TX brackets bridge joint on both sides."),
    ("Straight", "Tee branch", "Splice plate (S)", "NEMA", "Pre-made tee fitting. Splice all 3 arms."),
    ("Straight", "Tee branch", "Taper slide-fit", "CT", "CTT tee telescopes into straights on all 3 arms."),
    ("Straight", "Vertical (up)", "Riser Link (RL)", "ET3/ET5", "Cut tray at transition. RL bracket on each side bridges horizontal to vertical."),
    ("Straight", "Vertical (up)", "Splice plate (S)", "NEMA", "Pre-made external riser fitting. Splice both ends."),
    ("Straight", "Vertical (up)", "Taper slide-fit", "CT", "CTER fitting telescopes into horizontal and vertical straights."),
    ("Straight", "Vertical (down)", "Riser Link (RL)", "ET3/ET5", "Same as up but inverted. Add hold-down clips on vertical section."),
    ("Straight", "Vertical (down)", "Taper slide-fit", "CT", "CTIR fitting telescopes into horizontal and vertical straights."),
    ("Straight", "Reducer", "Splice plate (S)", "NEMA/ET", "Splice at wide end AND narrow end. Reducer is separate transition piece."),
    ("Bend", "Bend", "Short straight + 2x splice", "NEMA", "For S-bends: two bends connected by minimum 300mm straight with splices."),
    ("Bend", "Bend", "2x RP (one per bend)", "ET3/ET5", "For S-bends: two field-cuts with RPs. Short straight between."),
    ("Vertical", "Vertical", "Splice plate (S)", "All", "Same as horizontal straight-to-straight. Splice on outside of rails."),
    ("Straight", "Equipment", "End plate / gland plate", "All", "Tray terminates at switchboard/panel. End plate closes the tray. Earth bond to equipment."),
    ("Straight", "Wall", "Fire collar / penetration", "All", "Through fire-rated walls: fire-rated cable tray penetration seal required per AS/NZS 3013."),
]

for row_idx, (from_c, to_c, conn, system, rule) in enumerate(rules, 5):
    ws2.cell(row=row_idx, column=1, value=from_c).border = thin_border
    ws2.cell(row=row_idx, column=2, value=to_c).border = thin_border
    ws2.cell(row=row_idx, column=3, value=conn).border = thin_border
    ws2.cell(row=row_idx, column=4, value=system).border = thin_border
    ws2.cell(row=row_idx, column=5, value=rule).border = thin_border
    for col in range(1, 6):
        ws2.cell(row=row_idx, column=col).alignment = wrap_align

ws2.freeze_panes = "A5"


# =============================================================================
# SHEET 3: Prohibited Connections (What NOT to do)
# =============================================================================
ws3 = wb.create_sheet("Prohibited Connections")

ws3.cell(row=1, column=1, value="PROHIBITED CONNECTIONS").font = Font(bold=True, size=14, color="CC0000")
ws3.cell(row=2, column=1, value="These configurations are physically impossible or non-compliant").font = Font(italic=True)

prohib_headers = ["Prohibited Action", "Why It Fails", "Correct Alternative"]
for col, h in enumerate(prohib_headers, 1):
    cell = ws3.cell(row=4, column=col, value=h)
    cell.font = header_font
    cell.fill = PatternFill(start_color="CC0000", end_color="CC0000", fill_type="solid")
    cell.border = thin_border

ws3.column_dimensions["A"].width = 35
ws3.column_dimensions["B"].width = 45
ws3.column_dimensions["C"].width = 45

prohibitions = [
    (
        "Butt two tray ends together (no splice)",
        "No structural connection. Joint will separate under cable weight. No earth continuity. Fails AS/NZS 3000.",
        "Use splice plates (S) on outside of both rails, bolted through with SBH/CNH.",
    ),
    (
        "Directly merge bend into straight (shared edge)",
        "Raised side rails of both pieces interfere. No physical way to mate two upstanding flanges edge-to-edge.",
        "ET: Cut rails and use RP underneath (continuous base). NEMA/CT: Separate bend fitting with splice/taper between.",
    ),
    (
        "CT bend with radius other than 150mm",
        "ALL CT fittings are manufactured at fixed 150mm radius. Cannot be field-modified.",
        "If larger radius needed: use ET3/ET5 system with RP (adjustable radius) or NEMA with custom-order bend.",
    ),
    (
        "Mix CT fittings with ET3/ET5 tray",
        "Different profiles, different side heights (20mm vs 50/85mm), different connection methods. Incompatible.",
        "Use only one system per run. Transition between systems requires an end plate on each + new support.",
    ),
    (
        "Mix NEMA ladder with ET cable tray",
        "Different rail profiles, different rung/base construction, different splice hardware. Incompatible.",
        "Use only one system per run. Plan system boundaries at logical transition points (room entries, risers).",
    ),
    (
        "Bend tighter than cable minimum radius",
        "Cable insulation damage, reduced current capacity, potential fault. CT 150mm radius only suits cables ≤25mm².",
        "Select fitting radius ≥ largest cable's minimum installed bend radius. Upsize to 300/450/600mm radius as needed.",
    ),
    (
        "Unsupported joint (no bracket within 300mm)",
        "Joint under load will sag/fail. Non-compliant with AS/NZS 3000 cl. 3.9.5.",
        "Install support bracket within 300mm of EVERY direction change, junction, and termination point.",
    ),
    (
        "Vertical run without hold-down clips",
        "Cables slide down under gravity, bunch at bottom, overload bottom support.",
        "Hold-down clips (HD) at maximum 1.5m intervals on ALL vertical sections. Minimum 2 per vertical run.",
    ),
    (
        "Tee branch wider than main tray",
        "Branch cannot physically fit through cut in main rail. Structural weakness.",
        "Branch must be same width or narrower than main. Use reducer if branch needs to be wider downstream.",
    ),
    (
        "Cover across a joint without cover splice",
        "Cover ends will gap/separate at joint, defeating protection purpose.",
        "Use matching cover fittings: cover bend, cover tee, cover splice. Each tray fitting has a matching cover fitting.",
    ),
]

for row_idx, (action, why, correct) in enumerate(prohibitions, 5):
    ws3.cell(row=row_idx, column=1, value=action).border = thin_border
    ws3.cell(row=row_idx, column=2, value=why).border = thin_border
    ws3.cell(row=row_idx, column=3, value=correct).border = thin_border
    for col in range(1, 4):
        ws3.cell(row=row_idx, column=col).alignment = wrap_align

for row in range(5, 15):
    ws3.row_dimensions[row].height = 60

ws3.freeze_panes = "A5"


# =============================================================================
# SHEET 4: Part Number Quick Reference
# =============================================================================
ws4 = wb.create_sheet("Part Numbers")

ws4.cell(row=1, column=1, value="EZYSTRUT PART NUMBER DECODER").font = Font(bold=True, size=14)
ws4.cell(row=3, column=1, value="Format: [System][Width][Finish]").font = Font(bold=True)
ws4.cell(row=4, column=1, value="Accessories: [System][Accessory][Finish]").font = Font(bold=True)

# Systems
ws4.cell(row=6, column=1, value="System Prefix").font = subheader_font
systems = [("ET", "EzyTray (light)"), ("ET3", "ET3 Cable Tray (medium)"), ("ET5", "ET5 Cable Tray (heavy)"),
           ("CT", "CT Perforated Tray"), ("CTB", "CT Bend"), ("CTT", "CT Tee"), ("CTC", "CT Cross"),
           ("CTIR", "CT Internal Riser"), ("CTER", "CT External Riser")]
for i, (code, desc) in enumerate(systems, 7):
    ws4.cell(row=i, column=1, value=code)
    ws4.cell(row=i, column=2, value=desc)

# Widths
ws4.cell(row=17, column=1, value="Widths (mm)").font = subheader_font
widths = ["75", "100", "150", "225", "300", "450", "600", "900"]
for i, w in enumerate(widths, 18):
    ws4.cell(row=i, column=1, value=w)

# Finishes
ws4.cell(row=6, column=3, value="Finish Suffix").font = subheader_font
finishes = [("G", "Pre-Galvanised"), ("H", "Hot Dip Galvanised"), ("S", "Stainless Steel"), ("A", "Aluminium (ET3 only)")]
for i, (code, desc) in enumerate(finishes, 7):
    ws4.cell(row=i, column=3, value=code)
    ws4.cell(row=i, column=4, value=desc)

# Accessory codes
ws4.cell(row=12, column=3, value="Accessory Codes").font = subheader_font
accessories = [("S", "Splice"), ("TX", "Tee/Cross Bracket"), ("RL", "Riser Link"),
               ("HD", "Hold Down Unit"), ("RP", "Radius Plate"), ("DS", "Divider Strip"),
               ("SHB", "Side Hanger Bracket")]
for i, (code, desc) in enumerate(accessories, 13):
    ws4.cell(row=i, column=3, value=code)
    ws4.cell(row=i, column=4, value=desc)

# Examples
ws4.cell(row=21, column=3, value="Example Part Numbers").font = subheader_font
examples = [
    ("ET5600G", "ET5 tray, 600mm wide, pre-galvanised"),
    ("ET5SG", "ET5 splice, pre-galvanised"),
    ("ET5RPG", "ET5 radius plate, pre-galvanised"),
    ("ET5TXH", "ET5 tee/cross bracket, hot-dip galv"),
    ("ET5RLG", "ET5 riser link, pre-galvanised"),
    ("CT300G", "CT tray, 300mm wide, pre-galvanised"),
    ("CTB300G", "CT bend, 300mm wide, pre-galvanised"),
    ("CTT150G", "CT tee, 150mm wide, pre-galvanised"),
]
for i, (code, desc) in enumerate(examples, 22):
    ws4.cell(row=i, column=3, value=code).font = Font(bold=True)
    ws4.cell(row=i, column=4, value=desc)


# =============================================================================
# Save
# =============================================================================
wb.save(OUTPUT_PATH)
print(f"Saved: {OUTPUT_PATH}")
print(f"Sheets: {wb.sheetnames}")
