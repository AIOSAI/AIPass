#!/usr/bin/env bash
#
# AIPass setup script
# Creates a venv, installs the package in editable mode, and verifies CLI entry points.
#

set -euo pipefail

# cd to repo root (where this script lives) so it works from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- OS detection ---
# Detect Windows (Git Bash / MSYS2 / Cygwin) and macOS — used throughout the script
IS_WINDOWS=0
IS_MACOS=0
case "${OSTYPE:-}" in
    msys*|cygwin*|mingw*) IS_WINDOWS=1 ;;
    darwin*) IS_MACOS=1 ;;
    *)
        # Fallback: check uname if OSTYPE is unset
        if uname -s 2>/dev/null | grep -qi "mingw\|msys\|cygwin"; then
            IS_WINDOWS=1
        elif uname -s 2>/dev/null | grep -qi "darwin"; then
            IS_MACOS=1
        fi
        ;;
esac

echo "=== AIPass Setup ==="
echo "Repo root: $SCRIPT_DIR"
echo ""

# --- Strip broken venv from PATH (Windows: stale .venv/Scripts shadows real Python) ---
if [ "$IS_WINDOWS" -eq 1 ]; then
    export PATH=$(echo "$PATH" | tr ':' '\n' | grep -v '\.venv' | tr '\n' ':' | sed 's/:$//')
    export PYTHONUTF8=1
fi

# --- Find working Python (#292: Windows python3 → MS Store alias) ---
PYTHON=""
# Probe versioned binaries first — on macOS, Homebrew installs Python as
# python3.11 and stock python3 may still point to 3.9. Checking versioned
# names first finds a suitable interpreter without auto-install on Mac too.
for v in 3.13 3.12 3.11 3.10; do
    if command -v "python$v" &>/dev/null && "python$v" -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python$v"
        break
    fi
done
# Fall back to python3, then python (Windows installs as 'python' not 'python3')
if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null && python3 -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python3"
    elif command -v python &>/dev/null && python -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "FAIL: No working Python found. Install Python 3.10+ and try again."
    echo "  Windows: install from python.org, NOT the Microsoft Store."
    echo "  Then disable the Store alias: Settings > Apps > Advanced app settings > App execution aliases"
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found $PYTHON $PY_VERSION"

# --- Check minimum version ---
PY_OK=$($PYTHON -c 'import sys; print(int(sys.version_info >= (3, 10)))')
if [ "$PY_OK" != "1" ]; then
    if [ "$IS_MACOS" -eq 1 ]; then
        # Auto-install on Mac. Stock macOS 12 ships only python3 3.9 and has no
        # versioned binaries. Try Homebrew if it's already installed (no admin
        # needed to USE brew — only to install it), then fall back to uv, which
        # installs entirely in user-space and works on non-admin Mac accounts.
        echo "Python 3.10+ not found on this Mac. Attempting auto-install ..."

        # Path 1: existing Homebrew. Don't attempt to install brew itself —
        # that step requires admin/sudo and locks out non-admin accounts.
        if command -v brew &>/dev/null; then
            echo "Homebrew present — installing python@3.11 via brew ..."
            if brew install python@3.11; then
                if command -v python3.11 &>/dev/null; then
                    PYTHON="python3.11"
                elif [ -x /opt/homebrew/opt/python@3.11/bin/python3.11 ]; then
                    PYTHON="/opt/homebrew/opt/python@3.11/bin/python3.11"
                elif [ -x /usr/local/opt/python@3.11/bin/python3.11 ]; then
                    PYTHON="/usr/local/opt/python@3.11/bin/python3.11"
                fi
            fi
            if [ -n "$PYTHON" ] && "$PYTHON" -c 'import sys; exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
                PY_OK=1
            fi
        fi

        # Path 2: uv — no sudo, no admin, works on any account.
        # Installs a prebuilt standalone Python to ~/.local/share/uv/python.
        if [ "$PY_OK" != "1" ]; then
            echo "Using uv (no-sudo Python installer) ..."
            if ! command -v uv &>/dev/null; then
                echo "Installing uv to ~/.local/bin ..."
                curl -LsSf https://astral.sh/uv/install.sh | sh
                export PATH="$HOME/.local/bin:$PATH"
            fi
            if ! command -v uv &>/dev/null; then
                echo "FAIL: uv install did not succeed."
                echo "Install Python 3.10+ manually from https://www.python.org/downloads/ and retry."
                exit 1
            fi
            echo "Downloading Python 3.11 via uv ..."
            uv python install 3.11
            # Locate the installed python
            UV_PY=$(uv python find 3.11 2>/dev/null || true)
            if [ -z "$UV_PY" ] || [ ! -x "$UV_PY" ]; then
                UV_PY=$(ls -1 "$HOME/.local/share/uv/python/"*"/bin/python3.11" 2>/dev/null | head -1)
            fi
            if [ -n "$UV_PY" ] && [ -x "$UV_PY" ]; then
                PYTHON="$UV_PY"
                PY_OK=1
            else
                echo "FAIL: uv installed but python3.11 binary not located."
                exit 1
            fi
        fi

        PY_VERSION=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
        echo "Now using $PYTHON $PY_VERSION"
    else
        echo "FAIL: Python 3.10+ required, found $PY_VERSION"
        exit 1
    fi
