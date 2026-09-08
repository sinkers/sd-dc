# Cable Tray Joining Rules

## The Core Problem

Cable tray components have **raised side rails** (20-150mm depending on system). You cannot simply butt two components together end-to-end because:
- Two raised edges meeting creates a gap/interference
- No structural continuity across the joint
- No electrical continuity for earthing
- Cables cannot smoothly transition across the bump

Every joint between components requires a **specific connection method** that resolves the raised-edge interface.

---

## System-Specific Connection Methods

### CT System (Pre-Made Fittings)

**Connection Interface: TAPERED EDGES**

CT tray and all CT fittings (CTB, CTT, CTC, CTIR, CTER) have taper-folded edges at their ends. One end tapers IN, the other tapers OUT. They telescope together:

```
STRAIGHT CT                    CTB BEND
   ___________                ___________
  |           |←─ taper ─→  |           |
  |  ┌─────┐ |   slides    | ┌─────┐  |
  |  │     │ ╞═══INTO══════╡ │     │  |
  |  └─────┘ |   each      | └─────┘  |
  |___________|   other     |___________|
```

**Rules:**
1. Tapered end of fitting slides INTO the straight tray (or vice versa)
2. Overlap is approximately 30-50mm
3. Secure with M6 x 10 screw + M6 flanged nut through base perforations
4. Fastener code: WIZZ
5. **ALL CT fittings use 150mm fixed radius** (no other radius available)
6. Side walls are only 20mm - minimal interference at joints

### ET3/ET5 System (Field-Fabricated)

**Connection Interface: SPLICE PLATES + FIELD CUTS**

ET3/ET5 tray is a one-piece formed section with tall side rails (ET3=50mm, ET5=85mm). Fittings are NOT separate tray pieces - they are **brackets/templates** used to FABRICATE bends in the tray itself.

**Straight-to-Straight Joint:**
```
   TRAY 1         SPLICE         TRAY 2
   _______    _______________    _______
  |       |  |   ET3S/ET5S   |  |       |
  | rail  |  | (flat plate)  |  | rail  |
  |  ┃    ╞══╡  sits on      ╞══╡   ┃  |
  |  ┃    |  |  outside of   |  |   ┃  |
  |__┃____|  |  both rails   |  |___┃__|
             |_______________|
```
- **ET3S / ET5S Splice** plate bridges across the joint
- Bolted through both side rails with SBH/CNH fasteners
- One splice per side (2 per joint)

**Horizontal Bend (using Radius Plate RP):**
```
  The tray is CUT at the bend point:
  
  1. Mark bend location using RP as template
  2. Cut both side rails with tin snips
  3. Bend the tray base to desired angle
  4. RP sits UNDERNEATH the base, supporting the curve
  5. Splice plates close the cut in the side rails
  
      RP underneath
         ╔═══╗
    ─────╢   ╟─────
    rail ║   ║ rail (re-joined with splice)
    ─────╢   ╟─────  
         ╚═══╝
```
- **ET3RP / ET5RP Radius Plate** = curved plate that goes UNDER the tray base at the bend
- Side rails are cut, bent, and re-spliced
- Any angle possible (not just 90°)
- Radius determined by how far from the cut you place the RP

**Tee or Cross (using TX Bracket):**
```
  Main run is CUT, branch tray butts in:
  
      Main tray (continuous)
    ══════╤═══════════╤══════
          │  TX       │
          │ bracket   │
          │ bridges   │
          ╧═══════════╧
          Branch tray
```
- **ET3TX / ET5TX Tee Cross Bracket** = L-shaped bracket
- Main tray side rail is CUT to create opening
- Branch tray slides in and TX bracket bolts across the joint
- For a CROSS: both sides of main tray are cut, two branches enter

**Vertical Bend (using Riser Link RL):**
```
  Horizontal tray         Vertical tray
    ════════╗              ║
            ║   RL         ║
            ╠══link══╗     ║
            ║         ║    ║
            ╚═════════╝    ║
```
- **ET3RL / ET5RL Riser Link** = angled bracket connecting horizontal to vertical
- Tray is cut at the transition point
- RL bolts across the joint, bridging the angle change

### NEMA Cable Ladder (Factory-Made Fittings)

**Connection Interface: SPLICE PLATES ON SIDE RAILS**

NEMA ladder consists of two parallel side rails with rungs between them. Fittings (bends, tees, crosses) are separate factory-made pieces with their own side rails and rungs.

**Straight-to-Straight:**
```
  Rail 1          Splice plate        Rail 2
  ┃               ┌──────────┐        ┃
  ┃───rung───┃    │ overlaps │    ┃───rung───┃
  ┃           ┃═══╡ both     ╞═══┃           ┃
  ┃───rung───┃    │ rails    │    ┃───rung───┃
  ┃               └──────────┘        ┃
```
- Standard splice or N1 hanging splice
- 4 bolts per side (2 per rail end)
- Splice plate sits on OUTSIDE of rails

