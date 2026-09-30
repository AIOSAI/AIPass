# =================== AIPass ====================
# Name: literal_path_content.py
# Description: Literal Absolute Path Standards Content Handler
# Version: 1.0.0
# Created: 2026-09-22
# Modified: 2026-09-22
# =============================================

"""
Literal Absolute Path Standards Content Handler

Provides formatted Literal Absolute Path standards content.
Module orchestrates, handler implements.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_literal_path_standards() -> str:
    """Return formatted literal_path standards content with Rich markup

    Returns:
        str: Formatted standards text with Rich styling
    """
    lines = [
        "[bold cyan]CORE PRINCIPLE (test template v1, item 22):[/bold cyan]",
        "  Paths in a test are [green]built from tmp_path[/green], never written as a",
        "  literal [red]/...[/red]",
        "",
        '  Path("/nonexistent/path") happens to work on Windows. It is still the',
        "  habit that breaks the next test: the path is a fact about ONE host,",
        "  written into a file that has to run on three.",
        "",
        "[bold cyan]THIS IS NOT hardcoded_path:[/bold cyan]",
        "  That standard hunts a HOME directory -- /home/<user>/, /Users/<user>/ --",
        "  by regex over every file in the fleet. Item 22's own example has no",
        "  home in it and hardcoded_path cannot see it. Of 2,491 literal absolute",
        "  paths in the fleet's test files, 164 are home-rooted; the other 2,327",
        "  had no checker until this one.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  An absolute path literal HANDED TO A CALL, in a file under [dim]tests/[/dim]:",
        "",
        '  [red]Path("/fake/logs/system")[/red]              the template\'s own shape',
        '  [red]register_contact("/some/inbox.json")[/red]   a product call',
        '  [red]fake_home = "/fake/home"[/red] then [red]run(fake_home)[/red]   judged where USED',
        "",
        "  A literal that merely SITS somewhere is data, not a path in use. That",
        "  restriction IS the rule -- it is what takes 2,327 nominations to 874.",
        "",
        "[bold cyan]NEVER CONVICTED (each measured over 553 fleet test files):[/bold cyan]",
        "  [green]Home-rooted[/green] (78) -- hardcoded_path already convicts it.",
        '  [green]Mock data[/green] (200) -- [dim]mock.return_value = "/usr/bin/tmux"[/dim].',
        '  [green]A URL path[/green] (188) -- [dim]client.get("/v1/whoami")[/dim] names a route.',
        '  [green]A system root[/green] (60) -- [dim]read_file("/etc/passwd")[/dim] names a real file',
        "  the fence must refuse; tmp_path cannot express that.",
        '  [green]A pure path class[/green] (26) -- [dim]PureWindowsPath("/x")[/dim] is string algebra.',
        '  [green]A string operation[/green] (10) -- [dim]p.startswith("/proc")[/dim] is a comparison.',
        '  [green]A drive-rooted literal[/green] (15) -- [dim]r"C:\\proj\\AIPass"[/dim]. COUNTED and',
        "  reported in the passing message, never convicted: on a POSIX host",
        "  tmp_path cannot produce one, so a cross-OS test has no other spelling.",
        "",
        "[bold cyan]VIOLATIONS:[/bold cyan]",
        "  [red]Bad -- a path invented on one host:[/red]",
        '  [dim]result = classify(Path("/fake/repo/apps/entry.py"))[/dim]',
        "",
        "  [green]Good -- the same test, built:[/green]",
        '  [dim]entry = tmp_path / "apps" / "entry.py"[/dim]',
        "  [dim]result = classify(entry)[/dim]",
        "",
        "[bold cyan]THE FIX:[/bold cyan]",
        "  [green]Build it from tmp_path.[/green] The fixture is already in every test's",
        "  signature; a path built from it exists, is writable, and is cleaned up.",
        "",
        "[bold cyan]WHY IT EXISTS:[/bold cyan]",
        "  Measured 2026-09-22 over 578 fleet test files: 874 hits in 117 files,",
        '  281 of them the template\'s own shape, Path("/...").',
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  SCORED, per test file, since the audit's corpus took in tests/",
        "  (2026-09-21, owner ruling 21:20). A file with any hit scores 0 and the",
        "  branch number moves. The per-file checklist convicts on the write.",
    ]

    json_handler.log_operation("content_served", {"standard": "literal_path"})
    return "\n".join(lines)
