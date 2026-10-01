#!/usr/bin/env bash
#
# Tokdash → Claude Code statusline (full / multi-row example)
# -------------------------------------------------------------------------------
# A richer, four-row statusline that combines Claude Code's own session fields with
# live tokdash totals. Renders something like:
#
#   [Claude Sonnet 4.6] | 🌿 main | effort: high
#   ████████░░ 80% [120kin+18kout/200k] | $4.56 | ⏱️ 3m 12s
#   📁 myproject | 🐍 myenv | 📊 12.3M ($4.56) today | 📊 84.1M ($61.20) week | +2staged ~1changed
#   Sat Jun 21  14:03:51 | 🔄 2h 11m [5h:34% 7d:12%] | claude 9.8M | codex 1.7M | openclaw 820k
#
# The tokdash-specific blocks are clearly marked below; delete any row you don't want.
# Requires: jq, curl. Every tokdash call fails silently if the server is unreachable,
# and all calls are GET only, so the write-protection gate never blocks the statusline.
#
# Install:
#   1. cp statusline-full.sh ~/.claude/scripts/statusline.sh
#   2. add the "statusLine" block from this folder's README.md to ~/.claude/settings.json
#
# If you changed TOKDASH_HOST / TOKDASH_PORT, export the endpoint in your shell profile:
#   export TOKDASH_URL="http://127.0.0.1:55423"
#
input=$(cat)

TOKDASH_URL="${TOKDASH_URL:-http://127.0.0.1:55423}"

# --- Claude Code session fields (from the stdin JSON) ----------------------------
MODEL=$(echo "$input" | jq -r '.model.display_name')
DIR=$(echo "$input" | jq -r '.workspace.current_dir')
COST=$(echo "$input" | jq -r '.cost.total_cost_usd // 0')
PCT=$(echo "$input" | jq -r '.context_window.used_percentage // 0' | cut -d. -f1)
API_MS=$(echo "$input" | jq -r '.cost.total_api_duration_ms // 0')
EFFORT=$(echo "$input" | jq -r '.effort.level // "normal"')
RATE5_PCT=$(echo "$input" | jq -r '.rate_limits.five_hour.used_percentage // 0' | cut -d. -f1)
RESETS_AT=$(echo "$input" | jq -r '.rate_limits.five_hour.resets_at // ""')
RATE7_PCT=$(echo "$input" | jq -r '.rate_limits.seven_day.used_percentage // 0' | cut -d. -f1)
IN_TOKENS=$(echo "$input" | jq -r '.context_window.total_input_tokens // 0')
OUT_TOKENS=$(echo "$input" | jq -r '.context_window.total_output_tokens // 0')
CTX_SIZE=$(echo "$input" | jq -r '.context_window.context_window_size // 0')

