# =================== AIPass ====================
# Name: named_encoding_content.py
# Description: Named Encoding Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-21
# Modified: 2026-09-21
# =============================================

"""
Named Encoding Standards Content Handler

Provides formatted Named Encoding standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_named_encoding_standards() -> str:
    """Return formatted named_encoding standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 21):[/bold cyan]",
        "  Every file read or write in a test [green]names its encoding[/green].",
        "",
        "  open(), Path.read_text() and Path.write_text() fall back to the",
        "  LOCALE's encoding. That is UTF-8 on this fleet's Linux and macOS",
        "  hosts and cp1252 on Windows through Python 3.12 -- so an unnamed",
        "  encoding passes on the machine the test was written on and raises",
        "  UnicodeDecodeError in the Windows CI lane.",
        "",
        "  [bold]The product's output is not ASCII. A test that cannot read it is broken,[/bold]",
        "  [bold]not the product.[/bold]",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Three shapes, all convicted, in files under [dim]tests/[/dim] (conftest included):",
        "",
        '  [red]open(path)[/red]  or  [red]open(path, "w")[/red]      any text mode, no encoding',
        "  [red]path.read_text()[/red]                     no encoding",
        "  [red]path.write_text(body)[/red]                no encoding",
        "",
        "[bold cyan]NEVER CONVICTED:[/bold cyan]",
        '  [green]Binary[/green] -- [dim]open(p, "rb")[/dim], [dim]read_bytes()[/dim], [dim]write_bytes()[/dim].',
        "  Bytes have no encoding to name.",
        "",
        '  [green]An encoding named positionally[/green] -- [dim]p.write_text(body, "utf-8")[/dim].',
        "  The signature gives it that slot; filling it is the rule satisfied.",
        "",
        '  [green]An encoding that is not utf-8[/green] -- [dim]p.read_text(encoding="latin-1")[/dim].',
        "  COUNTED and reported in the passing message, never convicted: a test",
        "  of latin-1 handling has to name latin-1.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- the fixture is written in whatever the host prefers:[/red]",
        '  [dim](tmp_path / "README.md").write_text(body)[/dim]',
        '  [dim]assert "--" in (tmp_path / "README.md").read_text()[/dim]',
        "",
        "  [green]Good -- the same two lines, encoding named:[/green]",
        '  [dim](tmp_path / "README.md").write_text(body, encoding="utf-8")[/dim]',
        '  [dim]assert "--" in (tmp_path / "README.md").read_text(encoding="utf-8")[/dim]',
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        '  [green]Add encoding="utf-8" to the call.[/green] There is no threshold and no',
        "  tuning: the argument is one keyword and it is always the same one.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  PR#774's Windows leg. Measured 2026-09-21 over 553 fleet test files:",
        "  918 hits in 82 files -- 703 write_text and 215 read_text. Zero bare",
        "  open() calls are missing an encoding; the fleet already learned that",
        "  half of the lesson.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per test file, since the audit's corpus took in tests/",
        "  (2026-09-21, owner ruling 21:20). A file with any hit scores 0 and the",
        "  branch number moves. The per-file checklist convicts on the write.",
    ]

    json_handler.log_operation("content_served", {"standard": "named_encoding"})
    return "\n".join(lines)
