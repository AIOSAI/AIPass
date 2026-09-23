# =================== AIPass ====================
# Name: declared_pass_contradiction_content.py
# Description: Declared Pass Contradiction Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Declared Pass Contradiction Standards Content Handler

Provides formatted Declared Pass Contradiction standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_declared_pass_contradiction_standards() -> str:
    """Return formatted declared_pass_contradiction standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class H, template v1 item 4):[/bold cyan]",
        "  A declared pass is a promise about what this file does NOT cover. It is",
        "  worth exactly as much as its accuracy. Two ways of breaking it are",
        "  mechanical, and both are scored.",
        "",
        "[bold cyan]H1 — THE DECLARATION IS CONTRADICTED:[/bold cyan]",
        "  The file declares a constant's value untested, then asserts that value as",
        "  a literal. test_drive_pipeline.py declares [green]TRACKER_FILENAME[/green] while three",
        "  asserts pin [red]'drive_tracker.json'[/red].",
        "",
        "[bold cyan]H2 — THE DECLARATION NAMES NOTHING:[/bold cyan]",
        "  test_ceiling_guard.py declares [red]DEFAULT_MAX_SIZE_GB[/red]; the constant is",
        "  [green]DEFAULT_MAX_TOTAL_GB[/green]. A promise about a symbol that does not exist covers",
        "  nothing, and the real constant stays uncovered behind it.",
        "",
        "[bold cyan]THE JUDGEMENT THIS RULE MAKES:[/bold cyan]",
        "  USING a declared constant BY NAME is consistent with declaring it untested.",
        "  [green]assert CURE in message[/green] survives any change to CURE's text — it pins the",
        "  wiring, not the prose. ASSERTING ITS VALUE does not: [red]assert x == 'drive_",
        "  tracker.json'[/red] pins exactly what the file said it would not.",
        "",
        "[bold cyan]SEARCH THE SOURCE TEXT, NOT THE AST's NAMES:[/bold cyan]",
        "  A declared symbol can be an environment variable (a string, never an",
        "  identifier), an annotated dataclass field, or a directory segment in a path.",
        "  Collecting def/class/Name/Attribute nodes missed all three and convicted",
        "  [red]86 live symbols[/red]; a word-boundary search of apps/ leaves [green]3[/green], all real.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-23, 572 fleet test files):[/bold cyan]",
        "  37 files carry a declared pass at all, 137 lines between them.",
        "  [green]7 files, 8 scored[/green] — 5 contradicted constants, 3 absent names.",
        "",
        "[bold cyan]REPORTED WITH A COUNT, CHARGED TO NOBODY:[/bold cyan]",
        "  106 in all: 39 lines that name no symbol — prose is a legitimate",
        "  declaration — and 67 dotted stdlib names (Path.resolve, os.scandir), where",
        "  a test's incidental use of the call is indistinguishable from testing it.",
        "  3 declared LIBRARIES whose call feeds an assert. Not scored on purpose:",
        "  [green]no_product_call[/green] already convicts test_ignore_pathspec.py:46, the one case",
        "  where the library really is the subject, and the other two files score 100",
        "  there — which proves their library call is the test's reading tool.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  Both scored forms are contradictions between two statements in the same",
        "  file. There is no threshold and nothing to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the declared line, the symbol and what is",
        "  wrong, on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Assert the constant by name, or drop the line that declares it untested.[/green]",
        "  [green]Name the symbol that exists, or drop the line.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "declared_pass_contradiction"})
    return "\n".join(lines)
