#!/usr/bin/env bash
# Fetch the third-party manufacturer catalogues that this repo reads.
#
# Same posture as tools/data_pull_standards.sh, different rightsholder. Nexans,
# Ezystrut and Tricab publish this data for use with their products; that is not
# the same as a licence for us to redistribute it. The code that reads it is
# open source, the data is not in this repository.
#
#   ./tools/data_pull_vendor.sh              fetch into the components that read them
#   ./tools/data_pull_vendor.sh --list       what is available
#   ./tools/data_pull_vendor.sh --check      report what is present locally
#
# Without credentials the test suites run against the synthetic fixtures.
set -euo pipefail

BUCKET="${SDDC_ARTIFACTS_BUCKET:?set SDDC_ARTIFACTS_BUCKET to your artifacts bucket}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# local path : s3 key under vendor/ : what it is
FILES=(
  "cables/cable_catalog.json:nexans/cable_catalog.json:Nexans Australia, drives cable sizing"
  "cable-tray-ezystrut/tray_catalogue.json:ezystrut/tray_catalogue.json:Ezystrut tray dimensions"
  "cable-sizing/tricab_families.json:tricab/tricab_families.json:Tricab family metadata"
  "cable-tray-ezystrut/INDEX.md:ezystrut/INDEX.md:Ezystrut reference library index"
  "cable-tray-ezystrut/GUIDELINES.md:ezystrut/GUIDELINES.md:Ezystrut design guidelines"
)

# Nexans product documentation: 20 markdown files under vendor/nexans/docs/,
# fetched as a set rather than listed individually.
NEXANS_DOCS_PREFIX="vendor/nexans/docs/"

case "${1:-}" in
  --list)
    echo "s3://$BUCKET/vendor/"
    aws s3 ls "s3://$BUCKET/vendor/" --recursive --human-readable \
      | awk '{printf "  %-10s %s\n", $3" "$4, $5}'
    exit 0 ;;
  --check)
    echo "local vendor data in $HERE:"
    missing=0
    for spec in "${FILES[@]}"; do
      rel="${spec%%:*}"; rest="${spec#*:}"; what="${rest#*:}"
      if [ -f "$HERE/$rel" ]; then
        printf "  present  %-44s %s\n" "$rel" "$(du -h "$HERE/$rel" | cut -f1)"
      else
        printf "  MISSING  %-44s %s\n" "$rel" "$what"; missing=$((missing+1))
      fi
    done
    [ "$missing" -eq 0 ] && echo "all present" \
      || echo "$missing missing — run without --check to fetch"
    exit 0 ;;
esac

echo "fetching vendor catalogues into $HERE"
got=0; gone=0
for spec in "${FILES[@]}"; do
  rel="${spec%%:*}"; rest="${spec#*:}"; key="${rest%%:*}"
  mkdir -p "$(dirname "$HERE/$rel")"
  if aws s3 cp "s3://$BUCKET/vendor/$key" "$HERE/$rel" --quiet 2>/dev/null; then
    printf "  fetched  %-44s %s\n" "$rel" "$(du -h "$HERE/$rel" | cut -f1)"
    got=$((got+1))
  else
    printf "  absent   %-44s\n" "$rel"; gone=$((gone+1))
  fi
done

# Nexans documentation set
if aws s3 ls "s3://$BUCKET/$NEXANS_DOCS_PREFIX" >/dev/null 2>&1; then
  n=$(aws s3 sync "s3://$BUCKET/$NEXANS_DOCS_PREFIX" "$HERE/cables/" \
        --exclude "*" --include "*.md" --quiet 2>/dev/null && \
      aws s3 ls "s3://$BUCKET/$NEXANS_DOCS_PREFIX" | wc -l | tr -d " ")
  printf "  fetched  %-44s %s files\n" "cables/*.md (Nexans docs)" "$n"
  got=$((got+1))
fi

echo
echo "fetched $got, absent $gone"
echo "These files are gitignored. Do not commit them."
