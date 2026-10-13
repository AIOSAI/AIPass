# =================== AIPass ====================
# Name: git_module.py
# Description: Git workflow module — PR, status, sync, lock management
# Version: 1.6.1
# Created: 2026-03-17
# Modified: 2026-10-13
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
import textwrap
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git import (
    lock_handler,
    status_handler,
    sync_handler,
    merge_main_handler,
    diff_handler,
    log_handler,
    tracked_handler,
    export_handler,
    show_handler,
    blame_handler,
    commit_handler,
    checkout_handler,
    dev_pr_handler,
    branches_handler,
    delete_branch_handler,
    close_pr_handler,
    tag_handler,
    remote_handler,
    repo_door,
    help_pages,
)
from aipass.drone.apps.handlers.help_flags import help_topic, wants_help
from aipass.drone.apps.handlers.router_handler import caller_cwd
from aipass.drone.apps.handlers.json_flags import strip_json_flag, wants_json

DRONE_MODULE = {
    "name": "git",
    "version": "2.0.0",
    "description": "Git workflow — tier-based access, status, diff, log, commit, checkout, sync, lock",
}

_COMMANDS = (
    "status",
    "diff",
    "log",
    "show",
    "blame",
    "tracked",
    "export",
    "remote",
    "lock",
    "branches",
    "issue",
    "run",
    "workflow",
    "commit",
    "checkout",
    "sync",
    "merge-main",
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
    "issue-write",
    "run-write",
    "workflow-write",
)

_GH_PASSTHROUGH_COMMANDS = ("issue", "run", "workflow")

# gh's default `issue view` render asks GitHub for repository.issue.projectCards
# — a Projects-classic field the API now rejects outright, so the call returns the
# deprecation notice and no issue at all.  Rendering from pinned --json fields never
# requests it.  Callers who already chose a rendering keep their own invocation.
_ISSUE_VIEW_RENDER_FLAGS = ("--json", "-q", "--jq", "-t", "--template", "-w", "--web")
_ISSUE_VIEW_COMMENT_FLAGS = ("-c", "--comments")

_ISSUE_VIEW_FIELDS = "number,title,state,author,createdAt,url,labels,body"

_ISSUE_VIEW_TEMPLATE = (
    "#{{.number}} {{.title}}\n"
    "{{.state}} · opened by {{.author.login}} · {{.createdAt}}"
    "{{range .labels}} [{{.name}}]{{end}}\n"
    "{{.url}}\n\n"
    "{{.body}}\n"
)

_ISSUE_VIEW_COMMENTS_TEMPLATE = _ISSUE_VIEW_TEMPLATE + (
    "{{range .comments}}\n--- {{.author.login}} · {{.createdAt}}\n\n{{.body}}\n{{end}}"
)

# `run view --log` / `--log-failed` in gh 2.45 (this machine's packaged gh) finds
# each step's log by file name inside the run's log archive. GitHub's archive now
# holds job-level files only — measured on run 34730939542: `0_seedgo-audit.txt`,
# `1_test (3.10).txt` and no per-step files — so gh matches nothing, prints nothing
# and exits 0. An empty answer with a clean exit is read from the jobs API instead.
_RUN_LOG_FLAGS = ("--log", "--log-failed")
_FAILED_CONCLUSIONS = ("failure", "timed_out")
_RUN_VIEW_VALUE_FLAGS = ("-R", "--repo", "-j", "--job", "-a", "--attempt", "-q", "--jq", "-t", "--template", "--json")
_JOB_ROW_JQ = '"\\(.id)\\t\\(.conclusion)\\t\\(.name)"'
_GH_TIMEOUT = 60

# The flags diff takes; any other flag before `--` is refused by name
_DIFF_FLAGS = ("--staged", "--all", "--stat")

# Count flags whose value lives in the following arg — skipped, not warned about
_LOG_COUNT_FLAGS = ("-n", "--count", "--max-count")


