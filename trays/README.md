# Trays: cable tray runs, their cables and their supports

Routes a cable tray run with the pipe router (`../piping/core`), sizes the
circuits on it with the cable sizing calculator (`../cable-sizing`), puts
ground-mounted supports under it, and builds it as a 3D model. Served as the `tray_route_and_support` tool
by the piping MCP server, and as `POST /api/tray` by its REST server.

```
python3 tools/demo.py            # invented yard scene -> out/tray_demo.png
python3 -m pytest -q tests
```

## Files

| File | What |
|---|---|
| `tray.py` | tray types, routing, span and ground supports |
| `cables.py` | sizes circuits with cable-sizing, works out mass, footprint and where each core lies |
| `model3d.py` | the 3D model as primitives (no FreeCAD): ladder rails and rungs, bends, posts, every core |
| `freecad_build.py` | runs inside FreeCAD (`freecadcmd`) and turns the primitives into FCStd and STEP |
| `schedule.py` | the cable schedule as CSV and Markdown |
| `service.py` | the request in, result out; served by the piping MCP and REST servers |

## Circuits

Give `circuits` instead of a cable weight: each has kW, kVA or amps, and
optionally power factor, voltage, cable type, formation (trefoil by default),
ambient, fault level, harmonics, and `tails_m` (cable beyond the tray). Each
is sized by the AS/NZS 3008 engine for the tray route length plus tails, with
every circuit and parallel run on the tray counted for grouping (re-sized
until the count settles). The result lists, per circuit: cable description,
length, design current against derated capacity, voltage drop (V and %)
against its limit, fault current, operating temperature, mass and footprint;
plus metres of each cable to order. The cable mass sets the support span, and
a tray too narrow (`tray_full`), too shallow (`above_rails`) or with bends too
tight for the cable (`bend_too_tight`) is an issue.

## 3D model

Add `"model": {}`. The service always produces the primitives, and builds
them with FreeCAD when `freecadcmd` is found (`FREECADCMD`, the PATH, or the
macOS app). Files go to `out/models/<id>.FCStd|.step` (`TRAY_MODEL_DIR`), one
object per group: `tray`, `supports`, `context`, and `cable:<circuit>`. Each
profile keeps its place in the tray's cross-section through bends and risers,
so cables on the inside of a bend take a tighter radius, as on site.

## What it does

1. **Route** (or take `points` as drawn). The tray's envelope is its overall
   width; bends use the fitting's centreline radius.
2. **Span.** Cable load plus growth (default 25 %) picks the longest
   published span whose rated load covers it. The rating excludes tray self
   weight; self weight is added when sizing each support.
3. **Positions.** A support within `near_fitting_mm` (600) of each bend,
   riser and termination, then at a pitch that divides the standard length,
   so splices land beside supports. No gap exceeds the span.
4. **Splices.** Any splice not within a quarter span of a support gets one.
5. **Fit.** Each support is a post (cantilever bracket) or two posts
   (goalpost) from the floor to the tray underside, with base plates. Posts
   and plates are clash-checked against every obstacle; a blocked support
   tries the other side, then slides along the run.
6. **Report.** Positions, post heights, support loads, a BOM, and issues:
   `support_blocked`, `span_exceeded`, `splice_unsupported`, `overloaded`.
   Vertical runs come back as `riser_fixing` open items.

## Limits, said plainly

- **Draft, not a structural design.** Support ratings in `tray.SUPPORTS` are
  the AU01-2 drawing values carried over from `cable_tray_router.py`,
  unverified against a datasheet. Posts over 4 m are flagged for bracing.
- Rules 3 and 4 follow NEMA VE 2 practice; project specifications override
  them through the options.
- Only ground supports so far. Wall brackets, trapezes from structure and
  riser fixings are next.
- Bend radius is not in the catalogue; it defaults to the tray width, as the
  old router assumed. Pass the real fitting radius.
- Tray data comes from `../cable-tray-ezystrut/tray_catalogue.json` when
  present (vendor data, not in git), or a full tray description in the
  request. Tests and the demo use synthetic numbers.
- Clearance follows the tray's cross-section on horizontal runs (half its
  depth above and below, half its width sideways). Risers get half the
  width on every side, because their orientation is not tracked yet.
- Ladder bends are modelled as rails and cables only: no rungs in the bend.
- Cable layout is one layer of trefoils (or flat), circuits side by side in
  the order given; no segregation rules between services yet.
- Cable sizing needs the cable catalogue (vendor data, local only); without
  it a request with circuits is refused with a clear message.

`../cable-tray-ezystrut/cable_tray_router.py` is the earlier hand-scripted
router; its FreeCAD ladder geometry is still the way to build solids.
