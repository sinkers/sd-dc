#!/usr/bin/env bash
#
# Run a case on a fresh EC2 Spot instance, bring the results home, terminate.
#
# Built for repeat use: every AWS object it creates is named and reused on the
# next run, and the instance is terminated on exit whatever happens - including
# Ctrl-C or a mid-run failure.
#
#   ./remote/ec2-run.sh case-hall
#   TYPE=c8g.24xlarge ITERS=2000 ./remote/ec2-run.sh case-hall
#   KEEP=1 ./remote/ec2-run.sh case-hall     # leave the instance up afterwards
#
set -euo pipefail

CASE="${1:-case-hall}"
REGION="${REGION:-us-east-2}"
TYPE="${TYPE:-c8g.48xlarge}"
DISK="${DISK:-120}"
NAME="${NAME:-cfd-spot}"
KEYNAME="${KEYNAME:-cfd-run}"
SG="${SG:-cfd-run}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KEYFILE="$HOME/.ssh/${KEYNAME}.pem"
IMAGE="${IMAGE:-opencfd/openfoam-default:2406}"
AQ=(aws --region "$REGION")

log() { printf '\n[ec2] %s\n' "$*"; }

# ---------------------------------------------------------------- prerequisites
AMI=$("${AQ[@]}" ssm get-parameters --names \
  /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
  --query 'Parameters[0].Value' --output text)
case "$TYPE" in
  c7g.*|c8g.*|m7g.*|m8g.*|r8g.*) : ;;   # Graviton, arm64 - matches the AMI
  *) echo "[ec2] $TYPE is not Graviton; this script pins an arm64 AMI" >&2; exit 2 ;;
esac

if ! "${AQ[@]}" ec2 describe-key-pairs --key-names "$KEYNAME" >/dev/null 2>&1; then
  log "creating key pair $KEYNAME"
  "${AQ[@]}" ec2 create-key-pair --key-name "$KEYNAME" \
    --query 'KeyMaterial' --output text > "$KEYFILE"
  chmod 600 "$KEYFILE"
else
  [ -f "$KEYFILE" ] || { echo "[ec2] key $KEYNAME exists in AWS but $KEYFILE is missing." >&2
                         echo "      Delete the key pair in EC2 and re-run to regenerate." >&2; exit 2; }
fi

MYIP=$(curl -fsS --max-time 20 https://checkip.amazonaws.com | tr -d '\n')
SGID=$("${AQ[@]}" ec2 describe-security-groups --filters "Name=group-name,Values=$SG" \
        --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -z "$SGID" ] || [ "$SGID" = "None" ]; then
  log "creating security group $SG"
  SGID=$("${AQ[@]}" ec2 create-security-group --group-name "$SG" \
          --description "CFD spot runs, SSH only" --query 'GroupId' --output text)
fi
# keep the SSH rule pointed at wherever we are now
"${AQ[@]}" ec2 authorize-security-group-ingress --group-id "$SGID" \
  --protocol tcp --port 22 --cidr "${MYIP}/32" >/dev/null 2>&1 || true

# --------------------------------------------------------------------- generate
# Which parameter file exists decides both the generator and where ITERS lands.
PARAMS=""
for p in au01Parameters hallParameters simulationParameters; do
  if [ -f "$HERE/$CASE/system/$p" ]; then PARAMS="$HERE/$CASE/system/$p"; break; fi
done
if [ -z "$PARAMS" ]; then echo "no parameter file in $CASE/system" 1>&2; exit 2; fi

# ITERS was documented but never implemented, so a run asking for 2000 quietly
# used whatever the file said. It edits the parameter file in place - that is a
# real change to the repo, so say so.
if [ -n "${ITERS:-}" ]; then
  log "setting iterations to $ITERS in $(basename "$PARAMS") (edits the file)"
  sed -i.bak -E "s/^([[:space:]]*iterations[[:space:]]+)[0-9]+/\1$ITERS/" "$PARAMS"
  rm -f "$PARAMS.bak"
fi

log "generating dictionaries for $CASE"
case "$(basename "$PARAMS")" in
  au01Parameters)       "$HERE/make_au01_dicts.py" "$HERE/$CASE" ;;
  hallParameters)       "$HERE/make_hall_dicts.py" "$HERE/$CASE" ;;
  simulationParameters) "$HERE/make_row_dicts.py"  "$HERE/$CASE" ;;
