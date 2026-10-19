# =================== AIPass ====================
# Name: alerts_handler.py
# Description: alerts list | dismiss: a repo's code-scanning alerts through gh api
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""``drone @git alerts list | dismiss``: the code-scanning alerts of the repo the command stands in.

dismiss always carries its reason and comment to GitHub, so every dismissal there says why.
"""

from __future__ import annotations

from pathlib import Path

from aipass.drone.apps.handlers.git import gh_chores
from aipass.drone.apps.handlers.git.gh_chores import ChoreRefusal
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.json_flags import strip_json_flag, wants_json

STATES = ("open", "dismissed", "all")
# The flag's words, and the words GitHub's API takes for them.
REASONS = {"false_positive": "false positive", "wont_fix": "won't fix", "used_in_tests": "used in tests"}
# GitHub refuses a dismissed_comment longer than this.
COMMENT_CAP = 280
_PAGE_SIZE = 100
_MAX_PAGES = 10

USAGE = (
    "Usage: drone @git alerts list [--state open|dismissed|all] [--json] | "
    "alerts dismiss <number> --reason false_positive|wont_fix|used_in_tests --comment 'text'  [--repo <path>]"
)
REFUSE_SUB = "'alerts {sub}' is not served. Alerts: list, dismiss."
REFUSE_STATE = "alerts list --state takes open, dismissed or all; '{state}' is not one."
REFUSE_LIST_ARGS = "alerts list takes only --state and --json."
REFUSE_NUMBER = "alerts dismiss needs one alert number: drone @git alerts dismiss <number> --reason R --comment 'text'"
REFUSE_REASON = "alerts dismiss --reason takes false_positive, wont_fix or used_in_tests; '{reason}' is not one."
REFUSE_NO_COMMENT = "alerts dismiss refused: --comment is required. A dismissal says why: --comment 'text'."
REFUSE_LONG_COMMENT = "alerts dismiss refused: --comment is {length} characters; GitHub takes at most {cap}."
REFUSE_NO_ALERT = "alerts dismiss refused: github.com/{slug} has no code-scanning alert #{number}."
REFUSE_NOT_OPEN = "alerts dismiss refused: alert #{number} on github.com/{slug} is {state}, not open."


def _row(alert: dict) -> dict:
    """The fields list prints for one alert."""
    rule = alert.get("rule") or {}
    location = (alert.get("most_recent_instance") or {}).get("location") or {}
    return {
        "number": alert.get("number"),
        "rule": rule.get("id") or "",
        "severity": rule.get("security_severity_level") or rule.get("severity") or "",
        "state": alert.get("state") or "",
        "path": location.get("path") or "",
        "line": location.get("start_line"),
    }


def _list(args: list[str], slug: str, as_json: bool) -> dict:
    """``alerts list``: one row per alert, newest first as GitHub orders them."""
    positionals, values = gh_chores.parse_flags(args, ("--state",), "alerts list")
    if positionals:
        raise ChoreRefusal(REFUSE_LIST_ARGS)
    state = values.get("--state", "open")
    if state not in STATES:
        raise ChoreRefusal(REFUSE_STATE.format(state=state))
    query = "" if state == "all" else f"&state={state}"
    rows: list[dict] = []
    for page in range(1, _MAX_PAGES + 1):
        path = f"repos/{slug}/code-scanning/alerts?per_page={_PAGE_SIZE}&page={page}{query}"
        batch = gh_chores.gh_json(["api", path], verb="alerts list", slug=slug)
        if not isinstance(batch, list):
            reason = "the answer was not a list of alerts"
            raise ChoreRefusal(gh_chores.REFUSE_GH_FAILED.format(verb="alerts list", slug=slug, reason=reason))
        rows += [_row(alert) for alert in batch]
        if len(batch) < _PAGE_SIZE:
            break
    json_handler.log_operation("git_alerts_list", {"github": slug, "state": state, "count": len(rows)})
    if as_json:
        return gh_chores.json_answer({"ok": True, "github": slug, "state": state, "count": len(rows), "alerts": rows})
    if not rows:
        return gh_chores.answer(f"No {'' if state == 'all' else state + ' '}code-scanning alerts on github.com/{slug}.")
    lines = [
        f"#{row['number']}  {row['rule']}  {row['severity']}  {row['state']}  {row['path']}:{row['line']}"
        for row in rows
    ]
    return gh_chores.answer("\n".join(lines))


def _dismiss(args: list[str], repo_root: Path, slug: str, caller: str) -> dict:
    """``alerts dismiss``: an open alert becomes dismissed, with its reason and comment."""
    numbers, values = gh_chores.parse_flags(args, ("--reason", "--comment"), "alerts dismiss")
    if len(numbers) != 1 or not numbers[0].isdigit():
        raise ChoreRefusal(REFUSE_NUMBER)
    number = numbers[0]
    reason = values.get("--reason", "")
    if reason not in REASONS:
        raise ChoreRefusal(REFUSE_REASON.format(reason=reason))
    comment = values.get("--comment", "").strip()
    if not comment:
        raise ChoreRefusal(REFUSE_NO_COMMENT)
    if len(comment) > COMMENT_CAP:
        raise ChoreRefusal(REFUSE_LONG_COMMENT.format(length=len(comment), cap=COMMENT_CAP))
    path = f"repos/{slug}/code-scanning/alerts/{number}"
    try:
        alert = gh_chores.gh_json(["api", path], verb="alerts dismiss", slug=slug)
    except ChoreRefusal as refusal:
        if gh_chores.is_not_found(refusal):
            raise ChoreRefusal(REFUSE_NO_ALERT.format(slug=slug, number=number)) from refusal
        raise
    if not isinstance(alert, dict) or alert.get("state") != "open":
        state = alert.get("state") if isinstance(alert, dict) else None
        raise ChoreRefusal(REFUSE_NOT_OPEN.format(number=number, slug=slug, state=state))
    gh_chores.gh(
        [
            "api",
            "-X",
            "PATCH",
            path,
            "-f",
            "state=dismissed",
            "-f",
            f"dismissed_reason={REASONS[reason]}",
            "-f",
            f"dismissed_comment={comment}",
        ],
        verb="alerts dismiss",
        slug=slug,
    )
    rule = _row(alert)["rule"]
    gh_chores.record_write(
        caller=caller,
        verb="alerts dismiss",
        repo_root=repo_root,
        slug=slug,
        outcome=gh_chores.OUTCOME_WRITTEN,
        details={"number": int(number), "rule": rule, "reason": reason, "comment": comment},
    )
    return gh_chores.answer(f"Dismissed alert #{number} ({rule}) on github.com/{slug} as {reason}: {comment}")


def alerts_command(args: list[str], repo_root: Path, caller: str) -> dict:
    """``alerts list [--state S] [--json] | alerts dismiss <n> --reason R --comment 'text'``, as a routing result."""
    as_json = wants_json(args)
    args = strip_json_flag(args)
    try:
        if not args or args[0] not in ("list", "dismiss"):
            raise ChoreRefusal(REFUSE_SUB.format(sub=args[0]) if args else USAGE)
        slug = gh_chores.repo_slug(repo_root, f"alerts {args[0]}")
        if args[0] == "list":
            return _list(args[1:], slug, as_json)
        return _dismiss(args[1:], repo_root, slug, caller)
    except ChoreRefusal as refusal:
        if as_json:
            return gh_chores.json_answer({"ok": False, "message": str(refusal)}, exit_code=1)
        return gh_chores.answer(str(refusal), exit_code=1)
