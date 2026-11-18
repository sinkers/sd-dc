# Question bank

One section per round. Each question names the brief field it fills (see
`../templates/brief.template.yaml`), what to look for in the project documents
before asking, and what "answered" means. Ask the documented proposal first;
ask cold only when nothing holds the answer.

Format of each entry: **field** — question. *Look in:* where to find a proposal.
*Done when:* the test for a closed answer.

---

## R0 Project and deliverables

- **project.code / project.name** — What is the project code and site name? *Look in:* the site pipeline, folder names, document register. *Done when:* the code matches the register (for example AU013, not AU01).
- **project.folder** — Where should the brief, models and outputs live? *Look in:* the project library on SharePoint/OneDrive. *Done when:* it is a path outside this repo.
- **deliverables** — Which of D1 to D10 are wanted, and by when? Offer the full set, with D1, D2 and D3 always on. *Done when:* each has yes/no and a date or "with the brief".
- **numbering** — Have document numbers been allocated for the brief, the model and the drawings, or should they be requested? *Look in:* the document register. *Done when:* numbers allocated or an OPEN item raised with the document controller.
- **reference_design** — Is this site derived from a reference design (for example RD110), a previous site's model, or nothing? *Done when:* named with revision, or "none".

## R1 Site

- **site.address / site.title** — Street address, title reference (allotment, plan), and council. *Look in:* master plan brief, planning documents.
- **site.boundary.source** — What defines the boundary DAME controls: the title, a lease plan, or a concept plan? Which document and revision? *Done when:* a polygon source is named. A concept-plan markup is acceptable only if the user accepts it as such (status `assumption`).
- **site.crs / site.datum** — Coordinate system (MGA zone) and height datum (AHD). *Look in:* the survey. *Done when:* both stated, or the model is declared local-only.
- **site.survey** — Is there a feature survey or TIN? File, date, surveyor, extent. *Done when:* named, or OPEN with an owner.
- **site.aerial** — Aerial imagery source and date, and whether it is georeferenced. If it is not, which three or more control points (title corners, road centreline points) fix it? *Done when:* control points listed, or `assumption: hand-registered`.
- **site.access** — Where vehicles enter from, and which road authority owns it. Is any road in the drawings not built (a turning head drawn but not there)? *Done when:* each entry point is located; anything drawn but absent is flagged.
- **site.setbacks / easements / overlays** — Boundary setbacks, easements (powerlines, services), planning overlays. *Look in:* planning advice, title. *Done when:* each is a `must` with its instrument, or `none found`.
- **site.pad** — Finished pad level (AHD), or the rule for setting it (balance cut and fill, a level above flood). *Done when:* a level or a rule, with the rule's source.
- **site.existing** — Existing structures, trees, fences or services that stay, go or need protecting. *Done when:* each listed with keep/remove.

## R2 Programme

- **programme.it_mw / total_mw** — IT load and total connected load, firm and flexible. *Look in:* the grid connection strategy, the proposal.
- **programme.density** — kW per rack, rack count, rack type (e.g. GB300 NVL72), and how they group into pods.
- **programme.cooling** — Cooling topology (DLC plus fan wall, chillers, dry coolers), design ambient (ASHRAE conditions file), PUE target.
- **programme.redundancy** — Electrical and mechanical redundancy (N, N+1, 2N) per system, as `must` (contract) or `feasibility`.
- **programme.phases** — Build phases and what is in each. *Done when:* each collection of equipment has a phase.

## R3 Buildings

Ask per building (data hall, office, plant buildings).

- **building.footprint.source** — Drawing number and revision of the footprint, or the reference design block. *Done when:* outline dimensions and position (or the rule for it, such as "centred on the hall's south face").
- **building.storeys** — For each storey: name, FFL (mm above pad), floor-to-floor, clear height, slab build-up. *Look in:* the sections (e.g. ARC-030). *Done when:* every storey has FFL and clear height.
- **building.roof** — Roof type (gable, mono-pitch, flat with parapet), pitch, eave and ridge heights, parapet height. *Done when:* enough to build it.
- **building.structure** — Structural grid and frame spacing (portal frames at x m), column sizes if known.
- **building.envelope** — Wall and roof cladding, glazing types. Colours only if wanted for renders.
- **building.voids** — Areas with no floor above (double-height logistics strips, plant voids).

## R4 Rooms

Ask per storey. Room data sheets are the source; the plans place them.

- **rooms[]** — For each room: number, name, storey, area (from the room data sheet), security zone, and polygon (from the plan). *Look in:* the room data sheets (e.g. ARC-100) and the plans (ARC-011/012). *Done when:* every room has number, storey, zone and an area to check against.
- **rooms.adjacency** — Required adjacencies and separations (the NOC on the hall wall; visitors never reach the portal). Tag each `must` or `feasibility`.
- **openings[]** — Doors, shutters and windows: type, size, wall, sill and head heights, security class (MFA, card, fire egress). *Look in:* the plans' opening legend and the sections. *Done when:* every external opening and every security door is listed.
- **vertical.circulation** — Stairs and lifts: location, which storeys, egress rating.

## R5 Plant and yards

- **plant[]** — Every equipment item: tag, catalogue reference (or vendor block), footprint, height, weight, position source. *Look in:* the GA (e.g. the Schneider 10 MW layout), the catalogue. *Done when:* catalogue ref plus position for each; any envelope taken off a scaled GA is `assumption`.
- **plant.clearances** — Placement and clearance rules (ARC-200 or the vendor's), quoted with their source. *Done when:* each rule states what is spaced from what, with the value.
- **plant.access** — Crane and maintenance access, delivery routes, laydown.

## R6 Site works

- **fence.rule** — Which line the security fence follows: the lease boundary, an offset of the compound, or something else. Height and type. *Done when:* the rule is stated well enough to compute the line.
- **gates[]** — Number, width, type (sliding or swing), and where (which road crosses the fence).
- **roads[]** — Driveway, truck apron, turning: widths and the design vehicle.
- **parking** — Bay count, accessible count, layout preference. Dimensions come from the standard the user names (for example AS/NZS 2890.1 and 2890.6), quoted from the standard. If it is not to hand, record the dimensions as OPEN. *Done when:* counts plus a sourced dimension set.
- **lighting / drainage / landscaping** — In scope or not; if in scope, the rule.

## R7 Connections (IndustroML)

- **electrical** — Single line diagram source and revision: utility supply, MV, transformers, LV boards, UPS, PTUs, busway to racks. *Look in:* SLD, connection schedule.
- **mechanical** — P&ID source: chillers, pumps, headers, CDUs, fan walls, pipe sizes.
- **data / control / safety** — Fibre entries, MMRs, BMS/EPMS, fire panel.
- **routes** — Trays and pipe racks connections run through, if known.

*Done when:* every asset in R5 has its interfaces and every interface is in a connection, or the gap is OPEN.

## R8 Visualisation and staging

- **groups** — Which parts must be toggled independently (each roof, each storey, each yard).
- **flyover.shots** — The story: establishing orbit, approach, roof lifts, walkthroughs, levels. *Done when:* shot list with durations.
- **flyover.build_sequence** — Order the parts drop into place, as stages. Reuse the project's 4D stage matrix if one exists.
- **flyover.quality** — Draft or final, resolution, length, and who it is for.

## R9 Checks

- **checks[]** — Which checks run (clash, inside the lease, setbacks, room areas against the RDS, ARC-200 placement, fence closure, parking count) and the pass rule for each.
- **signoff** — Who reviews the model and the brief, and in which review class.