esac

# ----------------------------------------------------------------------- launch
log "requesting $TYPE spot in $REGION"
IID=$("${AQ[@]}" ec2 run-instances \
  --image-id "$AMI" --instance-type "$TYPE" --key-name "$KEYNAME" \
  --security-group-ids "$SGID" --count 1 \
  --instance-market-options 'MarketType=spot,SpotOptions={SpotInstanceType=one-time}' \
  --block-device-mappings "[{\"DeviceName\":\"/dev/sda1\",\"Ebs\":{\"VolumeSize\":$DISK,\"VolumeType\":\"gp3\",\"DeleteOnTermination\":true}}]" \
  --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" \
  --query 'Instances[0].InstanceId' --output text)
log "instance $IID"

cleanup() {
  local rc=$?
  if [ "${KEEP:-0}" = "1" ]; then
    log "KEEP=1, leaving $IID running - terminate with:"
    echo "    aws --region $REGION ec2 terminate-instances --instance-ids $IID"
  else
    log "terminating $IID"
    "${AQ[@]}" ec2 terminate-instances --instance-ids "$IID" \
      --query 'TerminatingInstances[0].CurrentState.Name' --output text || true
  fi
  exit $rc
}
trap cleanup EXIT INT TERM

"${AQ[@]}" ec2 wait instance-running --instance-ids "$IID"
IP=$("${AQ[@]}" ec2 describe-instances --instance-ids "$IID" \
      --query 'Reservations[0].Instances[0].PublicIpAddress' --output text)
log "public IP $IP"

SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null
     -o BatchMode=yes -o ConnectTimeout=10 -o ServerAliveInterval=30 "ubuntu@$IP")
log "waiting for SSH"
for _ in $(seq 1 60); do "${SSH[@]}" true 2>/dev/null && break; sleep 10; done
"${SSH[@]}" true || { echo "[ec2] SSH never came up" >&2; exit 1; }

# -------------------------------------------------------------------- provision
log "provisioning OpenFOAM (skipped if the AMI already has it)"
"$HERE/remote/provision-docker.sh" "ubuntu@$IP" "$KEYFILE"

# -------------------------------------------------------------------- transfer
# '[0-9]*/' also matches 0.orig, which would strip the initial
# conditions; the include must come first because rsync takes the
# first matching rule.
log "syncing $CASE up"
RSH="ssh -i $KEYFILE -o StrictHostKeyChecking=accept-new -o UserKnownHostsFile=/dev/null -o BatchMode=yes"
"${SSH[@]}" "mkdir -p ~/cfd"
rsync -az --delete -e "$RSH" \
  --exclude 'processor*' --exclude 'postProcessing' --exclude 'log.*' \
  --include '0.orig/***' --exclude '[0-9]*/' --exclude '*.png' --exclude '*.mp4' --exclude 'web' \
  "$HERE/$CASE/" "ubuntu@$IP:~/cfd/$CASE/"

# ------------------------------------------------------------------------- solve
if [ -n "${RANKS:-}" ]; then
  log "rank count forced to $RANKS"
else
  RANKS=$("${SSH[@]}" 'lscpu | awk -F: "/^Core\(s\) per socket/{c=\$2} /^Socket\(s\)/{s=\$2} END{print c*s}"' | tr -d ' \r')
