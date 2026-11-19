# Deliverable set

Every deliverable lives in the project folder, never in this repo. File names
follow DAME-GEN-PRC-0001 (`<PROJECT>-<DISC>-<TYPE>-<NNNN>_<REV>_<Title>.<ext>`)
once numbers are allocated. Before that, use `<site>_<deliverable>` and record
the number request as an OPEN item. A draft stays at one revision and is
updated in place until it goes for review.

| ID | Deliverable | Format | Made by | Required |
|---|---|---|---|---|
| D1 | Brief | `<site>_brief.yaml` (+ a rendered summary if asked) | this skill | always |
| D2 | IndustroML model | `<site>.industroml.yaml`, validated | this skill, then the layout engine | always |
| D3 | Open-items register | `<site>_open_items.yaml` (or a Jira epic, via post-to-jira) | this skill | always |
| D4 | FreeCAD model | `.FCStd`, with the group convention below | FreeCAD scripts via the MCP bridge; later `layout/compile/freecad.py` | when a model is wanted |
| D5 | Review model | `.glb` + `.parts.json` | `model-review/export.sh` | with D4 |
| D6 | 2D drawings | DXF per sheet (+ PDF for review) | `ezdxf` scripts; TechDraw for sections | when drawings are wanted |
| D7 | 3D exchange | STEP | FreeCAD export of D4 | with D4 |
| D8 | IFC | `.ifc` (IFC4) | `layout/compile/ifc.py` — **pending**; do not hand-make | when the compiler exists |
| D9 | Fly-over | site config `.json` + stills + `.mp4` | `flythrough/build_flythrough.sh` | when asked |
| D10 | Check report | `<site>_checks.yaml` (+ summary table) | check scripts | with every model build |

## D1 brief

Shape: `../templates/brief.template.yaml`. Every leaf answer is an object:

```yaml
pad_rl_m: {value: 120.00, units: m AHD, status: confirmed, source: "user, <date>", id: BR-SITE-009}
```

`status` is one of `confirmed` (sourced and accepted), `assumption` (accepted
by a named person without a source), `OPEN` (with `owner` and `question`).
Requirements carry `class: must` (with `instrument`) or `class: feasibility`.

## D2 IndustroML model

See `industroml-geometry.md`. It must pass:

```bash
python3 ~/workspace/industroml/validate_industroML.py <site>.industroml.yaml \
    --schema ~/workspace/industroml/industroml.schema.json
```

Exit 0 is the bar. Exit 2 (referential errors) means a connection points at an
interface that does not exist. Fix the model; do not loosen the check.

## D4 FreeCAD group convention

Group names are what the fly-over config, the review viewer and the checks key
off, so keep them stable:

```
<Layout part>                      App::Part carrying the layout frame (origin + yaw)
  _10_3D_Model
    _11_Data_Hall_3D               slab, columns, wall cladding
      _11a_Hall_Roof               roof cladding + rafters (toggle to see in)
    _12_Plant_3D                   gensets, MV pods, PTUs, chillers
    _13_Office_Block_3D
      _13a_Office_L1               L1 slab, L1 walls, glazing, stairs, labels
      _13b_Office_L2               L2 slab, L2 walls, glazing, labels
      _13c_Office_Roof             roof slab, parapet, lift overrun
    _14_Car_Park_3D
    _15_AI_Pods_3D                 solid racks + services, not links
_05_Site_Works_3D                  fence, gates (site coordinates)
_00_Aerial                         image plane(s)
_01_Terrain, _02_Contours, _03_Leased_Area, _04_Context   (2D reference)
```

Rules: one storey per group, so a level can be isolated; external walls cut at
each floor line; roofs always in their own group; anything placed as an
`App::Link` gets a solid copy under `_10_3D_Model` (links into a hidden
component library do not export); component libraries stay in a hidden
`_00_Components`.

## D9 fly-over

The site config is project data: keep it beside the model, not in the repo.
`flythrough/example.config.json` in the repo is the template. Collections in
the config must match the D4 groups; the shot list comes from R8.

## D10 check report

One entry per check: `id`, `rule` (with source), `measured`, `limit`, `result`
(pass/fail/not-run), `objects`. Minimum set: clash between solids, everything
inside the lease, setbacks, room areas against the room data sheets (state the
tolerance, for example ±5 %), fence closed, gate on every road crossing, parking
count, and every ARC-200 rule that applies.
