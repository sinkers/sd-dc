---
name: brief-to-3d
description: Run the brief-to-3D process for a data centre site in sd-dc — quiz the user, round by round, for everything the brief needs (site, programme, buildings and storeys, rooms, plant, site works, connections, visualisation), then produce the deliverable set, an IndustroML model included. Use when someone wants to start a new site model, turn a floor plan or reference design into a 3D model, "build the brief", scope a site layout, or asks what information is needed to model a site.
---

# Brief to 3D

The standard architectural route from a brief to a model is: brief, then site,
then massing, then storeys and rooms, then elements (walls, slabs, roofs,
openings), then equipment and connections. Each step adds level of detail to
the step before. The model follows the IFC spatial tree: site, building, storey,
space, with elements hung off it. This skill runs that route for sd-dc. You quiz
the user until the brief is complete enough to build each level of detail,
record where every answer came from, and then produce the deliverable set.

The skill is the front end of the pipeline in `PLAN.md` (§0.2 layout IR, §2
layout engine, §4 geometry). Read those sections before the first round so the
questions match what the compilers consume.

## Ground rules

1. **Project data never goes in this repository.** The repo is headed for public
   GitHub (see `PUBLISH-REVIEW.md`). The brief, the IndustroML model, configs
   and every output go in the project's own folder (OneDrive/SharePoint) or a
   `private/` path that git ignores. Only templates live here. Put
   `# PRIVATE: project data. Do not commit to a public repository.` at the top
   of every project file you write, the way `planning/industroml-private/` does.
2. **Look before you ask.** Before each round, search the project's documents
   (the DAME drive search tool if connected, the project folder, existing FCStd
   models, room data sheets, reference designs such as RD110). Put what you
   find to the user as a proposed answer with its source, for them to confirm or
   correct. Only ask cold for what no document holds.
3. **Never invent a value.** An answer you cannot source is recorded as `OPEN`
   with an owner and the question that would close it. Do not fill a gap with a
   default that looks like a decision. A default is allowed only when the user
   says so, and it is recorded as `assumption`, with who accepted it.
4. **Split hard requirements from everything else.** Tag every requirement
   `must` (a legal or contractual obligation, citing the instrument) or
   `feasibility` (everything else, tested for whether it can be met). Do not add
   requirements nobody asked for. When you cite a standard, quote its text from
   the standard itself, never from commentary. If the standard is not to hand,
   record the clause as `OPEN` for the standards owner, through `spec-exchange/`
   if it is a cable or electrical question.