fi
log "solving on $RANKS ranks"
"${SSH[@]}" "printf 'FoamFile { version 2.0; format ascii; class dictionary; object decomposeParDict; }\nnumberOfSubdomains $RANKS;\nmethod scotch;\n' > ~/cfd/$CASE/system/decomposeParDict"
# The solver is a parameter now, so its log name cannot be assumed. Assuming the
# steady one made a completed transient run look like it had never started: the
# script took the failure path and terminated the instance before fetching
# postProcessing, losing 2.5 hours of results.
SOLVER=$(awk '/^application/{gsub(/;/,"",$2); print $2}' "$HERE/$CASE/system/controlDict")
SOLVERLOG="log.${SOLVER:-buoyantSimpleFoam}"
log "solver is ${SOLVER:-unknown}, expecting $SOLVERLOG"

DOCKER="sudo docker run --rm --shm-size=32g --ulimit memlock=-1 -v /home/ubuntu/cfd:/work -e OMPI_ALLOW_RUN_AS_ROOT=1 -e OMPI_ALLOW_RUN_AS_ROOT_CONFIRM=1 $IMAGE bash -lc"

# Run detached on the box and poll, rather than holding one SSH session open for
# hours. A dropped connection used to look exactly like success: the script
# carried on, fetched the partial results, and terminated the instance with the
# solver still running. One run was truncated at 14 s of a 60 s transient that
# way and still reported "solver completed 4696 iterations".
log "starting Allrun detached on the instance"
"${SSH[@]}" "cd ~/cfd/$CASE && rm -f .rc run.out && nohup $DOCKER \"cd /work/$CASE && ./Allclean >/dev/null 2>&1; time ./Allrun; echo \\\$? > /work/$CASE/.rc\" > run.out 2>&1 < /dev/null & echo detached"

set +e
elapsed=0
while : ; do
  if "${SSH[@]}" "test -f ~/cfd/$CASE/.rc" 2>/dev/null; then break; fi
  sleep 60
  elapsed=$((elapsed + 60))
  if [ $((elapsed % 600)) -eq 0 ]; then
    prog=$("${SSH[@]}" "cd ~/cfd/$CASE && tail -200 $SOLVERLOG 2>/dev/null | grep '^Time = ' | tail -1" 2>/dev/null | tr -d '\r')
    log "still running after $((elapsed/60)) min  ${prog:-(meshing)}"
  fi
  if [ "$elapsed" -gt "${MAXWAIT:-28800}" ]; then
    log "exceeded MAXWAIT of ${MAXWAIT:-28800}s - giving up but fetching what exists"
    break
  fi
done
RC=$("${SSH[@]}" "cat ~/cfd/$CASE/.rc 2>/dev/null" | tr -d ' \r')
"${SSH[@]}" "tail -40 ~/cfd/$CASE/run.out" 2>/dev/null
set -e
log "Allrun exit code ${RC:-unknown} after $((elapsed/60)) min"

# runParallel swallows the solver's exit code and the pipe above hides it, so
# check the log for real failure signatures before believing the run worked.
# Check every log, not just the solver's: the mesh is now built by
# snappyHexMesh + topoSet + createPatch, and a failure in any of those leaves no
# solver log at all - which the old single-log grep read as success.
FAILED=$("${SSH[@]}" "grep -lE 'FOAM FATAL|signal [0-9]+|Bus error|Segmentation|error code' ~/cfd/$CASE/log.* 2>/dev/null | xargs -r -n1 basename | tr '\n' ' '" | tr -d '\r')
if [ -z "$FAILED" ] && ! "${SSH[@]}" "test -s ~/cfd/$CASE/$SOLVERLOG"; then
  FAILED="(no solver log written)"
fi
if [ -n "$FAILED" ]; then
  log "RUN FAILED in: $FAILED - fetching logs before teardown"
  rm -rf "$HERE/$CASE"/log.* 2>/dev/null || true
  rsync -az -e "$RSH" "ubuntu@$IP:~/cfd/$CASE/"log.* "$HERE/$CASE/" 2>/dev/null || true
  "${SSH[@]}" "du -sh ~/cfd/$CASE; df -h / | tail -1; ls -d ~/cfd/$CASE/processor* 2>/dev/null | wc -l" || true
  log "logs are in $CASE/ ; tail of the solver log:"
  "${SSH[@]}" "tail -20 ~/cfd/$CASE/$SOLVERLOG" || true
  exit 1