def _detect_branch_dir() -> tuple[str, Path] | None:
    """Detect caller's branch from CWD via passport lookup.

    Walks up from CWD looking for ``.trinity/passport.json`` and extracts
    the branch name + directory.  Works for any registered branch regardless
    of where it lives on disk (commons, skills, aipass sub-dirs, etc.).

    Returns None when the process has no CWD — this detects the branch from
    LOCATION, and there is nothing to detect from. Identity assigned at spawn
    is a different question, answered elsewhere and unaffected.

    Raises ValueError when a passport is found but cannot be read: a corrupt
    passport is a failure to report, never "not inside a branch".
    """
    cwd = caller_cwd()
    if cwd is None:
        return None
    current = cwd.resolve()
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
                raise ValueError(f"Unreadable passport at {passport}: {exc}") from exc
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
    if wants_help(command, args):
        print_help(help_topic(command, args))
        return {"stdout": "", "stderr": "", "exit_code": 0}

    if command is None:
        print_introspection()
        return {"stdout": "", "stderr": "", "exit_code": 0}

    # The external-repo door is decided BEFORE the tier gate. Its question is not
    # "does this caller own the repo it stands in" but "does this caller hold the
    # admin grant", and a flag aimed at another repo must never fall through and
    # run the verb in the standing one. The gh passthroughs are not door verbs:
    # their --repo OWNER/NAME is gh's own flag and reaches gh untouched, as ever.
    if command not in _GH_PASSTHROUGH_COMMANDS:
        repo_flag = repo_door.extract_repo_flag(args)
        if repo_flag.present:
            return _handle_repo_door(command, repo_flag)

    cmd: str = command
    if cmd == "tag" and (not args or args[0] == "--list"):
        cmd = "tag-list"
    from aipass.drone.apps.plugins.devpulse_ops.auth import GH_SUBCOMMANDS, gh_access_key, verify_git_access

    if command in _GH_PASSTHROUGH_COMMANDS:
        # Reads stay global, writes ask the owner tier, and an unknown subcommand
        # is refused here, before the gate and before gh (DPLAN-0356 leg 3).
        gh_key = gh_access_key(command, args)
        if gh_key is None:
            table = GH_SUBCOMMANDS[command]
            message = (
                f"Unknown subcommand for '{command}': '{args[0]}'. "
                f"Reads: {', '.join(table['read'])}. Owner only: {', '.join(table['write'])}."
            )
            return {"stdout": "", "stderr": message, "exit_code": 1}
        cmd = gh_key
    try:
        caller = verify_git_access(cmd)
    except PermissionError as exc:
        # WARNING, not ERROR: auth.py already logged this same denial with the
        # authoritative severity. Re-logging at ERROR made one refusal surface as
        # two ERROR fingerprints 0.12s apart, so suppressing one left the twin loud.
        logger.warning("git access denied: %s", exc)
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
    if command == "show":
        return _handle_show(args)
    if command == "blame":
        return _handle_blame(args)
    if command == "tracked":
        return _handle_tracked(args)
    if command == "export":
        return _handle_export(args)
    if command == "remote":
        return _handle_remote(args)
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
    if command == "merge-main":
        return _handle_merge_main(args)
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


def _handle_tag(args: list[str], repo_root: Path | None = None) -> dict:
    """Handle the tag subcommand — create/push release tags or list them."""
    if not args or args[0] == "--list":
        result = tag_handler.list_tags(repo_root=repo_root)
        if not result["tags"]:
            return {"stdout": result["message"], "stderr": "", "exit_code": 0}
        return {"stdout": "\n".join(result["tags"]), "stderr": "", "exit_code": 0}

    result = tag_handler.tag_release(args[0], repo_root=repo_root)
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _refuse_repo_door(verdict: repo_door.AdminVerdict, flag: repo_door.RepoFlag, verb: str, reason: str) -> dict:
    """Record a refused door use and return the refusal, printed exactly."""
    logger.warning("git repo door refused '%s' --repo %s: %s", verb, flag.path, reason)
    repo_door.record_use(
        caller=verdict.caller,
        verb=verb,
        args=flag.args,
        requested=flag.path,
        repo=flag.path,
        head_before="",
        head_after="",
        exit_code=1,
        outcome=repo_door.OUTCOME_REFUSED,
        reason=reason,
    )
    return {"stdout": "", "stderr": reason, "exit_code": 1}


def _handle_repo_door(command: str, flag: repo_door.RepoFlag) -> dict:
    """Run one verb in another repo through the admin seat's door (DPLAN-0344).

    The order is the contract. WHO first, so a seat without the grant learns
    nothing about the path it named; then the flag's own shape; then WHICH verb;
    then WHICH repo. ``verify_git_access`` is not consulted: its owner tier
    answers for the repo the caller stands in, and the admin grant is the
    stronger check for a repo they do not. Every exit writes one record.
    """
    verb = "tag-list" if command == "tag" and (not flag.args or flag.args[0] == "--list") else command
    verdict = repo_door.admin_verdict()
    if not verdict.granted:
        return _refuse_repo_door(verdict, flag, verb, verdict.refusal)
    if flag.error:
        return _refuse_repo_door(verdict, flag, verb, flag.error)
    if command not in repo_door.DOOR_VERBS:
        return _refuse_repo_door(verdict, flag, verb, repo_door.REFUSE_VERB.format(verb=command))
    target = repo_door.resolve_repo(flag.path, lock_handler.find_repo_root())
    if target.root is None:
        return _refuse_repo_door(verdict, flag, verb, target.refusal)

    head_before = repo_door.head_sha(target.root)
    result = _run_door_verb(command, flag.args, target.root)
    repo_door.record_use(
        caller=verdict.caller,
        verb=verb,
        args=flag.args,
        requested=flag.path,
        repo=target.root,
        head_before=head_before,
        head_after=repo_door.head_sha(target.root),
        exit_code=result["exit_code"],
        outcome=repo_door.OUTCOME_RAN,
        reason="",
    )
    return result


