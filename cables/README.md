# Data Centre Cable Catalog - Nexans Australia

## Purpose

This catalog provides a BIM-ready reference library of cables from Nexans Australia (nexans.com.au) for use in data centre 3D modelling. It contains structured specifications enabling an AI agent to:

1. **Select appropriate cables** based on electrical requirements (voltage, current, distance)
2. **Generate accurate 3D cable models** with correct dimensions (OD, bend radius)
3. **Validate designs** against thermal, mechanical, and fire safety constraints
4. **Route cables** respecting minimum bend radii and pulling tensions

## Agent Instructions

When generating 3D cable models or cable routing systems for data centres, follow this process:

### Step 1: Determine Requirements
- What is the voltage level? (LV 0.6/1kV, MV 6.6kV/11kV/22kV/33kV)
- What is the load current required?
- What is the cable run length? (affects voltage drop and derating)
- What is the installation method? (ladder/tray, conduit, direct burial, enclosed)
- Is fire rating required? (LFH = Low Fire Hazard, FR = Fire Resistant)
- Is EMC screening required? (VSD cables for motor drives)
- Copper or aluminium conductor?

### Step 2: Select Cable Type
Use the selection matrix below:

| Application | Cable Type | File Reference |
|---|---|---|
| Main power distribution (LV) | XLPE/PVC SDI Single Core | `01_lv_sdi_xlpe_copper.md` |
| Main power (LV, cost-sensitive) | XLPE/PVC SDI Aluminium | `02_lv_sdi_xlpe_aluminium.md` |
| Sub-mains, PDU feeds (LV) | Orange Circular XLPE 3C+E/4C+E | `03_lv_orange_circular.md` |
| Sub-mains armoured (LV) | Orange Circular SWA XLPE | `04_lv_orange_circular_swa.md` |
| VSD/cooling motor feeds | VAROLEX VSD 3C+3E | `05_lv_varolex_vsd.md` |
| VSD with EMC requirements | VAROLEX VSD/EMC 3C+3E | `06_lv_varolex_vsd_emc.md` |
| Flexible connections | POWERLEX Heavy Duty | `07_lv_powerlex.md` |
| Control & instrumentation | Instrolex Pairs/Triples | `08_lv_control_instrumentation.md` |
| Fire-rated power (LFH) | Nexans LFH Single Core 110C | `09_lfh_single_core.md` |
| Fire-rated multicore (LFH) | Nexans LFH Multicore 110C | `10_lfh_multicore.md` |
| Fire-resistant (FR) | Alsecure PLUS Single Core | `11_fr_single_core.md` |
| MV switchgear feeds | MV XLPE Single Core | `12_mv_xlpe_single_core.md` |
| MV distribution (armoured) | MV XLPE Three Core SWA | `13_mv_xlpe_three_core_swa.md` |
| MV underground reticulation | MV Triplex URD | `14_mv_triplex.md` |
| Data (structured cabling) | LAN Cat5e/Cat6 | `15_data_lan.md` |
| Fibre backbone | Optical Fibre | `16_fibre_optic.md` |

### Step 3: Size the Cable
1. Look up the current carrying capacity table for the selected cable type
2. Apply derating factors for:
   - Ambient temperature above 40C (common in data centres)
   - Grouping/bundling on cable trays
   - Installation method
3. Select the smallest conductor size where derated capacity >= required current
4. Verify voltage drop over the run length is acceptable (< 5% for sub-mains)

### Step 4: Generate 3D Model Parameters
For each cable in the routing, extract from this catalog:
- **Outer Diameter (mm)** - for cable tray fill calculations and conduit sizing
- **Minimum Bend Radius - Installation (mm)** - for routing geometry
- **Minimum Bend Radius - Installed (mm)** - for final resting position
- **Weight (kg/m)** - for tray loading calculations
- **Maximum Pulling Tension (kN)** - for installation feasibility

### Step 5: Model the Cable Cross-Section
Cable construction (inside to outside):
1. **Conductor** - copper (brown/orange) or aluminium (silver)
2. **Insulation** - colour-coded per AS/NZS 3000 (Active: Red/White/Blue, Neutral: Black, Earth: Green/Yellow)
3. **Bedding/Filler** - where applicable (grey)
4. **Screen/Shield** - copper tape or wire (for VSD/MV cables)
5. **Armour** - steel wire (SWA) where applicable
6. **Outer Sheath** - PVC (black/orange) or HDPE or HFS (LFH/FR)

### Colour Conventions for 3D Models
| Sheath Type | Colour |
|---|---|
| Standard PVC (SDI) | Black |
| Orange Circular | Orange |
| LFH/FR | Black (with red stripe for FR) |
| MV cables | Red or Black |
| Data cables | Grey/Blue |
| Fibre optic | Yellow (SM) / Orange (MM) |

### Key Derating Factors (AS/NZS 3008.1)
| Condition | Multiplier |
|---|---|
| Ambient 45C (vs 40C reference) | 0.93 |
| Ambient 50C | 0.87 |
| Ambient 55C | 0.79 |
| 2 cables grouped | 0.87 |
| 3 cables grouped | 0.80 |
| 6 cables grouped | 0.72 |
| 9 cables grouped | 0.69 |
| Cable tray (touching, single layer) | per Table 22 AS/NZS 3008 |

### Cable Tray Fill Rules
- Maximum 50% fill for power cables (allows heat dissipation)
- Maximum 40% fill for control/data cables
- Maintain 300mm separation between power and data trays
- Single layer preferred for high-current cables (>200A)

## Source
All specifications sourced from Nexans Australia (www.nexans.com.au) product catalog, August 2026.
Standards: AS/NZS 5000.1, AS/NZS 1429.1, AS/NZS 3008.1, AS/NZS 3013, IEC 60502
