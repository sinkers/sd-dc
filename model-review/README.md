# model-review — FreeCAD to the browser

A model that only opens in FreeCAD can only be reviewed by whoever has FreeCAD,
the file, and ten minutes to wait for it. This turns an `.FCStd` into a single
GLB and a static viewer, so a review is a URL: orbit the plant, switch groups
off, cut a section, click a part and read the name it has in the model.

The AU01 building goes from a 263 MB FreeCAD document to a **7.4 MB GLB in about
90 seconds**, keeping every shown part individually named and selectable, and it
is published behind an unguessable path on the existing au01-twin box.

```
                 export.sh                       gltfpack                 three.js
DAME_AU01.FCStd ──────────▶ au01.glb ───────────▶ au01.packed.glb ──────────▶ browser
    263 MB      freecadcmd     77 MB    meshopt        7.4 MB      deploy.sh    ~1 s load
                            + au01.parts.json (part table, for diffing revisions)
```

## Run it

```bash
# Size the job before committing to it (meshes 150 parts, extrapolates).
./export.sh --fcstd "<model>.FCStd" --out /tmp/probe.glb --probe 150

# The real thing. Writes the GLB, the meshopt-packed GLB, and the part table.
./export.sh --fcstd "<model>.FCStd" --out viewer/model/au01.glb

# Review it.
./viewer/serve.sh                     # http://127.0.0.1:8771/
```

Options: `--deflection` (linear, mm, default 12), `--angular` (degrees, default
30), `--min-diag` (drop parts smaller than this, mm — useful for a fast
walkthrough build).

`FREECADCMD` overrides the FreeCAD console binary, which is how the same command
runs on a VM:

```bash
FREECADCMD=/usr/bin/freecadcmd ./export.sh --fcstd model.FCStd --out out/model.glb
```

## Publishing it

```bash
./deploy/deploy.sh              # first run mints the path, later runs reuse it
./deploy/deploy.sh --rotate     # mint a new path, retiring the old one
```

The viewer joins the air twin (`/`) and the liquid loop (`/loop/`) on the same
`t4g.small` as a third drop-in Caddy route, served straight off disk — no
service, no port, nothing to restart. The route is validated before Caddy
reloads and removed again if it does not validate, because that Caddyfile also
serves the two twins. A deploy moves ~8 MB and takes a few seconds.

The path is a UUID kept in `deploy/.published-path`, which is gitignored so the
URL does not travel with the repository. **It is obscurity, not
authentication** — anyone with the link, or anything that scrapes it from a
browser history, a chat thread or a referrer header, gets the full AU01 design.
Deliberate call, taken with the same reasoning as `digital-twin/DEPLOY-PLAN.md`.
Responses carry `X-Robots-Tag: noindex, nofollow, noarchive`, directory listing
is off, and adding a password is one `basic_auth` block in the route file plus a
re-run.

`Cache-Control: no-cache` rather than a long max-age, because the model keeps its
filename across exports: a cached copy would quietly show a stale model after the
next one. ETags make revalidation cheap.

## Shipping modelling work off a FreeCAD VM

Nothing here needs a GUI, a display, or a GPU. `export_glb.py` runs under
`freecadcmd`, reads the `.FCStd` off disk and writes a GLB, so the loop is:

1. Model on the VM (or let an agent drive FreeCAD there).
2. `./export.sh --fcstd model.FCStd --out viewer/model/<name>.glb` on the VM.
3. Copy `viewer/model/` to wherever the viewer is served. The viewer is four
   static files plus vendored three.js — any static host will do, no build step.
4. Send the URL.

`<name>.parts.json` is the reason to keep every export: it is a full part table
(FreeCAD name, label, tree path, mesh index, bounding box) so two revisions can
be diffed for what moved, appeared or vanished, without opening either model.

**Exports are project data, so they are not in this repo.** `viewer/model/` is
gitignored. A site's packed GLB and part table are kept in the private
`sd-dc-config` repo under `model-review/<site>/`; copy them into `viewer/model/`
to serve or deploy.

## What the exporter decides, and why

**Only visible objects.** FreeCAD hides a solid when a fusion, cut or compound
consumes it, so the visible set is exactly the set a reviewer sees. Taking
everything would emit each boolean's result *and* its inputs.

