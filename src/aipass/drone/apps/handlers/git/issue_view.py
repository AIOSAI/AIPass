# =================== AIPass ====================
# Name: issue_view.py
# Description: Renders gh issue view from pinned JSON fields instead of gh's default view
# Version: 1.0.0
# Created: 2026-11-10
# Modified: 2026-11-10
# =============================================

"""``issue view`` on pinned fields: gh's default view requests projectCards, which the API now rejects."""

from __future__ import annotations

from aipass.drone.apps.handlers.json import json_handler

_RENDER_FLAGS = ("--json", "-q", "--jq", "-t", "--template", "-w", "--web")
_COMMENT_FLAGS = ("-c", "--comments")

_FIELDS = "number,title,state,author,createdAt,url,labels,body"

_TEMPLATE = (
    "#{{.number}} {{.title}}\n"
    "{{.state}} · opened by {{.author.login}} · {{.createdAt}}"
    "{{range .labels}} [{{.name}}]{{end}}\n"
    "{{.url}}\n\n"
    "{{.body}}\n"
)

_COMMENTS_TEMPLATE = _TEMPLATE + "{{range .comments}}\n--- {{.author.login}} · {{.createdAt}}\n\n{{.body}}\n{{end}}"


def rewrite_issue_view(args: list[str]) -> list[str]:
    """*args* with pinned fields; a caller who already picked a rendering keeps it, since it conflicts with --json."""
    if not args or args[0] != "view":
        return args
    if any(arg in _RENDER_FLAGS for arg in args):
        return args

    wants_comments = any(arg in _COMMENT_FLAGS for arg in args)
    json_handler.log_operation("issue_view_pinned", {"comments": wants_comments})
    kept = [arg for arg in args if arg not in _COMMENT_FLAGS]
    fields = _FIELDS + ",comments" if wants_comments else _FIELDS
    template = _COMMENTS_TEMPLATE if wants_comments else _TEMPLATE
    return kept + ["--json", fields, "--template", template]