def _run_door_verb(command: str, args: list[str], repo_root: Path) -> dict:
    """Run a door verb through the same handler it uses at home, pointed at *repo_root*."""
    if command == "status":
        return _handle_status(args, repo_root=repo_root)
    if command == "diff":
        return _handle_diff(args, repo_root=repo_root)
    if command == "log":
        return _handle_log(args, repo_root=repo_root)
    if command == "commit":
        return _handle_commit(args, repo_root=repo_root)
    if command == "tag":
        return _handle_tag(args, repo_root=repo_root)
    if command in ("fetch", "sync", "merge-upstream") and args:
        return {"stdout": "", "stderr": repo_door.REFUSE_NO_ARGS.format(verb=command), "exit_code": 1}
    if command == "fetch":
        return repo_door.fetch_report(repo_root)
    if command == "sync":
        return repo_door.sync_fast_forward(repo_root)
    if command == "merge-upstream":
        return repo_door.merge_upstream(repo_root)
    if args:
        return {"stdout": "", "stderr": repo_door.REFUSE_PUSH_ARGS, "exit_code": 1}
    return repo_door.push_current_branch(repo_root)


def _rewrite_issue_view(args: list[str]) -> list[str]:
    """Render ``issue view`` from pinned JSON fields instead of gh's default view.

    Returns args untouched for every other issue subcommand, and for callers who
    already picked a rendering — their flags conflict with ``--json`` and their
    choice is theirs to keep.
    """
    if not args or args[0] != "view":
        return args
    if any(arg in _ISSUE_VIEW_RENDER_FLAGS for arg in args):
        return args

    wants_comments = any(arg in _ISSUE_VIEW_COMMENT_FLAGS for arg in args)
    kept = [arg for arg in args if arg not in _ISSUE_VIEW_COMMENT_FLAGS]
    fields = _ISSUE_VIEW_FIELDS + ",comments" if wants_comments else _ISSUE_VIEW_FIELDS
    template = _ISSUE_VIEW_COMMENTS_TEMPLATE if wants_comments else _ISSUE_VIEW_TEMPLATE
    return kept + ["--json", fields, "--template", template]


def _flag_value(args: list[str], names: tuple[str, ...]) -> str | None:
    """The value of the first of *names* in *args*, written `--name value` or `--name=value`."""
    for index, arg in enumerate(args):
        if arg in names and index + 1 < len(args):
            return args[index + 1]
        for name in names:
            if name.startswith("--") and arg.startswith(name + "="):
                return arg[len(name) + 1 :]
    return None


