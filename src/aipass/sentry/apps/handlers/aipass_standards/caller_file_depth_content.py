# =================== AIPass ====================
# Name: caller_file_depth_content.py
# Description: Caller File Depth Standards Content Handler
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""Caller File Depth Standards Content Handler"""

from aipass.sentry.apps.handlers.json import json_handler


def get_caller_file_depth_standards() -> str:
    """Return formatted caller_file_depth standards content with Rich markup."""
    lines = [
        "[bold cyan]CORE PRINCIPLE:[/bold cyan]",
        "  A function that finds a caller's branch by climbing a fixed number of folders",
        "  from the caller's file is right only for a file at the layout it was written",
        "  for. A caller anywhere else works by coincidence of depth, or not at all.",
        "",
        "[bold cyan]WHAT IT CHECKS:[/bold cyan]",
        "  A depth function: any function under src/aipass climbing two or more levels",
        "  from a parameter (.parents[n], .parent chains, os.path.dirname). A call handing",
        "  one __file__ is convicted when the caller, from any place it runs, is not at",
        "  <branch>/apps/... with exactly the depth the function climbs:",
        "",
        "  1. [red]Wrong depth[/red]: the climb lands on another folder, not the branch",
        "  2. [red]Run from a copy[/red]: a copy beside apps/ (hooks/.live-<stamp>/) lands on",
        "     the branch only by coincidence of depth",
        "",
        "[bold cyan]WHAT PASSES:[/bold cyan]",
        "  - a caller at <branch>/apps/... at the function's depth, with no copy beside apps/",
        "  - a call handing any path other than the file's own __file__",
        "  - a whole-branch copy elsewhere (docs.local/snap/apps/...) and .archive/: not run",
        "",
        "[bold cyan]HOW TO FIX:[/bold cyan]",
        "  [green]Good:[/green]  [dim]for_branch(BRANCH_ROOT)[/dim] -- pass the branch root explicitly",
        "  [green]Good:[/green]  the function walks up to a marker (.trinity/passport.json), not a depth",
        "  [red]Bad:[/red]  [dim]for_module(__file__)[/dim] from a file that runs from a snapshot",
        "",
        "[yellow]SCOPE:[/yellow]",
        "  AUDIT_SCOPE = [bold]all_files[/bold], APPLIES_TO = [bold]production[/bold]",
        "  A copy is seen only when it is on disk: a clean checkout, a wheel or a temp",
        "  copy is not seen.",
        "",
        "[bold cyan]SCORING:[/bold cyan]",
        "  One finding per call (line, enclosing function). [green]100[/green] = none,",
        "  [red]0[/red] = any unwaived call. A file Python cannot parse scores 0, unjudged.",
        "",
        "[bold cyan]REFERENCE:[/bold cyan]",
        "  [dim]Checker: caller_file_depth_check.py  Doc: caller_file_depth.md[/dim]",
    ]

    json_handler.log_operation("standard_content_queried", {"standard": "caller_file_depth"})
    return "\n".join(lines)
