"""Tests for ruff_check.check_branch — the 33rd seedgo standard."""

# =================== META ====================
# Name: test_checkers_batch5.py
# Description: Unit tests for ruff_check checker handler (batch 5)
# Version: 1.0.0
# Created: 2026-04-16
# Modified: 2026-04-16
# =============================================

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.seedgo.apps.handlers.aipass_standards.ruff_check import (
    check_branch,
    _score_from_count,
    _is_ruff_bypassed,
)


# =============================================
# HELPERS
# =============================================


def _write_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _make_branch(tmp_path: Path) -> Path:
    apps = tmp_path / "apps"
    (apps / "modules").mkdir(parents=True)
    (apps / "handlers").mkdir(parents=True)
    return tmp_path


def _ruff_proc(violations: list, returncode: int = 1) -> MagicMock:
    """Build a fake subprocess.CompletedProcess with JSON output."""
    proc = MagicMock()
    proc.stdout = json.dumps(violations)
    proc.stderr = ""
    proc.returncode = returncode
    return proc


def _make_violation(filename: str, code: str = "F401", row: int = 1) -> dict:
    return {
        "filename": filename,
        "code": code,
        "location": {"row": row, "column": 1},
        "end_location": {"row": row, "column": 10},
        "message": f"Mock violation {code}",
    }


# =============================================
# 1. Score helper
# =============================================


class TestScoreFromCount:
    def test_zero_violations(self) -> None:
        """Zero violations maps to score 100."""
        assert _score_from_count(0) == 100

    def test_one_violation(self) -> None:
        """One violation falls in the 1–5 band, score 95."""
        assert _score_from_count(1) == 95

    def test_five_violations(self) -> None:
        """Five violations is the upper bound of the 1–5 band, score 95."""
        assert _score_from_count(5) == 95

    def test_six_violations(self) -> None:
        """Six violations enters the 6–20 band, score 85."""
        assert _score_from_count(6) == 85

    def test_fifty_one_violations(self) -> None:
        """51 violations enters the 51–100 band, score 50."""
        assert _score_from_count(51) == 50

    def test_over_hundred(self) -> None:
        """101+ violations hits the floor band, score 25."""
        assert _score_from_count(101) == 25


# =============================================
# 2. Ruff bypass helper
# =============================================


class TestIsRuffBypassed:
    def test_no_bypass_rules(self) -> None:
        """Empty bypass list never matches any violation."""
        v = _make_violation("/apps/module.py", "F401", 10)
        assert not _is_ruff_bypassed(v, [])

    def test_file_and_code_match(self) -> None:
        """Rule matching file and code bypasses the violation."""
        v = _make_violation("/apps/module.py", "F401", 10)
        bypass = [{"file": "module.py", "code": "F401"}]
        assert _is_ruff_bypassed(v, bypass)

    def test_code_mismatch(self) -> None:
        """Rule with different code does not bypass the violation."""
        v = _make_violation("/apps/module.py", "F401", 10)
        bypass = [{"file": "module.py", "code": "E501"}]
        assert not _is_ruff_bypassed(v, bypass)

    def test_line_match(self) -> None:
        """Rule with matching line number bypasses the violation."""
        v = _make_violation("/apps/module.py", "F401", 42)
        bypass = [{"file": "module.py", "code": "F401", "line": 42}]
        assert _is_ruff_bypassed(v, bypass)

    def test_line_mismatch(self) -> None:
        """Rule targeting a different line does not bypass the violation."""
        v = _make_violation("/apps/module.py", "F401", 10)
        bypass = [{"file": "module.py", "code": "F401", "line": 99}]
        assert not _is_ruff_bypassed(v, bypass)

    def test_file_only_matches_any_code(self) -> None:
        """File-only rule bypasses all violations in that file regardless of code."""
        v = _make_violation("/apps/module.py", "E501", 1)
        bypass = [{"file": "module.py"}]
        assert _is_ruff_bypassed(v, bypass)


# =============================================
# 3. check_branch
# =============================================


@patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.json_handler")
class TestCheckBranch:
    def test_clean_branch_scores_100(self, mock_json, tmp_path: Path) -> None:
        """Branch with zero ruff violations scores 100."""
        branch = _make_branch(tmp_path)
        clean_proc = _ruff_proc([], returncode=0)
        with patch(
            "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.shutil.which", return_value="/usr/bin/ruff"
        ):
            with patch(
                "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run", return_value=clean_proc
            ):
                result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result["standard"] == "RUFF_CHECK"
        assert result["advisory"] is True

    def test_violations_caught_and_scored(self, mock_json, tmp_path: Path) -> None:
        """Branch with violations reports count and drops score."""
        branch = _make_branch(tmp_path)
        violations = [_make_violation(str(branch / "apps" / "modules" / "x.py"), "F401", i) for i in range(10)]
        proc = _ruff_proc(violations, returncode=1)
        with patch(
            "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.shutil.which", return_value="/usr/bin/ruff"
        ):
            with patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run", return_value=proc):
                result = check_branch(str(branch))
        assert result["score"] == 85  # 10 violations → 6–20 band
        assert result["passed"] is True  # advisory: always True
        assert "10 violation" in result["checks"][0]["message"]

    def test_standard_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Standard-level bypass via bypass_rules returns score 100."""
        branch = _make_branch(tmp_path)
        bypass = [{"standard": "ruff_check"}]
        result = check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True

    def test_ruff_not_installed_skips(self, mock_json, tmp_path: Path) -> None:
        """Missing ruff binary returns score 100 with skipped status."""
        branch = _make_branch(tmp_path)
        with patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.shutil.which", return_value=None):
            result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result.get("status") == "skipped"
        assert "not installed" in result["checks"][0]["message"]

    def test_ruff_bypass_json_filters_violations(self, mock_json, tmp_path: Path) -> None:
        """Violations listed in .seedgo/ruff_bypass.json are filtered out."""
        branch = _make_branch(tmp_path)
        v_path = str(branch / "apps" / "modules" / "thing.py")
        violations = [
            _make_violation(v_path, "F401", 1),
            _make_violation(v_path, "E501", 10),
        ]
        proc = _ruff_proc(violations, returncode=1)
        # Bypass the F401
        bypass_file = branch / ".seedgo" / "ruff_bypass.json"
        bypass_file.parent.mkdir(parents=True, exist_ok=True)
        bypass_file.write_text(json.dumps([{"file": "thing.py", "code": "F401"}]))
        with patch(
            "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.shutil.which", return_value="/usr/bin/ruff"
        ):
            with patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run", return_value=proc):
                result = check_branch(str(branch))
        # Only 1 active violation (E501), score should be 95
        assert result["score"] == 95
        assert "1 violation" in result["checks"][0]["message"]

    def test_timeout_returns_score_zero(self, mock_json, tmp_path: Path) -> None:
        """Subprocess timeout returns score 0 and passed False."""
        import subprocess as sp

        branch = _make_branch(tmp_path)
        with patch(
            "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.shutil.which", return_value="/usr/bin/ruff"
        ):
            with patch(
                "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run",
                side_effect=sp.TimeoutExpired(cmd="ruff", timeout=60),
            ):
                result = check_branch(str(branch))
        assert result["score"] == 0
        assert result["passed"] is False
        assert "timed out" in result["checks"][0]["message"]
