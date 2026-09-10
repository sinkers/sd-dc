#!/usr/bin/env bash
# Publish the cable sizer's MCP endpoint to the box that already runs the air twin.
#
# The MCP server itself speaks stdio, which a hosted client cannot spawn, so what
# is deployed is http_mcp_server.py: the same dispatch reached over HTTP. It runs
# on loopback as its own user and Caddy is its only route in, sharing the host and
# certificate with the air twin at au01-twin.dametech.net.
#
# The two share nothing else: separate directory, separate user, separate port,
# separate systemd unit. Deploying one cannot take the other down, and the Caddy
# reload is validated before it is applied for exactly that reason.
#
#   ./deploy/deploy.sh                     # deploy to /cable/
#   MCP_TOKEN=... ./deploy/deploy.sh       # pin the bearer token
#   BASE_PATH=/sizing ./deploy/deploy.sh   # somewhere else
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
BASE_PATH="${BASE_PATH:-/cable}"
APP_DIR="${APP_DIR:-/opt/dcable}"
APP_USER="${APP_USER:-dcable}"
PORT="${PORT:-8766}"
KEYNAME="${KEYNAME:-asinclair-dev}"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }

# A token is generated on first deploy and then reused, so redeploying does not
# silently invalidate a connector someone has already configured.
TOKEN="${MCP_TOKEN:-}"

IP="${IP:-$(aws --region "$REGION" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)}"
[ -n "$IP" ] && [ "$IP" != "None" ] || { echo "[deploy] no running instance named $NAME" >&2; exit 1; }
log "target $IP ($DOMAIN$BASE_PATH/)"

SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
     -o LogLevel=ERROR -o ConnectTimeout=20 ubuntu@"$IP")

log "syncing source"
"${SSH[@]}" "sudo mkdir -p $APP_DIR && sudo chown -R ubuntu:ubuntu $APP_DIR"
# The licensed tables travel with the code: the engine cannot answer without
# them, and this box is ours. They are gitignored, so rsync is how they arrive.
rsync -az --delete \
  -e "ssh -i $KEYFILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'out/' \
  --exclude 'reference/' --exclude 'fixtures/' --exclude 'tests/' \
  --exclude '*.egg-info' --exclude 'deploy/' \
  --include 'data/***' \
  "$HERE"/*.py "$HERE"/*.json "$HERE"/data "$HERE"/dame_cable \
  ubuntu@"$IP":"$APP_DIR/"

# Two data files live in sibling components in a checkout. tables.path_for()
# prefers a flat file in the data dir over the sibling path, which is exactly
# the hook for a deploy: copy them in flat and nothing has to know it is not a
# checkout. Without these, size_cable raises FileNotFoundError on first call.
log "syncing the sibling catalogues"
rsync -az \
  -e "ssh -i $KEYFILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  "$HERE/../cables/cable_catalog.json" \
  "$HERE/../cable-tray-ezystrut/tray_catalogue.json" \
  ubuntu@"$IP":"$APP_DIR/"

log "installing the service"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail

id -u $APP_USER >/dev/null 2>&1 || sudo useradd --system --no-create-home --shell /usr/sbin/nologin $APP_USER

# Reuse an existing token so a configured connector keeps working across deploys.
SUPPLIED="${TOKEN}"
if [ -n "\$SUPPLIED" ]; then
  TOKEN="\$SUPPLIED"
elif sudo test -f /etc/dcable.env; then
  TOKEN=\$(sudo sed -n 's/^MCP_TOKEN=//p' /etc/dcable.env)
else
  TOKEN=\$(python3 -c 'import secrets;print(secrets.token_urlsafe(32))')
fi
printf 'MCP_TOKEN=%s\n' "\$TOKEN" | sudo tee /etc/dcable.env >/dev/null
sudo chmod 640 /etc/dcable.env
sudo chown root:$APP_USER /etc/dcable.env

sudo tee /etc/systemd/system/dcable.service >/dev/null <<UNIT
[Unit]
Description=Cable sizing MCP over HTTP (AS/NZS 3008.1.1)
After=network.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=/etc/dcable.env
ExecStart=/usr/bin/python3 $APP_DIR/http_mcp_server.py --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=2
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=$APP_DIR

[Install]
WantedBy=multi-user.target
UNIT

