#!/usr/bin/env bash
# Bring up the AU01 twin on a t4g.small in ap-southeast-2, with TLS on a real name.
#
# Idempotent: re-running adopts the existing security group, address and instance
# rather than creating duplicates. Follows the conventions of the CFD stream's
# remote/ec2-run.sh — bash + aws CLI, env-var overrides, arm64 throughout.
#
#   ./deploy/up.sh                      # create everything, print the URL
#   DOMAIN=twin.example.com ./deploy/up.sh
#
# Costs money from the moment the instance starts: a t4g.small is roughly
# US$0.017/hour on demand (~$12/month) plus a couple of dollars of EBS. down.sh
# removes all of it.
set -euo pipefail

REGION="${REGION:-ap-southeast-2}"
TYPE="${TYPE:-t4g.small}"
NAME="${NAME:-au01-twin}"
DOMAIN="${DOMAIN:-au01-twin.dametech.net}"
ZONE_NAME="${ZONE_NAME:-${DOMAIN#*.}}"     # dametech.net
KEYNAME="${KEYNAME:-asinclair-dev}"
VOLUME_GB="${VOLUME_GB:-12}"
# Only these may reach the box. 0.0.0.0/0 on 80/443 is required: the service is
# public by decision, and Let's Encrypt must reach port 80 to issue.
SSH_CIDR="${SSH_CIDR:-0.0.0.0/0}"

AQ=(aws --region "$REGION")
log() { printf '[up] %s\n' "$*"; }
die() { printf '[up] ERROR: %s\n' "$*" >&2; exit 1; }

case "$TYPE" in
  t4g.*|c7g.*|c8g.*|m7g.*|m8g.*|r8g.*) : ;;
  *) die "$TYPE is not Graviton; this script pins an arm64 AMI" ;;
esac

# ---------------------------------------------------------------- prerequisites
"${AQ[@]}" sts get-caller-identity >/dev/null || die "no usable AWS credentials"
"${AQ[@]}" ec2 describe-key-pairs --key-names "$KEYNAME" >/dev/null 2>&1 \
  || die "key pair '$KEYNAME' not found in $REGION (set KEYNAME=)"
KEYFILE="${KEYFILE:-$HOME/.ssh/$KEYNAME.pem}"
[ -f "$KEYFILE" ] || die "private key $KEYFILE not found (set KEYFILE=)"

ZONE_ID=$("${AQ[@]}" route53 list-hosted-zones-by-name \
  --dns-name "$ZONE_NAME" --query "HostedZones[?Name=='${ZONE_NAME}.'].Id | [0]" \
  --output text 2>/dev/null | sed 's|/hostedzone/||')
[ -n "$ZONE_ID" ] && [ "$ZONE_ID" != "None" ] || die "no Route53 hosted zone for $ZONE_NAME"
log "hosted zone $ZONE_NAME -> $ZONE_ID"

VPC=$("${AQ[@]}" ec2 describe-vpcs --filters Name=isDefault,Values=true \
  --query 'Vpcs[0].VpcId' --output text)
SUBNET=$("${AQ[@]}" ec2 describe-subnets --filters Name=vpc-id,Values="$VPC" \
  Name=default-for-az,Values=true --query 'Subnets[0].SubnetId' --output text)
log "vpc $VPC subnet $SUBNET"

# ------------------------------------------------------------- security group
SG=$("${AQ[@]}" ec2 describe-security-groups \
  --filters Name=group-name,Values="$NAME-sg" Name=vpc-id,Values="$VPC" \
  --query 'SecurityGroups[0].GroupId' --output text 2>/dev/null || true)
if [ -z "$SG" ] || [ "$SG" = "None" ]; then
  log "creating security group $NAME-sg"
  SG=$("${AQ[@]}" ec2 create-security-group --group-name "$NAME-sg" \
    --description "AU01 digital twin: HTTP/HTTPS public, SSH" --vpc-id "$VPC" \
    --query GroupId --output text)
  for rule in "tcp 80 0.0.0.0/0" "tcp 443 0.0.0.0/0" "tcp 22 $SSH_CIDR"; do
    read -r proto port cidr <<<"$rule"
    "${AQ[@]}" ec2 authorize-security-group-ingress --group-id "$SG" \
      --protocol "$proto" --port "$port" --cidr "$cidr" >/dev/null
  done
fi
log "security group $SG"

# ------------------------------------------------------------------- instance
IID=$("${AQ[@]}" ec2 describe-instances \
  --filters Name=tag:Name,Values="$NAME" \
  "Name=instance-state-name,Values=pending,running,stopped" \
  --query 'Reservations[0].Instances[0].InstanceId' --output text 2>/dev/null || true)

