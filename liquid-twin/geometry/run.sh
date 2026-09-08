#!/usr/bin/env bash
# Build the RD110 loop geometry. Run from anywhere.
#
# FreeCAD's console mode takes the script on stdin rather than as an argument
# (`-c <file>` opens an interactive console and ignores the file), and stdin has
# no __file__, so the component root is passed in the environment instead.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

FREECAD="${FREECAD:-/Applications/FreeCAD.app/Contents/MacOS/FreeCAD}"
if [ ! -x "$FREECAD" ]; then
  echo "FreeCAD not found at $FREECAD. Set FREECAD to its binary." >&2
  exit 1
fi

# Console mode is a line-by-line REPL, so feeding it the script directly breaks
# every multi-line block. A one-line bootstrap that execs the file is the way in.
#
# The launcher also prints the whole environment and a 3Dconnexion warning on
# macOS; neither is ours and neither matters, so both are filtered out.
LIQUID_TWIN_DIR="$ROOT" "$FREECAD" -c 2>&1 \
  <<< "exec(open('$HERE/model_loop.py').read())" \
  | grep -vE '^[A-Z_][A-Z0-9_]*=|3Dconnexion|^Running:|^\[FreeCAD Console|^>>>|^_=|\([0-9]+ %\)|saving\.\.\.' \
  || true
