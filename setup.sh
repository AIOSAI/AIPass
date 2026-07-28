#!/usr/bin/env bash
#
# AIPass setup script
# Creates a venv, installs the package in editable mode, and verifies CLI entry points.
# On interactive terminals it then chains into `aipass init run` to scaffold a first
# project (DPLAN-0234: one command does setup + init).
#
# Usage: ./setup.sh [--no-init] [--with-init] [--project <dir>] [--no-symlink] [--force-symlink]
#   --no-init        skip the first-project init chain
#   --with-init      force the init chain even headless (init runs --non-interactive)
#   --project <dir>  first-project directory (default: ~/aipass-project)
#   --no-symlink     do not create/modify global drone/aipass CLI symlinks
#   --force-symlink  repoint a global symlink even if it points at a different install (#660)
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

# --- Args ---
# Mirrors the `aipass install` handoff rules: --no-init wins, --with-init forces,
# default (auto) chains into init on interactive terminals only — CI/headless skip.
RUN_INIT="auto"
INIT_PROJECT=""
SKIP_SYMLINK="no"
FORCE_SYMLINK="no"
PREV_ARG=""
for arg in "$@"; do
    if [ "$PREV_ARG" = "--project" ]; then
        INIT_PROJECT="$arg"
        PREV_ARG=""
        continue
    fi
    case "$arg" in
        --no-init)       RUN_INIT="no" ;;
        --with-init)     RUN_INIT="yes" ;;
        --no-symlink)    SKIP_SYMLINK="yes" ;;
        --force-symlink) FORCE_SYMLINK="yes" ;;
        --project=*)     INIT_PROJECT="${arg#--project=}" ;;
        --project)       PREV_ARG="--project" ;;
        *) echo "WARN: unknown argument '$arg' (ignored)" ;;
    esac
done

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

# --- Check ensurepip (Debian/Ubuntu split it into python3-venv apt package) ---
if ! $PYTHON -c 'import ensurepip' &>/dev/null 2>&1; then
    echo ""
    echo "FAIL: ensurepip is unavailable for $PYTHON."
    echo "  Without it, 'python3 -m venv' creates a broken venv (no pip, no activate)."
    echo ""
    echo "  Debian/Ubuntu:  sudo apt install python3-venv python3-pip"
    echo "  Fedora/RHEL:    sudo dnf install python3-pip"
    echo "  Arch:           (included in base python — file a bug if you hit this)"
    echo ""
    exit 1
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

echo "Installing aipass in editable mode (with dev + memory extras) — this can take a few minutes while the memory wheels build ..."
"$VENV_PYTHON" -m pip install -e ".[dev,memory]"

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

# --- Sandbox prerequisites (kernel FS boundary) ---
echo ""
echo "Checking sandbox prerequisites ..."

if [ "$IS_WINDOWS" -eq 1 ] || [ "$IS_MACOS" -eq 1 ]; then
    echo "  kernel sandbox: Linux-only for now, skipping"
