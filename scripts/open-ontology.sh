#!/usr/bin/env bash
# Open a hosted ontolagni wiki that is served on a box's localhost only, through an SSM port forward.
#
#   open-ontology.sh [INSTANCE_ID]        (or set ONTOLOGY_SITE_INSTANCE)
#
# Your own AWS credentials decide: the forward opens only if your identity may start an
# AWS-StartPortForwardingSession on that instance. Nothing listens publicly; the box has no inbound rules.
# Needs the AWS CLI v2 and the Session Manager plugin. Ctrl-C closes the tunnel.
# Env: ONTOLOGY_SITE_REGION (default us-east-1), ONTOLOGY_SITE_PORT (local port, default 8765),
#      ONTOLOGY_SITE_REMOTE_PORT (default 8080), ONTOLOGY_SITE_NO_BROWSER=1 to only print the URL.
set -euo pipefail

instance="${1:-${ONTOLOGY_SITE_INSTANCE:-}}"
region="${ONTOLOGY_SITE_REGION:-us-east-1}"
port="${ONTOLOGY_SITE_PORT:-8765}"
remote="${ONTOLOGY_SITE_REMOTE_PORT:-8080}"

die() { echo "open-ontology: $*" >&2; exit 1; }
command -v aws >/dev/null || die "the AWS CLI v2 is not on PATH"
command -v session-manager-plugin >/dev/null ||
  die "the Session Manager plugin is not on PATH (https://docs.aws.amazon.com/systems-manager/latest/userguide/session-manager-working-with-install-plugin.html)"
if [[ -z "$instance" ]]; then  # fall back to the tag, for identities that may describe instances
  instance=$(aws ec2 describe-instances --region "$region" --output text --query 'Reservations[].Instances[0].InstanceId' \
    --filters Name=tag:project,Values=ontology-site Name=instance-state-name,Values=running 2>/dev/null | awk '{print $1}')
  [[ -n "$instance" && "$instance" != None ]] || die "give the instance id: open-ontology.sh i-... (or ONTOLOGY_SITE_INSTANCE)"
fi
if (exec 3<>"/dev/tcp/127.0.0.1/$port") 2>/dev/null; then die "local port $port is in use; set ONTOLOGY_SITE_PORT"; fi

log=$(mktemp -t open-ontology.XXXXXX)
aws ssm start-session --region "$region" --target "$instance" --document-name AWS-StartPortForwardingSession \
  --parameters "portNumber=$remote,localPortNumber=$port" >"$log" 2>&1 &
tunnel=$!
close() { pkill -TERM -P "$tunnel" 2>/dev/null || true; kill "$tunnel" 2>/dev/null || true; wait "$tunnel" 2>/dev/null || true; rm -f "$log"; }
trap close EXIT
trap 'exit 130' INT TERM

for _ in $(seq 1 60); do
  kill -0 "$tunnel" 2>/dev/null || { cat "$log" >&2; die "the port forward did not open (no access, or the box is down)"; }
  grep -q "Waiting for connections" "$log" && break
  sleep 0.5
done
grep -q "Waiting for connections" "$log" || { cat "$log" >&2; die "timed out waiting for the port forward"; }

url="http://localhost:$port/"
echo "ontology: $url   (Ctrl-C to close)"
if [[ -z "${ONTOLOGY_SITE_NO_BROWSER:-}" ]]; then
  if command -v open >/dev/null; then open "$url"; elif command -v xdg-open >/dev/null; then xdg-open "$url" >/dev/null 2>&1 || true; fi
fi
wait "$tunnel"
