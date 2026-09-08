#!/usr/bin/env bash
# Tear down everything up.sh created. Prompts, because it is irreversible.
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
ZONE_NAME="${ZONE_NAME:-${DOMAIN#*.}}"
AQ=(aws --region "$REGION")
log() { printf '[down] %s\n' "$*"; }

IID=$("${AQ[@]}" ec2 describe-instances --filters Name=tag:Name,Values="$NAME" \
  "Name=instance-state-name,Values=pending,running,stopped,stopping" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)
ALLOC=$("${AQ[@]}" ec2 describe-addresses --filters Name=tag:Name,Values="$NAME" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || true)
IP=$("${AQ[@]}" ec2 describe-addresses --filters Name=tag:Name,Values="$NAME" \
  --query 'Addresses[0].PublicIp' --output text 2>/dev/null || true)

echo "About to delete:"
echo "  instance      ${IID:-none}"
echo "  elastic IP    ${ALLOC:-none} ${IP:-}"
echo "  DNS record    $DOMAIN"
echo "  security grp  $NAME-sg"
if [ "${FORCE:-0}" != "1" ]; then
  read -r -p "Type the instance name ($NAME) to confirm: " reply
  [ "$reply" = "$NAME" ] || { echo "aborted"; exit 1; }
fi

if [ -n "${IP:-}" ] && [ "$IP" != "None" ]; then
  ZONE_ID=$("${AQ[@]}" route53 list-hosted-zones-by-name --dns-name "$ZONE_NAME" \
    --query "HostedZones[?Name=='${ZONE_NAME}.'].Id | [0]" --output text | sed 's|/hostedzone/||')
  if [ -n "$ZONE_ID" ] && [ "$ZONE_ID" != "None" ]; then
    log "removing $DOMAIN"
    "${AQ[@]}" route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" \
      --change-batch "{\"Changes\":[{\"Action\":\"DELETE\",\"ResourceRecordSet\":{\"Name\":\"$DOMAIN\",\"Type\":\"A\",\"TTL\":60,\"ResourceRecords\":[{\"Value\":\"$IP\"}]}}]}" \
      >/dev/null 2>&1 || log "(DNS record already gone)"
  fi
fi

if [ -n "${IID:-}" ] && [ "$IID" != "None" ]; then
  log "terminating $IID"
  "${AQ[@]}" ec2 terminate-instances --instance-ids "$IID" >/dev/null
  "${AQ[@]}" ec2 wait instance-terminated --instance-ids "$IID"
fi

if [ -n "${ALLOC:-}" ] && [ "$ALLOC" != "None" ]; then
  log "releasing the elastic IP (charged while unassociated)"
  "${AQ[@]}" ec2 release-address --allocation-id "$ALLOC" >/dev/null 2>&1 || true
fi

SG=$("${AQ[@]}" ec2 describe-security-groups --filters Name=group-name,Values="$NAME-sg" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -n "$SG" ] && [ "$SG" != "None" ]; then
  log "deleting $SG"
  for _ in $(seq 1 10); do
    "${AQ[@]}" ec2 delete-security-group --group-id "$SG" 2>/dev/null && break
    sleep 6   # the ENI takes a moment to release after termination
  done
fi
log "done — nothing left billing"
