#!/usr/bin/env bash
#
# AIPass setup script
# Creates a venv, installs the package in editable mode, and verifies CLI entry points.
# It ends in `aipass install --finish`: the doctor, the install report and the final screen.
#
# Usage: ./setup.sh [--no-finish] [--no-symlink] [--force-symlink]
#   --no-finish      skip the doctor/report tail (`aipass install` passes it and runs the tail itself)
#   --no-symlink     do not create/modify global drone/aipass CLI symlinks
#   --force-symlink  repoint a global symlink even if it points at a different install (#660)
#

set -euo pipefail

# cd to repo root (where this script lives) so it works from anywhere
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- Args ---
RUN_FINISH="yes"
SKIP_SYMLINK="no"
FORCE_SYMLINK="no"
for arg in "$@"; do
    case "$arg" in
        --no-finish)     RUN_FINISH="no" ;;
        --no-symlink)    SKIP_SYMLINK="yes" ;;
        --force-symlink) FORCE_SYMLINK="yes" ;;
        --yes)           export AIPASS_YES=1 ;;
        *) echo "WARN: unknown argument '$arg' (ignored)" ;;
    esac
done

# --- Collected action-needed items (round-2 install UX: a0f2351e Catch 2) ---
# Anything printed mid-run that needs a follow-up command gets appended here,
# then printed as ONE block at the end and written to .aipass/setup_attention.txt
# for the install report — scrolling output buries sudo hints otherwise.
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
# This checkout's venv is deleted below: one active in the calling shell must not be the python picked here.
PATH=$(printf '%s' "$PATH" | tr ':' '\n' | grep -vxF "$SCRIPT_DIR/.venv/bin" | paste -sd:)
PYTHON=""
# Probe versioned binaries first: stock python3 may be older than 3.10.
for v in 3.13 3.12 3.11 3.10; do
    if command -v "python$v" &>/dev/null && "python$v" -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python$v"
        break
    fi
done
# Fall back to python3 (bare `python` is not probed: Python 2 on old hosts)
if [ -z "$PYTHON" ]; then
    if command -v python3 &>/dev/null && python3 -c "import sys" &>/dev/null 2>&1; then
        PYTHON="python3"
    fi
fi

if [ -z "$PYTHON" ]; then
    echo "FAIL: No working Python found. Install Python 3.10+ and try again."
    printf '%s\n' "setup.sh stopped: no working Python 3.10+" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
    exit 1
fi

