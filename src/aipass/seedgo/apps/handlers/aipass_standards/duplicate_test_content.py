# =================== AIPass ====================
# Name: duplicate_test_content.py
# Description: Duplicate Test Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Duplicate Test Standards Content Handler

Provides formatted Duplicate Test standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_duplicate_test_standards() -> str:
    """Return formatted duplicate_test standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class B, review of @backup 2026-09-22):[/bold cyan]",
        "  A test that adds nothing, because another test in the same file already",
        "  asserts everything it asserts. It doubles the maintenance and the",
        "  runtime and it widens no net. The reviewers found 24 across nine files.",
        "",
        "[bold cyan]TWO SHAPES, BOTH MECHANICAL, BOTH ON ONE CHECK:[/bold cyan]",
        "",
        "  [red]B1 CLONE[/red]     Two tests whose bodies are the same statements, docstring",
        "               dropped. The name differs and nothing else does.",
        "",
        "  [red]B2 SUBSUMED[/red]  Every statement of X also appears in Y, AND the statements",
        "               Y adds beyond X are only asserts or bindings that call",
        "               nothing.",
        "",
        "[bold cyan]THE RESTRICTION ON Y'S EXTRAS IS THE WHOLE RULE:[/bold cyan]",
        "  Without it, test_floor_applies_with_no_backupignore (no .backupignore at",
        "  all) reads as subsumed by test_floor_applies_when_the_file_never_names_tmp",
        "  (a .backupignore that omits tmp). But the second adds a [red]write_text[/red], and a",
        "  statement that changes the world makes it a DIFFERENT PRECONDITION, not a",
        "  superset. The reviewers called that pair SOUND, both rows.",
        "",
        "  A binding like [green]ignore = project / '.backupignore'[/green] changes nothing and does",
        "  not break the reading. That is the line: a call, a with, a loop — no. An",
        "  assert or a pure binding — yes.",
        "",
        "[bold cyan]WHAT THIS RULE HONESTLY DOES NOT SEE:[/bold cyan]",
        "  [red]Of @backup's 24 DUPLICATE rows it convicts TWO.[/red] The other 22 are SEMANTIC",
        "  duplication — the same claim in a different spelling — and no shape rule",
        "  reaches them. test_drive_pipeline.py:783 and test_drive_mocked.py:49 pin",
        "  identical behaviour with [] versus drive_sync.PRIMARY_COMMAND,",
        "  capsys.readouterr().out versus a tuple unpack, and one extra",
        "  assert err == ''. A reader sees one test twice; an AST sees two programs.",
        "",
        "  The two it does convict are both confirmed rows and it invents none:",
        "  [green]test_cli_routing.py:250[/green] ('identical claim to line 163') as SUBSUMED, and",
        "  [green]test_dead_cwd_imports.py:828[/green] ('line-for-line the same assertion as 469')",
        "  as a CLONE.",
        "",
        "[bold cyan]ONE FILE, NOT THE BRANCH:[/bold cyan]",
        "  Cross-file duplication is real and measured — [green]21 files, 22 exact clones[/green]",
        "  fleet-wide, and @backup's six drive_pipeline / drive_mocked pairs are the",
        "  kind of thing it would name. It is left out because the verdict would",
        "  have to be reported against one of two files and this lane hands the",
        "  checker one path at a time. It wants a branch-level lane.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over 559 fleet test files):[/bold cyan]",
        "  [green]59 files, 92 hits, 6.8s[/green] — 57 clones and 35 subsumed.",
        "  Top three: api 8 files, seedgo 8, trigger 6. Worst single file:",
        "  devpulse/test_git_gate.py at 6.",
        "  A widened B2 accepting ANY extra statement in Y finds 130 files and 204",
        "  hits and convicts the SOUND pair above. That extra yield is bought with a",
        "  false conviction rate the measurement cannot bound, so the narrow form",
        "  ships and the wide number is reported.",
        "",
        "[bold cyan]CONSTANTS ARE KEPT:[/bold cyan]",
        "  '*.log' and '*.txt' are two different claims about the product. A",
        "  normalisation that blanked constants convicted [red]345 files with 2,415 hits[/red].",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  If every statement of your test already appears, verbatim, in another",
        "  test in the same file, and that other test's only additions are asserts,",
        "  your test excludes no failure the other does not already exclude. There",
        "  is no threshold and nothing to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the test, its line, and the test that",
        "  already covers it, on ONE check. The FIRST by line is the original and",
        "  every later copy is the finding — stable under an edit elsewhere in the",
        "  file, which a 'shortest wins' rule is not. A clone is never also charged",
        "  as subsumed.",
    ]

    json_handler.log_operation("content_served", {"standard": "duplicate_test"})
    return "\n".join(lines)
