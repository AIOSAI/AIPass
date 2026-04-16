# =================== AIPass ====================
# Name: ruff_check_content.py
# Description: Ruff Check Standards Content Handler
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
Ruff Check Standards Content Handler

Provides formatted ruff_check standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_ruff_check_standards() -> str:
    """Return formatted ruff_check standards content with Rich markup.

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  Ruff is the primary linter for AIPass code. Zero violations is the bar.",
        "  Code that passes seedgo can still have 338 ruff violations — this standard",
        "  closes that gap. Advisory initially: surfaces violations, never blocks.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  Runs [dim]ruff check <branch>/apps/ --output-format=json[/dim] and scores",
        "  based on violation count. Covers the full ruff rule set: unused imports,",
        "  undefined names, style, complexity, security, and more.",
        "",
        "  [green]Graceful degradation:[/green]",
        "  - ruff not installed → SKIP (score 100, no penalty)",
        "  - subprocess timeout (60s) → FAIL with score 0",
        "  - JSON parse failure → FAIL with score 0",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Violation count → score:",
        "  [green]0 violations         → 100[/green]",
        "  [yellow]1–5 violations        → 95[/yellow]",
        "  [yellow]6–20 violations       → 85[/yellow]",
        "  [yellow]21–50 violations      → 70[/yellow]",
        "  [red]51–100 violations     → 50[/red]",
        "  [red]101+ violations       → 25[/red]",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold]",
        "  Runs once per branch — ruff walks [dim]apps/[/dim] tree itself.",
        "  Respects the branch's own [dim]pyproject.toml[/dim] or [dim]ruff.toml[/dim] if present.",
        "",
        "[bold cyan]ADVISORY MODE:[/bold cyan]",
        "  This standard is currently ADVISORY — it surfaces violation counts",
        "  and affects branch scores but never blocks an audit.",
        "  Promotion to REQUIRED once all branches are consistently clean.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  Violation message format:",
        "  [dim]3 violation(s) — E501 module.py:42, F401 handler.py:7, F841 utils.py:15[/dim]",
        "",
        "  [red]Common violations:[/red]",
        "  [dim]E501[/dim]  Line too long",
        "  [dim]F401[/dim]  Unused import",
        "  [dim]F841[/dim]  Local variable assigned but never used",
        "  [dim]E741[/dim]  Ambiguous variable name",
        "  [dim]F811[/dim]  Redefinition of unused name",
        "",
        "  Full rule reference: [dim]https://docs.astral.sh/ruff/rules/[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Run [dim]ruff check apps/[/dim] to see violations with context.",
        "  Run [dim]ruff check apps/ --fix[/dim] to auto-fix safe violations.",
        "  Re-run the audit to confirm score 100.",
        "",
        "[bold cyan]BYPASS — standard:[/bold cyan]",
        "  Add to [dim].seedgo/bypass.json[/dim] to skip the entire standard for a branch:",
        '  [dim]{"standard": "ruff_check", "file": "src/aipass/<branch>"}[/dim]',
        "",
        "[bold cyan]BYPASS — ruff-specific:[/bold cyan]",
        "  Add to [dim].seedgo/ruff_bypass.json[/dim] for fine-grained filtering.",
        "  All fields are optional — omit to match any value.",
        "",
        "  Skip all E501 in a file:",
        '  [dim]{"file": "apps/handlers/long_file.py", "code": "E501"}[/dim]',
        "",
        "  Skip a single violation at a specific line:",
        '  [dim]{"file": "apps/modules/thing.py", "code": "F401", "line": 42}[/dim]',
        "",
        "  Skip all violations in a file:",
        '  [dim]{"file": "apps/handlers/generated.py"}[/dim]',
        "",
        "  File content: a JSON array of rule objects.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: ruff_check.py[/dim]",
        "  [dim]Standards pack: seedgo standards (ruff_check)[/dim]",
        "  [dim]Ruff docs: https://docs.astral.sh/ruff/[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "ruff_check"})
    return "\n".join(lines)