PY_VERSION=$($PYTHON -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
echo "Found $PYTHON $PY_VERSION"

# --- Check minimum version ---
PY_OK=$($PYTHON -c 'import sys; print(int(sys.version_info >= (3, 10)))')
if [ "$PY_OK" != "1" ]; then
    echo "FAIL: Python 3.10+ required, found $PY_VERSION"
    printf '%s\n' "setup.sh stopped: Python 3.10+ required, found $PY_VERSION" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
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
    printf '%s\n' "setup.sh stopped: ensurepip unavailable for $PYTHON (Debian/Ubuntu: apt install python3-venv)" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
    exit 1
fi

# --- Create venv ---
if [ -d ".venv" ]; then
    echo "Existing .venv found — removing $SCRIPT_DIR/.venv for a clean install."
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

# --- User's display name: git user.name, else $USER, never asked (the owner: no
# questions about the user). Stored as registry metadata.user; the install report
# carries it as user_name and devpulse greets by it. Git identity itself is never
# asked here: git names the gap the first time a commit needs one. ---
resolve_user_name() {
    USER_NAME="$(git config --global user.name 2>/dev/null || true)"
    # $USER is unset under a bare su or a container entrypoint; the login name is always there.
    USER_NAME="${USER_NAME:-${USER:-$(id -un 2>/dev/null || true)}}"
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
            "path": d.relative_to(repo_root).as_posix(),
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

from aipass.spawn import render_bootstrap_trinity

branch_name, target_path, citizen_class, role = sys.argv[1:5]
# Spawn owns the render: seed first, then the class template for each missing
# file. A bad seed or an unreadable registry kills the install loudly.
written = render_bootstrap_trinity(
    branch_name, Path(target_path), citizen_class, role, Path("AIPASS_REGISTRY.json"),
)
print(",".join(written))
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

# Every citizen with a tracked passport seed, derived from the tree as the registry build is.
for vault in "$SCRIPT_DIR"/src/aipass/*/.aipass/passport.vault.json; do
    [ -f "$vault" ] || continue
    seat_dir="${vault%/.aipass/passport.vault.json}"
    seat_meta=$("$VENV_PYTHON" -c 'import json, sys; i = json.load(open(sys.argv[1], encoding="utf-8"))["identity"]; print(i["citizen_class"], i["role"])' "$vault") || {
        echo "FAIL: cannot read citizen_class and role from $vault"
        printf '%s\n' "setup.sh stopped: unreadable passport seed $vault" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
        exit 1
    }
    read -r seat_class seat_role <<< "$seat_meta"
    bootstrap_branch "$(basename "$seat_dir")" "$seat_dir" "$seat_class" "$seat_role"
done

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

from aipass.hooks import enroll

sys.exit(0 if enroll(sys.argv[1]) else 1)
PYEOF
then
    echo "  trusted -> $SCRIPT_DIR"
else
    echo "  WARN: could not enroll $SCRIPT_DIR — hooks stay inactive until it is trusted"
    ACTION_NEEDED+=("Hook trust enrollment failed — run: aipass trust $SCRIPT_DIR")
fi

# --- Machine changes outside this checkout (owner rule: one explanation, one yes/no) ---
# On a tty one question covers the block below; on no it is skipped whole. AIPASS_YES=1
# (aipass install --yes) is the yes given up front. With no tty, AIPASS_NON_INTERACTIVE
# or CI and no AIPASS_YES, nobody was asked, so it is a no: never a silent yes.
confirm_machine_changes() {
    MACHINE_CHANGES="yes"
    if [ "${AIPASS_YES:-}" = "1" ]; then
        return 0
    fi
    if ! is_interactive || [ -n "${CI:-}" ]; then
        MACHINE_CHANGES="no"
        echo ""
        echo "  Machine changes skipped: no terminal to ask on and no --yes counts as no."
        ACTION_NEEDED+=("Machine changes skipped (no --yes): shell rc, AIPASS_HOME, symlinks. Run: aipass install --yes, or $SCRIPT_DIR/setup.sh on a terminal")
        return 0
    fi
    echo ""
    echo "Setup now changes these things outside $SCRIPT_DIR:"
    echo "  - ~/.bashrc: AIPASS_HOME, and a PATH line if needed; ~/.profile: AIPASS_HOME"
    echo "  - drone/aipass symlinks in /usr/local/bin (sudo) or ~/.local/bin"
    echo "No provider is wired now. At the end of the install you pick one, and only it is wired:"
    echo "  - Claude Code: ~/.claude/settings.json (hooks, env, deny rules; backed up first), ~/.claude/commands/memo.md,"
    echo "    and a claude() shell function in ~/.bashrc and ~/.zshrc (the boot shim)"
    echo "  - Codex: \$CODEX_HOME/hooks.json (else ~/.codex/hooks.json) and four pins in its config.toml"
    echo "  - OpenCode: the AIPass plugin in its config dir (~/.config/opencode)"
    echo "Nothing above is written until you answer. With no terminal and no --yes, the answer is no."
    local answer=""
    read -r -p "Make these changes? [Y/n]: " answer || answer="n"
    case "$answer" in
        ""|y|Y|yes|Yes|YES) return 0 ;;
    esac
    MACHINE_CHANGES="no"
    echo "  Skipped. Until you run $SCRIPT_DIR/setup.sh again and answer yes:"
    echo "    - 'drone' and 'aipass' are not on PATH: use $SCRIPT_DIR/.venv/bin/drone"
    echo "    - projects outside this checkout cannot find it (no AIPASS_HOME in your shell)"
    ACTION_NEEDED+=("Machine changes skipped (shell rc, symlinks): run $SCRIPT_DIR/setup.sh and answer yes to make them")
}
confirm_machine_changes

SYMLINK_SKIPPED=0
LINUX_SYMLINK_DIR=""
# === Gated block start: runs only when MACHINE_CHANGES=yes (not re-indented: heredocs) ===
if [ "$MACHINE_CHANGES" = "yes" ]; then

# --- Provider wiring is not setup's ---
# Claude Code, Codex and OpenCode are wired at the end of `aipass install`, only the one
# the user picks (`aipass provider <name>` later); `aipass doctor --fix` still wires any installed.

# --- Set AIPASS_HOME + PATH so all services work from any project ---
echo ""
echo "Configuring cross-project access ..."

PROFILE="$HOME/.bashrc"

# AIPASS_HOME
if ! grep -qxF "export AIPASS_HOME=\"$SCRIPT_DIR\"" "$PROFILE" 2>/dev/null; then  # this home exactly: a second install moves it
    echo "" >> "$PROFILE"
    echo "# AIPass — cross-project access" >> "$PROFILE"
    echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$PROFILE"
    echo "  AIPASS_HOME added to $PROFILE"
else
    echo "  AIPASS_HOME already $SCRIPT_DIR in $PROFILE"
fi

# ~/.bashrc returns early when not interactive; ~/.profile reaches every login shell (Codex's shell snapshot, cron).
if [ -f "$HOME/.profile" ]; then
    if ! grep -qxF "export AIPASS_HOME=\"$SCRIPT_DIR\"" "$HOME/.profile" 2>/dev/null; then
        echo "" >> "$HOME/.profile"
        echo "# AIPass — cross-project access (login shells, interactive or not)" >> "$HOME/.profile"
        echo "export AIPASS_HOME=\"$SCRIPT_DIR\"" >> "$HOME/.profile"
        echo "  AIPASS_HOME added to $HOME/.profile"
    else
        echo "  AIPASS_HOME already $SCRIPT_DIR in $HOME/.profile"
    fi
fi

# --- Create global symlinks for CLI tools ---
# #660: never SILENTLY hijack a global 'drone'/'aipass' that points at a
# DIFFERENT install. safe_symlink skips a different-target link (loud warning)
# unless --force-symlink; --no-symlink opts out of symlinking entirely.
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
                    ACTION_NEEDED+=("No global '$cmd' command: both symlinks failed. Run: ln -sf $VENV_BIN/$cmd $LOCAL_BIN/$cmd")
                fi
            fi
        fi
    done
fi

fi
# === Gated block end ===

export AIPASS_HOME="$SCRIPT_DIR"

if [ "$SYMLINK_SKIPPED" -gt 0 ]; then
    echo ""
    echo "  NOTE: $SYMLINK_SKIPPED global symlink(s) left untouched (pointed at a different install)."
    echo "        Your existing 'drone'/'aipass' still work. Use --force-symlink to repoint them here."
    ACTION_NEEDED+=("$SYMLINK_SKIPPED global symlink(s) left untouched — rerun with --force-symlink to repoint them here")
fi

# --- Action items for the install report (read by `aipass install --finish`) ---
mkdir -p "$SCRIPT_DIR/.aipass"
{
    if [ ${#ACTION_NEEDED[@]} -gt 0 ]; then printf '%s\n' "${ACTION_NEEDED[@]}"; fi
} > "$SCRIPT_DIR/.aipass/setup_attention.txt"

# --- Result ---
echo ""
if [ "$FAIL" -eq 0 ]; then
    echo "=== Setup complete ==="
    echo ""
    case "$LINUX_SYMLINK_DIR" in
        /usr/local/bin) echo "drone is available globally via /usr/local/bin symlink." ;;
        "") echo "drone has no global symlink: run $SCRIPT_DIR/.venv/bin/drone, or put that directory on PATH." ;;
        *) echo "drone is available via $LINUX_SYMLINK_DIR symlink (on PATH in a new shell)." ;;
    esac
    echo "sentry is accessed via: drone @sentry"
    echo "No venv activation needed for CLI commands."
    echo ""

    print_action_needed

    AIPASS_BIN=""
    if [ -f "$SCRIPT_DIR/.venv/bin/aipass" ]; then
        AIPASS_BIN="$SCRIPT_DIR/.venv/bin/aipass"
    elif command -v aipass &>/dev/null; then
        AIPASS_BIN="$(command -v aipass)"
    fi

    if [ "$RUN_FINISH" = "no" ]; then
        :   # aipass install runs the tail itself
    elif [ -z "$AIPASS_BIN" ]; then
        echo "ERROR: aipass binary not found: no health check, no install report. Open a new terminal and run: aipass install --finish --path $SCRIPT_DIR"
        printf '%s\n' "setup.sh stopped: aipass binary not found; run: aipass install --finish --path $SCRIPT_DIR" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
        exit 1
    elif [ ! -t 0 ] || [ -n "${CI:-}" ]; then
        "$AIPASS_BIN" install --finish --non-interactive --path "$SCRIPT_DIR"
    else
        "$AIPASS_BIN" install --finish --path "$SCRIPT_DIR"
    fi
else
    echo "=== Setup finished with errors ==="
    echo "The venv was created and the package was installed, but one or more"
    echo "CLI entry points failed verification. Check the output above."
    printf '%s\n' "setup.sh stopped: CLI entry points failed verification" > "$SCRIPT_DIR/.aipass/setup_attention.txt"
    exit 1
fi
