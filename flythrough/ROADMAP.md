# flythrough: roadmap

What the first site film (a 90-second "site dossier" reel, November 2026) taught
us, and what later releases should add. Project specifics stay in the private
config repo; this file is about the tool.

## How the first reel was made

| Pass | Tool | Measured | Notes |
|---|---|---|---|
| 3D build and grid shots | Blender 5.2, EEVEE, 1280 × 720 | 0.39–0.65 s a frame on an M4 Pro (1,056 frames in about 8 min) | GPU-bound render; Blender used about one CPU core, for scene evaluation |
| 2D maps, titles and overlays | HTML page, `render(t)` per frame, headless Chrome via Playwright | 0.22 s a frame (2,160 frames in about 8 min) | Same page draws opaque 2D scenes and transparent overlays for the 3D section |
| Assembly | ffmpeg overlay and concat of PNG sequences, libx264 | over 10 min for 90 s at 720p | PNG decode and RGBA overlay dominate |

## Performance (next releases)

1. **Parallel frame ranges.** Run three or four Blender processes on split frame
   ranges. EEVEE's per-frame cost is mostly single-threaded scene evaluation, so
   this should give 2–3× on Apple silicon (not yet benchmarked).
2. **Cheaper scene evaluation.** Thousands of objects with keyed visibility are
   re-evaluated every frame. Key visibility per collection (one empty per build
   stage) instead of per object, merge static geometry, and use persistent data.
3. **Cloud GPUs for Cycles finals.** If a final needs path-traced quality, render
   frame ranges on NVIDIA GPU instances (g6 / g5 / g6e, OptiX):
   - AWS Deadline Cloud (managed, Blender supported), or AWS Batch on spot with a
     Blender container, results to S3;
   - a cost guard (hard cap per job) and a stills-first quality check.
   Check current regional pricing before committing.
4. **Faster 2D pass.** Several browser pages in parallel; only re-render overlay
   frames whose content changes (banners, cards), and hold the rest.
5. **Faster assembly.** Pipe frames straight to ffmpeg, or use ProRes/EXR
   intermediates instead of PNG; hardware encoding (`h264_videotoolbox`) for
   drafts; or composite in Blender's sequencer in the same render.

## Features (next releases)

### Longer runs and multiple cuts
- The whole film as data: one shot list (YAML) drives the 3D pass, the 2D pass,
  banners, cards and sound cues, instead of timings repeated in three scripts.
- Several cuts from one shot list: a 30 s social cut, the 90 s reel, and a
  long-form walkthrough (3–5 min) with chapters.
- Every map scene generic to any site: positions from the GIS server, aerial and
  relief from its imagery tools, attribution added per shot.

### Voice-over in several languages
- A script as data: each line has a speaker (for example *handler* and
  *system*), a scene, a time slot, and text per language.
- Generate speech with ElevenLabs (Multilingual v2 or later): one cast per
  language, a speed setting per voice to fit each slot, and a check that flags
  any line that overruns its slot.
- Re-time banners and captions to the generated speech, so a longer German line
  moves its banner rather than clipping it.
- On-screen text from the same translation files, with locale number formats
  (decimal separators, units), and subtitles (SRT and VTT) per language.
- One render of the picture; the audio and text layers are rebuilt per
  language, so a new language costs minutes, not a re-render.

### Sound
- A cue sheet tied to timeline events: typing, target locks, components landing,
  lines energising, scene changes.
- A music or drone bed that ducks under the voice (sidechain compression), and
  loudness normalised for the outlet (about −14 LUFS for web, −23 LUFS for
  broadcast).
- A licence register for every sound, voice and image, with any required
  credits added to the end card automatically.
