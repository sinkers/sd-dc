#!/usr/bin/env bash
# Provision a fresh Ubuntu arm64 host to serve the AU01 twin.
#
# Runs ON the instance. Idempotent — safe to re-run over a working host, which is
# the point: re-running is how you upgrade Caddy or repair a broken unit without
# rebuilding.
#
# No Docker. The service is pure Python (numpy + websockets), so a venv and a
# systemd unit is less machinery than a daemon and ~200 MB more free RAM on a
# 2 GB box. Caddy terminates TLS, gets its certificate from Let's Encrypt
# automatically, and reverse-proxies WebSockets without configuration.
set -euo pipefail

DOMAIN="${DOMAIN:?DOMAIN must be set, e.g. au01-twin.dametech.net}"
APP_USER="${APP_USER:-dthall}"
APP_DIR="${APP_DIR:-/opt/dthall}"
PORT="${PORT:-8765}"

log() { printf '[provision] %s\n' "$*"; }

# Ubuntu's unattended-upgrades holds the dpkg lock on a fresh boot; the CFD
# provisioner learned this the hard way, so wait it out rather than fail.
wait_for_apt() {
  local waited=0
  while sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    [ "$waited" -ge 300 ] && { echo "dpkg lock held for 5 min, giving up" >&2; exit 1; }
    sleep 5; waited=$((waited + 5))
    [ $((waited % 30)) -eq 0 ] && log "waiting for dpkg lock (${waited}s)"
  done
}

log "installing packages"
wait_for_apt
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
wait_for_apt
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
  python3 python3-venv python3-pip rsync curl debian-keyring debian-archive-keyring apt-transport-https

if ! command -v caddy >/dev/null 2>&1; then
  log "installing Caddy from the official repo"
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
    | sudo gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
  curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
    | sudo tee /etc/apt/sources.list.d/caddy-stable.list >/dev/null
  wait_for_apt
  sudo apt-get update -qq
  wait_for_apt
  sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq caddy
fi

log "creating service user and directories"
id -u "$APP_USER" >/dev/null 2>&1 || sudo useradd --system --home "$APP_DIR" --shell /usr/sbin/nologin "$APP_USER"
sudo mkdir -p "$APP_DIR"
sudo chown -R "$APP_USER:$APP_USER" "$APP_DIR"

log "writing the Caddyfile for $DOMAIN"
sudo tee /etc/caddy/Caddyfile >/dev/null <<CADDY
# Automatic HTTPS: Caddy obtains and renews a Let's Encrypt certificate for
# \$DOMAIN, which requires ports 80 and 443 reachable from the internet and the
# DNS A record already pointing here.
$DOMAIN {
	encode zstd gzip

	# reverse_proxy passes WebSocket upgrades through untouched. The solver only
	# ever listens on loopback, so this is its sole route in.
	reverse_proxy 127.0.0.1:$PORT

	header {
		X-Content-Type-Options nosniff
		X-Frame-Options SAMEORIGIN
		Referrer-Policy no-referrer
		-Server
	}

	# Access logs go to the journal (Caddy's default). An explicit file sink was
	# tried and removed: the packaged unit runs ProtectSystem=full as user caddy,
	# so Caddy cannot open /var/log/caddy/access.log however the directory is
	# owned, and the reload fails with "permission denied". journald already
	# rotates, and journalctl -u caddy is where you would look anyway.
	#
	# NOTE: this heredoc is unquoted so that \$DOMAIN expands, which means
	# backticks in it would be command substitution. Do not use them here.
}
CADDY

log "writing the systemd unit"
sudo tee /etc/systemd/system/dthall.service >/dev/null <<UNIT
[Unit]
Description=AU01 digital twin
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$APP_USER
WorkingDirectory=$APP_DIR
Environment=PYTHONUNBUFFERED=1
# Public endpoint guards. Raise DTHALL_MAX_SESSIONS only after checking headroom:
# each session costs ~0.5% of a core at the default speed and ~2% at the cap.
Environment=DTHALL_MAX_SESSIONS=40
Environment=DTHALL_MAX_SPEED=60
Environment=DTHALL_MAX_CMD_RATE=20
Environment=DTHALL_MAX_SESSION_S=14400
Environment=DTHALL_PUBLISH_HZ=10
Environment=DTHALL_MODE=auto
# An installed package has no sibling viewer/; point at the deployed copy.
Environment=DTHALL_VIEWER_ROOT=$APP_DIR/viewer
ExecStart=$APP_DIR/venv/bin/python -m dthall.cli run --host 127.0.0.1 --port $PORT
Restart=always
RestartSec=3
# The service needs nothing but its own directory.
NoNewPrivileges=yes
PrivateTmp=yes
ProtectSystem=strict
ProtectHome=yes
ReadWritePaths=$APP_DIR

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable caddy
# `enable --now` does NOT restart an already-running unit, and apt starts Caddy
# with its default Caddyfile the moment it is installed. Without an explicit
# reload the host keeps serving that default — port 80 only, no automatic HTTPS —
# and the site never gets a certificate. Validate first so a bad Caddyfile fails
# here rather than taking the running service down.
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload-or-restart caddy
log "provisioned. Push code with deploy.sh, then: systemctl start dthall"
