# =================== AIPass ====================
# Name: oversize_test_file_content.py
# Description: Oversize Test File Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""
Oversize Test File Standards Content Handler

Provides formatted Oversize Test File standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_oversize_test_file_standards() -> str:
    """Return formatted oversize_test_file standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test file is read by someone looking for ONE subject. Past a few",
        "  thousand lines nobody reads it - they grep it, find a similar test,",
        "  and copy it. That is how a weak shape spreads inside a branch.",
        "",
        "  Cap: [bold]1,500 code lines[/bold] per test file.",
        "",
        "[bold cyan]FIXTURE PAYLOAD DOES NOT COUNT:[/bold cyan]",
        "  Every line inside a multi-line string literal is subtracted before",
        "  the cap applies - sample JSON, a captured log, a rendered README,",
        "  and [green]docstrings too[/green].",
        "",
        "  This is deliberate. Charging for payload would push authors to hide",
        "  fixtures in another file rather than split anything, and charging",
        "  for docstrings would make the size rule a reason to delete the",
        "  sentence naming the bug a test pins. Both are worse than a long file.",
        "",
        "  [dim]tests/test_import_dead_cwd.py: 2,718 total - 1,533 payload = 1,185 code -> PASSES[/dim]",
        "",
        "[bold cyan]WHY 1,500:[/bold cyan]",
        "  Measured across the fleet 2026-09-20: [bold]538[/bold] test files,",
        "  median [bold]378[/bold] code lines, 90th percentile [bold]1,161[/bold].",
        "  1,500 sits above nine files in ten and convicts [bold]34[/bold] - the",
        "  tail, not the body. It is also the cap the product side already uses,",
        "  so tests and modules are held to one number.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad:[/red]",
        "  [dim]tests/test_pytest_quality_pack.py - 4,595 code lines of 10,524[/dim]",
        "",
        "  Violation message example:",
        "  [dim]4595 code lines, cap 1500 (10524 total, 5929 of string payload[/dim]",
        "  [dim]already excluded) - split it along the unit under test...[/dim]",
        "",
        "[bold cyan]HOW TO FIX - and the gate you will meet:[/bold cyan]",
        "  Split along [bold]the unit under test[/bold], one file per subject -",
        "  never by line count, and never into `_part2`.",
        "",
        "  [yellow]The cure needs NEW test files, and the hooks test-write gate[/yellow]",
        "  [yellow]refuses those by policy (.aipass/test_write_policy.json).[/yellow]",
        "",
        "  So: [bold]do not route around the gate.[/bold] Mail @devpulse naming the",
        "  file, its code-line count, and the subjects you would split it into.",
        "  Moving tests is not adding them - a split that adds no test function",
        "  is the case to make.",
        "",
        "  If the file is large because it pins rules that are themselves being",
        "  retired, the retire comes first and the split may not be needed at all.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  APPLIES_TO = [bold]tests[/bold] -- test files only.",
        "",
        "  The audit's corpus is [dim]apps/[/dim], so this standard scores NOTHING in",
        "  [dim]audit aipass[/dim] and no branch's number moved when it landed. It",
        "  convicts in the per-file [dim]checklist[/dim] lane on the write that grows",
        "  the file, and reports the standing backlog unscored, naming the",
        "  largest offender so there is somewhere to start.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (at or under cap) or [red]fail[/red] (over).",
        "  Score: 100 if passed, 0 if failed.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "oversize_test_file", "file": "tests/test_big.py"}[/dim]',
        "",
        "  A generated test file is the honest bypass case: nobody reads it and",
        "  nobody splits it. Write the generator's name in the reason.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: docs/test_gold_standard.md[/dim]",
        "  [dim]Checker: oversize_test_file_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "oversize_test_file"})
    return "\n".join(lines)
