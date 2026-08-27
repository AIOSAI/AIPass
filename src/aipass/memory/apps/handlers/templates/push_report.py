# =================== AIPass ====================
# Name: push_report.py
# Description: Renders and persists the trinity push report — the artifact the dry-run exists to produce
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Trinity Push Report

The dry-run's whole purpose is a report a human reads before granting a fleet
GO, so the rendering lives in a handler rather than in the CLI module: it is
domain work with its own rules, not display sugar.

Two of those rules earn their keep:

- **Per branch, never a wall.** The fleet report covers 22 branches; a flat
  list of 366 prune lines is technically complete and practically unreadable.
  Each branch gets its own block, and the per-entry detail is capped with the
  remainder counted out loud rather than silently dropped.
- **What is NOT in scope is stated.** Stray files in a branch's ``.trinity/``
  are reported in the same breath as the prunes and explicitly marked as
  outside the push's mandate, so a reader cannot mistake the push's silence
  about them for the push having handled them.
"""

from datetime import datetime
from pathlib import Path
from typing import List

from aipass.prax import logger
from aipass.memory.apps.handlers.json import json_handler

_MEMORY_ROOT = Path(__file__).resolve().parents[3]
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

    if dry_run:
        lines.append(f"   would prune {entry['pruned']} entries · {entry['carried']} carry over untouched")
        lines.extend(_prune_lines(entry.get("prunes", [])))
        lines.extend(_frame_lines(entry.get("frame_changes", {})))
    else:
        lines.append(
            f"   pruned {entry['pruned']} · carried {entry['carried']} · files written {entry['written']}"
            f" · note {'written' if entry['noted'] else 'not needed'}"
            f" · receipt {'stamped' if entry['receipt'] else 'NOT stamped'}"
        )
        lines.extend(f"     ! {message}" for message in entry.get("errors", []))

    strays = entry.get("strays", [])
    if strays:
        lines.append(f"   NOT push scope — {len(strays)} stray file(s) in .trinity/: {', '.join(strays)}")
    lines.append("")
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


def _summary_block(result: dict) -> List[str]:
    """Fleet totals and the refusal roll-call."""
    pruned = sum(entry.get("pruned", 0) for entry in result["branches"])
    carried = sum(entry.get("carried", 0) for entry in result["branches"])
    refused = [entry["branch"] for entry in result["branches"] if entry.get("refused")]
    lines = [
        "─" * 64,
        f"TOTAL: {pruned} entries to archive · {carried} carry over · {len(result['branches'])} branches",
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
