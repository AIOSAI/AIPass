# =================== META ====================
# Name: test_diagnostics.py
# Description: Unit tests for handlers/diagnostics/
# Version: 1.2.1
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/diagnostics/diagnostics_check.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — subprocess's launch of the child process; the runner is stubbed or absent here
# seedgo: no-test-needed(standard) — each runner's own verdicts; apps/handlers/diagnostics/diagnostics_check.py is the seam

from aipass.seedgo.apps.handlers.diagnostics import diagnostics_check
from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
    check_branch,
    check_file,
    format_summary,
    should_ignore_file,
)


# ---------------------------------------------------------------------------
# Tests -- should_ignore_file
# ---------------------------------------------------------------------------


def test_should_ignore_file_removes_the_gitignored_driver_layer(tmp_path):
    """The branch-root driver layer and a bytecode cache are out of pyright's filter."""
    assert should_ignore_file(str(tmp_path / "apps" / "integrations" / "google" / "driver.py"), tmp_path) is True
    assert should_ignore_file(str(tmp_path / "apps" / "__pycache__" / "mod.py"), tmp_path) is True


def test_should_ignore_file_keeps_tracked_source_under_a_like_named_directory(tmp_path):
    """Mutant: the substring patterns back ("/integrations/", "/artifacts/", "/test/", ".old")."""
    for rel in ("handlers/integrations/call.py", "handlers/artifacts/trade_ops.py", "handlers/test/x.py", "a.old.py"):
        assert should_ignore_file(str(tmp_path / "apps" / rel), tmp_path) is False, rel


def test_should_ignore_file_leaves_a_file_outside_the_branch_alone(tmp_path):
    """A path the branch root does not contain is never read as ignored."""
    assert should_ignore_file(str(tmp_path.parent / "__pycache__" / "mod.py"), tmp_path / "branch") is False


# ---------------------------------------------------------------------------
# Tests -- check_file (non-existent / non-python)
# ---------------------------------------------------------------------------


def test_check_file_nonexistent(tmp_path):
    """check_file returns zero errors for a file that does not exist."""
    result = check_file(str(tmp_path / "missing" / "file.py"))
    assert result["errors"] == 0
    assert "error" in result  # should have an error message


def test_check_file_not_python(tmp_path):
    """check_file returns zero errors for a non-Python file."""
    txt_file = tmp_path / "file.txt"
    txt_file.write_text("hello", encoding="utf-8")
    result = check_file(str(txt_file))
    assert result["errors"] == 0
    assert "skipped" in result


# ---------------------------------------------------------------------------
# Tests -- check_branch (no apps dir)
# ---------------------------------------------------------------------------


def test_check_branch_no_apps_dir(tmp_path):
    """check_branch returns score=100 when no apps/ directory exists."""
    result = check_branch(str(tmp_path))
    assert result["passed"] is True
    assert result["score"] == 100
    assert result["standard"] == "DIAGNOSTICS"


def test_check_branch_returns_expected_keys(tmp_path):
    """check_branch returns all expected keys in the output dict."""
    result = check_branch(str(tmp_path))
    for key in ("passed", "score", "total_files", "total_errors", "checks", "standard"):
        assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Tests -- format_summary
# ---------------------------------------------------------------------------


def test_format_summary_with_error():
    """format_summary returns the error message when present."""
    result = format_summary(
        {"error": "Pyright timed out", "total_files": 0, "files_with_errors": 0, "total_errors": 0, "total_warnings": 0}
    )
    assert "Pyright timed out" in result


def test_format_summary_clean_run():
    """format_summary formats a clean run correctly."""
    result = format_summary(
        {
            "total_files": 10,
            "files_with_errors": 0,
            "total_errors": 0,
            "total_warnings": 2,
        }
    )
    assert "Files analyzed: 10" in result
    assert "Total errors: 0" in result
    assert "Total warnings: 2" in result
    assert "Files with errors: 0" in result


# ---------------------------------------------------------------------------
# Tests -- _get_enabled_runners_from_config
# ---------------------------------------------------------------------------


def _dispatched(tmp_path, monkeypatch, *configs):
    """The runners check_branch dispatches for these pack configs; no runner really runs."""
    (tmp_path / "apps").mkdir(exist_ok=True)
    monkeypatch.setattr(diagnostics_check, "_discover_pack_configs", lambda: [{"config": c} for c in configs])
    seen = []
    monkeypatch.setattr(diagnostics_check, "_run_runner", lambda name, *_a, **_k: seen.append(name))
    check_branch(str(tmp_path))
    return seen


def test_get_enabled_runners_simple(tmp_path, monkeypatch):
    """Mutant: a boolean runner entry ignored in apps/handlers/diagnostics/diagnostics_check.py — killed."""
    config = {"runners": {"typescript": False, "go": True}}
    assert _dispatched(tmp_path, monkeypatch, config) == ["go"]


def test_get_enabled_runners_detailed(tmp_path, monkeypatch):
    """Mutant: a detailed {"enabled": ...} runner entry ignored in apps/handlers/diagnostics/diagnostics_check.py — killed."""
    config = {"runners": {"go": {"enabled": True}, "rust": {"enabled": False}}}
    assert _dispatched(tmp_path, monkeypatch, config) == ["go"]


def test_get_enabled_runners_empty(tmp_path, monkeypatch):
    """No runner enabled anywhere: check_branch falls back to python alone."""
    assert _dispatched(tmp_path, monkeypatch, {}, {"runners": {}}) == ["python"]
