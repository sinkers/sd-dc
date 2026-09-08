# Cooling model

Parametric FreeCAD geometry for a closed-loop cooling plant. Builds the plant as
solid 3D geometry from a script, so a layout change is an edit and a re-run
rather than CAD work.

The oldest component here, and the smallest. It predates `piping/`, which has
since taken over routing properly — see [Relationship to `piping/`](#relationship-to-piping).

## What it builds

`create_cooling_system()` produces a closed loop:

| Item | Count | Notes |
|---|---|---|
| Dry cooler | 1 | 2.5 MW, outdoor unit with a fan array |
| Pumps | 3 | in parallel on the supply manifold |
| CDUs | 3 | Vertiv XDU 1350, rack-mounted |
| Piping | — | supply and return, with headers and manifolds |

Coordinates are `X = width, Y = depth, Z = height`, in millimetres, matching the
rest of the toolkit.

## Running it

Needs FreeCAD. It imports `FreeCAD` and `Part` directly, so it runs inside
FreeCAD's Python, not a plain interpreter — either the GUI console or the
headless VM in [`../vm-setup/`](../vm-setup/).

```python
exec(open('/path/to/cooling-model/model_cooling_system.py').read())
create_cooling_system()
```

## Outputs, and which are worth keeping

| File | What |
|---|---|
| `CoolingSystem.FCStd` | the FreeCAD document — the editable master |
| `CoolingPlant.step` | STEP export of the plant |
| `PumpSkid_Test.step`, `.obj` | pump skid, for import elsewhere |
| `PipingDemo.step` | piping-only export |
| `*_render.svg` | rendered views |

All are regenerable from `model_cooling_system.py`. They are committed because
FreeCAD is a heavy dependency and a reader should be able to see the result
without installing it.

## Helper functions

`make_box`, `make_cylinder`, `make_pipe` and `make_pipe_simple` are small
wrappers over `Part` primitives. `make_pipe` builds a hollow pipe between two
points; `make_pipe_simple` a solid cylinder where the bore does not matter.

## Relationship to `piping/`

This component draws pipes between points it is told about. It does not route
them: no obstacle avoidance, no bend-radius validation, no check that
consecutive segments actually meet.

[`../piping/`](../piping/) does all of that — A* routing on a grid, orthogonal
runs, and the minimum-segment-length constraint that stops two elbows
overlapping. New work belongs there.

What is still useful here is the **plant layout**: where the dry cooler, pumps
and CDUs sit relative to each other, and the manifold arrangement. `PLAN.md`
folds that into the layout engine's catalogue, at which point this becomes a
reference implementation rather than a live component.

## Status

Working, 313 lines, **no tests**. `QUALITY.md` rates it low-risk to refactor
because it is small and its output is visually obvious when wrong — a geometry
bug here produces a picture that looks incorrect, unlike `piping/`, where a
0.4 mm gap between segments is silent until STEP export fails.
