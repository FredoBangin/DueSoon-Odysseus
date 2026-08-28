#!/usr/bin/env bash
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
username=${1:-duesoon-owner}
app_root=/opt/duesoon
runtime_env=/etc/duesoon/duesoon.env
credentials=/etc/duesoon/owner-credentials.env
compose_env=/etc/duesoon/compose.env
[[ -f $runtime_env && -f $compose_env ]] || { echo "DueSoon runtime is not provisioned" >&2; exit 1; }

if [[ ${2:-} == --generate ]]; then
  password=$(openssl rand -base64 30 | tr -d '\n=/+')
else
  read -r -s -p "New DueSoon web password: " password; echo
  read -r -s -p "Confirm password: " confirmation; echo
  [[ $password == "$confirmation" ]] || { echo "Passwords do not match" >&2; exit 2; }
  unset confirmation
fi
[[ ${#password} -ge 12 ]] || { echo "Password must have at least 12 characters" >&2; exit 2; }
cd "$app_root"
password_hash=$(printf '%s' "$password" | python3 -m src.duesoon.auth.passwords hash-stdin)
public_host=$(sed -n 's/^DUESOON_PUBLIC_HOST=//p' "$compose_env" | head -n1)
[[ -n $public_host ]] || { echo "Public host is missing" >&2; exit 1; }

tmp=$(mktemp /etc/duesoon/duesoon.env.XXXXXX)
trap 'rm -f "$tmp"' EXIT
grep -Ev '^DUESOON_(WEB_ENABLED|PUBLIC_ORIGIN|OWNER_USERNAME|OWNER_PASSWORD_HASH|TIMEZONE)=' "$runtime_env" > "$tmp"
printf '%s\n' "DUESOON_WEB_ENABLED=true" "DUESOON_PUBLIC_ORIGIN=https://$public_host" \
  "DUESOON_OWNER_USERNAME=$username" "DUESOON_OWNER_PASSWORD_HASH=$password_hash" \
  "DUESOON_TIMEZONE=America/New_York" >> "$tmp"
chmod 0600 "$tmp"
mv "$tmp" "$runtime_env"
trap - EXIT
grep -Ev '^WEB_(USERNAME|PASSWORD)=' "$credentials" > "${credentials}.tmp"
printf '%s\n' "WEB_USERNAME=$username" "WEB_PASSWORD=$password" >> "${credentials}.tmp"
chmod 0600 "${credentials}.tmp"
mv "${credentials}.tmp" "$credentials"
unset password password_hash
echo "DueSoon web login configured; credentials remain in $credentials"