fi

# --- Create venv ---
if [ "$IS_WINDOWS" -eq 1 ] && [ -f ".venv/Scripts/python.exe" ]; then
    # Windows: skip venv recreation if python.exe exists (rm -rf unreliable due to file locking)
    echo "Existing .venv found — reusing (Windows file locking prevents clean removal)"
elif [ -d ".venv" ]; then
    echo "Existing .venv found — removing it for a clean install."
    rm -rf .venv
fi

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment at .venv ..."
    if [ "$IS_WINDOWS" -eq 1 ]; then
        # Windows: create without pip, bootstrap manually to avoid subprocess path issues
        $PYTHON -m venv --without-pip .venv
    else
        $PYTHON -m venv .venv
    fi
fi

# --- Activate and install ---
# Determine venv python path for explicit invocation
if [ "$IS_WINDOWS" -eq 1 ] && [ -f ".venv/Scripts/python.exe" ]; then
    source .venv/Scripts/activate
    VENV_PYTHON=".venv/Scripts/python.exe"
    # Bootstrap pip if missing (--without-pip on Windows)
    if ! "$VENV_PYTHON" -m pip --version &>/dev/null 2>&1; then
        echo "Bootstrapping pip in venv ..."
        "$VENV_PYTHON" -m ensurepip --default-pip || true
        if ! "$VENV_PYTHON" -m pip --version &>/dev/null 2>&1; then
            echo "ensurepip did not install pip — falling back to get-pip.py"
            "$VENV_PYTHON" -c "import urllib.request; urllib.request.urlretrieve('https://bootstrap.pypa.io/get-pip.py', 'get-pip.py')"
            "$VENV_PYTHON" get-pip.py
            rm -f get-pip.py
        fi
        "$VENV_PYTHON" -m pip --version || { echo "ERROR: pip still missing after bootstrap" >&2; exit 1; }
    fi
else
    source .venv/bin/activate
    VENV_PYTHON="python3"
fi

echo "Upgrading pip ..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet

echo "Installing aipass in editable mode (with dev extras) ..."
"$VENV_PYTHON" -m pip install -e ".[dev]" --quiet

