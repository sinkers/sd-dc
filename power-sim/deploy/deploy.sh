#!/usr/bin/env bash
# Publish power-sim to the box that already runs the air twin, the loop viewer
# and cable sizing, at https://au01-twin.dametech.net/power/.
#
# Unlike the loop viewer this is not static: the viewer re-runs the day on the
# service whenever a setting changes. So it is a systemd unit on a loopback
# port (standard library Python, no venv, nothing to build) behind a Caddy
# drop-in route, the same shape as cable sizing.
#
# It shares the host and certificate and nothing else: its own user, its own
# directory, its own port. The unit is capped at half a core and 256 MB so a
# burst of requests cannot starve the air twin, and the Caddy reload is
# validated before it is applied.
#
#   ./deploy/deploy.sh                     # deploy to /power/
#   BASE_PATH=/elec ./deploy/deploy.sh     # somewhere else
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
BASE_PATH="${BASE_PATH:-/power}"
APP_DIR="${APP_DIR:-/opt/dtpower}"
PORT="${PORT:-8780}"
SVC_USER="${SVC_USER:-dtpower}"
KEYNAME="${KEYNAME:-asinclair-dev}"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }

IP="${IP:-$(aws --region "$REGION" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)}"
[ -n "$IP" ] && [ "$IP" != "None" ] || { echo "[deploy] no running instance named $NAME" >&2; exit 1; }
log "target $IP ($DOMAIN$BASE_PATH/)"

SSH_OPTS=(-i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR -o ConnectTimeout=20)
SSH=(ssh "${SSH_OPTS[@]}" ubuntu@"$IP")

# Never publish something that fails its own tests.
log "running the tests"
(cd "$HERE/model" && python3 -m pytest -q tests >/dev/null) || { echo "[deploy] tests failed; not deploying" >&2; exit 1; }

log "syncing model and viewer"
"${SSH[@]}" "sudo mkdir -p $APP_DIR && sudo chown -R ubuntu:ubuntu $APP_DIR"
rsync -az --delete -e "ssh ${SSH_OPTS[*]}" \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'tests/' \
  "$HERE/model" "$HERE/viewer" "$HERE/README.md" ubuntu@"$IP":"$APP_DIR/"

log "installing the service and the Caddy route at $BASE_PATH/"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail

id -u $SVC_USER >/dev/null 2>&1 || sudo useradd --system --no-create-home --shell /usr/sbin/nologin $SVC_USER
sudo chown -R root:root $APP_DIR
sudo chmod -R a+rX $APP_DIR

sudo tee /etc/systemd/system/dtpower.service >/dev/null <<'UNIT'
[Unit]
Description=Power sim: grid, BESS, UPS and GPU load simulations
After=network.target

[Service]
Type=simple
User=$SVC_USER
WorkingDirectory=$APP_DIR/model
Environment=PYTHONUNBUFFERED=1
Environment=PYTHONDONTWRITEBYTECODE=1
Environment=DTPOWER_VIEWER_ROOT=$APP_DIR/viewer
ExecStart=/usr/bin/python3 -m dtpower serve --host 127.0.0.1 --port $PORT
Restart=on-failure
RestartSec=2
# Shares a 2 vCPU box with the air twin, which streams in real time. A day
# solves in 30-110 ms; the quota stops a burst of runs from crowding it out.
CPUQuota=50%
MemoryMax=256M
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadOnlyPaths=$APP_DIR

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable dtpower >/dev/null 2>&1
sudo systemctl restart dtpower

for i in \$(seq 1 20); do
  curl -sf http://127.0.0.1:$PORT/healthz >/dev/null && break
  sleep 0.5
done
curl -sf http://127.0.0.1:$PORT/healthz >/dev/null || { echo "[remote] dtpower did not come up" >&2; sudo journalctl -u dtpower -n 30 --no-pager >&2; exit 1; }

sudo mkdir -p /etc/caddy/sites.d
sudo tee /etc/caddy/sites.d/30-power.caddy >/dev/null <<'ROUTE'
# Power sim. The viewer and its JSON API, from one loopback service.
#
# handle_path strips the prefix, so /power/api/sims reaches the service as
# /api/sims. Every URL in the page is relative, which is why the redirect
# matters: without the trailing slash the browser resolves them against / and
# talks to the air twin instead.
redir $BASE_PATH $BASE_PATH/
handle_path $BASE_PATH/* {
	reverse_proxy 127.0.0.1:$PORT
}
ROUTE

# Validate before reloading: this Caddyfile also serves the air twin, the loop
# viewer and cable sizing, and a broken route would take them all down.
if ! sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/tmp/caddy-validate.log 2>&1; then
  echo "[remote] Caddyfile did not validate; removing the route and leaving the other sites alone" >&2
  sudo rm -f /etc/caddy/sites.d/30-power.caddy
  tail -20 /tmp/caddy-validate.log >&2
  exit 1
fi
sudo systemctl reload caddy
REMOTE

log "checking every site on the box"
fail=0
check() {  # check <url> [method] [body]
  local code
  if [ "${2:-GET}" = POST ]; then
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 -X POST -H 'Content-Type: application/json' -d "$3" "$1" || echo 000)
  else
    code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 20 "$1" || echo 000)
  fi
  printf '[deploy]   %-62s %s\n' "$1" "$code"
  [ "$code" = "200" ] || fail=1
}
check "https://$DOMAIN/healthz"
check "https://$DOMAIN/loop/"
check "https://$DOMAIN$BASE_PATH/"
check "https://$DOMAIN$BASE_PATH/api/sims/bess-dr"
check "https://$DOMAIN$BASE_PATH/api/sims/bess-dr/run" POST '{"scenario":"nsw-spike"}'

if [ "$fail" -ne 0 ]; then
  echo "[deploy] something is not answering; check: ssh -i $KEYFILE ubuntu@$IP 'journalctl -u dtpower -u caddy -n 40'" >&2
  exit 1
fi
log "live at https://$DOMAIN$BASE_PATH/"
