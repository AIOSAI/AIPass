#!/usr/bin/env bash
#
# AIPass setup script
# Creates a venv, installs the package in editable mode, and verifies CLI entry points.
#

set -euo pipefail

# cd to repo root (where this script lives) so it works from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "=== AIPass Setup ==="
echo "Repo root: $SCRIPT_DIR"
echo ""

# --- Check python3 exists ---
if ! command -v python3 &>/dev/null; then
    echo "FAIL: python3 not found. Install Python 3.10+ and try again."
    exit 1
fi

PY_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found python3 $PY_VERSION"

# --- Check minimum version ---
PY_OK=$(python3 -c 'import sys; print(int(sys.version_info >= (3, 10)))')
if [ "$PY_OK" != "1" ]; then
    echo "FAIL: Python 3.10+ required, found $PY_VERSION"
    exit 1
fi

# --- Create venv ---
if [ -d ".venv" ]; then
    echo "Existing .venv found — removing it for a clean install."
    rm -rf .venv
fi

echo "Creating virtual environment at .venv ..."
python3 -m venv .venv

# --- Activate and install ---
source .venv/bin/activate

echo "Upgrading pip ..."
pip install --upgrade pip --quiet

echo "Installing aipass in editable mode (with dev extras) ..."
pip install -e ".[dev]" --quiet

# --- Verify CLI entry points ---
FAIL=0

echo ""
echo "Verifying entry points ..."

if drone --help &>/dev/null; then
    echo "  drone  ... ok"
else
    echo "  drone  ... FAILED"
    FAIL=1
fi

if seedgo --help &>/dev/null; then
    echo "  seedgo ... ok"
else
    echo "  seedgo ... FAILED"
    FAIL=1
fi

# --- Create secrets directory ---
SECRETS_DIR="$HOME/.secrets/aipass"
if [ ! -d "$SECRETS_DIR" ]; then
    echo "Creating secrets directory at $SECRETS_DIR ..."
    mkdir -p "$SECRETS_DIR"
    chmod 700 "$HOME/.secrets"
    echo "  ~/.secrets/aipass/ ... created"
else
    echo "Secrets directory already exists — skipping"
fi

# --- Seed .env template into secrets ---
if [ ! -f "$SECRETS_DIR/.env" ] && [ -f ".env.example" ]; then
    cp .env.example "$SECRETS_DIR/.env"
    echo "  Copied .env.example → ~/.secrets/aipass/.env (add your API keys there)"
fi

# --- Generate branch registry ---
if [ ! -f "AIPASS_REGISTRY.json" ]; then
    echo "Generating AIPASS_REGISTRY.json ..."
    python3 - "$SCRIPT_DIR" << 'PYEOF'
import json, sys, os
from pathlib import Path
from datetime import date

repo_root = sys.argv[1]
src_dir = Path(repo_root) / "src" / "aipass"
today = date.today().isoformat()

branches = {}
# Discover modules under src/aipass/
for d in sorted(src_dir.iterdir()):
    if d.is_dir() and not d.name.startswith(("_", ".")):
        branches[d.name] = {
            "name": d.name,
            "path": str(d),
            "profile": "library",
            "description": "",
            "email": f"@{d.name}",
            "status": "active",
            "created": today,
            "last_active": today,
        }

# Add external branches: commons and skills
for ext_name in ["commons", "skills"]:
    ext_path = Path(repo_root) / "src" / ext_name
    if ext_path.is_dir():
        branches[ext_name] = {
            "name": ext_name,
            "path": str(ext_path),
            "profile": "library",
            "description": "",
            "email": f"@{ext_name}",
            "status": "active",
            "created": today,
            "last_active": today,
        }

registry = {
    "metadata": {
        "version": "1.0.0",
        "last_updated": today,
        "total_branches": len(branches),
    },
    "branches": branches,
}

out = Path(repo_root) / "AIPASS_REGISTRY.json"
out.write_text(json.dumps(registry, indent=2) + "\n")
print(f"  {len(branches)} branches registered")
PYEOF
else
    echo "AIPASS_REGISTRY.json already exists — skipping"
fi

# --- Bootstrap branch identity and memory files ---
echo ""
echo "Bootstrapping branch identity files ..."

DATE_TODAY=$(date +%Y-%m-%d)

