# =================== AIPass ====================
# Name: readme_content.py
# Description: README Standards Content
# Version: 1.3.0
# Created: 2026-03-05
# Modified: 2026-09-19
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

[yellow]CANONICAL SECTION ORDER - eight ## sections, names exact, order fixed:[/yellow]

  [bold cyan]1 Quick Start[/bold cyan]         the first commands a newcomer runs
  [bold cyan]2 What It Does[/bold cyan]        what the branch owns, in a few lines
  [bold cyan]3 Live Inventory[/bold cyan]      a pointer to drone @<branch> and --help, never a copy
  [bold cyan]4 How To Reach Me[/bold cyan]     mail, dispatch, the address
  [bold cyan]5 Commands[/bold cyan]            a pointer to --help, and the few verbs worth naming
  [bold cyan]6 Architecture[/bold cyan]        the layout and the idea behind it
  [bold cyan]7 Documentation[/bold cyan]       the docs/ index, one line per page
  [bold cyan]8 Integration Points[/bold cyan]  what it depends on and what depends on it

  The fleet's de facto order (DPLAN-0351). Back-link, H1 and purpose sit
  above the first section; ### subsections are free. Every README carries
  all eight - the advisory line [dim]readme sections[/dim] names the rest.

  The generated AUTO:NAME marker sections are retired: no README carries
  one, and the live inventory is drone @<branch> and --help, generated
  from code on every call.

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

  README must contain a [dim]*Last Updated: YYYY-MM-DD*[/dim] line
  with a parseable date.

  Local-file only: presence and shape, never a comparison against code
  history. Recency is not a property of the files on disk, and a git
  comparison would score a working tree and a clean CI checkout
  differently.

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

[yellow]CHECK 7 - TEST COUNT ACCURACY:[/yellow]

  If README mentions test counts (e.g. "219 tests" in tree comments
  or status lines), the claimed number must be within [bold white]10%[/bold white]
  of the actual [dim]def test_[/dim] function count in tests/.

  The highest claimed count is compared against actual.
  Branches with no test claims or no tests/ directory pass by default.

  Date-bumping hides this drift. A branch can update its date
  every week while claiming "130 tests" when reality is 450.

[yellow]CHECK 8 - MARKDOWN LINK VALIDITY:[/yellow]

  All relative markdown links [dim]\\[text](path)[/dim] must point to
  existing files or directories relative to the branch root.

  Skips external links (http/https/mailto) and anchor links (#).
  Dead links mislead contributors navigating via README.

[yellow]ADVISORY LANE - DOCS INDEX + ROT BAIT (never scored):[/yellow]

  [bold cyan]ADVISORY[/bold cyan] - reports lines, moves no number. These
  arrive as [dim]info lines[/dim] on [bold cyan]drone @seedgo audit aipass @branch[/bold cyan],
  rendered at any score, and are never merged into scores or violations.
  The README is the [bold white]face[/bold white] plus an index of docs/;
  the live inventory is [bold cyan]drone @<branch>[/bold cyan] and
  [bold cyan]--help[/bold cyan]; the depth is docs/, one file per module or
  handler group (DPLAN-0347, boardroom thread 16).

  [bold cyan]docs index[/bold cyan]
    Every [dim]docs/*.md[/dim] must be reachable from the README - a
    relative link that resolves to it, or the literal path
    [dim]docs/<name>[/dim] in the text. A link to [dim]docs/[/dim] itself
    covers [dim]docs/README.md[/dim]. No docs/ directory is SILENCE.

  [bold cyan]named paths[/bold cyan]
    A path the README names, rooted in one of this branch's own top-level
    directories, must exist. Paths relative to somewhere deeper, a
    neighbour branch's files and illustrations are out of scope: an audit
    of one branch cannot tell a stale reference from a foreign one.
    Link targets belong to CHECK 8, directories to CHECK 4.

  [bold cyan]rot bait[/bold cyan]
    Content that stays true only while someone re-types it:
    counts ("46 standards", "13 modules"), dated or Status/Latest Audit
    headings, and a Commands section that re-types [dim]--help[/dim].
    The Last Updated line is exempt - CHECK 3 requires it. The Commands
    line asks for a POINTER, not a deletion: CHECKS 2 and 6 still want
    the section.

  [bold cyan]sections[/bold cyan]
    The eight ## sections above, names exact, order fixed: what is
    missing, a rename (a heading sharing its first word with a missing
    section), the out-of-order pairs, and a ## heading that is not one
    of the eight. All eight in order is SILENCE.

  [dim]Why advisory: readme is scored and CI gates every branch at 100.
  17 of 18 branches have no docs index today, so a ninth scored check
  would red the whole fleet on one commit - exactly what happened on
  2026-09-13. Advisory first, ratchet later.[/dim]

[yellow]SCORING:[/yellow]

  8 checks, each worth ~12.5 points. Pass threshold: 75%.
  A branch with a missing README scores 12/100 (only check 1 runs).
  The advisory lane is outside this arithmetic entirely."""
