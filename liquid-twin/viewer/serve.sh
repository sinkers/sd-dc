#!/usr/bin/env bash
# Serve the review viewer. The bundle is fetched with XHR, so file:// will not
# work - it needs an origin.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8770}"
if [ ! -f "$HERE/geometry/manifest.json" ]; then
  echo "no bundle yet; building it" >&2
  "$HERE/prepare_geometry.py"
fi
echo "RD110 loop viewer -> http://127.0.0.1:$PORT/"
exec python3 -m http.server "$PORT" --directory "$HERE" --bind 127.0.0.1
