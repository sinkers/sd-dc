# Cable System 3D Modelling - Agent Instructions

## Overview

You are generating 3D models of data centre cabling systems. This folder contains a complete catalog of Nexans Australia cables with physical and electrical properties. Your job is to:

1. Accept electrical requirements (load, voltage, distance, installation method)
2. Select appropriate cables from this catalog
3. Generate geometrically accurate 3D cable models that satisfy all constraints

## Critical Constraints for Cable Routing

### Bend Radius (MUST NOT VIOLATE)
Every cable has TWO bend radii:
- **Installation bend radius** - the minimum radius during pulling (under tension)
- **Installed bend radius** - the minimum radius at rest (no tension, final position)

The installed radius is what matters for your 3D model geometry. Any bend tighter than this will damage the cable insulation and create a fire/fault hazard.

**Rule:** All curves in your cable model must have radius >= the "Bend Radius Installed" value for that cable size.

### Thermal Derating (AFFECTS CABLE SELECTION)
Cables in data centres run hot. Apply these corrections:
- If ambient > 40C: derate per tables in README.md
- If cables are grouped/bundled: derate per grouping factors
- If in conduit: use "enclosed conduit" column (significantly lower than free-air)
- If on open ladder tray with spacing: use "unenclosed spaced" column (highest rating)

### Cable Tray Fill
- Power cable trays: max 50% cross-sectional fill
- Control/data cable trays: max 40% fill
- Single layer only for cables > 200A

### Separation Requirements
- Power and data cable trays: minimum 300mm vertical or horizontal separation
- MV and LV cables: minimum 300mm separation or physical barrier
- Fire-rated cables: dedicated routes (not mixed with non-rated cables)

## 3D Model Generation Process

### For each cable run, define:
```
{
  "cable_type": "reference to catalog file",
  "conductor_size_mm2": number,
  "outer_diameter_mm": number,  // from catalog table
  "bend_radius_mm": number,     // installed bend radius from catalog
  "weight_kg_per_m": number,    // from catalog (divide kg/100m by 100)
  "sheath_colour": "hex or name",
  "route_points": [[x,y,z], ...],  // 3D path waypoints
  "total_length_m": number
}
```

### Cable Cross-Section Modelling
Model cables as cylinders with the outer diameter from the catalog. For cutaway views or termination details, use the construction layers described in each catalog file.

### Standard Cable Colours (Australian AS/NZS 3000)
| Cable Type | Sheath Colour | Hex |
|---|---|---|
| XLPE SDI (LV power) | Black | #1a1a1a |
| Orange Circular (LV) | Orange | #ff6600 |
| LFH/FR (fire rated) | Black (LFH) / Red (FR) | #1a1a1a / #cc0000 |
| MV cables | Red | #cc0000 |
| VSD (VAROLEX) | Black | #1a1a1a |
| Control/Instrumentation | Grey | #808080 |
| Data (Cat5e/6) | Grey or Blue | #808080 / #0066cc |
| Fibre SM | Yellow | #ffcc00 |
| Fibre MM | Orange | #ff9900 |

### Core Colour Coding (AS/NZS 3000 for active conductors)
| Phase | Colour | Hex |
|---|---|---|
| Phase A (L1) | Red | #cc0000 |
| Phase B (L2) | White | #ffffff |
| Phase C (L3) | Blue | #0000cc |
| Neutral | Black | #000000 |
| Earth | Green/Yellow striped | #00cc00/#ffff00 |

## Typical Data Centre Cable Types by Location

### Utility Incoming (Boundary to Main Switchroom)
- **Cable:** MV XLPE Single Core (file 12) or MV Triplex (file 14)
- **Voltage:** 11kV or 22kV
- **Typical size:** 240-630mm2
- **Route:** Underground in concrete duct bank, then into cable basement

### Transformer to Main Switchboard (MSB)
- **Cable:** XLPE SDI Copper Single Core (file 01)
- **Voltage:** 0.6/1kV
- **Typical size:** 300-630mm2 (multiple parallel sets per transformer)
- **Route:** Cable basement on heavy-duty ladder tray

