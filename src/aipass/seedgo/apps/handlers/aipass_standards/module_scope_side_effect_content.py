# =================== AIPass ====================
# Name: module_scope_side_effect_content.py
# Description: Module Scope Side Effect Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Module Scope Side Effect Standards Content Handler

Provides formatted Module Scope Side Effect standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_module_scope_side_effect_standards() -> str:
    """Return formatted module_scope_side_effect standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Module-level code in a test_*.py runs at COLLECTION -- once, before any test,",
        "  in whatever order pytest imports files. A side effect there leaks into every",
        "  test in the session; a failure there takes the whole file down.",
        "",
        "[bold cyan]WHAT IS MODULE SCOPE:[/bold cyan]",
        "  Top-level statements (inside top-level if/try/with/for too, never under",
        "  [green]if __name__ == '__main__':[/green]), class bodies, decorator expressions, and",
        "  default-argument expressions. Function and method BODIES are not.",
        "",
        "[bold cyan]THE EIGHT SHAPES:[/bold cyan]",
        "  [red]audit_hook[/red] sys.addaudithook  [red]host_read[/red] Path.home(), Path.cwd(), os.getcwd(),",
        "  os.path.expanduser  [red]environ_write[/red] os.environ writes, putenv, unsetenv",
        "  [red]sys_modules_write[/red]  [red]sys_path_write[/red]  [red]module_attr_write[/red] X.attr = / setattr(X, ...)",
        "  on an imported X  [red]cwd_change[/red] os.chdir  [red]global_recorder[/red] a name a function",
        "  rebinds via `global`. Constants, pytestmark, fixtures and imports are not judged.",
        "",
        "[bold cyan]NOT JUDGED:[/bold cyan]",
        "  [yellow]conftest.py[/yellow] -- its module scope is the declared once-per-session harness",
        "  (template v1 conftest C0 requires the AIPASS_TEST_LOG_DIR write there).",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  557 test files judged. [red]15 convicted, 32 hits[/red] -- sys_modules_write 16,",
        "  host_read 6, global_recorder 5, sys_path_write 4, audit_hook 1. Judged, all 18",
        "  conftest.py files would score 0 (18 of 21 hits the C0 line). The model file passes.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Move it into a fixture (monkeypatch / tmp_path) or into the test that needs it.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "module_scope_side_effect"})
    return "\n".join(lines)
