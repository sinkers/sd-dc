#!/usr/bin/env bash
# Serve the review viewer. The GLB is fetched with XHR, so file:// will not work
# - it needs an origin.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8771}"
if [ ! -f "$HERE/model/au01.packed.glb" ]; then
  echo "no model yet; run ../export.sh first" >&2
  exit 1
fi
echo "AU01 model review -> http://127.0.0.1:$PORT/"
exec python3 -m http.server "$PORT" --directory "$HERE" --bind 127.0.0.1