def _run_view_id(args: list[str]) -> str | None:
    """The run id in ``run view`` args: the first bare number that is not a flag's value."""
    skip_next = False
    for arg in args[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg in _RUN_VIEW_VALUE_FLAGS:
            skip_next = True
            continue
        if arg.isdigit():
            return arg
    return None


def _run_log_via_job_api(args: list[str]) -> dict:
    """Answer ``run view --log`` / ``--log-failed`` from the jobs API after gh printed nothing.

    The API has no per-step slice, so each job's log comes back whole, every line
    led by its job name and a tab — the column gh's own rendering leads with. For
    --log-failed that is the full log of each failed job, and the notice on stderr
    says so rather than letting it pass for gh's step-filtered view.
    """
    failed_only = "--log-failed" in args
    named_repo = _flag_value(args, ("-R", "--repo"))
    api = f"repos/{named_repo}" if named_repo else "repos/{owner}/{repo}"
    job_id = _flag_value(args, ("-j", "--job"))
    run_id = _run_view_id(args)
    attempt = _flag_value(args, ("-a", "--attempt"))

    if job_id:
        listing_argv = ["gh", "api", f"{api}/actions/jobs/{job_id}", "--jq", _JOB_ROW_JQ]
    elif run_id:
        runs = f"{api}/actions/runs/{run_id}" + (f"/attempts/{attempt}" if attempt else "")
        listing_argv = ["gh", "api", "--paginate", f"{runs}/jobs", "--jq", f".jobs[] | {_JOB_ROW_JQ}"]
    else:
        return {
            "stdout": "",
            "stderr": "gh printed no log, and no run or job id was given to read one.",
            "exit_code": 1,
        }

    shown = "the full log of each failed job" if failed_only else "each job's full log"
    notice = (
        "gh printed no log: this run's log archive holds job-level files only, so gh's per-step "
        f"matching finds nothing. Showing {shown} from the jobs API instead."
    )
    lines: list[str] = []
    errors: list[str] = []
    try:
        listing = subprocess.run(listing_argv, capture_output=True, text=True, timeout=_GH_TIMEOUT)
        if listing.returncode != 0:
            return {"stdout": "", "stderr": f"{notice}\nThe jobs API refused: {listing.stderr.strip()}", "exit_code": 1}
        jobs = [row.split("\t", 2) for row in listing.stdout.splitlines() if row.count("\t") >= 2]
        if failed_only:
            jobs = [job for job in jobs if job[1] in _FAILED_CONCLUSIONS]
        for number, _conclusion, name in jobs:
            log = subprocess.run(
                ["gh", "api", f"{api}/actions/jobs/{number}/logs"],
                capture_output=True,
                text=True,
                timeout=_GH_TIMEOUT,
            )
            if log.returncode != 0:
                errors.append(f"job {number} ({name}): {log.stderr.strip()}")
                continue
            lines.extend(f"{name}\t{line}" for line in log.stdout.splitlines())
    except (OSError, subprocess.SubprocessError) as exc:
        logger.warning("run log fallback through the jobs API failed: %s", exc)
        return {"stdout": "", "stderr": f"{notice}\nThe jobs API call failed: {exc}", "exit_code": 1}

    if not jobs:
        notice += " No failed job in this run." if failed_only else " The run lists no jobs."
    return {"stdout": "\n".join(lines), "stderr": "\n".join([notice, *errors]), "exit_code": 1 if errors else 0}


def _handle_gh_passthrough(subcommand: str, args: list[str]) -> dict:
    """Pass through to gh CLI for issue, run, and workflow subcommands."""
    if subcommand == "issue":
        args = _rewrite_issue_view(args)
    cmd = ["gh", subcommand] + args
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if (
            subcommand == "run"
            and args[:1] == ["view"]
            and any(arg in _RUN_LOG_FLAGS for arg in args)
            and result.returncode == 0
            and not result.stdout.strip()
        ):
            return _run_log_via_job_api(args)
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


def _terminal_answer(prompt: str) -> str | None:
    """The typed answer to *prompt* on a real terminal, or None when stdin is not one.

    Its body is the two calls the merge gate made inline. It has a name of its
    own for the tests: they hand the gate a terminal through this name instead of
    replacing sys.stdin for the whole process (drone's decision, DPLAN-0354 leg 5).
    """
    if not sys.stdin.isatty():
        return None
    return input(prompt)


def _confirm_merge(pr_number: str, caller: str, confirmed: bool) -> dict | None:
    """Joint-decision gate: merges must never happen accidentally (DPLAN-0256).

    Returns None when the merge may proceed, or a refusal/abort result dict.
    Order matters: an explicit --confirm always passes; otherwise a real
    terminal gets an interactive y/N prompt; headless callers are refused.
    """
    if confirmed:
        json_handler.log_operation("merge_gate", {"pr_number": pr_number, "caller": caller, "path": "--confirm"})
        return None

    answer = _terminal_answer(f"Merge PR #{pr_number}? Merges are a joint decision. [y/N] ")
    if answer is not None:
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


def _json_document(payload: dict, *, ok: bool) -> dict:
    """Render *payload* as the one JSON document a machine caller reads.

    Args:
        payload: The document body. ``ok`` is stamped into it here so every
            machine answer on every read door carries the same verdict field.
        ok: Whether the door answered the question.

    Returns:
        A routing result whose stdout is the document. A refusal travels on
        stdout too — a caller that asked for JSON must be able to parse what
        comes back, including the reason it failed — while the exit code still
        goes non-zero so a shell script reading only that is told the truth.
    """
    return {
        "stdout": json.dumps({"ok": ok, **payload}, indent=2),
        "stderr": "",
        "exit_code": 0 if ok else 1,
    }


def _handle_status(args: list[str] | None = None, repo_root: Path | None = None) -> dict:
    """Handle the status subcommand (global tier). --all for repo-wide, --json for machines.

    *repo_root* is set only by the external-repo door, which names the repo
    outright: there is no branch to detect and nothing narrower than the whole
    repo to scope to.
    """
    args = args or []
    as_json = wants_json(args)
    args = strip_json_flag(args)
    show_all = "--all" in args or repo_root is not None
    counts: dict | None = None

    if repo_root is not None:
        branch_name = repo_root.name
        result = status_handler.get_branch_status(repo_root, repo_root=repo_root)
        if result.get("ok", True):
            result["message"] = f"{result['total']} file(s) changed in {repo_root}"
    else:
        try:
            detected = _detect_branch_dir()
            message = "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/"
        except ValueError as exc:
            detected, message = None, str(exc)
        if detected is None:
            if as_json:
                # This refusal fires BEFORE the branch is known, which is how a
                # machine caller ends up parsing a bare sentence. Every exit from a
                # --json call is a document, early ones included.
                return _json_document(
                    {"branch": "", "scope": "branch", "files": [], "total": 0, "message": message}, ok=False
                )
            return {"stdout": "", "stderr": message, "exit_code": 1}

        branch_name, branch_dir = detected

        if show_all:
            standing_root = lock_handler.find_repo_root()
            result = status_handler.get_branch_status(standing_root)
            if result.get("ok", True):
                # only reword the success message — an error message must survive verbatim
                result["message"] = f"{result['total']} file(s) changed in repo"
                # The twin of `git rev-list --count` both ways: how far this branch
                # is from its origin twin, as of the last fetch (DPLAN-0356).
                counts = status_handler.get_ahead_behind(standing_root)
                if not counts["ok"]:
                    result = {**result, "ok": False, "message": counts["message"]}
        else:
            result = status_handler.get_branch_status(branch_dir)

    if as_json:
        # The scope footer and the header sentence are prose. A machine caller
        # asked for facts, so it gets the scope as a field instead of a line it
        # would have to recognise and strip.
        document = {
            "branch": branch_name,
            "scope": "repo" if show_all else "branch",
            "files": result["files"],
            "total": result["total"],
            "message": result["message"],
        }
        if counts is not None:
            document.update(upstream=counts["upstream"], ahead=counts["ahead"], behind=counts["behind"])
        return _json_document(document, ok=result.get("ok", True))

    if not result.get("ok", True):
        # a failed git status must FAIL the command — exit 0 here false-greened
        # scripts and CI into reading an error as a clean tree
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}

    lines = [result["message"]]
    if counts is not None:
        lines.append(counts["message"])
    for f in result["files"]:
        # STRIPPED FOR THE SCREEN ONLY. The handler now reports porcelain's two
        # columns verbatim; this rendering has always shown one right-aligned
        # letter and keeps doing so, byte for byte, so every current reader of
        # this surface is untouched. Machine callers take --json and get both.
        lines.append(f"  {f['status'].strip():>2} {f['path']}")

    if not show_all:
        lines.append(f"(showing {branch_name} scope — use --all for full repo)")

    return {
        "stdout": "\n".join(lines),
        "stderr": "",
        "exit_code": 0,
    }


