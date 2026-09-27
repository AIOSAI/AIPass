# =================== META ====================
# Name: test_checkers_batch5.py
# Description: Unit tests for ruff_check checker handler (batch 5)
# Version: 1.2.0
# Created: 2026-04-16
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_standards/ruff_check.py through check_branch."""

# ruff_check is the 33rd seedgo standard. Its per-file lane, check_module, has no
# test in this file.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — ruff's own lint and format verdicts; subprocess.run is sealed, its output built here
# seedgo: no-test-needed(stdlib) — shutil.which's PATH search; the tests only choose what PATH holds

import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

from aipass.seedgo.apps.handlers.aipass_standards.ruff_check import check_branch

_RUN = "aipass.seedgo.apps.handlers.aipass_standards.ruff_check.subprocess.run"


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


def _fmt_proc(unformatted_files: list[str] | None = None) -> MagicMock:
    """Build a fake subprocess.CompletedProcess for ruff format --check."""
    proc = MagicMock()
    if unformatted_files:
        proc.stdout = "\n".join(unformatted_files) + "\n"
        proc.returncode = 1
    else:
        proc.stdout = ""
        proc.returncode = 0
    proc.stderr = ""
    return proc


def _make_violation(filename: str, code: str = "F401", row: int = 1) -> dict:
    return {
        "filename": filename,
        "code": code,
        "location": {"row": row, "column": 1},
        "end_location": {"row": row, "column": 10},
        "message": f"Mock violation {code}",
    }


def _put_ruff_on_path(tmp_path: Path, monkeypatch) -> None:
    """PATH holds only a stand-in ruff; subprocess.run is sealed, so it never runs."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    # Windows finds ruff.exe through PATHEXT and ignores the bit; POSIX needs the bit.
    for name in ("ruff", "ruff.exe"):
        stub = bin_dir / name
        stub.write_text("", encoding="utf-8")
        if sys.platform != "win32":
            os.chmod(stub, 0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


def _branch_result(tmp_path: Path, monkeypatch, violations: list, ruff_bypass: list | None = None) -> dict:
    """check_branch on a fresh branch whose ruff reports these lint hits and no format hits."""
    branch = _make_branch(tmp_path)
    if ruff_bypass is not None:
        bypass_file = branch / ".seedgo" / "ruff_bypass.json"
        bypass_file.parent.mkdir(parents=True, exist_ok=True)
        bypass_file.write_text(json.dumps(ruff_bypass), encoding="utf-8")
    _put_ruff_on_path(tmp_path, monkeypatch)
    lint = _ruff_proc(violations, returncode=1 if violations else 0)
    with patch(_RUN, side_effect=[lint, _fmt_proc()]):
        return check_branch(str(branch))


def _hits(tmp_path: Path, count: int) -> list:
    return [_make_violation(str(tmp_path / "apps" / "modules" / "x.py"), "F401", i) for i in range(count)]


# =============================================
# 1. Score bands, through check_branch
# =============================================


class TestScoreFromCount:
    def test_zero_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Zero violations maps to score 100. Mutant: the clean score returns 99 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, [])["score"] == 100

    def test_one_violation(self, tmp_path: Path, monkeypatch) -> None:
        """One violation falls in the 1–5 band, score 95. Mutant: the band starts at 2 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 1))["score"] == 95

    def test_five_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Five violations is the upper bound of the 1–5 band, score 95. Mutant: count < 5 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 5))["score"] == 95

    def test_six_violations(self, tmp_path: Path, monkeypatch) -> None:
        """Six violations enters the 6–20 band, score 85. Mutant: the 95 band reaches 6 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 6))["score"] == 85

    def test_fifty_one_violations(self, tmp_path: Path, monkeypatch) -> None:
        """51 violations enters the 51–100 band, score 50. Mutant: the 70 band reaches 51 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 51))["score"] == 50

    def test_over_hundred(self, tmp_path: Path, monkeypatch) -> None:
        """101+ violations hits the floor band, score 25. Mutant: the 50 band reaches 101 in apps/handlers/aipass_standards/ruff_check.py — killed."""
        assert _branch_result(tmp_path, monkeypatch, _hits(tmp_path, 101))["score"] == 25


# =============================================
# 2. Ruff bypass (.seedgo/ruff_bypass.json)
# =============================================


class TestIsRuffBypassed:
    def test_no_bypass_rules(self, tmp_path: Path, monkeypatch) -> None:
        """Empty bypass list never matches any violation. Mutant: an empty list matches all in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=[])["score"] == 95

    def test_file_and_code_match(self, tmp_path: Path, monkeypatch) -> None:
        """Rule matching file and code bypasses the violation. Mutant: file must match whole in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "F401"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100

    def test_code_mismatch(self, tmp_path: Path, monkeypatch) -> None:
        """Rule with different code does not bypass the violation. Mutant: the code is ignored in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "E501"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 95

    def test_line_match(self, tmp_path: Path, monkeypatch) -> None:
        """Rule with matching line number bypasses the violation. Mutant: a line rule never matches in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 42)
        bypass = [{"file": "module.py", "code": "F401", "line": 42}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100

    def test_line_mismatch(self, tmp_path: Path, monkeypatch) -> None:
        """Rule targeting a different line does not bypass the violation. Mutant: the line is ignored in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "F401", 10)
        bypass = [{"file": "module.py", "code": "F401", "line": 99}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 95

    def test_file_only_matches_any_code(self, tmp_path: Path, monkeypatch) -> None:
        """File-only rule bypasses all codes in that file. Mutant: a missing code matches none in apps/handlers/aipass_standards/ruff_check.py — killed."""
        v = _make_violation(str(tmp_path / "apps" / "module.py"), "E501", 1)
        bypass = [{"file": "module.py"}]
        assert _branch_result(tmp_path, monkeypatch, [v], ruff_bypass=bypass)["score"] == 100


# =============================================
# 3. check_branch
# =============================================


@patch("aipass.seedgo.apps.handlers.aipass_standards.ruff_check.json_handler")
class TestCheckBranch:
    def test_clean_branch_scores_100(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Branch with zero ruff violations scores 100."""
        branch = _make_branch(tmp_path)
        clean_proc = _ruff_proc([], returncode=0)
        fmt_clean = _fmt_proc()
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[clean_proc, fmt_clean]):
            result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result["standard"] == "RUFF_CHECK"
        assert "advisory" not in result

    def test_violations_caught_and_scored(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Branch with violations reports count and drops score."""
        branch = _make_branch(tmp_path)
        violations = [_make_violation(str(branch / "apps" / "modules" / "x.py"), "F401", i) for i in range(10)]
        proc = _ruff_proc(violations, returncode=1)
        fmt_clean = _fmt_proc()
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[proc, fmt_clean]):
            result = check_branch(str(branch))
        assert result["score"] == 85  # 10 violations → 6–20 band
        assert result["passed"] is False  # the row gates since 2026-09-25
        assert "10 violation" in result["checks"][0]["message"]

    def test_an_unformatted_file_alone_fails_the_row(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """The row covers format too: one unformatted file, zero lint hits, still gates."""
        branch = _make_branch(tmp_path)
        fmt_dirty = _fmt_proc([f"Would reformat: {branch / 'apps' / 'x.py'}"])
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[_ruff_proc([], returncode=0), fmt_dirty]):
            result = check_branch(str(branch))
        assert result["score"] == 98
        assert result["passed"] is False
        assert "1 file(s) need formatting — x.py" in result["checks"][1]["message"]

    def test_standard_bypass_respected(self, mock_json, tmp_path: Path) -> None:
        """Standard-level bypass via bypass_rules returns score 100."""
        branch = _make_branch(tmp_path)
        bypass = [{"standard": "ruff_check"}]
        result = check_branch(str(branch), bypass_rules=bypass)
        assert result["score"] == 100
        assert result["passed"] is True

    def test_ruff_not_installed_skips(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Missing ruff binary returns score 100 with skipped status."""
        branch = _make_branch(tmp_path)
        (tmp_path / "empty").mkdir()
        monkeypatch.setenv("PATH", str(tmp_path / "empty"))
        result = check_branch(str(branch))
        assert result["score"] == 100
        assert result["passed"] is True
        assert result.get("status") == "skipped"
        assert "not installed" in result["checks"][0]["message"]

    def test_ruff_bypass_json_filters_violations(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Violations listed in .seedgo/ruff_bypass.json are filtered out."""
        branch = _make_branch(tmp_path)
        v_path = str(branch / "apps" / "modules" / "thing.py")
        violations = [
            _make_violation(v_path, "F401", 1),
            _make_violation(v_path, "E501", 10),
        ]
        proc = _ruff_proc(violations, returncode=1)
        fmt_clean = _fmt_proc()
        # Bypass the F401
        bypass_file = branch / ".seedgo" / "ruff_bypass.json"
        bypass_file.parent.mkdir(parents=True, exist_ok=True)
        bypass_file.write_text(json.dumps([{"file": "thing.py", "code": "F401"}]), encoding="utf-8")
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=[proc, fmt_clean]):
            result = check_branch(str(branch))
        # Only 1 active violation (E501), score should be 95
        assert result["score"] == 95
        assert "1 violation" in result["checks"][0]["message"]

    def test_timeout_returns_score_zero(self, mock_json, tmp_path: Path, monkeypatch) -> None:
        """Subprocess timeout returns score 0 and passed False."""
        import subprocess as sp

        branch = _make_branch(tmp_path)
        _put_ruff_on_path(tmp_path, monkeypatch)
        with patch(_RUN, side_effect=sp.TimeoutExpired(cmd="ruff", timeout=60)):
            result = check_branch(str(branch))
        assert result["score"] == 0
        assert result["passed"] is False
        assert "timed out" in result["checks"][0]["message"]
