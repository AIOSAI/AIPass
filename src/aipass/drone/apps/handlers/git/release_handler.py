# =================== AIPass ====================
# Name: release_handler.py
# Description: release list | edit — a repo's published GitHub releases through gh; edit rewrites notes
# Version: 1.1.0
# Created: 2026-10-15
# Modified: 2026-10-19
# =============================================

"""``drone @git release list | edit``: a repo's published GitHub releases.

list: every seat may read, so public data only, a private repo is refused even when gh's
account sees it; ``gh api``, because ``gh release list`` carries no bodies. edit: the owner
rewrites one release's notes with that tag's CHANGELOG.md block, by publish.yml's rule.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

from aipass.prax import logger
from aipass.drone.apps.handlers.git import gh_chores
from aipass.drone.apps.handlers.git.gh_chores import ChoreRefusal
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.json_flags import strip_json_flag, wants_json

DEFAULT_REPO = "AIOSAI/AIPass"
DEFAULT_LIMIT = 30
# The gh passthroughs' budget: one API page answers in a second or two.
GH_TIMEOUT = 60
_PAGE_SIZE = 100
# Ten pages is a thousand releases; a --since tag older than that is refused, not chased.
_MAX_PAGES = 10
_SLUG = re.compile(r"[A-Za-z0-9-]+/[A-Za-z0-9._-]+")
_VALUE_FLAGS = ("--repo", "--since", "--limit")

USAGE = "Usage: drone @git release list [--repo OWNER/NAME] [--since TAG] [--limit N] [--json]"
# Refusal texts, printed exactly as written here; --help renders the same constants.
REFUSE_SUB = "'release {sub}' is not served. Releases are read only: drone @git release list."
REFUSE_FLAG = "Unknown argument for 'release list': {arg}"
REFUSE_NO_VALUE = "release list {flag} needs a value."
REFUSE_SLUG = "release list --repo takes a GitHub OWNER/NAME; '{repo}' is not one."
REFUSE_LIMIT = "release list --limit takes a whole number above 0; '{value}' is not one."
REFUSE_NO_GH = "release list needs the gh CLI, and gh is not installed here. Install: https://cli.github.com/"
REFUSE_UNKNOWN = "release list refused: github.com/{repo} is unknown, or private (GitHub answered 404)."
REFUSE_PRIVATE = "release list refused: github.com/{repo} is private. Only public release data is read."
REFUSE_TIMEOUT = "release list: gh did not answer within {seconds} s for github.com/{repo}."
REFUSE_GH_FAILED = "release list: gh could not read github.com/{repo}: {reason}"
REFUSE_SINCE = "release list refused: --since {tag} is not a published release of github.com/{repo}."

# publish.yml's rule, so the door and the workflow write the same notes: GitHub refuses a
# body over 125,000 characters, and the cut lands under this on an entry boundary.
NOTES_CAP = 120_000
_SECTION = "## ["
_TAG = re.compile(r"[A-Za-z0-9._-]+")
REFUSE_EDIT_USAGE = "release edit needs one tag: drone @git release edit <tag> [--repo <path>]"
REFUSE_NO_CHANGELOG = "release edit refused: {repo} has no CHANGELOG.md to take the notes from."
REFUSE_NO_SECTION = "release edit refused: no CHANGELOG.md section header carries {tag}."
REFUSE_NOT_PUBLISHED = "release edit refused: {tag} is not a published release of github.com/{slug}."


class _Refusal(Exception):
    """The command cannot answer; the message is the refusal, printed exactly."""


def _parse(args: list[str]) -> tuple[str, str | None, int]:
    """``(repo, since, limit)`` from ``list``'s flags, each spaced or ``--flag=value``; raise _Refusal."""
    values: dict[str, str] = {}
    rest = list(args)
    while rest:
        arg = rest.pop(0)
        flag, equals, value = arg.partition("=")
        if flag not in _VALUE_FLAGS:
            raise _Refusal(REFUSE_FLAG.format(arg=arg))
        if not equals:
            if not rest:
                raise _Refusal(REFUSE_NO_VALUE.format(flag=flag))
            value = rest.pop(0)
        values[flag] = value
    repo = values.get("--repo", DEFAULT_REPO)
    if not _SLUG.fullmatch(repo):
        raise _Refusal(REFUSE_SLUG.format(repo=repo))
    raw_limit = values.get("--limit", str(DEFAULT_LIMIT))
    if not raw_limit.isdigit() or int(raw_limit) < 1:
        raise _Refusal(REFUSE_LIMIT.format(value=raw_limit))
    return repo, values.get("--since"), int(raw_limit)


