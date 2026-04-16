"""Tests for the aipass_standards handler directory."""

# =================== META ====================
# Name: test_aipass_standards.py
# Description: Unit tests for handlers/aipass_standards/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
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

    # Force re-imports of specific checker modules we test
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.naming_check",
        "aipass.seedgo.apps.handlers.aipass_standards.json_structure_check",
        "aipass.seedgo.apps.handlers.aipass_standards.meta_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- naming_check.check_module
# ---------------------------------------------------------------------------


def test_naming_check_module_returns_dict(tmp_path):
    """naming_check.check_module returns a dict with expected keys."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample module."""\n\ndef my_function():\n    pass\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    result = check_module(str(py_file))
    assert isinstance(result, dict)
    assert "passed" in result
    assert "checks" in result
    assert "score" in result
    assert isinstance(result["passed"], bool)
    assert isinstance(result["checks"], list)
    assert isinstance(result["score"], (int, float))


def test_naming_check_module_missing_file():
    """naming_check.check_module handles missing file gracefully."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    result = check_module("/nonexistent/path/file.py")
    assert isinstance(result, dict)
    assert "passed" in result


def test_naming_check_module_with_bypass(tmp_path):
    """naming_check.check_module respects bypass rules."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    bypass = [{"file": "sample.py", "standard": "naming", "reason": "test"}]
    result = check_module(str(py_file), bypass_rules=bypass)
    assert isinstance(result, dict)
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Tests -- json_structure_check.check_module
# ---------------------------------------------------------------------------


def test_json_structure_check_returns_expected_keys(tmp_path):
    """json_structure_check.check_module returns dict with standard keys."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample."""\nimport json\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module(str(py_file))
    assert isinstance(result, dict)
    assert "passed" in result
    assert "score" in result
    assert "checks" in result


def test_json_structure_check_missing_file():
    """json_structure_check.check_module handles missing file."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module("/nonexistent/module.py")
    assert isinstance(result, dict)
    assert "passed" in result


def test_json_structure_check_has_standard_field(tmp_path):
    """json_structure_check.check_module includes 'standard' in output."""
    py_file = tmp_path / "test_mod.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module(str(py_file))
    assert "standard" in result


# ---------------------------------------------------------------------------
# Tests -- naming_check.is_bypassed
# ---------------------------------------------------------------------------


def test_naming_is_bypassed_true():
    """is_bypassed returns True when rule matches."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    rules = [{"file": "foo.py", "standard": "naming", "reason": "legacy"}]
    assert is_bypassed("some/path/foo.py", "naming", bypass_rules=rules) is True


def test_naming_is_bypassed_false_no_rules():
    """is_bypassed returns False with no rules."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    assert is_bypassed("foo.py", "naming", bypass_rules=None) is False


def test_naming_is_bypassed_wrong_standard():
    """is_bypassed returns False when standard does not match."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    rules = [{"file": "foo.py", "standard": "imports", "reason": "legacy"}]
    assert is_bypassed("foo.py", "naming", bypass_rules=rules) is False
