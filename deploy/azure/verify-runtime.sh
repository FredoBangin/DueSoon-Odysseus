#!/usr/bin/env bash
set -euo pipefail

credentials=/etc/duesoon/owner-credentials.env
[[ -r $credentials ]] || { echo "Credentials file is unavailable" >&2; exit 1; }

set -a
source "$credentials"
set +a

response_file=$(mktemp)
login_response=$(mktemp)
login_payload=$(mktemp)
cookie_jar=$(mktemp)
trap 'rm -f "$response_file" "$login_response" "$login_payload" "$cookie_jar"' EXIT

api_status=$(curl -sS -o "$response_file" -w '%{http_code}' \
  -H "X-API-Token: $DUESOON_API_TOKEN" \
  "$DUESOON_URL/api/v1/courses")
ntfy_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  "$DUESOON_URL/$NTFY_TOPIC/json?poll=1")

[[ -n ${WEB_USERNAME:-} && -n ${WEB_PASSWORD:-} ]] || {
  echo "Web credentials are unavailable" >&2
  exit 1
}
export WEB_USERNAME WEB_PASSWORD
python3 -c 'import json, os; print(json.dumps({"username": os.environ["WEB_USERNAME"], "password": os.environ["WEB_PASSWORD"]}))' > "$login_payload"
chmod 0600 "$login_payload" "$cookie_jar"
login_status=$(curl -sS -o "$login_response" -w '%{http_code}' \
  -c "$cookie_jar" -H 'Content-Type: application/json' -H "Origin: $DUESOON_URL" \
  --data-binary "@$login_payload" "$DUESOON_URL/api/v1/auth/login")
briefing_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -b "$cookie_jar" "$DUESOON_URL/api/v1/dashboard/briefing")
documents_status=$(curl -sS -o /dev/null -w '%{http_code}' \
  -b "$cookie_jar" "$DUESOON_URL/api/v1/dashboard/documents?limit=1")

printf 'authenticated_api=%s web_login=%s briefing=%s documents=%s anonymous_ntfy=%s courses=' \
  "$api_status" "$login_status" "$briefing_status" "$documents_status" "$ntfy_status"
cat "$response_file"
printf '\n'

[[ $api_status == 200 ]]
[[ $login_status == 200 ]]
[[ $briefing_status == 200 ]]
[[ $documents_status == 200 ]]
[[ $ntfy_status == 401 || $ntfy_status == 403 ]]