**Visible means shown, which is not the same as `Visibility == true`.** FreeCAD
hides a subtree by hiding its *container* and leaves the children's own flags
alone, so reading per-object visibility reports parts as visible that nobody can
see in FreeCAD. That one cost the first published model its credibility: DAME
keeps a component library in the same file — `CMP_Delta_IT_Run`,
`CMP_MPD_Dry_Cooler`, `CMP_Minera_TX`, `CMP_Schneider_PTU_3D`,
`CMP_Grundfos_CR95`, `CMP_Fence_Panel_2400x2100`, and the `AU01 layout - 1 phase`
working assembly — each parked on the origin with its container hidden. All seven
are hidden containers full of visible children, so 3,440 parts of library
geometry landed in the middle of the building: a second IT pod in the west half,
a dry cooler floating over the PTUs, and manifold pipework 14.7 m below grade.
Respecting container visibility takes the model from 3,563 parts to 123 and
12 MB to 7.4 MB, and loses nothing real.

**Do not fix that by hiding the leaves in FreeCAD.** It looks like the tidier
option and it breaks the model. An `App::Link` draws its target's geometry even
when the target's *container* is hidden — that is exactly how the placed dry
coolers and PTUs appear on site while their masters do not — but it draws nothing
when the target's *leaves* are hidden. Hiding the 3,442 library objects in the
document emptied 13 of the 15 placed instances. The exclusion belongs in the
exporter.

**Containers are dropped, but only when their contents survive.** A group or
`App::Part` exposes a Shape that is a compound of its children. Emitting both
doubles the geometry and z-fights. The check is per model, not a list of type
names: drop the container only if something inside it is being exported. Guessing
the type list is what broke it once — `App::Link` was on it, and 23 of AU01's 24
links point at a *hidden* target, so the link is the only copy of that
transformer or pump skid there is. Dropping links silently deleted the heavy
vendor equipment and cut the model from 2.9 M triangles to 0.6 M.

**Transforms are world transforms: the containers' placements composed with the
object's own.** AU01 positions plant by wrapping each unit in an `App::Part` that
carries the offset onto its plinth — "GEN 4 UNIT" holds (0, −300, +750) — so an
object's own placement alone leaves it beside the pad rather than on it. Skipping
the inherited transform sank all eight gensets and PTUs 750 mm into their
plinths and slid four of them 0.8–2.1 m sideways. See `ancestor_placement`.

The object's own half of that comes from `Shape.Placement`, never
`obj.Placement`. For an `App::Link` the two differ — `obj.Shape` already has the
link resolved into it while `obj.Placement` still holds the link's transform — and
applying the latter put both dry coolers 38 m west of site, stretching the model
from 130 m to 167 m wide. `local + Shape.Placement == Shape` holds by
construction for every object type.

`getGlobalPlacement()` computes the same world transform and is deliberately not
used: `App::Link` does not implement it, and links are precisely how the PTUs,
transformers, pump banks and rack runs are placed. The chain is walked here
instead so one rule covers every type.

**Every transform is checked, not assumed.** Each part's local shape is put back
through its transform and the centre of mass compared against the original, to
1 mm. Anything that fails is exported in world coordinates with no transform and
no instancing: bigger and slower for that part, never in the wrong place. Centre
of mass rather than bounding box, because FreeCAD's box for a curved solid is
computed to a tolerance and moves by up to 630 mm between evaluations of the same
shape — a box test failed 603 good parts.

**Instancing does the heavy lifting.** Plant models are mostly the same vendor
part repeated. Parts are keyed on face and edge counts, area, volume, local
bounding-box dimensions and a hash of every vertex rounded to a micron; a match
shares one mesh and differs only by a node transform. Every instance keeps its own
name and tree path, so nothing is lost for review. On the shown AU01 set that is
123 parts from 63 meshes; before container visibility was respected it carried the
component library too, and instancing folded 3,563 parts into 451 meshes.

**Flat-shaded, non-indexed triangles.** Averaged vertex normals make CAD read
wrong — a box inflates, a chamfer disappears. Welding the seams back is
`gltfpack`'s job, and it does it better than we would.

**`MeshPart.meshFromShape`, not `Shape.tessellate`.** The latter ignores its
deviation argument on analytic surfaces: every cylinder lands at ~500 triangles
whether you ask for 8 mm or 40 mm (documented at length in
`../liquid-twin/viewer/prepare_geometry.py`). `meshFromShape` honours both linear
and angular deflection, so LOD is a knob rather than a wish.

