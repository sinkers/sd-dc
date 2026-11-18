#!/usr/bin/env bash
# FCStd + site config -> Blender fly-over (.blend, stills, MP4).
#
#   ./build_flythrough.sh --fcstd model.FCStd --config site.json --out work/
#   ./build_flythrough.sh ... --stills              # one frame per shot, quick check
#   ./build_flythrough.sh ... --render              # full animation -> work/flythrough.mp4
#   ./build_flythrough.sh ... --render --quality final --engine cycles
#   ./build_flythrough.sh ... --skip-export --stills   # re-cut shots, keep the GLB
#   ./build_flythrough.sh ... --render --frames 1-240  # one stretch; rerun resumes
#
# Steps:
#   1. model-review/export_glb.py (headless FreeCAD): visible solids -> model.glb
#      plus model.parts.json (FreeCAD name, label and tree path per part)
#   2. export_scene.py (headless FreeCAD): terrain mesh, aerial image plane,
#      layout frame and outlines -> scene.json, terrain_*.json
#   3. flythrough.py (headless Blender): builds the scene, saves flythrough.blend,
#      optionally renders stills or the animation
#   4. ffmpeg: frames/ -> flythrough.mp4
#
# The FCStd is opened read-only in a separate process, so FreeCAD can stay open.
# Save the model first: visibility comes from the saved file, and anything
# hidden there (a component library parked on the origin) stays out.
set -euo pipefail
# Launched from inside FreeCAD (or any app bundling Python), PYTHONHOME points at
# that app's interpreter and breaks every other Python this script starts.
unset PYTHONHOME PYTHONPATH

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
FREECADCMD="${FREECADCMD:-/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd}"
BLENDER="${BLENDER:-}"
if [ -z "$BLENDER" ]; then
  for c in /Applications/Blender.app/Contents/MacOS/Blender "$(command -v blender || true)" \
           /opt/homebrew/bin/blender /usr/bin/blender; do
    if [ -n "$c" ] && [ -x "$c" ]; then BLENDER="$c"; break; fi
  done
fi
FFMPEG="${FFMPEG:-$(command -v ffmpeg || echo /opt/homebrew/bin/ffmpeg)}"

FCSTD="" CONFIG="" OUT="" QUALITY="draft" ENGINE="eevee" FRAMES=""
DEFLECTION="20" STILLS=0 RENDER=0 SKIP_EXPORT=0

usage() { sed -n '2,12p' "$0" | sed 's/^# \{0,1\}//'; exit "${1:-0}"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --fcstd) FCSTD="$2"; shift 2 ;;
    --config) CONFIG="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --quality) QUALITY="$2"; shift 2 ;;
    --engine) ENGINE="$2"; shift 2 ;;
    --frames) FRAMES="$2"; shift 2 ;;
    --deflection) DEFLECTION="$2"; shift 2 ;;
    --stills) STILLS=1; shift ;;
    --render) RENDER=1; shift ;;
    --skip-export) SKIP_EXPORT=1; shift ;;
    -h|--help) usage 0 ;;
    *) echo "unknown option: $1" >&2; usage 1 ;;
  esac
done

[ -n "$CONFIG" ] && [ -n "$OUT" ] || { echo "--config and --out are required" >&2; usage 1; }
[ -f "$CONFIG" ] || { echo "config not found: $CONFIG" >&2; exit 1; }
[ -n "$BLENDER" ] || { echo "Blender not found; set BLENDER=/path/to/Blender" >&2; exit 1; }
mkdir -p "$OUT"
OUT="$(cd "$OUT" && pwd)"
CONFIG="$(cd "$(dirname "$CONFIG")" && pwd)/$(basename "$CONFIG")"

# freecadcmd prints progress spinners and a 3Dconnexion banner; drop them.
fc_filter() { grep -vE '3Dconnexion|^\(|\([0-9]+ %\)|^$' || true; }

if [ "$SKIP_EXPORT" -eq 0 ]; then
  [ -n "$FCSTD" ] && [ -f "$FCSTD" ] || { echo "--fcstd is required unless --skip-export" >&2; exit 1; }
  [ -x "$FREECADCMD" ] || { echo "freecadcmd not found at $FREECADCMD; set FREECADCMD" >&2; exit 1; }

  echo "== 1/4 GLB from $(basename "$FCSTD")"
  # Groups the config names in show_groups export even if hidden in the saved
  # view (a roof switched off while reviewing must still be in the film).
  SHOW=()
  while IFS= read -r g; do [ -n "$g" ] && SHOW+=(--show "$g"); done < <(
    python3 -c 'import json,sys; [print(g) for g in json.load(open(sys.argv[1])).get("show_groups", [])]' "$CONFIG")
  GLB_ARGS="$(printf '%q ' --fcstd "$FCSTD" --out "$OUT/model.glb" --deflection "$DEFLECTION" ${SHOW[@]+"${SHOW[@]}"})"
  EXPORT_GLB_ARGS="$GLB_ARGS" "$FREECADCMD" "$REPO/model-review/export_glb.py" 2>&1 | fc_filter
  [ -f "$OUT/model.glb" ] || { echo "GLB export failed" >&2; exit 1; }

  echo "== 2/4 terrain, aerial and frames"
  ARGS_JSON="$(python3 -c 'import json,sys; print(json.dumps({"fcstd":sys.argv[1],"config":sys.argv[2],"out":sys.argv[3]}))' \
    "$FCSTD" "$CONFIG" "$OUT")"
  FLYTHROUGH_ARGS="$ARGS_JSON" "$FREECADCMD" "$HERE/export_scene.py" 2>&1 | fc_filter
  [ -f "$OUT/scene.json" ] || { echo "scene export failed" >&2; exit 1; }
else
  echo "== 1-2/4 skipped, reusing $OUT/model.glb and scene.json"
fi

echo "== 3/4 Blender scene ($("$BLENDER" --version 2>/dev/null | head -1))"
BL_ARGS=(--work "$OUT" --config "$CONFIG" --quality "$QUALITY" --engine "$ENGINE")
[ "$STILLS" -eq 1 ] && BL_ARGS+=(--stills)
[ "$RENDER" -eq 1 ] && BL_ARGS+=(--render)
[ -n "$FRAMES" ] && BL_ARGS+=(--frames "$FRAMES")
"$BLENDER" -b --factory-startup -P "$HERE/flythrough.py" -- "${BL_ARGS[@]}" 2>&1 \
  | grep -E '^\[flythrough\]|Error|Traceback|^  File|Fra:[0-9]+ .*(Rendering|Finished)' \
  | grep -vE 'Fra:[0-9]+ .*Rendering [0-9]+ / ' || true
[ -f "$OUT/flythrough.blend" ] || { echo "Blender step failed; rerun without the grep filter to see why" >&2; exit 1; }

if [ "$RENDER" -eq 1 ]; then
  echo "== 4/4 encode"
  FPS="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["fps"])' "$OUT/render_info.json")"
  if [ -x "$FFMPEG" ]; then
    "$FFMPEG" -y -loglevel error -framerate "$FPS" -pattern_type glob -i "$OUT/frames/*.png" \
      -c:v libx264 -pix_fmt yuv420p -crf 18 -movflags +faststart "$OUT/flythrough.mp4"
    echo "wrote $OUT/flythrough.mp4"
  else
    echo "ffmpeg not found; frames are in $OUT/frames/ at $FPS fps" >&2
  fi
else
  echo "== 4/4 skipped (no --render). Open $OUT/flythrough.blend to scrub the shots."
fi