# --- Detect shadowing drone installs (Windows) ---
# Issues #317 + #321: system-Python pip or legacy npm aipass-drone can shadow venv drone.exe.
# Warn the user with precise uninstall commands; don't touch anything automatically.
if [ "$IS_WINDOWS" -eq 1 ]; then
    echo ""
    echo "Checking for shadowing drone installs ..."

    # System Python check (#317)
    for sys_py in "python" "py -3" "python3"; do
        if command -v $sys_py &>/dev/null; then
            if $sys_py -m pip show aipass &>/dev/null 2>&1; then
                # Don't match our own venv python
                SYS_PY_PATH=$($sys_py -c "import sys; print(sys.executable)" 2>/dev/null || echo "")
                if [ -n "$SYS_PY_PATH" ] && [[ "$SYS_PY_PATH" != *".venv"* ]]; then
                    echo "  WARN: aipass is installed in system Python at $SYS_PY_PATH"
                    echo "  This shadows the venv drone.exe on Windows PATH. To fix:"
                    echo "    \"$SYS_PY_PATH\" -m pip uninstall aipass -y"
                    break
                fi
            fi
        fi
    done

    # Legacy npm aipass-drone check (#321)
    NPM_BIN="$APPDATA/npm"
    if [ -d "$NPM_BIN" ] && { [ -f "$NPM_BIN/drone" ] || [ -f "$NPM_BIN/drone.cmd" ] || [ -f "$NPM_BIN/drone.ps1" ]; }; then
        echo "  WARN: Legacy npm drone scripts found in $NPM_BIN — these shadow venv drone.exe."
        echo "  To fix:"
        echo "    npm uninstall -g aipass-drone"
        echo "    rm -f \"$NPM_BIN/drone\" \"$NPM_BIN/drone.cmd\" \"$NPM_BIN/drone.ps1\""
    fi
fi

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

# seedgo is accessed via drone @seedgo, not as a standalone CLI
if drone @seedgo --help &>/dev/null; then
    echo "  seedgo ... ok (via drone @seedgo)"
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

branches = []
# Discover modules under src/aipass/
for d in sorted(src_dir.iterdir()):
    if d.is_dir() and not d.name.startswith(("_", ".")):
        branches.append({
            "name": d.name,
            "path": str(d),
            "profile": "library",
            "description": "",
            "email": f"@{d.name}",
            "status": "active",
            "created": today,
            "last_active": today,
        })

# NOTE: commons and skills were external branches, now removed from public repo.
# Registry only includes branches discovered under src/aipass/.

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
bootstrap_branch "memory"   "$SCRIPT_DIR/src/aipass/memory"   "builder" "Vector memory bank"

# External branches
# NOTE: backup, daemon removed S82/S87. commons, skills moved to external repos.
# Only the 11 core branches above should be bootstrapped.

echo "  15 branches bootstrapped"

# --- Seed branch config files from .example defaults ---
# Some branches need a config file that's gitignored (contains local state).
# Ship `*.example.json` in git; seed the real file from it on fresh install.
MEMORY_CONFIG_DIR="$SCRIPT_DIR/src/aipass/memory/config"
MEMORY_CONFIG_FILE="$MEMORY_CONFIG_DIR/memory_bank.config.json"
MEMORY_CONFIG_EXAMPLE="$MEMORY_CONFIG_DIR/memory_bank.config.example.json"
if [ -f "$MEMORY_CONFIG_EXAMPLE" ] && [ ! -f "$MEMORY_CONFIG_FILE" ]; then
    cp "$MEMORY_CONFIG_EXAMPLE" "$MEMORY_CONFIG_FILE"
    echo "  memory_bank.config.json seeded from example"
fi

# --- Install Claude Code hooks ---
CLAUDE_SETTINGS="$HOME/.claude/settings.json"

if [ -d "$SCRIPT_DIR/.claude/hooks" ]; then
    echo "Installing Claude Code hooks ..."
    mkdir -p "$HOME/.claude"

    # Determine python command for hooks.
    # Linux: keep "python3" — distros ship 3.10+ and hooks import nothing
    # version-specific beyond that. Leaving this path unchanged per Linux stability.
    # macOS: stock /usr/bin/python3 is 3.9.6 on macOS 12 and cannot parse hook
    # scripts that use PEP 604 union syntax (`X | None`). Point at the venv
    # python, which setup just built with a 3.10+ interpreter.
    # Windows: existing venv-python behavior.
    if [ "$IS_WINDOWS" -eq 1 ]; then
        HOOK_PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
    elif [ "$IS_MACOS" -eq 1 ]; then
        HOOK_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
    else
        HOOK_PYTHON="python3"
    fi

    "$PYTHON" - "$SCRIPT_DIR" "$CLAUDE_SETTINGS" "$HOOK_PYTHON" << 'PYEOF'
import json
import sys
from pathlib import Path

