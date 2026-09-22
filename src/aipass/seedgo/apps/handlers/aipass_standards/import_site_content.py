# =================== AIPass ====================
# Name: import_site_content.py
# Description: Import Site Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""
Import Site Standards Content Handler

Provides formatted Import Site standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_import_site_standards() -> str:
    """Return formatted import_site standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 8):[/bold cyan]",
        "  Product imports go at the [green]top of the test file[/green], never inside a test.",
        "",
        "  This is not tidiness. An import that runs inside a test runs AFTER the",
        "  test has had its chance to replace what it is about to import. That is",
        "  the whole mechanism by which a green test can be measuring a stub.",
        "",
        "  [bold]If the unit can be swapped before it is imported, the test proves nothing.[/bold]",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Two shapes, both convicted, in files under [dim]tests/[/dim] (conftest included):",
        "",
        "  [bold]a. A product import inside a function, method or class body[/bold]",
        "  [red]def test_x():[/red]",
        "  [red]    from aipass.flow.apps.modules.list_plans import list_plans[/red]",
        "",
        "  [bold]b. A sys.modules write, or an in-function importlib reload, naming aipass[/bold]",
        # Square brackets are Rich markup, so a subscript has to be escaped or
        # the console silently prints `sys.modules = stub` and teaches the wrong shape.
        "  [dim]sys.modules\\[key] = stub        del sys.modules\\[key]       sys.modules.pop(key)[/dim]",
        "  [dim]patch.dict(sys.modules, ...)   monkeypatch.setitem/delitem(sys.modules, ...)[/dim]",
        "  [dim]importlib.reload(...)          importlib.import_module(...)[/dim]",
        "",
        "[bold cyan]NEVER CONVICTED:[/bold cyan]",
        "  [green]A module-level import[/green] -- including under a module-level",
        "  [dim]try[/dim]/[dim]except ImportError[/dim] or [dim]if TYPE_CHECKING[/dim].",
        "  Nothing at module level can be preceded by a test's own patching.",
        "",
        "  [green]A stdlib or third-party import inside a function.[/green]",
        "  Those cannot fake the unit under test, and asking for them at the top",
        "  would be exactly the tidiness rule this one is not.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- the import is staged behind a patch:[/red]",
        "  [dim]def test_list_plans_prints_the_table():[/dim]",
        '  [dim]    with patch(f"{_MOD}.console") as mock_console:[/dim]',
        "  [dim]        from aipass.flow.apps.modules.list_plans import list_plans[/dim]",
        "",
        "  [red]Bad -- the module under test is rebuilt from a stub:[/red]",
        '  [dim]monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())[/dim]',
        "  [dim]importlib.reload(trigger_check)[/dim]",
        "",
        "  [green]Good -- the real module at the top, patched at the edge:[/green]",
        "  [dim]from aipass.flow.apps.modules.list_plans import list_plans[/dim]",
        "  [dim]...[/dim]",
        "  [dim]def test_list_plans_prints_the_table(monkeypatch, capsys):[/dim]",
        '  [dim]    monkeypatch.setattr(list_plans_mod, "load_registry", lambda: ROWS)[/dim]',
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        "  Shape a: [green]move the import to the top of the file[/green].",
        "  Shape b: [green]import the real module at the top and patch at the edge",
        "  with monkeypatch[/green] -- setattr on the seam, not setitem on sys.modules.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-21 over 590 fleet test files: 369 carry at least one",
        "  hit -- 5,175 deferred product imports and 921 sys.modules stubs.",
        "  The readme tests this branch retired on 2026-09-20 are the worked",
        "  example: source mutants SURVIVED them, because the module under test",
        "  was rebuilt from a stub inside the test body.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  UNSCORED. Test files are not in the audit's corpus, so no branch's",
        "  number moves. The audit reports the standing backlog through the info",
        "  channel; the per-file checklist convicts on the next write of a file.",
    ]

    json_handler.log_operation("content_served", {"standard": "import_site"})
    return "\n".join(lines)