def _gh_api(repo: str, path: str) -> str:
    """gh's stdout for one GET on the GitHub API; raise _Refusal naming why it could not be read."""
    try:
        result = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=GH_TIMEOUT)
    except FileNotFoundError as exc:
        logger.warning("git release list: gh not found: %s", exc)
        raise _Refusal(REFUSE_NO_GH) from exc
    except subprocess.TimeoutExpired as exc:
        logger.warning("git release list: gh api %s timed out", path)
        raise _Refusal(REFUSE_TIMEOUT.format(seconds=GH_TIMEOUT, repo=repo)) from exc
    if result.returncode != 0:
        reason = (result.stderr or result.stdout).strip()
        logger.warning("git release list: gh api %s failed: %s", path, reason)
        if "HTTP 404" in reason:
            raise _Refusal(REFUSE_UNKNOWN.format(repo=repo))
        raise _Refusal(REFUSE_GH_FAILED.format(repo=repo, reason=reason))
    return result.stdout


def _read_json(repo: str, path: str) -> object:
    try:
        return json.loads(_gh_api(repo, path))
    except json.JSONDecodeError as exc:
        logger.warning("git release list: gh api %s answered non-JSON: %s", path, exc)
        raise _Refusal(REFUSE_GH_FAILED.format(repo=repo, reason=f"the answer was not JSON ({exc})")) from exc


def list_releases(repo: str, since: str | None, limit: int) -> list[dict]:
    """Up to *limit* published releases of *repo*, newest first, stopping before *since* (exclusive).

    With *since*, reading continues past *limit* until the tag is seen, so a mistyped tag is refused.
    """
    meta = _read_json(repo, f"repos/{repo}")
    if not isinstance(meta, dict) or meta.get("private") is not False:
        raise _Refusal(REFUSE_PRIVATE.format(repo=repo))
    rows: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        batch = _read_json(repo, f"repos/{repo}/releases?per_page={_PAGE_SIZE}&page={page}")
        if not isinstance(batch, list):
            raise _Refusal(REFUSE_GH_FAILED.format(repo=repo, reason="the answer was not a list of releases"))
        for release in batch:
            if release.get("draft"):
                continue
            if since is not None and release.get("tag_name") == since:
                return rows
            if len(rows) == limit:
                continue
            rows.append(
                {
                    "tag": release.get("tag_name", ""),
                    "published_at": release.get("published_at") or "",
                    "name": release.get("name") or "",
                    "body": release.get("body") or "",
                }
            )
            if len(rows) == limit and since is None:
                return rows
        if len(batch) < _PAGE_SIZE:
            break
    if since is not None:
        raise _Refusal(REFUSE_SINCE.format(tag=since, repo=repo))
    return rows


def render(rows: list[dict]) -> str:
    """One row per release (tag, published_at, name), its notes indented under it."""
    blocks = []
    for row in rows:
        notes = row["body"].splitlines() or ["(no notes)"]
        blocks.append(
            f"{row['tag']}  {row['published_at']}  {row['name']}\n" + "\n".join(f"    {n}".rstrip() for n in notes)
        )
    return "\n\n".join(blocks)


def release_command(args: list[str]) -> dict:
    """``release list [--repo OWNER/NAME] [--since TAG] [--limit N] [--json]``, as a routing result.

    With --json, stdout is one document carrying ``ok``, refusals included (every @git read door's shape).
    """
    as_json = wants_json(args)
    args = strip_json_flag(args)
    repo = DEFAULT_REPO
    try:
        if not args or args[0] != "list":
            raise _Refusal(REFUSE_SUB.format(sub=args[0]) if args else USAGE)
        repo, since, limit = _parse(args[1:])
        rows = list_releases(repo, since, limit)
    except _Refusal as refusal:
        if as_json:
            return {
                "stdout": json.dumps({"ok": False, "repo": repo, "message": str(refusal)}, indent=2),
                "stderr": "",
                "exit_code": 1,
            }
        return {"stdout": "", "stderr": str(refusal), "exit_code": 1}
    json_handler.log_operation("git_release_list", {"repo": repo, "count": len(rows)})
    message = f"{len(rows)} release(s) of github.com/{repo}"
    if as_json:
        document = {"ok": True, "repo": repo, "count": len(rows), "releases": rows, "message": message}
        return {"stdout": json.dumps(document, indent=2), "stderr": "", "exit_code": 0}
    return {
        "stdout": render(rows) if rows else f"No published releases of github.com/{repo}.",
        "stderr": "",
        "exit_code": 0,
    }


