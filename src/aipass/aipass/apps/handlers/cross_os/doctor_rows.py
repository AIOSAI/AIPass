# =================== AIPass ====================
# Name: doctor_rows.py
# Description: The rows of `aipass doctor --cross-os`, built for doctor to print
# Version: 1.0.0
# Created: 2026-09-29
# Modified: 2026-09-29
# =============================================

"""Cross-OS pre-flight rows for `aipass doctor --cross-os`.

Moved out of apps/modules/doctor.py on 2026-09-29 (fleet green leg 5, aipass's
decision) to give doctor.py room under its line cap. The rows are built here and
doctor only prints them: run_cross_os and run_cross_os_record stay in doctor.
No answer and no printed line changed in the move.
"""

from __future__ import annotations

import sys
from typing import List, NamedTuple

from aipass.prax import logger

from aipass.aipass.apps.handlers.cross_os.gap_registry import CrossOsGapError, gaps_for_platform
from aipass.aipass.apps.handlers.cross_os.preflight import (
    E2E_UNRUNNABLE_PREFIX,
    PreflightResult,
    check_hookstatus,
    check_routing,
    check_versions,
)
from aipass.aipass.apps.handlers.cross_os.preflight import run_e2e as run_e2e_preflight
from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN


class CrossOsRow(NamedTuple):
    """One doctor check row (the fields of doctor.CheckResult, without importing a module)."""

    label: str
    glyph: str
    detail: str
    remediation: str


def cross_os_gap_rows() -> List[CrossOsRow]:
    """OS-gap cross-reference rows (slice 1): tracked gaps for this platform.

    Machine pre-flight — surfaces OS-specific gaps from tests/CROSS_OS_TESTING.md
    for this box. Never claims the checklist's human green. WARN per gap, a single
    PASS when none apply, a single WARN when the registry can't be read (never
    silent).
    """
    platform_name = sys.platform
    try:
        gaps = gaps_for_platform(platform_name)
    except CrossOsGapError as exc:
        logger.warning("[doctor] cross-OS gap registry unavailable: %s", exc)
        return [
            CrossOsRow(
                "cross-os registry (pre-flight)",
                GLYPH_WARN,
                f"pre-flight: gap registry unavailable — {exc}",
                "Ensure tests/CROSS_OS_TESTING.md has a 'Known cross-OS gap registry' table",
            )
        ]

    if not gaps:
        return [
            CrossOsRow(
                "cross-os (pre-flight)",
                GLYPH_PASS,
                f"pre-flight: no tracked cross-OS gaps for {platform_name}",
                "",
            )
        ]

    return [
        CrossOsRow(
            f"cross-os gap #{gap.number} (pre-flight)",
            GLYPH_WARN,
            f"pre-flight: {gap.symptom}",
            f"tracked gap [{gap.status}] — owner {gap.owner}; human Layer-3 pass still required",
        )
        for gap in gaps
    ]


def preflight_row(label: str, result: PreflightResult, remediation: str) -> CrossOsRow:
    """Map a non-mutating PreflightResult to a labelled pre-flight row.

    ok -> PASS, else FAIL. The detail is always prefixed 'pre-flight:' so a row
    can never be mistaken for the checklist's human acceptance green.
    """
    glyph = GLYPH_PASS if result.ok else GLYPH_FAIL
    return CrossOsRow(f"{label} (pre-flight)", glyph, f"pre-flight: {result.detail}", "" if result.ok else remediation)


def e2e_row(result: PreflightResult) -> CrossOsRow:
    """Map the heavy e2e PreflightResult to a row (PASS/FAIL/WARN).

    ok -> PASS. Un-runnable infra cases (dir missing, no pytest, timeout) -> WARN.
    Real test failures -> FAIL.
    """
    if result.ok:
        glyph, remediation = GLYPH_PASS, ""
    elif result.detail.startswith(E2E_UNRUNNABLE_PREFIX):
        glyph = GLYPH_WARN
        remediation = "Ensure a project .venv with pytest (or system pytest) and tests/e2e are present"
    else:
        glyph, remediation = GLYPH_FAIL, "Run 'pytest tests/e2e -q' from the repo root to inspect the failures"
    return CrossOsRow("e2e suite (pre-flight)", glyph, f"pre-flight: {result.detail}", remediation)


def check_cross_os(run_e2e: bool = False) -> List[CrossOsRow]:
    """Cross-OS pre-flight group (Layer-3-lite): gap cross-reference + machine routes.

    Combines the slice-1 OS-gap rows with the non-mutating routing / --version /
    hookstatus probes (Phase 4 / 1.3 / 6.3). None of these wake a citizen. When
    ``run_e2e`` is set, also runs the heavy Phase-2 e2e suite. Every row is
    labelled pre-flight and still needs the human Layer-3 pass.
    """
    results = cross_os_gap_rows()

    results.append(
        preflight_row(
            "routing", check_routing(), "Ensure aipass is installed (setup.sh) so 'drone systems' and routes resolve"
        )
    )
    results.append(
        preflight_row(
            "versions", check_versions(), "Ensure 'drone' and 'aipass' are on PATH (clone the repo, run setup.sh)"
        )
    )
    results.append(
        preflight_row("hookstatus", check_hookstatus(), "Check @hooks routing: 'drone @hooks status' should exit 0")
    )

    if run_e2e:
        results.append(e2e_row(run_e2e_preflight()))

    return results


def record_path_arg(args: list[str]) -> str | None:
    """Extract the optional PATH value following ``--record`` (None if absent).

    ``--record`` may stand alone (default path) or be followed by a path; a
    following token that starts with ``-`` is another flag, not the path.
    """
    if "--record" not in args:
        return None
    idx = args.index("--record")
    if idx + 1 < len(args):
        candidate = args[idx + 1]
        if not candidate.startswith("-"):
            return candidate
    return None
