# Trays: cable tray runs and their supports

Routes a cable tray run with the pipe router (`../piping/core`) and puts
ground-mounted supports under it. Served as the `tray_route_and_support` tool
by the piping MCP server, and as `POST /api/tray` by its REST server.

```
python3 tools/demo.py            # invented yard scene -> out/tray_demo.png
python3 -m pytest -q tests
```

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
- Clearance uses one envelope for every axis, so a wide, shallow tray keeps
  more room above and below than it needs.

`../cable-tray-ezystrut/cable_tray_router.py` is the earlier hand-scripted
router; its FreeCAD ladder geometry is still the way to build solids.
