# ParaView recipe

`plot_slice.py` already produces the headline picture with no ParaView install.
Use ParaView when you want to explore the result interactively or produce 3D
views for a report.

## Opening the case

1. Install ParaView (<https://www.paraview.org/download/>), version 5.11+.
2. Open `case/case.foam`.
3. In the Properties panel:
   - **Case Type**: `Reconstructed Case`
   - **Mesh Regions**: `internalMesh`
   - **Cell Arrays**: `T`, `TdegC`, `U`, `p_rgh`
   - Click **Apply**, then step to the last time value on the toolbar.

`TdegC` is temperature in degrees Celsius, written by a function object
specifically so you never have to subtract 273.15 in the GUI.

## Fixed colour scale

Do this first, and do it identically for every run you want to compare.
Without it ParaView rescales per run and two different results look identical.

- Colour by `TdegC`
- **Rescale to Custom Data Range**: `18` to `40`
- Preset: **Turbo** (or *Cool to Warm (Extended)*)
- Tick **Use Below/Above Range Colors** so out-of-range air is obvious

## The four views worth building

### 1. Centreline vertical slice — the main diagnostic
`Slice` filter, Y Normal, origin `(2.2, 0.3, 1.5)`.
Colour by `TdegC`.

This is the same view `plot_slice.py` renders. Read it as: cold aisle should be
uniformly blue right up to the cabinet face; the hot aisle should be uniformly
red; the boundary between them should sit *at* the containment, not inside the
cold aisle.

### 2. Airflow direction — is air going the right way through the gap?
On the slice, add `Glyph`:
- Glyph Type **Arrow**, Orientation Array `U`, Scale Array `U`
- Scale Factor ~`0.08`, Glyph Mode **Every Nth Point**, Stride `4`
- Colour by `TdegC`

Look at the gap above the containment. Arrows pointing **right** (into the hot
aisle) are cold-air bypass — wasteful but safe. Arrows pointing **left** (back
into the cold aisle) are hot-air recirculation, and that is what pushes the
server intake temperature up.

### 3. Delivery path — streamlines from the fan wall
`Stream Tracer` on the `internalMesh`:
- Seed Type **Point Cloud**, Center `(0.05, 0.3, 1.5)`, Radius `0.9`,
  Number of Points `400`
- Integration Direction **FORWARD**
- Colour by `TdegC`, then `Tube` filter with radius `0.01` to make them visible

Cold streamlines that reach the cabinet face are doing useful work. Streamlines
that loop back into the cold aisle without entering the cabinet are short-
circuiting the supply.

### 4. Hot-air escape — isosurface
`Contour` on `TdegC` at value `27`.

Anything on the cold-aisle side of the containment is air the servers will
ingest above the ASHRAE recommended limit. In a healthy design this surface
hugs the containment plane and never reaches x = 1.8 m.

## Comparing runs side by side

After `./sweep.sh`, each run is a full case under `runs/<tag>/`. Open several
`case.foam` files at once and use **View > Split Horizontal** with
**Link Camera** so they pan together. Keep the 18–40 °C scale on all of them.

## Screenshotting from the command line

If you have ParaView installed, `pvbatch` can drive the same views headlessly:

```bash
pvbatch --force-offscreen-rendering your_script.py
```

This repository deliberately does not ship a `pvbatch` script, because
`plot_slice.py` covers the automated-image use case without requiring ParaView
at all.
