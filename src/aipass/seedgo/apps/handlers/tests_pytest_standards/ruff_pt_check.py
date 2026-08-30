# =================== AIPass ====================
# Name: ruff_pt_check.py
# Description: nominator - the adopt-half, ruff's flake8-pytest-style family
# Version: 1.0.0
# Created: 2026-08-29
# Modified: 2026-08-29
# =============================================

"""
The adopt-not-build half of the static tier: `ruff --select PT`.

Not a TAXONOMY-ranked rule and deliberately so. The PT family is
`flake8-pytest-style` reimplemented in Rust — fixture scope mistakes, raises
blocks that are too broad, parametrize shapes, `assertTrue` left over from
unittest. It is thirty-odd checks somebody else maintains, it runs the whole
fleet in about a third of a second, and reimplementing it here would be the
purest waste in the campaign.

WHAT MAKES THIS A NOMINATOR AND NOT A LINTER RUN. Ruff emits diagnostics with
severities and a fix-availability flag; this module discards all of that and
publishes each one as a `suspect` nomination with a code and a location. Law
S7a forbids an unscored group from carrying a score, and Law M1 says static
NOMINATES — so a PT diagnostic here is not a failure, it is a pointer.

RUFF'S ABSENCE IS A `not_applicable`, NEVER A ZERO AND NEVER A SILENT PASS.
The tool is not guaranteed present on a machine measuring an external target,
and a group that scored clean because the linter was missing would be the
exact lie Law S1 exists to stop. The group says which of the three happened:
ruff ran, ruff is not installed, or ruff failed — each in its own words.
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

#: The rule family. PT is flake8-pytest-style; nothing else is selected,
#: because every other family is already the audit's business, not this lane's.
RULE_SELECTOR = "PT"

#: Both spellings of the binary, because the sibling of a Windows interpreter
#: is `ruff.exe` and a POSIX-only name list would report "not installed" on
#: every Windows machine that has it.
RUFF_NAMES = ("ruff", "ruff.exe")

#: Wall-clock ceiling. Research measured the whole fleet at ~0.3s; anything
#: near this ceiling means something is wrong rather than slow.
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
    """The candidate ruff paths beside the running interpreter, both spellings.

    `sys.executable` IS the venv's python when the lane runs under a venv, so
    its directory is where `pip install ruff` put the binary.
    """
    beside = Path(sys.executable).parent
    return [beside / name for name in RUFF_NAMES]


def _ruff_binary() -> str:
    """The ruff executable, or "" when there is not one on this machine.

    THE INTERPRETER'S OWN DIRECTORY IS SEARCHED BEFORE PATH. A PATH-only lookup
    reported "ruff is not installed" on a machine that had had ruff in its venv
    for months: the calling process's PATH did not carry `.venv/bin`, so the
    whole PT family published a not_applicable it had no right to. A false
    not_applicable is the exact species this lane exists to kill, and it is
    worse here than anywhere else, because the group that goes missing is the
    one nobody re-checks by hand.

    A sibling counts only if it is a FILE that is EXECUTABLE - a directory
    named `ruff`, or a downloaded archive nobody chmod'd, is not a linter, and
    handing its path to subprocess would turn an absence into a crash.
    """
    for candidate in _interpreter_siblings():
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    return shutil.which("ruff") or ""


def _absent_reason() -> str:
    """Why ruff could not be found, NAMING BOTH PLACES that were searched.

    "ruff is not installed" is what this said before, and it is why the defect
    lived: the sentence was true of PATH and false of the machine, and no
    reader of the artifact could tell which claim they were holding. The
    not_applicable reason now carries both candidate locations, so the answer
    to "installed where?" is in the document rather than in a re-run.
    """
    looked = " and ".join(str(candidate) for candidate in _interpreter_siblings())
    return (
        "ruff is not installed on this machine, so the PT family could not be checked: "
        f"looked beside the running interpreter at {looked}, then on PATH via shutil.which('ruff')"
    )


def _run_ruff(binary: str, root: Path, paths: List[str]) -> Tuple[List[dict], str]:
    """Run ruff over the given paths. Returns `(diagnostics, error)`.

    A non-zero exit is NORMAL for a linter that found something, so the return
    code is not treated as failure — only an unparseable stdout is. Conflating
    "found problems" with "could not run" is how a lane reports a clean sheet
    for a tool that crashed.
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
        # Never swallowed into an empty diagnostic list: unreadable output and
        # a clean run must not produce the same group document.
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
        # An absolute path still identifies the file, but it will not match a
        # nodeid pasted into pytest from the target's own root, so the fallback
        # is recorded rather than taken quietly.
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

    Raises RuntimeError when ruff is absent or failed, which the orchestrator
    turns into a `not_applicable` group carrying that reason. Returning an
    empty list instead would publish a clean group for a tool that never ran.
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