fi
ITER=$("${SSH[@]}" "grep -c '^Time = ' ~/cfd/$CASE/$SOLVERLOG 2>/dev/null" | tr -d ' \r')
log "solver completed $ITER iterations"
[ "${ITER:-0}" -gt 0 ] || { log "no iterations completed"; exit 1; }

# "It ran some iterations" is not the same as "it finished". A truncated
# transient reported 4696 iterations and looked fine, but had covered 14 s of a
# 60 s run - so the averaging window was empty and no field was ever written.
WANT=$(awk '/^endTime/{gsub(/;/,"",$2); print $2}' "$HERE/$CASE/system/controlDict")
GOT=$("${SSH[@]}" "grep '^Time = ' ~/cfd/$CASE/$SOLVERLOG 2>/dev/null | tail -1 | sed 's/^Time = //'" | tr -d ' \r')
log "reached t = ${GOT:-?} of ${WANT:-?}"
if [ -n "$WANT" ] && [ -n "$GOT" ]; then
  if awk -v g="$GOT" -v w="$WANT" 'BEGIN{exit !(g < 0.995*w)}'; then
    log "WARNING: solver stopped at $GOT, short of endTime $WANT."
    log "         Results are a partial transient. Fetching them anyway."
    SHORT=1
  fi
fi

# ------------------------------------------------------------------------ fetch
log "sampling slices"
"${SSH[@]}" "$DOCKER \"cd /work/$CASE && postProcess -func slices -latestTime > log.sample 2>&1 || true\"" || true
log "clearing stale local results before fetching"
# Old numeric time directories are from previous runs on previous MESHES. Left in
# place they accumulate, and a reader that takes the latest time value silently
# pairs one run's fields with another run's mesh - which is how a 3,216,884-cell
# field ended up loaded against a 3,216,877-cell mesh.
find "$HERE/$CASE" -maxdepth 1 -type d -regex '.*/[0-9]+\(\.[0-9]+\)?' \
  -not -name 0 -exec rm -rf {} + 2>/dev/null || true
rm -rf "$HERE/$CASE/postProcessing" "$HERE/$CASE"/log.* 2>/dev/null || true
log "syncing results home"
rsync -az -e "$RSH" --exclude 'processor*' \
  "ubuntu@$IP:~/cfd/$CASE/postProcessing" "ubuntu@$IP:~/cfd/$CASE/"log.* \
  "$HERE/$CASE/"
# '[0-9]*' matches 0.orig as well, and 'sort -n' reads it as 0, so with no real
# time directory written this picked 0.orig and fetched the initial conditions
# back over the local ones. Require a purely numeric name.
LATEST=$("${SSH[@]}" "cd ~/cfd/$CASE && ls -d [0-9]* 2>/dev/null | grep -xE '[0-9]+([.][0-9]+)?' | grep -vx 0 | sort -n | tail -1" | tr -d '\r')
if [ -n "$LATEST" ]; then
  log "fetching time directory $LATEST"
  rsync -az -e "$RSH" "ubuntu@$IP:~/cfd/$CASE/$LATEST" "$HERE/$CASE/"
  # Fields are useless without the mesh they were written on. reconstructParMesh
  # writes constant/polyMesh on the instance; the upload rsync only ever sent the
  # blockMesh version, and nothing brought the real one back - so a fetched time
  # directory could not be opened at all.
  log "fetching the reconstructed mesh"
  rsync -az -e "$RSH" "ubuntu@$IP:~/cfd/$CASE/constant/polyMesh" "$HERE/$CASE/constant/" || true
fi

if [ "${SHORT:-0}" = "1" ]; then
  log "NOTE: this run did NOT reach endTime - treat every number as provisional"
fi
case "$CASE" in
  *au01*) log "done. Next:  ./plot_au01.py $CASE" ;;
  *hall*) log "done. Next:  ./plot_hall.py $CASE" ;;
  *)      log "done. Next:  ./plot_row.py $CASE"  ;;
esac