def _resolve_diff_paths(
    path_tokens: list[tuple[str, bool]], root: Path, cwd: Path | None
) -> tuple[list[str], str | None]:
    """The diff's paths made absolute, or the first token that names no path (then the paths are partial)."""
    paths: list[str] = []
    for token, must_exist in path_tokens:
        resolved = log_handler.resolve_log_path(token, root, cwd, must_exist)
        if resolved is None:
            return paths, token
        paths.append(resolved)
    return paths, None


def _handle_diff(args: list[str], repo_root: Path | None = None) -> dict:
    """Handle the diff subcommand (global tier): `diff [--staged] [--stat] [--all] [path ...]`.

    Paths narrow the diff to those files and are read against the caller's
    directory, then the repo root, as log reads them; one that no longer
    exists goes after `--`. --stat prints git's summary in place of the patch.
    Any other flag fails by name. *repo_root* is set only by the external-repo
    door: the whole named repo, paths read against it alone.
    """
    flags: set[str] = set()
    path_tokens: list[tuple[str, bool]] = []
    after_separator = False
    for arg in args:
        if after_separator or arg == "--":
            path_tokens += [(arg, False)] if after_separator else []
            after_separator = True
            continue
        if arg in _DIFF_FLAGS:
            flags.add(arg)
            continue
        if arg.startswith("-"):
            return {"stdout": "", "stderr": f"Unknown argument for 'diff': {arg}", "exit_code": 1}
        path_tokens.append((arg, True))
    staged = "--staged" in flags
    stat = "--stat" in flags
    scope_note = ""
    if path_tokens:
        root = repo_root if repo_root is not None else lock_handler.find_repo_root()
        cwd = None if repo_root is not None else caller_cwd()
        paths, unknown = _resolve_diff_paths(path_tokens, root, cwd)
        if unknown is not None:
            message = (
                f"Unknown argument for 'diff': {unknown} (no such path; a path that no longer exists goes after --)"
            )
            logger.warning("git diff refused unknown argument '%s'", unknown)
            return {"stdout": "", "stderr": message, "exit_code": 1}
        result = diff_handler.get_branch_diff(root, staged=staged, repo_root=root, paths=paths, stat=stat)
    elif repo_root is not None:
        result = diff_handler.get_branch_diff(repo_root, staged=staged, repo_root=repo_root, stat=stat)
    else:
        try:
            detected = _detect_branch_dir()
            message = "Cannot detect branch directory from CWD. Run from within src/aipass/<branch>/"
        except ValueError as exc:
            detected, message = None, str(exc)
        if detected is None:
            return {"stdout": "", "stderr": message, "exit_code": 1}

        branch_name, branch_dir = detected
        show_all = "--all" in flags
        target_dir = lock_handler.find_repo_root() if show_all else branch_dir
        result = diff_handler.get_branch_diff(target_dir, staged=staged, stat=stat)
        if not show_all:
            scope_note = f"\n(showing {branch_name} scope — use --all for full repo)"

    if not result.get("ok", True):
        # same false-green trap as _handle_status — a git failure must exit non-zero
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}

    output = result["diff"] if result["diff"] else result["message"]
    return {"stdout": output + scope_note, "stderr": "", "exit_code": 0}


def _split_log_entry(entry: str) -> dict:
    """Split one ``--oneline`` row into its sha and its subject.

    Args:
        entry: A row as git prints it — a short sha, a space, the subject.

    Returns:
        {sha, subject}. Split ONCE on the first space: a subject contains
        spaces of its own, and splitting on all of them is how a consumer ends
        up rebuilding the message it was handed. A row with no subject keeps
        its sha and reports an empty one rather than vanishing.
    """
    sha, _, subject = entry.strip().partition(" ")
    return {"sha": sha, "subject": subject.strip()}


