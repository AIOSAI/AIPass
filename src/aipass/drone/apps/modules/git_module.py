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
import sys
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
    close_pr_handler,
    tag_handler,
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
    "close-pr",
    "merge",
    "smart-sync",
    "fix",
    "pr",
    "prune-temp",
    "tag",
    "tag-list",
)

_GH_PASSTHROUGH_COMMANDS = ("issue", "run", "workflow")

# Count flags whose value lives in the following arg — skipped, not warned about
_LOG_COUNT_FLAGS = ("-n", "--count", "--max-count")


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
    if cmd == "tag" and (not args or args[0] == "--list"):
        cmd = "tag-list"
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
    if command == "close-pr":
        return _handle_close_pr(args)
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
    if command == "prune-temp":
        return _handle_prune_temp()
    if command == "tag":
        return _handle_tag(args)

    available = ", ".join(_COMMANDS)
    return {
        "stdout": "",
        "stderr": f"Unknown git command: '{command}'. Available: {available}",
        "exit_code": 1,
    }


def _handle_tag(args: list[str]) -> dict:
    """Handle the tag subcommand — create/push release tags or list them."""
    if not args or args[0] == "--list":
        result = tag_handler.list_tags()
        if not result["tags"]:
            return {"stdout": result["message"], "stderr": "", "exit_code": 0}
        return {"stdout": "\n".join(result["tags"]), "stderr": "", "exit_code": 0}

    result = tag_handler.tag_release(args[0])
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


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


def _handle_prune_temp() -> dict:
    """Handle the prune-temp subcommand — delete merged citizen/* branches."""
    result = branches_handler.prune_temp_branches()
    lines = [result["message"]]
    for name in result.get("pruned", []):
        lines.append(f"  deleted: {name}")
    return {"stdout": "\n".join(lines), "stderr": "", "exit_code": 0}


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
        return {"stdout": "", "stderr": "Usage: drone @git delete-branch <name>", "exit_code": 1}
    result = delete_branch_handler.delete_remote_branch(args[0])
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _handle_close_pr(args: list[str]) -> dict:
    """Handle the close-pr subcommand (owner tier)."""
    if not args:
        return {"stdout": "", "stderr": "Usage: drone @git close-pr <number>", "exit_code": 1}
    result = close_pr_handler.close_pr(args[0])
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _confirm_merge(pr_number: str, caller: str, confirmed: bool) -> dict | None:
    """Joint-decision gate: merges must never happen accidentally (DPLAN-0256).

    Returns None when the merge may proceed, or a refusal/abort result dict.
    Order matters: an explicit --confirm always passes; otherwise a real
    terminal gets an interactive y/N prompt; headless callers are refused.
    """
    if confirmed:
        json_handler.log_operation("merge_gate", {"pr_number": pr_number, "caller": caller, "path": "--confirm"})
        return None

    if sys.stdin.isatty():
        answer = input(f"Merge PR #{pr_number}? Merges are a joint decision. [y/N] ")
        if answer.strip().lower() in ("y", "yes"):
            json_handler.log_operation("merge_gate", {"pr_number": pr_number, "caller": caller, "path": "tty-yes"})
            return None
        json_handler.log_operation("merge_gate", {"pr_number": pr_number, "caller": caller, "path": "tty-abort"})
        return {"stdout": "", "stderr": f"Merge of PR #{pr_number} aborted at prompt.", "exit_code": 1}

    json_handler.log_operation("merge_gate", {"pr_number": pr_number, "caller": caller, "path": "headless-refused"})
    logger.info("merge gate: refused headless merge of PR #%s by %s (no --confirm)", pr_number, caller)
    return {
        "stdout": "",
        "stderr": (
            f"Merge of PR #{pr_number} requires explicit confirmation — merges are a joint decision.\n"
            f"Re-run once agreed: drone @git merge {pr_number} --confirm"
        ),
        "exit_code": 1,
    }


