#!/usr/bin/env bash
# Cross-OS e2e wiring harness prototype: runs inside a clean container, repo read-only at /repo.
# Never exits on first failure, so every tier's red/green shows.
set -uo pipefail

P=0; F=0
ok(){ echo "    ok  $1"; P=$((P+1)); }
no(){ echo "    XX  $1"; F=$((F+1)); }
chk(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else no "$1"; fi; }
hdr(){ echo; echo "=== $1 ==="; }

SRC=~/src
BUILDENV=/tmp/buildenv
CLEANENV=/tmp/cleanenv
DIST=/tmp/dist
PY=$CLEANENV/bin/python
AIPASS=$CLEANENV/bin/aipass
DRONE=$CLEANENV/bin/drone

hdr "SETUP — copy repo (writable), build wheel"
rm -rf "$SRC" "$DIST" "$BUILDENV" "$CLEANENV"
cp -r /repo "$SRC" 2>/dev/null || true   # .trinity memory files are perm-restricted; harmless, code copies fine
cd "$SRC"
# A fresh clone generates the registry via setup.sh (the host's is 0600): synthesize a minimal one.
cat > "$SRC/AIPASS_REGISTRY.json" <<JSON
{ "metadata": { "name": "AIPASS", "version": "1.0.0", "total_branches": 2 },
  "branches": [
    { "name": "drone",  "path": "$SRC/src/aipass/drone" },
    { "name": "seedgo", "path": "$SRC/src/aipass/seedgo" }
  ] }
