# =================== AIPass ====================
# Name: conftest_fixtures_content.py
# Description: Conftest Fixtures Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Conftest Fixtures Standards Content Handler

Provides formatted Conftest Fixtures standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_conftest_fixtures_standards() -> str:
    """Return formatted conftest_fixtures standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 20):[/bold cyan]",
        "  A branch's [green]tests/conftest.py[/green] pins the console width once, session",
        "  scope, on every console the product exports — and resets the command",
        "  state after every test.",
        "",
        "[bold cyan]THE UNIT IS THE CONFTEST, NOT THE TEST FILE:[/bold cyan]",
        "  Every other file under tests/ passes silently. These two fixtures belong",
        "  in exactly ONE place (item 16, never copied per file), so a rule that",
        "  read them anywhere else would convict 563 files for not being the",
        "  conftest. All 18 branches have one; the checker never convicts a branch",
        "  for a conftest that is not there, because it cannot see a missing file.",
        "",
        "[bold cyan]TWO SUB-RULES, BOTH ON ONE CHECK:[/bold cyan]",
        "",
        "  [red]C1[/red]  A [green]session-scope autouse[/green] fixture pins [green].width[/green] on the PRODUCT's",
        "      consoles. Rich sizes an unpinned console on every print: 80 on POSIX, 79 on",
        "      Windows under pytest's capture, the terminal's width under -s, and",
        "      COLUMNS when exported. The template measured 4 of the trial's 31",
        "      tests flipping at width 40, none with the pin.",
        "",
        '      [dim]@pytest.fixture(autouse=True, scope="session")[/dim]',
        "      [dim]def pinned_console_width() -> None:[/dim]",
        "      [dim]    for console in (display.CONSOLE, display.err_console):[/dim]",
        "      [dim]        console.width = 200[/dim]",
        "",
        "  [red]C2[/red]  An [green]autouse[/green] fixture calls [green]display.reset_command_state()[/green] AFTER",
        "      the test. error() marks the process failed, and a test must not hand that",
        "      flag to the next one. Item 18 wearing a conftest's clothes.",
        "",
        "      [dim]@pytest.fixture(autouse=True)[/dim]",
        "      [dim]def clean_command_state() -> Generator[None, None, None]:[/dim]",
        "      [dim]    yield[/dim]",
        "      [dim]    display.reset_command_state()[/dim]",
        "",
        "[bold cyan]THE PIN HAS TO LAND ON THE PRODUCT'S CONSOLES:[/bold cyan]",
        "  A [red]Console(width=200)[/red] the fixture builds itself is a console the product",
        "  never prints to, so it pins nothing and C1 is NOT satisfied. The name has",
        "  to come from an aipass.cli import — display.CONSOLE, display.err_console,",
        "  or the console / err_console those modules export — or be the loop",
        "  variable of a `for` over them. Same install-site restriction mock_console",
        "  took from host_portability ARM A.",
        "",
        "  ORDER MATTERS for C2: a reset BEFORE the yield clears the flag the",
        "  PREVIOUS test set and hands this test's flag straight on.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over all 18 branch conftests):[/bold cyan]",
        "  [green]1 of 18 pins width[/green] — seedgo, and it is the model file.",
        "  [green]2 of 18 reset command state[/green] — seedgo and commons.",
        "  [green]0 branches are missing a conftest[/green] — every one has one today.",
        "  @cli's conftest carries Console(width=..., force_terminal=...) in its",
        "  make_capture_console HELPER. That is a console the test prints to, not a",
        "  pin on the product's, so C1 is not satisfied there.",
        "  [green]292 shared-console import sites[/green] across the 18 branches pull console /",
        "  err_console from aipass.cli.apps.modules, where console IS CONSOLE. C1",
        "  works fleet-wide because it mutates the shared Console INSTANCE.",
        "",
        "[bold cyan]THE ONE OPEN TEMPLATE QUESTION:[/bold cyan]",
        "  48 other Console() builds exist in the fleet. 47 sit inside a",
        "  try/except ImportError fallback that fires only when aipass.cli cannot be",
        "  imported — never in the suite. The 48th is real and it is SEEDGO's own:",
        "  apps/handlers/diagnostics/diagnostics_check.py:33 binds a module-level",
        "  console = Console() that C1's two names do not reach. Whether C1 should",
        "  name every module-level console a branch builds is a question for the",
        "  owner, not a conviction to soften.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per file, but only conftest.py is ever judged. A conftest missing",
        "  either fixture scores 0 and the branch number moves; every other file in",
        "  tests/ scores 100 and says so.",
    ]

    json_handler.log_operation("content_served", {"standard": "conftest_fixtures"})
    return "\n".join(lines)