def _handle_merge(args: list[str], caller: str) -> dict:
    """Handle the merge subcommand (owner-tier, auth pre-checked)."""
    confirmed = "--confirm" in args
    pr_args = [a for a in args if not a.startswith("--")]
    if not pr_args:
        return {"stdout": "", "stderr": "Usage: drone @git merge <PR#> [--confirm]", "exit_code": 1}

    refusal = _confirm_merge(pr_args[0], caller, confirmed)
    if refusal is not None:
        return refusal

    try:
        from aipass.drone.apps.plugins.devpulse_ops.merge_plugin import merge_pr
    except ImportError as exc:
        logger.error("Failed to import devpulse_ops merge plugin: %s", exc)
        return {"stdout": "", "stderr": f"devpulse_ops plugin not available: {exc}", "exit_code": 1}

    result = merge_pr(pr_args[0], caller)
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


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

    branch_name = detected[0]

    if show_all:
        repo_root = lock_handler.find_repo_root()
        result = status_handler.get_branch_status(repo_root)
        result["message"] = f"{result['total']} file(s) changed in repo"
    else:
        result = status_handler.get_branch_status(branch_dir)

    lines = [result["message"]]
    for f in result["files"]:
        lines.append(f"  {f['status']:>2} {f['path']}")

    if not show_all:
        lines.append(f"(showing {branch_name} scope — use --all for full repo)")

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

    branch_name, branch_dir = detected
    staged = "--staged" in args
    show_all = "--all" in args

    target_dir = lock_handler.find_repo_root() if show_all else branch_dir
    result = diff_handler.get_branch_diff(target_dir, staged=staged)

    output = result["diff"] if result["diff"] else result["message"]
    if not show_all:
        output += f"\n(showing {branch_name} scope — use --all for full repo)"

    return {"stdout": output, "stderr": "", "exit_code": 0}


