# =================== AIPass ====================
# Name: front_door_content.py
# Description: Front Door Standards Content Handler
# Version: 1.5.0
# Created: 2026-11-16
# Modified: 2026-11-17
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
        "  [red]from aipass.aipass.shared.json_ops import backup_json[/red]       wrong: beneath the top file",
        "  Any path beneath aipass.<branch> is a finding: apps, shared, lib, docs, tests alike.",
        "",
        "[bold cyan]THE DOOR FILE:[/bold cyan]",
        "  src/aipass/<branch>/__init__.py is the one door: a _HOMES name-to-home table read by",
        "  __getattr__ (PEP 562) on each access. Nothing cached; an unknown name raises AttributeError.",
        "  Second doors under apps/modules/ are convicted, never waived: a door_*.py, a pure",
        "  re-export module (line 1), and a real module whose __all__ hands out handler names",
        "  (at that line, each name and its handler listed; __all__ keeps only own defs).",
        "",
        "[bold cyan]THE DOOR MODEL (checked, never waived):[/bold cyan]",
        "  A package top file with a __getattr__ is a door. Convicted at the breaking line:",
        "  a cache (globals()/vars() write, setattr on sys.modules[...], a module-level memo, global),",
        "  an answered unknown name (getattr default, except that returns, a return before the",
        "  AttributeError guard), __all__ missing or not built from the table, no __dir__.",
        "  A shape the reader does not follow is left unjudged, never guessed.",
        "",
        "[bold cyan]TESTS:[/bold cyan]",
        "  Patch a door name via mock.patch('aipass.<branch>.<name>'), the caller's bound name,",
        "  or its home module (sys.modules[obj.__module__]). Never monkeypatch.setattr on the",
        "  package: its undo leaves the real value as a package global the door serves from then on.",
        "  Event bus: patch.object(Trigger, 'fire') with from aipass.trigger import Trigger.",
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