CYAN='\033[36m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; MAGENTA='\033[35m'; ORANGE='\033[38;5;208m'; RESET='\033[0m'

# Context bar color
case "$PCT" in
  ''|*[!0-9-]*) PCT=0 ;;
esac
BAR_PCT="$PCT"
if [ "$BAR_PCT" -gt 100 ]; then BAR_PCT=100; fi

if [ "$PCT" -ge 90 ]; then BAR_COLOR="$RED"
elif [ "$PCT" -ge 70 ]; then BAR_COLOR="$YELLOW"
else BAR_COLOR="$GREEN"; fi

FILLED=$((BAR_PCT / 10)); EMPTY=$((10 - FILLED))
printf -v FILL "%${FILLED}s"; printf -v PAD "%${EMPTY}s"
BAR="${FILL// /█}${PAD// /░}"

# API duration — show hours when >= 60 minutes
API_S=$((API_MS / 1000))
if [ "$API_S" -ge 3600 ]; then
  API_HRS=$((API_S / 3600)); API_MINS=$(((API_S % 3600) / 60))
  DUR_STR="${API_HRS}h ${API_MINS}m"
elif [ "$API_S" -ge 60 ]; then
  DUR_STR="$((API_S / 60))m $((API_S % 60))s"
else
  DUR_STR="${API_S}s"
fi

# 5-hour reset countdown — guard against date parse failure
RESET_STR="?"
if [ -n "$RESETS_AT" ] && [ "$RESETS_AT" != "null" ]; then
  # GNU date uses -d; macOS/BSD date uses -r.
  RESET_EPOCH=$(date -d "@$RESETS_AT" +%s 2>/dev/null || date -r "$RESETS_AT" +%s 2>/dev/null)
  if [ -n "$RESET_EPOCH" ]; then
    NOW=$(date +%s)
    REMAINING=$((RESET_EPOCH - NOW))
    if [ "$REMAINING" -le 0 ]; then
      RESET_STR="0m"
    elif [ "$REMAINING" -ge 3600 ]; then
      R_HRS=$((REMAINING / 3600)); R_MINS=$(((REMAINING % 3600) / 60))
      RESET_STR="${R_HRS}h ${R_MINS}m"
    else
      RESET_STR="$((REMAINING / 60))m $((REMAINING % 60))s"
    fi
  fi
fi

# Token counts in k
fmt_k() { local n=$1; if [ "$n" -ge 1000 ]; then echo "$(( (n + 500) / 1000 ))k"; else echo "$n"; fi; }
# Compact token count (B / M / k / raw) — used by the tokdash total and per-tool blocks
fmt_tok() {
  local n=$1
  if [ "$n" -ge 1000000000 ]; then awk "BEGIN {printf \"%.1fB\", $n/1000000000}"
  elif [ "$n" -ge 1000000 ]; then awk "BEGIN {printf \"%.1fM\", $n/1000000}"
  elif [ "$n" -ge 1000 ]; then echo "$(( (n + 500) / 1000 ))k"
  else echo "$n"; fi
}
IN_K=$(fmt_k "$IN_TOKENS")
OUT_K=$(fmt_k "$OUT_TOKENS")
CTX_K=$(fmt_k "$CTX_SIZE")

# ================================================================================
# TOKDASH BLOCK — today + week totals and a top-3 per-tool breakdown.
# Delete this whole block (and the ${ROW3_TOKDASH}/${TOOLS_STR} refs below) to drop it.
# ================================================================================
# Brand accents for tokdash's supported clients; unknown tools fall back to default.
TOOL_COLOR() {
  case "$1" in
    claude)   echo '\033[38;5;208m' ;;  # orange
    openclaw) echo '\033[31m'       ;;  # red
    codex)    echo '\033[38;5;36m'  ;;  # OpenAI green
    opencode) echo '\033[38;5;216m' ;;  # peach
    gemini)   echo '\033[38;5;75m'  ;;  # blue
    copilot)  echo '\033[38;5;141m' ;;  # purple
    kimi)     echo '\033[38;5;199m' ;;  # magenta
    pi)       echo '\033[38;5;44m'  ;;  # teal
    hermes)   echo '\033[38;5;245m' ;;  # grey
    *)        echo ''               ;;
  esac
}

TOKDASH_STR=""
WEEK_STR=""
TOOLS_STR=""
TOKDASH_JSON=$(curl -s -m 1 "${TOKDASH_URL}/api/usage?period=today" 2>/dev/null)
WEEK_JSON=$(curl -s -m 1 "${TOKDASH_URL}/api/usage?period=week" 2>/dev/null)
if [ -n "$TOKDASH_JSON" ]; then
  TODAY_TOKENS=$(echo "$TOKDASH_JSON" | jq -r '.total_tokens // 0' 2>/dev/null)
  TODAY_COST=$(echo "$TOKDASH_JSON" | jq -r '.total_cost // 0' 2>/dev/null)
  if [ -n "$TODAY_TOKENS" ] && [ "$TODAY_TOKENS" != "0" ]; then
    TOK_FMT=$(fmt_tok "$TODAY_TOKENS")
    COST_TODAY=$(printf '$%.2f' "$TODAY_COST")
    TOKDASH_STR="📊 ${TOK_FMT} (${COST_TODAY}) today"

    # Top 3 tools by tokens — one colored block each (shows fewer if <3 tools used).
    while IFS=$'\t' read -r T_NAME T_TOK; do
      [ -z "$T_NAME" ] && continue
      T_COLOR=$(TOOL_COLOR "$T_NAME")
      TOOLS_STR="${TOOLS_STR} | ${T_COLOR}${T_NAME}${RESET} $(fmt_tok "$T_TOK")"
    done < <(echo "$TOKDASH_JSON" | jq -r '.by_tool // {} | to_entries | sort_by(-.value.tokens) | .[:3][] | "\(.key)\t\(.value.tokens)"' 2>/dev/null)
  fi