**`gltfpack -vpf`.** Quantised positions are 12 MB against 15 MB, but the grid
spans the whole 70 m site, so small parts — pipe fittings, brackets — came out
with 372% position error and visibly deformed. gltfpack warns about exactly this.
`-vpf` keeps float positions, and the warning goes away.

## How the export is verified

Positions were checked part by part against the source, not eyeballed:

- **In FreeCAD**: mesh the local shape, apply the exported transform, compare the
  result's bounding box to the original object's. Agreement to 0.1 mm.
- **In the browser**: every part's precise mesh bounding box compared against the
  part table. All sit inside their FreeCAD box, none outside it, and the model's
  overall extent matches the source exactly.
- **Equipment against its plinth**: all eight PTUs and gensets centre on their
  pads to 0 mm with a consistent 300 mm margin, each standing on the pad top.
  This is the check that actually catches an inherited-transform bug, because it
  compares two objects that must agree rather than one object against itself.

Three measurement traps, if the check is ever re-run.

`ViewObject.getBoundingBox()` is **not** ground truth for where FreeCAD draws
something, however much it sounds like it. It reports the object's local box and
ignores inherited container transforms, so it cheerfully confirms whichever frame
you already believed — it is what hid the plinth misalignment through a full round
of "verification". Neither is `Part.getShape(obj, transform=True)` agreeing with
`obj.Shape`: both resolve only the object's own placement, so they agree by
construction whether or not the answer is right. Check geometry against *another
object it must line up with*, or against a rendered image.

Use `Box3.setFromObject(mesh, true)`: without `precise`, three.js transforms the
local AABB's corners and overstates any rotated part, which made 91 rotated pipe
clamps look 71 mm too wide.

Residual deviations up to 630 mm are the *FreeCAD* box being loose on curved
solids, not the mesh being wrong — which is why the test that matters is
containment.

## Gotchas worth knowing before editing this

- **`freecadcmd` has no argument passthrough.** Every token after the script name
  is treated as another document to open. Options travel in `EXPORT_GLB_ARGS`,
  and `export.sh` is the front door that puts them there.
- **`freecadcmd` runs a script with `__name__` set to the file stem.** A
  `if __name__ == "__main__"` guard never fires, and the process exits silently
  with nothing but the FreeCAD banner.
- **`freecadcmd` does not flush stdio on exit.** Anything still buffered is lost
  and looks exactly like a crash mid-export. Everything prints through `say()`.
- **Headless FreeCAD has no `ViewObject`.** Visibility and colour — the two things
  that decide what a reviewer sees — are parsed straight out of the FCStd zip:
  `GuiDocument.xml` for the view providers and the `ShapeAppearance*` blobs for
  materials, where a colour is a little-endian uint32 holding `0xRRGGBBAA`.
- **three.js sanitises glTF node names**, turning spaces into underscores. The
  real label is carried in node `extras` and the viewer reads that.

## Files

| | |
|---|---|
| `export.sh` | front door: runs the exporter, then gltfpack |
| `export_glb.py` | FCStd → GLB. Part selection, instancing, manifest |
| `fcstd_gui.py` | reads visibility, colour, tree paths, meshes shapes |
| `glb.py` | dependency-free glTF 2.0 / GLB writer with instancing |
| `audit.py` | predicts tessellation cost from face counts, in seconds |
| `viewer/` | static viewer: `index.html`, `app.js`, `serve.sh`, `vendor/` |
| `viewer/model/` | export output, gitignored (project data). `*.packed.glb` is what the viewer loads |
| `deploy/deploy.sh` | publish to au01-twin.dametech.net behind a UUID path |

## Limits

- **2D annotation is not exported.** Draft rectangles, circles and text carry no
  faces, so the site plan linework and equipment labels are absent. The 3D solids
  are all there.
- **Rotated copies of a baked-in-place part are not deduplicated.** Where
  `Shape.Placement` is identity, the only recoverable transform is a translation,
  so a rotated twin gets its own mesh. A missed saving, not an error.
- **One draw call per part.** 123 is nothing, but the pre-cleanup model had 3,563.
  If a bigger model drags, merge parts per group and keep the per-part table for
  picking.
