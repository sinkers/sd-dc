#!/usr/bin/env bash
#
# Run the case on a remote Linux box instead of locally, then bring the results
# back so all the local plotting tools work unchanged.
#
# The box must already be provisioned:  ./remote/provision-openfoam.sh HOST KEY
#
# Usage:
#   ./remote/run-remote.sh ubuntu@1.2.3.4 ~/.ssh/mykey
#   RANKS=12 CASE_DIR=case ./remote/run-remote.sh ubuntu@1.2.3.4 ~/.ssh/mykey
#
# Brings back: postProcessing/, the latest time directory, and all log.* files.
#
set -euo pipefail

HOST="${1:?usage: $0 user@host [ssh-key]}"
KEY="${2:-}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASE_DIR="${CASE_DIR:-case}"
REMOTE_DIR="${REMOTE_DIR:-/home/ubuntu/cfd-cabinet-cooling}"

SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")
SSH=(ssh "${SSH_OPTS[@]}")

# Rank count: default to physical cores, capped by cells/20000 once we know the
# mesh size. Physical cores, not nproc - SMT hurts CFD.
if [ -z "${RANKS:-}" ]; then
    RANKS=$("${SSH[@]}" "$HOST" \
      'lscpu | awk -F: "/^Core\(s\) per socket/{c=\$2} /^Socket\(s\)/{s=\$2} END{print c*s}"' | tr -d ' \r')
fi
echo "[remote] $HOST, $RANKS MPI ranks"

# NB: the 0.orig include must precede the [0-9]*/ exclude.
echo "[remote] syncing case in"
"${SSH[@]}" "$HOST" "mkdir -p '$REMOTE_DIR'"
rsync -az --delete ${KEY:+-e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"} \
    --exclude 'processor*' --exclude 'postProcessing' --exclude 'log.*' \
    --include '0.orig/***' --exclude '[0-9]*/' --exclude '*.png' \
    "$HERE/$CASE_DIR/" "$HOST:$REMOTE_DIR/$CASE_DIR/"

echo "[remote] solving"
"${SSH[@]}" "$HOST" bash -lc "'
set -e
cd \"$REMOTE_DIR/$CASE_DIR\"
printf \"FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains $RANKS;\nmethod scotch;\n\" > system/decomposeParDict
./Allclean >/dev/null 2>&1 || true
time ./Allrun
'"

echo "[remote] syncing results back"
rsync -az ${KEY:+-e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"} \
    --exclude 'processor*' \
    "$HOST:$REMOTE_DIR/$CASE_DIR/postProcessing" \
    "$HOST:$REMOTE_DIR/$CASE_DIR/"log.* \
    "$HERE/$CASE_DIR/" 2>/dev/null || true
# latest time directory, for slices and ParaView
LATEST=$("${SSH[@]}" "$HOST" "cd '$REMOTE_DIR/$CASE_DIR' && ls -d [0-9]* 2>/dev/null | grep -v '^0$' | sort -n | tail -1" | tr -d '\r')
if [ -n "$LATEST" ]; then
    echo "[remote] fetching time directory $LATEST"
    rsync -az ${KEY:+-e "ssh -i $KEY -o BatchMode=yes -o StrictHostKeyChecking=accept-new"} \
        "$HOST:$REMOTE_DIR/$CASE_DIR/$LATEST" "$HERE/$CASE_DIR/"
fi

echo "[remote] done. Now run locally:"
echo "  ./plot_metrics.py $CASE_DIR"
