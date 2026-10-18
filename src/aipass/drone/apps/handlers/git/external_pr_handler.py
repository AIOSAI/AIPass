# =================== AIPass ====================
# Name: external_pr_handler.py
# Description: dev-pr and merge in an external project's repo, run by its own manager
# Version: 1.0.0
# Created: 2026-10-17
# Modified: 2026-10-17
# =============================================

"""dev-pr and merge for a repo that is not AIPass's own, run by that project's manager.

Same dev -> main model, aimed at the repo's own GitHub slug. No PR lock, no sync with
AIPass, no pr_merged event: that event syncs AIPass's own status page.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.repo_door import GIT_LOCAL_TIMEOUT, GIT_NETWORK_TIMEOUT, github_slug

DEV = "dev"
MAIN = "main"
REMOTE = "origin"
PROTECTED_BRANCHES = (DEV, MAIN)

_NETWORK = ("fetch", "push")

REFUSE_NO_GITHUB = (
    "the origin remote of {repo} does not name a github.com repository, so there is no OWNER/NAME to hand gh"
)
REFUSE_NOT_ON_DEV = "Not on dev branch (current: {branch}). Switch to dev first: drone @git checkout dev"
REFUSE_DIRTY = (
    "{count} tracked file(s) have uncommitted changes, which the PR would not carry. "
    'Commit them first: drone @git commit "<message>" <files>'
)
REFUSE_NOT_AHEAD = "dev has no commits ahead of origin/main — there is nothing to open a PR for"


class _ToolFailed(Exception):
    """git or gh could not run, did not finish in time, or answered non-zero."""


def _run(repo_root: Path, argv: list[str]) -> subprocess.CompletedProcess:
    """Run *argv* in *repo_root*, timed, never prompting: nobody is at the terminal to answer."""
    timeout = GIT_NETWORK_TIMEOUT if argv[0] == "gh" or argv[1] in _NETWORK else GIT_LOCAL_TIMEOUT
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GH_PROMPT_DISABLED": "1"}
    try:
        return subprocess.run(argv, capture_output=True, text=True, cwd=str(repo_root), timeout=timeout, env=env)
    except FileNotFoundError as exc:
        raise _ToolFailed(f"{argv[0]} not found — install it ({exc})") from exc
    except subprocess.TimeoutExpired as exc:
        raise _ToolFailed(f"{argv[0]} {argv[1]} timed out after {timeout} s in {repo_root}") from exc
    except (OSError, subprocess.SubprocessError) as exc:
        raise _ToolFailed(f"{argv[0]} {argv[1]} could not run: {exc}") from exc


def _out(repo_root: Path, argv: list[str]) -> str:
    """Stripped stdout of a call that must succeed; raise _ToolFailed with the tool's own words if it does not."""
    result = _run(repo_root, argv)
    if result.returncode != 0:
        raise _ToolFailed(f"{' '.join(argv[:3])} failed: {(result.stderr or result.stdout).strip()}")
    return result.stdout.strip()


def _slug(repo_root: Path) -> str:
    """OWNER/NAME of *repo_root*'s origin on github.com; raise _ToolFailed when origin names none."""
    slug = github_slug(_out(repo_root, ["git", "remote", "get-url", REMOTE]))
    if slug is None:
        raise _ToolFailed(REFUSE_NO_GITHUB.format(repo=repo_root))
    return slug


def _existing_pr_url(stderr: str) -> str:
    """The URL gh names when a PR for the head already exists, else ''."""
    for line in stderr.splitlines():
        if line.strip().startswith("https://"):
            return line.strip()
    return ""


