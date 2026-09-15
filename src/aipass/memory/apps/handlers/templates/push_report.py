# =================== AIPass ====================
# Name: push_report.py
# Description: Renders and persists the trinity push report — the artifact the dry-run exists to produce
# Version: 1.2.0
# Created: 2026-08-27
# Modified: 2026-09-15
# =============================================

"""Trinity Push Report

The dry-run's whole purpose is a report a human reads before granting a fleet
GO, so the rendering lives in a handler rather than in the CLI module: it is
domain work with its own rules, not display sugar.

Three of those rules earn their keep:

- **Per branch, never a wall.** The fleet report covers 22 branches; a flat
  list of 366 prune lines is technically complete and practically unreadable.
  Each branch gets its own block, and the per-entry detail is capped with the
  remainder counted out loud rather than silently dropped.
- **What is NOT in scope is stated.** Stray files in a branch's ``.trinity/``
  are reported in the same breath as the prunes and explicitly marked as
  outside the push's mandate, so a reader cannot mistake the push's silence
  about them for the push having handled them.
- **Todos are counted, reasoned and located on EVERY branch** (DPLAN-0345). A
  todo that leaves the pad goes to ``.backup/todo/<branch>/backlog.json``, so
  each branch says how many it saw, how many move and why, and whether that
  backlog already exists. A zero is spoken too: "I owe nothing" and "my pad
  was emptied" must never render the same.
"""

from datetime import datetime
from typing import List

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.templates.trinity_push import DEFECT_ORDER

_MEMORY_ROOT = module_file(__file__).parents[3]
REPORTS_DIR = _MEMORY_ROOT / "artifacts" / "push_reports"

# Per-entry detail is capped per branch; the remainder is COUNTED, never
# silently dropped — a truncation that does not announce itself reads as
# completeness.
MAX_PRUNE_SAMPLES = 6

# How the todo chars are measured, stated once under the fleet line. It is the
# measure behind DPLAN-0345's "Todo JSON is 106,408 chars" (devpulse 69,680,
# seedgo 16,127 reproduce with it).
CHARS_MEASURE = "chars = len(json.dumps(<the todos moved, as one list>, ensure_ascii=False)) per branch, summed"


def render(result: dict, label: str) -> List[str]:
    """Render the whole report as plain lines.

    Args:
        result: The payload from ``trinity_push.push``.
        label: Scope label — ``@branch`` or ``FLEET``.

    Returns:
        The report, one line per element, ready to print or write.
    """
    lines = [
        f"Trinity push report · scope {label} · {'DRY RUN — nothing written' if result['dry_run'] else 'EXECUTED'}",
        f"Generated {datetime.now().isoformat(timespec='seconds')}",
        f"Branches in scope: {result['scope']}",
        "",
    ]

    if not result["branches"]:
        lines.append("No branches resolved.")
    for entry in result["branches"]:
        lines.extend(_branch_block(entry, result["dry_run"]))

    lines.extend(_summary_block(result))
    return lines


def _branch_block(entry: dict, dry_run: bool) -> List[str]:
    """One branch's section of the report."""
    head = f"── {entry['branch']} " + "─" * max(0, 60 - len(entry["branch"]))
    lines = [head]

    if entry.get("refused"):
        lines.append("   REFUSED — nothing was changed for this branch:")
        lines.extend(f"     ! {message}" for message in entry.get("errors", []))
        lines.append("")
        return lines

    if dry_run:
        lines.append(f"   would prune {entry['pruned']} entries · {entry['carried']} carry over untouched")
        lines.extend(_todo_lines(entry, dry_run))
        lines.extend(_prune_lines(entry.get("prunes", [])))
        lines.extend(_frame_lines(entry.get("frame_changes", {})))
    else:
        lines.append(
            f"   pruned {entry['pruned']} · carried {entry['carried']} · files written {entry['written']}"
            f" · note {'written' if entry['noted'] else 'not needed'}"
            f" · receipt {'stamped' if entry['receipt'] else 'NOT stamped'}"
        )
        lines.extend(_todo_lines(entry, dry_run))
        lines.extend(f"     ! {message}" for message in entry.get("errors", []))

    strays = entry.get("strays", [])
    if strays:
        # "NOT push scope" alone read as a verdict on the BRANCH — @spawn and
        # @devpulse both took it that way on 2026-09-07 and held the first real
        # bump back on the strength of it, when every one of those branches was
        # being pruned and carried normally on the line directly above. The
        # files are out of scope; the branch never was.
        lines.append(
            f"   {len(strays)} file(s) in .trinity/ are not push scope (reported, never deleted): {', '.join(strays)}"
        )
    lines.append("")
    return lines


