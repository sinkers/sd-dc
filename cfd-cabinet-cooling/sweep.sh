#!/usr/bin/env bash
#
# Airflow sweep: clone the baseline case once per parameter set, run each one,
# and collect the converged metrics into runs/results.csv.
#
# Usage:
#   ./sweep.sh                                  # default fan-wall velocity sweep
#   ./sweep.sh 0.7 1.0 1.41 1.8                 # explicit fanWallVelocity list
#   PARAM=supplyTemp ./sweep.sh 291.15 293.15 297.15
#   PARAM=containmentTopZ ./sweep.sh 2.2 2.6 3.0
#
# Any scalar in case/system/simulationParameters can be swept via PARAM.
# Note containmentTopZ changes the mesh; the script re-meshes every run anyway.
#
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$HERE"

PARAM="${PARAM:-fanWallVelocity}"
VALUES=("$@")
if [ ${#VALUES[@]} -eq 0 ]; then
    VALUES=(0.85 1.13 1.41 1.69)      # 60 / 80 / 100 / 120 % of server demand
fi

RUNS_DIR="runs"
RESULTS="$RUNS_DIR/results.csv"
mkdir -p "$RUNS_DIR"

if [ ! -f "$RESULTS" ]; then
    echo "param,value,inletT_C,inletTmax_C,outletT_C,deltaT_K,supply_kgs,through_kgs,gap_kgs,verdict" > "$RESULTS"
fi

# Pull the final value out of a function-object .dat file.
final_value() {
    local case_dir="$1" name="$2"
    find "$case_dir/postProcessing/$name" -name '*.dat' 2>/dev/null \
        | sort | xargs cat 2>/dev/null \
        | grep -v '^#' | awk 'NF{v=$2} END{print v}'
}

for v in "${VALUES[@]}"; do
    tag="${PARAM}_${v}"
    dest="$RUNS_DIR/$tag"

    echo
    echo "############################################################"
    echo "#  $PARAM = $v"
    echo "############################################################"

    rm -rf "$dest"
    mkdir -p "$dest"
    cp -R case/0.orig case/constant case/system case/Allrun case/Allclean "$dest"/
    rm -rf "$dest/constant/polyMesh"

    # Overwrite the swept parameter in the cloned case.
    #   `key   value;`  ->  `key   <new>;`
    perl -pi -e "s/^(\s*\Q$PARAM\E\s+)\S+;/\${1}$v;/" "$dest/system/simulationParameters"

    if ! grep -qE "^\s*$PARAM\s+$v;" "$dest/system/simulationParameters"; then
        echo "ERROR: failed to set $PARAM=$v in $dest/system/simulationParameters" >&2
        exit 1
    fi

    CASE_DIR="$dest" ./run.sh --keep > "$dest/sweep.log" 2>&1 || {
        echo "  run FAILED - see $dest/sweep.log" >&2
        echo "$PARAM,$v,,,,,,,,ERROR" >> "$RESULTS"
        continue
    }

    Ti=$(final_value "$dest" cabinetInletT)
    Tix=$(final_value "$dest" cabinetInletTmax)
    To=$(final_value "$dest" cabinetOutletT)
    ms=$(final_value "$dest" fanWallFlow)
    mt=$(final_value "$dest" cabinetFlow)
    mg=$(final_value "$dest" containmentGapFlow)

    python3 - "$PARAM" "$v" "$Ti" "$Tix" "$To" "$ms" "$mt" "$mg" >> "$RESULTS" <<'PY'
import sys
param, val, Ti, Tix, To, ms, mt, mg = sys.argv[1:9]
K = 273.15
Ti, Tix, To = float(Ti) - K, float(Tix) - K, float(To) - K
ms, mt, mg = abs(float(ms)), abs(float(mt)), float(mg)
verdict = "PASS" if Ti <= 27.0 else "FAIL"
if verdict == "PASS" and Tix > 32.0:
    verdict = "MARGINAL"
print(f"{param},{val},{Ti:.2f},{Tix:.2f},{To:.2f},{To-Ti:.2f},"
      f"{ms:.3f},{mt:.3f},{mg:+.3f},{verdict}")
PY

    echo "  -> $(tail -1 "$RESULTS")"
done

echo
echo "============================================================"
column -s, -t < "$RESULTS"
echo "============================================================"
echo "results: $RESULTS"
