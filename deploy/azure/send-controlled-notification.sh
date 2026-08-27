#!/usr/bin/env bash
set -euo pipefail

credentials=/etc/duesoon/owner-credentials.env
[[ -r $credentials ]] || { echo "Credentials file is unavailable" >&2; exit 1; }

set -a
source "$credentials"
set +a

idempotency_key=${1:-"controlled-$(date -u +%Y%m%dT%H%M%SZ)"}

curl -fsS \
  -X POST \
  -H "X-API-Token: $DUESOON_API_TOKEN" \
  -H "Idempotency-Key: $idempotency_key" \
  -H "Content-Type: application/json" \
  --data '{"title":"DueSoon is live","message":"Your Azure prototype is online and ready.","priority":4}' \
  "$DUESOON_URL/api/v1/notifications/test"
printf '\n'