def _handle_log(args: list[str]) -> dict:
    """Handle the log subcommand (global tier).

    Accepts the git idioms: `log 20`, `log -n 20`, and `log -20`.
    """
    count = 10
    for arg in args:
        if arg in _LOG_COUNT_FLAGS:
            continue
        # git shorthand: -20 means 20 commits
        candidate = arg[1:] if arg.startswith("-") and arg[1:].isdigit() else arg
        try:
            count = int(candidate)
            break
        except ValueError as exc:
            logger.warning("Invalid log count argument '%s': %s", arg, exc)
            continue

    if count < 1:
        return {
            "stdout": "",
            "stderr": f"Invalid log count {count}: must be 1 or greater",
            "exit_code": 1,
        }

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
    if "--main-ref" in args:
        result = sync_handler.sync_main_ref()
        if result["success"]:
            return {"stdout": result["message"], "stderr": "", "exit_code": 0}
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}

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
    if command == "close-pr":
        return "git close-pr <number> — Close a GitHub pull request by number [owner]\n"
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
            "git sync [--autostash] [--main-ref] — Sync with origin/main [owner]\n"
            "  On dev: fast-forward to origin/main (stays on dev, no checkout).\n"
            "  On main: pull latest. From other branch: checkout main first.\n"
            "  Refuses if dev has diverged — no silent rewrite.\n"
            "  Options:\n"
            "    --autostash   Stash local changes before sync and restore after.\n"
            "    --main-ref    Update local main ref without checkout (from any branch).\n"
        )
    if command == "unlock":
        return "git unlock --force — Force-release the PR lock [owner]\n"
    if command == "merge":
        return (
            "git merge <PR#> [--confirm] — Merge a PR and sync local main [owner]\n"
            "  Runs gh pr merge --merge --delete-branch, then git pull --rebase.\n"
            "  Joint-decision gate: terminal sessions get a y/N prompt; headless\n"
            "  callers must pass --confirm or the merge is refused.\n"
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
    if command == "tag":
        return (
            "git tag <vX.Y.Z> — Create and push an annotated release tag [owner]\n"
            "git tag --list    — List all tags (newest first) [global]\n"
            "\n"
            "Safety guards:\n"
            "  Version guard   Tags on origin/main only after verifying pyproject.toml\n"
            "                  and __init__.py both match the tag version.\n"
            "  Exists guard    Refuses if tag already exists locally or on remote.\n"
        )

    return (
        "git — Tier-based git workflow (dev branch model)\n"
        "Global (all branches):\n"
        "  status                 Show git status for your branch\n"
        "  diff [--staged]        Show git diff for your branch\n"
        "  log [count]            Show recent git log (default: 10)\n"
        "  lock                   Check lock status\n"
        "  branches               List remote branches\n"
        "  prune-temp             Delete merged citizen/* temp branches\n"
        "  tag --list             List all tags (newest first)\n"
        "  issue [args]           Passthrough to gh issue\n"
        "  run [args]             Passthrough to gh run\n"
        "  workflow [args]        Passthrough to gh workflow\n"
        "Owner (devpulse only):\n"
        "  commit <msg> [--all | files]  Commit changes (selective or --all)\n"
        "  checkout <main|dev>    Switch branches\n"
        "  pr <desc>              Push current branch and create PR to main\n"
        "  dev-pr <desc>          Push dev and create PR to main\n"
        "  delete-branch <name>   Delete a remote branch\n"
        "  close-pr <number>      Close a PR\n"
        "  merge <PR#> [--confirm]  Merge a PR (gated: y/N prompt or --confirm)\n"
        "  sync [--autostash]     Sync with origin/main (FF on dev)\n"
        "  smart-sync             Fetch + rebase if behind\n"
        "  unlock --force         Force-release the PR lock\n"
        "  tag <vX.Y.Z>           Create and push release tag\n"
        "  fix [--dry-run]        Fix broken git states\n"
    )


def get_introspective() -> str:
    """Return introspection text showing connected handlers."""
    return (
        "@git — Tier-based git workflow, dev branch model (v3.0.0)\n"
        "Connected Handlers:\n"
        "  handlers/git/\n"
        "    - lock_handler.py, status_handler.py, diff_handler.py, log_handler.py\n"
        "    - commit_handler.py, checkout_handler.py, sync_handler.py\n"
        "    - dev_pr_handler.py, branches_handler.py, delete_branch_handler.py, close_pr_handler.py\n"
        "  plugins/devpulse_ops/\n"
        "    - auth.py, merge_plugin.py, sync_plugin.py, fix_plugin.py\n"
        "  gh passthrough: issue, run, workflow\n"
        "Tiers: global (status,diff,log,lock,branches,prune-temp,tag --list,issue,run,workflow)"
        " | owner (pr,commit,checkout,dev-pr,delete-branch,close-pr,sync,unlock,merge,smart-sync,fix,tag)\n"
    )


def _get_console():
    try:
        from aipass.cli.apps.modules.display import console

        return console
    except ImportError:
        logger.warning("CLI console not available, using fallback")
        from rich.console import Console

        return Console()


def print_introspection() -> None:
    """Print introspection (seedgo compliance)."""
    c = _get_console()
    c.print()
    c.print("[bold cyan]@git[/bold cyan] [dim]— Tier-based git workflow, dev branch model (v3.0.0)[/dim]")
    c.print("[yellow]Connected Handlers:[/yellow]")
    c.print("  [cyan]handlers/git/[/cyan]")
    c.print(
        "    - [cyan]lock_handler.py[/cyan], [cyan]status_handler.py[/cyan],"
        " [cyan]diff_handler.py[/cyan], [cyan]log_handler.py[/cyan]"
    )
    c.print("    - [cyan]commit_handler.py[/cyan], [cyan]checkout_handler.py[/cyan], [cyan]sync_handler.py[/cyan]")
    c.print(
        "    - [cyan]dev_pr_handler.py[/cyan], [cyan]branches_handler.py[/cyan],"
        " [cyan]delete_branch_handler.py[/cyan], [cyan]close_pr_handler.py[/cyan],"
        " [cyan]tag_handler.py[/cyan]"
    )
    c.print("  [cyan]plugins/devpulse_ops/[/cyan]")
    c.print(
        "    - [cyan]auth.py[/cyan], [cyan]merge_plugin.py[/cyan],"
        " [cyan]sync_plugin.py[/cyan], [cyan]fix_plugin.py[/cyan]"
    )
    c.print("  [dim]gh passthrough: issue, run, workflow[/dim]")
    c.print(
        "[yellow]Tiers:[/yellow] [dim]global[/dim]"
        " [dim](status,diff,log,lock,branches,prune-temp,tag --list,issue,run,workflow)[/dim]"
        " | [dim]owner[/dim]"
        " [dim](pr,commit,checkout,dev-pr,delete-branch,close-pr,sync,unlock,merge,smart-sync,fix,tag)[/dim]"
    )
    c.print()


def print_help() -> None:
    """Print help (seedgo compliance)."""
    _get_console().print(get_help())
