# =================== AIPass ====================
# Name: self_set_assert_content.py
# Description: Self Set Assert Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-23
# Modified: 2026-09-23
# =============================================

"""
Self Set Assert Standards Content Handler

Provides formatted Self Set Assert standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_self_set_assert_standards() -> str:
    """Return formatted self_set_assert standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class E):[/bold cyan]",
        "  A test writes a value, then asserts the value is there.",
        "    [red]r.files_deleted = 5[/red]",
        "    [red]assert r.files_deleted == 5[/red]",
        "  Nothing about the product decided that. Python's attribute assignment did,",
        "  and it would pass against an empty class.",
        "",
        "[bold cyan]THE THREE SHAPES:[/bold cyan]",
        "  [green]target.attr = X[/green]      then assert target.attr == X",
        "  [green]d[key] = X[/green]           then assert d[key] == X",
        "  [green]obj = C(attr=X)[/green]      then assert obj.attr == X",
        "  The constructor kwarg is 14 of the fleet's 15 — the shape nobody sees while",
        "  writing it.",
        "",
        "[bold cyan]THE JUDGEMENT THIS RULE MAKES:[/bold cyan]",
        "  Score only when NOTHING RAN in between. If a call sits between the",
        "  assignment and the assertion, the assert is a durability oracle — 'the",
        "  product did not clobber this' — and that is a real claim. test_drive_",
        "  pipeline.py sets client.file_tracker, calls get_or_create_backup_folder(),",
        "  then asserts the tracker is unchanged: that is the test's whole point.",
        "  Those ride in the passing message as a count.",
        "",
        "[bold cyan]THE OTHER LINE IT HOLDS:[/bold cyan]",
        "  The comparison must be [green]==[/green] against the SAME literal. [green]client._drive_service =",
        "  service[/green] followed by [green]assert client.drive_service is service[/green] sets the backing",
        "  field and asserts the PROPERTY — different name, and 'is' not '=='. The",
        "  product's getter is under test there, so the rule declines it.",
        "",
        "[bold cyan]THE OTHER HALF OF weak_oracle:[/bold cyan]",
        "  weak_oracle reads a self-set assert as STRONG, because it is a real value",
        "  comparison. This rule is the other half of that verdict: the comparison is",
        "  strong, the value is the test's own.",
        "",
        "[bold cyan]CHECK FIRST (2026-09-23, 572 fleet test files):[/bold cyan]",
        "  [green]5 files scored, 15 hits; 8 more reported in 5 other files.[/green] Shapes:",
        "  constructor kwarg 14, attribute assign 1. The largest single cluster is one",
        "  Event built with eight keyword arguments, all eight read straight back.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  With no call in between there is no product between the write and the read.",
        "  The assertion is a statement about Python, and it passes with the product",
        "  deleted.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file. Every hit names the assert line, the path and the shape,",
        "  on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]Assert what the product computed, not what this test just wrote.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "self_set_assert"})
    return "\n".join(lines)
