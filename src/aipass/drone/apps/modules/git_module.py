# =================== AIPass ====================
# Name: git_module.py
# Description: Git workflow module — PR, status, sync, lock management
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Git workflow module and drone adapter.

Serves as BOTH the drone adapter (registered in _MODULE_REGISTRY) and
the module orchestrator, routing git commands to the appropriate handlers.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import (
    lock_handler,
    status_handler,
    sync_handler,
    diff_handler,
    log_handler,
    commit_handler,
    checkout_handler,
    dev_pr_handler,
    branches_handler,
    delete_branch_handler,
)

DRONE_MODULE = {
    "name": "git",
    "version": "2.0.0",
    "description": "Git workflow — tier-based access, status, diff, log, commit, checkout, sync, lock",
}

_COMMANDS = (
    "status",
    "diff",
    "log",
    "lock",
    "branches",
    "issue",
    "run",
    "workflow",
    "commit",
    "checkout",
    "sync",
    "unlock",
    "dev-pr",
    "delete-branch",
    "merge",
    "smart-sync",
    "fix",
    "pr",
)

_GH_PASSTHROUGH_COMMANDS = ("issue", "run", "workflow")


def _detect_branch_dir() -> tuple[str, Path] | None:
    """Detect caller's branch from CWD via passport lookup.

    Walks up from CWD looking for ``.trinity/passport.json`` and extracts
    the branch name + directory.  Works for any registered branch regardless
    of where it lives on disk (commons, skills, aipass sub-dirs, etc.).
    """
    current = Path.cwd().resolve()
    for _ in range(10):
        passport = current / ".trinity" / "passport.json"
        if passport.exists():
            try:
                with open(passport, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                name = data.get("branch_info", {}).get("branch_name")
                if not name:
                    name = data.get("identity", {}).get("name")
                if name:
                    return name, current
            except Exception as exc:
                logger.warning("Failed to read passport at %s: %s", passport, exc)
                return None
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def handle_command(command: str | None = None, args: list[str] | None = None) -> dict:
    """Route a git command to the appropriate handler.

    Auth is centralized: verify_git_access() is called once at the top,
    before any routing. Global-tier commands pass for all callers;
    owner-tier commands require devpulse.

    Args:
        command: The subcommand (status, diff, log, commit, checkout, etc.).
        args: Optional list of arguments.

    Returns:
        Dict with stdout, stderr, and exit_code.
    """
    if not args:
        if command is None:
            print_introspection()
            return {"stdout": "", "stderr": "", "exit_code": 0}
        args = []
    if command in ("--help", "-h") or (args and args[0] in ("--help", "-h")):
        print_help()
        return {"stdout": "", "stderr": "", "exit_code": 0}

    if command is None:
        print_introspection()
        return {"stdout": "", "stderr": "", "exit_code": 0}

    cmd: str = command
    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_git_access

        caller = verify_git_access(cmd)
    except PermissionError as exc:
        logger.error("git access denied: %s", exc)
        return {"stdout": "", "stderr": str(exc), "exit_code": 1}

    json_handler.log_operation("git_handle_command", {"command": command, "args": args, "caller": caller})

    if command in _GH_PASSTHROUGH_COMMANDS:
        return _handle_gh_passthrough(command, args)
    if command == "status":
        return _handle_status(args)
    if command == "diff":
        return _handle_diff(args)
    if command == "log":
        return _handle_log(args)
    if command == "lock":
        return _handle_lock()
    if command == "branches":
        return _handle_branches()
    if command == "dev-pr":
        return _handle_dev_pr(args)
    if command == "delete-branch":
        return _handle_delete_branch(args)
    if command == "commit":
        return _handle_commit(args)
    if command == "checkout":
        return _handle_checkout(args)
    if command == "sync":
        return _handle_sync(args)
    if command == "unlock":
        return _handle_unlock(args)
    if command == "merge":
        return _handle_merge(args, caller)
    if command == "smart-sync":
        return _handle_smart_sync(caller)
    if command == "fix":
        return _handle_fix(args, caller)
    if command == "pr":
        return _handle_pr(args)

    available = ", ".join(_COMMANDS)
    return {
        "stdout": "",
        "stderr": f"Unknown git command: '{command}'. Available: {available}",
        "exit_code": 1,
    }


def _handle_gh_passthrough(subcommand: str, args: list[str]) -> dict:
    """Pass through to gh CLI for issue, run, and workflow subcommands."""
    cmd = ["gh", subcommand] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        return {
            "stdout": result.stdout,
            "stderr": result.stderr,
            "exit_code": result.returncode,
        }
    except FileNotFoundError as exc:
        logger.warning("gh CLI not found: %s", exc)
        return {
            "stdout": "",
            "stderr": "gh CLI not found. Install: https://cli.github.com/",
            "exit_code": 1,
        }
    except subprocess.TimeoutExpired as exc:
        logger.warning("gh %s timed out: %s", subcommand, exc)
        return {
            "stdout": "",
            "stderr": f"gh {subcommand} timed out after 60s",
            "exit_code": 1,
        }


def _handle_branches() -> dict:
    """Handle the branches subcommand (global tier)."""
    result = branches_handler.list_remote_branches()
    if result["branches"]:
        return {
            "stdout": "\n".join(result["branches"]),
            "stderr": "",
            "exit_code": 0,
        }
    return {"stdout": result["message"], "stderr": "", "exit_code": 0}


def _handle_pr(args: list[str]) -> dict:
    """Handle the pr subcommand — push current branch and create PR to main."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git pr <description>",
            "exit_code": 1,
        }
    description = " ".join(args)
    result = dev_pr_handler.create_branch_pr(description)
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _handle_dev_pr(args: list[str]) -> dict:
    """Handle the dev-pr subcommand (owner tier)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git dev-pr <description>",
            "exit_code": 1,
        }
    description = " ".join(args)
    result = dev_pr_handler.create_dev_pr(description)
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _handle_delete_branch(args: list[str]) -> dict:
    """Handle the delete-branch subcommand (owner tier)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git delete-branch <name>",
            "exit_code": 1,
        }
    result = delete_branch_handler.delete_remote_branch(args[0])
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _handle_merge(args: list[str], caller: str) -> dict:
    """Handle the merge subcommand (owner-tier, auth pre-checked)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git merge <PR#>",
            "exit_code": 1,
        }

    pr_number = args[0]

    try:
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops merge plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    result = merge_pr(pr_number, caller)

    if result["success"]:
        return {
            "stdout": result["message"],
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_smart_sync(caller: str) -> dict:
    """Handle the smart-sync subcommand (owner-tier, auth pre-checked)."""
    try:
        from aipass.drone.apps.plugins.devpulse_ops.sync_plugin import smart_sync
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops sync plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    result = smart_sync(caller)

    if result["success"]:
        return {
            "stdout": result["message"],
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_fix(args: list[str], caller: str) -> dict:
    """Handle the fix subcommand (owner-tier, auth pre-checked)."""
    try:
        from aipass.drone.apps.plugins.devpulse_ops.fix_plugin import fix_git_state
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops fix plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    dry_run = "--dry-run" in (args or [])
    result = fix_git_state(caller, dry_run=dry_run)

    if result["success"]:
        return {
            "stdout": result["message"],
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_status(args: list[str] | None = None) -> dict:
    """Handle the status subcommand (global tier). --all for repo-wide."""
    args = args or []
    show_all = "--all" in args

    detected = _detect_branch_dir()
    if detected is None:
        return {
            "stdout": "",
            "stderr": "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/",
            "exit_code": 1,
        }

    _, branch_dir = detected

    if show_all:
        repo_root = lock_handler.find_repo_root()
        result = status_handler.get_branch_status(repo_root)
        result["message"] = f"{result['total']} file(s) changed in repo"
    else:
        result = status_handler.get_branch_status(branch_dir)

    lines = [result["message"]]
    for f in result["files"]:
        lines.append(f"  {f['status']:>2} {f['path']}")

    return {
        "stdout": "\n".join(lines),
        "stderr": "",
        "exit_code": 0,
    }


def _handle_diff(args: list[str]) -> dict:
    """Handle the diff subcommand (global tier). --staged, --all supported."""
    detected = _detect_branch_dir()
    if detected is None:
        return {
            "stdout": "",
            "stderr": "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/",
            "exit_code": 1,
        }

    _, branch_dir = detected
    staged = "--staged" in args
    show_all = "--all" in args

    target_dir = lock_handler.find_repo_root() if show_all else branch_dir
    result = diff_handler.get_branch_diff(target_dir, staged=staged)

    return {
        "stdout": result["diff"] if result["diff"] else result["message"],
        "stderr": "",
        "exit_code": 0,
    }


def _handle_log(args: list[str]) -> dict:
    """Handle the log subcommand (global tier)."""
    count = 10
    for arg in args:
        try:
            count = int(arg)
            break
        except ValueError as exc:
            logger.warning("Invalid log count argument '%s': %s", arg, exc)
            continue

    result = log_handler.get_git_log(count=count)

    if result["entries"]:
        return {
            "stdout": "\n".join(result["entries"]),
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": result["message"],
        "stderr": "",
        "exit_code": 0,
    }


def _handle_commit(args: list[str]) -> dict:
    """Handle the commit subcommand (owner tier)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git commit <message> [--all | file1 file2 ...]",
            "exit_code": 1,
        }

    all_files = "--all" in args
    clean_args = [a for a in args if a != "--all"]

    if not clean_args:
        return {
            "stdout": "",
            "stderr": "Commit message cannot be empty",
            "exit_code": 1,
        }

    message = clean_args[0]
    files = clean_args[1:] if len(clean_args) > 1 else None

    if not message:
        return {
            "stdout": "",
            "stderr": "Commit message cannot be empty",
            "exit_code": 1,
        }

    return commit_handler.commit_changes(message, all_files=all_files, files=files)


def _handle_checkout(args: list[str]) -> dict:
    """Handle the checkout subcommand (owner tier)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git checkout <main|dev>",
            "exit_code": 1,
        }

    return checkout_handler.checkout_branch(args[0])


def _handle_sync(args: list[str]) -> dict:
    """Handle the sync subcommand (owner tier)."""
    autostash = "--autostash" in args
    result = sync_handler.sync_main(autostash=autostash)

    if result["success"]:
        return {
            "stdout": result["message"],
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_lock() -> dict:
    """Handle the lock subcommand (global tier)."""
    result = lock_handler.check_lock_status()
    return {
        "stdout": json.dumps(result, indent=2),
        "stderr": "",
        "exit_code": 0,
    }


def _handle_unlock(args: list[str]) -> dict:
    """Handle the unlock subcommand (owner tier)."""
    if "--force" not in args:
        return {
            "stdout": "",
            "stderr": "unlock requires --force flag",
            "exit_code": 1,
        }

    result = lock_handler.force_unlock()
    if result["success"]:
        return {
            "stdout": result["message"],
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def get_help(command: str | None = None) -> str:
    """Return help text for the git module.

    Args:
        command: Optional specific subcommand to get help for.

    Returns:
        Help text string.
    """
    if command == "issue":
        return (
            "git issue [args] — Passthrough to gh issue CLI [global]\n  Examples: list, create, view <#>, close <#>\n"
        )
    if command == "run":
        return "git run [args] — Passthrough to gh run CLI [global]\n  Examples: list, view <id>, watch <id>\n"
    if command == "workflow":
        return (
            "git workflow [args] — Passthrough to gh workflow CLI [global]\n  Examples: list, view <name>, run <name>\n"
        )
    if command == "pr":
        return (
            "git pr <description> — Push current branch and create PR to main [owner]\n"
            "  On main: creates temp branch from slug. Otherwise: pushes branch directly. No -u flag.\n"
        )
    if command == "status":
        return "git status [--all] — Show git status filtered to your branch (--all for repo-wide) [global]\n"
    if command == "diff":
        return (
            "git diff [--staged] [--all] — Show git diff filtered to your branch [global]\n"
            "  Options:\n"
            "    --staged   Show staged changes only.\n"
            "    --all      Show all repo changes (not just your branch).\n"
        )
    if command == "log":
        return "git log [count] — Show recent git log entries (default: 10) [global]\n"
    if command == "lock":
        return "git lock — Check current lock status [global]\n  Shows lock holder, age, stale/orphan detection.\n"
    if command == "branches":
        return "git branches — List all remote branches [global]\n"
    if command == "dev-pr":
        return (
            "git dev-pr <description> — Push dev branch and create PR to main [owner]\n"
            "  Description becomes the PR title.\n"
        )
    if command == "delete-branch":
        return (
            "git delete-branch <name> — Delete a remote branch [owner]\n  Protected: main and dev cannot be deleted.\n"
        )
    if command == "commit":
        return (
            "git commit <message> [--all | file1 file2 ...] — Commit changes [owner]\n"
            "  Options:\n"
            "    --all          Stage all repo changes (git add -A) before committing.\n"
            "    file1 file2    Stage only these files before committing.\n"
            "  With no flag or files, commits whatever is already staged.\n"
        )
    if command == "checkout":
        return "git checkout <main|dev> — Switch branches (main or dev only) [owner]\n"
    if command == "sync":
        return (
            "git sync [--autostash] — Checkout main and pull latest changes [owner]\n"
            "  Options:\n"
            "    --autostash   Stash local changes before pull and restore after.\n"
        )
    if command == "unlock":
        return "git unlock --force — Force-release the PR lock [owner]\n"
    if command == "merge":
        return (
            "git merge <PR#> — Merge a PR and sync local main [owner]\n"
            "  Runs gh pr merge --merge --delete-branch, then git pull --rebase.\n"
        )
    if command == "smart-sync":
        return "git smart-sync — Fetch origin and rebase if behind [owner]\n"
    if command == "fix":
        return (
            "git fix [--dry-run] — Detect and fix broken git states [owner]\n"
            "\n"
            "Detected states and actions:\n"
            "  Stuck rebase   → git rebase --abort\n"
            "  Detached HEAD  → git checkout main\n"
            "  Diverged       → git fetch + git merge origin/main\n"
            "  Dirty index    → git reset HEAD\n"
            "\n"
            "Options:\n"
            "  --dry-run   Report without executing fixes.\n"
        )

    return (
        "git — Tier-based git workflow (dev branch model)\n"
        "\n"
        "Global (all branches):\n"
        "  status                 Show git status for your branch\n"
        "  diff [--staged]        Show git diff for your branch\n"
        "  log [count]            Show recent git log (default: 10)\n"
        "  lock                   Check lock status\n"
        "  branches               List remote branches\n"
        "  issue [args]           Passthrough to gh issue\n"
        "  run [args]             Passthrough to gh run\n"
        "  workflow [args]        Passthrough to gh workflow\n"
        "\n"
        "Owner (devpulse only):\n"
        "  commit <msg> [--all | files]  Commit changes (selective or --all)\n"
        "  checkout <main|dev>    Switch branches\n"
        "  pr <desc>              Push current branch and create PR to main\n"
        "  dev-pr <desc>          Push dev and create PR to main\n"
        "  delete-branch <name>   Delete a remote branch\n"
        "  merge <PR#>            Merge a PR\n"
        "  sync [--autostash]     Checkout main and pull\n"
        "  smart-sync             Fetch + rebase if behind\n"
        "  unlock --force         Force-release the PR lock\n"
        "  fix [--dry-run]        Fix broken git states\n"
    )


def get_introspective() -> str:
    """Return introspection text showing connected handlers."""
    return (
        "@git — Tier-based git workflow, dev branch model (v3.0.0)\n"
        "Connected Handlers:\n"
        "  handlers/git/\n"
        "    - lock_handler.py (acquire_lock, release_lock, check_lock_status, force_unlock)\n"
        "    - status_handler.py (get_branch_status — scoped git status)\n"
        "    - diff_handler.py (get_branch_diff — scoped git diff)\n"
        "    - log_handler.py (get_git_log — recent log entries)\n"
        "    - commit_handler.py (commit_changes — selective files, --all, or pre-staged)\n"
        "    - checkout_handler.py (checkout_branch — main/dev only)\n"
        "    - sync_handler.py (sync_main — safe main synchronization)\n"
        "    - dev_pr_handler.py (create_branch_pr, create_dev_pr — PR to main)\n"
        "    - branches_handler.py (list_remote_branches)\n"
        "    - delete_branch_handler.py (delete_remote_branch — protected: main/dev)\n"
        "\n"
        "  plugins/devpulse_ops/\n"
        "    - auth.py (verify_git_access — tier-based authorization)\n"
        "    - merge_plugin.py (merge_pr — merge PR + sync)\n"
        "    - sync_plugin.py (smart_sync — fetch + rebase if behind)\n"
        "    - fix_plugin.py (fix_git_state — detect/fix broken states)\n"
        "\n"
        "  gh passthrough:\n"
        "    - issue, run, workflow → subprocess gh <cmd> [args]\n"
        "\n"
        "Access Tiers: global (status, diff, log, lock, branches, issue, run, workflow) | owner (pr, commit, checkout, dev-pr, delete-branch, sync, unlock, merge, smart-sync, fix)\n"
    )


def print_introspection() -> None:
    """Print introspection (seedgo compliance)."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print(get_introspective())


def print_help() -> None:
    """Print help (seedgo compliance)."""
    try:
        from aipass.cli.apps.modules.display import console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        console = Console()

    console.print(get_help())
