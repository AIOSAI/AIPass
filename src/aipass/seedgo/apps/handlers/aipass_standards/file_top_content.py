# =================== AIPass ====================
# Name: file_top_content.py
# Description: Test File Top Standards Content Handler
# Version: 1.1.0
# Created: 2026-09-22
# Modified: 2026-09-27
# =============================================

"""
Test File Top Standards Content Handler

Provides formatted Test File Top standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_file_top_standards() -> str:
    """Return formatted file_top standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, items 5, 6 and 7):[/bold cyan]",
        "  A test file opens the same way every time, [green]top to bottom[/green]:",
        "",
        "  [green]1.[/green] the META header block, first, banner word AIPass (meta_check's rule)",
        "  [green]2.[/green] then the module docstring: ONE line, naming the subject as a path",
        "  [green]3.[/green] then the declared pass: what is NOT tested here, and what covers it",
        "",
        "  Three items, one shape, one checker with three sub-rules -- the way",
        "  imports carries six. The ORDER is half the rule.",
        "",
        "[bold cyan]THE CANONICAL TOP (tests/test_readme_update.py):[/bold cyan]",
        "  [dim]# =================== AIPass ====================[/dim]",
        "  [dim]# Name: test_readme_update.py[/dim]",
        "  [dim]# Description: Template v1 model -- readme_update module[/dim]",
        "  [dim]# Version: 2.2.0[/dim]",
        "  [dim]# Created: 2026-09-20[/dim]",
        "  [dim]# Modified: 2026-09-21[/dim]",
        "  [dim]# =============================================[/dim]",
        "",
        '  [dim]"""Tests for apps/modules/readme_update.py and the handlers it drives."""[/dim]',
        "",
        "  [dim]# The declared pass -- what is NOT tested here, and what covers it instead:[/dim]",
        "  [dim]# seedgo: no-test-needed(ruff) -- that every file in handlers/readme/ parses[/dim]",
        "  [dim]# seedgo: no-test-needed(constant) -- SECTION_NAMES' display strings[/dim]",
        "",
        "[bold cyan]NOTHING IS CHARGED TWICE:[/bold cyan]",
        "  [dim]meta[/dim] and [dim]documentation[/dim] are APPLIES_TO = production and never see a",
        "  test file. [dim]template[/dim] is branch_level and advisory: it reads the prompt,",
        "  README and passport for stub markers, not a file's top. These three",
        "  items had no checker at all until this one.",
        "",
        "[bold cyan]conftest.py IS JUDGED ON ITEM 5 ONLY:[/bold cyan]",
        "  Decided from the template's text. Item 6 wants one line naming the",
        "  SUBJECT and a conftest has no subject; item 7 asks what is NOT tested",
        "  HERE and a conftest holds no tests. The header still binds: every",
        "  Python file in the fleet carries the block.",
        "",
        "[bold cyan]THE THREE MESSAGES:[/bold cyan]",
        "  [red]item 5 META header:[/red] the file opens with code / with a docstring /",
        "  the banner line is X, not meta_check's AIPass line / missing Created, Modified",
        "  [red]item 6 subject docstring:[/red] missing / 3 lines, not 1 / names no path",
        "  [red]item 7 declared pass:[/red] missing / line N is not a marker /",
        "  the block is above the docstring",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-22 over 579 fleet test files: 367 open with the block,",
        "  223 carry a one-line docstring, and 7 carry a declared pass. The",
        "  template says why the third matters: in the trial that slot is where",
        "  six tests got dropped -- writing it does the deciding.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per test file, since the audit's corpus took in tests/",
        "  (2026-09-21, owner ruling 21:20). A file missing any of the three",
        "  scores 0, and all three messages print together so an author sees",
        "  which is missing. The per-file checklist convicts on the write.",
    ]

    json_handler.log_operation("content_served", {"standard": "file_top"})
    return "\n".join(lines)
