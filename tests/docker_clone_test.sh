#!/usr/bin/env bash
#
# Docker clone test — simulates fresh user: setup.sh → verify hooks → run direct tests
# Run from inside the container with /repo bind-mounted read-only.
#
set -uo pipefail

echo "========================================="
echo "  AIPass Fresh-Clone Test"
echo "========================================="
echo ""

# --- Phase 1: Clone repo ---
# Real git clone, not cp -r: a copy drags gitignored local state (real
# .trinity/ passports, venvs) into the "fresh" tree and fakes clone results.
echo "--- Phase 1: Cloning repo ---"
rm -rf ~/workspace/AIPass
git clone --quiet /repo ~/workspace/AIPass
cd ~/workspace/AIPass

echo "  Repo cloned to ~/workspace/AIPass"
echo "  Python: $(python3 --version)"
echo "  Git: $(git --version)"
echo ""

# --- Phase 2: Run setup.sh ---
echo "--- Phase 2: Running setup.sh ---"
bash setup.sh 2>&1 | tail -30 || echo "  WARNING: setup.sh exited non-zero"
echo ""

# --- Phase 3: Inspect provider settings ---
echo "--- Phase 3: Inspecting ~/.claude/settings.json ---"
SETTINGS="$HOME/.claude/settings.json"
if [ ! -f "$SETTINGS" ]; then
    echo "  FAIL: $SETTINGS does not exist!"
    exit 1
fi

echo "  File exists: $SETTINGS"
echo "  Size: $(wc -c < "$SETTINGS") bytes"
echo ""

# Check hooks are wired
echo "  Hook events wired:"
jq -r '.hooks | keys[]' "$SETTINGS" 2>/dev/null | while read -r event; do
    count=$(jq -r ".hooks.\"$event\" | length" "$SETTINGS")
    echo "    $event: $count matcher(s)"
done
echo ""

# Check env vars
echo "  Env vars:"
jq -r '.env // {} | to_entries[] | "    \(.key) = \(.value)"' "$SETTINGS" 2>/dev/null
echo ""

# Check deny rules
deny_count=$(jq -r '.permissions.deny | length' "$SETTINGS" 2>/dev/null || echo "0")
echo "  Deny rules: $deny_count"

# Check ask rules
ask_count=$(jq -r '.permissions.ask | length' "$SETTINGS" 2>/dev/null || echo "0")
echo "  Ask rules: $ask_count"
echo ""

# --- Phase 4: Verify specific hooks exist ---
echo "--- Phase 4: Hook script verification ---"
HOOKS_DIR="$HOME/workspace/AIPass/.claude/hooks"
expected_hooks=(
    "global_prompt_loader.py"
    "branch_prompt_loader.py"
    "identity_injector.py"
    "email_notification.py"
    "tool_use_sound.py"
    "pre_edit_gate.py"
    "git_gate.py"
    "auto_fix_diagnostics.py"
    "subagent_stop_gate.py"
    "pre_compact.py"
    "stop_sound.py"
    "notification_sound.py"
    "hook_log.py"
    "hook_test.py"
    "hook_report.py"
)

pass=0
fail=0
for hook in "${expected_hooks[@]}"; do
    if [ -f "$HOOKS_DIR/$hook" ]; then
        echo "  OK  $hook"
        ((pass++))
    else
        echo "  FAIL $hook — NOT FOUND"
        ((fail++))
    fi
done
echo "  Scripts: $pass found, $fail missing"
echo ""

# --- Phase 5: Run direct hook tests ---
echo "--- Phase 5: Running hook_test.py --direct ---"
export AIPASS_HOME="$HOME/workspace/AIPass"

# Activate the venv setup.sh created so python3 finds the right env
if [ -f "$AIPASS_HOME/.venv/bin/activate" ]; then
    source "$AIPASS_HOME/.venv/bin/activate"
fi

python3 "$HOOKS_DIR/hook_test.py" --direct --verbose 2>&1 || true
echo ""

# --- Phase 6: Check settings.json matches Patrick's machine pattern ---
echo "--- Phase 6: Settings validation ---"
checks_passed=0
checks_total=0

# AIPASS_HOME in env
((checks_total++))
if jq -e '.env.AIPASS_HOME' "$SETTINGS" > /dev/null 2>&1; then
    echo "  OK  AIPASS_HOME in env"
    ((checks_passed++))
else
    echo "  FAIL AIPASS_HOME not in env"
fi

# CLAUDE_CODE_DISABLE_AUTO_MEMORY
((checks_total++))
if jq -e '.env.CLAUDE_CODE_DISABLE_AUTO_MEMORY' "$SETTINGS" > /dev/null 2>&1; then
    echo "  OK  CLAUDE_CODE_DISABLE_AUTO_MEMORY in env"
    ((checks_passed++))
else
    echo "  FAIL CLAUDE_CODE_DISABLE_AUTO_MEMORY not in env"
fi

# git deny rules present
((checks_total++))
if jq -e '.permissions.deny[] | select(contains("git reset"))' "$SETTINGS" > /dev/null 2>&1; then
    echo "  OK  git deny rules present"
    ((checks_passed++))
else
    echo "  FAIL git deny rules missing"
fi

# secrets deny rules present
((checks_total++))
if jq -e '.permissions.deny[] | select(contains(".secrets"))' "$SETTINGS" > /dev/null 2>&1; then
    echo "  OK  secrets deny rules present"
    ((checks_passed++))
else
    echo "  FAIL secrets deny rules missing"
fi

# ask rules for ~/.claude
((checks_total++))
if jq -e '.permissions.ask[] | select(contains(".claude"))' "$SETTINGS" > /dev/null 2>&1; then
    echo "  OK  ask rules for ~/.claude"
    ((checks_passed++))
else
    echo "  FAIL ask rules for ~/.claude missing"
fi

# UserPromptSubmit has 4 hooks
((checks_total++))
ups_count=$(jq -r '.hooks.UserPromptSubmit | length' "$SETTINGS" 2>/dev/null || echo "0")
if [ "$ups_count" -eq 4 ]; then
    echo "  OK  UserPromptSubmit: 4 hooks"
    ((checks_passed++))
else
    echo "  FAIL UserPromptSubmit: expected 4, got $ups_count"
fi

# PreToolUse has 3 matchers
((checks_total++))
ptu_count=$(jq -r '.hooks.PreToolUse | length' "$SETTINGS" 2>/dev/null || echo "0")
if [ "$ptu_count" -eq 3 ]; then
    echo "  OK  PreToolUse: 3 matchers"
    ((checks_passed++))
else
    echo "  FAIL PreToolUse: expected 3, got $ptu_count"
fi

# global_prompt_loader.py used (not cat)
((checks_total++))
if jq -r '.hooks.UserPromptSubmit[0].hooks[0].command' "$SETTINGS" 2>/dev/null | grep -q "global_prompt_loader.py"; then
    echo "  OK  Uses global_prompt_loader.py (not cat)"
    ((checks_passed++))
else
    echo "  FAIL Still using cat instead of global_prompt_loader.py"
fi

echo ""
echo "========================================="
echo "  Results: $checks_passed/$checks_total settings checks passed"
echo "========================================="
