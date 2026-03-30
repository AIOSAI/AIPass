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
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import lock_handler, status_handler, sync_handler, pr_handler

DRONE_MODULE = {
    "name": "git",
    "version": "1.0.0",
    "description": "Git workflow — PR, status, sync, lock management",
}

_COMMANDS = ("pr", "status", "sync", "lock", "unlock", "system-pr", "merge", "smart-sync", "fix")


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

    Args:
        command: The subcommand (pr, status, sync, lock, unlock).
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

    json_handler.log_operation("git_handle_command", {"command": command, "args": args})

    if command == "system-pr":
        return _handle_system_pr(args)
    if command == "merge":
        return _handle_merge(args)
    if command == "smart-sync":
        return _handle_smart_sync(args)
    if command == "fix":
        return _handle_fix(args)
    if command == "pr":
        return _handle_pr(args)
    if command == "status":
        return _handle_status()
    if command == "sync":
        return _handle_sync()
    if command == "lock":
        return _handle_lock()
    if command == "unlock":
        return _handle_unlock(args)

    available = ", ".join(_COMMANDS)
    return {
        "stdout": "",
        "stderr": f"Unknown git command: '{command}'. Available: {available}",
        "exit_code": 1,
    }


def _handle_system_pr(args: list[str]) -> dict:
    """Handle the system-pr subcommand (devpulse-only)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git system-pr <description>",
            "exit_code": 1,
        }

    description = " ".join(args)

    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_caller
        from aipass.drone.apps.plugins.devpulse_ops.pr_plugin import create_system_pr
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    try:
        caller = verify_caller()
    except PermissionError as exc:
        logger.error("system-pr authorization failed: %s", exc)
        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": 1,
        }

    result = create_system_pr(description, caller)

    if result["success"]:
        return {
            "stdout": f"System PR created: {result['pr_url']}\nBranch: {result['feature_branch']}",
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_merge(args: list[str]) -> dict:
    """Handle the merge subcommand (devpulse-only)."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git merge <PR#>",
            "exit_code": 1,
        }

    pr_number = args[0]

    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_caller
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops merge plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    try:
        caller = verify_caller()
    except PermissionError as exc:
        logger.error("merge authorization failed: %s", exc)
        return {
            "stdout": "",
            "stderr": str(exc),
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


def _handle_smart_sync(args: list[str]) -> dict:
    """Handle the smart-sync subcommand (devpulse-only)."""
    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_caller
        from aipass.drone.apps.plugins.devpulse_ops.sync_plugin import smart_sync
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops sync plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    try:
        caller = verify_caller()
    except PermissionError as exc:
        logger.error("smart-sync authorization failed: %s", exc)
        return {
            "stdout": "",
            "stderr": str(exc),
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


def _handle_fix(args: list[str]) -> dict:
    """Handle the fix subcommand (devpulse-only)."""
    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import verify_caller
        from aipass.drone.apps.plugins.devpulse_ops.fix_plugin import fix_git_state
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops fix plugin: %s", exc)
        return {
            "stdout": "",
            "stderr": f"devpulse_ops plugin not available: {exc}",
            "exit_code": 1,
        }

    try:
        caller = verify_caller()
    except PermissionError as exc:
        logger.error("fix authorization failed: %s", exc)
        return {
            "stdout": "",
            "stderr": str(exc),
            "exit_code": 1,
        }

    result = fix_git_state(caller)

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


def _handle_pr(args: list[str]) -> dict:
    """Handle the PR subcommand."""
    if not args:
        return {
            "stdout": "",
            "stderr": "Usage: drone @git pr <description>",
            "exit_code": 1,
        }

    description = " ".join(args)
    detected = _detect_branch_dir()
    if detected is None:
        return {
            "stdout": "",
            "stderr": "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/",
            "exit_code": 1,
        }

    branch_name, branch_dir = detected
    result = pr_handler.create_pr(branch_name, description, branch_dir)

    if result["success"]:
        return {
            "stdout": f"PR created: {result['pr_url']}\nBranch: {result['feature_branch']}",
            "stderr": "",
            "exit_code": 0,
        }
    return {
        "stdout": "",
        "stderr": result["message"],
        "exit_code": 1,
    }


def _handle_status() -> dict:
    """Handle the status subcommand."""
    detected = _detect_branch_dir()
    if detected is None:
        return {
            "stdout": "",
            "stderr": "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/",
            "exit_code": 1,
        }

    _, branch_dir = detected
    result = status_handler.get_branch_status(branch_dir)

    lines = [result["message"]]
    for f in result["files"]:
        lines.append(f"  {f['status']:>2} {f['path']}")

    return {
        "stdout": "\n".join(lines),
        "stderr": "",
        "exit_code": 0,
    }


def _handle_sync() -> dict:
    """Handle the sync subcommand."""
    result = sync_handler.sync_main()

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
    """Handle the lock subcommand (check status)."""
    result = lock_handler.check_lock_status()
    return {
        "stdout": json.dumps(result, indent=2),
        "stderr": "",
        "exit_code": 0,
    }


def _handle_unlock(args: list[str]) -> dict:
    """Handle the unlock subcommand (force only)."""
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
    if command == "pr":
        return (
            "git pr <description> — Create a PR with scoped changes\n"
            "  Stages only files under the caller's branch directory,\n"
            "  creates a feature branch, commits, pushes, and opens a PR.\n"
        )
    if command == "status":
        return (
            "git status — Show git status filtered to your branch directory\n"
        )
    if command == "sync":
        return (
            "git sync — Checkout main and pull latest changes\n"
        )
    if command == "lock":
        return (
            "git lock — Check current lock status\n"
            "  Shows lock holder, age, stale/orphan detection.\n"
        )
    if command == "unlock":
        return (
            "git unlock --force — Force-release the PR lock\n"
            "  Removes .git_pr.lock regardless of holder.\n"
        )
    if command == "system-pr":
        return (
            "git system-pr <description> — Create a system-wide PR (devpulse only)\n"
            "  Stages all tracked changes, creates a disposable feature branch,\n"
            "  and opens a PR. Requires devpulse passport authorization.\n"
        )
    if command == "merge":
        return (
            "git merge <PR#> — Squash-merge a PR and sync local main (devpulse only)\n"
            "  Runs gh pr merge --squash --delete-branch, then git pull --rebase.\n"
        )
    if command == "smart-sync":
        return (
            "git smart-sync — Fetch origin and rebase if behind (devpulse only)\n"
            "  Detects divergence and rebases safely; aborts on conflict.\n"
        )
    if command == "fix":
        return (
            "git fix — Detect and fix common broken git states (devpulse only)\n"
            "  Fixes stuck rebases, detached HEAD, diverged branches, dirty index.\n"
        )

    return (
        "git — Git workflow: PR, status, sync, lock management\n"
        "\n"
        "Commands:\n"
        "  pr <description>       Create a PR with scoped changes\n"
        "  system-pr <desc>       Create a system-wide PR (devpulse only)\n"
        "  merge <PR#>            Squash-merge a PR (devpulse only)\n"
        "  smart-sync             Fetch + rebase if behind (devpulse only)\n"
        "  fix                    Fix broken git states (devpulse only)\n"
        "  status                 Show git status for your branch\n"
        "  sync                   Checkout main and pull\n"
        "  lock                   Check lock status\n"
        "  unlock --force         Force-release the PR lock\n"
    )


def get_introspective() -> str:
    """Return introspection text showing connected handlers."""
    return (
        "@git — Git workflow: PR, status, sync, lock management\n"
        "\n"
        "Connected Handlers:\n"
        "  handlers/git/\n"
        "    - lock_handler.py (acquire_lock, release_lock, check_lock_status, force_unlock)\n"
        "    - status_handler.py (get_branch_status — scoped git status)\n"
        "    - sync_handler.py (sync_main — safe main synchronization)\n"
        "    - pr_handler.py (create_pr — full PR workflow with lockfile)\n"
        "\n"
        "  plugins/devpulse_ops/\n"
        "    - auth.py (verify_caller — passport-based authorization)\n"
        "    - pr_plugin.py (create_system_pr — system-wide PR workflow)\n"
        "    - merge_plugin.py (merge_pr — squash-merge PR + sync)\n"
        "    - sync_plugin.py (smart_sync — fetch + rebase if behind)\n"
        "    - fix_plugin.py (fix_git_state — detect/fix broken states)\n"
        "\n"
        "Commands: pr, system-pr, merge, smart-sync, fix, status, sync, lock, unlock\n"
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
