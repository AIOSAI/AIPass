# =================== AIPass ====================
# Name: unused_conftest_fixture_content.py
# Description: Unused Conftest Fixture Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Unused Conftest Fixture Standards Content Handler

Provides formatted Unused Conftest Fixture standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_unused_conftest_fixture_standards() -> str:
    """Return formatted unused_conftest_fixture standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class G, review of @backup 2026-09-22):[/bold cyan]",
        "  A fixture defined in a branch's conftest.py, not autouse, that no test and",
        "  no other fixture in the branch ever requests. It is apparatus nothing uses",
        "  — dead weight that reads as shared infrastructure, so the next author",
        "  extends it instead of deleting it.",
        "",
        "  @backup's tests/conftest.py carries three: [red]temp_dir[/red] (80),",
        "  [red]sample_data[/red] (92), [red]mock_logger[/red] (176).",
        "",
        "[bold cyan]THREE WAYS TO REQUEST A FIXTURE — all three count as use:[/bold cyan]",
        "  by [green]PARAMETER NAME[/green] on a test or on another fixture — the ordinary way",
        "  by [green]@pytest.mark.usefixtures('name')[/green] — a string",
        "  by [green]request.getfixturevalue('name')[/green] — also a string",
        "",
        "  Both string forms are why every string literal in the branch's tests is",
        "  read as a possible request. A rule that reads only parameter names convicts",
        "  every fixture used through usefixtures or getfixturevalue.",
        "",
        "  [green]autouse=True is never convicted.[/green] Nothing requests it by design; that is",
        "  what autouse means.",
        "",
        "[bold cyan]BUILT ALONE, NOT INSIDE conftest_fixtures:[/bold cyan]",
        "  conftest_fixtures is all_files and judges one conftest.py in isolation — its",
        "  two rules are about what that file itself contains. This question cannot be",
        "  answered from that file at all: whether a fixture is requested is a fact",
        "  about the WHOLE branch's tests/ tree, so the rule is branch_level. Folding",
        "  it in would have meant a file-level rule secretly reading its siblings —",
        "  exactly the coupling the two scopes exist to keep apart.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over the fleet):[/bold cyan]",
        "  [green]13 conftest files, 22 fixtures.[/green]",
        "  backup 3 · drone 3 · commons 2 · daemon 2 · memory 2 · skills 2 · spawn 2",
        "  · ai_mail, aipass, api, cli, devpulse, flow at 1 each.",
        "",
        "  The review's first cut said 17 files and 51. The gap is the three request",
        "  forms above. @backup's three land at 80, 92 and 176; the review cites the",
        "  @pytest.fixture decorator line, this rule cites the def.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  If no parameter, no usefixtures string and no getfixturevalue string in the",
        "  entire branch names the fixture, pytest can never construct it. Deleting it",
        "  cannot turn the suite red.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per BRANCH — the conftest against the whole tests/ tree. Every hit",
        "  names the file, the line and the fixture, on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]request it in a test, or delete it.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "unused_conftest_fixture"})
    return "\n".join(lines)
