#!/usr/bin/env bash
set -euo pipefail

credentials=/etc/duesoon/owner-credentials.env
[[ -r $credentials ]] || { echo "Credentials file is unavailable" >&2; exit 1; }

set -a
source "$credentials"
set +a

response_file=$(mktemp)
trap 'rm -f "$response_file"' EXIT

api_status=$(curl -sS -o "$response_file" -w '%{http_code}' \
  -H "X-API-Token: $DUESOON_API_TOKEN" \
  "$DUESOON_URL/api/v1/courses")
ntfy_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  "$DUESOON_URL/$NTFY_TOPIC/json?poll=1")

printf 'authenticated_api=%s anonymous_ntfy=%s courses=' "$api_status" "$ntfy_status"
cat "$response_file"
printf '\n'

[[ $api_status == 200 ]]
[[ $ntfy_status == 401 || $ntfy_status == 403 ]]
