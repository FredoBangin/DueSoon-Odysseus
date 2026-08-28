#!/usr/bin/env bash
set -euo pipefail
umask 077

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
runtime_env=/etc/duesoon/duesoon.env
[[ -f $runtime_env ]] || { echo "DueSoon runtime is not provisioned" >&2; exit 1; }

mode=${1:-all}
[[ $mode == model || $mode == google || $mode == all ]] || {
  echo "Usage: $0 [model|google|all]" >&2
  exit 2
}

configure_model() {
  local base_url primary fallbacks api_key tmp
  read -r -p "OpenAI-compatible base URL [https://api.openai.com/v1]: " base_url
  base_url=${base_url:-https://api.openai.com/v1}
  [[ $base_url == https://* ]] || { echo "Production model URL must use HTTPS" >&2; exit 2; }
  read -r -p "Primary model: " primary
  [[ -n $primary ]] || { echo "Primary model is required" >&2; exit 2; }
  read -r -p "Fallback models (comma separated, optional): " fallbacks
  read -r -s -p "Model API key (hidden): " api_key; echo
  [[ -n $api_key ]] || { echo "Model API key is required" >&2; exit 2; }

  tmp=$(mktemp /etc/duesoon/duesoon.env.XXXXXX)
  grep -Ev '^DUESOON_MODEL_' "$runtime_env" > "$tmp"
  printf '%s\n' \
    "DUESOON_MODEL_ENABLED=true" \
    "DUESOON_MODEL_BASE_URL=$base_url" \
    "DUESOON_MODEL_API_KEY=$api_key" \
    "DUESOON_MODEL_PRIMARY_MODEL=$primary" \
    "DUESOON_MODEL_FALLBACK_MODELS=$fallbacks" \
    "DUESOON_MODEL_TIMEOUT_SECONDS=15" \
    "DUESOON_MODEL_MAX_INPUT_TOKENS=6000" \
    "DUESOON_MODEL_MAX_OUTPUT_TOKENS=700" \
    "DUESOON_MODEL_CALL_BUDGET=2" >> "$tmp"
  chmod 0600 "$tmp"
  mv "$tmp" "$runtime_env"
  unset api_key
  echo "Model assistant configured; secret was not printed"
}

configure_google() {
  local client_id client_secret refresh_token gmail calendar tmp
  read -r -p "Google OAuth client ID: " client_id
  read -r -s -p "Google OAuth client secret (hidden): " client_secret; echo
  read -r -s -p "Google OAuth refresh token (hidden): " refresh_token; echo
  [[ -n $client_id && -n $client_secret && -n $refresh_token ]] || {
    echo "All Google OAuth values are required" >&2
    exit 2
  }
  read -r -p "Enable read-only Gmail? [Y/n]: " gmail
  read -r -p "Enable read-only Google Calendar? [Y/n]: " calendar
  gmail=${gmail:-y}; calendar=${calendar:-y}
  [[ $gmail =~ ^[Yy]$ || $calendar =~ ^[Yy]$ ]] || {
    echo "Enable at least one Google reader" >&2
    exit 2
  }

  tmp=$(mktemp /etc/duesoon/duesoon.env.XXXXXX)
  grep -Ev '^DUESOON_GOOGLE_' "$runtime_env" > "$tmp"
  printf '%s\n' \
    "DUESOON_GOOGLE_ENABLED=true" \
    "DUESOON_GOOGLE_GMAIL_ENABLED=$([[ $gmail =~ ^[Yy]$ ]] && echo true || echo false)" \
    "DUESOON_GOOGLE_CALENDAR_ENABLED=$([[ $calendar =~ ^[Yy]$ ]] && echo true || echo false)" \
    "DUESOON_GOOGLE_CLIENT_ID=$client_id" \
    "DUESOON_GOOGLE_CLIENT_SECRET=$client_secret" \
    "DUESOON_GOOGLE_REFRESH_TOKEN=$refresh_token" \
    "DUESOON_GOOGLE_TIMEOUT_SECONDS=15" >> "$tmp"
  chmod 0600 "$tmp"
  mv "$tmp" "$runtime_env"
  unset client_secret refresh_token
  echo "Google readers configured; secrets were not printed"
}

[[ $mode == model || $mode == all ]] && configure_model
[[ $mode == google || $mode == all ]] && configure_google
echo "Restart DueSoon to load the new integration settings"
