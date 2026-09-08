#!/usr/bin/env bash
# Run every suite in the repo. No arguments, no options, exits non-zero on failure.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fail=0

run() {  # run <name> <dir> <command...>
  printf '\n\033[1m== %s\033[0m\n' "$1"; shift
  local dir="$1"; shift
  if ( cd "$HERE/$dir" && "$@" ); then :; else
    echo "FAILED: $dir"; fail=1
  fi
}

# The credential-free suite always runs: it points itself at fixtures/ and
# proves the code assembles. The two value suites need the licensed data and
# skip cleanly (exit 0) without it — see tools/data_pull_standards.sh.
run "cable-sizing — synthetic smoke (no data needed)" cable-sizing python3 test_synthetic.py
run "cable-sizing — AS/NZS 3008 engine"               cable-sizing python3 test_cable_sizing.py
run "cable-sizing — REST + MCP API"                   cable-sizing python3 test_api.py

# digital-twin needs its package importable. Prefer an installed dthall; fall
# back to PYTHONPATH so a plain checkout still runs.
if python3 -c "import dthall" 2>/dev/null; then
  run "digital-twin — ROM" digital-twin python3 -m pytest -q rom/tests
else
  echo -e "\n\033[1m== digital-twin — ROM\033[0m"
  echo "  dthall not installed; using PYTHONPATH. For CI: pip install -e digital-twin"
  ( cd "$HERE/digital-twin" && PYTHONPATH=rom python3 -m pytest -q rom/tests ) || fail=1
fi

printf '\n'
if [ "$fail" -eq 0 ]; then echo "All suites passed."; else echo "One or more suites FAILED."; fi
exit "$fail"