sudo chown -R $APP_USER:$APP_USER "$APP_DIR"
sudo systemctl daemon-reload
sudo systemctl enable --now dcable
sudo systemctl restart dcable
REMOTE

log "installing the Caddy route at $BASE_PATH/"
TOKEN=$("${SSH[@]}" "sudo sed -n 's/^MCP_TOKEN=//p' /etc/dcable.env")
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail
sudo mkdir -p /etc/caddy/sites.d

# handle_path strips the prefix, so $BASE_PATH/mcp reaches the service as /mcp.
# Two ways in, same service.
#
#   $BASE_PATH/mcp          bearer token in the Authorization header. Correct
#                           for anything that can set headers - curl, an SDK,
#                           a stdio bridge.
#   $BASE_PATH/s/<token>/mcp  token in the path, injected as a header by Caddy.
#                           Claude's custom-connector UI takes a URL and no
#                           header, so without this it cannot authenticate at
#                           all. The URL *is* the credential: it is as secret
#                           as the token, travels encrypted under TLS, but
#                           will sit in browser history and any proxy log that
#                           records paths. Rotate it by deploying with a new
#                           MCP_TOKEN.
sudo tee /etc/caddy/sites.d/20-cable.caddy >/dev/null <<ROUTE
handle_path $BASE_PATH/s/$TOKEN/* {
	reverse_proxy 127.0.0.1:$PORT {
		header_up Authorization "Bearer $TOKEN"
	}
}
handle_path $BASE_PATH/* {
	reverse_proxy 127.0.0.1:$PORT
}
ROUTE

# This Caddyfile also serves the air twin. A broken snippet would take it down,
# so a snippet that does not validate is removed here rather than found by a user.
if ! sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  echo "[remote] Caddyfile did not validate; removing the route and leaving the air twin alone" >&2
  sudo rm -f /etc/caddy/sites.d/20-cable.caddy
  tail -20 /tmp/caddy-validate.log >&2
  exit 1
fi
sudo systemctl reload caddy
REMOTE

log "verifying"
TOKEN=$("${SSH[@]}" "sudo sed -n 's/^MCP_TOKEN=//p' /etc/dcable.env")
fail=0
for url in "https://$DOMAIN/healthz" "https://$DOMAIN$BASE_PATH/healthz"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$url" || echo 000)
  printf '[deploy]   %-58s %s\n' "$url" "$code"
  [ "$code" = "200" ] || fail=1
done
code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
  "https://$DOMAIN$BASE_PATH/mcp" -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || echo 000)
printf '[deploy]   %-58s %s\n' "POST $BASE_PATH/mcp (tools/list)" "$code"
[ "$code" = "200" ] || fail=1

if [ "$fail" -ne 0 ]; then
  echo "[deploy] something is not answering; check:" >&2
  echo "[deploy]   ssh -i $KEYFILE ubuntu@$IP 'journalctl -u dcable -n 40'" >&2
  exit 1
fi

code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST \
  "https://$DOMAIN$BASE_PATH/s/$TOKEN/mcp" -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' || echo 000)
printf '[deploy]   %-58s %s\n' "POST $BASE_PATH/s/<token>/mcp (no header)" "$code"
[ "$code" = "200" ] || fail=1

echo
log "MCP endpoint (header auth):  https://$DOMAIN$BASE_PATH/mcp"
# The token is deliberately NOT printed by default. It is the credential, and a
# deploy log gets pasted into chat, captured by CI and read over a shared
# screen. It already lives in /etc/dcable.env on the box; fetch it from there,
# or pass --show-token when you actually need to configure a client.
if [ "${1:-}" = "--show-token" ] || [ "${SHOW_TOKEN:-}" = "1" ]; then
  log "MCP endpoint (URL auth):     https://$DOMAIN$BASE_PATH/s/$TOKEN/mcp"
  log "bearer token:                $TOKEN"
else
  log "MCP endpoint (URL auth):     https://$DOMAIN$BASE_PATH/s/${TOKEN:0:4}...REDACTED/mcp"
  log "bearer token:                ${TOKEN:0:4}...  (re-run with --show-token, or:"
  log "                             ssh ubuntu@$IP \"sudo cat /etc/dcable.env\")"
fi
