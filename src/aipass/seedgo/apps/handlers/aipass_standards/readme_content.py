# =================== AIPass ====================
# Name: readme_content.py
# Description: README Standards Content
# Version: 1.0.0
# Created: 2026-03-05
# Modified: 2026-03-05
# =============================================

"""
README Standards Content

Provides Rich-formatted reference text for the README standard.
"""

from aipass.seedgo.apps.handlers.json import json_handler


def get_readme_standards() -> str:
    """Return Rich-formatted README standards text"""
    json_handler.log_operation("standard_content_queried", {"standard": "readme"})
    return """[bold white]README STANDARD[/bold white]

[yellow]PURPOSE:[/yellow]
  Every branch README must accurately reflect its current state.
  A stale or incomplete README misleads contributors and AI agents.

[yellow]CHECK 1 - README EXISTS:[/yellow]

  [bold cyan]README.md[/bold cyan] must be present at branch root.
  This is the entry point for anyone encountering the branch.

[yellow]CHECK 2 - REQUIRED SECTIONS:[/yellow]

  At least one heading from each group (## markdown headers):

  [bold cyan]Architecture / Directory Structure[/bold cyan]
    How the branch is organized. Tree view preferred.

  [bold cyan]Commands / Usage[/bold cyan]
    How to use the branch. CLI commands, API calls, etc.

  [bold cyan]Integration Points / Depends On / Provides To[/bold cyan]
    What the branch connects to. Inbound and outbound.

[yellow]CHECK 3 - LAST UPDATED FRESHNESS:[/yellow]

  README must contain a [dim]*Last Updated: YYYY-MM-DD*[/dim] line.
  Date must be within [bold white]7 days[/bold white] of the newest .py file
  modification in the branch.

  If code changed but README didn't update, it's likely stale.

[yellow]CHECK 4 - DIRECTORY TREE ACCURACY:[/yellow]

  If README contains a directory tree (fenced code block under
  Architecture/Directory Structure heading), verify that listed
  directories actually exist on disk.

  Phantom directories in the tree = misleading documentation.

[yellow]CHECK 5 - MODULE LIST COMPLETENESS:[/yellow]

  Every file in [dim]apps/modules/*.py[/dim] (excluding __init__.py)
  should be mentioned somewhere in the README.

  Undocumented modules are invisible to collaborators.

[yellow]CHECK 6 - COMMAND LIST PRESENCE:[/yellow]

  The Commands/Usage section must not be empty.
  At minimum, list the primary commands the branch supports.

[yellow]SCORING:[/yellow]

  6 checks, each worth ~17 points. Pass threshold: 75%.
  A branch with a missing README scores 17/100 (only check 1 runs)."""
