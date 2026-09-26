"""Tests for the diagnostics handler directory (diagnostics_check)."""

# =================== META ====================
# Name: test_diagnostics.py
# Description: Unit tests for handlers/diagnostics/
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-25
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for diagnostics handlers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- bypass ignore handler: the REAL list, re-imported over the mocks above, so the
    # filter tests below pin the anchors the audit uses, not a stand-in.
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", raising=False)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check", raising=False)


# ---------------------------------------------------------------------------
# Tests -- should_ignore_file
# ---------------------------------------------------------------------------


def test_should_ignore_file_removes_the_gitignored_driver_layer(tmp_path):
    """The branch-root driver layer and a bytecode cache are out of pyright's filter."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import should_ignore_file

    assert should_ignore_file(str(tmp_path / "apps" / "integrations" / "google" / "driver.py"), tmp_path) is True
    assert should_ignore_file(str(tmp_path / "apps" / "__pycache__" / "mod.py"), tmp_path) is True


def test_should_ignore_file_keeps_tracked_source_under_a_like_named_directory(tmp_path):
    """Mutant: the substring patterns back ("/integrations/", "/artifacts/", "/test/", ".old")."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import should_ignore_file

    for rel in ("handlers/integrations/call.py", "handlers/artifacts/trade_ops.py", "handlers/test/x.py", "a.old.py"):
        assert should_ignore_file(str(tmp_path / "apps" / rel), tmp_path) is False, rel


def test_should_ignore_file_leaves_a_file_outside_the_branch_alone(tmp_path):
    """A path the branch root does not contain is never read as ignored."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import should_ignore_file

    assert should_ignore_file(str(tmp_path.parent / "__pycache__" / "mod.py"), tmp_path / "branch") is False


# ---------------------------------------------------------------------------
# Tests -- check_file (non-existent / non-python)
# ---------------------------------------------------------------------------


def test_check_file_nonexistent():
    """check_file returns zero errors for a file that does not exist."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import check_file

    result = check_file("/nonexistent/file.py")
    assert result["errors"] == 0
    assert "error" in result  # should have an error message


def test_check_file_not_python(tmp_path):
    """check_file returns zero errors for a non-Python file."""
    txt_file = tmp_path / "file.txt"
    txt_file.write_text("hello", encoding="utf-8")
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import check_file

    result = check_file(str(txt_file))
    assert result["errors"] == 0
    assert "skipped" in result


# ---------------------------------------------------------------------------
# Tests -- check_branch (no apps dir)
# ---------------------------------------------------------------------------


def test_check_branch_no_apps_dir(tmp_path):
    """check_branch returns score=100 when no apps/ directory exists."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import check_branch

    result = check_branch(str(tmp_path))
    assert result["passed"] is True
    assert result["score"] == 100
    assert result["standard"] == "DIAGNOSTICS"


def test_check_branch_returns_expected_keys(tmp_path):
    """check_branch returns all expected keys in the output dict."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import check_branch

    result = check_branch(str(tmp_path))
    for key in ("passed", "score", "total_files", "total_errors", "checks", "standard"):
        assert key in result, f"Missing key: {key}"


# ---------------------------------------------------------------------------
# Tests -- format_summary
# ---------------------------------------------------------------------------


def test_format_summary_with_error():
    """format_summary returns the error message when present."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import format_summary

    result = format_summary(
        {"error": "Pyright timed out", "total_files": 0, "files_with_errors": 0, "total_errors": 0, "total_warnings": 0}
    )
    assert "Pyright timed out" in result


def test_format_summary_clean_run():
    """format_summary formats a clean run correctly."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import format_summary

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


def test_get_enabled_runners_simple():
    """_get_enabled_runners_from_config handles boolean format."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import _get_enabled_runners_from_config

    config = {"runners": {"python": True, "typescript": False}}
    result = _get_enabled_runners_from_config(config)
    assert "python" in result
    assert "typescript" not in result


def test_get_enabled_runners_detailed():
    """_get_enabled_runners_from_config handles detailed format."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import _get_enabled_runners_from_config

    config = {"runners": {"python": {"enabled": True}, "rust": {"enabled": False}}}
    result = _get_enabled_runners_from_config(config)
    assert "python" in result
    assert "rust" not in result


def test_get_enabled_runners_empty():
    """_get_enabled_runners_from_config returns empty for no runners."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import _get_enabled_runners_from_config

    assert _get_enabled_runners_from_config({}) == []
    assert _get_enabled_runners_from_config({"runners": {}}) == []
