# =================== AIPass ====================
# Name: mock_console_content.py
# Description: Mock Console Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Mock Console Standards Content Handler

Provides formatted Mock Console standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_mock_console_standards() -> str:
    """Return formatted mock_console standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 14):[/bold cyan]",
        "  The edge is [green]real[/green], not [red]mocked[/red].",
        "",
        "  The product's consoles write to sys.stdout and sys.stderr AT PRINT",
        "  TIME, so pytest's capsys captures every one of them -- the cli header",
        "  channel included. A test asserts on capsys, [bold]by channel[/bold].",
        "",
        "[bold cyan]WHAT A MOCK CONSOLE COSTS:[/bold cyan]",
        '  [dim]console.print.assert_called_with("[[red]]Refused")[/dim]',
        "",
        "  That passes when the product hands Rich a string. It also passes when",
        "  the string never reaches a terminal, when the console was the wrong",
        "  one, when the markup is malformed, when stderr went to stdout. The",
        "  assertion measures the CALL; what the user reads is the CHANNEL.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  A console stand-in [bold]installed over[/bold] the product, or handed to it,",
        "  in a file under [dim]tests/[/dim]:",
        "",
        '  [red]@patch(f"{MOD}.console")[/red]                    297 fleet sites',
        '  [red]monkeypatch.setattr(mod, "console", Mock())[/red]  70',
        "  [red]cli_mod.console = MagicMock()[/red]                30",
        '  [red]patch.object(display, "CONSOLE", cons)[/red]       26',
        "  [red]product_call(console=MagicMock())[/red]             9",
        "",
        "  A patch given NO replacement is the same finding -- mock hands the",
        "  product a MagicMock by default, and 284 of the 432 sites take it.",
        "",
        "  Three kinds of stand-in are named in the message: [red]a Mock[/red],",
        "  [red]a Rich Console on a buffer[/red] (Console(file=buf) still takes the words",
        "  out of the channel), and [red]a fake console class[/red] with a print method.",
        "",
        "[bold cyan]NEVER CONVICTED:[/bold cyan]",
        "  [green]capsys and capfd[/green] -- 79 of 580 fleet test files already read the",
        "  channel. They are the fix, not the offence.",
        "  [green]A console the PRODUCT builds[/green] -- this checker never reads apps/.",
        '  [green]A restore[/green] -- [dim]setattr(module, "console", original)[/dim] puts the real',
        "  one BACK, the opposite of the habit.",
        "  [green]A Mock for something that is not a console[/green] -- the install site has",
        "  to be console-named, and that means one qualifier at most, so the",
        "  helper _print_event_to_console is not a console.",
        "  [green]A renderer test[/green] (8 consoles, 4 files) -- a Console(file=...) the test",
        "  builds and prints to ITSELF, never installing it. The subject there is",
        "  what RICH does to a string; capsys cannot capture an output the",
        "  product never wrote. COUNTED in the passing message, never charged.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- the oracle is the call:[/red]",
        '  [dim]@patch(f"{MOD}.console")[/dim]',
        "  [dim]def test_refusal_is_reported(mock_console):[/dim]",
        '  [dim]    run(["--bad"])[/dim]',
        "  [dim]    assert mock_console.print.called[/dim]",
        "",
        "  [green]Good -- the oracle is the channel:[/green]",
        "  [dim]def test_refusal_is_reported(capsys):[/dim]",
        '  [dim]    run(["--bad"])[/dim]',
        "  [dim]    err = capsys.readouterr().err[/dim]",
        '  [dim]    assert "Refused" in err[/dim]',
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        "  [green]Read the channel with capsys.readouterr().[/green] It returns .out and",
        "  .err separately, so the test pins WHICH channel carried the line --",
        "  something a mock console cannot tell you at all.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-22 over 580 fleet test files: 432 hits in 81 files.",
        "  @prax's test_display_resilience.py carries the receipt in its header --",
        "  the live monitor died on a line Rich could not render, and every",
        "  mock-console test in that branch stayed green.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per test file, since the audit's corpus took in tests/",
        "  (2026-09-21, owner ruling 21:20). A file with any hit scores 0 and the",
        "  branch number moves. The per-file checklist convicts on the write.",
    ]

    json_handler.log_operation("content_served", {"standard": "mock_console"})
    return "\n".join(lines)
