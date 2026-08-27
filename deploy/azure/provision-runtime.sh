#!/usr/bin/env bash
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run as root" >&2
  exit 1
fi
if [[ $# -ne 2 ]]; then
  echo "Usage: provision-runtime.sh PUBLIC_HOST ACME_EMAIL" >&2
  exit 2
fi

public_host=$1
acme_email=$2
app_root=/opt/duesoon
config_root=/etc/duesoon
compose_file=$app_root/deploy/azure/docker-compose.production.yml
compose_env=$config_root/compose.env
runtime_env=$config_root/duesoon.env
credentials=$config_root/owner-credentials.env

mountpoint -q /mnt/duesoon || { echo "/mnt/duesoon is not mounted" >&2; exit 1; }
[[ -f $compose_file ]] || { echo "DueSoon repository is missing" >&2; exit 1; }
[[ ! -e $credentials ]] || { echo "Runtime is already provisioned" >&2; exit 1; }

umask 077
install -d -m 0700 "$config_root"

api_token=$(openssl rand -hex 32)
topic="duesoon-$(openssl rand -hex 12)"
owner_password=$(openssl rand -base64 30 | tr -d '\n=/+')

cat >"$compose_env" <<EOF
DUESOON_PUBLIC_HOST=$public_host
ACME_EMAIL=$acme_email
DUESOON_ENV_FILE=$runtime_env
EOF

cat >"$runtime_env" <<EOF
DUESOON_API_TOKEN=$api_token
DUESOON_DRY_RUN=false
DUESOON_SCHEDULER_ENABLED=false
DUESOON_CANVAS_ENABLED=false
DUESOON_CANVAS_BASE_URL=
DUESOON_CANVAS_ACCESS_TOKEN=
DUESOON_NTFY_ENABLED=false
DUESOON_NTFY_TOPIC=$topic
DUESOON_NTFY_TOKEN=
DUESOON_NTFY_TIMEOUT_SECONDS=10
EOF

compose=(docker compose --env-file "$compose_env" -f "$compose_file")
"${compose[@]}" up -d ntfy

container_id=$("${compose[@]}" ps -q ntfy)
for _ in $(seq 1 60); do
  health=$(docker inspect --format '{{if .State.Health}}{{.State.Health.Status}}{{end}}' "$container_id")
  [[ $health == healthy ]] && break
  sleep 2
done
[[ $health == healthy ]] || { echo "ntfy did not become healthy" >&2; exit 1; }

"${compose[@]}" exec -T -e NTFY_PASSWORD="$owner_password" ntfy \
  ntfy user add duesoon-owner >/dev/null
"${compose[@]}" exec -T ntfy ntfy access duesoon-owner "$topic" rw >/dev/null
token_output=$("${compose[@]}" exec -T ntfy \
  ntfy token add --label="DueSoon publisher" duesoon-owner)
ntfy_token=$(printf '%s' "$token_output" | grep -Eo 'tk_[[:alnum:]]+' | head -n 1)
[[ $ntfy_token == tk_* ]] || { echo "ntfy token creation failed" >&2; exit 1; }

cat >"$runtime_env" <<EOF
DUESOON_API_TOKEN=$api_token
DUESOON_DRY_RUN=false
DUESOON_SCHEDULER_ENABLED=false
DUESOON_CANVAS_ENABLED=false
DUESOON_CANVAS_BASE_URL=
DUESOON_CANVAS_ACCESS_TOKEN=
DUESOON_NTFY_ENABLED=true
DUESOON_NTFY_TOPIC=$topic
DUESOON_NTFY_TOKEN=$ntfy_token
DUESOON_NTFY_TIMEOUT_SECONDS=10
EOF

cat >"$credentials" <<EOF
DUESOON_URL=https://$public_host
DUESOON_API_TOKEN=$api_token
NTFY_USERNAME=duesoon-owner
NTFY_PASSWORD=$owner_password
NTFY_TOPIC=$topic
NTFY_TOKEN=$ntfy_token
EOF
chmod 0600 "$compose_env" "$runtime_env" "$credentials"

"${compose[@]}" up -d --build
echo "DueSoon runtime provisioned; credentials remain in $credentials"
