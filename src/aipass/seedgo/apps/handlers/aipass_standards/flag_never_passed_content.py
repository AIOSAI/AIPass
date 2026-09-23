# =================== AIPass ====================
# Name: flag_never_passed_content.py
# Description: Flag Never Passed Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Flag Never Passed Standards Content Handler

Provides formatted Flag Never Passed standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_flag_never_passed_standards() -> str:
    """Return formatted flag_never_passed standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (crack class P, review of @backup 2026-09-22):[/bold cyan]",
        "  The product's handle_command parses a --flag out of args and no test in",
        "  the branch ever passes that flag to it. The flag's branch is unpinned —",
        "  delete the parse, hardcode the default, and the suite stays green.",
        "",
        "[bold cyan]THE SHAPE, FROM @backup's share.py:129:[/bold cyan]",
        "  [red]public = '--public' in args[/red]",
        "  [red]run_share(file_path, public=public)[/red]",
        "",
        "  public = False survives all 21 share tests. The only place --public",
        "  appears under backup/tests/ is a help-text substring assertion and a",
        "  tuple of flag names iterated for a help sweep. Neither hands it over.",
        "",
        "[bold cyan]WHAT COUNTS AS PASSING IT — the whole rule:[/bold cyan]",
        "  The literal must reach an [green]ARGUMENT of some call[/green]:",
        "    handle_command('share', ['--public'])",
        "    a sub-handler — handle_create([target, '--dry-run']), how @spawn does it",
        "    monkeypatch.setattr(sys, 'argv', [...]) before main()",
        "    a name bound to an argv list",
        "    a parametrize argvalue whose parameter is then handed over",
        "",
        "  A tuple that is only [red]ITERATED[/red] is not an argument. That is what keeps",
        "  @backup's for flag in ('--name', ..., '--public') help sweep from",
        "  acquitting the very flag it names.",
        "",
        "[bold cyan]AN ARGV CARRYING --help OR -h EXERCISES NOTHING ELSE IN THAT ROW:[/bold cyan]",
        "  The product itself says so — share.py returns from print_help() before it",
        "  reads args[0]. So ['drive_clear', root, '--force', '--help'] pins --help",
        "  and leaves [red]--force exactly as unpinned as before[/red]. Without this rule the",
        "  help sweep acquitted three of the five flags the reviewers named.",
        "",
        "[bold cyan]CHECK FIRST (measured 2026-09-22 over the fleet):[/bold cyan]",
        "  [green]27 files, 43 hits, 8.7s[/green], nine branches.",
        "  aipass 14 · spawn 10 · backup 5 · seedgo 4 — and seedgo's four are mine.",
        "",
        "  THE THREE CUTS, and the middle one is the instructive failure:",
        "    the flag appears as ANY string under tests/      7 files,  9 hits",
        "    the literal must reach a handle_command CALL    38 files, 82 hits",
        "    any call argument, minus the --help rows        27 files, 43 hits",
        "",
        "  The middle cut convicted all 20 of @spawn's flags, because @spawn tests",
        "  its sub-handlers and never names handle_command. [red]A rule that reads one",
        "  function name mistakes a different spelling for an absent test.[/red]",
        "",
        "[bold cyan]THE JUDGEMENT CALL:[/bold cyan]",
        "  A flag parsed only in a module's __main__ block, or only in a helper that",
        "  builds argv for something else, is NOT declared and is never convicted.",
        "  The declared set starts at handle_command and follows only the same-file",
        "  functions it calls. The router's contract is the one the tests exercise.",
        "",
        "[bold cyan]WHY IT CANNOT BE SATISFIED BY ACCIDENT:[/bold cyan]",
        "  If the literal never reaches the parser in any test, the branch behind it",
        "  is never taken, and deleting the parse cannot turn the suite red. There",
        "  is no threshold and nothing to tune.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per BRANCH — the rule compares a branch's apps/ against its whole",
        "  tests/ tree, so no single file owns the verdict. Every hit names the",
        "  parse site, the flag and the cure, on ONE check. Flags that appear only",
        "  inside a --help argv are counted in the passing message, never charged.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]pass it to the parser in a test, or delete the branch nothing reaches.[/green]",
    ]

    json_handler.log_operation("content_served", {"standard": "flag_never_passed"})
    return "\n".join(lines)
