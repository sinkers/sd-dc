#!/usr/bin/env bash
# Fetch the licensed standards tables that cable-sizing reads.
#
# These are transcribed from licensed copies of AS/NZS 3008.1.1:2025 and
# AS/NZS 3000:2018. Standards Australia holds the copyright, so the tables are
# not in this repository — the code that reads them is open source, the tables
# are not. Same posture the established calculators take: jCalc, Elek and Tricab
# all hold the tables server-side and return only results.
#
#   ./tools/data_pull_standards.sh              fetch into cable-sizing/
#   ./tools/data_pull_standards.sh --list       what is available
#   ./tools/data_pull_standards.sh --check      report what is present locally
#
# You need your own licensed copy of the standards to use these legitimately.
# Without credentials the test suites run against the synthetic fixture instead.
set -euo pipefail

BUCKET="${SDDC_ARTIFACTS_BUCKET:?set SDDC_ARTIFACTS_BUCKET to your artifacts bucket}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HERE/cable-sizing"

FILES=(
  as3008_impedance_tables.json    # AS/NZS 3008.1.1:2025 Tables 4.1-4.13
  as3008_vc_tables.json           # Tables 4.14-4.31
  as3008_short_circuit.json       # Table 5.2
  as3008_ratings.json             # Table 3.14
  reference_tables.json           # AS/NZS 3000:2018 tables 3.2/3.3/3.4/C8/C10-C12
)

case "${1:-}" in
  --list)
    echo "s3://$BUCKET/standards/"
    aws s3 ls "s3://$BUCKET/standards/" --recursive --human-readable \
      | awk '{printf "  %-10s %s\n", $3" "$4, $5}'
    exit 0 ;;
  --check)
    echo "local standards data in $DEST:"
    missing=0
    for f in "${FILES[@]}"; do
      if [ -f "$DEST/$f" ]; then
        printf "  present  %-32s %s\n" "$f" "$(du -h "$DEST/$f" | cut -f1)"
      else
        printf "  MISSING  %-32s\n" "$f"; missing=$((missing+1))
      fi
    done
    [ "$missing" -eq 0 ] && echo "all present" || echo "$missing missing — run without --check to fetch"
    exit 0 ;;
esac

echo "fetching standards tables into $DEST"
got=0 gone=0
for f in "${FILES[@]}"; do
  # AS/NZS 3000 material sits under a different prefix from AS/NZS 3008.
  case "$f" in
    reference_tables.json) prefix="standards/as-nzs-3000" ;;
    *)                     prefix="standards/as-nzs-3008" ;;
  esac
  if aws s3 cp "s3://$BUCKET/$prefix/$f" "$DEST/$f" --quiet 2>/dev/null; then
    printf "  fetched  %-32s %s\n" "$f" "$(du -h "$DEST/$f" | cut -f1)"
    got=$((got+1))
  else
    printf "  absent   %-32s (not yet uploaded)\n" "$f"
    gone=$((gone+1))
  fi
done

echo
echo "fetched $got, absent $gone"
if [ "$gone" -gt 0 ]; then
  echo "Absent files are not an error while B5 is in progress — see PUBLISH-REVIEW.md."
fi
echo "These files are gitignored. Do not commit them."
