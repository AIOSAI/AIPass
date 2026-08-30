# =================== AIPass ====================
# Name: render.py
# Description: renders an audit-tests artifact to the terminal
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The lane's terminal output. Language-neutral: it renders the ARTIFACT.

Nothing here knows what pytest is. It reads `group_list`, `groups`, `harness`
and `refusal` — the vocabulary every ecosystem's adapter fills — so a Rust
adapter's run renders through this file unchanged. That is the same seam the
core keeps everywhere else, and rendering is where it is easiest to lose:
one `if ecosystem == "pytest"` here and the second ecosystem is a rewrite.

THREE RULES THIS FILE EXISTS TO ENFORCE VISUALLY:

  1. A SCORE NEVER PRINTS ALONE. Law S8 in its rendered form. `100` on its own
     reads as "this suite is clean"; printed beside the count of child
     processes and sqlite handles nobody watched, it reads as what it is — no
     violation SEEN.
  2. A `not_applicable` GROUP PRINTS ITS REASON. Law S1. A group rendered as a
     dash is indistinguishable from a group that scored zero, and the whole
     point of the status vocabulary is that those differ.
  3. A NOMINATION IS NEVER RENDERED AS A VERDICT. Law M1 and Law M11. The
     lines say "suspect" and "improve", the delete family never appears, and
     the deletion-safety probe's absence is stated rather than implied.
"""

from typing import Dict, List

from aipass.cli import console
from aipass.cli.apps.modules import error, success, warning

#: How many nomination rows to print per group before summarising the rest.
#: The ARTIFACT is always untruncated; this is a terminal courtesy and the
#: line below it says exactly how many were withheld from the screen.
NOMINATION_PREVIEW = 5

#: Status colours, so a reader scanning the block sees shape before words.
STATUS_STYLE: Dict[str, str] = {
    "measured": "green",
    "not_applicable": "dim",
    "refused": "red",
}


def render_target(document: dict, path: str) -> None:
    """The full report for one target."""
    console.print()
    if document.get("status") == "refused":
        _render_refusal(document)
        return

    _render_scored(document)
    _render_groups(document)
    _render_harness(document)
    console.print(f"[dim]artifact: {path}[/dim]")


def _render_refusal(document: dict) -> None:
    """A refusal, with the law it cites and what a reader can do about it."""
    block = document.get("refusal") or {}
    error(f"REFUSED: {block.get('reason', 'no reason recorded')}")
    console.print(f"[dim]law: {block.get('law', 'unrecorded')}   exit code: {block.get('code')}[/dim]")
    for line in block.get("detail", [])[:6]:
        console.print(f"  [dim]{line}[/dim]")
    console.print("[dim]A refusal still publishes a complete artifact - every group not_applicable with a[/dim]")
    console.print("[dim]reason. No file, and a run that never happened, would look the same.[/dim]")


def _render_scored(document: dict) -> None:
    """The scored group, and never the number on its own (Law S8)."""
    hygiene = document.get("groups", {}).get("hygiene", {})
    score = hygiene.get("score")
    count = hygiene.get("violation_count", 0)

    if score == 100:
        success(f"hygiene {score} - no write violation SEEN by this gate ({count} violation(s))")
    else:
        warning(f"hygiene {score} - the suite wrote outside its sandbox ({count} violation(s))")

    coverage = hygiene.get("gate_coverage") or {}
    children = coverage.get("child_processes_spawned", 0)
    databases = coverage.get("sqlite3_connections", {}).get("file_backed", 0)
    console.print(f"  [dim]mechanism: {coverage.get('mechanism', 'unrecorded')}[/dim]")
    console.print(
        f"  [yellow]blind:[/yellow] [dim]{children} child process(es) and {databases} file-backed "
        f"sqlite3 handle(s) wrote where this gate cannot follow[/dim]"
    )
    console.print("  [dim]100 means 'no violation seen by this gate', never 'no violation'.[/dim]")
    console.print()


def _render_groups(document: dict) -> None:
    """Every published group in `group_list` order, with its reason or count."""
    console.print("[bold cyan]Groups[/bold cyan]")
    for name in document.get("group_list", []):
        group = document.get("groups", {}).get(name, {})
        _render_group_line(name, group)

    retired = document.get("retired_groups", [])
    if retired:
        console.print()
        console.print("[bold cyan]Retired[/bold cyan] [dim](Law S3 - a group vanishes only by ruling)[/dim]")
        for entry in retired:
            console.print(f"  [dim]{entry.get('group')}: {entry.get('ruling', '')[:150]}[/dim]")
    console.print()


def _render_group_line(name: str, group: dict) -> None:
    """One group's line, plus its nominations when it has any."""
    status = str(group.get("status", "unknown"))
    style = STATUS_STYLE.get(status, "yellow")

    if status == "not_applicable":
        # Law S1 rendered: the reason prints, always. A dash here and a zero
        # would look the same on the screen, which is the confusion the whole
        # status vocabulary exists to prevent.
        console.print(f"  [{style}]{name:34}[/{style}] [dim]not_applicable - {group.get('reason', '')[:80]}[/dim]")
        return

    count = group.get("nomination_count")
    if count is None:
        console.print(f"  [{style}]{name:34}[/{style}] [dim]{status}[/dim]")
        return

    console.print(f"  [{style}]{name:34}[/{style}] [dim]{count} nomination(s)[/dim]")
    _render_nominations(group.get("nominations", []))


def _render_nominations(rows: List[dict]) -> None:
    """A preview of a group's nominations, saying what it withheld."""
    for row in rows[:NOMINATION_PREVIEW]:
        location = row.get("nodeid") or f"{row.get('file')}:{row.get('line')}"
        console.print(f"      [dim]{row.get('verdict')}[/dim] {row.get('species')}  [dim]{location}[/dim]")

    withheld = len(rows) - NOMINATION_PREVIEW
    if withheld > 0:
        console.print(f"      [dim]... and {withheld} more - the ARTIFACT carries all of them, untruncated[/dim]")


def _render_harness(document: dict) -> None:
    """The harness's verdict on itself, failures first and never hidden."""
    harness = document.get("harness") or {}
    checks = harness.get("checks", [])
    if not checks:
        return

    failed = [row for row in checks if row.get("status") == "fail"]
    console.print(
        f"[bold cyan]Harness[/bold cyan] [dim]{harness.get('passed', 0)} pass, "
        f"{harness.get('failed', 0)} fail, {harness.get('not_applicable', 0)} not_applicable[/dim]"
    )
    for row in failed:
        warning(f"  harness check {row.get('check')} FAILED: {row.get('name')} - {row.get('detail', '')[:120]}")
    if not failed:
        console.print("  [dim]every instrument check that could run, ran and passed.[/dim]")
    console.print()