def changelog_block(text: str, tag: str) -> str:
    """The block whose ``## [`` header carries *tag*, up to the next header, ``---`` lines dropped.

    publish.yml's rule: the tag sits between non-version characters, so v2.8.2 never claims v2.8.20.
    """
    carries = re.compile("(^|[^0-9A-Za-z.])" + re.escape(tag) + "([^0-9]|$)")
    keep = False
    lines: list[str] = []
    # awk's records: a final newline ends the last line, it does not start an empty one.
    for line in text.removesuffix("\n").split("\n"):
        if line.startswith(_SECTION):
            keep = carries.search(line) is not None
        if keep and line != "---":
            lines.append(line + "\n")
    return "".join(lines)


def fit_notes(block: str, tag: str, slug: str) -> str:
    """*block* as GitHub will take it: over NOTES_CAP, cut on an entry and pointed at the full block."""
    if len(block) <= NOTES_CAP:
        return block
    head = block.splitlines()[0]
    tail = (
        "\n\n---\n\n*Release notes truncated: the full block is "
        f"{len(block):,} characters and GitHub caps a release body at 125,000. "
        f"The complete entry is `{head[:60]}…` in "
        f"[CHANGELOG.md](https://github.com/{slug}/blob/{tag}/CHANGELOG.md).*\n"
    )
    cut = block.rfind("\n- **", 0, NOTES_CAP - len(tail))
    if cut <= 0:
        cut = NOTES_CAP - len(tail)
    return block[:cut].rstrip() + tail


def _published(slug: str, tag: str) -> dict:
    """The published release *tag* of *slug*; raise ChoreRefusal when there is none."""
    try:
        release = gh_chores.gh_json(["api", f"repos/{slug}/releases/tags/{tag}"], verb="release edit", slug=slug)
    except ChoreRefusal as refusal:
        if gh_chores.is_not_found(refusal):
            raise ChoreRefusal(REFUSE_NOT_PUBLISHED.format(tag=tag, slug=slug)) from refusal
        raise
    if not isinstance(release, dict) or release.get("draft"):
        raise ChoreRefusal(REFUSE_NOT_PUBLISHED.format(tag=tag, slug=slug))
    return release


def edit_command(args: list[str], repo_root: Path, caller: str) -> dict:
    """``release edit <tag>``: rewrite the release's notes with *repo_root*'s CHANGELOG.md block for it."""
    try:
        if len(args) != 1 or not _TAG.fullmatch(args[0]):
            raise ChoreRefusal(REFUSE_EDIT_USAGE)
        tag = args[0]
        try:
            text = (repo_root / "CHANGELOG.md").read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise ChoreRefusal(REFUSE_NO_CHANGELOG.format(repo=repo_root)) from exc
        block = changelog_block(text, tag)
        if not block:
            raise ChoreRefusal(REFUSE_NO_SECTION.format(tag=tag))
        slug = gh_chores.repo_slug(repo_root, "release edit")
        old = _published(slug, tag).get("body") or ""
        notes = fit_notes(block, tag, slug)
        details = {"tag": tag, "old_length": len(old), "new_length": len(notes)}
        if old == notes:
            outcome = gh_chores.OUTCOME_UNCHANGED
            gh_chores.record_write(
                caller=caller, verb="release edit", repo_root=repo_root, slug=slug, outcome=outcome, details=details
            )
            return gh_chores.answer(f"Release {tag} of github.com/{slug} already carries its CHANGELOG.md block.")
        gh_chores.gh(
            ["release", "edit", tag, "--repo", slug, "--notes-file", "-"], verb="release edit", slug=slug, stdin=notes
        )
    except ChoreRefusal as refusal:
        return gh_chores.answer(str(refusal), exit_code=1)
    gh_chores.record_write(
        caller=caller,
        verb="release edit",
        repo_root=repo_root,
        slug=slug,
        outcome=gh_chores.OUTCOME_WRITTEN,
        details=details,
    )
    return gh_chores.answer(
        f"Release {tag} of github.com/{slug}: notes rewritten from CHANGELOG.md, "
        f"{len(old):,} -> {len(notes):,} characters."
    )
