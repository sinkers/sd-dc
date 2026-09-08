#!/usr/bin/env bash
#
# Run the cabinet cooling case inside the OpenFOAM v2406 container.
# Nothing needs to be installed on the host except Docker.
#
# Usage:
#   ./run.sh                 # clean, mesh and solve the case in ./case
#   ./run.sh --keep          # solve without wiping previous results
#   ./run.sh --sample        # extract the centreline slice for plot_slice.py
#   ./run.sh --shell         # drop into an interactive OpenFOAM shell
#   CASE_DIR=runs/foo ./run.sh
#
set -euo pipefail

IMAGE="${IMAGE:-opencfd/openfoam-default:2406}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CASE_DIR="${CASE_DIR:-case}"

# Run natively on both Apple Silicon and x86; the image is multi-arch.
case "$(uname -m)" in
    arm64|aarch64) PLATFORM="${PLATFORM:-linux/arm64}" ;;
    *)             PLATFORM="${PLATFORM:-linux/amd64}" ;;
esac

mode="run"
for arg in "$@"; do
    case "$arg" in
        --keep)   mode="keep" ;;
        --sample) mode="sample" ;;
        --shell)  mode="shell" ;;
        *) echo "unknown option: $arg" >&2; exit 2 ;;
    esac
done

# Only attach a TTY when we actually have one (so CI / background runs work).
# Written as a plain string for bash 3.2 compatibility (macOS /bin/bash).
TTY_FLAGS=""
if [ -t 0 ] && [ -t 1 ]; then TTY_FLAGS="-it"; fi

docker_run() {
    docker run --rm $TTY_FLAGS \
        --platform "$PLATFORM" \
        --shm-size=4g \
        -v "$HERE:/work" \
        -e OMPI_ALLOW_RUN_AS_ROOT=1 \
        -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
        "$IMAGE" \
        bash -lc "cd /work && $1"
}

# Generated dictionaries are built on the host (the container has no python3)
# and before any sync. Which generator depends on the case: the single-row case
# is driven by simulationParameters, the two-row hall by hallParameters.
if [ "$mode" != "shell" ]; then
    if   [ -f "$HERE/$CASE_DIR/system/au01Parameters" ]; then
        "$HERE/make_au01_dicts.py" "$HERE/$CASE_DIR"
    elif [ -f "$HERE/$CASE_DIR/system/hallParameters" ]; then
        "$HERE/make_hall_dicts.py" "$HERE/$CASE_DIR"
    elif [ -f "$HERE/$CASE_DIR/system/simulationParameters" ]; then
        "$HERE/make_row_dicts.py"  "$HERE/$CASE_DIR"
    fi
fi

case "$mode" in
    shell)
        docker run --rm -it --platform "$PLATFORM" \
            -v "$HERE:/work" \
            -e OMPI_ALLOW_RUN_AS_ROOT=1 -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 \
            "$IMAGE" bash -l
        ;;
    keep)
        docker_run "cd '$CASE_DIR' && ./Allrun"
        ;;
    sample)
        docker_run "cd '$CASE_DIR' && postProcess -func slices -latestTime"
        ;;
    run)
        docker_run "cd '$CASE_DIR' && ./Allclean && ./Allrun"
        ;;
esac
