#!/usr/bin/env bash
# FCStd -> GLB, then meshopt-compress it for the browser.
#
#   ./export.sh --fcstd model.FCStd --out viewer/model/au01.glb [--deflection 12]
#   ./export.sh --fcstd model.FCStd --out /tmp/probe.glb --probe 150   # size the job first
#
# Everything after this script's own flags is handed to export_glb.py through
# EXPORT_GLB_ARGS, because freecadcmd has no argument passthrough of its own.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FREECADCMD="${FREECADCMD:-/Applications/FreeCAD.app/Contents/Resources/bin/freecadcmd}"

if [ ! -x "$FREECADCMD" ]; then
  echo "freecadcmd not found at $FREECADCMD" >&2
  echo "set FREECADCMD, e.g. FREECADCMD=/usr/bin/freecadcmd $0 ..." >&2
  exit 1
fi

# Pull --out back out of the arguments so we know what to compress afterwards.
OUT=""
prev=""
for arg in "$@"; do
  [ "$prev" = "--out" ] && OUT="$arg"
  prev="$arg"
done

# Re-quote each argument, or a path with spaces in it - which every OneDrive
# path has - arrives at the script as several broken arguments.
ARGS=""
for arg in "$@"; do
  ARGS+="$(printf '%q' "$arg") "
done

EXPORT_GLB_ARGS="$ARGS" "$FREECADCMD" "$HERE/export_glb.py" 2>&1 \
  | grep -vE '3Dconnexion|^\(|\([0-9]+ %\)|^$' || true

# gltfpack welds the flat-shaded seams back together, quantises attributes and
# leaves a meshopt-compressed GLB that the viewer decodes with its wasm module.
# It is optional: without it the raw GLB still loads, just several times larger.
if [ -n "$OUT" ] && [ -f "$OUT" ]; then
  PACKED="${OUT%.glb}.packed.glb"
  if npx --yes gltfpack -v >/dev/null 2>&1; then
    echo "compressing with gltfpack -> $PACKED"
    # -kn keeps one node per part, so a reviewer can still click a part and get
    # its FreeCAD name; -ke keeps the extras that carry the tree path.
    #
    # -vpf keeps positions as floats instead of quantising them to a 14-bit grid.
    # That costs about 10 MB on the AU01 model and is worth it: the grid spans
    # the whole 70 m site, so the small parts - pipe fittings, bolted brackets -
    # came out with 372% position error and visibly deformed. gltfpack warns
    # about exactly this. With -vpf it is silent and the geometry is exact.
    npx --yes gltfpack -i "$OUT" -o "$PACKED" -cc -kn -ke -vpf
    ls -lh "$OUT" "$PACKED" | awk '{print $5, $9}'
  else
    echo "gltfpack unavailable; shipping the raw GLB (larger, still works)" >&2
  fi
fi
