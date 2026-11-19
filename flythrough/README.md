# flythrough — a site fly-over from the FreeCAD model, in Blender

One command turns a site's `.FCStd` into a Blender scene with a scripted camera:
an establishing orbit, the approach, the data hall roof lifting off, a walk down
the hall at eye height, the office roof and then its upper storey lifting off,
and a build sequence where every part drops onto the site in order.

```bash
./build_flythrough.sh --fcstd site.FCStd --config site.json --out work/ --stills
./build_flythrough.sh --config site.json --out work/ --skip-export --render
./build_flythrough.sh --config site.json --out work/ --skip-export --render --quality final
```

`--stills` renders one frame from the middle of each shot (seconds per shot).
`--render` renders every frame to `work/frames/` and encodes `work/flythrough.mp4`
with ffmpeg. A render can be interrupted and rerun: frames already on disk are
skipped. `work/flythrough.blend` is always saved, so the shots can be opened,
scrubbed and adjusted by hand in Blender.

Keep `work/` off OneDrive. A 1080p render is several gigabytes of frames;
copy only the MP4 back to the project folder.

## Pipeline

| Step | Runs in | Does |
|---|---|---|
| 1 | `freecadcmd` | `../model-review/export_glb.py`: every shown solid to `model.glb` and `model.parts.json` (name, label, tree path). `show_groups` in the config are exported even if hidden in the saved view |
| 2 | `freecadcmd` | `export_scene.py`: terrain mesh, aerial image plane, layout frame and outlines to `scene.json` |
| 3 | `blender -b` | `flythrough.py`: builds the scene, saves the `.blend`, renders |
| 4 | `ffmpeg` | frames to H.264 MP4 |

FreeCAD can stay open: both FreeCAD steps open the saved file in their own
process. Save the model first.

## The site config

Project data, so it lives beside the model, not here. `example.config.json`
is the template; every label in it must match the model.

- `frame` — the `App::Part` whose placement is the layout's frame. Camera positions are measured in it.
- `origin`, `ground.pad` — a closed wire (the fence line). The scene is recentred on it at pad level, and the ground is cut flat inside it with a graded batter outside.
- `ground.terrain`, `ground.aerial` — the TIN mesh and the aerial image plane. The ground is a grid over the aerial's extent, draped on the TIN, extended past the survey edge at the nearest surveyed level.
- `collections` — ordered rules: a part goes to the first rule whose `paths` contains a group on its tree path, or whose `label_regex` matches its label. Collections are what shots lift and what the build drops.
- `materials` — label regex to colour, alpha and finish (glazing, chain mesh, line marking).
- `anchors` — named boxes (the bounding box of some collections, in the layout frame).
- `shots` — the film. A camera point is `{"anchor", "u", "v", "h"}`: fractions of the anchor box along the frame's x and y (0 to 1 is inside, negative is before it), and metres above the pad. Shot types:
  - `orbit` — `target`, `radius_m`, `height_m`, `from_deg` to `to_deg` (frame angles, 270 is the -y side)
  - `path` — `keys` with `t` (s), `cam`, `look`, optional `lens_mm`; `continue: true` starts from the last shot's camera
  - `build` — an orbit while `stages` drop in from `drop_m`, one stage every `step_s`, each taking `each_s`. A stage may carry a `caption`; `intro_caption` shows before the first stage. `"stages": "plan"` takes the stages from the plan (below)
  - any shot can carry `caption`: on-screen text for the whole shot
  - any shot can carry `events`: `lift` (rise `dz_m` over `dur_s`, then hide), `hide`, `show`, `restore`

Each shot has its own camera, switched by a timeline marker, so cuts are clean.

- `extra_models` — `[{"glb": "exploded.glb", "parts": "exploded.parts.json"}]`, files in the work folder. Imported after `model.glb`; main parts named in the extra table's `replaces` are dropped, so a linked component exported part by part (construction-sequence `explode_links.py`) stands in for its single solid.
- `plan` — a construction-sequence `plan-<mode>.json` drives the build shot: `{"file", "stage_by": "layer" | "task", "captions": {id: text}, "skip": [id]}`. Each part the plan builds goes to collection `plan_<id>` of its layer or task, unless an explicit `collections` rule claims it first; an explicit collection then arrives with the stage that builds most of its parts. Parts the plan does not build (existing, context) stand throughout. Captions default to the layer or task name; set them for an audience.
- `caption_style` — `font` (file), `size` and `y` (fractions of frame height), `colour`, `box` (background opacity). Captions are written to `captions.json` and burnt in by ffmpeg at the encode step (`captions_filter.py`), so stills do not show them.

## Requirements

Blender 4.2 or later (written against 5.2 LTS), FreeCAD 1.x (`freecadcmd`),
ffmpeg for the MP4. Override paths with `BLENDER=`, `FREECADCMD=`, `FFMPEG=`.

## Known limits

- Roofs lift and then pop out; they do not fade. A fade needs per-part
  material copies.
- The aerial is draped by its own placement. If it was registered by eye in
  FreeCAD, it is only as good as that registration.
- Draft text (room labels) is not exported. Overlay titles in ffmpeg or the
  Blender sequencer if needed.
