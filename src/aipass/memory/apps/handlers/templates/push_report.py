# =================== AIPass ====================
# Name: push_report.py
# Description: Renders and persists the trinity push report — the artifact the dry-run exists to produce
# Version: 1.1.0
# Created: 2026-08-27
# Modified: 2026-08-27
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
- **Left-behind work is named, never merely counted.** A non-canonical todo is
  the one thing the push refuses to archive, so the report is the only place
  its owner learns which lines still need reshaping. Those lines are printed
  in full — uncapped, unlike the prune samples — because there are a handful
  of them fleet-wide and each one is somebody's open debt.
"""

from datetime import datetime
from typing import List

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler
from aipass.memory.apps.handlers.repo_root import module_file

_MEMORY_ROOT = module_file(__file__).parents[3]
REPORTS_DIR = _MEMORY_ROOT / "artifacts" / "push_reports"

# Per-entry detail is capped per branch; the remainder is COUNTED, never
# silently dropped — a truncation that does not announce itself reads as
# completeness.
MAX_PRUNE_SAMPLES = 6


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

    reshapes = entry.get("reshapes", [])
    todos = _todo_clause(entry.get("todos_seen", 0), len(reshapes), dry_run)
    if dry_run:
        lines.append(f"   would prune {entry['pruned']} entries · {entry['carried']} carry over untouched · {todos}")
        lines.extend(_prune_lines(entry.get("prunes", [])))
        lines.extend(_reshape_lines(reshapes))
        lines.extend(_frame_lines(entry.get("frame_changes", {})))
    else:
        lines.append(
            f"   pruned {entry['pruned']} · carried {entry['carried']} · files written {entry['written']}"
            f" · note {'written' if entry['noted'] else 'not needed'}"
            f" · receipt {'stamped' if entry['receipt'] else 'NOT stamped'}"
            f" · {todos}"
        )
        lines.extend(_reshape_lines(reshapes))
        lines.extend(f"     ! {message}" for message in entry.get("errors", []))

    strays = entry.get("strays", [])
    if strays:
        lines.append(f"   NOT push scope — {len(strays)} stray file(s) in .trinity/: {', '.join(strays)}")
    lines.append("")
    return lines


def _todo_clause(seen: int, reshaping: int, dry_run: bool) -> str:
    """What the push saw in ``todos`` — stated on EVERY branch, every run.

    Silence used to be the report's answer for a branch with no drifted todos,
    which made "this agent owes nothing" and "this agent's open work is gone"
    render identically. That is the exact blindness the morning of 2026-08-27
    ran into: 67 todos were archived across 8 branches and every affected
    agent loaded an empty list that read as a clean desk. A count nobody asked
    for is cheap; a zero you cannot interpret costs a fleet a morning.
    """
    tense = "to reshape in place" if dry_run else "left to reshape"
    return f"todos {seen} seen, {reshaping} {tense}"


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


def _reshape_lines(reshapes: List[dict]) -> List[str]:
    """Every todo the push refused to archive, named in full.

    Not capped like the prune samples: a prune sample is a pointer into a
    vector store that holds the whole entry, while this is the ONLY place the
    left-behind work is named. Dropping the tail here would leave an agent
    believing it owed fewer debts than it does.
    """
    if not reshapes:
        return []
    lines = ["   LEFT IN PLACE — open work is never archived; reshape these here:"]
    for record in reshapes:
        number = record["number"] if record.get("number") is not None else "?"
        lines.append(f"     ~ {record['container']}[{record['index']}] #{number}: {record['reason']}")
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


def _summary_block(result: dict) -> List[str]:
    """Fleet totals and the refusal roll-call."""
    pruned = sum(entry.get("pruned", 0) for entry in result["branches"])
    carried = sum(entry.get("carried", 0) for entry in result["branches"])
    refused = [entry["branch"] for entry in result["branches"] if entry.get("refused")]
    reshaping = [entry for entry in result["branches"] if entry.get("reshapes")]
    reshaped = sum(len(entry["reshapes"]) for entry in reshaping)
    lines = [
        "─" * 64,
        f"TOTAL: {pruned} entries to archive · {carried} carry over · {len(result['branches'])} branches",
    ]
    if reshaping:
        roll = ", ".join(f"{entry['branch']} ({len(entry['reshapes'])})" for entry in reshaping)
        lines.append(f"TODOS LEFT TO RESHAPE: {reshaped} across {len(reshaping)} branch(es) — {roll}")
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