5. **Every item gets an ID** (`BR-SITE-001`, `BR-BLD-HALL-003`, ...) and a
   `source` (document number and revision, drawing, measurement, or "user,
   <date>"). Requirements state what is spaced from what, with a value and
   units.
6. **Ask in rounds, not walls.** Use the AskUserQuestion tool: at most four
   questions per call, multiple choice with the sourced proposal first and
   marked "(Recommended)" where you have one. Free-text values (levels,
   dimensions) go as a short plain-text question listing exactly what you
   need. Summarise what the round settled before starting the next one.
7. **Units:** millimetres in geometry, metres in prose, AHD for levels, the
   site's MGA zone for coordinates. Say which on every value you record.

## The rounds

Work through `references/question-bank.md` in this order. Skip a question
only when a document already answers it and the user has confirmed that
answer. Stop at the end of any round if the user wants a partial build. Each
round unlocks a level of detail, shown in the gate column.

| Round | Covers | Gate it unlocks |
|---|---|---|
| R0 | Project, deliverables, document numbers, where files land | — |
| R1 | Site: title and lease boundary, survey and datum, aerial, access, setbacks, pad level | site model, ground, fence line |
| R2 | Programme: IT MW, density, cooling, redundancy, phases, reference design | massing |
| R3 | Buildings: footprint, storeys (FFL, floor-to-floor, clear height), roof, structure grid, envelope | building shells |
| R4 | Rooms per storey: room data sheets, areas, security zones, adjacencies, door and window schedule | rooms, walls, openings |
| R5 | Plant and yards: equipment from the catalogue or GA, clearances, placement rules (ARC-200) | equipment placement |
| R6 | Site works: fence rule and gates, roads and aprons, car parking, lighting, drainage | site works |
| R7 | Connections: single line, P&ID, data, controls, connection schedule | IndustroML connections |
| R8 | Visualisation and staging: show/hide groups, fly-over shots, build sequence | renders, fly-over |
| R9 | Checks: what is tested, against which rule, and who signs off | check report |

At the end of every round, write the answers into the brief file straight away
(`templates/brief.template.yaml` is the shape). Do not hold them in the
conversation.

## Deliverables

`references/deliverables.md` is the full list with formats, naming and the
tool that makes each one. Confirm the set with the user in R0. The core set
is:

- **D1 Brief** (`<site>_brief.yaml`), every answer with ID, source and status.
- **D2 IndustroML model** (`<site>.industroml.yaml`), validated against
  `industroml.schema.json` with `validate_industroML.py`. This is
  non-negotiable; the rest of the stack reads it. How site, building, storey,
  room and yard geometry is carried in IndustroML v0.1 is set out in
  `references/industroml-geometry.md`. Follow it exactly. Where v0.1 has no
  type for something (a storey, a roof), record it in attributes as described
  there, and log the gap as an open item against the IndustroML schema. Never
  edit the schema from here.
- **D3 Open-items register**: every `OPEN` and every `assumption`, with an owner.
- **D4 FreeCAD model**, with the group convention in `references/deliverables.md`
  (per-storey and roof groups, so levels can be isolated).
- **D5 GLB plus parts table** for review, through `model-review/export.sh`.
- **D6 2D drawings as DXF** and **D7 STEP**, per DAME document control. Native
  FCStd alongside.
- **D8 IFC** once `layout/compile/ifc.py` exists. Until then, list it as
  pending; do not hand-make one.
- **D9 Fly-over**: a site config for `flythrough/` (shots, collections, build
  stages), then stills and the MP4.
- **D10 Check report**: clash, inside the lease, setbacks, room areas against the
  room data sheets, placement rules, each pass or fail with the measured value.

Numbering and revisions follow DAME-GEN-PRC-0001 (the dame-engineering-voice
and dame-document-controller skills, if present). A draft keeps one revision
(Rev 0.1) and is updated in place until it is sent for review.

## Building from the brief

Once R1 to R4 are closed, the brief is enough to build shells and rooms; R5 and
R6 add plant and site works. Until `layout/` exists, build with FreeCAD scripts
through the FreeCAD MCP bridge, in this order. Each step reads the brief and
the IndustroML model; none reads a value off a picture unless the brief says
that is its source.

1. Site: terrain mesh, parcels, the fence rule, the georeferenced aerial (fit it
   from control points; `aerial_nudge.py` is for fine-tuning only).
2. Shells: per building, storey slabs at FFL, external walls cut at each floor
   line, the roof as its own group.
3. Rooms: walls from room polygons, with shared edges built once and openings
   from the schedule. Labels sit on their storey.
4. Plant: catalogue instances at their positions, at real envelope heights.
5. Site works: the fence from the rule, gates where roads cross it, the car
   park and driveway from the counts and the dimensions the standard gives
   (quoted, not remembered).
6. Checks (D10), then exports (D4 to D9).

Address the document by name in every FreeCAD call
(`FreeCAD.getDocument(...)`), never `ActiveDocument`; another agent may be
working in FreeCAD at the same time. Save once a step checks clean.

## When you finish

Report which deliverables were made and where they are (SharePoint web-view
links, never download links), what is still `OPEN` and who owns it, and which
checks failed. Keep it short; the register and the check report hold the
detail.
