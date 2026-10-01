#!/usr/bin/env bash
#
# Tokdash → Claude Code statusline (minimal starter)
# -------------------------------------------------------------------------------
# Renders one line, e.g.:   [Claude Sonnet 4.6] 📁 myproject | 📊 12.3M ($4.56) today
#
# Requires: jq, curl. Fails silently (drops the 📊 segment) if tokdash isn't running.
# This script only ever issues GET requests, so the write-protection gate never blocks it.
#
# Install:
#   1. cp statusline-minimal.sh ~/.claude/scripts/statusline.sh
#   2. add the "statusLine" block from this folder's README.md to ~/.claude/settings.json
#
# If you changed TOKDASH_HOST / TOKDASH_PORT, point the script at your endpoint:
#   export TOKDASH_URL="http://127.0.0.1:55423"   # in your shell profile
#
set -o pipefail

TOKDASH_URL="${TOKDASH_URL:-http://127.0.0.1:55423}"
PERIOD="${TOKDASH_STATUSLINE_PERIOD:-today}"   # today | 3days | week | 14days | month | year | all

# Claude Code feeds the statusline a JSON blob on stdin.
input=$(cat)
MODEL=$(printf '%s' "$input" | jq -r '.model.display_name // "?"')
DIR=$(printf '%s' "$input" | jq -r '.workspace.current_dir // ""')

# Compact a raw token count to B / M / k.
fmt_tok() {
  local n=${1:-0}
  if   [ "$n" -ge 1000000000 ]; then awk "BEGIN{printf \"%.1fB\", $n/1000000000}"
  elif [ "$n" -ge 1000000 ];    then awk "BEGIN{printf \"%.1fM\", $n/1000000}"
  elif [ "$n" -ge 1000 ];       then echo "$(((n + 500) / 1000))k"
  else echo "$n"; fi
}

# Fetch the period totals. -m 1 keeps the bar responsive if tokdash is mid-restart.
TOKDASH_STR=""
JSON=$(curl -s -m 1 "${TOKDASH_URL}/api/usage?period=${PERIOD}" 2>/dev/null)
if [ -n "$JSON" ]; then
  TOK=$(printf '%s' "$JSON" | jq -r '.total_tokens // 0' 2>/dev/null)
  COST=$(printf '%s' "$JSON" | jq -r '.total_cost // 0' 2>/dev/null)
  if [ -n "$TOK" ] && [ "$TOK" != "0" ]; then
    TOKDASH_STR=" | 📊 $(fmt_tok "$TOK") ($(printf '$%.2f' "$COST")) ${PERIOD}"
  fi
fi

printf '[%s] 📁 %s%s\n' "$MODEL" "${DIR##*/}" "$TOKDASH_STR"
