# =================== AIPass ====================
# Name: ruff_check.py
# Description: Ruff Linter & Formatter Standards Checker Handler
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-04-26
# =============================================

"""
Ruff Linter & Formatter Standards Checker Handler

Runs both ``ruff check`` (lint) and ``ruff format --check`` (formatting).

Two modes:
- check_branch(): runs ruff across entire apps/ tree (used by audit pipeline,
  AUDIT_SCOPE = branch_level, ADVISORY = always-passes)
- check_module(): runs ruff on a single file (used by checklist/per-file hooks,
  returns passed=False on violations so subagent_stop_gate can block)

AUDIT_SCOPE: branch_level — audit pipeline uses check_branch() once per branch.
  Checkers that also implement check_module() are eligible for per-file checklist runs.
ADVISORY: check_branch() surfaces violations but always passes (advisory score).
          check_module() returns passed=False so checklist/hooks can block.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler
from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed

AUDIT_SCOPE = "branch_level"
ADVISORY = True

# ruff format --check marks each unformatted file with this prefix; every other
# stdout line is summary prose.
_FORMAT_PREFIX = "Would reformat: "


def _load_ruff_bypass(branch_path: Path) -> list:
    """Load .seedgo/ruff_bypass.json for ruff-specific bypass rules."""
    bypass_file = branch_path / ".seedgo" / "ruff_bypass.json"
    if not bypass_file.exists():
        return []
    try:
        data = json.loads(bypass_file.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception as exc:
        logger.warning("Failed to load ruff_bypass.json: %s", exc)
        return []


def _is_ruff_bypassed(violation: dict, ruff_bypass: list) -> bool:
    """Check if a single ruff violation matches any ruff-specific bypass rule.

    Bypass rule format: {"file": "partial/path.py", "code": "E501", "line": 42}
    All fields optional — omitting a field means "match any".
    """
    v_file = violation.get("filename", "")
    v_code = violation.get("code", "")
    v_line = violation.get("location", {}).get("row")
    for rule in ruff_bypass:
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in v_file:
            continue
        rule_code = rule.get("code", "")
        if rule_code and rule_code != v_code:
            continue
        rule_line = rule.get("line")
        if rule_line is not None and v_line != rule_line:
            continue
        return True
    return False


def _score_from_count(count: int) -> int:
    """Map violation count to a 0–100 score."""
    if count == 0:
        return 100
    if count <= 5:
        return 95
    if count <= 20:
        return 85
    if count <= 50:
        return 70
    if count <= 100:
        return 50
    return 25


def _find_ruff_bypass_from_file(file_path: str) -> list:
    """Walk up from file_path to find .seedgo/ruff_bypass.json at the branch root."""
    fp = Path(file_path).resolve()
    for parent in list(fp.parents):
        candidate = parent / ".seedgo" / "ruff_bypass.json"
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                return data if isinstance(data, list) else []
            except Exception as exc:
                logger.warning("Failed to load ruff_bypass.json at %s: %s", candidate, exc)
                return []
        if (parent / ".git").exists():
            break
    return []


def check_module(module_path: str, bypass_rules: list | None = None) -> Dict:
    """Run ruff check on a single file.

    Used by checklist mode and subagent_stop_gate for per-file enforcement.
    Returns passed=False when violations exist so hooks can block.

    Args:
        module_path: Absolute path to the Python file to check.
        bypass_rules: Standard bypass rules from .seedgo/bypass.json

    Returns:
        dict with passed, checks, score, standard keys.
    """
    fp = Path(module_path)

    if is_bypassed(module_path, "ruff_check", bypass_rules=bypass_rules):
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "RUFF_CHECK",
        }

    if shutil.which("ruff") is None:
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": "ruff not installed — check skipped"}],
            "score": 100,
            "standard": "RUFF_CHECK",
        }

    ruff_bypass = _find_ruff_bypass_from_file(module_path)

    try:
        proc = subprocess.run(
            ["ruff", "check", str(fp), "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ruff check_module timed out on %s", module_path)
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": "ruff check timed out — skipped"}],
            "score": 100,
            "standard": "RUFF_CHECK",
        }
    except Exception as exc:
        logger.warning("ruff check_module failed on %s: %s", module_path, exc)
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": f"ruff error — skipped: {exc}"}],
            "score": 100,
            "standard": "RUFF_CHECK",
        }

    violations: list = []
    if proc.stdout.strip():
        try:
            violations = json.loads(proc.stdout)
            if not isinstance(violations, list):
                violations = []
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning("ruff JSON parse failed for %s: %s", module_path, exc)
            violations = []

    active = [v for v in violations if not _is_ruff_bypassed(v, ruff_bypass)]
    count = len(active)

    checks: list[dict] = []
    passed = True

    if count == 0:
        checks.append({"name": "Ruff lint", "passed": True, "message": "No ruff violations found"})
    else:
        top = active[:5]
        msgs = [
            f"{v.get('code', '?')} L{v.get('location', {}).get('row', '?')}: {v.get('message', '?')[:80]}" for v in top
        ]
        suffix = f" (and {count - 5} more)" if count > 5 else ""
        detail = f"{count} violation(s) — " + "; ".join(msgs) + suffix
        checks.append({"name": "Ruff lint", "passed": False, "message": detail})
        passed = False

    # --- ruff format --check ---
    needs_format = False
    try:
        fmt_proc = subprocess.run(
            ["ruff", "format", "--check", str(fp)],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if fmt_proc.returncode != 0:
            needs_format = True
    except subprocess.TimeoutExpired:
        logger.warning("ruff format --check timed out on %s", module_path)
    except Exception as exc:
        logger.warning("ruff format --check failed on %s: %s", module_path, exc)

    if needs_format:
        checks.append({"name": "Ruff format", "passed": False, "message": f"{fp.name} needs ruff format"})
        passed = False
    else:
        checks.append({"name": "Ruff format", "passed": True, "message": "File is formatted"})

    score = 100 if passed else 0

    json_handler.log_operation(
        "check_completed",
        {
            "file": module_path,
            "score": score,
            "standard": "ruff_check",
            "violations": count,
            "needs_format": needs_format,
        },
    )

    return {
        "passed": passed,
        "checks": checks,
        "score": score,
        "standard": "RUFF_CHECK",
    }


def check_branch(branch_path: str, bypass_rules: list | None = None) -> Dict:
    """Run ruff against the branch and score based on violation count.

    Args:
        branch_path: Path to branch root (e.g., src/aipass/seedgo)
        bypass_rules: Standard bypass rules from .seedgo/bypass.json

    Returns:
        dict: {
            'passed': bool (always True — advisory mode),
            'checks': [{'name': str, 'passed': bool, 'message': str}],
            'score': int,
            'standard': 'RUFF_CHECK',
            'advisory': True
        }
    """
    bp = Path(branch_path)

    # Standard-level bypass
    if is_bypassed(branch_path, "ruff_check", bypass_rules=bypass_rules):
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "ruff_check"},
        )
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": "Standard bypassed via .seedgo/bypass.json"}],
            "score": 100,
            "standard": "RUFF_CHECK",
            "advisory": True,
        }

    # Graceful degradation: ruff not installed
    if shutil.which("ruff") is None:
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 100, "standard": "ruff_check", "status": "skipped"},
        )
        return {
            "passed": True,
            "checks": [{"name": "Ruff check", "passed": True, "message": "ruff not installed — check skipped"}],
            "score": 100,
            "status": "skipped",
            "standard": "RUFF_CHECK",
            "advisory": True,
        }

    # Scan apps/ AND tests/ — CI's gate is `ruff check src/ tests/` from the repo root,
    # which reaches every branch's tests/ too. Scanning apps/ alone is why this branch
    # read 100 on trigger while CI failed three of its test files on formatting
    # (macOS run 34682737363, FPLAN-0554). Fall back to the whole branch when neither
    # directory exists, so a branch with an unusual layout is still covered.
    scan_targets = [d for d in (bp / "apps", bp / "tests") if d.is_dir()] or [bp]

    # Load ruff-specific bypass rules
    ruff_bypass = _load_ruff_bypass(bp)

    # Run ruff
    try:
        proc = subprocess.run(
            ["ruff", "check", *(str(t) for t in scan_targets), "--output-format=json"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        logger.warning("ruff check timed out on branch %s", branch_path)
        json_handler.log_operation(
            "check_completed",
            {"branch": branch_path, "score": 0, "standard": "ruff_check", "error": "timeout"},
        )
        return {
            "passed": False,
            "checks": [{"name": "Ruff check", "passed": False, "message": "ruff check timed out after 60s"}],
            "score": 0,
            "standard": "RUFF_CHECK",
            "advisory": True,
        }

    # Parse JSON output (ruff exits 0=clean, 1=violations, 2+=error)
    violations: list = []
    if proc.stdout.strip():
        try:
            violations = json.loads(proc.stdout)
            if not isinstance(violations, list):
                violations = []
        except (json.JSONDecodeError, ValueError):
            stderr_snippet = proc.stderr[:300] if proc.stderr else "(no stderr)"
            logger.warning("ruff JSON parse failed on %s: %s", branch_path, stderr_snippet)
            json_handler.log_operation(
                "check_completed",
                {"branch": branch_path, "score": 0, "standard": "ruff_check", "error": "json_parse"},
            )
            return {
                "passed": False,
                "checks": [
                    {"name": "Ruff check", "passed": False, "message": f"ruff JSON parse failed: {stderr_snippet}"}
                ],
                "score": 0,
                "standard": "RUFF_CHECK",
                "advisory": True,
            }

    # Filter bypassed violations
    active = [v for v in violations if not _is_ruff_bypassed(v, ruff_bypass)]
    count = len(active)
    score = _score_from_count(count)

    checks: list[dict] = []

    if count == 0:
        checks.append({"name": "Ruff lint", "passed": True, "message": "No ruff violations found"})
    else:
        top = active[:5]
        codes = ", ".join(
            f"{v.get('code', '?')} {Path(v.get('filename', '?')).name}:{v.get('location', {}).get('row', '?')}"
            for v in top
        )
        suffix = f" (and {count - 5} more)" if count > 5 else ""
        message = f"{count} violation(s) — {codes}{suffix}"
        checks.append({"name": "Ruff lint", "passed": False, "message": message})

    # --- ruff format --check (advisory) ---
    fmt_files: list[str] = []
    try:
        fmt_proc = subprocess.run(
            ["ruff", "format", "--check", *(str(t) for t in scan_targets)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if fmt_proc.returncode != 0 and fmt_proc.stdout.strip():
            # Only the "Would reformat: <path>" lines are files. ruff also prints a
            # trailing summary ("2 files would be reformatted, 1 file already formatted");
            # counting it inflated fmt_count by one and put that sentence into the
            # message where a filename belongs (found while widening the corpus, FPLAN-0554).
            fmt_files = [
                line.split(_FORMAT_PREFIX, 1)[1].strip()
                for line in fmt_proc.stdout.splitlines()
                if line.startswith(_FORMAT_PREFIX)
            ]
    except subprocess.TimeoutExpired:
        logger.warning("ruff format --check timed out on branch %s", branch_path)
    except Exception as exc:
        logger.warning("ruff format --check failed on branch %s: %s", branch_path, exc)

    fmt_count = len(fmt_files)
    if fmt_count == 0:
        checks.append({"name": "Ruff format", "passed": True, "message": "All files formatted"})
    else:
        names = ", ".join(Path(f).name for f in fmt_files[:5])
        fmt_suffix = f" (and {fmt_count - 5} more)" if fmt_count > 5 else ""
        checks.append(
            {
                "name": "Ruff format",
                "passed": False,
                "message": f"{fmt_count} file(s) need formatting — {names}{fmt_suffix}",
            }
        )
        # Penalise score: subtract 2 points per unformatted file, floor at 25
        score = max(25, score - fmt_count * 2)

    json_handler.log_operation(
        "check_completed",
        {
            "branch": branch_path,
            "score": score,
            "standard": "ruff_check",
            "violations": count,
            "format_violations": fmt_count,
            "advisory": True,
        },
    )

    return {
        "passed": True,  # Advisory: never blocks the audit
        "checks": checks,
        "score": score,
        "standard": "RUFF_CHECK",
        "advisory": True,
    }
