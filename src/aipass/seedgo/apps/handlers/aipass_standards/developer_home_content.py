# =================== AIPass ====================
# Name: developer_home_content.py
# Description: Developer Home Standards Content Handler
# Version: 1.0.0
# Created: 2026-10-04
# Modified: 2026-10-04
# =============================================

"""
Developer Home Standards Content Handler

Provides formatted developer_home standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_developer_home_standards() -> str:
    """Return formatted developer_home standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  AIPass is a PUBLIC repo. No tracked text file names a person, and a home",
        "  directory names a person the same way a name does (owner, 2026-10-04).",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Every line of a text file -- .py .md .json .toml .yml .yaml .sh .txt, or no",
        "  suffix at all -- for a home directory whose segment could be somebody's login:",
        "",
        "  1. [red]POSIX[/red]: /home/<login>, with or without the trailing slash",
        "  2. [red]macOS[/red]: /Users/<login>",
        "  3. [red]Windows[/red]: <drive>:\\Users\\<login> -- one backslash, two, or a slash; any case",
        "",
        "[bold cyan]NOT HARDCODED_PATH:[/bold cyan]",
        "  hardcoded_path is about the PORTABILITY of code, so it skips comments and",
        "  docstrings. This standard is about NAMING A PERSON, and prose names a person",
        "  exactly as code does: comments, docstrings, markdown and JSON are all read.",
        "",
        "[bold cyan]WHAT PASSES:[/bold cyan]",
        "  - a segment that names nobody: user, username, someone, carol, alice, you, me,",
        "    example, test, aipass, runner, runneradmin, ... (NEUTRAL_SEGMENTS)",
        "  - any single-character segment -- an initial names nobody findable",
        "  - any segment holding < { $ % * -- a template slot: <user>, {name}, $USER",
        "  - a home inside a URL (the character before the slash is a word or a dot)",
        "  - a non-text kind (.png) and a file holding a NUL byte: declined, not read",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [green]Good -- a placeholder:[/green]  [dim]/home/<user>/Projects/AIPass[/dim]",
        "  [green]Good -- built at run time:[/green]  [dim]Path.home() / 'Projects'[/dim]",
        "  [red]Bad -- the same path with a real login where <user> stands[/red]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold], APPLIES_TO = [bold]everywhere[/bold], TEXT_FILES = True",
        "  The checklist judges a non-.py text file with it; the audit reads .py files;",
        "  drone @seedgo home-paths scan reads the whole tracked tree (the CI gate)",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One check per file. [green]100[/green] = none found, [red]0[/red] = one or more",
        "  Reports up to 3 hits as L<line>: <matched>",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  A line rule in the owning branch's [dim].seedgo/bypass.json[/dim], with the reason --",
        "  for a file whose home paths ARE the input under test, never for a real one.",
        '  [dim]{{"file": "tests/test_x.py", "standard": "developer_home", "lines": [42],[/dim]',
        '  [dim] "reason": "the checker\'s own input"}}[/dim]',
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: developer_home_check.py  Doc: developer_home.md[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "developer_home"})
    return "\n".join(lines)
