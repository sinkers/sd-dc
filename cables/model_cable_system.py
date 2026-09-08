"""
Parametric cable tray + cable system generator for FreeCAD.

Generates a 3D model of power cables on ladder trays between two points,
with correct cable selection, tray sizing, trefoil arrangement, and bend radii.

Usage (inside FreeCAD Python console or via MCP):
    exec(open('/Users/andrewsinclair/workspace/sd-dc/cables/model_cable_system.py').read())

    # Example: 4000A from transformer to PTU, 20m run
    model = generate_cable_system(
        current_a=4000,
        voltage_v=415,
        phases=3,
        run_length_m=20,
        cable_type="XLPE_SDI_CU",
        installation="spaced",
        ambient_temp_c=40,
        route_turns=[
            {"distance_m": 5, "direction": "up", "rise_m": 2.5},
            {"distance_m": 10, "direction": "straight"},
            {"distance_m": 5, "direction": "down", "rise_m": -2.5},
        ],
        start_point=(0, 0, 500),      # mm from origin
        end_point=(20000, 0, 500),     # mm
        tray_height_mm=2500,           # above floor
    )

Coordinate system: X = length of run, Y = lateral, Z = height (mm)
"""

import json
import math
import os

# Try FreeCAD imports - script works standalone for calculations,
# only needs FreeCAD for 3D generation
try:
    import FreeCAD
    import Part
    HAS_FREECAD = True
except ImportError:
    HAS_FREECAD = False
    print("[cable_system] Running in calculation-only mode (no FreeCAD)")


# =============================================================================
# CATALOG DATA
# =============================================================================

# Resolve catalog path - works whether run from FreeCAD, CLI, or imported
_THIS_DIR = os.path.dirname(os.path.abspath(__file__)) if '__file__' in dir() else '/Users/andrewsinclair/workspace/sd-dc/cables'
CATALOG_PATH = os.path.join(_THIS_DIR, "cable_catalog.json")

def load_catalog():
    with open(CATALOG_PATH, "r") as f:
        return json.load(f)


# =============================================================================
# CABLE SIZING ENGINE
# =============================================================================

def select_cable_size(current_a, cable_type_key, installation, ambient_temp_c,
                      num_parallel_groups, catalog):
    """
    Select the optimal cable size for given requirements.

    Returns dict with cable size and all properties, or None if impossible.
    """
    cable_data = catalog["cables"][cable_type_key]
    derating = catalog["derating_factors"]

    # Installation method maps to rating column
    install_map = {
        "spaced": "i_3ph_spaced_a",
        "touching": "i_3ph_touching_a",
        "conduit": "i_3ph_conduit_a",
        "buried": "i_3ph_buried_a",
    }
    rating_key = install_map.get(installation, "i_3ph_spaced_a")

    # Temperature derating
    temp_factor = 1.0
    if ambient_temp_c > 40:
        temp_str = str(int(ambient_temp_c))
        if temp_str in derating["ambient_temp"]:
            temp_factor = derating["ambient_temp"][temp_str]
        else:
            # Interpolate
            temp_factor = max(0.5, 1.0 - (ambient_temp_c - 40) * 0.02)

    # Grouping derating
    group_str = str(min(num_parallel_groups, 9))
    group_factor = derating["grouping"].get(group_str, 0.69)

    # Find smallest cable that meets derated requirement
    target_per_cable = current_a / num_parallel_groups

    # Sort sizes numerically
    sorted_sizes = sorted(cable_data["sizes"].items(), key=lambda x: int(x[0]))

    for size_str, props in sorted_sizes:
        base_rating = props[rating_key]
        derated_rating = base_rating * temp_factor * group_factor

        if derated_rating >= target_per_cable:
            return {
                "size_mm2": int(size_str),
                "properties": props,
                "base_rating_a": base_rating,
                "derated_rating_a": derated_rating,
                "temp_factor": temp_factor,
                "group_factor": group_factor,
                "parallel_count": num_parallel_groups,
                "total_capacity_a": derated_rating * num_parallel_groups,
            }

    return None  # No cable large enough


