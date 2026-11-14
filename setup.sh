#!/usr/bin/env bash
#
# AIPass setup script
# Creates a venv, installs the package in editable mode, and verifies CLI entry points.
# On interactive terminals it then ends in a conversation with the AIPass concierge —
# the cold install ends in chat, not project creation (DPLAN-0274). Project creation
# stays a separate, later step: `aipass init run`.
#
# Usage: ./setup.sh [--no-chat] [--no-symlink] [--force-symlink]
#   --no-chat        skip the welcome-chat ending (build only)
#   --no-symlink     do not create/modify global drone/aipass CLI symlinks
#   --force-symlink  repoint a global symlink even if it points at a different install (#660)
#

set -euo pipefail

# cd to repo root (where this script lives) so it works from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Args ---
# Mirrors the `aipass install` handoff: --no-chat skips the welcome chat,
# default (auto) ends in chat on interactive terminals only — CI/headless skip.
RUN_CHAT="auto"
SKIP_SYMLINK="no"
FORCE_SYMLINK="no"
for arg in "$@"; do
    case "$arg" in
        --no-chat)       RUN_CHAT="no" ;;
        --no-symlink)    SKIP_SYMLINK="yes" ;;
        --force-symlink) FORCE_SYMLINK="yes" ;;
        *) echo "WARN: unknown argument '$arg' (ignored)" ;;
    esac
done

# --- Collected action-needed items (round-2 install UX: a0f2351e Catch 2) ---
# Anything printed mid-run that needs a follow-up command gets appended here,
# then re-printed as ONE highlighted block right before the welcome chat —
# scrolling output buries sudo hints and skipped-identity notices otherwise.
ACTION_NEEDED=()

