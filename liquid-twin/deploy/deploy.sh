#!/usr/bin/env bash
# Publish the loop review viewer to the box that already runs the air twin.
#
# The viewer is entirely static - HTML, one JS module, a 0.6 MB geometry bundle
# and a manifest carrying the solved hydraulics - so there is no service to
# install and nothing to restart. It is an rsync and a Caddy route.
#
# It shares a host and a certificate with the air twin at au01-twin.dametech.net
# and sits at /loop/. The two do not share anything else: separate directory,
# no Python, no port. Deploying one cannot take the other down, and the Caddy
# reload below is validated before it is applied for the same reason.
#
#   ./deploy/deploy.sh                    # deploy to /loop/
#   BASE_PATH=/liquid ./deploy/deploy.sh  # somewhere else
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
BASE_PATH="${BASE_PATH:-/loop}"
APP_DIR="${APP_DIR:-/opt/dtloop}"
KEYNAME="${KEYNAME:-asinclair-dev}"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }

IP="${IP:-$(aws --region "$REGION" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)}"
[ -n "$IP" ] && [ "$IP" != "None" ] || { echo "[deploy] no running instance named $NAME" >&2; exit 1; }
log "target $IP ($DOMAIN$BASE_PATH/)"

SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
     -o LogLevel=ERROR -o ConnectTimeout=20 ubuntu@"$IP")

# Rebuild the bundle if it is missing, so a fresh clone cannot publish a viewer
# that fails to load. It is regenerable from dtloop.layout and needs no FreeCAD.
if [ ! -f "$HERE/viewer/geometry/manifest.json" ]; then
  log "building the geometry bundle"
  (cd "$HERE" && ./viewer/prepare_geometry.py >/dev/null)
fi

log "syncing the viewer"
"${SSH[@]}" "sudo mkdir -p $APP_DIR && sudo chown -R ubuntu:ubuntu $APP_DIR"
rsync -az --delete \
  -e "ssh -i $KEYFILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  --exclude '__pycache__' \
  "$HERE/viewer/" ubuntu@"$IP":"$APP_DIR/viewer/"

log "installing the Caddy route at $BASE_PATH/"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail

sudo mkdir -p /etc/caddy/sites.d

# Make sure the site block imports the drop-in directory. provision.sh writes
# this line on a new box; adding it here idempotently means an existing box does
# not have to be re-provisioned - which would restart the air twin and drop its
# sessions for a change that is one line of config.
#
# One line inserted, and no attempt to rewrite anything else in there: the file
# also serves the air twin, and a sed that got clever with it would be a poor
# trade for the seconds it saves.
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
sudo tee /etc/caddy/sites.d/10-loop.caddy >/dev/null <<'ROUTE'
# Liquid loop review viewer. Static files, no service.
#
# handle_path strips the prefix, so /loop/app.js is served from
# $APP_DIR/viewer/app.js. Every URL in the page is relative, which is why the
# redirect below matters: without a trailing slash the browser resolves them
# against / and fetches the air twin's index instead of the bundle.
redir $BASE_PATH $BASE_PATH/
handle_path $BASE_PATH/* {
	root * $APP_DIR/viewer
	file_server
}
ROUTE

# Validate before reloading. This Caddyfile also serves the air twin, and a
# broken route file would take it down with it - so a bad snippet is removed
# here rather than discovered by a user.
if ! sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  echo "[remote] Caddyfile did not validate; removing the route and leaving the air twin alone" >&2
  sudo rm -f /etc/caddy/sites.d/10-loop.caddy
  tail -20 /tmp/caddy-validate.log >&2
  exit 1
fi

# Reload, not restart: no dropped connections on the air twin's WebSockets.
sudo systemctl reload caddy
REMOTE

log "checking both sites"
fail=0
for url in "https://$DOMAIN/healthz" "https://$DOMAIN$BASE_PATH/" \
           "https://$DOMAIN$BASE_PATH/geometry/manifest.json"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url" || echo 000)
  printf '[deploy]   %-58s %s\n' "$url" "$code"
  [ "$code" = "200" ] || fail=1
done

if [ "$fail" -ne 0 ]; then
  echo "[deploy] something is not answering; check: ssh -i $KEYFILE ubuntu@$IP 'journalctl -u caddy -n 40'" >&2
  exit 1
fi
log "live at https://$DOMAIN$BASE_PATH/"
