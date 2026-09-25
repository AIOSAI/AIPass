# =================== AIPass ====================
# Name: retired_token_docstring_content.py
# Description: Retired Token Docstring Standards Content Handler
# Version: 1.1.0
# Created: 2026-09-25
# Modified: 2026-09-25
# =============================================

"""
Retired Token Docstring Standards Content Handler

Provides formatted Retired Token Docstring standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_retired_token_docstring_standards() -> str:
    """Return formatted retired_token_docstring standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (tests only, docstrings only):[/bold cyan]",
        "  The v4 keyword auditor (test_quality, removed in c1e0eeed) scored a test",
        "  file by grepping for keywords, and agents wrote them into docstrings as",
        "  bait. The gate is gone; the cargo misleads readers. A test docstring says",
        "  what the test proves, not which keywords a dead grep wanted.",
        "",
        "[bold cyan]THE VOCABULARY:[/bold cyan]",
        "  The retired STANDARD_CATEGORIES (apps/handlers/aipass_standards/",
        "  test_quality_check.py) from two commits, embedded verbatim as their union:",
        "  c1e0eeed^ (7 categories, 28 items) plus the 20 items only 7cd59aa4^ carries",
        "  (retired by DPLAN-0325 part B) -- 10 categories, 48 items. Nothing added:",
        "  [green]patterns, whitelist[/green] is not v4's. Plain English patterns ([green]yield[/green], [green]corrupt[/green], [green]operation[/green])",
        "  never count; code-shaped ones do ([red]capsys[/red], [red]StringIO[/red], [red].exists()[/red], [red]returns_dict[/red]).",
        "",
        "[bold cyan]TWO SHAPES, one finding per docstring:[/bold cyan]",
        "  T1 TOKEN LABEL: a run of v4 terms, one code-shaped, labelled token(s) --",
        "     [red]returns_dict, isinstance(result, dict), json_type tokens[/red]",
        "  T2 BAIT LIST: two or more code-shaped terms joined by , / and or --",
        "     [red]no_overwrite, already_exists[/red]",
        "  print_help and print_introspection are the fleet's CLI contract: they",
        "  lengthen a bait list, never make one. Code quoted in backticks is not a",
        "  list. Comments are not judged.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-25):[/bold cyan]",
        "  596 test files, c1e0eeed^ vocabulary: [red]7 convicted, 13 docstrings[/red] -- backup",
        "  2 / 8, api 3 / 3, commons 1 / 1, drone 1 / 1. Backup then cured its 8.",
        "  598 files, the union: [red]7 convicted, 8 docstrings[/red] -- api 3 / 3, memory 1 / 2,",
        "  commons 1 / 1, drone 1 / 1, aipass 1 / 1. The model file passes.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Drop the retired v4 keywords; say what the test proves.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "retired_token_docstring"})
    return "\n".join(lines)
