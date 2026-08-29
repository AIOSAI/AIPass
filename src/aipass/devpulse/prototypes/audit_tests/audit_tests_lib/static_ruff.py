# =================== AIPass ====================
# Name: static_ruff.py - the adopt-not-build half of the static tier
# Description: ruff's PT family over the copied test files, as nominations
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Run ruff's ``PT`` family over the copied test files.

The adopt half of the two-tool split (``test_quality_tooling_research.md``
§8.1.5): ruff has no plugin API, so the custom rules live in ``ast`` and the
flake8-pytest-style family is taken as-is.  ``PT011`` -- ``pytest.raises(OSError)``
with no ``match=``, which passes for any ``OSError`` from any line -- is the one
the report calls the real prize.

``--isolated`` is deliberate: the target's own ruff config may switch PT off, and
a nominator that inherits the settings of the code it is inspecting is not a
second opinion.

Absent ruff, this group is ``not_applicable`` with a reason.  Law S1: not-run is
never 0.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


from .logsetup import logger


def find_ruff(override: str | None = None, beside: Path | None = None) -> tuple[str | None, str]:
    """Locate a ruff binary; return ``(path, how_it_was_found)``."""
    if override:
        if Path(override).is_file():
            return override, "given on the command line"
        return None, f"{override} is not a file"
    on_path = shutil.which("ruff")
    if on_path:
        return on_path, "PATH"
    if beside is not None:
        sibling = Path(beside).parent / "ruff"
        if sibling.is_file():
            return str(sibling), "beside the interpreter that runs the target's suite"
    from_env = os.environ.get("AUDIT_TESTS_RUFF")
    if from_env and Path(from_env).is_file():
        return from_env, "AUDIT_TESTS_RUFF"
    beside = Path(sys.executable).parent / "ruff"
    if beside.is_file():
        return str(beside), "beside the running interpreter"
    return None, "ruff not installed"


def run(test_files: list[Path], root: Path, ruff_path: str | None, timeout: int = 300) -> dict:
    """Nominate with ruff, or say plainly why the group was not measured."""
    if not ruff_path:
        return {"status": "not_applicable", "reason": "ruff not installed", "nominations": []}
    if not test_files:
        return {"status": "not_applicable", "reason": "no test files to inspect", "nominations": []}

    command = [
        ruff_path,
        "check",
        "--isolated",
        "--select",
        "PT",
        "--output-format",
        "json",
        "--no-cache",
        *[str(p) for p in test_files],
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        logger.warning("ruff did not complete: %s", exc)
        return {
            "status": "not_applicable",
            "reason": f"ruff did not complete: {type(exc).__name__}",
            "nominations": [],
        }
    if result.returncode not in (0, 1):
        return {
            "status": "not_applicable",
            "reason": f"ruff exited {result.returncode}: {result.stderr.strip()[:200]}",
            "nominations": [],
        }
    try:
        findings = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        logger.warning("ruff produced unparseable JSON", exc_info=exc)
        return {"status": "not_applicable", "reason": "ruff produced unparseable JSON", "nominations": []}

    nominations = []
    by_code: dict[str, int] = {}
    for item in findings:
        code = item.get("code") or "?"
        by_code[code] = by_code.get(code, 0) + 1
        filename = item.get("filename", "")
        try:
            display = str(Path(filename).relative_to(root))
        except ValueError as exc:
            logger.debug("ruff named a file outside the root: %s", filename, exc_info=exc)
            display = filename
        nominations.append(
            {
                "file": display,
                "line": (item.get("location") or {}).get("row", 0),
                "code": code,
                "rule": item.get("name", ""),
                "message": item.get("message", ""),
            }
        )
    return {
        "status": "measured",
        "ruff": ruff_path,
        "select": "PT",
        "isolated": True,
        "by_code": dict(sorted(by_code.items())),
        "nominations": nominations,
    }
