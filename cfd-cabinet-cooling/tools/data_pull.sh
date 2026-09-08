#!/usr/bin/env bash
# Fetch a solved OpenFOAM case from S3. Designed to be the first thing a cluster
# worker runs, so it reads the manifest and reports before downloading.
#
# Usage:
#   ./tools/data_pull.sh --list                 what is in the bucket
#   ./tools/data_pull.sh case-hall              latest sha for that case
#   ./tools/data_pull.sh case-hall <git-sha>    a specific one
#   ./tools/data_pull.sh case-hall --info       read the manifest, download nothing
set -euo pipefail

BUCKET="${SDDC_ARTIFACTS_BUCKET:?set SDDC_ARTIFACTS_BUCKET to your artifacts bucket}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [ "${1:-}" = "--list" ]; then
  echo "cases in s3://$BUCKET/cfd/"
  aws s3 ls "s3://$BUCKET/cfd/" | awk '{print "  "$2}'
  exit 0
fi

CASE="${1:?usage: data_pull.sh <case-dir> [git-sha|--info] | --list}"
ARG="${2:-}"

if [ -n "$ARG" ] && [ "$ARG" != "--info" ]; then
  SHA="$ARG"
else
  # Most recently pushed sha for this case, by S3 LastModified on the manifest.
  SHA=$(aws s3api list-objects-v2 --bucket "$BUCKET" --prefix "cfd/$CASE/" \
        --query 'sort_by(Contents[?ends_with(Key, `manifest.json`)], &LastModified)[-1].Key' \
        --output text 2>/dev/null | awk -F/ '{print $3}')
  [ -n "$SHA" ] && [ "$SHA" != "None" ] || { echo "no pushes found for case '$CASE'" >&2; exit 1; }
fi

SRC="s3://$BUCKET/cfd/$CASE/$SHA"

echo "== manifest =="
aws s3 cp "$SRC/manifest.json" - 2>/dev/null | python3 -m json.tool \
  || { echo "no manifest at $SRC — refusing to pull an unlabelled case" >&2; exit 1; }

if [ "$ARG" = "--info" ]; then exit 0; fi

# Warn if the checkout does not match the sha the solution was produced against.
LOCAL_SHA=$(git -C "$HERE" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
if [ "$LOCAL_SHA" != "$SHA" ]; then
  echo
  echo "NOTE: local checkout is $LOCAL_SHA, this solution was solved at $SHA."
  echo "      The case dictionaries may differ from the ones that produced it."
fi

echo
echo "pulling into $HERE/$CASE ..."
aws s3 sync "$SRC" "$HERE/$CASE" --exclude 'manifest.json' --no-progress
echo "done. $(du -sh "$HERE/$CASE" | cut -f1) on disk."