repo_root = sys.argv[1]
settings_path = Path(sys.argv[2])
hook_python = sys.argv[3]
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
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/branch_prompt_loader.py"}]},
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/identity_injector.py"}]},
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/email_notification.py"}]},
    ],
    "PreToolUse": [
        {"matcher": "Bash|Edit|MultiEdit|Write|Read|Grep|Glob|WebSearch|WebFetch|Task",
         "hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/tool_use_sound.py"}]},
    ],
    "PostToolUse": [
        {"matcher": "Edit|MultiEdit|Write|NotebookEdit",
         "hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/auto_fix_diagnostics.py"}]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/stop_sound.py"}]},
    ],
    "Notification": [
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/notification_sound.py"}]},
    ],
    "PreCompact": [
        {"matcher": "manual", "hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/pre_compact.py", "timeout": 60}]},
        {"matcher": "auto", "hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/pre_compact.py", "timeout": 60}]},
    ],
}

# Inject AIPASS_HOME into env block so dispatched agents find AIPass
import os
env_block = settings.get("env", {})
env_block["AIPASS_HOME"] = repo_root
# Windows: force UTF-8 for Rich output in hook processes
msys = os.environ.get("MSYSTEM", "") + os.environ.get("OSTYPE", "")
if "MSYS" in msys or "msys" in msys or "MINGW" in msys:
    env_block["PYTHONUTF8"] = "1"
settings["env"] = env_block

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"  hooks -> {settings_path}")
print(f"  AIPASS_HOME -> {repo_root} (in settings.json env)")
PYEOF
else
    echo "Skipping hooks (no .claude/hooks/ directory found)"
fi

# --- Install Codex CLI hooks ---
if command -v codex &>/dev/null; then
    if [ -f "$SCRIPT_DIR/.codex/hooks.json" ]; then
        echo "Installing Codex CLI hooks ..."
        mkdir -p "$HOME/.codex"

        python3 - "$SCRIPT_DIR" "$HOME/.codex/config.toml" << 'PYEOF'
import sys
from pathlib import Path

repo_root = sys.argv[1]
config_path = Path(sys.argv[2])

# Read existing config or start fresh
existing = {}
if config_path.exists():
    for line in config_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("[") and not line.startswith("#") and "=" in line:
            key, val = line.split("=", 1)
            existing[key.strip()] = val.strip()

# Preserve model if set
model = existing.get("model", '"o4-mini"')

config = f'''model = {model}
check_for_update_on_startup = false

[features]
codex_hooks = true

[experimental_features]
multi_agent = true
multi_agent_v2 = true

[projects."{repo_root}"]
trust_level = "trusted"
'''

config_path.write_text(config)
print(f"  config.toml -> {config_path}")
print(f"  hooks.json -> {repo_root}/.codex/hooks.json (project-level, travels with repo)")
PYEOF
    else
        echo "Skipping Codex hooks (no .codex/hooks.json found in repo)"
    fi
else
    echo "Skipping Codex CLI (not installed)"
fi

# --- Install Gemini CLI hooks ---
if command -v gemini &>/dev/null; then
    if [ -d "$SCRIPT_DIR/.gemini/hooks" ]; then
        echo "Installing Gemini CLI hooks ..."

        GEMINI_SETTINGS="$HOME/.gemini/settings.json"
        mkdir -p "$HOME/.gemini"

        # HOOK_PYTHON was set earlier in the Claude hooks block; reuse it.
        # Fall back to python3 if this block runs without that setup (defensive).
        GEMINI_HOOK_PYTHON="${HOOK_PYTHON:-python3}"

        python3 - "$SCRIPT_DIR" "$GEMINI_SETTINGS" "$GEMINI_HOOK_PYTHON" << 'PYEOF'
import json
import sys
from pathlib import Path

repo_root = sys.argv[1]
settings_path = Path(sys.argv[2])
hook_python = sys.argv[3]
hooks_dir = f"{repo_root}/.gemini/hooks"

# Load existing settings or start fresh
if settings_path.exists():
    settings = json.loads(settings_path.read_text())
else:
    settings = {}

