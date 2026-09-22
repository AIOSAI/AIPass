# =================== AIPass ====================
# Name: state_leak_content.py
# Description: State Leak Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
State Leak Standards Content Handler

Provides formatted State Leak standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_state_leak_standards() -> str:
    """Return formatted state_leak standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 18):[/bold cyan]",
        "  [green]No test leaks state into the next.[/green] Every patch through",
        "  monkeypatch, every file under tmp_path, nothing left in sys.modules.",
        "",
        "[bold cyan]WHY THIS ONE IS NOT LIKE THE OTHERS:[/bold cyan]",
        "  A leaking test [red]does not fail[/red]. It makes an UNRELATED test lie, in a",
        "  file its author never opened, and alphabetical order decides whether",
        "  anyone ever sees it. seedgo carried exactly one for months: 25 files",
        '  stub sys.modules["...bypass"] with a MagicMock and re-import a checker',
        "  against it. monkeypatch restores the sys.modules ENTRY -- but it cannot",
        "  undo a name another module already bound, and trigger_check does",
        "  [dim]from ...bypass.utils import matching_rule[/dim] at import time. test_bypass.py",
        "  then ran on mock.utils.matching_rule(). It ran FIRST in a forward run.",
        "  That is the only reason the suite was ever green.",
        "",
        "[bold cyan]WHAT IT CHECKS -- a write to shared state, at test time,[/bold cyan]",
        "[bold cyan]with nothing to put it back. Three shapes:[/bold cyan]",
        "",
        "  [red](a) A DIRECT WRITE[/red]",
        '      [dim]os.environ["AIPASS_BRANCH"] = "spawn"[/dim]',
        "      [dim]sys.path.insert(0, str(root))[/dim]",
        '      [dim]sys.modules["watchdog"] = fake[/dim]',
        "      [dim]log_watcher.WATCHDOG_AVAILABLE = False[/dim]   on an imported product module",
        '      [dim]setattr(log_watcher, "_queue", None)[/dim]',
        "",
        "  [red](b) A PATCHER STARTED AND NEVER STOPPED[/red]",
        '      [dim]p = patch("aipass.x.y"); p.start()[/dim]  with no stop()',
        "",
        "  [red](c) os.chdir WITH NO RESTORE[/red]",
        "",
        "[bold cyan]NEVER CONVICTED (each measured over 582 fleet test files):[/bold cyan]",
        "  [green]Every monkeypatch verb[/green] -- 4,890 uses: setattr 3,321, setitem 608,",
        "  setenv 415, chdir 257, delenv 178, delitem 104, delattr 5, undo 2.",
        "  A verb credits [bold]its own family only[/bold]: setenv says nothing about sys.path.",
        "  [green]with patch(...)[/green] (7,222) and [green]@patch[/green] decorators (2,078) -- they restore",
        "  on exit. Only the manual start() form can be left running.",
        "  [green]A restoring fixture IN SCOPE[/green] -- autouse covers the file; a named one",
        "  covers only the tests that REQUEST it by name. That distinction is the",
        "  difference between 39 honest acquittals and trusting a fixture nobody asked for.",
        "  [green]try/finally in the same function[/green] (141) -- item 18 done by hand, and it works.",
        "  [green]A sys.modules stub naming an aipass module[/green] -- item 8, import_site,",
        "  already convicts it. One habit is never charged twice.",
        "  [green]A write at IMPORT TIME[/green] -- happens once, before any test; every test in",
        "  the file sees the same thing. 22 sites in 20 files, COUNTED in the",
        "  passing message and never charged.",
        "  [green]A write to something the test built[/green] -- a local, a Mock, a tmp_path file.",
        "  [dim]mod.helper.return_value = x[/dim] configures an object, not the module: depth",
        "  ONE only, which is what drops 45 nominations from prax and trigger.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- the next test inherits it:[/red]",
        "  [dim]def test_disabled():[/dim]",
        "  [dim]    log_watcher.WATCHDOG_AVAILABLE = False[/dim]",
        "",
        "  [green]Good -- pytest puts it back:[/green]",
        "  [dim]def test_disabled(monkeypatch):[/dim]",
        '  [dim]    monkeypatch.setattr(log_watcher, "WATCHDOG_AVAILABLE", False)[/dim]',
        "",
        "[bold cyan]THE FIX -- the message names the one you need:[/bold cyan]",
        "  os.environ  ->  [green]monkeypatch.setenv / monkeypatch.delenv[/green]",
        "  sys.modules ->  [green]monkeypatch.setitem[/green]",
        "  sys.path    ->  [green]monkeypatch.syspath_prepend[/green]",
        "  an attribute->  [green]monkeypatch.setattr[/green]",
        "  the cwd     ->  [green]monkeypatch.chdir[/green]",
        "  a patcher   ->  [green]stop() in teardown, or addCleanup(p.stop)[/green]",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-22 over 582 fleet test files: 343 hits in 49 files.",
        "  145 are a write to a product module's attribute, 108 the same through",
        "  setattr(), 75 a sys.modules.pop(). @prax holds 177 and @trigger 115;",
        "  trigger/test_log_watcher.py alone carries 92.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per test file. A file with any hit scores 0 and the branch",
        "  number moves. Every hit rides on ONE check, because the checklist shows",
        "  the first failure and hides the rest.",
    ]

    json_handler.log_operation("content_served", {"standard": "state_leak"})
    return "\n".join(lines)