### MSB to Sub-Distribution Board (SDB)
- **Cable:** XLPE SDI Copper (file 01) or Orange Circular 3C+E (file 03)
- **Voltage:** 0.6/1kV
- **Typical size:** 95-240mm2
- **Route:** Vertical risers + overhead cable tray

### SDB to PDU (Power Distribution Unit)
- **Cable:** Orange Circular XLPE 3C+E (file 03)
- **Voltage:** 0.6/1kV
- **Typical size:** 35-95mm2
- **Route:** Under raised floor or overhead

### PDU to IT Rack
- **Cable:** Orange Circular XLPE or POWERLEX (file 03/07)
- **Typical size:** 10-25mm2
- **Route:** Under raised floor or overhead in basket tray

### Cooling Plant (VSD Motor Feeds)
- **Cable:** VAROLEX VSD 3C+3E (file 05) or VSD/EMC (file 06)
- **Typical size:** 16-95mm2 (depends on motor kW)
- **Route:** Cable tray to plant room, then conduit to motor terminal box

### Fire-Rated Circuits (Essential Services)
- **Cable:** Alsecure PLUS FR Single Core (file 11)
- **Typical size:** 10-50mm2
- **Route:** Dedicated fire-rated cable tray (mineral insulated clips if exposed)

### BMS/Control
- **Cable:** Instrolex Instrumentation (file 08)
- **Route:** Control cable tray (separate from power)

### Data Cabling
- **Cable:** Cat 6 UTP/LSOH (file 15) + Fibre OM3/OS2 (file 16)
- **Route:** Dedicated data cable tray above racks (overhead) or below (raised floor)

## Voltage Drop Calculation

For long cable runs, verify voltage drop:
```
Vd = (I × L × Zc) / 1000

Where:
  I = current (A)
  L = cable length (m) - one way
  Zc = cable impedance (mV/A/m) = sqrt(Rac² + Xac²) × 1000
  Rac = AC resistance from catalog (ohm/km)
  Xac = reactance from catalog (ohm/km)

Acceptable: Vd < 5% of nominal voltage (i.e. < 20V on 400V 3-phase)
```

If voltage drop exceeds 5%, upsize the cable or shorten the run.

## File Index

| File | Cable Type | Key Use |
|---|---|---|
| README.md | Overview & selection guide | Start here |
| 01_lv_sdi_xlpe_copper.md | LV SDI Copper | Main power distribution |
| 02_lv_sdi_xlpe_aluminium.md | LV SDI Aluminium | Cost-effective large feeders |
| 03_lv_orange_circular.md | Orange Circular XLPE | Sub-mains, PDU feeds |
| 04_lv_orange_circular_swa.md | Orange Circular SWA | Armoured sub-mains |
| 05_lv_varolex_vsd.md | VAROLEX VSD | Cooling motor drives |
| 06_lv_varolex_vsd_emc.md | VAROLEX VSD/EMC | EMC-rated motor drives |
| 07_lv_powerlex.md | POWERLEX Flexible | Equipment tails |
| 08_lv_control_instrumentation.md | Instrolex/Control | BMS, instrumentation |
| 09_lfh_single_core.md | LFH Single Core 110C | Fire-safe power |
| 10_lfh_multicore.md | LFH Multicore 110C | Fire-safe sub-mains |
| 11_fr_single_core.md | Alsecure PLUS FR | Essential services |
| 12_mv_xlpe_single_core.md | MV XLPE Single Core | HV incoming supply |
| 13_mv_xlpe_three_core_swa.md | MV 3C SWA | Underground MV |
| 14_mv_triplex.md | MV Triplex URD | Underground reticulation |
| 15_data_lan.md | LAN Cat5e/Cat6 | Structured cabling |
| 16_fibre_optic.md | Optical Fibre | Backbone/inter-rack |
| data_comms_cables.md | Extended data/comms | Full scrape detail |
| mv_cables.md | Extended MV data | Full scrape detail |