# Build hooks config with absolute paths (Gemini uses different event names)
settings["hooks"] = {
    "SessionStart": [
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/session_start_identity.py", "timeout": 10}]}
    ],
    "BeforeModel": [
        {"hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/prompt_inject.py", "timeout": 10}]}
    ],
    "BeforeTool": [
        {"matcher": "Edit|Write",
         "hooks": [{"type": "command", "command": f"{hook_python} {hooks_dir}/pre_edit_gate.py", "timeout": 5}]}
    ],
}

settings_path.write_text(json.dumps(settings, indent=2) + "\n")
print(f"  hooks -> {settings_path}")
PYEOF
    else
        echo "Skipping Gemini hooks (no .gemini/hooks/ directory found in repo)"
    fi
else
    echo "Skipping Gemini CLI (not installed)"
fi

# --- Set AIPASS_HOME + PATH so all services work from any project ---
echo ""
echo "Configuring cross-project access ..."

if [ "$IS_WINDOWS" -eq 1 ]; then
    # Windows (Git Bash): write to ~/.bash_profile
    PROFILE="$HOME/.bash_profile"
    touch "$PROFILE"

    # AIPASS_HOME
    if ! grep -q "AIPASS_HOME" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "# AIPass — cross-project access" >> "$PROFILE"
        echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$PROFILE"
        echo "  AIPASS_HOME added to $PROFILE"
    else
        echo "  AIPASS_HOME already in $PROFILE"
    fi

    # PATH (venv Scripts for Windows)
    VENV_SCRIPTS="$SCRIPT_DIR/.venv/Scripts"
    if ! grep -q ".venv/Scripts" "$PROFILE" 2>/dev/null; then
        echo "export PATH=\"$VENV_SCRIPTS:\$PATH\"" >> "$PROFILE"
        echo "  PATH updated in $PROFILE (drone available globally)"
    else
        echo "  PATH already includes venv in $PROFILE"
    fi

    # PYTHONUTF8
    if ! grep -q "PYTHONUTF8" "$PROFILE" 2>/dev/null; then
        echo "export PYTHONUTF8=1" >> "$PROFILE"
        echo "  PYTHONUTF8=1 added to $PROFILE"
    fi

    # Export for current session too
    export AIPASS_HOME="$SCRIPT_DIR"
    export PATH="$VENV_SCRIPTS:$PATH"
    export PYTHONUTF8=1

    # PowerShell profile wrapper — makes `drone @branch cmd` work from PowerShell
    # without @ being consumed by PS splatting operator. See issue #340.
    PS_PROFILE_DIR="$HOME/Documents/WindowsPowerShell"
    PS_PROFILE="$PS_PROFILE_DIR/Microsoft.PowerShell_profile.ps1"
    mkdir -p "$PS_PROFILE_DIR"
    if [ ! -f "$PS_PROFILE" ] || ! grep -q "AIPass drone wrapper" "$PS_PROFILE" 2>/dev/null; then
        cat >> "$PS_PROFILE" <<'PSWRAP'

