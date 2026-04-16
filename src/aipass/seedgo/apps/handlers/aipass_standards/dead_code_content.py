# =================== AIPass ====================
# Name: dead_code_content.py
# Description: Dead Code Standards Content Handler
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""
Dead Code Standards Content Handler

Provides formatted Dead Code standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_dead_code_standards() -> str:
    """Return formatted dead_code standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Every file in apps/modules/ and apps/handlers/ must be referenced",
        "  somewhere in the branch. Unreferenced files are dead weight --",
        "  they confuse navigation, burn context, and rot over time.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Operates at [bold]branch level[/bold] (not per-file). The checker:",
        "",
        "  1. Collects all .py files from [dim]apps/modules/[/dim] and [dim]apps/handlers/[/dim]",
        "     (skipping __init__.py, __pycache__, .archive, etc.)",
        "  2. Reads ALL .py content under [dim]apps/[/dim] into a search corpus",
        "  3. For each collected file, checks whether it is referenced by:",
        "",
        "     [green]a)[/green] Full dotted import path [dim](aipass.branch.apps.handlers.foo)[/dim]",
        "     [green]b)[/green] Relative dotted path [dim](handlers.foo)[/dim]",
        "     [green]c)[/green] Import statement containing the module stem",
        "     [green]d)[/green] importlib.import_module reference",
        '     [green]e)[/green] Glob-based auto-discovery [dim](glob("*_check.py"), glob("*.py"))[/dim]',
        '     [green]f)[/green] Filename string literal [dim]("my_handler.py")[/dim]',
        "",
        "  [yellow]Always considered used:[/yellow] __init__.py, entry point files,",
        "  and glob-discovered patterns (*_check.py, *_content.py).",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  A file with zero references in the branch source is flagged dead.",
        "",
        "  [red]Bad -- file exists but nothing imports or references it:[/red]",
        "  [dim]apps/handlers/legacy/old_processor.py  -- 0 references[/dim]",
        "",
        "  [green]Good -- file is imported or glob-discovered:[/green]",
        "  [dim]from aipass.branch.apps.handlers.json import json_handler[/dim]",
        '  [dim]# or discovered via glob("*_check.py")[/dim]',
        "",
        "  Violation message example:",
        "  [dim]3/25 files unreferenced: handlers/old/foo.py, modules/unused.py, ...[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  1. Review each flagged file:",
        "     [green]Still needed?[/green] Add a proper import or reference",
        "     [green]Obsolete?[/green] Delete the file or move to .archive/",
        "  2. Re-run the audit to confirm all files are referenced",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  This checker runs once per branch (not per file). It receives the",
        "  branch root path and scans the entire apps/ tree.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Score = referenced_files / total_files * 100",
        "  Threshold: score >= 75 to pass overall",
        "  A branch with 20/25 files referenced scores 80 (passes).",
        "  A branch with 15/25 files referenced scores 60 (fails).",
        "",
        "[bold cyan]SKIP DIRECTORIES:[/bold cyan]",
        "  The following directories are excluded from scanning:",
        "  [dim]__pycache__, .archive, .mypy_cache, .ruff_cache, .pytest_cache,[/dim]",
        "  [dim]json_templates, logs, tools, .venv, venv, node_modules, .git,[/dim]",
        "  [dim]site-packages, .trinity, .aipass, .ai_mail.local, .spawn,[/dim]",
        "  [dim]backups, reports, docs, tests, .sorting_unprocessed[/dim]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "dead_code", "file": "path/to/file.py"}[/dim]',
        "  Entire standard or individual files can be bypassed.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (dead_code)[/dim]",
        "  [dim]Checker: dead_code_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "dead_code"})
    return "\n".join(lines)
