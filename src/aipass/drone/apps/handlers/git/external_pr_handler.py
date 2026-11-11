# =================== AIPass ====================
# Name: external_pr_handler.py
# Description: dev-pr and merge in an external project's repo, by its own manager or through the admin door
# Version: 1.1.0
# Created: 2026-10-17
# Modified: 2026-11-10
# =============================================

"""dev-pr and merge for a repo that is not AIPass's own, run by that project's manager.

Same dev -> main model, aimed at the repo's own GitHub slug. No PR lock, no sync with
AIPass, no pr_merged event: that event syncs AIPass's own status page. The admin door's
pr and merge (``--repo``) read the checked-out branch and GitHub's default branch instead
of dev and main, and never delete a branch.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.git.commit_handler import subject_refusal
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
REFUSE_NOT_AHEAD = "{head} has no commits ahead of origin/{base} — there is nothing to open a PR for"
REFUSE_DETACHED = "pr refused: HEAD is detached in {repo}. Check out the working branch first."
REFUSE_ON_DEFAULT = "pr refused: {repo} has {branch} checked out, the default branch GitHub reports. Check out the working branch first."
TITLE_OUTCOME = "The PR title was refused. Nothing was pushed."
KEPT = "Its head branch was kept and nothing local moved."
_DEFAULT_BRANCH = ".defaultBranchRef.name"


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


def _push_and_open(repo_root: Path, slug: str, head: str, base: str, description: str, verb: str) -> dict:
    """Refuse a tracked change or a head level with origin's base, else push head and open head -> base.

    Never forced: git's own refusal comes back in the message.
    """
    try:
        dirty = _out(repo_root, ["git", "status", "--porcelain", "--untracked-files=no"])
        if dirty:
            return {"success": False, "message": REFUSE_DIRTY.format(count=len(dirty.splitlines())), "pr_url": ""}
        _out(repo_root, ["git", "fetch", REMOTE, base])
        ahead = _out(repo_root, ["git", "rev-list", "--count", f"{REMOTE}/{base}..{head}"])
        if ahead == "0":
            return {"success": False, "message": REFUSE_NOT_AHEAD.format(head=head, base=base), "pr_url": ""}
        _out(repo_root, ["git", "push", REMOTE, head])
        pr = _run(
            repo_root,
            ["gh", "pr", "create", "-R", slug, "--head", head, "--base", base, "--title", description, "--body", ""],
        )
    except _ToolFailed as exc:
        logger.warning("external %s in %s refused: %s", verb, repo_root, exc)
        return {"success": False, "message": f"{verb} failed: {exc}", "pr_url": ""}

    if pr.returncode != 0:
        stderr = pr.stderr.strip()
        if "already exists" not in stderr:
            return {"success": False, "message": f"Pushed {head}. PR creation failed: {stderr}", "pr_url": ""}
        pr_url = _existing_pr_url(stderr)
        json_handler.log_operation("dev_pr_push_existing", {"repo": slug, "pr_url": pr_url, "description": description})
        return {"success": True, "message": f"Pushed {head}. PR already open: {pr_url or slug}", "pr_url": pr_url}

    pr_url = pr.stdout.strip()
    json_handler.log_operation("create_dev_pr", {"repo": slug, "pr_url": pr_url, "description": description})
    logger.info("External PR %s -> %s created in %s: %s", head, base, slug, pr_url)
    return {"success": True, "message": f"PR created: {pr_url}", "pr_url": pr_url}


def create_dev_pr(repo_root: Path, description: str) -> dict:
    """Push dev and open the PR dev -> main; refused before any push unless on a clean dev ahead of main.

    Returns:
        Dict with success, message, and pr_url keys.
    """
    try:
        slug = _slug(repo_root)
        branch = _out(repo_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
    except _ToolFailed as exc:
        logger.warning("external dev-pr in %s refused: %s", repo_root, exc)
        return {"success": False, "message": f"dev-pr failed: {exc}", "pr_url": ""}
    if branch != DEV:
        return {"success": False, "message": REFUSE_NOT_ON_DEV.format(branch=branch), "pr_url": ""}
    return _push_and_open(repo_root, slug, DEV, MAIN, description, "dev-pr")


def open_branch_pr(repo_root: Path, description: str) -> dict:
    """``pr --repo``: push the checked-out branch and open its PR to the default branch GitHub reports.

    Returns:
        Dict with success, message, and pr_url keys.
    """
    refusal = subject_refusal(description, TITLE_OUTCOME)
    if refusal:
        return {"success": False, "message": refusal, "pr_url": ""}
    try:
        slug = _slug(repo_root)
        head = _out(repo_root, ["git", "rev-parse", "--abbrev-ref", "HEAD"])
        if head == "HEAD":
            return {"success": False, "message": REFUSE_DETACHED.format(repo=repo_root), "pr_url": ""}
        base = _out(repo_root, ["gh", "repo", "view", slug, "--json", "defaultBranchRef", "--jq", _DEFAULT_BRANCH])
    except _ToolFailed as exc:
        logger.warning("external pr in %s refused: %s", repo_root, exc)
        return {"success": False, "message": f"pr failed: {exc}", "pr_url": ""}
    if head == base:
        return {"success": False, "message": REFUSE_ON_DEFAULT.format(repo=repo_root, branch=base), "pr_url": ""}
    return _push_and_open(repo_root, slug, head, base, description, "pr")


def _merge_on_github(repo_root: Path, pr_number: str, keep_head: bool) -> tuple[str, str]:
    """Merge PR *pr_number* on origin's repo as a merge commit and return (slug, title).

    The head is deleted only when *keep_head* is False and it is a known branch other than dev or main.
    """
    slug = _slug(repo_root)
    pr = json.loads(_out(repo_root, ["gh", "pr", "view", pr_number, "-R", slug, "--json", "headRefName,title"]))
    head_ref, title = pr.get("headRefName", ""), pr.get("title", "")
    merge_cmd = ["gh", "pr", "merge", pr_number, "-R", slug, "--merge"]
    if not keep_head and head_ref and head_ref not in PROTECTED_BRANCHES:
        merge_cmd.append("--delete-branch")
    _out(repo_root, merge_cmd)
    return slug, title


def _merge_commit(repo_root: Path, slug: str, pr_number: str) -> str:
    """The merge commit GitHub recorded for PR *pr_number*."""
    return _out(
        repo_root, ["gh", "pr", "view", pr_number, "-R", slug, "--json", "mergeCommit", "--jq", ".mergeCommit.oid"]
    )


def merge_door_pr(repo_root: Path, pr_number: str, caller: str) -> dict:
    """``merge --repo``: merge the PR on origin's repo as a merge commit; no branch deleted, nothing local moved.

    Returns:
        Dict with success and message.
    """
    try:
        slug, title = _merge_on_github(repo_root, pr_number, keep_head=True)
    except (_ToolFailed, json.JSONDecodeError) as exc:
        logger.warning("door merge of PR #%s in %s refused: %s", pr_number, repo_root, exc)
        return {"success": False, "message": f"Merge failed: {exc}"}
    merged = f"PR #{pr_number} merged on {slug}: {title}"
    try:
        merged += f" ({_merge_commit(repo_root, slug, pr_number)[:8]}). {KEPT}"
    except _ToolFailed as exc:
        logger.warning("door merge of PR #%s: merge commit unread: %s", pr_number, exc)
        merged += f". {KEPT} Its merge commit could not be read: {exc}"
    json_handler.log_operation("merge_pr", {"caller": caller, "repo": slug, "pr_number": pr_number, "title": title})
    logger.info(merged)
    return {"success": True, "message": merged}


def merge_pr(repo_root: Path, pr_number: str, caller: str) -> dict:
    """Merge the PR on GitHub, then fast-forward local dev; a later failure still names the merge.

    Returns:
        Dict with success, pr_number, title, merge_commit, and message.
    """
    result: dict = {"success": False, "pr_number": pr_number, "title": "", "merge_commit": "", "message": ""}
    try:
        slug, title = _merge_on_github(repo_root, pr_number, keep_head=False)
    except (_ToolFailed, json.JSONDecodeError) as exc:
        result["message"] = f"Merge failed: {exc}"
        logger.warning("external merge of PR #%s refused: %s", pr_number, exc)
        return result

    result["title"] = title
    try:
        result["merge_commit"] = _merge_commit(repo_root, slug, pr_number)
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
