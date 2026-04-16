# =================== AIPass ====================
# Name: readme_currency.py
# Description: Verify README.md accuracy against actual pack state
# Version: 1.0.0
# Created: 2026-03-22
# Modified: 2026-03-22
# =============================================

"""README Currency Proof -- Compare README checker counts and standard lists against actual pack.

Checks that the seedgo branch README.md accurately reflects the current state
of the standards pack: correct checker count, all standards documented, no stale
references to removed standards.

Interface:
    scan(pack_dir: Path) -> dict
    Returns: {"passed": bool, "readme_found": bool, "actual_check_count": int,
              "readme_counts": list, "undocumented": list, "stale_refs": list,
              "issues": list, "summary": str}

Reference: tools/readme_currency_scanner.py (original prototype)
"""

from __future__ import annotations

import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler


# -- Helpers -------------------------------------------------------------------


def _standard_name_from_file(filename: str) -> str:
    """Extract the standard name from a *_check.py filename.

    Example: 'cli_flags_check.py' -> 'cli_flags'
    """
    return filename.removesuffix("_check.py")


def _normalize_name(name: str) -> str:
    """Normalize a standard name for flexible matching.

    Lowercases, replaces spaces/hyphens with underscores, strips
    surrounding whitespace, and collapses repeated underscores.
    """
    name = name.lower().strip()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name


def _extract_readme_count_references(
    readme_text: str,
) -> list[dict[str, str | int]]:
    """Find lines that reference a number followed by checker/standard/etc.

    Returns a list of dicts with 'line', 'number', and 'context' keys.
    """
    results: list[dict[str, str | int]] = []
    pattern = re.compile(
        r"\b(\d+)\s+"
        r"(checker|checkers|standard|standards|check|checks)",
        re.IGNORECASE,
    )
    for lineno, line in enumerate(readme_text.splitlines(), start=1):
        for match in pattern.finditer(line):
            results.append(
                {
                    "line": lineno,
                    "number": int(match.group(1)),
                    "context": line.strip(),
                }
            )
    return results


def _extract_readme_standard_names(readme_text: str) -> set[str]:
    """Extract standard names mentioned in the README.

    Looks for the 'Checker Packs' section listing. Handles comma-separated
    lists like 'architecture, CLI, CLI flags, ... and diagnostics patterns'.
    """
    names: set[str] = set()

    # Parse the comma/and-separated list in the Checker Packs section.
    checks_pattern = re.compile(r"pack\s+checks?:\s*(.+?)(?:\.|$)", re.IGNORECASE | re.DOTALL)
    match = checks_pattern.search(readme_text)
    if match:
        raw_list = match.group(1)
        # Split on commas and ", and "
        raw_list = re.sub(r",?\s+and\s+", ",", raw_list)
        for item in raw_list.split(","):
            item = item.strip().rstrip(".")
            if item:
                names.add(_normalize_name(item))

    return names


# -- Core scan -----------------------------------------------------------------


def scan(pack_dir: Path) -> dict:
    """Compare README.md checker counts and standard lists against actual pack state.

    Args:
        pack_dir: Path to the standards pack directory (e.g. handlers/aipass_standards/).
                  The seedgo README.md is located at pack_dir.parent.parent.parent / "README.md".

    Returns:
        Dict with keys: passed, readme_found, actual_check_count, readme_counts,
        undocumented, stale_refs, issues, summary.
    """
    issues: list[str] = []

    # -- Gather actual standards from pack_dir --
    if not pack_dir.is_dir():
        msg = f"Pack directory not found: {pack_dir}"
        logger.warning(msg)
        return {
            "passed": False,
            "readme_found": False,
            "actual_check_count": 0,
            "readme_counts": [],
            "undocumented": [],
            "stale_refs": [],
            "issues": [msg],
            "summary": msg,
        }

    check_files = sorted(pack_dir.glob("*_check.py"))
    actual_names: set[str] = {_standard_name_from_file(f.name) for f in check_files}
    actual_check_count = len(check_files)

    # -- Locate README --
    # pack_dir is e.g. .../seedgo/apps/handlers/aipass_standards/
    # seedgo root = pack_dir.parent.parent.parent
    seedgo_root = pack_dir.parent.parent.parent
    readme_path = seedgo_root / "README.md"

    if not readme_path.is_file():
        msg = f"README not found: {readme_path}"
        issues.append(msg)
        return {
            "passed": False,
            "readme_found": False,
            "actual_check_count": actual_check_count,
            "readme_counts": [],
            "undocumented": sorted(actual_names),
            "stale_refs": [],
            "issues": issues,
            "summary": msg,
        }

    readme_text = readme_path.read_text(encoding="utf-8")

    # -- Count references --
    count_refs = _extract_readme_count_references(readme_text)
    count_mismatch = any(ref["number"] != actual_check_count for ref in count_refs)
    if count_mismatch:
        for ref in count_refs:
            if ref["number"] != actual_check_count:
                issues.append(
                    f"Line {ref['line']}: README says {ref['number']} but actual count is {actual_check_count}"
                )

    # -- Name references --
    readme_names = _extract_readme_standard_names(readme_text)

    # Build lookup tables for normalized matching
    actual_lookup: dict[str, str] = {_normalize_name(n): n for n in actual_names}
    readme_lookup: dict[str, str] = {_normalize_name(n): n for n in readme_names}

    actual_norm = set(actual_lookup.keys())
    readme_norm = set(readme_lookup.keys())

    # Flexible matching: a README name matches if it is a substring of or
    # equal to any actual normalized name, and vice-versa.
    matched_actual: set[str] = set()
    matched_readme: set[str] = set()

    for rn in readme_norm:
        for an in actual_norm:
            if rn == an or rn in an or an in rn:
                matched_actual.add(an)
                matched_readme.add(rn)

    stale_norm = readme_norm - matched_readme
    missing_norm = actual_norm - matched_actual

    stale_refs = sorted(readme_lookup[n] for n in stale_norm)
    undocumented = sorted(actual_lookup[n] for n in missing_norm)

    if stale_refs:
        issues.append(f"Stale references in README: {', '.join(stale_refs)}")
    if undocumented:
        issues.append(f"Undocumented standards: {', '.join(undocumented)}")

    passed = not count_mismatch and not stale_refs and not undocumented

    # -- Summary --
    if passed:
        summary = f"README is current. {actual_check_count} checkers, all documented, no stale references."
    else:
        parts: list[str] = []
        if count_mismatch:
            parts.append("count mismatch")
        if stale_refs:
            parts.append(f"{len(stale_refs)} stale reference(s)")
        if undocumented:
            parts.append(f"{len(undocumented)} undocumented standard(s)")
        summary = f"README is stale: {', '.join(parts)}."

    logger.info(f"readme_currency proof: {summary}")

    json_handler.log_operation("proof_scan", {"proof": "readme_currency", "passed": passed})

    return {
        "passed": passed,
        "readme_found": True,
        "actual_check_count": actual_check_count,
        "readme_counts": count_refs,
        "undocumented": undocumented,
        "stale_refs": stale_refs,
        "issues": issues,
        "summary": summary,
    }
