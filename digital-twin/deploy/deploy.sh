#!/usr/bin/env bash
# Push the current working tree to the running instance and restart the service.
#
# Deploys are an rsync and a systemctl restart: the app is pure Python, so there
# is nothing to build. Connections drop on restart; the viewer reconnects by
# itself and gets a freshly settled hall.
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
APP_DIR="${APP_DIR:-/opt/dthall}"
KEYNAME="${KEYNAME:-asinclair-dev}"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"

log() { printf '[deploy] %s\n' "$*"; }

IP="${IP:-$(aws --region "$REGION" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" Name=instance-state-name,Values=running \
  --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)}"
[ -n "$IP" ] && [ "$IP" != "None" ] || { echo "[deploy] no running instance named $NAME" >&2; exit 1; }
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
log "target $IP ($DOMAIN)"

SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null
     -o LogLevel=ERROR ubuntu@"$IP")

# The viewer needs its geometry bundle; regenerate if absent so a fresh clone
# cannot deploy a viewer that fails to load.
if [ ! -f "$HERE/viewer/geometry/geometry.bin" ]; then
  log "building the viewer geometry bundle"
  (cd "$HERE" && python3 viewer/prepare_geometry.py >/dev/null)
fi

log "syncing source"
"${SSH[@]}" "sudo mkdir -p $APP_DIR && sudo chown -R ubuntu:ubuntu $APP_DIR"
rsync -az --delete \
  -e "ssh -i $KEYFILE -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR" \
  --exclude '__pycache__' --exclude '.pytest_cache' --exclude 'runs/' \
  --exclude 'ue/' --exclude 'fields/baked/_verify_*' --exclude '*.egg-info' \
  "$HERE/rom" "$HERE/viewer" "$HERE/pyproject.toml" "$HERE/README.md" \
  ubuntu@"$IP":"$APP_DIR/"

log "installing (runtime deps only: numpy + websockets)"
"${SSH[@]}" bash -s <<REMOTE
set -euo pipefail
cd "$APP_DIR"
[ -d venv ] || python3 -m venv venv
./venv/bin/pip install -q --upgrade pip
./venv/bin/pip install -q .
sudo chown -R dthall:dthall "$APP_DIR"
sudo systemctl restart dthall
REMOTE

log "waiting for health"
for _ in $(seq 1 30); do
  if out=$("${SSH[@]}" "curl -fsS http://127.0.0.1:8765/healthz" 2>/dev/null); then
    echo "[deploy] local health: $out"; break
  fi
  sleep 2
done

log "checking public URL"
for _ in $(seq 1 20); do
  if out=$(curl -fsS --max-time 10 "https://$DOMAIN/healthz" 2>/dev/null); then
    echo "[deploy] public health: $out"
    echo "[deploy] live at https://$DOMAIN/"
    exit 0
  fi
  sleep 5
done
echo "[deploy] public URL not answering yet — TLS may still be issuing." >&2
echo "[deploy]   check: ssh -i $KEYFILE ubuntu@$IP 'journalctl -u caddy -n 40'" >&2
