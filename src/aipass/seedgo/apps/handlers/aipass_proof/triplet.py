# =================== AIPass ====================
# Name: triplet.py
# Description: Verify standard triplet completeness (check + content + md)
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""Triplet Proof -- Verify every standard has all 3 files: *_check.py, *_content.py, *.md

Interface:
    scan(pack_dir: Path) -> dict
    Returns: {"passed": bool, "total": int, "complete": list, "check_only": list,
              "missing_check": list, "other_incomplete": list, "orphaned": list,
              "issues": list, "summary": str}

Reference: tools/triplet_scanner.py (original prototype)
"""

from __future__ import annotations

from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

# Directories to skip entirely
_SKIP_DIRS = {".archive", ".sorting_unprocessed", "__pycache__"}


def _top_level_files(pack_dir: Path) -> list[Path]:
    """Return all regular files directly in *pack_dir*, skipping hidden/skip dirs."""
    if not pack_dir.is_dir():
        return []
    return [p for p in pack_dir.iterdir() if p.is_file() and p.name not in _SKIP_DIRS and not p.name.startswith("_")]


def scan(pack_dir: Path) -> dict:
    """Run triplet completeness scan on a standards pack directory.

    Every standard should have three files: {name}_check.py, {name}_content.py, {name}.md.
    Files that don't fit any triplet pattern are flagged as orphaned.

    Args:
        pack_dir: Path to the standards pack directory (e.g. handlers/aipass_standards/).

    Returns:
        Dict with keys: passed, total, complete, check_only, missing_check,
        other_incomplete, orphaned, issues, summary.
    """
    logger.info(f"[triplet] Scanning {pack_dir}")

    checks: set[str] = set()
    contents: set[str] = set()
    docs: set[str] = set()
    orphaned_files: list[str] = []

    for filepath in _top_level_files(pack_dir):
        name = filepath.name

        if name.endswith("_check.py"):
            checks.add(name.removesuffix("_check.py"))

        elif name.endswith("_content.py"):
            contents.add(name.removesuffix("_content.py"))

        elif name.endswith(".md"):
            # Only lowercase-starting .md files participate in triplet matching.
            # Uppercase .md (e.g. README.md, SOP docs) are ancillary -- not orphaned.
            stem = filepath.stem
            if stem[0:1].islower():
                docs.add(stem)

        elif name.endswith(".py"):
            # .py files that are neither _check nor _content -- orphaned
            orphaned_files.append(name)

        elif name.endswith(".json"):
            # Config / ancillary JSON files -- not orphaned
            pass

        else:
            orphaned_files.append(name)

    # Union of all discovered standard names
    all_names = sorted(checks | contents | docs)

    complete: list[str] = []
    check_only: list[str] = []
    missing_check: list[str] = []
    other_incomplete: list[str] = []
    issues: list[dict[str, str | bool]] = []

    for std_name in all_names:
        has_check = std_name in checks
        has_content = std_name in contents
        has_md = std_name in docs

        entry = {
            "name": std_name,
            "has_check": has_check,
            "has_content": has_content,
            "has_md": has_md,
        }

        if has_check and has_content and has_md:
            complete.append(std_name)
        elif has_check and not has_content and not has_md:
            check_only.append(std_name)
            issues.append({**entry, "issue": "check only -- missing content + md"})
        elif not has_check:
            missing_check.append(std_name)
            missing = []
            if not has_check:
                missing.append("check")
            if not has_content:
                missing.append("content")
            if not has_md:
                missing.append("md")
            issues.append({**entry, "issue": f"missing: {', '.join(missing)}"})
        else:
            other_incomplete.append(std_name)
            missing = []
            if not has_content:
                missing.append("content")
            if not has_md:
                missing.append("md")
            issues.append({**entry, "issue": f"missing: {', '.join(missing)}"})

    passed = len(issues) == 0 and len(orphaned_files) == 0

    # Build human-readable summary
    parts = [f"{len(complete)} complete"]
    if check_only:
        parts.append(f"{len(check_only)} check-only")
    if missing_check:
        parts.append(f"{len(missing_check)} missing-check")
    if other_incomplete:
        parts.append(f"{len(other_incomplete)} other-incomplete")
    if orphaned_files:
        parts.append(f"{len(orphaned_files)} orphaned")
    parts.append(f"{len(all_names)} total")
    summary = " | ".join(parts)

    logger.info(f"[triplet] Result: {summary}")

    json_handler.log_operation("proof_scan", {"proof": "triplet", "passed": passed})

    return {
        "passed": passed,
        "total": len(all_names),
        "complete": complete,
        "check_only": check_only,
        "missing_check": missing_check,
        "other_incomplete": other_incomplete,
        "orphaned": orphaned_files,
        "issues": issues,
        "summary": summary,
    }
