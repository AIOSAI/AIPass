# =================== AIPass ====================
# Name: ruff_check.py
# Description: Ruff Linter Standards Checker Handler
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

"""
Ruff Linter Standards Checker Handler

Runs ruff against a branch's apps/ directory and scores based on violation
count. Prevents ruff debt from silently re-accumulating after a cleanup.

AUDIT_SCOPE: branch_level — runs once per branch, ruff walks the tree.
ADVISORY: surfaces violations and score but always passes overall.
          Promote to required once all branches are clean.
"""

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

AUDIT_SCOPE = "branch_level"
ADVISORY = True


def is_bypassed(file_path: str, standard: str, bypass_rules: list | None = None) -> bool:
    """Check if a violation should be bypassed via standard bypass.json rules."""
    if not bypass_rules:
        return False
    for rule in bypass_rules:
        if rule.get("standard") and rule.get("standard") != standard:
            continue
        rule_file = rule.get("file", "")
        if rule_file and rule_file not in file_path:
            continue
        return True
    return False


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
            "checks": [{"name": "Ruff check", "passed": True,
                        "message": "Standard bypassed via .seedgo/bypass.json"}],
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
            "checks": [{"name": "Ruff check", "passed": True,
                        "message": "ruff not installed — check skipped"}],
            "score": 100,
            "status": "skipped",
            "standard": "RUFF_CHECK",
            "advisory": True,
        }

    # Scan apps/ if present, otherwise full branch
    scan_target = bp / "apps" if (bp / "apps").is_dir() else bp

    # Load ruff-specific bypass rules
    ruff_bypass = _load_ruff_bypass(bp)

    # Run ruff
    try:
        proc = subprocess.run(
            ["ruff", "check", str(scan_target), "--output-format=json"],
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
            "checks": [{"name": "Ruff check", "passed": False,
                        "message": "ruff check timed out after 60s"}],
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
                "checks": [{"name": "Ruff check", "passed": False,
                            "message": f"ruff JSON parse failed: {stderr_snippet}"}],
                "score": 0,
                "standard": "RUFF_CHECK",
                "advisory": True,
            }

    # Filter bypassed violations
    active = [v for v in violations if not _is_ruff_bypassed(v, ruff_bypass)]
    count = len(active)
    score = _score_from_count(count)

    if count == 0:
        message = "No ruff violations found"
        check_passed = True
    else:
        top = active[:5]
        codes = ", ".join(f"{v.get('code', '?')} {Path(v.get('filename', '?')).name}:{v.get('location', {}).get('row', '?')}" for v in top)
        suffix = f" (and {count - 5} more)" if count > 5 else ""
        message = f"{count} violation(s) — {codes}{suffix}"
        check_passed = False

    json_handler.log_operation(
        "check_completed",
        {"branch": branch_path, "score": score, "standard": "ruff_check",
         "violations": count, "advisory": True},
    )

    return {
        "passed": True,  # Advisory: never blocks the audit
        "checks": [{"name": "Ruff check", "passed": check_passed, "message": message}],
        "score": score,
        "standard": "RUFF_CHECK",
        "advisory": True,
    }