def _handle_log(args: list[str], repo_root: Path | None = None) -> dict:
    """Handle the log subcommand (global tier).

    Accepts the git idioms: `log 20`, `log -n 20`, and `log -20`, and paths that
    keep only the commits touching them: `log src/aipass/drone`, or after `--`
    for a path that no longer exists (`log -n 5 -- old/file.py`). A path is read
    against the caller's directory, then the repo root. One range of commits,
    `log origin/dev..HEAD`, lists every commit in it unless a count caps it;
    each side must name a commit. *repo_root* is set only by the external-repo
    door, where paths are read against that repo alone.
    """
    as_json = wants_json(args)
    # Stripped BEFORE the count scan below: left in, `--json` reaches int(),
    # fails, and logs a bogus "Invalid log count argument" on every call.
    args = strip_json_flag(args)
    count: int | None = None
    path_tokens: list[tuple[str, bool]] = []
    after_separator = False
    for arg in args:
        if after_separator:
            path_tokens.append((arg, False))
            continue
        if arg == "--":
            after_separator = True
            continue
        if arg in _LOG_COUNT_FLAGS:
            continue
        # git shorthand: -20 means 20 commits
        candidate = arg[1:] if arg.startswith("-") and arg[1:].isdigit() else arg
        if count is None and candidate.isdigit():
            count = int(candidate)
            continue
        path_tokens.append((arg, True))

    root = repo_root if repo_root is not None else lock_handler.find_repo_root()
    rev_range: str | None = None
    for argument, must_exist in path_tokens:
        if must_exist and ".." in argument and log_handler.is_commit_range(argument, root):
            rev_range = argument
            path_tokens.remove((argument, must_exist))
            break

    if count is None and rev_range is None:
        count = 10
    if count is not None and count < 1:
        message = f"Invalid log count {count}: must be 1 or greater"
        if as_json:
            return _json_document({"commits": [], "count": 0, "message": message}, ok=False)
        return {"stdout": "", "stderr": message, "exit_code": 1}

    paths: list[str] = []
    if path_tokens:
        cwd = None if repo_root is not None else caller_cwd()
        for argument, must_exist in path_tokens:
            resolved = log_handler.resolve_log_path(argument, root, cwd, must_exist)
            if resolved is None:
                # The owner's standing ruling: an unknown argument FAILS by name.
                # It once logged a WARNING and carried on with the default 10, so
                # `log not_a_real_count` printed what plain `log` prints, exit 0.
                message = (
                    f"Unknown argument for 'log': {argument} (not a count, not a range of commits, and no such path; "
                    "a path that no longer exists goes after --)"
                )
                logger.warning("git log refused unknown argument '%s'", argument)
                if as_json:
                    return _json_document({"commits": [], "count": 0, "message": message}, ok=False)
                return {"stdout": "", "stderr": message, "exit_code": 1}
            paths.append(resolved)

    if rev_range is None:
        result = log_handler.get_git_log(count=count, repo_root=repo_root, paths=paths or None)
    else:
        result = log_handler.get_git_log(count=count, repo_root=root, paths=paths or None, rev_range=rev_range)

    if not result["success"]:
        if as_json:
            return _json_document({"commits": [], "count": 0, "message": result["message"]}, ok=False)
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}

    if as_json:
        return _json_document(
            {
                "commits": [_split_log_entry(entry) for entry in result["entries"]],
                "count": result["count"],
                "message": result["message"],
            },
            ok=True,
        )

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


def _handle_show(args: list[str]) -> dict:
    """Handle the show subcommand (global tier).

    `show <ref>` shows the commit; `show <ref> <path>` reads that file AT the
    commit. Repo-wide by design — see show_handler for why it is not scoped to
    the caller's own branch.
    """
    as_json = wants_json(args)
    # Stripped BEFORE args[0] is read as the ref: left in, `show --json HEAD`
    # hands `--json` to show_object, which refuses it as a flag-shaped ref.
    args = strip_json_flag(args)

    if not args:
        message = "Usage: drone @git show <ref> [path]"
        if as_json:
            return _json_document({"ref": "", "path": None, "content": "", "message": message}, ok=False)
        return {"stdout": "", "stderr": message, "exit_code": 1}

    ref = args[0]
    path = args[1] if len(args) > 1 else None
    result = show_handler.show_object(ref, path)

    if as_json:
        return _json_document(
            {"ref": ref, "path": path, "content": result["content"], "message": result["message"]},
            ok=result["success"],
        )

    if result["success"]:
        return {"stdout": result["content"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


def _handle_blame(args: list[str]) -> dict:
    """Handle the blame subcommand (global tier): `blame <file> [-L START,END]`.

    The file is read against the caller's directory, then the repo root, the
    same way log reads its paths. Repo-wide, like show (see blame_handler).
    """
    usage = "Usage: drone @git blame <file> [-L START,END]"
    file_token: str | None = None
    line_range: tuple[int, int] | None = None
    index = 0
    while index < len(args):
        arg = args[index]
        if arg == "-L":
            spec = args[index + 1] if index + 1 < len(args) else ""
            line_range = blame_handler.parse_line_range(spec)
            if line_range is None:
                message = f"Invalid line range for 'blame': '{spec}' (use -L START,END, e.g. -L 10,40)"
                return {"stdout": "", "stderr": message, "exit_code": 1}
            index += 2
            continue
        if file_token is None and not arg.startswith("-"):
            file_token = arg
            index += 1
            continue
        return {"stdout": "", "stderr": f"Unknown argument for 'blame': {arg}\n{usage}", "exit_code": 1}

    if file_token is None:
        return {"stdout": "", "stderr": usage, "exit_code": 1}

    root = lock_handler.find_repo_root()
    resolved = log_handler.resolve_log_path(file_token, root, caller_cwd(), True)
    if resolved is None:
        return {"stdout": "", "stderr": f"No such file for 'blame': {file_token}", "exit_code": 1}

    result = blame_handler.get_git_blame(resolved, line_range, repo_root=root)
    if not result["success"]:
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}
    return {"stdout": "\n".join(result["lines"]), "stderr": "", "exit_code": 0}


def _handle_tracked(args: list[str]) -> dict:
    """Handle the tracked subcommand (global tier): `tracked <path ...>`, one row per path.

    The twin of `git ls-files` plus `git check-ignore`. Each path is read
    against the caller's directory, then the repo root, as log reads them.
    """
    if not args:
        return {"stdout": "", "stderr": "Usage: drone @git tracked <path ...>", "exit_code": 1}
    flag = next((arg for arg in args if arg.startswith("-")), None)
    if flag is not None:
        return {"stdout": "", "stderr": f"Unknown argument for 'tracked': {flag}", "exit_code": 1}
    result = tracked_handler.classify(lock_handler.find_repo_root(), caller_cwd(), args)
    if not result["ok"]:
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}
    rows = [f"{state:<10} {path}" for state, path in result["rows"]]
    return {"stdout": "\n".join(rows), "stderr": "", "exit_code": 0}


