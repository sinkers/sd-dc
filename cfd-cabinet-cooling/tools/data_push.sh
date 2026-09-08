#!/usr/bin/env bash
# Push a solved OpenFOAM case to S3, with a manifest describing what it is.
#
# A solution is only meaningful against the case dictionaries that produced it,
# so the S3 key is <case>/<git-sha>, not a content hash. The manifest is what
# lets a cluster worker decide whether a solution is usable WITHOUT downloading
# several hundred megabytes to find out.
#
# Usage:  ./tools/data_push.sh case-hall [git-sha]
set -euo pipefail

BUCKET="${SDDC_ARTIFACTS_BUCKET:?set SDDC_ARTIFACTS_BUCKET to your artifacts bucket}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CASE="${1:?usage: data_push.sh <case-dir> [git-sha]}"
CASE_DIR="$HERE/$CASE"

[ -d "$CASE_DIR" ] || { echo "no such case: $CASE_DIR" >&2; exit 1; }

SHA="${2:-$(git -C "$HERE" rev-parse --short=12 HEAD)}"
DIRTY=false
if ! git -C "$HERE" diff --quiet -- "$CASE_DIR/system" "$CASE_DIR/constant" 2>/dev/null; then
  DIRTY=true
fi

# A solution filed under a sha whose dictionaries have since changed is worse
# than no solution, because it looks authoritative. Refuse, or label it honestly.
if [ "$DIRTY" = true ] && [ -z "${2:-}" ]; then
  echo "REFUSING: $CASE/system or /constant is modified relative to $SHA." >&2
  echo "  A solution filed under that sha would not describe the case that produced it." >&2
  echo >&2
  echo "  Either commit the dictionaries first, or file it honestly as dirty:" >&2
  echo "      ./tools/data_push.sh $CASE ${SHA}-dirty" >&2
  exit 1
fi
case "$SHA" in *-dirty) DIRTY=true ;; esac

DEST="s3://$BUCKET/cfd/$CASE/$SHA"

# Time directories, excluding the 0/0.orig initial conditions which are in git.
TIMES=$(find "$CASE_DIR" -maxdepth 1 -type d -name '[0-9]*' ! -name '0' ! -name '0.orig' \
        -exec basename {} \; | sort -g | paste -sd, -)
LATEST="${TIMES##*,}"

echo "case      $CASE"
echo "sha       $SHA"
echo "times     ${TIMES:-<none>}"
echo "dest      $DEST"

MANIFEST=$(mktemp)
cat > "$MANIFEST" <<EOF
{
  "case": "$CASE",
  "git_sha": "$SHA",
  "pushed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)",
  "pushed_by": "$(whoami)@$(hostname -s)",
  "time_dirs": "${TIMES:-}",
  "latest_time": "${LATEST:-}",
  "has_mesh": $([ -d "$CASE_DIR/constant/polyMesh" ] && echo true || echo false),
  "openfoam_version": "$(grep -ho 'OpenFOAM-[0-9v.]*' "$CASE_DIR"/log.* 2>/dev/null | head -1 || echo unknown)",
  "size_bytes": $(du -sk "$CASE_DIR" | awk '{print $1*1024}'),
  "dictionaries_dirty": $DIRTY,
  "converged": null,
  "note": "converged is null unless set by hand after reading plot_metrics.py output"
}
EOF
python3 -c "import json,sys; json.load(open(sys.argv[1]))" "$MANIFEST" \
  || { echo "manifest is not valid JSON" >&2; exit 1; }

aws s3 cp "$MANIFEST" "$DEST/manifest.json" --content-type application/json
rm -f "$MANIFEST"

# Mesh and solution fields only. Logs, .foam stubs and postProcessing are
# regenerable or trivially re-derived, and dominate the object count if included.
aws s3 sync "$CASE_DIR" "$DEST" \
  --exclude '*' \
  --include 'constant/polyMesh/*' \
  --include 'constant/triSurface/*' \
  $(for t in ${TIMES//,/ }; do printf -- "--include %s/* " "$t"; done) \
  --exclude '*/uniform/*' \
  --no-progress

echo
echo "pushed. verify with:  aws s3 ls $DEST/ --recursive --human-readable --summarize | tail -3"