print_action_needed() {
    [ ${#ACTION_NEEDED[@]} -eq 0 ] && return
    echo ""
    if [ -t 1 ]; then
        echo -e "\033[1;33m▲ ACTION NEEDED — before you dive in:\033[0m"
    else
        echo "=== ACTION NEEDED — before you dive in: ==="
    fi
    for item in "${ACTION_NEEDED[@]}"; do
        echo "  - $item"
    done
    echo ""
}

# local@domain.tld — no whitespace, an @, a dot in the domain. Literal 'skip'
# handled by the caller before this ever runs (never store junk as an email).
is_valid_git_email() {
    [[ "$1" =~ ^[^[:space:]@]+@[^[:space:]@]+\.[^[:space:]@]+$ ]]
}

# Own function (not an inline `[ -t 0 ]`) so tests can override it after
# sourcing and drive the interactive prompts below without a real tty.
# AIPASS_NON_INTERACTIVE=1 wins over the tty test: `aipass install --non-interactive`
# exports it, because install.sh hands that process the user's tty and a run told
# it was non-interactive still asked for a git identity (container proof, 2026-10-13).
is_interactive() {
    [ -n "${AIPASS_NON_INTERACTIVE:-}" ] && return 1
    [ -t 0 ]
}

echo "=== AIPass Setup ==="
echo "Repo root: $SCRIPT_DIR"
echo ""

# --- Find working Python ---
PYTHON=""
# Probe versioned binaries first: stock python3 may be older than 3.10.
for v in 3.13 3.12 3.11 3.10; do
    if command -v "python$v" &>/dev/null && "python$v" -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python$v"
        break
    fi
done
# Fall back to python3, then python
if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null && python3 -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python3"
    elif command -v python &>/dev/null && python -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "FAIL: No working Python found. Install Python 3.10+ and try again."
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found $PYTHON $PY_VERSION"

# --- Check minimum version ---
PY_OK=$($PYTHON -c 'import sys; print(int(sys.version_info >= (3, 10)))')
if [ "$PY_OK" != "1" ]; then
    echo "FAIL: Python 3.10+ required, found $PY_VERSION"
    exit 1
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
if [ -d ".venv" ]; then
    echo "Existing .venv found — removing it for a clean install."
    rm -rf .venv
fi

echo "Creating virtual environment at .venv ..."
$PYTHON -m venv .venv

# --- Activate and install ---
source .venv/bin/activate
VENV_PYTHON="python3"

echo "Upgrading pip ..."
"$VENV_PYTHON" -m pip install --upgrade pip --quiet

echo "Installing aipass in editable mode (with dev, memory, llm, drive, bluesky extras) — this can take a few minutes while the memory wheels build ..."
"$VENV_PYTHON" -m pip install -e ".[dev,memory,llm,drive,bluesky,host]"

# --- Sandbox prerequisites (kernel FS boundary) ---
echo ""
echo "Checking sandbox prerequisites ..."

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

# @anthropic-ai/sandbox-runtime — resolve via the real resolver (owned by
# the hooks branch, handles node-prefix != npm-prefix layouts, DPLAN-0279)
SRT_RESOLVER="$SCRIPT_DIR/src/aipass/hooks/apps/modules/_srt_resolve.mjs"
if command -v node &>/dev/null && [ -f "$SRT_RESOLVER" ]; then
    SRT_PATH=$(node "$SRT_RESOLVER" --resolve 2>/dev/null) || SRT_PATH=""
    if [ -n "$SRT_PATH" ]; then
        echo "  srt       ... $SRT_PATH"
    else
        echo "  srt       ... MISSING"
        if command -v npm &>/dev/null; then
            NPM_PREFIX=$(npm root -g 2>/dev/null)
            echo "    Attempting: npm install -g @anthropic-ai/sandbox-runtime (into ${NPM_PREFIX:-npm global prefix})"
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
elif ! command -v node &>/dev/null; then
    echo "  srt       ... skipped (no node)"
    SB_MISSING+=("srt")
else
    # Not an optional tool: the resolver is a tracked file of this checkout.
    # Its absence means the clone is incomplete, which is the one sandbox
    # row that belongs in ACTION NEEDED (DPLAN-0409, the 2026-10-15 review).
    echo "  srt       ... skipped (resolver script missing: $SRT_RESOLVER)"
    SB_MISSING+=("srt")
    ACTION_NEEDED+=("Checkout incomplete — $SRT_RESOLVER is a tracked file and is missing. Run: drone @git status, then drone @git fix, or re-run the install line to clone again")
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
    # Optional (DPLAN-0407): AIPass runs without the kernel sandbox, so a missing
    # tool is a line here, never an ACTION NEEDED item after "ready" (the owner's
    # test 13: the install ended on a homework list of five optional tools).
    echo "  sandbox: optional, not set up here (${SB_MISSING[*]} missing); AIPass runs without it — aipass doctor says how"
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

# sentry is accessed via drone @sentry, not as a standalone CLI
if drone @sentry --help &>/dev/null; then
    echo "  sentry ... ok (via drone @sentry)"
else
    echo "  sentry ... FAILED"
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
resolve_git_identity() {
    GIT_EMAIL=$(git config --global user.email 2>/dev/null || true)
    GIT_NAME=$(git config --global user.name 2>/dev/null || true)
    GIT_IDENTITY_SKIPPED="no"
    if [ -z "$GIT_EMAIL" ] || [ -z "$GIT_NAME" ]; then
        echo ""
        echo "Git identity not configured — commits will fail without it."
        if is_interactive; then
            # Interactive — no defaults. Git needs a real identity, not ours.
            echo "  Git needs a name and email to attribute commits to you — this is yours, not ours."
            echo "  Enter (or type 'skip') to skip for now and set it up later."
            while true; do
                read -r -p "  Git user.email: " GIT_EMAIL
                if [ -z "$GIT_EMAIL" ] || [ "$GIT_EMAIL" = "skip" ]; then
                    GIT_EMAIL=""
                    GIT_IDENTITY_SKIPPED="yes"
                    break
                fi
                if is_valid_git_email "$GIT_EMAIL"; then
                    break
                fi
                echo "  Doesn't look like an email — needs an @ and a dot in the domain (or Enter/'skip' to skip)."
            done
            if [ "$GIT_IDENTITY_SKIPPED" = "no" ]; then
                while [ -z "$GIT_NAME" ]; do
                    read -r -p "  Git user.name: " GIT_NAME
                    [ -z "$GIT_NAME" ] && echo "  Can't be blank — git needs a name to attribute commits."
                done
                git config --global user.email "$GIT_EMAIL"
                git config --global user.name "$GIT_NAME"
                git config --global pull.rebase true
                echo "  Git identity set: $GIT_NAME <$GIT_EMAIL>"
            else
                echo "  Skipped. Set it later with:"
                echo "    git config --global user.email \"you@example.com\""
                echo "    git config --global user.name \"Your Name\""
                ACTION_NEEDED+=("Git identity not set — run: git config --global user.email \"you@example.com\" && git config --global user.name \"Your Name\"")
            fi
        else
            # Non-interactive — never guess an identity, and never make it homework
            # (DPLAN-0407): a stranger's first five minutes do not commit. One line;
            # git itself asks for a name the first time a commit needs one.
            echo "  Not set (non-interactive); git will ask for one at your first commit."
            GIT_IDENTITY_SKIPPED="yes"
        fi
    else
        echo "Git identity: $GIT_NAME <$GIT_EMAIL>"
    fi
}
resolve_git_identity

# --- User's display name (round-2 install UX, 43ff5873: collected once here so
# the registry — and later the concierge greeting — already has it; the chat's
# own name-ask becomes a fallback for whenever this is skipped or empty) ---
resolve_user_name() {
    USER_NAME=""
    if is_interactive; then
        if [ -n "$GIT_NAME" ]; then
            read -r -p "What should we call you? [$GIT_NAME] (Enter to accept, or 'skip'): " USER_NAME
            if [ -z "$USER_NAME" ]; then
                USER_NAME="$GIT_NAME"
            elif [ "$USER_NAME" = "skip" ]; then
                USER_NAME=""
            fi
        else
            read -r -p "What should we call you? (Enter to skip): " USER_NAME
            # set -e trap: a bare `[ ... ] && ...` as the function's last command
            # returns 1 when the test fails, killing the whole install silently.
            if [ "$USER_NAME" = "skip" ]; then USER_NAME=""; fi
        fi
    fi
}
resolve_user_name

# --- Generate branch registry ---
if [ ! -f "AIPASS_REGISTRY.json" ]; then
    echo "Generating AIPASS_REGISTRY.json ..."
    python3 - "$SCRIPT_DIR" "$USER_NAME" << 'PYEOF'
import json, sys, os, uuid
from pathlib import Path
from datetime import date

repo_root = sys.argv[1]
user_name = sys.argv[2] if len(sys.argv) > 2 else ""
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

# Registry includes every branch discovered under src/aipass/ — no hardcoded list.

registry = {
    "metadata": {
        "id": str(uuid.uuid4()),
        "version": "1.0.0",
        "last_updated": today,
        "total_branches": len(branches),
        "user": user_name,
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

BRANCH_COUNT=0

bootstrap_branch() {
    local name="$1"
    local path="$2"
    local citizen_class="$3"
    local role="$4"
    local created=0

    BRANCH_COUNT=$((BRANCH_COUNT + 1))

    # .trinity/passport.json + local.json + observations.json
    # DPLAN-0263 P2: rendered from spawn's own specialist/manager templates
    # (single source of truth) instead of hand-rolled heredocs — the heredocs had
    # drifted to a pre-numbered-entry schema (key_learnings as dict, observations
    # nested session/entries) that the cap/rollover system doesn't expect. By this
    # point in the script the venv exists and aipass is pip-installed editable
    # (with the memory extra), so VENV_PYTHON can import aipass.spawn's renderer
    # directly. rel_path keeps branch_info.path relative ("src/aipass/<name>",
    # matching every real passport) instead of the absolute path build_replacements_dict
    # would otherwise render for an absolute target_dir.
    mkdir -p "$path/.trinity"
    local rel_path="${path#"$SCRIPT_DIR"/}"
    local rendered
    if [ ! -f "$path/.trinity/passport.json" ] || [ ! -f "$path/.trinity/local.json" ] || [ ! -f "$path/.trinity/observations.json" ]; then
        rendered=$("$VENV_PYTHON" - "$name" "$rel_path" "$citizen_class" "$role" << 'PYEOF'
import sys
from pathlib import Path

from aipass.spawn.apps.handlers.class_registry import get_template_dir, resolve_template_class
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict, replace_placeholders

branch_name, target_path, citizen_class, role = sys.argv[1:5]
target = Path(target_path)

# PASSPORT SEEDS (TDPLAN-0017): a branch shipping a tracked seed births its real
# identity from it — machine-local ids minted fresh, same as spawn's seed door.
# The template loop below only fills what this lane didn't write. A seed that
# fails validation kills the install loudly — never a silent template fallback.
import json
import uuid

from aipass.spawn.apps.handlers.seed_ops import find_seed, mint_and_write

minted = []
seed_file = find_seed(target)
passport_dest = target / ".trinity" / "passport.json"
if seed_file is not None and not passport_dest.exists():
    registry = json.loads(Path("AIPASS_REGISTRY.json").read_text(encoding="utf-8"))
    mint_and_write(
        seed_file,
        passport_dest,
        branch_name=branch_name,
        registry_id=registry.get("metadata", {}).get("id", ""),
        citizen_id=str(uuid.uuid4()),
    )
    minted.append("passport.json(seed)")

# "manager" (devpulse) isn't template-selectable — resolve_template_class picks
# its real shape via identity.role, same logic `spawn update` heals against.
template_class = resolve_template_class({"citizen_class": citizen_class, "role": role})
template_dir = get_template_dir(template_class)

try:
    from aipass.memory.apps.handlers.tracking.tab_renderer import render_all_meta_tabs
    meta_tabs = render_all_meta_tabs()
except ImportError:
    meta_tabs = {}

replacements = build_replacements_dict(
    target, branch_name, role=role, purpose=role, citizen_class=citizen_class, meta_tabs=meta_tabs,
)
# build_replacements_dict's MODULE default is bare (shared with non-package
# project_agent branches) — every src/aipass/* branch's real import path
# carries the aipass. package prefix.
replacements["MODULE"] = f"aipass.{replacements['branchname']}"

created = list(minted)
for filename in ("passport.json", "local.json", "observations.json"):
    dest = target / ".trinity" / filename
    if dest.exists():
        continue
    src = template_dir / ".trinity" / filename
    content = replace_placeholders(src.read_text(encoding="utf-8"), replacements)
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    created.append(filename)

print(",".join(created))
PYEOF
)
        if [ -n "$rendered" ]; then
            created=1
        fi
    fi

    # .sentry/bypass.json
    mkdir -p "$path/.sentry"
    if [ ! -f "$path/.sentry/bypass.json" ]; then
        echo '{}' > "$path/.sentry/bypass.json"
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
bootstrap_branch "drone"    "$SCRIPT_DIR/src/aipass/drone" "specialist" "Command routing and module discovery"
bootstrap_branch "sentry"   "$SCRIPT_DIR/src/aipass/sentry" "specialist" "Standards enforcement and code auditing"
bootstrap_branch "prax"     "$SCRIPT_DIR/src/aipass/prax" "specialist" "Logging and monitoring system"
bootstrap_branch "cli"      "$SCRIPT_DIR/src/aipass/cli" "specialist" "Display formatting service"
bootstrap_branch "flow"     "$SCRIPT_DIR/src/aipass/flow" "specialist" "Workflow and plan management"
bootstrap_branch "ai_mail"  "$SCRIPT_DIR/src/aipass/ai_mail" "specialist" "Inter-agent messaging and dispatch"
bootstrap_branch "api"      "$SCRIPT_DIR/src/aipass/api" "specialist" "LLM access and model routing"
bootstrap_branch "trigger"  "$SCRIPT_DIR/src/aipass/trigger" "specialist" "Event-driven automation"
bootstrap_branch "spawn"    "$SCRIPT_DIR/src/aipass/spawn" "specialist" "Branch lifecycle management"
bootstrap_branch "devpulse" "$SCRIPT_DIR/src/aipass/devpulse" "manager" "Orchestration hub and coordination"
bootstrap_branch "memory"   "$SCRIPT_DIR/src/aipass/memory" "specialist" "Vector memory bank"
bootstrap_branch "aipass"   "$SCRIPT_DIR/src/aipass/aipass" "specialist" "Concierge — init, doctor, profile, onboarding"
bootstrap_branch "hooks"    "$SCRIPT_DIR/src/aipass/hooks" "specialist" "Hook engine — hook dispatch and per-project config"
bootstrap_branch "backup"   "$SCRIPT_DIR/src/aipass/backup" "specialist" "Local-first backups, snapshots and restore"
bootstrap_branch "commons"  "$SCRIPT_DIR/src/aipass/commons" "specialist" "Community social space — posts, comments, votes"
bootstrap_branch "daemon"   "$SCRIPT_DIR/src/aipass/daemon" "specialist" "Task scheduler — per-branch schedule discovery"
bootstrap_branch "skills"   "$SCRIPT_DIR/src/aipass/skills" "specialist" "Capability framework — discoverable skill units"
bootstrap_branch "canary"   "$SCRIPT_DIR/src/aipass/canary" "specialist" "Permanent test citizen — dispatch and gate verification"

# All 18 core branches in src/aipass/ are bootstrapped above. (A stale note here
# once claimed backup/commons/daemon/skills were external — they returned to core
# long ago; the drift canary caught the gap, DPLAN-0262.)
# THIS LIST IS A BIRTH-DAY HAZARD: every citizen @spawn creates must be added by
# hand or fresh installs mint every passport except theirs — which is exactly how
# @canary (born 2026-08-22) failed spawn's drift test the next morning. @spawn is told; the durable fix is deriving this list from the
# tree the way the registry build already does.

echo "  $BRANCH_COUNT branches bootstrapped"

# --- Reconcile registry owner + per-citizen identity ---
# setup.sh's registry generation above lists branches with no owner seat and no
# per-branch registry_id (only metadata.id + passports get one, all sharing the
# same value by design). Without this step, a newcomer's FIRST doctor run reads
# 19 stale-bookkeeping errors (entry_rid_stale x17, no_owner) on a healthy install
# — sync-registry --fix carries this exact machinery, it just never ran here.
echo ""
echo "Reconciling registry owner + identity ..."
"$VENV_PYTHON" - << 'PYEOF'
from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

result = fix_owner_identity(dry_run=False)
if result["actions"]:
    for action in result["actions"]:
        print(f"  {action}")
else:
    print("  already clean")
PYEOF

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
# One door writes ~/.claude/settings.json at install: refresh_provider_hooks below
# (hooks, env, permissions, scalars), which backs the file up and leaves a receipt
# first (FPLAN-0645). The stdlib heredoc that used to rewrite env and deny rules
# after it, with no backup, is gone.

if [ -f "$SCRIPT_DIR/src/aipass/hooks/apps/handlers/bridges/claude.py" ]; then
    echo "Installing Claude Code hooks ..."
    mkdir -p "$HOME/.claude"

    "$VENV_PYTHON" - "$SCRIPT_DIR/.claude/provider_manifest.json" << 'PYEOF'
import sys
from pathlib import Path

from aipass.aipass.apps.handlers.provider_wire import refresh_provider_hooks

manifest_path = Path(sys.argv[1])
actions = refresh_provider_hooks(manifest_path)
for action in actions:
    print(f"  {action}")
PYEOF
else
    echo "Skipping Claude hooks (bridge not found at src/aipass/hooks/apps/handlers/bridges/claude.py)"
fi

# --- Enroll this install in the hook trust registry (the owner's ruling, compass #221) ---
# The hook engine only loads .aipass/hooks.json for projects listed in
# ~/.aipass/trusted_projects.json. That gate exists to stop a FOREIGN project's
# hostile hooks.json from running — it was never meant to distrust the config
# this installer just wired up. Without this step a non-interactive install
# finishes "clean" with every hook silently dead ("No .aipass/hooks.json found").
# enroll() is idempotent (dict-key assignment + stale prune), so re-running
# setup.sh refreshes the hash instead of duplicating the entry.
echo ""
echo "Enrolling this install in the hook trust registry ..."
if "$VENV_PYTHON" - "$SCRIPT_DIR" << 'PYEOF'
import sys

from aipass.hooks.apps.modules.door_trust_registry import enroll

sys.exit(0 if enroll(sys.argv[1]) else 1)
PYEOF
then
    echo "  trusted -> $SCRIPT_DIR"
else
    echo "  WARN: could not enroll $SCRIPT_DIR — hooks stay inactive until it is trusted"
    ACTION_NEEDED+=("Hook trust enrollment failed — run: aipass trust $SCRIPT_DIR")
fi

# --- Install claude() boot shim (attach-if-live / start-in-tmux) ---
# Ships via the .gitignore negation (#666). Idempotent: the installer checks for
# its marker before appending to the shell rc, and resolves the venv Python from
# its own location. Composes with presence_gate seeding.
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
# One door, the code `aipass doctor --fix` runs for the hooks: cli.codex merged into the
# user-level $CODEX_HOME/hooks.json (else ~/.codex/hooks.json), then the four config pins set
# line by line in config.toml, every other line (the owner's model among them) kept.
if command -v codex &>/dev/null; then
    echo "Installing Codex CLI hooks ..."
    if "$VENV_PYTHON" - "$SCRIPT_DIR/.claude/provider_manifest.json" << 'PYEOF'
import sys
from pathlib import Path

from aipass.aipass.apps.handlers.provider_wire import refresh_codex

for action in refresh_codex(Path(sys.argv[1])):
    print(f"  {action}")
PYEOF
    then
        echo "  Trust them once: run codex and choose 'Trust all and continue' (headless runs skip untrusted hooks)."
    else
        echo "  Codex hooks NOT installed (see the error above); run aipass doctor for the Codex rows."
    fi
else
    echo "Skipping Codex CLI (not installed)"
fi

# --- Install the OpenCode plugin (the `aipass doctor --fix` door: backup, byte-equal copy, receipt) ---
# The curl installer puts opencode in ~/.opencode/bin, on PATH only through ~/.bashrc.
if command -v opencode &>/dev/null || [ -x "$HOME/.opencode/bin/opencode" ]; then
    echo "Installing the OpenCode plugin ..."
    if "$VENV_PYTHON" - "$SCRIPT_DIR/.claude/provider_manifest.json" << 'PYEOF'
import sys
from pathlib import Path

from aipass.aipass.apps.handlers.provider_wire import install_opencode_plugin

for action in install_opencode_plugin(Path(sys.argv[1])):
    print(f"  {action}")
PYEOF
    then
        :
    else
        echo "  OpenCode plugin NOT installed (see the error above); run aipass doctor for the OpenCode rows."
    fi
else
    echo "Skipping OpenCode (not installed)"
fi

# --- Set AIPASS_HOME + PATH so all services work from any project ---
echo ""
echo "Configuring cross-project access ..."

PROFILE="$HOME/.bashrc"

# AIPASS_HOME
if ! grep -q "AIPASS_HOME" "$PROFILE" 2>/dev/null; then
    echo "" >> "$PROFILE"
    echo "# AIPass — cross-project access" >> "$PROFILE"
    echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$PROFILE"
    echo "  AIPASS_HOME added to $PROFILE"
else
    echo "  AIPASS_HOME already in $PROFILE"
fi

# ~/.bashrc returns early when not interactive; ~/.profile reaches every login shell (Codex's shell snapshot, cron).
if [ -f "$HOME/.profile" ]; then
    if ! grep -q "AIPASS_HOME" "$HOME/.profile" 2>/dev/null; then
        echo "" >> "$HOME/.profile"
        echo "# AIPass — cross-project access (login shells, interactive or not)" >> "$HOME/.profile"
        echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$HOME/.profile"
        echo "  AIPASS_HOME added to $HOME/.profile"
    else
        echo "  AIPASS_HOME already in $HOME/.profile"
    fi
fi

export AIPASS_HOME="$SCRIPT_DIR"

# --- Create global symlinks for CLI tools ---
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
    ACTION_NEEDED+=("$SYMLINK_SKIPPED global symlink(s) left untouched — rerun with --force-symlink to repoint them here")
fi

# --- Result ---
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "=== Setup complete ==="
    echo ""
    if [ "${LINUX_SYMLINK_DIR:-}" = "/usr/local/bin" ]; then
        echo "drone is available globally via /usr/local/bin symlink."
    else
        echo "drone is available via ~/.local/bin symlink (on PATH)."
    fi
    echo "sentry is accessed via: drone @sentry"
    echo "No venv activation needed for CLI commands."
    echo ""
    echo "CLI integrations:"
    echo "  Claude Code: hooks installed to ~/.claude/settings.json"
    { command -v opencode &>/dev/null || [ -x "$HOME/.opencode/bin/opencode" ]; } && echo "  OpenCode:    plugin installed to ~/.config/opencode/plugins/aipass.ts"
    command -v codex &>/dev/null && echo "  Codex CLI:   hooks merged into ${CODEX_HOME:-~/.codex}/hooks.json, pins in its config.toml (trust them once in codex)"
    echo ""

    # Last thing on screen before the chat launches — everything collected
    # above (sudo hints, skipped identity, untouched symlinks) in one place.
    print_action_needed

    # --- End in a welcome chat (DPLAN-0274: cold install ends in a conversation,
    # not project creation — commit 71e5198d / TDPLAN-0014 built the chat machinery
    # this reuses: `aipass install --chat-only` composes the same prompt via
    # install.py's _build_install_prompt and launches it via launch_inline. Nothing
    # is recomposed here in bash, no prompt text is duplicated.
    AIPASS_BIN=""
    if [ -f "$SCRIPT_DIR/.venv/bin/aipass" ]; then
        AIPASS_BIN="$SCRIPT_DIR/.venv/bin/aipass"
    elif command -v aipass &>/dev/null; then
        AIPASS_BIN="$(command -v aipass)"
    fi

    if [ "$RUN_CHAT" = "no" ]; then
        echo "Skipping the welcome chat (--no-chat). Run 'claude' in $SCRIPT_DIR when ready, or 'aipass init run' in a fresh directory to start a project."
    elif [ -z "$AIPASS_BIN" ]; then
        echo "WARN: aipass binary not found — open a new terminal and run 'aipass install --chat-only --path $SCRIPT_DIR'."
    elif [ ! -t 0 ] || [ -n "${CI:-}" ]; then
        echo "Non-interactive shell — skipping the welcome chat. Run 'claude' in $SCRIPT_DIR when ready, or 'aipass init run' in a fresh directory to start a project."
    else
        # --path (not --here): setup.sh can be invoked from any CWD, but the home
        # it built is always its own directory. ACTION_NEEDED items + the
        # identity-skip flag pass through as env vars — composition of the
        # concierge's opener stays in install.py's _build_install_prompt, the
        # ONE place that builds it (round-2 install UX, a0f2351e/43ff5873).
        if [ ${#ACTION_NEEDED[@]} -eq 0 ]; then
            export AIPASS_ACTION_NEEDED=""
        else
            export AIPASS_ACTION_NEEDED="$(printf '%s\n' "${ACTION_NEEDED[@]}")"
        fi
        [ "$GIT_IDENTITY_SKIPPED" = "yes" ] && export AIPASS_IDENTITY_SKIPPED="1"
        "$AIPASS_BIN" install --chat-only --path "$SCRIPT_DIR"
    fi
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    exit 1
fi