def _todo_lines(entry: dict, dry_run: bool) -> List[str]:
    """What the push saw in ``todos`` and where the leavers go — stated on EVERY branch, every run.

    Silence used to be the report's answer for a branch with no drifted todos,
    which made "this agent owes nothing" and "this agent's open work is gone"
    render identically (67 todos archived across 8 branches on 2026-08-27).
    """
    seen = entry.get("todos_seen", 0)
    planned = entry.get("todos_to_backlog", 0)
    count = entry.get("todos_count")
    pad = f"the pad of {count}" if count is not None else "a pad with no configured size"
    if dry_run:
        moving = f"{planned} to backlog ({entry.get('todos_chars', 0):,} chars)"
    else:
        moving = f"{entry.get('todos_moved', 0)} of {planned} moved to backlog ({entry.get('todos_chars', 0):,} chars)"
    lines = [f"   todos {seen} seen · {moving} · {seen - planned} stay on {pad}"]
    if not planned:
        return lines
    reasons = ", ".join(f"{label} {number}" for label, number in entry.get("todo_reasons", {}).items())
    lines.append(f"     reasons: {reasons}")
    state = "exists, appended to" if entry.get("backlog_exists") else "does not exist yet, created by the push"
    lines.append(f"     backlog {entry.get('backlog_display')} ({state}; never overwritten)")
    return lines


def _prune_lines(prunes: List[dict]) -> List[str]:
    """Per-entry prune detail, capped and honest about what it dropped."""
    if not prunes:
        return []
    lines = ["   entries to be vectorized, verified, then pruned:"]
    for prune in prunes[:MAX_PRUNE_SAMPLES]:
        number = prune["number"] if prune["number"] is not None else "?"
        lines.append(f"     - {prune['container']}[{prune['index']}] #{number}: {prune['reason']}")
    if len(prunes) > MAX_PRUNE_SAMPLES:
        lines.append(f"     … and {len(prunes) - MAX_PRUNE_SAMPLES} more (full list in the JSON log)")
    return lines


def _frame_lines(frame_changes: dict) -> List[str]:
    """What the machine-frame rewrite changes, per file."""
    lines = []
    for file_key, changes in frame_changes.items():
        if not changes:
            continue
        lines.append(f"   {file_key}.json frame:")
        lines.extend(f"     · {change}" for change in changes)
    return lines


def todo_totals(branches: List[dict], dry_run: bool) -> tuple[int, int, int]:
    """Fleet todo totals: (todos, branches, chars) planned on a dry run, verified moved on a real one.

    Args:
        branches: The per-branch entries from ``trinity_push.push``.
        dry_run: Whether the entries are dry-run plans.

    Returns:
        ``(todos, branches, chars)``. A refused branch moved nothing and counts nothing.
    """
    key = "todos_to_backlog" if dry_run else "todos_moved"
    movers = [entry for entry in branches if not entry.get("refused") and entry.get(key, 0)]
    todos = sum(entry[key] for entry in movers)
    chars = sum(entry.get("todos_chars", 0) for entry in movers)
    return todos, len(movers), chars


def _summary_block(result: dict) -> List[str]:
    """Fleet totals and the refusal roll-call."""
    pruned = sum(entry.get("pruned", 0) for entry in result["branches"])
    carried = sum(entry.get("carried", 0) for entry in result["branches"])
    refused = [entry["branch"] for entry in result["branches"] if entry.get("refused")]
    todos, movers, chars = todo_totals(result["branches"], result["dry_run"])
    lines = [
        "─" * 64,
        f"TOTAL: {pruned} entries to archive · {carried} carry over · {len(result['branches'])} branches",
        f"TODOS TO BACKLOG: {todos} across {movers} branches, {chars:,} chars",
        f"  {CHARS_MEASURE}",
        f"  each todo counts once, under its first reason in this order: {' > '.join(DEFECT_ORDER)}",
    ]
    if refused:
        lines.append(f"REFUSED ({len(refused)}): {', '.join(refused)}")
    if result["errors"]:
        lines.append(f"ERRORS ({len(result['errors'])}):")
        lines.extend(f"  ! {message}" for message in result["errors"])
    return lines


def save(lines: List[str], label: str, dry_run: bool) -> str:
    """Persist the report so the artifact outlives the terminal.

    Args:
        lines: The rendered report.
        label: Scope label, used in the filename.
        dry_run: Whether this was a dry run, also used in the filename.

    Returns:
        The path written, or an empty string when it could not be saved.
    """
    try:
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = label.lstrip("@").lower()
        mode = "dryrun" if dry_run else "executed"
        path = REPORTS_DIR / f"{stamp}_{slug}_{mode}.txt"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as exc:
        logger.warning(f"[push_report] Could not write report: {exc}")
        return ""

    json_handler.log_operation(
        "push_report_saved",
        {"path": str(path), "scope": slug, "dry_run": dry_run, "lines": len(lines)},
        module_name="push_report",
    )
    return str(path)