else
    SB_MISSING=()

    # bwrap
    if command -v bwrap &>/dev/null; then
        echo "  bwrap     ... $(bwrap --version 2>/dev/null || echo 'found')"
    else
        echo "  bwrap     ... MISSING"
        echo "    sudo apt install bubblewrap"
        SB_MISSING+=("bwrap")
    fi

    # node
    if command -v node &>/dev/null; then
        echo "  node      ... $(node --version 2>/dev/null)"
    else
        echo "  node      ... MISSING"
        echo "    Install Node.js: https://nodejs.org/"
        SB_MISSING+=("node")
    fi

    # npm (needed for srt install)
    if command -v npm &>/dev/null; then
        echo "  npm       ... $(npm --version 2>/dev/null)"
    else
        echo "  npm       ... MISSING"
        SB_MISSING+=("npm")
    fi

    # @anthropic-ai/sandbox-runtime — resolve same way as _srt_resolve.mjs
    if command -v node &>/dev/null; then
        SRT_PATH=$(node -e "
            const p = require('path');
            const fs = require('fs');
            const prefix = p.dirname(p.dirname(process.execPath));
            const entry = p.join(prefix, 'lib/node_modules/@anthropic-ai/sandbox-runtime/dist/index.js');
            if (fs.existsSync(entry)) process.stdout.write(entry);
            else process.exit(1);
        " 2>/dev/null) || SRT_PATH=""
        if [ -n "$SRT_PATH" ]; then
            echo "  srt       ... $SRT_PATH"
        else
            echo "  srt       ... MISSING"
            if command -v npm &>/dev/null; then
                echo "    Attempting: npm install -g @anthropic-ai/sandbox-runtime"
                if npm install -g @anthropic-ai/sandbox-runtime 2>/dev/null; then
                    echo "    srt       ... installed"
                else
                    echo "    Install failed (may need sudo). Run manually:"
                    echo "      sudo npm install -g @anthropic-ai/sandbox-runtime"
                    SB_MISSING+=("srt")
                fi
            else
                echo "    Install node+npm first, then: npm install -g @anthropic-ai/sandbox-runtime"
                SB_MISSING+=("srt")
            fi
        fi
    else
        echo "  srt       ... skipped (no node)"
        SB_MISSING+=("srt")
    fi

    # rg (ripgrep)
    if command -v rg &>/dev/null; then
        echo "  rg        ... $(rg --version 2>/dev/null | head -1)"
    elif [ -f "$HOME/.local/bin/rg" ]; then
        echo "  rg        ... $HOME/.local/bin/rg"
    else
        echo "  rg        ... MISSING"
        echo "    sudo apt install ripgrep"
        SB_MISSING+=("rg")
    fi

    if [ ${#SB_MISSING[@]} -eq 0 ]; then
        echo "  sandbox prereqs: READY"
    else
        echo "  sandbox prereqs: INCOMPLETE (${SB_MISSING[*]} missing) — aipass doctor for details"
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
    chmod 700 "$SECRETS_DIR"
    echo "  ~/.secrets/aipass/ ... created"
else
    echo "Secrets directory already exists — skipping"
fi

# --- Seed .env template into secrets ---
if [ ! -f "$SECRETS_DIR/.env" ] && [ -f ".env.example" ]; then
    cp .env.example "$SECRETS_DIR/.env"
    echo "  Copied .env.example → ~/.secrets/aipass/.env (add your API keys there)"
fi

# --- Git identity (commits fail without user.email / user.name) ---
GIT_EMAIL=$(git config --global user.email 2>/dev/null || true)
GIT_NAME=$(git config --global user.name 2>/dev/null || true)
if [ -z "$GIT_EMAIL" ] || [ -z "$GIT_NAME" ]; then
    echo ""
    echo "Git identity not configured — commits will fail without it."
    DEFAULT_EMAIL="aipass.system@gmail.com"
    DEFAULT_NAME="AIOSAI"
    if [ -t 0 ]; then
        # Interactive — prompt with defaults
        read -r -p "  Git user.email [$DEFAULT_EMAIL]: " INPUT_EMAIL
        read -r -p "  Git user.name  [$DEFAULT_NAME]: " INPUT_NAME
        GIT_EMAIL="${INPUT_EMAIL:-$DEFAULT_EMAIL}"
        GIT_NAME="${INPUT_NAME:-$DEFAULT_NAME}"
    else
        # Non-interactive — use defaults
        GIT_EMAIL="$DEFAULT_EMAIL"
        GIT_NAME="$DEFAULT_NAME"
        echo "  Non-interactive mode — using defaults ($GIT_EMAIL / $GIT_NAME)"
    fi
    git config --global user.email "$GIT_EMAIL"
    git config --global user.name "$GIT_NAME"
    git config --global pull.rebase true
    echo "  Git identity set: $GIT_NAME <$GIT_EMAIL>"
else
    echo "Git identity: $GIT_NAME <$GIT_EMAIL>"
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
  "branch_info": {
    "branch_name": "${name}",
    "alias": "",
    "path": "src/aipass/${name}",
    "module": "aipass.${name}",
    "email": "@${name}",
    "created": "${DATE_TODAY}",
    "git_branch": "main"
  },
  "identity": {
    "name": "${name}",
    "citizen_class": "${citizen_class}",
    "role": "${role}",
    "status": "active",
    "traits": [],
    "purpose": "${role}",
    "what_i_do": [],
    "what_i_dont_do": []
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
bootstrap_branch "drone"    "$SCRIPT_DIR/src/aipass/drone" "aipass_framework" "Command routing and module discovery"
bootstrap_branch "seedgo"   "$SCRIPT_DIR/src/aipass/seedgo" "aipass_framework" "Standards enforcement and code auditing"
bootstrap_branch "prax"     "$SCRIPT_DIR/src/aipass/prax" "aipass_framework" "Logging and monitoring system"
bootstrap_branch "cli"      "$SCRIPT_DIR/src/aipass/cli" "aipass_framework" "Display formatting service"
bootstrap_branch "flow"     "$SCRIPT_DIR/src/aipass/flow" "aipass_framework" "Workflow and plan management"
bootstrap_branch "ai_mail"  "$SCRIPT_DIR/src/aipass/ai_mail" "aipass_framework" "Inter-agent messaging and dispatch"
bootstrap_branch "api"      "$SCRIPT_DIR/src/aipass/api" "aipass_framework" "LLM access and model routing"
bootstrap_branch "trigger"  "$SCRIPT_DIR/src/aipass/trigger" "aipass_framework" "Event-driven automation"
bootstrap_branch "spawn"    "$SCRIPT_DIR/src/aipass/spawn" "aipass_framework" "Branch lifecycle management"
bootstrap_branch "devpulse" "$SCRIPT_DIR/src/aipass/devpulse" "manager" "Orchestration hub and coordination"
bootstrap_branch "memory"   "$SCRIPT_DIR/src/aipass/memory" "aipass_framework" "Vector memory bank"
bootstrap_branch "aipass"   "$SCRIPT_DIR/src/aipass/aipass" "aipass_framework" "Concierge — init, doctor, profile, onboarding"
bootstrap_branch "hooks"    "$SCRIPT_DIR/src/aipass/hooks" "aipass_framework" "Hook engine — cross-platform hook dispatch and per-project config"

# External branches
# NOTE: backup, daemon removed S82/S87. commons, skills moved to external repos.
# Only the 13 core branches above should be bootstrapped.

echo "  13 branches bootstrapped"

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

# Determine python command for non-Claude provider hooks.
# Claude hooks use bridge pattern with $AIPASS_HOME env var — no HOOK_PYTHON needed.
# Linux: keep "python3" — distros ship 3.10+ and hooks import nothing
# version-specific beyond that.
# macOS: stock /usr/bin/python3 is 3.9.6 on macOS 12 and cannot parse
# scripts that use PEP 604 union syntax (`X | None`). Use the venv python.
# Windows: existing venv-python behavior.
if [ "$IS_WINDOWS" -eq 1 ]; then
    HOOK_PYTHON="$SCRIPT_DIR/.venv/Scripts/python.exe"
elif [ "$IS_MACOS" -eq 1 ]; then
    HOOK_PYTHON="$SCRIPT_DIR/.venv/bin/python3"
else
    HOOK_PYTHON="python3"
fi

if [ -f "$SCRIPT_DIR/src/aipass/hooks/apps/handlers/bridges/claude.py" ]; then
    echo "Installing Claude Code hooks ..."
    mkdir -p "$HOME/.claude"

    "$PYTHON" - "$SCRIPT_DIR" "$CLAUDE_SETTINGS" "$IS_WINDOWS" << 'PYEOF'
import json
import os
import sys
from pathlib import Path

repo_root = sys.argv[1]
settings_path = Path(sys.argv[2])
is_windows = len(sys.argv) > 3 and sys.argv[3] == "1"

# Bridge entry point — all hooks route through the engine via this bridge.
# Uses $AIPASS_HOME env var (injected into settings.env below) so the
# settings file stays relocatable. CC on Windows runs hooks via Git Bash
# (which must exist for setup.sh to have run), so $VAR expansion works —
# but the venv interpreter lives at Scripts/python.exe there, not bin/python3
# (@hooks assessment, DPLAN-0234 Strand C).
venv_python = ".venv/Scripts/python.exe" if is_windows else ".venv/bin/python3"
bridge = f"$AIPASS_HOME/{venv_python} $AIPASS_HOME/src/aipass/hooks/apps/handlers/bridges/claude.py"

# Load existing settings or start fresh
if settings_path.exists():
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
else:
    settings = {}

# Build hooks config — bridge pattern
# UserPromptSubmit: 5 separate entries (EventType:hook_name) to avoid output merging
# PreToolUse, PostToolUse, SubagentStop, Stop, Notification: single aggregate entries
# PreCompact: 3 hooks x 2 matchers (manual + auto) = 6 entries
# SessionStart: cadence reset on startup/clear (handler skips resume itself)
aipass_hooks = {
    "UserPromptSubmit": [
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:tier0_kernel"}]},
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:navmap"}]},
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:branch_prompt"}]},
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:identity_injector"}]},
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:email_notification"}]},
        {"hooks": [{"type": "command", "command": f"{bridge} UserPromptSubmit:auto_process", "timeout": 120}]},
    ],
    "PreToolUse": [
        {"matcher": "Bash|Edit|MultiEdit|Write|Read|Grep|Glob|WebSearch|WebFetch|Task",
         "hooks": [{"type": "command", "command": f"{bridge} PreToolUse"}]},
    ],
    "PostToolUse": [
        {"matcher": "Bash|Edit|MultiEdit|Write|NotebookEdit",
         "hooks": [{"type": "command", "command": f"{bridge} PostToolUse"}]},
    ],
    "SubagentStop": [
        {"hooks": [{"type": "command", "command": f"{bridge} SubagentStop"}]},
    ],
    "Stop": [
        {"hooks": [{"type": "command", "command": f"{bridge} Stop"}]},
    ],
    "Notification": [
        {"hooks": [{"type": "command", "command": f"{bridge} Notification"}]},
    ],
    "PreCompact": [
        {"matcher": "manual", "hooks": [{"type": "command", "command": f"{bridge} PreCompact:pre_compact", "timeout": 60}]},
        {"matcher": "auto",   "hooks": [{"type": "command", "command": f"{bridge} PreCompact:pre_compact", "timeout": 60}]},
        {"matcher": "manual", "hooks": [{"type": "command", "command": f"{bridge} PreCompact:pre_compact_rollover", "timeout": 120}]},
        {"matcher": "auto",   "hooks": [{"type": "command", "command": f"{bridge} PreCompact:pre_compact_rollover", "timeout": 120}]},
        {"matcher": "manual", "hooks": [{"type": "command", "command": f"{bridge} PreCompact:auto_process", "timeout": 120}]},
        {"matcher": "auto",   "hooks": [{"type": "command", "command": f"{bridge} PreCompact:auto_process", "timeout": 120}]},
    ],
    "SessionStart": [
        {"hooks": [{"type": "command", "command": f"{bridge} SessionStart:cadence_reset", "timeout": 30}]},
    ],
}

# Merge, don't replace (DPLAN-0234 Strand C): refresh every AIPass bridge entry
# (identified by the bridges/claude.py marker) but preserve any hooks the user
# wired themselves. Re-runs stay idempotent; custom hooks survive reinstall.
existing_hooks = settings.get("hooks", {})
merged_hooks = {}
for event in set(existing_hooks) | set(aipass_hooks):
    user_entries = [
        entry for entry in existing_hooks.get(event, [])
        if "bridges/claude.py" not in json.dumps(entry)
    ]
    merged = aipass_hooks.get(event, []) + user_entries
    # Never emit an empty hook event. If this event had only stale AIPass bridge
    # entries (no current aipass_hooks definition AND no user-wired hooks), the
    # filter above orphans it to [] — a half-wired event that fires nothing,
    # written silently. Drop the key instead and say so, so the state stays honest.
    if not merged:
        print(f"  ! dropped orphaned hook event (no live entries): {event}")
        continue
    merged_hooks[event] = merged
settings["hooks"] = merged_hooks

# Inject AIPASS_HOME into env block so dispatched agents find AIPass
env_block = settings.get("env", {})
env_block["AIPASS_HOME"] = repo_root
env_block["CLAUDE_CODE_DISABLE_AUTO_MEMORY"] = "1"
# Windows: force UTF-8 for Rich output in hook processes
msys = os.environ.get("MSYSTEM", "") + os.environ.get("OSTYPE", "")
if "MSYS" in msys or "msys" in msys or "MINGW" in msys:
    env_block["PYTHONUTF8"] = "1"
settings["env"] = env_block

# Deny rules — hard-block tool access to secrets
permissions = settings.get("permissions", {})
deny = permissions.get("deny", [])
secrets_deny = [
    "Read(~/.secrets/**)",
    f"Read({os.path.expanduser('~')}/.secrets/**)",
    "Bash(cat ~/.secrets/*)",
    f"Bash(cat {os.path.expanduser('~')}/.secrets/*)",
    "Bash(head ~/.secrets/*)",
    f"Bash(head {os.path.expanduser('~')}/.secrets/*)",
    "Bash(tail ~/.secrets/*)",
    f"Bash(tail {os.path.expanduser('~')}/.secrets/*)",
    "Bash(less ~/.secrets/*)",
    f"Bash(less {os.path.expanduser('~')}/.secrets/*)",
]
git_deny = [
    "Bash(git reset --hard*)",
    "Bash(git push --force*)",
    "Bash(git push -f *)",
    "Bash(git rebase*)",
    "Bash(git clean*)",
    "Bash(git reset*)",
    "Bash(git merge*)",
    "Bash(git config*)",
    "Bash(git checkout -- *)",
    "Bash(git checkout .*)",
    "Bash(git restore --staged*)",
    "Bash(git restore .*)",
    "Bash(git branch -D*)",
    "Bash(git stash drop*)",
    "Bash(git stash clear*)",
    "Bash(git checkout -b*)",
    "Bash(git switch -c*)",
    "Bash(git switch --create*)",
    "Bash(git commit*)",
    "Bash(git push*)",
]
for rule in secrets_deny + git_deny:
    if rule not in deny:
        deny.append(rule)
permissions["deny"] = deny

ask = permissions.get("ask", [])
home = os.path.expanduser("~")
ask_rules = [
    f"Edit({home}/.claude/**)",
    f"Write({home}/.claude/**)",
    "Edit(~/.claude/**)",
    "Write(~/.claude/**)",
]
for rule in ask_rules:
    if rule not in ask:
        ask.append(rule)
permissions["ask"] = ask

settings["permissions"] = permissions

settings_path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
print(f"  hooks -> {settings_path}")
print(f"  AIPASS_HOME -> {repo_root} (in settings.json env)")
PYEOF
else
    echo "Skipping Claude hooks (bridge not found at src/aipass/hooks/apps/handlers/bridges/claude.py)"
fi

# --- Install claude() boot shim (attach-if-live / start-in-tmux) ---
# Ships via the .gitignore negation (#666). Idempotent: the installer checks for
# its marker before appending to the shell rc, and resolves the venv Python from
# its own location (POSIX/Windows/fallback). Composes with presence_gate seeding.
BOOT_SHIM="$SCRIPT_DIR/src/aipass/hooks/tools/install_boot_shim.sh"
if [ -f "$BOOT_SHIM" ]; then
    echo "Installing claude() boot shim ..."
    bash "$BOOT_SHIM" || echo "  boot shim install skipped (non-fatal)"
fi

# --- Install Claude Code commands (provider level) ---
# memo.md belongs at provider level — works in all projects.
# prep.md stays at repo root only — it's AIPass-specific.
COMMANDS_SRC="$SCRIPT_DIR/.claude/templates"
COMMANDS_DST="$HOME/.claude/commands"
if [ -f "$COMMANDS_SRC/memo.md" ]; then
    mkdir -p "$COMMANDS_DST"
    cp -n "$COMMANDS_SRC/memo.md" "$COMMANDS_DST/memo.md" 2>/dev/null && \
        echo "  memo.md -> $COMMANDS_DST/ (installed)" || \
        echo "  memo.md -> $COMMANDS_DST/ (already exists, skipped)"
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
# #660: never SILENTLY hijack a global 'drone'/'aipass' that points at a
# DIFFERENT install. safe_symlink skips a different-target link (loud warning)
# unless --force-symlink; --no-symlink opts out of symlinking entirely.
SYMLINK_SKIPPED=0
safe_symlink() {
    # safe_symlink <src> <dest> [sudo]  ->  0 linked · 1 skipped(diff target) · 2 ln failed
    local src="$1" dest="$2" use_sudo="${3:-}" existing=""
    if [ -L "$dest" ]; then
        existing="$(readlink "$dest" 2>/dev/null)"
    elif [ -e "$dest" ]; then
        existing="$dest (real file, not a symlink)"
    fi
    if [ -n "$existing" ] && [ "$existing" != "$src" ]; then
        if [ "$FORCE_SYMLINK" != "yes" ]; then
            echo "  SKIP $dest — already points at a different install:"
            echo "       $existing"
            echo "       Not repointing (would hijack your existing '$(basename "$dest")'); PATH keeps the above."
            echo "       Re-run 'aipass install' with --force-symlink to repoint here, or --no-symlink to skip quietly."
            SYMLINK_SKIPPED=$((SYMLINK_SKIPPED + 1))
            return 1
        fi
        echo "  WARNING: repointing $dest"
        echo "           from $existing"
        echo "           to   $src   (--force-symlink)"
    fi
    if [ -n "$use_sudo" ]; then
        $use_sudo ln -sf "$src" "$dest" 2>/dev/null && return 0 || return 2
    fi
    ln -sf "$src" "$dest" 2>/dev/null && return 0 || return 2
}

echo ""
if [ "$SKIP_SYMLINK" = "yes" ]; then
    echo "Skipping global CLI symlinks (--no-symlink)."
    echo "  'drone'/'aipass' resolve from $SCRIPT_DIR/.venv/bin — add it to PATH to use them."
elif [ "$IS_WINDOWS" -eq 1 ]; then
    echo "Windows: drone available via PATH (set above)"
elif [ "$IS_MACOS" -eq 1 ]; then
    # Mac: symlink into ~/.local/bin (user-writable, no sudo needed).
    # PATH export for ~/.local/bin is handled in the profile block above.
    echo "Creating user symlinks in ~/.local/bin ..."
    VENV_BIN="$SCRIPT_DIR/.venv/bin"
    LOCAL_BIN="$HOME/.local/bin"
    mkdir -p "$LOCAL_BIN"

    for cmd in drone aipass; do
        if [ -f "$VENV_BIN/$cmd" ]; then
            rc=0
            safe_symlink "$VENV_BIN/$cmd" "$LOCAL_BIN/$cmd" || rc=$?
            if [ "$rc" -eq 0 ]; then
                echo "  $LOCAL_BIN/$cmd -> $VENV_BIN/$cmd"
            elif [ "$rc" -eq 2 ]; then
                echo "  WARN: Could not create symlink for $cmd"
                echo "  Manual fix: ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd"
            fi
        fi
    done
else
    echo "Creating global symlinks ..."
    VENV_BIN="$SCRIPT_DIR/.venv/bin"
    LINUX_SYMLINK_DIR=""

    for cmd in drone aipass; do
        if [ -f "$VENV_BIN/$cmd" ]; then
            rc=0
            safe_symlink "$VENV_BIN/$cmd" "/usr/local/bin/$cmd" "sudo" || rc=$?
            if [ "$rc" -eq 0 ]; then
                echo "  /usr/local/bin/$cmd -> $VENV_BIN/$cmd"
                LINUX_SYMLINK_DIR="/usr/local/bin"
            elif [ "$rc" -eq 1 ]; then
                :  # skipped a different install — safe_symlink explained; do NOT fall back
            else
                # sudo/ln failed (e.g. no sudo) — fall back to user-local bin
                LOCAL_BIN="$HOME/.local/bin"
                mkdir -p "$LOCAL_BIN"
                rc=0
                safe_symlink "$VENV_BIN/$cmd" "$LOCAL_BIN/$cmd" || rc=$?
                if [ "$rc" -eq 0 ]; then
                    echo "  /usr/local/bin failed (no sudo) — using $LOCAL_BIN/$cmd instead"
                    LINUX_SYMLINK_DIR="$LOCAL_BIN"
                    # Ensure ~/.local/bin is on PATH
                    PROFILE="${HOME}/.bashrc"
                    if ! grep -q '\.local/bin' "$PROFILE" 2>/dev/null; then
                        echo 'export PATH="$HOME/.local/bin:$PATH"' >> "$PROFILE"
                        echo "  ~/.local/bin added to PATH in $PROFILE"
                    fi
                    export PATH="$HOME/.local/bin:$PATH"
                elif [ "$rc" -eq 2 ]; then
                    echo "  WARN: Could not create symlink for $cmd"
                    echo "  Manual fix: ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd"
                fi
            fi
        fi
    done
fi

if [ "$SYMLINK_SKIPPED" -gt 0 ]; then
    echo ""
    echo "  NOTE: $SYMLINK_SKIPPED global symlink(s) left untouched (pointed at a different install)."
    echo "        Your existing 'drone'/'aipass' still work. Use --force-symlink to repoint them here."
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
    elif [ "$LINUX_SYMLINK_DIR" = "/usr/local/bin" ]; then
        echo "drone is available globally via /usr/local/bin symlink."
    else
        echo "drone is available via ~/.local/bin symlink (on PATH)."
    fi
    echo "seedgo is accessed via: drone @seedgo"
    echo "No venv activation needed for CLI commands."
    echo ""
    echo "CLI integrations:"
    echo "  Claude Code: hooks installed to ~/.claude/settings.json"
    command -v codex &>/dev/null && echo "  Codex CLI:   hooks at .codex/hooks.json + config at ~/.codex/config.toml"
    echo ""

    # --- Chain into first-project init (DPLAN-0234: one command does setup + init) ---
    # `aipass init` refuses to run inside the engine tree, so it always targets a
    # sibling directory — never the repo itself. Decision mirrors install.py:
    # --no-init wins, --with-init forces (headless chains --non-interactive),
    # default = interactive terminals only (CI and piped shells skip).
    AIPASS_BIN=""
    if [ "$IS_WINDOWS" -eq 1 ] && [ -f "$SCRIPT_DIR/.venv/Scripts/aipass.exe" ]; then
        AIPASS_BIN="$SCRIPT_DIR/.venv/Scripts/aipass.exe"
    elif [ "$IS_WINDOWS" -eq 1 ] && [ -f "$SCRIPT_DIR/.venv/Scripts/aipass" ]; then
        AIPASS_BIN="$SCRIPT_DIR/.venv/Scripts/aipass"
    elif [ -f "$SCRIPT_DIR/.venv/bin/aipass" ]; then
        AIPASS_BIN="$SCRIPT_DIR/.venv/bin/aipass"
    elif command -v aipass &>/dev/null; then
        AIPASS_BIN="$(command -v aipass)"
    fi

    LAUNCH_INIT=0
    INIT_HEADLESS=0
    if [ "$RUN_INIT" = "no" ]; then
        echo "Skipping first-project init (--no-init). Run 'aipass init run' in a fresh directory when ready."
    elif [ "$RUN_INIT" = "yes" ]; then
        LAUNCH_INIT=1
        if [ ! -t 0 ]; then
            INIT_HEADLESS=1
        fi
    elif [ -t 0 ] && [ -z "${CI:-}" ]; then
        LAUNCH_INIT=1
    else
        echo "Non-interactive shell — skipping first-project init. Run 'aipass init run' in a fresh directory when ready."
    fi

    if [ "$LAUNCH_INIT" -eq 1 ]; then
        if [ -z "$AIPASS_BIN" ]; then
            echo "WARN: aipass binary not found — open a new terminal and run 'aipass init run' in a fresh directory."
        else
            DEFAULT_PROJECT_DIR="$HOME/aipass-project"
            PROJECT_DIR="$INIT_PROJECT"
            if [ -z "$PROJECT_DIR" ] && [ "$INIT_HEADLESS" -eq 0 ] && [ -t 0 ]; then
                echo "AIPass projects live in their own directory, never inside the engine repo."
                read -r -p "Set up your first project now? [Y/n]: " INIT_REPLY
                case "$INIT_REPLY" in
                    [nN]*)
                        PROJECT_DIR="-"
                        echo "  Skipped. Run 'aipass init run' in a fresh directory when ready."
                        ;;
                    *)
                        read -r -p "  Project directory [$DEFAULT_PROJECT_DIR]: " INIT_INPUT
                        PROJECT_DIR="${INIT_INPUT:-$DEFAULT_PROJECT_DIR}"
                        ;;
                esac
            elif [ -z "$PROJECT_DIR" ]; then
                PROJECT_DIR="$DEFAULT_PROJECT_DIR"
            fi

            if [ "$PROJECT_DIR" != "-" ]; then
                mkdir -p "$PROJECT_DIR"
                INIT_CMD=("$AIPASS_BIN" init run)
                if [ "$INIT_HEADLESS" -eq 1 ]; then
                    INIT_CMD+=(--non-interactive)
                fi
                echo ""
                echo "Launching guided setup in $PROJECT_DIR ..."
                if (cd "$PROJECT_DIR" && "${INIT_CMD[@]}"); then
                    echo "First project initialized at $PROJECT_DIR"
                else
                    echo "Init didn't complete — run 'aipass init run' in $PROJECT_DIR when ready."
                fi
            fi
        fi
    fi
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    exit 1
fi
