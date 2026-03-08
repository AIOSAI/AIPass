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

# --- Result ---
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "=== Setup complete ==="
    echo ""
    echo "To activate the environment, run:"
    echo ""
    echo "  source .venv/bin/activate"
    echo ""
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    exit 1
fi