def create_dev_pr(repo_root: Path, description: str) -> dict:
    """Push dev and open the PR dev -> main; refused before any push unless on a clean dev ahead of main.

    Returns:
        Dict with success, message, and pr_url keys.
    """
    try:
        slug = _slug(repo_root)
        branch = _out(repo_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if branch != DEV:
            return {"success": False, "message": REFUSE_NOT_ON_DEV.format(branch=branch), "pr_url": ""}
        dirty = _out(repo_root, ["git", "status", "--porcelain", "--untracked-files=no"])
        if dirty:
            return {"success": False, "message": REFUSE_DIRTY.format(count=len(dirty.splitlines())), "pr_url": ""}
        _out(repo_root, ["git", "fetch", REMOTE, MAIN])
        ahead = _out(repo_root, ["git", "rev-list", "--count", f"{REMOTE}/{MAIN}..{DEV}"])
        if ahead == "0":
            return {"success": False, "message": REFUSE_NOT_AHEAD, "pr_url": ""}
        _out(repo_root, ["git", "push", REMOTE, DEV])
        pr = _run(
            repo_root,
            ["gh", "pr", "create", "-R", slug, "--head", DEV, "--base", MAIN, "--title", description, "--body", ""],
        )
    except _ToolFailed as exc:
        logger.warning("external dev-pr in %s refused: %s", repo_root, exc)
        return {"success": False, "message": f"dev-pr failed: {exc}", "pr_url": ""}

    if pr.returncode != 0:
        stderr = pr.stderr.strip()
        if "already exists" not in stderr:
            return {"success": False, "message": f"Pushed dev. PR creation failed: {stderr}", "pr_url": ""}
        pr_url = _existing_pr_url(stderr)
        json_handler.log_operation("dev_pr_push_existing", {"repo": slug, "pr_url": pr_url, "description": description})
        return {"success": True, "message": f"Pushed dev. PR already open: {pr_url or slug}", "pr_url": pr_url}

    pr_url = pr.stdout.strip()
    json_handler.log_operation("create_dev_pr", {"repo": slug, "pr_url": pr_url, "description": description})
    logger.info("External dev PR created in %s: %s", slug, pr_url)
    return {"success": True, "message": f"PR created: {pr_url}", "pr_url": pr_url}


def merge_pr(repo_root: Path, pr_number: str, caller: str) -> dict:
    """Merge the PR on GitHub, then fast-forward local dev; a later failure still names the merge.

    Returns:
        Dict with success, pr_number, title, merge_commit, and message.
    """
    result: dict = {"success": False, "pr_number": pr_number, "title": "", "merge_commit": "", "message": ""}
    try:
        slug = _slug(repo_root)
        pr = json.loads(_out(repo_root, ["gh", "pr", "view", pr_number, "-R", slug, "--json", "headRefName,title"]))
        head_ref, title = pr.get("headRefName", ""), pr.get("title", "")
        merge_cmd = ["gh", "pr", "merge", pr_number, "-R", slug, "--merge"]
        if head_ref and head_ref not in PROTECTED_BRANCHES:
            merge_cmd.append("--delete-branch")
        _out(repo_root, merge_cmd)
    except (_ToolFailed, json.JSONDecodeError) as exc:
        result["message"] = f"Merge failed: {exc}"
        logger.warning("external merge of PR #%s refused: %s", pr_number, exc)
        return result

    result["title"] = title
    try:
        result["merge_commit"] = _out(
            repo_root, ["gh", "pr", "view", pr_number, "-R", slug, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"]
        )
        if _out(repo_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"]) != DEV:
            _out(repo_root, ["git", "checkout", DEV])
        _out(repo_root, ["git", "fetch", REMOTE])
        _out(repo_root, ["git", "merge", "--ff-only", f"{REMOTE}/{DEV}"])
    except _ToolFailed as exc:
        result["message"] = f"PR #{pr_number} merged on {slug}: {title}, but local dev was not brought up: {exc}"
        logger.warning(result["message"])
        return result

    result["success"] = True
    result["message"] = f"PR #{pr_number} merged: {title} ({result['merge_commit'][:8]}) — local dev is current"
    json_handler.log_operation(
        "merge_pr",
        {
            "caller": caller,
            "repo": slug,
            "pr_number": pr_number,
            "title": title,
            "merge_commit": result["merge_commit"],
        },
    )
    logger.info(result["message"])
    return result