# AIPass drone wrapper — preserves @branch args that PowerShell would otherwise splat
function drone {
    $exe = Join-Path $env:AIPASS_HOME '.venv\Scripts\drone.exe'
    if (-not (Test-Path $exe)) { Write-Error "drone.exe not found at $exe"; return }
    $raw = $MyInvocation.Line.Trim()
    if ($raw -match '^drone\s+(.+)$') {
        $argsPart = $Matches[1]
        $argsPart = ($argsPart -split '\s*\|\s*')[0].TrimEnd()
        cmd /c "`"$exe`" $argsPart"
    } else { & $exe }
}
PSWRAP
        echo "  PowerShell drone wrapper written to $PS_PROFILE"
    else
        echo "  PowerShell drone wrapper already in $PS_PROFILE"
    fi
else
    # Linux/macOS: write to the user's shell rc.
    # macOS default shell has been zsh since Catalina (2019) — stock macOS
    # will not source ~/.bashrc, so exports there are invisible. Pick the
    # right rc based on $SHELL on Mac; leave Linux behavior as-is (~/.bashrc).
    if [ "$IS_MACOS" -eq 1 ]; then
        case "${SHELL:-}" in
            */zsh) PROFILE="$HOME/.zshrc" ;;
            */bash) PROFILE="$HOME/.bash_profile" ;;   # Mac bash login shell sources .bash_profile, not .bashrc
            *) PROFILE="$HOME/.zshrc" ;;               # zsh is the macOS default; sensible fallback
        esac
    else
        PROFILE="$HOME/.bashrc"
    fi

    # AIPASS_HOME
    if ! grep -q "AIPASS_HOME" "$PROFILE" 2>/dev/null; then
        echo "" >> "$PROFILE"
        echo "# AIPass — cross-project access" >> "$PROFILE"
        echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$PROFILE"
        echo "  AIPASS_HOME added to $PROFILE"
    else
        echo "  AIPASS_HOME already in $PROFILE"
    fi

    # Mac: ensure ~/.local/bin is on PATH so the drone symlink resolves.
    # Linux already symlinks into /usr/local/bin (already on PATH everywhere).
    if [ "$IS_MACOS" -eq 1 ]; then
        if ! grep -q '\.local/bin' "$PROFILE" 2>/dev/null; then
            echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
            echo "  ~/.local/bin added to PATH in $PROFILE"
        else
            echo "  ~/.local/bin already on PATH in $PROFILE"
        fi
        export PATH="$HOME/.local/bin:$PATH"
    fi

    export AIPASS_HOME="$SCRIPT_DIR"
fi

# --- Create global symlinks for CLI tools (Linux/macOS only) ---
echo ""
if [ "$IS_WINDOWS" -eq 1 ]; then
    echo "Windows: drone available via PATH (set above)"
elif [ "$IS_MACOS" -eq 1 ]; then
    # Mac: symlink into ~/.local/bin (user-writable, no sudo needed).
    # PATH export for ~/.local/bin is handled in the profile block above.
    echo "Creating user symlinks in ~/.local/bin ..."
    VENV_BIN="$SCRIPT_DIR/.venv/bin"
    LOCAL_BIN="$HOME/.local/bin"
    mkdir -p "$LOCAL_BIN"

    for cmd in drone; do
        if [ -f "$VENV_BIN/$cmd" ]; then
            if ln -sf "$VENV_BIN/$cmd" "$LOCAL_BIN/$cmd"; then
                echo "  $LOCAL_BIN/$cmd -> $VENV_BIN/$cmd"
            else
                echo "  WARN: Could not create symlink for $cmd"
                echo "  Manual fix: ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd"
            fi
        fi
    done
else
    echo "Creating global symlinks ..."
    VENV_BIN="$SCRIPT_DIR/.venv/bin"
    LOCAL_BIN="/usr/local/bin"

    for cmd in drone; do
        if [ -f "$VENV_BIN/$cmd" ]; then
            if sudo ln -sf "$VENV_BIN/$cmd" "$LOCAL_BIN/$cmd" 2>/dev/null; then
                echo "  $LOCAL_BIN/$cmd -> $VENV_BIN/$cmd"
            else
                echo "  WARN: Could not create symlink for $cmd (try running with sudo)"
                echo "  Manual fix: sudo ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd"
            fi
        fi
    done
fi

# --- Result ---
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "=== Setup complete ==="
    echo ""
    if [ "$IS_WINDOWS" -eq 1 ]; then
        echo "drone is available in .venv/Scripts/ (or .venv/bin/ for Git Bash)."
        echo "Add the appropriate directory to your PATH (see above)."
    elif [ "$IS_MACOS" -eq 1 ]; then
        echo "drone is available via ~/.local/bin symlink (on PATH)."
    else
        echo "drone is available globally via /usr/local/bin symlink."
    fi
    echo "seedgo is accessed via: drone @seedgo"
    echo "No venv activation needed for CLI commands."
    echo ""
    echo "CLI integrations:"
    echo "  Claude Code: hooks installed to ~/.claude/settings.json"
    command -v codex &>/dev/null && echo "  Codex CLI:   hooks at .codex/hooks.json + config at ~/.codex/config.toml"
    command -v gemini &>/dev/null && echo "  Gemini CLI:  hooks installed to ~/.gemini/settings.json"
    echo ""
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    exit 1
fi