def _handle_export(args: list[str]) -> dict:
    """Handle the export subcommand (global tier): `export <ref> <dir>`, the tracked tree at ref into dir.

    The twin of `git archive | tar -x`. A relative dir is read against the
    caller's directory; export_handler decides whether it may be written.
    """
    if len(args) != 2:
        return {"stdout": "", "stderr": "Usage: drone @git export <ref> <dir>", "exit_code": 1}
    ref, dir_token = args
    dest = Path(dir_token)
    cwd = caller_cwd()
    if not dest.is_absolute():
        if cwd is None:
            message = f"export refused: {dir_token} is relative and there is no cwd to read it against"
            return {"stdout": "", "stderr": message, "exit_code": 1}
        dest = cwd / dest
    try:
        detected = _detect_branch_dir()
    except ValueError as exc:
        return {"stdout": "", "stderr": str(exc), "exit_code": 1}
    docs_local = detected[1] / "docs.local" if detected is not None else None
    result = export_handler.export_tree(lock_handler.find_repo_root(), ref, dest, docs_local)
    if not result["success"]:
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}
    return {"stdout": result["message"], "stderr": "", "exit_code": 0}


def _handle_remote(args: list[str]) -> dict:
    """Handle the remote subcommand (global tier) — where this repository points.

    Read-only: it lists what is configured and changes nothing. Credentials are
    redacted in the handler, before any value reaches this rendering.
    """
    as_json = wants_json(args)
    result = remote_handler.list_remotes()

    if as_json:
        return _json_document(
            {"remotes": result["remotes"], "count": result["count"], "message": result["message"]},
            ok=result["ok"],
        )

    if not result["ok"]:
        return {"stdout": "", "stderr": result["message"], "exit_code": 1}

    if not result["remotes"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}

    lines = [result["message"]]
    for entry in result["remotes"]:
        lines.append(f"  {entry['name']}  {entry['fetch']} (fetch)")
        # Push is printed only when it DIFFERS. Two identical rows is what git
        # itself prints, and it reads as two remotes at a glance.
        if entry["push"] and entry["push"] != entry["fetch"]:
            lines.append(f"  {entry['name']}  {entry['push']} (push)")

    return {"stdout": "\n".join(lines), "stderr": "", "exit_code": 0}


def _handle_commit(args: list[str], repo_root: Path | None = None) -> dict:
    """Handle the commit subcommand (owner tier). *repo_root* is set only by the external-repo door."""
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

    return commit_handler.commit_changes(message, all_files=all_files, files=files, repo_root=repo_root)


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


def _handle_merge_main(args: list[str]) -> dict:
    """Handle the merge-main subcommand (owner tier): origin/main into dev by merge commit."""
    if args:
        return {"stdout": "", "stderr": f"merge-main takes no arguments; got: {' '.join(args)}", "exit_code": 1}
    result = merge_main_handler.merge_main(lock_handler.find_repo_root())
    if result["success"]:
        return {"stdout": result["message"], "stderr": "", "exit_code": 0}
    return {"stdout": "", "stderr": result["message"], "exit_code": 1}


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
    if command in _GH_PASSTHROUGH_COMMANDS:
        return _gh_verb_help(command)
    return help_pages.page(command)


