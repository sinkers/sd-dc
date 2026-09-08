#!/usr/bin/env bash
#
# Provision a bare Ubuntu box (22.04/24.04, x86_64 or arm64) to run this case.
# Written for SPOT / ephemeral instances: idempotent, unattended, and safe to
# re-run. Takes ~10 min on a cold box, seconds if already provisioned.
#
# Usage, from your laptop:
#   ./remote/provision-openfoam.sh ubuntu@1.2.3.4 ~/.ssh/mykey
#
# Or on the box itself:
#   sudo bash provision-openfoam.sh --local
#
set -euo pipefail

FOAM_VER="${FOAM_VER:-2406}"

remote_body() {
cat <<'BODY'
set -euo pipefail
FOAM_VER="__FOAM_VER__"
FOAM_BASHRC="/usr/lib/openfoam/openfoam${FOAM_VER}/etc/bashrc"

log() { echo "[provision] $*"; }

# Already done? Bail out cheaply so this is safe to re-run.
if [ -f "$FOAM_BASHRC" ]; then
    log "OpenFOAM ${FOAM_VER} already present"
else
    # Spot instances often boot with unattended-upgrades holding the dpkg lock.
    log "waiting for any apt/dpkg lock to clear (up to 20 min)"
    for _ in $(seq 1 240); do
        if ! sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1 \
           && ! pgrep -x apt-get >/dev/null && ! pgrep -x unattended-upgr >/dev/null; then
            break
        fi
        sleep 5
    done
    sudo dpkg --configure -a 2>/dev/null || true

    log "adding the OpenCFD apt repository"
    curl -fsSL https://dl.openfoam.com/add-debian-repo.sh | sudo bash

    log "installing openfoam${FOAM_VER}-default (this is the slow part)"
    sudo apt-get update -qq
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
        "openfoam${FOAM_VER}-default" rsync
fi

# Make the environment available to non-login shells too, so `ssh host cmd` works.
if ! grep -q "openfoam${FOAM_VER}/etc/bashrc" "$HOME/.bashrc" 2>/dev/null; then
    log "sourcing OpenFOAM from ~/.bashrc"
    printf '\n# OpenFOAM %s\n[ -f %s ] && . %s\n' \
        "$FOAM_VER" "$FOAM_BASHRC" "$FOAM_BASHRC" >> "$HOME/.bashrc"
fi

# Verify, and report what this box can actually do.
. "$FOAM_BASHRC"
log "OpenFOAM $WM_PROJECT_VERSION  arch=$WM_ARCH"
for t in blockMesh buoyantSimpleFoam subsetMesh createBaffles topoSet \
         createPatch decomposePar reconstructPar mpirun; do
    command -v "$t" >/dev/null || { echo "[provision] MISSING: $t" >&2; exit 1; }
done
log "all required tools present"

cores=$(lscpu | awk -F: '/^Core\(s\) per socket/{c=$2} /^Socket\(s\)/{s=$2} END{print c*s}' | tr -d ' ')
log "physical cores: ${cores}   (use this many MPI ranks, not nproc)"
log "recommended numberOfSubdomains for a mesh of N cells: min(${cores}, N/20000)"
free -g | awk '/^Mem:/{print "[provision] RAM: "$2" GB"}'
df -h --output=avail /home 2>/dev/null | tail -1 | awk '{print "[provision] free disk on /home: "$1}'
log "done"
BODY
}

if [ "${1:-}" = "--local" ]; then
    remote_body | sed "s/__FOAM_VER__/${FOAM_VER}/" | bash
    exit $?
fi

HOST="${1:?usage: $0 user@host [ssh-key]}"
KEY="${2:-}"
SSH_OPTS=(-o BatchMode=yes -o StrictHostKeyChecking=accept-new -o ServerAliveInterval=30)
[ -n "$KEY" ] && SSH_OPTS+=(-i "$KEY")

# nohup + setsid on the remote side so a dropped SSH connection cannot kill a
# half-finished apt transaction. Learned the hard way.
echo "[provision] provisioning $HOST (detached; safe against SSH drops)"
remote_body | sed "s/__FOAM_VER__/${FOAM_VER}/" \
  | ssh "${SSH_OPTS[@]}" "$HOST" \
      "cat > /tmp/provision.sh"
# See provision-docker.sh: writing and launching must be separate SSH calls, or
# cat gets backgrounded and reads from /dev/null.
ssh "${SSH_OPTS[@]}" "$HOST" \
  'setsid nohup bash /tmp/provision.sh > /tmp/provision.log 2>&1 < /dev/null & echo started'

echo "[provision] following /tmp/provision.log ..."
while true; do
    out=$(ssh "${SSH_OPTS[@]}" "$HOST" 'tail -3 /tmp/provision.log 2>/dev/null; pgrep -f /tmp/provision.sh >/dev/null && echo __RUNNING__' 2>/dev/null || true)
    echo "$out" | grep -v __RUNNING__ | sed 's/^/  /'
    echo "$out" | grep -q __RUNNING__ || break
    sleep 20
done
ssh "${SSH_OPTS[@]}" "$HOST" 'grep -qE "\[provision\] done" /tmp/provision.log' \
  && echo "[provision] SUCCESS" \
  || { echo "[provision] FAILED - see /tmp/provision.log on $HOST" >&2; exit 1; }
