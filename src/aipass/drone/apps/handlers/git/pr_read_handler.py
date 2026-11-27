# =================== AIPass ====================
# Name: pr_read_handler.py
# Description: pr list | pr view: a repo's pull requests with their base, head and CI, through gh
# Version: 1.1.0
# Created: 2026-11-26
# Modified: 2026-11-26
# =============================================

"""``drone @git pr list | pr view <#>``: the pull requests of the repo the command stands in.

list filters by base, head-branch prefix, a text the body must contain, and state; the CI column
is the conclusion of the checks on each PR's head commit. ``--json`` adds head_sha and url to each row.
"""

from __future__ import annotations

import json
from pathlib import Path

from aipass.drone.apps.handlers.git import gh_chores
from aipass.drone.apps.handlers.git.gh_chores import ChoreRefusal
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.json_flags import strip_json_flag, wants_json

STATES = ("open", "all")
LIST_FLAGS = ("--base", "--head", "--marker", "--state")
# gh pr list has no head-prefix or body filter, so both are applied to the newest this-many PRs.
# Bodies and checks for 200 or more make GitHub's GraphQL answer 502, measured on AIOSAI/AIPass.
LIST_LIMIT = 100
LIST_FIELDS = "number,headRefName,headRefOid,baseRefName,state,title,createdAt,url,body,statusCheckRollup"
VIEW_FIELDS = "number,headRefName,headRefOid,baseRefName,state,mergeable,title,createdAt,url,body,statusCheckRollup"
_FAILED = {"FAILURE", "ERROR", "CANCELLED", "TIMED_OUT", "ACTION_REQUIRED", "STARTUP_FAILURE"}
_PASSED = {"SUCCESS", "NEUTRAL", "SKIPPED"}

USAGE = (
    "Usage: drone @git pr list [--base B] [--head PREFIX] [--marker TEXT] [--state open|all] [--json]"
    " | pr view <#> [--json]"
)
REFUSE_STATE = "pr list --state takes open or all, not '{state}'."
REFUSE_VIEW = "pr view takes one PR number: drone @git pr view <#>"
REFUSE_ANSWER = "the answer was not a list of pull requests"


def ci_conclusion(checks: list | None) -> str:
    """One word for a head commit's checks: failure beats pending beats success; none when there are none."""
    if not checks:
        return "none"
    words = {str(c.get("conclusion") or c.get("state") or c.get("status") or "").upper() for c in checks}
    if words & _FAILED:
        return "failure"
    if words <= _PASSED:
        return "success"
    return "pending"


def _row(pr: dict) -> dict:
    """The fields list prints for one PR."""
    return {
        "number": pr.get("number"),
        "head": pr.get("headRefName") or "",
        "base": pr.get("baseRefName") or "",
        "state": pr.get("state") or "",
        "ci": ci_conclusion(pr.get("statusCheckRollup")),
        "title": pr.get("title") or "",
        "created": pr.get("createdAt") or "",
        "head_sha": pr.get("headRefOid") or "",
        "url": pr.get("url") or "",
    }


def select(prs: list[dict], base: str | None, head: str | None, marker: str | None) -> list[dict]:
    """The PRs whose base is *base*, whose head starts with *head* and whose body holds *marker*; None is any."""
    return [
        pr
        for pr in prs
        if (base is None or pr.get("baseRefName") == base)
        and (head is None or (pr.get("headRefName") or "").startswith(head))
        and (marker is None or marker in (pr.get("body") or ""))
    ]


def _list(args: list[str], slug: str, as_json: bool) -> dict:
    positionals, values = gh_chores.parse_flags(args, LIST_FLAGS, "pr list")
    if positionals:
        raise ChoreRefusal(USAGE)
    state = values.get("--state", "open")
    if state not in STATES:
        raise ChoreRefusal(REFUSE_STATE.format(state=state))
    argv = ["pr", "list", "--repo", slug, "--state", state, "--limit", str(LIST_LIMIT), "--json", LIST_FIELDS]
    if "--base" in values:
        argv += ["--base", values["--base"]]
    prs = gh_chores.gh_json(argv, verb="pr list", slug=slug)
    if not isinstance(prs, list):
        raise ChoreRefusal(gh_chores.REFUSE_GH_FAILED.format(verb="pr list", slug=slug, reason=REFUSE_ANSWER))
    rows = [_row(pr) for pr in select(prs, values.get("--base"), values.get("--head"), values.get("--marker"))]
    json_handler.log_operation("git_pr_list", {"github": slug, "state": state, "count": len(rows)})
    if as_json:
        return gh_chores.answer(json.dumps(rows, indent=2))
    if not rows:
        return gh_chores.answer(f"No {'' if state == 'all' else 'open '}pull requests match on github.com/{slug}.")
    lines = [
        f"#{r['number']}  {r['head']} -> {r['base']}  {r['state']}  ci {r['ci']}  {r['title']}  {r['created']}"
        for r in rows
    ]
    return gh_chores.answer("\n".join(lines))


def _view(args: list[str], slug: str, as_json: bool) -> dict:
    if len(args) != 1 or not (args[0].isascii() and args[0].isdigit()):
        raise ChoreRefusal(REFUSE_VIEW)
    pr = gh_chores.gh_json(["pr", "view", args[0], "--repo", slug, "--json", VIEW_FIELDS], verb="pr view", slug=slug)
    if not isinstance(pr, dict):
        reason = "the answer was not a pull request"
        raise ChoreRefusal(gh_chores.REFUSE_GH_FAILED.format(verb="pr view", slug=slug, reason=reason))
    row = {**_row(pr), "mergeable": pr.get("mergeable") or "", "body": pr.get("body") or ""}
    json_handler.log_operation("git_pr_view", {"github": slug, "number": row["number"]})
    if as_json:
        return gh_chores.answer(json.dumps(row, indent=2))
    head = (
        f"#{row['number']} {row['title']}\n"
        f"{row['head']} -> {row['base']} · {row['state']} · mergeable {row['mergeable']} · ci {row['ci']}\n"
        f"head {row['head_sha']} · {row['url']}\n\n"
    )
    return gh_chores.answer(head + row["body"])


def pr_read(args: list[str], repo_root: Path) -> dict:
    """``pr list ...`` or ``pr view <#>`` against *repo_root*'s GitHub repo; refusals are printed exactly."""
    as_json = wants_json(args)
    verb, rest = args[0], strip_json_flag(args[1:])
    try:
        slug = gh_chores.repo_slug(repo_root, f"pr {verb}")
        return _list(rest, slug, as_json) if verb == "list" else _view(rest, slug, as_json)
    except ChoreRefusal as refusal:
        return gh_chores.answer(str(refusal), 1)
