#!/usr/bin/env bash
#
# Provision a bare Ubuntu box to run these cases via the OpenFOAM container.
#
# Docker rather than the apt packages, deliberately: the opencfd image is
# multi-arch, so the remote environment is bit-identical to the local one and
# there is no question of whether the Debian repo carries arm64 builds.
#
# Idempotent and safe to re-run. Detached under setsid so a dropped SSH
# connection cannot abort a half-finished apt transaction.
#
#   ./remote/provision-docker.sh ubuntu@1.2.3.4 ~/.ssh/key.pem
#
set -euo pipefail

IMAGE="${IMAGE:-opencfd/openfoam-default:2406}"
HOST="${1:?usage: $0 user@host [ssh-key]}"
KEY="${2:-}"
OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new
      -o UserKnownHostsFile=/dev/null -o ServerAliveInterval=30)
[ -n "$KEY" ] && OPTS+=(-i "$KEY")

remote_script() {
cat <<BODY
set -euo pipefail
IMAGE="$IMAGE"
log() { echo "[provision] \$*"; }

if docker image inspect "\$IMAGE" >/dev/null 2>&1; then
    log "image already present"
else
    if ! command -v docker >/dev/null 2>&1; then
        log "waiting for any apt lock to clear"
        for _ in \$(seq 1 180); do
            sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 || break
            sleep 5
        done
        sudo dpkg --configure -a 2>/dev/null || true
        log "installing docker.io and rsync"
        # The regional Ubuntu mirror returns transient 503s often enough to kill
        # a spot run outright - one did, fetching ubuntu-fan. Retry the whole
        # transaction, and let apt retry individual fetches too.
        ok=0
        for attempt in 1 2 3 4; do
            sudo apt-get update -qq -o Acquire::Retries=5 || true
            if sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
                   -o Acquire::Retries=5 --fix-missing docker.io rsync
            then ok=1; break
            fi
            log "apt attempt \$attempt failed, retrying in 20 s"
            sleep 20
        done
        if [ "\$ok" != "1" ]; then
            log "apt failed after 4 attempts"
            exit 1
        fi
        sudo usermod -aG docker ubuntu || true
    fi
    log "pulling \$IMAGE (this is the slow part)"
    sudo docker pull -q "\$IMAGE"
fi

sudo docker run --rm "\$IMAGE" bash -lc 'echo "[provision] OpenFOAM \$WM_PROJECT_VERSION \$WM_ARCH"'
cores=\$(lscpu | awk -F: '/^Core\(s\) per socket/{c=\$2} /^Socket\(s\)/{s=\$2} END{print c*s}' | tr -d ' ')
log "physical cores: \$cores"
free -g | awk '/^Mem:/{print "[provision] RAM: "\$2" GB"}'
df -h --output=avail / | tail -1 | awk '{print "[provision] free disk: "\$1}'
log "done"
BODY
}

echo "[provision] provisioning $HOST (detached)"
remote_script | ssh "${OPTS[@]}" "$HOST" \
  "cat > /tmp/prov.sh"
# Separate calls on purpose. 'cat > f && setsid ... & echo x' parses as
# '(cat > f && setsid ...) &', which backgrounds cat -- and a backgrounded job in
# a non-interactive shell gets stdin from /dev/null, so the script arrives empty.
ssh "${OPTS[@]}" "$HOST" \
  'setsid nohup bash /tmp/prov.sh > /tmp/provision.log 2>&1 < /dev/null & echo started'

# Poll the log rather than the process: no race on start-up, and it reports
# progress as it goes.
seen=0
for _ in $(seq 1 240); do          # up to 40 minutes
    out=$(ssh "${OPTS[@]}" "$HOST" 'cat /tmp/provision.log 2>/dev/null' 2>/dev/null || true)
    total=$(printf '%s' "$out" | wc -l | tr -d ' ')
    if [ "$total" -gt "$seen" ]; then
        printf '%s\n' "$out" | tail -n +$((seen + 1)) | sed 's/^/  /'
        seen=$total
    fi
    printf '%s' "$out" | grep -q '\[provision\] done' && { echo "[provision] SUCCESS"; exit 0; }
    printf '%s' "$out" | grep -qE '^E: |Unable to locate|no such|denied' && break
    sleep 10
done
echo "[provision] FAILED - full log:" >&2
ssh "${OPTS[@]}" "$HOST" 'cat /tmp/provision.log' >&2 || true
exit 1
