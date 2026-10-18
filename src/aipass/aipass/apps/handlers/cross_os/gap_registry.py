# =================== AIPass ====================
# Name: gap_registry.py
# Description: Live-parse the cross-OS gap registry and filter by platform
# Version: 1.0.0
# Created: 2026-07-02
# Modified: 2026-10-17
# =============================================

"""Cross-OS gap registry parser — Layer-3-lite pre-flight source.

Source: the table in tests/CROSS_OS_TESTING.md (read-only to @aipass). A missing doc, section
or row raises CrossOsGapError, never "no gaps"; callers surface it as WARN/FAIL.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List, NamedTuple

from aipass.prax import logger
from aipass.aipass.apps.handlers.json import json_handler

DOC_RELATIVE = Path("tests") / "CROSS_OS_TESTING.md"

_SECTION_MARKER = "known cross-os gap registry"

# The doc's table columns: # | Gap | OS | Symptom | Owner | Status
_EXPECTED_COLUMNS = 6


class CrossOsGapError(RuntimeError):
    """Raised when the cross-OS gap registry cannot be located or parsed."""


class CrossOsGap(NamedTuple):
    """One row of the Known cross-OS gap registry table."""

    number: str
    gap: str
    os: str
    symptom: str
    owner: str
    status: str


def find_gap_doc(start: Path | None = None) -> Path:
    """Search upward from ``start`` (or this file) for ``tests/CROSS_OS_TESTING.md``."""
    base = (start or Path(__file__)).resolve()
    for parent in [base, *base.parents]:
        candidate = parent / DOC_RELATIVE
        if candidate.is_file():
            return candidate
    raise CrossOsGapError(f"cross-OS testing doc not found (searched upward from {base} for {DOC_RELATIVE})")


def parse_gap_registry(text: str) -> List[CrossOsGap]:
    """Parse the 'Known cross-OS gap registry' table out of the doc text."""
    lines = text.splitlines()

    section_idx = None
    for i, line in enumerate(lines):
        if line.lstrip().startswith("#") and _SECTION_MARKER in line.lower():
            section_idx = i
            break
    if section_idx is None:
        raise CrossOsGapError("'Known cross-OS gap registry' section not found in doc")

    gaps: List[CrossOsGap] = []
    for line in lines[section_idx + 1 :]:
        stripped = line.strip()
        if stripped.startswith("## "):
            break
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < _EXPECTED_COLUMNS:
            continue
        number = cells[0]
        # Data rows start with a digit; the header ("#") and separator ("---") do not.
        if not number or not number[0].isdigit():
            continue
        gaps.append(
            CrossOsGap(
                number=number,
                gap=cells[1],
                os=cells[2],
                symptom=cells[3],
                owner=cells[4],
                status=cells[5],
            )
        )

    if not gaps:
        raise CrossOsGapError("gap registry table found but no data rows could be parsed")
    return gaps


def load_gaps(start: Path | None = None) -> List[CrossOsGap]:
    """Locate, read, and parse the full gap registry."""
    doc = find_gap_doc(start)
    try:
        raw = doc.read_text(encoding="utf-8")
    except OSError as exc:
        raise CrossOsGapError(f"cross-OS testing doc unreadable at {doc}: {exc}") from exc
    logger.info("[cross_os] parsing gap registry from %s", doc)
    return parse_gap_registry(raw)


def os_matches(os_cell: str, platform_name: str) -> bool:
    """Return True if an OS cell applies to ``platform_name`` (a ``sys.platform`` value).

    'all' matches every platform, 'win' win32, 'mac' darwin; 'Win/mac' matches both.
    """
    cell = os_cell.lower()
    if "all" in cell:
        return True
    if platform_name == "win32":
        return "win" in cell
    if platform_name == "darwin":
        return "mac" in cell
    return False


def gaps_for_platform(platform_name: str | None = None, start: Path | None = None) -> List[CrossOsGap]:
    """Return only the gap rows relevant to ``platform_name`` (defaults to ``sys.platform``)."""
    plat = platform_name or sys.platform
    gaps = load_gaps(start)
    relevant = [g for g in gaps if os_matches(g.os, plat)]
    json_handler.log_operation(
        "cross_os_gap_lookup",
        {"platform": plat, "total": len(gaps), "relevant": len(relevant)},
    )
    return relevant