bootstrap_branch() {
    local name="$1"
    local path="$2"
    local citizen_class="$3"
    local role="$4"
    local created=0

    # .trinity/passport.json
    mkdir -p "$path/.trinity"
    if [ ! -f "$path/.trinity/passport.json" ]; then
        cat > "$path/.trinity/passport.json" << JSONEOF
{
  "document_metadata": {
    "document_type": "identity",
    "document_name": "${name}.PASSPORT",
    "version": "1.0.0",
    "schema_version": "1.0.0",
    "created": "${DATE_TODAY}",
    "last_updated": "${DATE_TODAY}",
    "managed_by": "${name}"
  },
  "identity": {
    "name": "${name}",
    "citizen_class": "${citizen_class}",
    "role": "${role}",
    "status": "active"
  }
}
JSONEOF
        created=1
    fi

    # .trinity/local.json
    if [ ! -f "$path/.trinity/local.json" ]; then
        cat > "$path/.trinity/local.json" << JSONEOF
{
  "document_metadata": {
    "document_type": "session_history",
    "document_name": "${name}.LOCAL",
    "version": "1.0.0",
    "schema_version": "1.0.0",
    "created": "${DATE_TODAY}",
    "last_updated": "${DATE_TODAY}",
    "managed_by": "${name}",
    "tags": ["session_tracking", "work_log", "${name}"],
    "limits": {"max_lines": 600, "note": "Auto-rollover when max_lines exceeded"},
    "status": {"health": "healthy", "current_lines": 0, "last_health_check": "${DATE_TODAY}"}
  },
  "active_tasks": {
    "today_focus": "First session — explore codebase and capabilities",
    "recently_completed": []
  },
  "key_learnings": {},
  "sessions": []
}
JSONEOF
        created=1
    fi

    # .trinity/observations.json
    if [ ! -f "$path/.trinity/observations.json" ]; then
        cat > "$path/.trinity/observations.json" << JSONEOF
{
  "document_metadata": {
    "document_type": "collaboration_patterns",
    "document_name": "${name}.OBSERVATIONS",
    "version": "1.0.0",
    "schema_version": "1.0.0",
    "created": "${DATE_TODAY}",
    "last_updated": "${DATE_TODAY}",
    "managed_by": "${name}",
    "tags": ["collaboration", "patterns", "${name}"],
    "limits": {"max_lines": 600, "note": "Auto-rollover when max_lines exceeded"},
    "status": {"health": "healthy", "current_lines": 0, "last_health_check": "${DATE_TODAY}"}
  },
  "guidelines": {
    "purpose": "Capture collaboration patterns and experiential insights over time",
    "chronological_order": "Newest entries at TOP, oldest at BOTTOM - NEVER reorder"
  },
  "observations": [
    {
      "date": "${DATE_TODAY}",
      "session": 1,
      "entries": [
        {"title": "First Contact", "detail": "Branch initialized. Ready to begin capturing collaboration patterns."}
      ]
    }
  ]
}
JSONEOF
        created=1
    fi

    # .seedgo/bypass.json
    mkdir -p "$path/.seedgo"
    if [ ! -f "$path/.seedgo/bypass.json" ]; then
        echo '{}' > "$path/.seedgo/bypass.json"
        created=1
    fi

    # .ai_mail.local/inbox.json
    mkdir -p "$path/.ai_mail.local"
    if [ ! -f "$path/.ai_mail.local/inbox.json" ]; then
        echo '{"inbox": []}' > "$path/.ai_mail.local/inbox.json"
        created=1
    fi

    if [ "$created" -eq 1 ]; then
        echo "  @${name} ... bootstrapped"
    else
        echo "  @${name} ... exists (skipped)"
    fi
}

