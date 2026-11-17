# =================== AIPass ====================
# Name: front_door_content.py
# Description: Front Door Standards Content Handler
# Version: 1.1.0
# Created: 2026-11-16
# Modified: 2026-11-16
# =============================================

"""
Front Door Standards Content Handler
"""

from aipass.sentry.apps.handlers.json import json_handler


def get_front_door_standards() -> str:
    """Return formatted front_door standards content with Rich markup"""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A cross-branch import goes through the branch's front door, its package top file.",
        "  Inside its own branch a file imports any path.",
        "",
        "  [green]from aipass.prax import logger[/green]                          right: the door",
        "  [red]from aipass.prax.apps.modules.logger import system_logger[/red]   wrong: under apps/",
        "",
        "[bold cyan]THE DOOR FILE:[/bold cyan]",
        "  src/aipass/<branch>/__init__.py names its public list in __all__ and loads each name",
        "  on first access (PEP 562 __getattr__), never eagerly. prax's door is the model.",
        "  One door: a door_*.py, or a module that only re-exports its own handlers with __all__,",
        "  under apps/modules/ is a second door (retired pattern), convicted at line 1, never waived.",
        "",
        "[bold cyan]WHAT COUNTS (parse tree):[/bold cyan]",
        "  statement   import / from-import anywhere, functions included",
        "  type-only   the same inside if TYPE_CHECKING:",
        "  string      first argument of import_module, resolve_name, patch, <x>.setattr",
        "  Prose (docstrings, comments, messages) never counts. Production and tests both.",
        "",
        "[bold cyan]SCORING:[/bold cyan] per file, 0 with an unwaived site, else 100; gating.",
        "[bold cyan]BYPASS:[/bold cyan] standard front_door, by lines, functions or whole file.",
        "",
        "[bold cyan]THE PUBLIC LIST:[/bold cyan] drone @sentry front-door scan names what other branches reach for.",
    ]

    json_handler.log_operation("content_served", {"standard": "front_door"})
    return "\n".join(lines)