def _gh_verb_help(command: str) -> str:
    """Per-verb help for a gh passthrough: its reads and owner-only writes, from the gate's own table."""
    from aipass.drone.apps.plugins.devpulse_ops.auth import GH_SUBCOMMANDS

    table = GH_SUBCOMMANDS[command]
    writes = textwrap.fill(
        ", ".join(table["write"]), width=78, initial_indent="  Owner only: ", subsequent_indent=" " * 14
    )
    log_line = "  view <id> --log | --log-failed reads a run's log (job API fallback)\n" if command == "run" else ""
    return (
        f"git {command} <subcommand> [args] — gh {command}, gated per subcommand\n"
        f"  Reads [global]: {', '.join(table['read'])}\n"
        f"{writes}\n"
        f"{log_line}"
        "  A subcommand in neither list is refused, never passed to gh.\n"
    )


def get_introspective() -> str:
    """Return introspection text showing connected handlers."""
    return (
        "@git — Tier-based git workflow, dev branch model (v3.0.0)\n"
        "Connected Handlers:\n"
        "  handlers/git/\n"
        "    - lock_handler.py, status_handler.py, diff_handler.py, log_handler.py, show_handler.py\n"
        "    - tracked_handler.py, export_handler.py\n"
        "    - remote_handler.py, commit_handler.py, checkout_handler.py, sync_handler.py\n"
        "    - merge_main_handler.py\n"
        "    - dev_pr_handler.py, branches_handler.py, delete_branch_handler.py, close_pr_handler.py\n"
        "    - repo_door.py (--repo <path>, admin seat only)\n"
        "  plugins/devpulse_ops/\n"
        "    - auth.py, merge_plugin.py, sync_plugin.py, fix_plugin.py\n"
        "  gh passthrough: issue, run, workflow\n"
        "Machine surface: --json on status, log, show, remote\n"
        "Tiers: global (status,diff,log,show,blame,tracked,export,remote,lock,branches,tag --list,"
        "issue,run,workflow)"
        " | owner (pr,commit,checkout,dev-pr,delete-branch,prune-temp,close-pr,sync,merge-main,"
        "unlock,merge,smart-sync,fix,tag)\n"
    )


def _tier_commands(tier: str) -> list[str]:
    """The commands a tier actually grants, read from the gate itself.

    Args:
        tier: "global" or "owner".

    Returns:
        The tier's command list, or an empty list if the gate cannot be
        imported — an introspection line is not worth failing a command over,
        and an empty tier reads as unknown rather than as a confident lie.
    """
    try:
        from aipass.drone.apps.plugins.devpulse_ops.auth import GIT_ACCESS_TIERS

        return list(GIT_ACCESS_TIERS[tier]["commands"])
    except (ImportError, KeyError) as exc:
        logger.warning("Could not read git access tiers for introspection: %s", exc)
        return []


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
        " [cyan]diff_handler.py[/cyan], [cyan]log_handler.py[/cyan],"
        " [cyan]show_handler.py[/cyan], [cyan]remote_handler.py[/cyan]"
    )
    c.print("    - [cyan]commit_handler.py[/cyan], [cyan]checkout_handler.py[/cyan], [cyan]sync_handler.py[/cyan]")
    c.print("    - [cyan]merge_main_handler.py[/cyan], [cyan]tracked_handler.py[/cyan], [cyan]export_handler.py[/cyan]")
    c.print(
        "    - [cyan]dev_pr_handler.py[/cyan], [cyan]branches_handler.py[/cyan],"
        " [cyan]delete_branch_handler.py[/cyan], [cyan]close_pr_handler.py[/cyan],"
        " [cyan]tag_handler.py[/cyan]"
    )
    c.print("    - [cyan]repo_door.py[/cyan] [dim](--repo <path>, admin seat only)[/dim]")
    c.print("  [cyan]plugins/devpulse_ops/[/cyan]")
    c.print(
        "    - [cyan]auth.py[/cyan], [cyan]merge_plugin.py[/cyan],"
        " [cyan]sync_plugin.py[/cyan], [cyan]fix_plugin.py[/cyan]"
    )
    c.print("  [dim]gh passthrough: issue, run, workflow[/dim]")
    c.print("  [dim]machine surface: --json on status, log, show, remote[/dim]")
    # Read off GIT_ACCESS_TIERS rather than retyped: this line had drifted from
    # the gate it describes — it advertised prune-temp as global (it is owner)
    # and omitted show entirely. A surface that miseducates its own agent is the
    # species @spawn caught in their branch prompt; a copy cannot drift.
    c.print(
        "[yellow]Tiers:[/yellow] [dim]global[/dim]"
        f" [dim]({','.join(_tier_commands('global'))})[/dim]"
        " | [dim]owner[/dim]"
        f" [dim]({','.join(_tier_commands('owner'))})[/dim]"
    )
    c.print()


def print_help(command: str | None = None) -> None:
    """Print help (seedgo compliance).

    Args:
        command: The verb to explain. None prints the top-level page; an
            unknown verb falls through to it inside ``get_help``.

    ``markup=False``: this page is documentation, not styled output, and its
    argument placeholders are literal. Rendered as markup, Rich read ``[count]``
    and ``[path]`` as style tags and deleted them silently — ``log [count]``
    reached the terminal as ``log``. Measured 2026-09-15, with the Rich_Markup
    standard scoring 100, because the literal is returned by ``get_help()``
    rather than written at the print site.
    """
    _get_console().print(get_help(command), markup=False)
