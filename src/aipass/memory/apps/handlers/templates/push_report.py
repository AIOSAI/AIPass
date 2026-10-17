# =================== AIPass ====================
# Name: push_report.py
# Description: Renders and persists the trinity push report — the artifact the dry-run exists to produce
# Version: 1.3.0
# Created: 2026-08-27
# Modified: 2026-10-17
# =============================================

"""Trinity Push Report

Per branch, never a wall; out-of-scope files and zero todos are said out loud, never left silent.
Reference: docs/trinity_push.md
"""

from datetime import datetime
from typing import List

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file
from aipass.memory.apps.handlers.templates.trinity_push import DEFECT_ORDER

_MEMORY_ROOT = module_file(__file__).parents[3]
REPORTS_DIR = _MEMORY_ROOT / "artifacts" / "push_reports"

# The remainder past the cap is COUNTED: a silent truncation reads as completeness.
MAX_PRUNE_SAMPLES = 6

CHARS_MEASURE = "chars = len(json.dumps(<the todos moved, as one list>, ensure_ascii=False)) per branch, summed"


def render(result: dict, label: str) -> List[str]:
    """Render the whole report (``trinity_push.push`` payload) as plain lines."""
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
        if entry.get("local_store"):
            lines.append(f"   local store: none ({entry['local_store']}) — global store only")

    strays = entry.get("strays", [])
    if strays:
        # Name the FILES as out of scope: a bare "NOT push scope" reads as a verdict on the branch.
        lines.append(
            f"   {len(strays)} file(s) in .trinity/ are not push scope (reported, never deleted): {', '.join(strays)}"
        )
    lines.append("")
    return lines


def _todo_lines(entry: dict, dry_run: bool) -> List[str]:
    """What the push saw in ``todos`` and where the leavers go — stated on EVERY branch, every run.

    A zero is spoken too: "owes nothing" and "open work is gone" must never render the same.
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

    A refused branch moved nothing and counts nothing.
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
    """Persist the report so the artifact outlives the terminal; the path, or "" when unsaved."""
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
