# =================== AIPass ====================
# Name: ruff_pt_check.py
# Description: nominator - the adopt-half, ruff's flake8-pytest-style family
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-10-17
# =============================================

"""The adopt-not-build half of the static tier: `ruff --select PT`.

Reference: ruff_pt.md
"""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

from aipass.prax import logger
from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

GROUP = "static_ruff_pt"

RULE_SELECTOR = "PT"

#: A POSIX-only name would report "not installed" on every Windows machine that has it.
RUFF_NAMES = ("ruff", "ruff.exe")

RUFF_TIMEOUT_SECONDS = 120

SPECIFICATION = {
    "rule": "adopt-half - ruff --select PT (flake8-pytest-style), not a TAXONOMY-ranked rule",
    "species": ["PT-FAMILY"],
    "flags": [
        "every diagnostic ruff's PT family reports over the target's test files, published as "
        "a nomination with its code and location",
    ],
    "exempts": [
        "whatever the target's own ruff configuration excludes - the target's config is "
        "respected, because a nominator that overrode it would be measuring a project nobody has",
    ],
    "fix": "most PT codes carry an automatic fix: `ruff check --select PT --fix <tests>`.",
    "limits": [
        "ruff may not be installed on a machine measuring an external target; that is reported "
        "as not_applicable with a reason, never as a clean result",
        "severity and fix-availability are discarded - this tier nominates and does not rank",
    ],
    "evidence": "~0.3s for the whole 18-branch fleet (research section 2.5)",
}


def _interpreter_siblings() -> List[Path]:
    """The candidate ruff paths beside the running interpreter, both spellings."""
    beside = Path(sys.executable).parent
    return [beside / name for name in RUFF_NAMES]


def _ruff_binary() -> str:
    """The ruff executable, or "" when there is not one on this machine.

    Beside the interpreter before PATH, which may not carry `.venv/bin`; executable files only.
    """
    for candidate in _interpreter_siblings():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ruff") or ""


def _absent_reason() -> str:
    """Why ruff could not be found, NAMING BOTH PLACES that were searched."""
    looked = " and ".join(str(candidate) for candidate in _interpreter_siblings())
    return (
        "ruff is not installed on this machine, so the PT family could not be checked: "
        f"looked beside the running interpreter at {looked}, then on PATH via shutil.which('ruff')"
    )


def _run_ruff(binary: str, root: Path, paths: List[str]) -> Tuple[List[dict], str]:
    """Run ruff over the given paths. Returns `(diagnostics, error)`.

    A non-zero exit is normal for a linter that found something; only unparseable stdout fails.
    """
    command = [binary, "check", "--select", RULE_SELECTOR, "--output-format", "json", "--no-cache", *paths]
    try:
        result = subprocess.run(command, cwd=str(root), capture_output=True, text=True, timeout=RUFF_TIMEOUT_SECONDS)
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning(f"[AUDIT-TESTS] ruff PT could not run in {root}: {exc}")
        return [], f"ruff could not run: {type(exc).__name__}: {exc}"

    try:
        parsed = json.loads(result.stdout or "[]")
    except json.JSONDecodeError as exc:
        # Unreadable output and a clean run must not produce the same group document.
        detail = (result.stderr or "").strip()[:300]
        logger.warning(f"[AUDIT-TESTS] ruff PT output was unreadable: {exc}")
        return [], f"ruff output was not readable JSON ({exc}){': ' + detail if detail else ''}"

    return (parsed if isinstance(parsed, list) else []), ""


def _row(diagnostic: dict, root: Path) -> dict:
    """One ruff diagnostic as a nomination row."""
    filename = str(diagnostic.get("filename", ""))
    try:
        relative = Path(filename).resolve().relative_to(root.resolve()).as_posix()
    except (ValueError, OSError) as exc:
        logger.warning(f"[AUDIT-TESTS] ruff reported {filename}, which is outside {root}: {exc}")
        relative = filename

    location = diagnostic.get("location") or {}
    code = str(diagnostic.get("code") or "PT")

    return {
        "species": "PT-FAMILY",
        "file": relative,
        "line": int(location.get("row") or 0),
        "nodeid": "",
        "test": "",
        "verdict": corpus.VERDICT_IMPROVE,
        "why": f"{code}: {diagnostic.get('message', 'ruff reported a pytest-style problem')}",
        "deletion_safety": dict(corpus.DELETION_SAFETY_UNPROBED),
        "evidence": {"code": code, "url": diagnostic.get("url", "")},
    }


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every PT diagnostic over the corpus, as nominations.

    Raises RuntimeError when ruff is absent or failed: an empty list would publish a clean group.
    """
    binary = _ruff_binary()
    if not binary:
        raise RuntimeError(_absent_reason())

    paths = sorted({parsed.relpath for parsed in scanned.files})
    if not paths:
        return []

    diagnostics, error = _run_ruff(binary, scanned.root, paths)
    if error:
        raise RuntimeError(error)

    return [_row(diagnostic, scanned.root) for diagnostic in diagnostics]
