# =================== AIPass ====================
# Name: stdlib_only_content.py
# Description: Stdlib Only Standards Content Handler
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Stdlib Only Standards Content Handler"""

from aipass.sentry.apps.handlers.json import json_handler


def get_stdlib_only_standards() -> str:
    """Return formatted stdlib_only standards content with Rich markup."""
    lines = [
        "[bold cyan]THE SITUATION:[/bold cyan]",
        "  A few files are imported by other branches before any aipass service runs,",
        "  so they cannot import the json shim or log. Their branch asks sentry for a",
        "  custom standard instead of a bypass row: the file claims stdlib_only, and",
        "  the check proves the claim.",
        "",
        "[bold cyan]HOW A BRANCH ASKS:[/bold cyan]",
        "  Mail @sentry the file and why it must load before aipass. Sentry adds its",
        "  path under src/aipass to CLAIMS in stdlib_only_check.py. A claim is not a pass.",
        "",
        "[bold cyan]WHAT IT PROVES, per listed file:[/bold cyan]",
        "  1. [red]Imports[/red]: every one in sys.stdlib_module_names; no relative import, no",
        "     aipass import, no I/O module (subprocess, shutil, socket, tempfile, glob, ...)",
        "  2. [red]Disk[/red]: no open, read_*/write_*, listing, stat/exists, mkdir/unlink/rename",
        "  3. [red]Environment[/red]: no environ (read or imported), getenv/putenv/unsetenv",
        "  4. [red]Processes[/red]: no system/popen/fork, exec*/spawn*",
        "  5. [red]Run-time imports[/red]: no __import__, import_module, exec, eval",
        "  A listed path that does not exist fails; so does a file Python cannot parse.",
        "",
        "[bold cyan]WHAT A PROVEN CLAIM BUYS:[/bold cyan]",
        "  json_structure stands down for it and says so. An unlisted file gets no",
        "  relief, however clean it is.",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]branch_level[/bold], APPLIES_TO = [bold]production[/bold]",
        "  A branch with no claim: the row is not applicable (no score).",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  [green]100[/green] = every claim proven, [red]0[/red] = any claim missing or broken.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: stdlib_only_check.py  Doc: stdlib_only.md[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "stdlib_only"})
    return "\n".join(lines)