JSON
python3 -m venv "$BUILDENV"
"$BUILDENV/bin/pip" -q install --upgrade pip build 2>&1 | tail -2
echo "  building wheel..."
"$BUILDENV/bin/python" -m build --wheel --outdir "$DIST" . 2>&1 | tail -4
WHEEL=$(ls "$DIST"/*.whl 2>/dev/null | head -1)
echo "  wheel: ${WHEEL:-<NONE>}"

hdr "TIER 0 — clean-venv wheel install + binaries"
python3 -m venv "$CLEANENV"
if [ -n "${WHEEL:-}" ]; then
  "$CLEANENV/bin/pip" -q install "$WHEEL" 2>&1 | tail -3
fi
chk "wheel built"                     "[ -n '${WHEEL:-}' ]"
chk "clean venv has pip (not silent-broken venv, #495)" "[ -x '$CLEANENV/bin/pip' ]"
chk "aipass console_script installed" "[ -x '$AIPASS' ]"
chk "drone console_script installed"  "[ -x '$DRONE' ]"
chk "drone --version runs"            "'$DRONE' --version"
chk "aipass entrypoint imports (aipass init --help)" "'$AIPASS' init --help"

hdr "TIER 1 — aipass init scaffolds correctly"
PROJ=/tmp/proj; rm -rf "$PROJ"
# AIPASS_HOME unset on purpose: the core scaffold alone, without the Windows-only .venv symlink path.
"$AIPASS" init "$PROJ" demo > /tmp/init.out 2>&1
echo "  init exit=$? (see /tmp/init.out)"; tail -3 /tmp/init.out | sed 's/^/    | /'
chk "DEMO_REGISTRY.json exists"           "[ -f '$PROJ/DEMO_REGISTRY.json' ]"
chk "DEMO_REGISTRY.json is valid JSON"    "jq -e . '$PROJ/DEMO_REGISTRY.json'"
chk "registry metadata.name == DEMO"      "[ \"\$(jq -r .metadata.name '$PROJ/DEMO_REGISTRY.json')\" = DEMO ]"
chk ".claude/settings.json exists"        "[ -f '$PROJ/.claude/settings.json' ]"
chk "settings deny has EnterPlanMode"     "jq -e '.permissions.deny|index(\"EnterPlanMode\")' '$PROJ/.claude/settings.json'"
chk "src/demo/__init__.py exists"         "[ -f '$PROJ/src/demo/__init__.py' ]"
chk ".gitignore mentions .venv"           "grep -q '.venv' '$PROJ/.gitignore'"
chk ".trinity/ NOT created (projects!=citizens)" "[ ! -e '$PROJ/.trinity' ]"
chk "no passport.json created"            "[ ! -e '$PROJ/.trinity/passport.json' ]"

hdr "TIER 2a — synthetic hook fire (module form, sentinel UUID, engine.jsonl)"
HOOKP=/tmp/hookproj; rm -rf "$HOOKP"; mkdir -p "$HOOKP/.aipass"
# minimal isolated config: ONLY rm_gate enabled -> no git_gate/sound noise
cat > "$HOOKP/.aipass/hooks.json" <<'JSON'
{ "hooks_enabled": true,
  "PreToolUse": {
    "rm_gate": { "enabled": true, "handler": "aipass.hooks.apps.handlers.security.rm_gate.handle", "matcher": "Bash" }
  } }
JSON
UUID="PROTOUUID12345"
LOG=$(find "$CLEANENV" -path '*/aipass/hooks/logs/engine.jsonl' 2>/dev/null | head -1)
LOGDIR=$(dirname "$(find "$CLEANENV" -path '*/aipass/hooks' -type d 2>/dev/null | head -1)")
[ -n "$LOG" ] && : > "$LOG"   # truncate if present
OUT=$(cd "$HOOKP" && echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"rm -rf /tmp/x\"},\"agent_id\":\"$UUID\"}" \
  | AIPASS_HOME="$HOOKP" "$PY" -m aipass.hooks.apps.handlers.bridges.claude "PreToolUse:rm_gate" 2>/tmp/hook.err)
HX=$?
[ -z "$LOG" ] && LOG=$(find "$CLEANENV" -path '*/aipass/hooks/logs/engine.jsonl' 2>/dev/null | head -1)
printf '%s' "$OUT" > /tmp/hook.out   # write to file: never eval-interpolate captured JSON
echo "  hook exit=$HX  stdout=${OUT:0:80}"
[ -s /tmp/hook.err ] && echo "    stderr: $(head -1 /tmp/hook.err)"
# rm_gate blocks via {"decision":"block"} on stdout with exit 0, not exit 2.
chk "rm_gate decision==block (stdout JSON)" "jq -e '.decision==\"block\"' /tmp/hook.out"
chk "bridge exit 0 (block via JSON not code)" "[ '$HX' = 0 ]"
chk "engine.jsonl exists"                 "[ -n '$LOG' ] && [ -f '$LOG' ]"
chk "engine.jsonl logged sentinel UUID"   "[ -n '$LOG' ] && grep -q '$UUID' '$LOG'"
chk "logged record hook==rm_gate"         "[ -n '$LOG' ] && grep '$UUID' '$LOG' | grep -q rm_gate"
OUT2=$(cd "$HOOKP" && echo "{\"tool_name\":\"Bash\",\"tool_input\":{\"command\":\"echo hi\"},\"agent_id\":\"$UUID-neg\"}" \
  | AIPASS_HOME="$HOOKP" "$PY" -m aipass.hooks.apps.handlers.bridges.claude "PreToolUse:rm_gate" 2>/dev/null)
HX2=$?
chk "rm_gate allows echo (exit 0)"        "[ '$HX2' = 0 ]"

hdr "TIER 3 — drone routing (against real repo registry)"
chk "drone systems runs (reads registry)" "cd '$SRC' && '$DRONE' systems"
chk "drone systems lists a known branch"  "cd '$SRC' && '$DRONE' systems 2>/dev/null | grep -qi seedgo"
chk "drone @drone --help routes"          "cd '$SRC' && '$DRONE' @drone --help"

hdr "RESULT"
echo "  PASS=$P  FAIL=$F"
[ "$F" -eq 0 ] && echo "  ALL GREEN" || echo "  $F red — that's the truth we wanted"
exit 0
