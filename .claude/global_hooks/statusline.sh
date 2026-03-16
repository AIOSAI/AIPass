#!/bin/bash
# AIPass statusline — pretty, context-aware
input=$(cat)

# Extract fields
dir=$(echo "$input" | jq -r '.workspace.current_dir // ""')
model=$(echo "$input" | jq -r '.model.display_name // "?"')
ctx=$(echo "$input" | jq -r '.context_window.remaining_percentage // empty')
cost=$(echo "$input" | jq -r '.cost.total_cost_usd // empty')
lines_add=$(echo "$input" | jq -r '.cost.total_lines_added // 0')
lines_rm=$(echo "$input" | jq -r '.cost.total_lines_removed // 0')
session=$(echo "$input" | jq -r '.session_name // empty')

# Colors
RST='\033[0m'
DIM='\033[2m'
BOLD='\033[1m'
GREEN='\033[32m'
YELLOW='\033[33m'
RED='\033[31m'
CYAN='\033[36m'
MAGENTA='\033[35m'
WHITE='\033[97m'

# Shorten directory — extract branch name if inside AIPass
branch=""
if [[ "$dir" == *"/src/aipass/"* ]]; then
    branch=$(echo "$dir" | sed 's|.*/src/aipass/||' | cut -d/ -f1)
elif [[ "$dir" == *"/src/commons"* ]]; then
    branch="commons"
elif [[ "$dir" == *"/src/skills"* ]]; then
    branch="skills"
elif [[ "$dir" == *"/AIPass"* ]]; then
    branch="root"
fi

# Context color — green > 50%, yellow 20-50%, red < 20%
ctx_color="$GREEN"
if [ -n "$ctx" ]; then
    if [ "$ctx" -lt 20 ] 2>/dev/null; then
        ctx_color="$RED"
    elif [ "$ctx" -lt 50 ] 2>/dev/null; then
        ctx_color="$YELLOW"
    fi
fi

# Build context bar (10 chars wide)
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

# Shorten model name
short_model=$(echo "$model" | sed 's/Claude //')

# Git branch
git_branch=$(git -C "$dir" branch --show-current 2>/dev/null)

# Build output
out=""

# Branch or directory
if [ -n "$branch" ]; then
    out+="${CYAN}@${branch}${RST}"
else
    short_dir=$(echo "$dir" | sed "s|$HOME|~|" | awk -F/ '{if(NF>=2) print $(NF-1)"/"$NF; else print $NF}')
    out+="${DIM}${short_dir}${RST}"
fi

# Git branch
if [ -n "$git_branch" ]; then
    out+=" ${DIM}(${RST}${YELLOW}${git_branch}${RST}${DIM})${RST}"
fi

# Separator
out+=" ${DIM}│${RST} "

# Model
out+="${MAGENTA}${short_model}${RST}"

# Separator
out+=" ${DIM}│${RST} "

# Context
if [ -n "$ctx" ]; then
    out+="${ctx_color}${ctx}%${RST} ${bar}"
else
    out+="${DIM}...${RST}"
fi

# Cost (if any)
if [ -n "$cost" ] && [ "$cost" != "0" ]; then
    cost_fmt=$(printf "%.2f" "$cost" 2>/dev/null || echo "$cost")
    out+=" ${DIM}│${RST} ${DIM}\$${cost_fmt}${RST}"
fi

# Lines changed
if [ "$lines_add" -gt 0 ] 2>/dev/null || [ "$lines_rm" -gt 0 ] 2>/dev/null; then
    out+=" ${DIM}│${RST} ${GREEN}+${lines_add}${RST}${DIM}/${RST}${RED}-${lines_rm}${RST}"
fi

# Session name if set
if [ -n "$session" ]; then
    out=" ${DIM}[${RST}${WHITE}${session}${RST}${DIM}]${RST} ${out}"
fi

# Hook activity — show last hook if fired within 3 seconds
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
