#!/bin/bash
# AIPass statusline — pretty, context-aware
input=$(cat)

dir=$(echo "$input" | jq -r '.workspace.current_dir // ""')
model=$(echo "$input" | jq -r '.model.display_name // "?"')
ctx=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
lines_add=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
lines_rm=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
session=$(echo "$input" | jq -r '.session_name // empty')

RST='\033[0m'
DIM='\033[2m'
BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'
MAGENTA='\033[35m'
WHITE='\033[97m'

# A citizen is wherever a passport is (src/aipass/* and projects/*), not a path shape;
# path patterns are only the fallback for non-citizens.
branch=""
probe="$dir"
while [ -n "$probe" ] && [ "$probe" != "/" ] && [ "$probe" != "$HOME" ]; do
    if [ -f "$probe/.trinity/passport.json" ]; then
        branch=$(basename "$probe")
        break
    fi
    probe=$(dirname "$probe")
done
if [ -z "$branch" ]; then
    if [[ "$dir" == *"/src/aipass/"* ]]; then
        branch=$(echo "$dir" | sed 's|.*/src/aipass/||' | cut -d/ -f1)
    elif [[ "$dir" == *"/src/commons"* ]]; then
        branch="commons"
    elif [[ "$dir" == *"/src/skills"* ]]; then
        branch="skills"
    elif [[ "$dir" == *"/AIPass"* ]]; then
        branch="root"
    fi
fi

ctx_color="$GREEN"
if [ -n "$ctx" ]; then
    if [ "$ctx" -lt 20 ] 2>/dev/null; then
        ctx_color="$RED"
    elif [ "$ctx" -lt 50 ] 2>/dev/null; then
        ctx_color="$YELLOW"
    fi
fi

bar=""
if [ -n "$ctx" ]; then
    used=$((100 - ctx))
    filled=$((used / 10))
    empty=$((10 - filled))
    bar="${DIM}["
    for ((i=0; i<filled; i++)); do bar+="█"; done
    for ((i=0; i<empty; i++)); do bar+="░"; done
    bar+="]${RST}"
fi

short_model=$(echo "$model" | sed 's/Claude //')

git_branch=$(git -C "$dir" branch --show-current 2>/dev/null)

out=""

if [ -n "$branch" ]; then
    out+="${CYAN}@${branch}${RST}"
else
    short_dir=$(echo "$dir" | sed "s|$HOME|~|" | awk -F/ '{if(NF>=2) print $(NF-1)"/"$NF; else print $NF}')
    out+="${DIM}${short_dir}${RST}"
fi

if [ -n "$git_branch" ]; then
    out+=" ${DIM}(${RST}${YELLOW}${git_branch}${RST}${DIM})${RST}"
fi

# Watchdog sits first after the branch: narrow terminals truncate the tail of this line.
# The wire owns the heartbeat (touched every ~5s; stale past 15s means the wire is stuck).
# Green only when a live wire is registered for THIS session AND the heartbeat is fresh;
# armed but not ticking is red. Both wrappers count: "monitor" and the one-shot "background".
# No wire is the resting state: dim idle, not red, or red stops being read.
# Blind spot: work that is out with no wire armed also reads idle.
WD_HB="/tmp/aipass-watchdog-active"
WD_REG="$HOME/Projects/AIPass/src/aipass/devpulse/.watchdog/watchdog_active.json"
wd_session=$(echo "$input" | jq -r '.session_id // empty')
wd_beat=0
if [ -f "$WD_HB" ]; then
    wd_hb_ts=$(stat -c %Y "$WD_HB" 2>/dev/null || stat -f %m "$WD_HB" 2>/dev/null)
    wd_now=$(date +%s)
    if [ -n "$wd_hb_ts" ] && [ $((wd_now - wd_hb_ts)) -le 15 ] 2>/dev/null; then
        wd_beat=1
    fi
fi
wd_wire=0
if [ -f "$WD_REG" ] && [ -n "$wd_session" ]; then
    wd_wire_pid=$(jq -r --arg s "$wd_session" \
        '[.watches[]? | select(.type=="baseline_wire" and (.metadata.session // "")==$s and ((.metadata.wrapper // "")=="monitor" or (.metadata.wrapper // "")=="background")) | .pid] | first // empty' \
        "$WD_REG" 2>/dev/null)
    if [ -n "$wd_wire_pid" ] && [ -d "/proc/$wd_wire_pid" ]; then
        wd_wire=1
    fi
fi
if [ "$wd_wire" = 1 ] && [ "$wd_beat" = 1 ]; then
    out+=" ${DIM}│${RST} ${GREEN}watchdog:in${RST}"
elif [ "$wd_wire" = 1 ]; then
    # Registered and alive but not ticking: looks signed-in everywhere else.
    out+=" ${DIM}│${RST} ${RED}watchdog:HUNG${RST}"
elif [ "$wd_beat" = 1 ]; then
    # Another session is signed in — sign in here to take over.
    out+=" ${DIM}│${RST} ${RED}watchdog:ELSEWHERE${RST}"
else
    out+=" ${DIM}│${RST} ${DIM}watchdog:idle${RST}"
fi

out+=" ${DIM}│${RST} "

out+="${MAGENTA}${short_model}${RST}"

out+=" ${DIM}│${RST} "

if [ -n "$ctx" ]; then
    out+="${ctx_color}${ctx}%${RST} ${bar}"
else
    out+="${DIM}...${RST}"
fi

if [ -n "$cost" ] && [ "$cost" != "0" ]; then
    cost_fmt=$(printf "%.2f" "$cost" 2>/dev/null || echo "$cost")
    out+=" ${DIM}│${RST} ${DIM}\$${cost_fmt}${RST}"
fi

if [ "$lines_add" -gt 0 ] 2>/dev/null || [ "$lines_rm" -gt 0 ] 2>/dev/null; then
    out+=" ${DIM}│${RST} ${GREEN}+${lines_add}${RST}${DIM}/${RST}${RED}-${lines_rm}${RST}"
fi

if [ -n "$session" ]; then
    out=" ${DIM}[${RST}${WHITE}${session}${RST}${DIM}]${RST} ${out}"
fi

HOOK_FILE="/tmp/aipass-hook-last"
if [ -f "$HOOK_FILE" ]; then
    hook_data=$(cat "$HOOK_FILE" 2>/dev/null)
    hook_ts=$(echo "$hook_data" | cut -d' ' -f1)
    hook_name=$(echo "$hook_data" | cut -d' ' -f2-)
    now=$(date +%s)
    if [ -n "$hook_ts" ] && [ $((now - hook_ts)) -le 3 ] 2>/dev/null; then
        out+=" ${DIM}│${RST} ${DIM}hook:${RST}${YELLOW}${hook_name}${RST}"
    fi
fi

printf '%b' "$out"
