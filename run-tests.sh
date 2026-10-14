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

# piping: the FreeCAD-free router and its service. The Rev B benchmark is
# project data kept out of git (piping/private/); without it that class skips.
run "piping — router, service, MCP + REST"            piping python3 -m pytest -q tests
# trays: tray runs and their ground supports, on the piping router. Synthetic
# tray data only; the Ezystrut catalogue is vendor data and not needed.
run "trays — supports off the ground"                  trays python3 -m pytest -q tests

# digital-twin needs its package importable. Prefer an installed dthall; fall
# back to PYTHONPATH so a plain checkout still runs.
if python3 -c "import dthall" 2>/dev/null; then
  run "digital-twin — ROM" digital-twin python3 -m pytest -q rom/tests
else
  echo -e "\n\033[1m== digital-twin — ROM\033[0m"
  echo "  dthall not installed; using PYTHONPATH. For CI: pip install -e digital-twin"
  ( cd "$HERE/digital-twin" && PYTHONPATH=rom python3 -m pytest -q rom/tests ) || fail=1
fi

# liquid-twin, same arrangement as digital-twin: prefer an installed dtloop,
# fall back to PYTHONPATH so a plain checkout still runs.
if python3 -c "import dtloop" 2>/dev/null; then
  run "liquid-twin — hydraulics" liquid-twin python3 -m pytest -q loop/tests
else
  echo -e "\n\033[1m== liquid-twin — hydraulics\033[0m"
  echo "  dtloop not installed; using PYTHONPATH. For CI: pip install -e liquid-twin"
  ( cd "$HERE/liquid-twin" && PYTHONPATH=loop python3 -m pytest -q loop/tests ) || fail=1
fi

# power-sim: standard library only, so a plain checkout runs it with no install.
if python3 -c "import dtpower" 2>/dev/null; then
  run "power-sim — grid, BESS, UPS, generator" power-sim python3 -m pytest -q model/tests
else
  echo -e "\n\033[1m== power-sim — grid, BESS, UPS, generator\033[0m"
  ( cd "$HERE/power-sim" && PYTHONPATH=model python3 -m pytest -q model/tests ) || fail=1
fi

printf '\n'
if [ "$fail" -eq 0 ]; then echo "All suites passed."; else echo "One or more suites FAILED."; fi
exit "$fail"