# Branches inside src/aipass/
bootstrap_branch "drone"    "$SCRIPT_DIR/src/aipass/drone"    "builder" "Command routing and module discovery"
bootstrap_branch "seedgo"   "$SCRIPT_DIR/src/aipass/seedgo"   "builder" "Standards enforcement and code auditing"
bootstrap_branch "prax"     "$SCRIPT_DIR/src/aipass/prax"     "builder" "Logging and monitoring system"
bootstrap_branch "cli"      "$SCRIPT_DIR/src/aipass/cli"      "builder" "Display formatting service"
bootstrap_branch "flow"     "$SCRIPT_DIR/src/aipass/flow"     "builder" "Workflow and plan management"
bootstrap_branch "ai_mail"  "$SCRIPT_DIR/src/aipass/ai_mail"  "builder" "Inter-agent messaging and dispatch"
bootstrap_branch "api"      "$SCRIPT_DIR/src/aipass/api"      "builder" "LLM access and model routing"
bootstrap_branch "trigger"  "$SCRIPT_DIR/src/aipass/trigger"  "builder" "Event-driven automation"
bootstrap_branch "spawn"    "$SCRIPT_DIR/src/aipass/spawn"    "builder" "Branch lifecycle management"
bootstrap_branch "devpulse" "$SCRIPT_DIR/src/aipass/devpulse" "manager" "Orchestration hub and coordination"
bootstrap_branch "backup"   "$SCRIPT_DIR/src/aipass/backup"   "builder" "Multi-mode backup system"
bootstrap_branch "daemon"   "$SCRIPT_DIR/src/aipass/daemon"   "builder" "Background scheduler"
bootstrap_branch "memory"   "$SCRIPT_DIR/src/aipass/memory"   "builder" "Vector memory bank"

# External branches
bootstrap_branch "commons"  "$SCRIPT_DIR/src/commons"         "builder" "Social network for branches"
bootstrap_branch "skills"   "$SCRIPT_DIR/src/skills"          "builder" "Capability framework"

echo "  15 branches bootstrapped"

# --- Install Claude Code hooks ---
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

if [ -d "$SCRIPT_DIR/.claude/hooks" ]; then
    echo "Installing Claude Code hooks ..."
    mkdir -p "$HOME/.claude"

    python3 - "$SCRIPT_DIR" "$CLAUDE_SETTINGS" << 'PYEOF'
import json
import sys
from pathlib import Path

repo_root = sys.argv[1]
settings_path = Path(sys.argv[2])
hooks_dir = f"{repo_root}/.claude/hooks"

# Load existing settings or start fresh
if settings_path.exists():
    settings = json.loads(settings_path.read_text())
else:
    settings = {}

# Build hooks config with absolute paths
settings["hooks"] = {
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": f"cat {repo_root}/.aipass/aipass_global_prompt.md 2>/dev/null || true"}]},
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/branch_prompt_loader.py"}]},
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/identity_injector.py"}]},
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/email_notification.py"}]},
    ],
    "PreToolUse": [
        {"matcher": "Bash|Edit|MultiEdit|Write|Read|Grep|Glob|WebSearch|WebFetch|Task",
         "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/tool_use_sound.py"}]},
    ],
    "PostToolUse": [
        {"matcher": "Edit|MultiEdit|Write|NotebookEdit",
         "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/auto_fix_diagnostics.py"}]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/stop_sound.py"}]},
    ],
    "Notification": [
        {"hooks": [{"type": "command", "command": f"python3 {hooks_dir}/notification_sound.py"}]},
    ],
    "PreCompact": [
        {"matcher": "manual", "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/pre_compact.py", "timeout": 60}]},
        {"matcher": "auto", "hooks": [{"type": "command", "command": f"python3 {hooks_dir}/pre_compact.py", "timeout": 60}]},
    ],
}

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"  hooks -> {settings_path}")
PYEOF
else
    echo "Skipping hooks (no .claude/hooks/ directory found)"
fi

# --- Create global symlinks for CLI tools ---
echo ""
echo "Creating global symlinks ..."

VENV_BIN="$SCRIPT_DIR/.venv/bin"
LOCAL_BIN="/usr/local/bin"

for cmd in drone seedgo; do
    if [ -f "$VENV_BIN/$cmd" ]; then
        if sudo ln -sf "$VENV_BIN/$cmd" "$LOCAL_BIN/$cmd" 2>/dev/null; then
            echo "  $LOCAL_BIN/$cmd -> $VENV_BIN/$cmd"
        else
            echo "  WARN: Could not create symlink for $cmd (try running with sudo)"
            echo "  Manual fix: sudo ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd"
        fi
    fi
done

# --- Result ---
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "=== Setup complete ==="
    echo ""
    echo "drone and seedgo are available globally via /usr/local/bin symlinks."
    echo "No venv activation needed."
    echo ""
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    exit 1
fi
