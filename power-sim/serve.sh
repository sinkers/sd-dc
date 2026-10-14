#!/usr/bin/env bash
# Serve the power-sim viewer and its API on one port. The viewer calls the API,
# so it needs this origin; opening index.html from disk will not work.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PORT="${PORT:-8780}"
cd "$HERE/model"
exec python3 -m dtpower serve --port "$PORT" "$@"
