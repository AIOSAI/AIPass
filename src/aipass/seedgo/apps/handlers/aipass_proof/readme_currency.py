# =================== AIPass ====================
# Name: readme_currency.py
# Description: Verify README.md accuracy against actual pack state
# Version: 1.1.0
# Created: 2026-03-22
# Modified: 2026-10-24
# =============================================

"""README Currency Proof -- Compare README checker counts and standard lists against actual pack.

Checks that the seedgo branch README.md carries no stale checker count, and that the
pack's docs pages (docs/<pack>*.md, indexed from the README) table every standard
in the pack with no stale rows for removed ones.
"""

from __future__ import annotations

import re
from pathlib import Path

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

TABLE_ROW = re.compile(r"^\| ([a-z_0-9]+)\b", re.MULTILINE)


def _standard_name_from_file(filename: str) -> str:
    """Extract the standard name from a *_check.py filename."""
    return filename.removesuffix("_check.py")


def _normalize_name(name: str) -> str:
    """Normalize a standard name for flexible matching."""
    name = name.lower().strip()
    name = re.sub(r"[\s\-]+", "_", name)
    name = re.sub(r"_+", "_", name)
    return name


def _extract_readme_count_references(
    readme_text: str,
) -> list[dict[str, str | int]]:
    """Find lines that reference a number followed by checker/standard/etc."""
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


def _extract_table_standard_names(pack_name: str, docs_dir: Path) -> set[str]:
    """The first cell of every table row on the pack's docs pages, where the README indexes the standards."""
    names: set[str] = set()
    for page in sorted(docs_dir.glob(f"{pack_name}*.md")):
        names |= {_normalize_name(m.group(1)) for m in TABLE_ROW.finditer(page.read_text(encoding="utf-8"))}
    return names


def scan(pack_dir: Path) -> dict:
    """Compare README.md checker counts and standard lists against actual pack state."""
    issues: list[str] = []

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

    count_refs = _extract_readme_count_references(readme_text)
    count_mismatch = any(ref["number"] != actual_check_count for ref in count_refs)
    if count_mismatch:
        for ref in count_refs:
            if ref["number"] != actual_check_count:
                issues.append(
                    f"Line {ref['line']}: README says {ref['number']} but actual count is {actual_check_count}"
                )

    readme_names = _extract_table_standard_names(pack_dir.name, seedgo_root / "docs")

    actual_lookup: dict[str, str] = {_normalize_name(n): n for n in actual_names}
    readme_lookup: dict[str, str] = {_normalize_name(n): n for n in readme_names}

    actual_norm = set(actual_lookup.keys())
    readme_norm = set(readme_lookup.keys())

    # Exact after normalising: `cli` naming `cli_flags` would hide a stale or missing row.
    stale_norm = readme_norm - actual_norm
    missing_norm = actual_norm - readme_norm

    stale_refs = sorted(readme_lookup[n] for n in stale_norm)
    undocumented = sorted(actual_lookup[n] for n in missing_norm)

    if stale_refs:
        issues.append(f"Stale references in README: {', '.join(stale_refs)}")
    if undocumented:
        issues.append(f"Undocumented standards: {', '.join(undocumented)}")

    passed = not count_mismatch and not stale_refs and not undocumented

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