**Straight-to-Bend:**
```
  Straight rail      Splice     Bend fitting rail
  ┃                  plate      ┃
  ┃───rung───┃    ┌──────┐    ┃╲
  ┃           ┃═══╡      ╞═══┃  ╲ (curved rungs)
  ┃───rung───┃    └──────┘    ┃   ╲
  ┃                            ┃    ╲
```
- Bend fittings are complete ladder sections with curved rungs
- Connect to straight sections via splice plates
- Standard radii: 300mm (NEMA1) or 450mm (NEMA2/3/4)
- Custom radii: 600mm, 900mm available

**Straight-to-Tee:**
```
  Main ladder continues through the tee fitting.
  Branch exits at 90°. The tee fitting IS the junction
  piece - all three arms terminate with splice connections.
  
       ┃═══splice═══┃ (main continues)
       ┃    TEE     ┃
  ═════╡  FITTING   ╞═════  (main through)
       ┃            ┃
       ┃═══splice═══┃ (branch exits)
```
- Tee fitting has 3 splice points
- Cross fitting has 4 splice points
- Each arm connects to adjacent straight/bend via splice plate

---

## Universal Rules (All Systems)

### Rule 1: No Direct Butt Joints
Two tray sections NEVER touch edge-to-edge without a connection mechanism between them.

### Rule 2: Support Within 300mm of Any Joint
AS/NZS 3000 cl. 3.9.5 requires an additional support bracket within 300mm of:
- Any direction change
- Any termination point
- Any tee/cross junction

### Rule 3: Electrical Continuity
Every joint must maintain earth continuity:
- Pre-galv (G finish): Use star washers or serrated flange nuts to cut through coating
- HDG (H finish): May need paint removed at contact points
- If in doubt: fit separate earth bonding strap across joint

### Rule 4: Bend Radius Must Suit Cables
The tray bend radius must be >= the minimum bend radius of the LARGEST cable in the tray.
- CT system: Fixed 150mm radius (only suitable for small cables)
- ET3/ET5: Field-adjustable radius (use RP at appropriate distance)
- NEMA ladder: 300mm or 450mm standard; 600/900mm for large cables

### Rule 5: Fitting Sequence
Components connect in this order (not interchangeable):

```
[Straight] ──splice──> [Straight]           (S)
[Straight] ──splice──> [Bend] ──splice──> [Straight]    (NEMA/CT)
[Straight] ──cut+RP──> [Same tray bent]     (ET3/ET5 - no separate piece)
[Straight] ──cut+TX──> [Branch straight]    (ET3/ET5 tee)
[Straight] ──splice──> [Tee] ──splice──> [Straight] + [Branch]  (NEMA/CT)
```

### Rule 6: Reducer Between Different Widths
When tray width changes (e.g., 600mm → 300mm at a branch):
- Use a **straight reducer** fitting
- Connects via splices at each end
- Length is typically 600mm transition

### Rule 7: Cover Continuity
If covers are used, bend/tee/cross fittings have MATCHING cover fittings:
- Straight cover → Bend cover → Straight cover (all separate pieces)
- Cover clips onto side walls - no additional hardware

---

## Joint Type Inventory (for 3D modelling)

| # | Joint Type | Systems | Key Dimension | 3D Note |
|---|---|---|---|---|
| 1 | Straight splice | All | Overlap length (50-100mm) | Splice plate visible on outside of rails |
| 2 | Horizontal 90° bend | All | Radius (150/300/450/600/900mm) | Curved section between two straights |
| 3 | Horizontal 45° bend | NEMA/ET | Radius + angle | Same as 90° but half-turn |
| 4 | Tee junction | All | Radius at branch entry | T-shaped intersection |
| 5 | Cross junction | All | Radius at all 4 arms | X-shaped intersection |
| 6 | External riser (up) | All | Radius at top/bottom | Vertical curve, cable on outside |
| 7 | Internal riser (down) | All | Radius at top/bottom | Vertical curve, cable on inside |
| 8 | Straight reducer | NEMA | W1 to W2, length | Tapered section |
| 9 | Offset (S-bend) | NEMA/ET | 2x radius + straight | Two bends in opposite directions |
| 10 | Drop-out | All | Opening in base | Access point for cable exit |
| 11 | End cap | All | Tray width | Closes open end |
| 12 | Wall penetration | All | Tray width + firestop | Through-wall with sleeve |

---

## Critical Modelling Error to Avoid

**WRONG (what was in the previous model):**
```
Straight tray section ──directly touches──> Bend section
(Both have raised rails meeting at a point = impossible physically)
```

**CORRECT:**
```
ET3/ET5: Straight tray is CUT and BENT in place (one continuous piece)
         RP sits underneath, splice plates close the rail cuts
         
NEMA:    Straight ──splice plate──> Bend fitting ──splice plate──> Straight
         (3 separate pieces with splice hardware between each)
         
CT:      Straight ──tapered overlap──> CTB bend ──tapered overlap──> Straight
         (telescope fit with WIZZ screws)
```