if [ -z "$IID" ] || [ "$IID" = "None" ]; then
  AMI=$("${AQ[@]}" ssm get-parameters \
    --names /aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id \
    --query 'Parameters[0].Value' --output text)
  log "launching $TYPE from $AMI"
  IID=$("${AQ[@]}" ec2 run-instances \
    --image-id "$AMI" --instance-type "$TYPE" --key-name "$KEYNAME" \
    --subnet-id "$SUBNET" --security-group-ids "$SG" \
    --block-device-mappings "DeviceName=/dev/sda1,Ebs={VolumeSize=$VOLUME_GB,VolumeType=gp3,DeleteOnTermination=true}" \
    --metadata-options "HttpTokens=required" \
    --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME},{Key=Project,Value=sd-dc-digital-twin}]" \
    --query 'Instances[0].InstanceId' --output text)
else
  log "adopting existing instance $IID"
  state=$("${AQ[@]}" ec2 describe-instances --instance-ids "$IID" \
    --query 'Reservations[0].Instances[0].State.Name' --output text)
  [ "$state" = "stopped" ] && { log "starting it"; "${AQ[@]}" ec2 start-instances --instance-ids "$IID" >/dev/null; }
fi

log "waiting for $IID to run"
"${AQ[@]}" ec2 wait instance-running --instance-ids "$IID"

# --------------------------------------------------------------- elastic IP
# A static address keeps the DNS record valid across stop/start, which matters
# because Let's Encrypt rate-limits certificate issuance per name.
ALLOC=$("${AQ[@]}" ec2 describe-addresses --filters Name=tag:Name,Values="$NAME" \
  --query 'Addresses[0].AllocationId' --output text 2>/dev/null || true)
if [ -z "$ALLOC" ] || [ "$ALLOC" = "None" ]; then
  log "allocating an elastic IP"
  ALLOC=$("${AQ[@]}" ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" \
    --query AllocationId --output text)
fi
"${AQ[@]}" ec2 associate-address --instance-id "$IID" --allocation-id "$ALLOC" >/dev/null
IP=$("${AQ[@]}" ec2 describe-addresses --allocation-ids "$ALLOC" \
  --query 'Addresses[0].PublicIp' --output text)
log "public IP $IP"

# ------------------------------------------------------------------ DNS record
log "pointing $DOMAIN at $IP"
"${AQ[@]}" route53 change-resource-record-sets --hosted-zone-id "$ZONE_ID" \
  --change-batch "$(cat <<JSON
{"Changes":[{"Action":"UPSERT","ResourceRecordSet":{
  "Name":"$DOMAIN","Type":"A","TTL":60,"ResourceRecords":[{"Value":"$IP"}]}}]}
JSON
)" >/dev/null

log "waiting for DNS to resolve to $IP (Caddy cannot get a certificate until it does)"
for _ in $(seq 1 60); do
  got=$(dig +short "$DOMAIN" @1.1.1.1 | tail -1 || true)
  [ "$got" = "$IP" ] && break
  sleep 5
done
[ "$(dig +short "$DOMAIN" @1.1.1.1 | tail -1)" = "$IP" ] \
  || log "WARNING: $DOMAIN does not resolve to $IP yet; TLS issuance may fail on first try"

# ------------------------------------------------------------------ provision
SSH=(ssh -i "$KEYFILE" -o StrictHostKeyChecking=accept-new
     -o UserKnownHostsFile=/dev/null -o LogLevel=ERROR ubuntu@"$IP")
log "waiting for SSH"
for _ in $(seq 1 60); do "${SSH[@]}" true 2>/dev/null && break; sleep 5; done
"${SSH[@]}" true || die "cannot SSH to $IP"

log "provisioning"
scp -q -i "$KEYFILE" -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  "$(dirname "$0")/provision.sh" ubuntu@"$IP":/tmp/provision.sh
"${SSH[@]}" "DOMAIN=$DOMAIN bash /tmp/provision.sh"

log "deploying the application"
DOMAIN="$DOMAIN" IP="$IP" KEYFILE="$KEYFILE" "$(dirname "$0")/deploy.sh"

cat <<DONE

[up] done
     instance   $IID  ($TYPE, $REGION)
     address    $IP
     URL        https://$DOMAIN/
     health     https://$DOMAIN/healthz
     ssh        ssh -i $KEYFILE ubuntu@$IP
     logs       ssh ... 'journalctl -u dthall -f'
     teardown   ./deploy/down.sh

     TLS is issued on first request and can take ~30 s. If the browser shows a
     certificate warning, wait and reload; check 'journalctl -u caddy' if it
     persists (usually DNS not yet propagated when Caddy first tried).
DONE
