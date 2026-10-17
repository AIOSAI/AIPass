# =================== AIPass ====================
# Name: rendered_path_oracle_content.py
# Description: Rendered Path Oracle Standards Content Handler
# Version: 1.0.0
# Created: 2026-10-13
# Modified: 2026-10-17
# =============================================

"""
Rendered Path Oracle Standards Content Handler
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_rendered_path_oracle_standards() -> str:
    """Return formatted rendered_path_oracle standards content with Rich markup"""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A test that asserts a WHOLE PATH, spelled inside an f-string, against",
        "  output a console RENDERED. Green on Linux, [red]red on Windows and macOS[/red].",
        "",
        "[bold cyan]THE SPECIMEN (@aipass test_aipass_main.py, PR #787):[/bold cyan]",
        "  log_home = tmp_path / 'system_logs'",
        "  _out, err = capsys.readouterr()",
        "  [red]assert f\"... Permission denied: '{log_home}')\" in err[/red]",
        "",
        "[bold cyan]TWO FRAGILITIES — the second survives a cure for the first:[/bold cyan]",
        "  [red]WRAP[/red]  Rich wraps at the console width (the conftest pins 200). A Windows",
        "        tmp path (...\\AppData\\Local\\Temp\\pytest-of-runneradmin\\...) or",
        "        macOS /private/var/folders/... crosses it; the substring is gone.",
        "  [red]REPR[/red]  str(OSError) renders the filename with %r, so Windows backslashes",
        "        are DOUBLED and '{log_home}' never matches, wrap or not.",
        "        A wider console does not cure this one.",
        "",
        "[bold cyan]CONVICTED, inside one def test_*, one finding per assert:[/bold cyan]",
        "  NEEDLE    an f-string rendering a path: tmp_path itself, a name bound to",
        "            tmp_path / tmp_path_factory.mktemp() / an expression rooted at one",
        "            (/, .joinpath, .resolve()...), a Path()/PurePath()-built name,",
        "            str(<path>), <path>.parent.",
        "  HAYSTACK  captured output: out, err = capsys.readouterr() (or capfd),",
        "            captured.out / .err, capsys.readouterr().out, and result.output /",
        "            .stdout / .stderr of a CliRunner invoke or a subprocess.run.",
        "  COMPARE   in, not in, == and != (either side).",
        "",
        "[bold cyan]ACQUITTED:[/bold cyan]",
        "  [green]{path.name} / .stem / .suffix[/green] — not a path; it is the cure.",
        "  An f-string with no path in it. A path f-string compared against something",
        "  nothing rendered: str(exc), a returned value, a dict the product built.",
        "",
        "[bold cyan]HELD (not judged — the AST cannot settle it in one function):[/bold cyan]",
        "  An f-string bound to a name first; a haystack transformed before the",
        "  compare (' '.join(err.split())); check_output's return; tmpdir; a path",
        "  that reached the test through a helper or another fixture.",
        "",
        "[bold cyan]FLEET ON ARRIVAL (2026-10-13, 762 test files):[/bold cyan]",
        "  Specimen already cured by @aipass. [yellow]9 asserts convict: backup 8, devpulse 1.[/yellow]",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [yellow]ADVISORY[/yellow] — scored per file, kept out of the gating average until",
        "  the fleet is cured; then it gates. Pass/fail per file, every hit on ONE check.",
        "",
        "[bold cyan]THE CURE:[/bold cyan]",
        "  [green]assert the words without the path, and the path's .name[/green]",
        '  ("system_logs" in err), or compare the path through a channel nothing',
        "  renders (a returned value, the exception's .filename).",
    ]

    json_handler.log_operation("content_served", {"standard": "rendered_path_oracle"})
    return "\n".join(lines)