fi
if [ -n "$WEEK_JSON" ]; then
  WEEK_TOKENS=$(echo "$WEEK_JSON" | jq -r '.total_tokens // 0' 2>/dev/null)
  WEEK_COST=$(echo "$WEEK_JSON" | jq -r '.total_cost // 0' 2>/dev/null)
  if [ -n "$WEEK_TOKENS" ] && [ "$WEEK_TOKENS" != "0" ]; then
    WEEK_FMT=$(fmt_tok "$WEEK_TOKENS")
    COST_WEEK=$(printf '$%.2f' "$WEEK_COST")
    WEEK_STR=" | 📊 ${WEEK_FMT} (${COST_WEEK}) week"
  fi
fi
# ============================ END TOKDASH BLOCK =================================

BRANCH=""
GIT_STATUS_STR=""
if git -c core.hooksPath=/dev/null rev-parse --git-dir > /dev/null 2>&1; then
  BRANCH=" | 🌿 $(git -c core.hooksPath=/dev/null branch --show-current 2>/dev/null)"
  # git status counts — skip locks gracefully
  STATUS_OUT=$(git -c core.hooksPath=/dev/null status --porcelain 2>/dev/null)
  if [ -n "$STATUS_OUT" ]; then
    # grep -c always prints a count (0 when no match); don't add `|| echo 0` or you get "0\n0".
    STAGED=$(echo "$STATUS_OUT" | grep -c '^[MADRC]')
    UNSTAGED=$(echo "$STATUS_OUT" | grep -c '^.[MD]')
    UNTRACKED=$(echo "$STATUS_OUT" | grep -c '^??')
    GIT_STATUS_STR=""
    [ "$STAGED" -gt 0 ]    && GIT_STATUS_STR="${GIT_STATUS_STR} ${GREEN}+${STAGED}staged${RESET}"
    [ "$UNSTAGED" -gt 0 ]  && GIT_STATUS_STR="${GIT_STATUS_STR} ${YELLOW}~${UNSTAGED}changed${RESET}"
    [ "$UNTRACKED" -gt 0 ] && GIT_STATUS_STR="${GIT_STATUS_STR} ${RED}${UNTRACKED}untracked${RESET}"
    [ -z "$GIT_STATUS_STR" ] && GIT_STATUS_STR=" ${GREEN}clean${RESET}"
  else
    GIT_STATUS_STR=" ${GREEN}clean${RESET}"
  fi
fi

COST_FMT=$(printf '$%.2f' "$COST")

# Row 3 fields
CONDA_ENV="${CONDA_DEFAULT_ENV:-}"
OUTPUT_STYLE=$(echo "$input" | jq -r '.output_style.name // ""')

ROW3_CONDA=""
[ -n "$CONDA_ENV" ] && ROW3_CONDA=" | 🐍 ${MAGENTA}${CONDA_ENV}${RESET}"
ROW3_STYLE=""
[ -n "$OUTPUT_STYLE" ] && [ "$OUTPUT_STYLE" != "default" ] && ROW3_STYLE=" | style:${OUTPUT_STYLE}"
ROW3_TOKDASH=""
[ -n "$TOKDASH_STR" ] && ROW3_TOKDASH=" | ${TOKDASH_STR}${WEEK_STR}"

# Row 4 fields
NOW_STR=$(date "+%a %b %d  %H:%M:%S")
VIM_MODE=$(echo "$input" | jq -r '.vim.mode // ""')
ROW4_VIM=""
[ -n "$VIM_MODE" ] && ROW4_VIM=" | vim:${MAGENTA}${VIM_MODE}${RESET}"

echo -e "${CYAN}[$MODEL]${RESET}$BRANCH | effort: ${MAGENTA}${EFFORT}${RESET}"
echo -e "${BAR_COLOR}${BAR}${RESET} ${PCT}% [${IN_K}in+${OUT_K}out/${CTX_K}] | ${YELLOW}${COST_FMT}${RESET} | ⏱️ ${DUR_STR}"
ROW3_GIT=""
[ -n "$GIT_STATUS_STR" ] && ROW3_GIT=" |${GIT_STATUS_STR}"
echo -e "📁 ${DIR##*/}${ROW3_CONDA}${ROW3_STYLE}${ROW3_TOKDASH}${ROW3_GIT}"
echo -e "${YELLOW}${NOW_STR}${RESET} | 🔄 ${RESET_STR} [5h:${RATE5_PCT}% 7d:${RATE7_PCT}%]${ROW4_VIM}${TOOLS_STR}"
