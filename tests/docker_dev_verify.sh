#!/usr/bin/env bash
#
# Dev-Docker verify — SOP artifact for PPLAN dev-docker runs.
# Runs INSIDE the container (aipass-test image): real GitHub clone of the
# dev branch, one-command install, then asserts provider hook wiring and
# live-fires the SessionStart cadence reset + misroute guidance.
#
# Host invocation:
#   docker run --rm -v "$AIPASS_HOME/tests/docker_dev_verify.sh":/verify.sh:ro \
#     aipass-test:latest bash /verify.sh
#
# Supersedes docker_clone_test.sh (pre-bridge architecture, stale).
#
set -uo pipefail

PASS=0
FAIL=0
ok()  { echo "  OK   $1"; PASS=$((PASS+1)); }
bad() { echo "  FAIL $1"; FAIL=$((FAIL+1)); }

echo "========================================="
echo "  AIPass Dev-Docker Verify (bridge era)"
echo "========================================="

# --- Phase 1: real clone of dev ---
echo "--- Phase 1: clone dev from GitHub ---"
rm -rf "$HOME/workspace" && mkdir -p "$HOME/workspace" && cd "$HOME/workspace"
if git clone -b dev --depth 1 https://github.com/AIOSAI/AIPass.git 2>&1 | tail -2; then
    ok "clone dev"
else
    bad "clone dev"
    echo "Cannot continue without a clone."
    exit 1
fi
cd AIPass
echo "  HEAD: $(git log -1 --oneline)"

# --- Phase 2: one-command install ---
echo "--- Phase 2: ./aipass install ---"
if ./aipass install 2>&1 | tail -15; then
    ok "installer exit 0"
else
    bad "installer exited non-zero"
fi

SETTINGS="$HOME/.claude/settings.json"
AH="$HOME/workspace/AIPass"
VPY="$AH/.venv/bin/python3"
BRIDGE="$AH/src/aipass/hooks/apps/handlers/bridges/claude.py"

# --- Phase 3: provider settings assertions ---
echo "--- Phase 3: provider settings ---"
if [ -f "$SETTINGS" ]; then ok "settings.json exists"; else bad "settings.json missing"; fi

if jq -e '.hooks.SessionStart' "$SETTINGS" > /dev/null 2>&1; then
    ok "SessionStart event wired"
else
    bad "SessionStart event missing"
fi

SS_CMD=$(jq -r '.hooks.SessionStart[0].hooks[0].command // ""' "$SETTINGS" 2>/dev/null)
case "$SS_CMD" in
    *"bridges/claude.py SessionStart:cadence_reset"*) ok "SessionStart command = bridge cadence_reset" ;;
    *) bad "SessionStart command wrong: $SS_CMD" ;;
esac

SS_TO=$(jq -r '.hooks.SessionStart[0].hooks[0].timeout // 0' "$SETTINGS" 2>/dev/null)
if [ "$SS_TO" = "30" ]; then ok "SessionStart timeout 30"; else bad "SessionStart timeout: $SS_TO"; fi

if jq -e '.env.AIPASS_HOME' "$SETTINGS" > /dev/null 2>&1; then
    ok "AIPASS_HOME in settings env"
else
    bad "AIPASS_HOME missing from settings env"
fi

UPS=$(jq -r '.hooks.UserPromptSubmit | length' "$SETTINGS" 2>/dev/null || echo 0)
if [ "$UPS" -ge 6 ]; then ok "UserPromptSubmit: $UPS entries"; else bad "UserPromptSubmit: $UPS entries (want >=6)"; fi

PC=$(jq -r '.hooks.PreCompact | length' "$SETTINGS" 2>/dev/null || echo 0)
if [ "$PC" -eq 8 ]; then ok "PreCompact: 8 entries"; else bad "PreCompact: $PC entries (want 8)"; fi

# --- Phase 4: project hook config ---
echo "--- Phase 4: project hook config ---"
if jq -e '.SessionStart.cadence_reset.enabled == true' "$AH/.aipass/hooks.json" > /dev/null 2>&1; then
    ok ".aipass/hooks.json SessionStart.cadence_reset enabled"
else
    bad ".aipass/hooks.json SessionStart.cadence_reset missing/disabled"
fi
if jq -e '.SessionStart.cadence_reset.enabled == true' "$AH/.aipass/project_hooks.json" > /dev/null 2>&1; then
    ok "project_hooks.json template has SessionStart"
else
    bad "project_hooks.json template missing SessionStart"
fi

# --- Phase 5: live-fire cadence reset ---
echo "--- Phase 5: live-fire SessionStart ---"
export AIPASS_HOME="$AH"
TMPD=$("$VPY" -c "import tempfile; print(tempfile.gettempdir())")

echo '{"source":"startup","session_id":"dockerstartup"}' | "$VPY" "$BRIDGE" SessionStart:cadence_reset
TURN=$(jq -r '.turn // "none"' "$TMPD/aipass-cadence-dockerstartup.json" 2>/dev/null || echo "none")
if [ "$TURN" = "-1" ]; then ok "startup reset -> turn -1"; else bad "startup reset: turn=$TURN"; fi

echo '{"source":"resume","session_id":"dockerresume"}' | "$VPY" "$BRIDGE" SessionStart:cadence_reset
if [ ! -f "$TMPD/aipass-cadence-dockerresume.json" ]; then
    ok "resume skipped (no state written)"
else
    bad "resume wrote state (should skip)"
fi

PERIODS=$("$VPY" -c "
from aipass.hooks.apps.modules.cadence import _load_config
c = _load_config()
t = c['loaders']['tier0'].get('period', c['period'])
n = c['loaders']['navmap'].get('period', c['period'])
print(t, n)" 2>/dev/null)
if [ "$PERIODS" = "5 5" ]; then ok "cadence periods tier0=5 navmap=5"; else bad "cadence periods: $PERIODS (want '5 5')"; fi

# --- Phase 6: misroute guidance (guide, never crash) ---
echo "--- Phase 6: misroute guidance ---"
DRONE="$AH/.venv/bin/drone"
AIPASS_BIN="$AH/.venv/bin/aipass"

OUT=$("$DRONE" aipass 2>&1 || true)
if echo "$OUT" | grep -qi "traceback"; then bad "'drone aipass' crashed"; else ok "'drone aipass' no crash"; fi
if echo "$OUT" | grep -qi "aipass"; then ok "'drone aipass' mentions aipass guidance"; else bad "'drone aipass' output unhelpful"; fi

OUT=$("$DRONE" @aipass 2>&1 || true)
if echo "$OUT" | grep -qi "traceback"; then bad "'drone @aipass' crashed"; else ok "'drone @aipass' no crash"; fi

OUT=$("$AIPASS_BIN" @drone 2>&1 || true)
if echo "$OUT" | grep -qi "traceback"; then bad "'aipass @drone' crashed"; else ok "'aipass @drone' no crash"; fi
if echo "$OUT" | grep -qi "drone"; then ok "'aipass @drone' mentions drone guidance"; else bad "'aipass @drone' output unhelpful"; fi

# --- Summary ---
echo "========================================="
echo "  Results: $PASS passed, $FAIL failed"
echo "========================================="
[ "$FAIL" -eq 0 ]
