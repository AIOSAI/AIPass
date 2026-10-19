# =================== AIPass ====================
# Name: label_handler.py
# Description: label list | create: a repo's GitHub labels through gh, create idempotent
# Version: 1.0.0
# Created: 2026-10-19
# Modified: 2026-10-19
# =============================================

"""``drone @git label list | create``: the labels of the repo the command stands in.

create checks first, so a label already there is reported present and nothing is sent.
GitHub compares label names without case, and so does the check.
"""

from __future__ import annotations

import re
from pathlib import Path

from aipass.drone.apps.handlers.git import gh_chores
from aipass.drone.apps.handlers.git.gh_chores import ChoreRefusal
from aipass.drone.apps.handlers.json import json_handler
from aipass.drone.apps.handlers.json_flags import strip_json_flag, wants_json

# gh label list stops at 30 without --limit; a thousand is every label a repo plausibly holds.
LIST_LIMIT = 1000
_FIELDS = "name,color,description"
_COLOR = re.compile(r"#?([0-9A-Fa-f]{6})")

USAGE = (
    "Usage: drone @git label list [--json] | label create <name> [--color hex] [--description text]  [--repo <path>]"
)
REFUSE_SUB = "'label {sub}' is not served. Labels: list, create."
REFUSE_NO_NAME = "label create needs one label name: drone @git label create <name> [--color hex] [--description text]"
REFUSE_COLOR = "label create --color takes six hex digits, such as 0e8a16 or #0e8a16; '{color}' is not one."
REFUSE_LIST_ARGS = "label list takes only --json."


def _labels(slug: str) -> list[dict]:
    """Every label of *slug*, as gh reports them."""
    rows = gh_chores.gh_json(
        ["label", "list", "--repo", slug, "--limit", str(LIST_LIMIT), "--json", _FIELDS], verb="label", slug=slug
    )
    if not isinstance(rows, list):
        raise ChoreRefusal(gh_chores.REFUSE_GH_FAILED.format(verb="label", slug=slug, reason="not a list of labels"))
    return rows


def _list(args: list[str], slug: str, as_json: bool) -> dict:
    """``label list``: one row per label, name, #color, description."""
    if args:
        raise ChoreRefusal(REFUSE_LIST_ARGS)
    rows = _labels(slug)
    json_handler.log_operation("git_label_list", {"github": slug, "count": len(rows)})
    if as_json:
        return gh_chores.json_answer({"ok": True, "github": slug, "count": len(rows), "labels": rows})
    if not rows:
        return gh_chores.answer(f"No labels on github.com/{slug}.")
    lines = [f"{row.get('name', '')}  #{row.get('color', '')}  {row.get('description') or ''}".rstrip() for row in rows]
    return gh_chores.answer("\n".join(lines))


def _create(args: list[str], repo_root: Path, slug: str, caller: str) -> dict:
    """``label create``: send the label unless one of that name is already there."""
    names, values = gh_chores.parse_flags(args, ("--color", "--description"), "label create")
    if len(names) != 1 or not names[0].strip():
        raise ChoreRefusal(REFUSE_NO_NAME)
    name = names[0]
    color = values.get("--color")
    if color is not None:
        match = _COLOR.fullmatch(color)
        if match is None:
            raise ChoreRefusal(REFUSE_COLOR.format(color=color))
        color = match.group(1).lower()
    present = [row for row in _labels(slug) if str(row.get("name", "")).casefold() == name.casefold()]
    details = {"label": name, "color": color, "description": values.get("--description")}
    if present:
        gh_chores.record_write(
            caller=caller,
            verb="label create",
            repo_root=repo_root,
            slug=slug,
            outcome=gh_chores.OUTCOME_UNCHANGED,
            details=details,
        )
        found = present[0]
        return gh_chores.answer(
            f"Label '{found.get('name')}' is already present on github.com/{slug} "
            f"(#{found.get('color', '')}); nothing changed."
        )
    argv = ["label", "create", name, "--repo", slug]
    if color is not None:
        argv += ["--color", color]
    if "--description" in values:
        argv += ["--description", values["--description"]]
    gh_chores.gh(argv, verb="label create", slug=slug)
    gh_chores.record_write(
        caller=caller,
        verb="label create",
        repo_root=repo_root,
        slug=slug,
        outcome=gh_chores.OUTCOME_WRITTEN,
        details=details,
    )
    return gh_chores.answer(f"Created label '{name}' on github.com/{slug}.")


def label_command(args: list[str], repo_root: Path, caller: str) -> dict:
    """``label list [--json] | label create <name> [--color hex] [--description text]``, as a routing result."""
    as_json = wants_json(args)
    args = strip_json_flag(args)
    try:
        if not args or args[0] not in ("list", "create"):
            raise ChoreRefusal(REFUSE_SUB.format(sub=args[0]) if args else USAGE)
        slug = gh_chores.repo_slug(repo_root, f"label {args[0]}")
        if args[0] == "list":
            return _list(args[1:], slug, as_json)
        return _create(args[1:], repo_root, slug, caller)
    except ChoreRefusal as refusal:
        if as_json:
            return gh_chores.json_answer({"ok": False, "message": str(refusal)}, exit_code=1)
        return gh_chores.answer(str(refusal), exit_code=1)
