#!/usr/bin/env bash
# Fails if anything that should stay local has been committed.
# Run locally with: bash scripts/check_secrets.sh
set -uo pipefail

status=0

# 1. Files that must never be tracked, regardless of content.
forbidden_paths=(
  '.env'
  '.env.local'
  '*.pem'
  '*.key'
  '*.p12'
  '*.pfx'
  'id_rsa*'
  'id_ed25519*'
  '*.keystore'
  'credentials.json'
  'service-account*.json'
)

for pattern in "${forbidden_paths[@]}"; do
  # .env.example is the documented placeholder and is safe to track.
  hits=$(git ls-files -- "$pattern" | grep -v '^\.env\.example$' || true)
  if [[ -n "$hits" ]]; then
    echo "::error::Tracked file matching '$pattern' must not be committed:"
    echo "$hits" | sed 's/^/    /'
    status=1
  fi
done

# 2. High-signal credential patterns in tracked file contents. \b anchors keep
#    prefixes like "sk-" from matching ordinary words such as "task-header".
declare -A patterns=(
  ['Discord bot token']='[MNO][A-Za-z0-9_-]{23,27}\.[A-Za-z0-9_-]{6}\.[A-Za-z0-9_-]{27,}'
  ['Discord webhook URL']='discord(app)?\.com/api/webhooks/[0-9]+/[A-Za-z0-9_-]+'
  ['Private key block']='-----BEGIN [A-Z ]*PRIVATE KEY-----'
  ['AWS access key ID']='\bAKIA[0-9A-Z]{16}'
  ['GitHub token']='\bgh[pousr]_[A-Za-z0-9]{36}'
  ['Slack token']='\bxox[baprs]-[A-Za-z0-9-]{10,}'
  ['OpenAI/Anthropic key']='\bsk-(ant-)?[A-Za-z0-9_-]{20,}'
)

# Only scan files git actually tracks; -I skips binaries.
mapfile -t tracked < <(git ls-files)
if [[ ${#tracked[@]} -eq 0 ]]; then
  echo "No tracked files to scan."
  exit 0
fi

for label in "${!patterns[@]}"; do
  hits=$(grep -InIE --exclude='check_secrets.sh' "${patterns[$label]}" -- "${tracked[@]}" 2>/dev/null || true)
  if [[ -n "$hits" ]]; then
    echo "::error::Possible $label found in tracked files:"
    echo "$hits" | cut -c1-120 | sed 's/^/    /'
    status=1
  fi
done

if [[ $status -eq 0 ]]; then
  echo "No secret files or credential patterns found in tracked content."
fi

exit $status
