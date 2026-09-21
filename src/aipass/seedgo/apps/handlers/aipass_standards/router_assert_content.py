# =================== AIPass ====================
# Name: router_assert_content.py
# Description: Router Assert Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""
Router Assert Standards Content Handler

Provides formatted Router Assert standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_router_assert_standards() -> str:
    """Return formatted router_assert standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A command router returns [green]True[/green] for every path it takes --",
        "  the command it ran, the flag it printed, the error it displayed.",
        "  So [red]assert handle_command(...) is True[/red] is not an oracle:",
        "  it passes whether the command worked or did nothing at all.",
        "",
        "  [bold]The router returned True and the test asserts nothing it did.[/bold]",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  A test function is a violation when EVERY assertion in it is",
        "  [dim]assert <router call or its result> is True[/dim].",
        "",
        "  Router callees: [dim]handle_command, route_command, main, handle[/dim]",
        "  Both shapes count -- the one-liner and the assign-then-assert:",
        "",
        "  [dim]assert handle_command('x', []) is True[/dim]",
        "  [dim]result = handle_command('x', []); assert result is True[/dim]",
        "",
        "  [green]One honest assertion anywhere in the unit acquits it[/green], and so",
        "  does any [dim]assert_*[/dim] / [dim]_assert_*[/dim] helper call or a",
        "  [dim]pytest.raises[/dim] / [dim]pytest.warns[/dim] block -- those ARE the",
        "  effect assertion this standard asks for.",
        "",
        "[bold cyan]NEVER CONVICTED: is False[/bold cyan]",
        "  [green]assert handle_command('not_mine', []) is False[/green]",
        "",
        "  A decline is a whole contract. The router recognising that a command",
        "  is not its own IS the behaviour, and there is no effect to assert",
        "  beyond the return value. Fleet-wide that acquits 117 units, and this",
        "  standard will not be widened to reach them.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- the name promises what the oracle never reads:[/red]",
        "  [dim]def test_handle_command_unknown_subcommand():[/dim]",
        '  [dim]    """Unknown subcommand returns True (error displayed to user)."""[/dim]',
        "  [dim]    result = handle_command('readme', ['bogus'])[/dim]",
        "  [dim]    assert result is True[/dim]",
        "",
        "  Eight [dim]console.print[/dim] lines fire and none of them is read.",
        "",
        "  [green]Good -- assert the effect:[/green]",
        "  [dim]    with patch.object(readme_update, 'console') as con:[/dim]",
        "  [dim]        assert handle_command('readme', ['bogus']) is True[/dim]",
        "  [dim]    out = ' '.join(str(c) for c in con.print.call_args_list)[/dim]",
        "  [dim]    assert 'bogus' in out and 'Unknown' in out[/dim]",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  Read the test's own name and docstring -- they already say what the",
        "  test is for. Assert that, not the routing:",
        "",
        "  1. [bold]shows / displays / lists[/bold] -> assert what reached the console",
        "  2. [bold]passes X to Y[/bold] -> assert Y's call args",
        "  3. [bold]does not Z[/bold] -> assert Z's mock was NOT called",
        "  4. [bold]writes / updates[/bold] -> read the file back and assert its bytes",
        "",
        "  If the routing really is the whole contract, the test belongs with",
        "  the [dim]is False[/dim] decline case it pairs with, not on its own.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  APPLIES_TO = [bold]tests[/bold] -- test files only.",
        "",
        "  The audit's corpus is [dim]apps/[/dim], so this standard scores NOTHING in",
        "  [dim]audit aipass[/dim] and no branch's number moved when it landed. It",
        "  convicts in the per-file [dim]checklist[/dim] lane, which the PostToolUse",
        "  hook runs on the write -- so it meets an agent creating the shape.",
        "  The standing backlog is reported once per branch, unscored, through",
        "  the audit's info channel.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  Single check per file: [green]pass[/green] (0 units) or [red]fail[/red] (any units).",
        "  Score: 100 if passed, 0 if failed. Line-level bypass is supported.",
        "",
        "[bold cyan]BYPASS:[/bold cyan]",
        "  Add an entry to [dim].seedgo/bypass.json[/dim]:",
        '  [dim]{"standard": "router_assert", "file": "tests/test_x.py"}[/dim]',
        "  Or bypass the one unit, by the line its [dim]def[/dim] sits on:",
        '  [dim]{"standard": "router_assert", "file": "tests/test_x.py", "lines": [366]}[/dim]',
        "",
        "  The known false-positive kind is the implicit oracle: a test whose",
        "  real claim is [dim]did not raise SystemExit[/dim] has no assertion to write.",
        "  That is a bypass with a reason, not a silenced rule.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]See: docs/test_gold_standard.md -- the four weak oracles[/dim]",
        "  [dim]Checker: router_assert_check.py[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "router_assert"})
    return "\n".join(lines)
