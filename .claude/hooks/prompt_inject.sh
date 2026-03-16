#!/usr/bin/env bash
# AIPass Prompt Inject — Called by the global project_bridge.sh
# Runs all AIPass-specific UserPromptSubmit hooks.
# $1 = repo root path (passed by bridge)

REPO="${1:-$(git rev-parse --show-toplevel 2>/dev/null)}"
[ -z "$REPO" ] && exit 0

# 1. Global prompt
cat "$REPO/.aipass/aipass_global_prompt.md" 2>/dev/null

# 2. Branch prompt loader
python3 "$REPO/.claude/hooks/branch_prompt_loader.py" 2>/dev/null

# 3. Identity injector
python3 "$REPO/.claude/hooks/identity_injector.py" 2>/dev/null

# 4. Email notification
python3 "$REPO/.claude/hooks/email_notification.py" 2>/dev/null
