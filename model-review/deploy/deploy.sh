#!/usr/bin/env bash
# Publish the model review viewer to the au01-twin box behind an unguessable path.
#
#   ./deploy/deploy.sh              # first run mints the path, later runs reuse it
#   BASE_PATH=/m/<uuid> ./deploy/deploy.sh
#   ./deploy/deploy.sh --rotate     # mint a new path and drop the old one
#
# Static files only: no service, no port, nothing to restart. The viewer lands
# next to the air twin (/) and the liquid loop (/loop/) as another drop-in Caddy
# route, so publishing it cannot disturb either - the route file is validated
# before Caddy reloads, and removed again if it does not validate.
#
# THE PATH IS OBSCURITY, NOT AUTHENTICATION. Anyone holding the link, and
# anything that scrapes it out of a browser history, a chat thread or a referrer
# header, gets the full AU01 design: site layout, vendor selections, rack counts.
# That was a deliberate call. To add a password later, put a basic_auth block in
# the route file below and re-run; nothing else has to change.
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
KEYNAME="${KEYNAME:-asinclair-dev}"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
REMOTE_DIR="${REMOTE_DIR:-/opt/model-review}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
PATH_FILE="$HERE/deploy/.published-path"

log() { printf '[deploy] %s\n' "$*"; }

# The published path lives in a gitignored file so re-deploys keep the same URL
# and the URL does not travel with the repository.
if [ "${1:-}" = "--rotate" ]; then
  rm -f "$PATH_FILE"
  log "rotating: the previous path will stop working"
fi
if [ -n "${BASE_PATH:-}" ]; then
  :
elif [ -f "$PATH_FILE" ]; then
  BASE_PATH="$(cat "$PATH_FILE")"
else
  BASE_PATH="/m/$(uuidgen | tr 'A-Z' 'a-z')"
  printf '%s' "$BASE_PATH" > "$PATH_FILE"
  log "minted a new path: $BASE_PATH"
fi

if [ ! -f "$HERE/viewer/model/au01.packed.glb" ]; then
  echo "[deploy] no packed model at viewer/model/au01.packed.glb; run ./export.sh first" >&2
  exit 1
fi

IP="${IP:-$(aws --region "$REGION" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)}"
[ -n "$IP" ] && [ "$IP" != "None" ] || { echo "[deploy] no running instance named $NAME" >&2; exit 1; }
log "target $IP ($DOMAIN) at $BASE_PATH/"

SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
     -o LogLevel=ERROR ubuntu@"$IP")

log "syncing the viewer ($(du -sh "$HERE/viewer/model/au01.packed.glb" | cut -f1) model)"
"${SSH[@]}" "sudo mkdir -p $REMOTE_DIR && sudo chown -R ubuntu:ubuntu $REMOTE_DIR"
# The uncompressed GLB is an export intermediate and is not served: excluded so a
# deploy moves ~8 MB rather than ~90 MB.
rsync -az --delete \
  -e "ssh -i $KEYFILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  --exclude 'model/au01.glb' --exclude '.DS_Store' \
  "$HERE/viewer/" ubuntu@"$IP":"$REMOTE_DIR/viewer/"

log "installing the Caddy route"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail

# Caddy runs as its own user and only needs to read these.
sudo chown -R ubuntu:ubuntu "$REMOTE_DIR"
sudo chmod -R a+rX "$REMOTE_DIR"
sudo mkdir -p /etc/caddy/sites.d

# provision.sh writes the drop-in import on a new box; add it idempotently here
# so an existing box does not need re-provisioning, which would restart the air
# twin and drop its sessions for what is one line of config.
if ! grep -q 'sites.d' /etc/caddy/Caddyfile; then
  echo "[remote] adding the drop-in import to the Caddyfile"
  sudo python3 - <<'PATCH'
import re
path = "/etc/caddy/Caddyfile"
src = open(path).read()
line = "\n\t# Drop-in routes from other components on this box.\n\timport /etc/caddy/sites.d/*.caddy\n"
patched, n = re.subn(r"(\n\tencode zstd gzip\n)", r"\1" + line, src, count=1)
if n != 1:
    raise SystemExit("could not find the anchor line in the Caddyfile; not touching it")
open(path, "w").write(patched)
PATCH
fi

sudo tee /etc/caddy/sites.d/20-model-review.caddy >/dev/null <<ROUTE
# AU01 FreeCAD model review viewer. Static files, no service.
#
# handle_path strips the prefix, so <path>/app.js is served from
# $REMOTE_DIR/viewer/app.js. Every URL in the page is relative, which is why the
# redirect matters: without the trailing slash the browser resolves them against
# / and fetches the air twin's index instead of this viewer.
redir $BASE_PATH $BASE_PATH/
handle_path $BASE_PATH/* {
	root * $REMOTE_DIR/viewer
	# No browse: a directory listing would hand out the path's contents to
	# anyone who trimmed the URL back to a folder.
	file_server
	header {
		# An unguessable path is worth nothing if a crawler indexes it.
		X-Robots-Tag "noindex, nofollow, noarchive"
		# Revalidate rather than cache hard: the model keeps its filename
		# across exports, so a long max-age would serve a stale model after
		# the next one. ETags make the recheck cheap.
		Cache-Control "no-cache"
	}
}
ROUTE

# Validate before reloading. This Caddyfile also serves the air twin and the
# liquid loop, and a broken snippet would take both down - so a bad route is
# removed here rather than discovered by whoever opens the link.
if ! sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  echo "[remote] Caddyfile did not validate; removing the route and leaving the other sites alone" >&2
  sudo rm -f /etc/caddy/sites.d/20-model-review.caddy
  tail -20 /tmp/caddy-validate.log >&2
  exit 1
fi

# Reload, not restart: no dropped WebSocket sessions on the air twin.
sudo systemctl reload caddy
REMOTE

log "checking every site on the box"
fail=0
for url in "https://$DOMAIN/healthz" "https://$DOMAIN/loop/" \
           "https://$DOMAIN$BASE_PATH/" \
           "https://$DOMAIN$BASE_PATH/model/au01.packed.glb" \
           "https://$DOMAIN$BASE_PATH/model/au01.parts.json"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 30 "$url" || echo 000)
  printf '[deploy]   %s  %s\n' "$code" "$url"
  [ "$code" = "200" ] || fail=1
done
[ "$fail" = "0" ] || { echo "[deploy] something is not answering 200" >&2; exit 1; }

echo
log "live at https://$DOMAIN$BASE_PATH/"
log "path recorded in deploy/.published-path — ./deploy/deploy.sh --rotate to change it"
