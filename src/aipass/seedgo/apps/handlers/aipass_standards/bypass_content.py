# =================== AIPass ====================
# Name: bypass_content.py
# Description: Bypass Guidance Content Handler
# Version: 1.0.0
# Created: 2026-03-17
# Modified: 2026-03-17
# =============================================

"""
Bypass Guidance Content Handler

Not a scored standard — guidance content only.
Helps branches understand when and how to use .seedgo/bypass.json.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_bypass_standards() -> str:
    """Return formatted bypass guidance content with Rich markup."""
    lines = [
        "[bold red]BYPASS GUIDANCE[/bold red]",
        "",
        "[dim]This is not a scored standard. It's guidance for when and how[/dim]",
        "[dim]to use .seedgo/bypass.json in your branch.[/dim]",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHAT IS A BYPASS?[/bold cyan]",
        "",
        "  A bypass tells seedgo to skip a specific standard check for a",
        "  specific file. The file still gets audited on everything else —",
        "  only the bypassed standard is skipped.",
        "",
        "  Bypasses live in [green].seedgo/bypass.json[/green] at your branch root.",
        "  Every branch can have its own bypass file.",
        "",
        "─" * 70,
        "",
        "[bold cyan]WHEN TO USE A BYPASS[/bold cyan]",
        "",
        "  [yellow]A bypass is a last resort.[/yellow] Not a shortcut to 100%.",
        "",
        "  [green]Valid bypass cases:[/green]",
        "  [green]+[/green] [bold]Circular imports[/bold] — your module can't import something",
        "    without creating a dependency loop. You've confirmed the loop",
        "    exists and there's no clean way to break it.",
        "  [green]+[/green] [bold]Self-referencing standards[/bold] — trigger_check.py can't import",
        "    trigger (it checks trigger). The checker would fail on itself.",
        "  [green]+[/green] [bold]Design contracts[/bold] — a file is intentionally pure Python",
        "    with zero branch imports (e.g. bootstrap files). Adding the",
        "    import would break the design.",
        "  [green]+[/green] [bold]Documentation in strings[/bold] — a checker/content file shows",
        "    example patterns in Rich markup strings. The audit flags the",
        "    string content as a violation, but it's not executable code.",
        "",
        "  [red]NOT valid bypass cases:[/red]",
        "  [red]-[/red] \"It's too hard\" — try harder. Most standards have a clear",
        "    pattern. Read it: [dim]drone @seedgo standards_query aipass_standards <name>[/dim]",
        "  [red]-[/red] \"I don't understand the violation\" — ask seedgo. Email us.",
        "    Understanding comes before bypassing.",
        "  [red]-[/red] \"I just want 100%\" — the score reflects reality, not goals.",
        "    A bypass hides the problem, it doesn't fix it.",
        "  [red]-[/red] \"The standard seems wrong\" — that's a different issue.",
        "    Email seedgo. We'll investigate whether the checker or the",
        "    standard needs updating. Don't bypass a broken checker.",
        "",
        "─" * 70,
        "",
        "[bold cyan]BEFORE YOU BYPASS[/bold cyan]",
        "",
        "  Ask yourself:",
        "  1. Did I read the standard? [dim](drone @seedgo standards_query ...)[/dim]",
        "  2. Did I try the pattern it shows?",
        "  3. Is the failure genuinely unavoidable, not just unfamiliar?",
        "  4. Would another developer agree this can't be fixed?",
        "",
        "  If you answered no to any of these — keep trying.",
        "  If yes to all — bypass is appropriate.",
        "",
        "─" * 70,
        "",
        "[bold cyan]HOW TO ADD A BYPASS[/bold cyan]",
        "",
        "  Add an entry to [green].seedgo/bypass.json[/green] in your branch:",
        "",
        "  [dim]{[/dim]",
        "  [dim]  \"bypass\": [[/dim]",
        "  [dim]    {[/dim]",
        '  [dim]      "file": "apps/handlers/init/bootstrap.py",[/dim]',
        '  [dim]      "standard": "json_structure",[/dim]',
        '  [dim]      "reason": "Pure Python bootstrap — no branch imports by design"[/dim]',
        "  [dim]    }[/dim]",
        "  [dim]  ][/dim]",
        "  [dim]}[/dim]",
        "",
        "  [yellow]Fields:[/yellow]",
        '  [bold]file[/bold]     — relative path from branch root [dim](required)[/dim]',
        '  [bold]standard[/bold] — which standard to skip [dim](required)[/dim]',
        '  [bold]lines[/bold]    — specific line numbers [dim](optional — omit to bypass whole file)[/dim]',
        '  [bold]reason[/bold]   — why this bypass exists [dim](required — future you needs this)[/dim]',
        "",
        "─" * 70,
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Bypass handler: seedgo/apps/handlers/bypass/bypass_handler.py[/dim]",
        "  [dim]Config format: seedgo/apps/handlers/config/aipass_bypass.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "bypass"})
    return "\n".join(lines)