def size_cable_system(current_a, voltage_v, phases, run_length_m,
                      cable_type_key="XLPE_SDI_CU", installation="spaced",
                      ambient_temp_c=40, max_vdrop_pct=5.0):
    """
    Full cable sizing: determines parallel count, cable size, tray dimensions.

    Returns a complete specification dict.
    """
    catalog = load_catalog()
    cable_data = catalog["cables"][cable_type_key]

    # Start with largest cable, see how many parallels needed
    largest_size = max(cable_data["sizes"].keys(), key=lambda x: int(x))
    largest_props = cable_data["sizes"][largest_size]

    install_map = {
        "spaced": "i_3ph_spaced_a",
        "touching": "i_3ph_touching_a",
        "conduit": "i_3ph_conduit_a",
        "buried": "i_3ph_buried_a",
    }
    rating_key = install_map.get(installation, "i_3ph_spaced_a")

    # Determine minimum parallel sets needed (with largest cable)
    base_rating = largest_props[rating_key]
    min_parallels = math.ceil(current_a / base_rating)

    # Try to optimise: fewer parallels with largest cable, or more with smaller
    best_result = None

    for n_parallel in range(min_parallels, min_parallels + 4):
        result = select_cable_size(
            current_a, cable_type_key, installation,
            ambient_temp_c, n_parallel, catalog
        )
        if result:
            # Check voltage drop
            r_ac = result["properties"].get("r_ac_ohm_km",
                   result["properties"].get("r_dc_ohm_km", 0.1) * 1.02)
            x_ac = result["properties"].get("x_ohm_km", 0.08)
            z_cable = math.sqrt(r_ac**2 + x_ac**2)  # ohm/km per cable

            # Voltage drop (3-phase): Vd = sqrt(3) * I * Z * L / (n * 1000)
            i_per_cable = current_a / n_parallel
            vdrop_v = math.sqrt(3) * i_per_cable * z_cable * run_length_m / 1000
            vdrop_pct = (vdrop_v / voltage_v) * 100

            result["voltage_drop_v"] = vdrop_v
            result["voltage_drop_pct"] = vdrop_pct
            result["run_length_m"] = run_length_m

            if vdrop_pct <= max_vdrop_pct:
                if best_result is None or result["size_mm2"] < best_result["size_mm2"]:
                    best_result = result
                break  # First valid solution with minimum parallels
            else:
                # Need to upsize for voltage drop - try next parallel count
                continue

    if best_result is None:
        # Fallback: use largest cable with calculated parallels
        best_result = select_cable_size(
            current_a, cable_type_key, installation,
            ambient_temp_c, min_parallels + 2, catalog
        )
        if best_result:
            best_result["voltage_drop_v"] = 0
            best_result["voltage_drop_pct"] = 0
            best_result["run_length_m"] = run_length_m

    # Calculate tray sizing
    cable_od = best_result["properties"]["od_mm"]
    n_phase_cables = best_result["parallel_count"] * phases
    n_neutral = best_result["parallel_count"]
    n_earth = max(3, best_result["parallel_count"] // 2)
    total_cables = n_phase_cables + n_neutral + n_earth

    # Trefoil arrangement: 3 cables in triangle per set
    n_trefoils = best_result["parallel_count"]
    trefoil_width = 2 * cable_od
    trefoil_height = 1.73 * cable_od
    trefoil_gap = 50  # mm between groups

    # Power tray width (trefoils)
    power_tray_width_needed = n_trefoils * trefoil_width + (n_trefoils - 1) * trefoil_gap

    # Select standard tray width
    std_widths = catalog["tray_widths_mm"]
    power_tray_width = next(w for w in std_widths if w >= power_tray_width_needed)

    # Neutral/earth tray
    neutral_width_needed = (n_neutral + n_earth) * cable_od + (n_neutral + n_earth - 1) * 10
    neutral_tray_width = next(w for w in std_widths if w >= neutral_width_needed)

    # Weight per metre
    cable_weight_per_m = best_result["properties"]["weight_kg_100m"] / 100
    total_weight_per_m = total_cables * cable_weight_per_m

    # Support spacing (based on weight)
    if total_weight_per_m > 100:
        support_spacing_mm = 1000
    elif total_weight_per_m > 50:
        support_spacing_mm = 1500
    else:
        support_spacing_mm = 2000

    best_result["cable_type"] = cable_type_key
    best_result["cable_name"] = cable_data["name"]
    best_result["cable_od_mm"] = cable_od
    best_result["bend_radius_mm"] = best_result["properties"]["bend_installed_mm"]
    best_result["n_phase_cables"] = n_phase_cables
    best_result["n_neutral"] = n_neutral
    best_result["n_earth"] = n_earth
    best_result["total_cables"] = total_cables
    best_result["n_trefoils"] = n_trefoils
    best_result["trefoil_width_mm"] = trefoil_width
    best_result["trefoil_height_mm"] = trefoil_height
    best_result["power_tray_width_mm"] = power_tray_width
    best_result["neutral_tray_width_mm"] = neutral_tray_width
    best_result["total_weight_kg_per_m"] = total_weight_per_m
    best_result["support_spacing_mm"] = support_spacing_mm
    best_result["sheath_colour"] = cable_data["colour"]

    return best_result


# =============================================================================
# FREECAD 3D MODEL GENERATION
# =============================================================================

def make_cable_path(start, end, bend_radius, tray_height_mm=2500):
    """
    Generate a cable path (list of edges) with proper bend radii.
    Simple straight run for now - extend for complex routes.
    """
    start_v = FreeCAD.Vector(*start)
    end_v = FreeCAD.Vector(*end)

    # For a straight run, the path is just a line
    edges = [Part.makeLine(start_v, end_v)]
    wire = Part.Wire(edges)
    return wire


def make_cable_path_with_bends(waypoints, bend_radius):
    """
    Generate a wire through waypoints with filleted corners.
    waypoints: list of (x, y, z) tuples in mm
    bend_radius: minimum bend radius in mm
    """
    if len(waypoints) < 2:
        raise ValueError("Need at least 2 waypoints")

    vectors = [FreeCAD.Vector(*p) for p in waypoints]

    if len(vectors) == 2:
        return Part.Wire([Part.makeLine(vectors[0], vectors[1])])

    # Create polyline then fillet corners
    edges = []
    for i in range(len(vectors) - 1):
        edges.append(Part.makeLine(vectors[i], vectors[i + 1]))

    wire = Part.Wire(edges)

    # Fillet each internal vertex
    try:
        wire = wire.makeFillet(bend_radius, wire.Vertexes[1:-1])
    except Exception:
        # If fillet fails (e.g., radius too large for segment), use straight wire
        pass

    return wire


def make_tray(name, width_mm, depth_mm, path_wire, doc):
    """
    Create a cable tray (U-channel) swept along a path.
    """
    rail_thickness = 3  # mm

    # Create U-profile at start of path
    # Bottom + two sides
    hw = width_mm / 2
    points = [
        FreeCAD.Vector(-hw, 0, 0),
        FreeCAD.Vector(-hw, 0, depth_mm),
        FreeCAD.Vector(-hw + rail_thickness, 0, depth_mm),
        FreeCAD.Vector(-hw + rail_thickness, 0, rail_thickness),
        FreeCAD.Vector(hw - rail_thickness, 0, rail_thickness),
        FreeCAD.Vector(hw - rail_thickness, 0, depth_mm),
        FreeCAD.Vector(hw, 0, depth_mm),
        FreeCAD.Vector(hw, 0, 0),
        FreeCAD.Vector(-hw, 0, 0),  # close
    ]

    profile_edges = []
    for i in range(len(points) - 1):
        profile_edges.append(Part.makeLine(points[i], points[i + 1]))
    profile_wire = Part.Wire(profile_edges)

    # Sweep along path
    tray_shape = Part.Wire(path_wire).makePipe(profile_wire)

    obj = doc.addObject("Part::Feature", name)
    obj.Shape = tray_shape
    obj.ViewObject.ShapeColor = (0.7, 0.7, 0.7)  # light grey
    obj.ViewObject.Transparency = 40
    return obj


def make_single_cable(name, path_wire, cable_od_mm, offset_vec, colour, doc):
    """
    Create a single cable (solid cylinder) swept along a path with offset.
    """
    radius = cable_od_mm / 2

    # Offset the path
    if offset_vec.Length > 0:
        offset_path = path_wire.makeOffset2D(0)  # copy
        # Translate the wire
        offset_path.translate(offset_vec)
    else:
        offset_path = path_wire

    # Create circle profile
    circle = Part.makeCircle(radius)
    circle_wire = Part.Wire([circle])

    # Sweep
    cable_shape = offset_path.makePipe(circle_wire)

    obj = doc.addObject("Part::Feature", name)
    obj.Shape = cable_shape
    obj.ViewObject.ShapeColor = colour
    return obj


def make_cable_group_simple(name, path_wire, spec, doc):
    """
    Create cables as simple cylinders along a straight path.
    Uses cylinder primitives for reliability (sweep can fail on complex paths).
    """
    cable_od = spec["cable_od_mm"]
    radius = cable_od / 2
    n_trefoils = spec["n_trefoils"]
    trefoil_gap = 50

    # Get path start/end for direction
    start = path_wire.Vertexes[0].Point
    end = path_wire.Vertexes[-1].Point
    direction = end - start
    length = direction.Length

    # Phase colours (Australian: Red, White, Blue)
    phase_colours = [(0.8, 0.1, 0.1), (0.9, 0.9, 0.9), (0.1, 0.1, 0.8)]
    neutral_colour = (0.1, 0.1, 0.1)  # black
    earth_colour = (0.1, 0.7, 0.1)    # green

    cables_group = doc.addObject("App::DocumentObjectGroup", name)
    cable_idx = 0

    # Layout trefoils
    total_trefoil_width = n_trefoils * (2 * cable_od) + (n_trefoils - 1) * trefoil_gap
    start_offset_y = -total_trefoil_width / 2 + cable_od

    for t in range(n_trefoils):
        # Trefoil centre Y position
        ty = start_offset_y + t * (2 * cable_od + trefoil_gap)

        # Three cables in trefoil: bottom-left, bottom-right, top-centre
        positions = [
            (ty - radius, -radius),          # bottom left (Phase A)
            (ty + radius, -radius),          # bottom right (Phase B)
            (ty, radius * 0.73),             # top centre (Phase C)
        ]

        for p_idx, (py, pz) in enumerate(positions):
            cable_start = FreeCAD.Vector(start.x, start.y + py, start.z + pz)
            cyl = Part.makeCylinder(radius, length, cable_start, direction)

            obj = doc.addObject("Part::Feature", f"Cable_Ph{p_idx+1}_Set{t+1}")
            obj.Shape = cyl
            obj.ViewObject.ShapeColor = phase_colours[p_idx]
            cables_group.addObject(obj)
            cable_idx += 1

    # Neutral cables (row above trefoils)
    for n in range(spec["n_neutral"]):
        ny = start_offset_y + n * (cable_od + 10)
        nz = spec["trefoil_height_mm"] + cable_od
        cable_start = FreeCAD.Vector(start.x, start.y + ny, start.z + nz)
        cyl = Part.makeCylinder(radius, length, cable_start, direction)

        obj = doc.addObject("Part::Feature", f"Cable_N_Set{n+1}")
        obj.Shape = cyl
        obj.ViewObject.ShapeColor = neutral_colour
        cables_group.addObject(obj)

    # Earth cables
    for e in range(spec["n_earth"]):
        ey = start_offset_y + (spec["n_neutral"] + e) * (cable_od + 10)
        ez = spec["trefoil_height_mm"] + cable_od
        cable_start = FreeCAD.Vector(start.x, start.y + ey, start.z + ez)

        earth_r = radius * 0.75  # earth is smaller (50% CSA)
        cyl = Part.makeCylinder(earth_r, length, cable_start, direction)

        obj = doc.addObject("Part::Feature", f"Cable_E_{e+1}")
        obj.Shape = cyl
        obj.ViewObject.ShapeColor = earth_colour
        cables_group.addObject(obj)

    return cables_group


def make_tray_simple(name, width_mm, depth_mm, start, end, doc):
    """
    Create a cable tray as simple box geometry (ladder tray approximation).
    """
    direction = end - start
    length = direction.Length
    rail_h = depth_mm
    rail_w = 3  # mm wall thickness

    # Position tray centred on path
    tray_group = doc.addObject("App::DocumentObjectGroup", name)

    hw = width_mm / 2

    # Left rail
    left_start = FreeCAD.Vector(start.x, start.y - hw, start.z - depth_mm)
    left = Part.makeBox(length, rail_w, rail_h, left_start)
    obj_l = doc.addObject("Part::Feature", f"{name}_Rail_L")
    obj_l.Shape = left
    obj_l.ViewObject.ShapeColor = (0.6, 0.6, 0.6)
    obj_l.ViewObject.Transparency = 30
    tray_group.addObject(obj_l)

    # Right rail
    right_start = FreeCAD.Vector(start.x, start.y + hw - rail_w, start.z - depth_mm)
    right = Part.makeBox(length, rail_w, rail_h, right_start)
    obj_r = doc.addObject("Part::Feature", f"{name}_Rail_R")
    obj_r.Shape = right
    obj_r.ViewObject.ShapeColor = (0.6, 0.6, 0.6)
    obj_r.ViewObject.Transparency = 30
    tray_group.addObject(obj_r)

    # Bottom (rungs - simplified as solid plate)
    bottom_start = FreeCAD.Vector(start.x, start.y - hw, start.z - depth_mm)
    bottom = Part.makeBox(length, width_mm, 2, bottom_start)
    obj_b = doc.addObject("Part::Feature", f"{name}_Base")
    obj_b.Shape = bottom
    obj_b.ViewObject.ShapeColor = (0.6, 0.6, 0.6)
    obj_b.ViewObject.Transparency = 50
    tray_group.addObject(obj_b)

    return tray_group


def make_supports(name, start, end, tray_height_mm, support_spacing_mm, doc):
    """
    Create tray support brackets at regular intervals.
    """
    direction = end - start
    length = direction.Length
    n_supports = max(2, int(length / support_spacing_mm) + 1)

    supports_group = doc.addObject("App::DocumentObjectGroup", name)

    for i in range(n_supports):
        frac = i / max(1, n_supports - 1)
        sx = start.x + direction.x * frac
        sy = start.y + direction.y * frac
        sz = 0  # floor level

        # Vertical post
        post = Part.makeBox(50, 50, tray_height_mm,
                           FreeCAD.Vector(sx - 25, sy - 25, sz))
        obj = doc.addObject("Part::Feature", f"{name}_Post_{i+1}")
        obj.Shape = post
        obj.ViewObject.ShapeColor = (0.4, 0.4, 0.4)
        supports_group.addObject(obj)

    return supports_group


# =============================================================================
# MAIN ENTRY POINT
# =============================================================================

def generate_cable_system(current_a, voltage_v=415, phases=3,
                          run_length_m=20, cable_type="XLPE_SDI_CU",
                          installation="spaced", ambient_temp_c=40,
                          start_point=(0, 0, 2500),
                          end_point=None,
                          tray_height_mm=2500,
                          doc_name="CableSystem"):
    """
    Generate complete cable system model in FreeCAD.

    Parameters:
        current_a:        Total load current (amps)
        voltage_v:        System voltage (default 415V 3-phase)
        phases:           Number of phases (default 3)
        run_length_m:     Cable run length in metres
        cable_type:       Key from cable_catalog.json (XLPE_SDI_CU, XLPE_SDI_AL, LFH_SINGLE)
        installation:     "spaced", "touching", "conduit", "buried"
        ambient_temp_c:   Ambient temperature (default 40C)
        start_point:      (x, y, z) in mm - start of cable run
        end_point:        (x, y, z) in mm - end of cable run (auto-calculated if None)
        tray_height_mm:   Height of tray above floor
        doc_name:         FreeCAD document name

    Returns:
        dict with full specification and model references
    """

    # === SIZING ===
    spec = size_cable_system(
        current_a=current_a,
        voltage_v=voltage_v,
        phases=phases,
        run_length_m=run_length_m,
        cable_type_key=cable_type,
        installation=installation,
        ambient_temp_c=ambient_temp_c,
    )

    if spec is None:
        raise ValueError(f"Cannot size cable for {current_a}A - load exceeds catalog capacity")

    # Print specification summary
    print("\n" + "=" * 70)
    print(f"CABLE SYSTEM SPECIFICATION")
    print("=" * 70)
    print(f"  Load:              {current_a} A at {voltage_v}V {phases}-phase")
    print(f"  Run length:        {run_length_m} m")
    print(f"  Cable type:        {spec['cable_name']}")
    print(f"  Cable size:        {spec['size_mm2']} mm2")
    print(f"  Parallel sets:     {spec['parallel_count']}")
    print(f"  Cables per phase:  {spec['parallel_count']}")
    print(f"  Total cables:      {spec['total_cables']} ({spec['n_phase_cables']}ph + {spec['n_neutral']}N + {spec['n_earth']}E)")
    print(f"  Cable OD:          {spec['cable_od_mm']} mm")
    print(f"  Min bend radius:   {spec['bend_radius_mm']} mm")
    print(f"  Voltage drop:      {spec['voltage_drop_v']:.1f}V ({spec['voltage_drop_pct']:.2f}%)")
    print(f"  Capacity:          {spec['total_capacity_a']:.0f} A (derated)")
    print(f"  Derating:          temp={spec['temp_factor']:.2f} × group={spec['group_factor']:.2f}")
    print(f"  ---")
    print(f"  Power tray:        {spec['power_tray_width_mm']} mm wide")
    print(f"  Neutral tray:      {spec['neutral_tray_width_mm']} mm wide")
    print(f"  Weight on tray:    {spec['total_weight_kg_per_m']:.1f} kg/m")
    print(f"  Support spacing:   {spec['support_spacing_mm']} mm")
    print(f"  Trefoils:          {spec['n_trefoils']} × ({spec['trefoil_width_mm']:.0f} × {spec['trefoil_height_mm']:.0f} mm)")
    print("=" * 70)

    # === 3D MODEL ===
    if not HAS_FREECAD:
        print("\n[cable_system] FreeCAD not available - returning specification only")
        return spec

    # Calculate end point if not given
    if end_point is None:
        end_point = (start_point[0] + run_length_m * 1000, start_point[1], start_point[2])

    start_v = FreeCAD.Vector(*start_point)
    end_v = FreeCAD.Vector(*end_point)

    # Create/reset document
    if FreeCAD.ActiveDocument and FreeCAD.ActiveDocument.Name == doc_name:
        FreeCAD.closeDocument(doc_name)
    doc = FreeCAD.newDocument(doc_name)

    # Create path wire
    path_wire = Part.Wire([Part.makeLine(start_v, end_v)])

    # Create cable tray
    make_tray_simple("PowerTray", spec["power_tray_width_mm"], 150, start_v, end_v, doc)

    # Create cables in trefoil arrangement
    make_cable_group_simple("Cables", path_wire, spec, doc)

    # Create supports
    make_supports("Supports", start_v, end_v, tray_height_mm, spec["support_spacing_mm"], doc)

    # Add annotation object with specs
    anno = doc.addObject("App::Annotation", "CableSpec")
    anno.LabelText = [
        f"{current_a}A @ {voltage_v}V",
        f"{spec['parallel_count']}x {spec['size_mm2']}mm2 {spec['cable_name']}",
        f"Tray: {spec['power_tray_width_mm']}mm | Bend R: {spec['bend_radius_mm']}mm",
        f"Vdrop: {spec['voltage_drop_pct']:.1f}% | Weight: {spec['total_weight_kg_per_m']:.0f}kg/m",
    ]

    doc.recompute()

    print(f"\n[cable_system] Model generated: {doc_name}")
    print(f"[cable_system] Objects: {len(doc.Objects)}")

    spec["_doc"] = doc
    return spec


# =============================================================================
# CONVENIENCE FUNCTIONS
# =============================================================================

def example_transformer_to_ptu():
    """4000A feed from transformer to PTU - the worked example."""
    return generate_cable_system(
        current_a=4000,
        voltage_v=415,
        phases=3,
        run_length_m=20,
        cable_type="XLPE_SDI_CU",
        installation="spaced",
        ambient_temp_c=40,
        start_point=(0, 0, 2500),
        tray_height_mm=2500,
        doc_name="Transformer_to_PTU",
    )


def example_msb_to_sdb():
    """800A sub-main from MSB to sub-distribution board."""
    return generate_cable_system(
        current_a=800,
        voltage_v=415,
        phases=3,
        run_length_m=35,
        cable_type="XLPE_SDI_CU",
        installation="spaced",
        ambient_temp_c=45,
        start_point=(0, 0, 3000),
        tray_height_mm=3000,
        doc_name="MSB_to_SDB",
    )


def example_pdu_feed():
    """200A PDU feed."""
    return generate_cable_system(
        current_a=200,
        voltage_v=415,
        phases=3,
        run_length_m=15,
        cable_type="LFH_SINGLE",
        installation="spaced",
        ambient_temp_c=45,
        start_point=(0, 0, 2800),
        tray_height_mm=2800,
        doc_name="SDB_to_PDU",
    )


# =============================================================================
# RUN IF EXECUTED DIRECTLY (calculation mode)
# =============================================================================

if __name__ == "__main__" or not HAS_FREECAD:
    print("\n--- Example: 4000A Transformer to PTU ---")
    spec = size_cable_system(4000, 415, 3, 20, "XLPE_SDI_CU", "spaced", 40)
    if spec:
        print(f"  Cable: {spec['parallel_count']}x {spec['size_mm2']}mm2")
        print(f"  OD: {spec['cable_od_mm']}mm | Bend R: {spec['bend_radius_mm']}mm")
        print(f"  Power tray: {spec['power_tray_width_mm']}mm")
        print(f"  Total cables: {spec['total_cables']}")
        print(f"  Weight: {spec['total_weight_kg_per_m']:.1f} kg/m")
        print(f"  Vdrop: {spec['voltage_drop_pct']:.2f}%")

    print("\n--- Example: 800A MSB to SDB (45C ambient) ---")
    spec2 = size_cable_system(800, 415, 3, 35, "XLPE_SDI_CU", "spaced", 45)
    if spec2:
        print(f"  Cable: {spec2['parallel_count']}x {spec2['size_mm2']}mm2")
        print(f"  OD: {spec2['cable_od_mm']}mm | Bend R: {spec2['bend_radius_mm']}mm")
        print(f"  Power tray: {spec2['power_tray_width_mm']}mm")
        print(f"  Vdrop: {spec2['voltage_drop_pct']:.2f}%")

    print("\n--- Example: 200A PDU feed (LFH, 45C) ---")
    spec3 = size_cable_system(200, 415, 3, 15, "LFH_SINGLE", "spaced", 45)
    if spec3:
        print(f"  Cable: {spec3['parallel_count']}x {spec3['size_mm2']}mm2")
        print(f"  OD: {spec3['cable_od_mm']}mm | Bend R: {spec3['bend_radius_mm']}mm")
        print(f"  Power tray: {spec3['power_tray_width_mm']}mm")
        print(f"  Vdrop: {spec3['voltage_drop_pct']:.2f}%")
