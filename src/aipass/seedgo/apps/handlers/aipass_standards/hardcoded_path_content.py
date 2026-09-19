# =================== AIPass ====================
# Name: hardcoded_path_content.py
# Description: Hardcoded Absolute Path Standards Content Handler
# Version: 1.0.0
# Created: 2026-06-18
# Modified: 2026-06-18
# =============================================

"""
Hardcoded Absolute Path Standards Content Handler

Provides formatted hardcoded path standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_hardcoded_path_standards() -> str:
    """Return formatted hardcoded_path standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  AIPass is a cross-platform PUBLIC repo. Source code must NEVER contain",
        "  hardcoded absolute home-directory paths. They leak usernames, break on",
        "  other machines, and violate cross-platform portability.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Scans Python source lines (excluding comments and docstrings) for:",
        "",
        "  1. [red]POSIX home paths[/red]: /home/<user>/...",
        "  2. [red]macOS home paths[/red]: /Users/<user>/...",
        "  3. [red]Windows home paths[/red]: C:\\Users\\<user>\\...",
        "  4. [red]Dash-encoded POSIX[/red]: -home-<user>-... (Claude Code project-dir encoding)",
        "  5. [red]Dash-encoded macOS[/red]: -Users-<user>-... (Claude Code project-dir encoding)",
        "",
        "[bold cyan]FALSE-POSITIVE GUARDS:[/bold cyan]",
        "  - [dim]# comments[/dim] are skipped (line-level)",
        "  - [dim]Docstrings[/dim] are skipped (triple-quote blocks)",
        "  - [dim]__init__.py[/dim] files are skipped",
        "  - [dim]Test files[/dim] are NOT skipped by default -- use line-level bypass",
        "    for test fixtures that must assert on literal path strings",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "",
        "  [red]Bad -- hardcoded POSIX home:[/red]",
        '  [dim]ROOT = "/home/someone/Projects/AIPass"[/dim]',
        "",
        "  [red]Bad -- dash-encoded home (leaks username):[/red]",
        '  [dim]dirs = ["-home-someone-Projects-AIPass-src-aipass-memory"][/dim]',
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "",
        "  [green]Good -- use Path(__file__) or env:[/green]",
        "  [dim]ROOT = Path(__file__).resolve().parents[3][/dim]",
        "  [dim]ROOT = Path(os.environ['AIPASS_HOME'])[/dim]",
        "",
        "  [green]Good -- use pathlib for home:[/green]",
        "  [dim]home = Path.home()[/dim]",
        "",
        "  [green]Good -- test fixtures with generic paths:[/green]",
        '  [dim]path = "/home/user/Projects/AIPass/..."  # generic, no real username[/dim]',
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold]",
        "  Checks every .py file in the branch",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file (Hardcoded path)",
        "  [green]100[/green] = no hardcoded absolute home paths found",
        "  [red]0[/red] = one or more hardcoded paths found",
        "  Reports up to 3 offending line numbers with descriptions",
        "  Overall pass threshold: [yellow]75%[/yellow]",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Via [dim].seedgo/bypass.json[/dim] -- supports standard, file-level,",
        "  and line-level bypass rules",
        "",
        "  [dim]Example bypass entry (test fixture):[/dim]",
        '  [dim]{{"file": "tests/test_paths.py", "standard": "hardcoded_path",[/dim]',
        '  [dim] "lines": [42, 43], "reason": "Test asserts on literal path"}}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: seedgo standards pack (hardcoded_path)[/dim]",
        "  [dim]Checker: hardcoded_path_check.py[/dim]",
        "  [dim]House rule: cross-platform, no hardcoded paths, use pathlib[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "hardcoded_path"})
    return "\n".join(lines)
