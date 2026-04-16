"""Tests for the aipass_proof handler directory (interface, triplet, etc.)."""

# =================== META ====================
# Name: test_aipass_proof.py
# Description: Unit tests for handlers/aipass_proof/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for proof handlers."""
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

    # Force re-imports
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_proof.interface",
        "aipass.seedgo.apps.handlers.aipass_proof.triplet",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- interface.scan
# ---------------------------------------------------------------------------


def test_interface_scan_missing_directory():
    """interface.scan returns passed=False for non-existent directory."""
    from aipass.seedgo.apps.handlers.aipass_proof.interface import scan

    result = scan(Path("/nonexistent/directory"))
    assert result["passed"] is False
    assert result["total"] == 0
    assert len(result["issues"]) > 0


def test_interface_scan_empty_directory(tmp_path):
    """interface.scan on an empty directory finds no checkers."""
    from aipass.seedgo.apps.handlers.aipass_proof.interface import scan

    result = scan(tmp_path)
    assert result["total"] == 0
    assert result["passed"] is False  # 0 checkers => not passed
    assert result["issues"] == []


def test_interface_scan_compliant_checker(tmp_path):
    """interface.scan detects a fully compliant checker."""
    check_file = tmp_path / "example_check.py"
    check_file.write_text(
        'AUDIT_SCOPE = "all_files"\n\ndef check_module(module_path, bypass_rules=None):\n    return {"passed": True}\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_proof.interface import scan

    result = scan(tmp_path)
    assert result["passed"] is True
    assert result["total"] == 1
    assert result["pass_count"] == 1
    assert result["fail_count"] == 0


def test_interface_scan_missing_scope(tmp_path):
    """interface.scan flags checker without AUDIT_SCOPE."""
    check_file = tmp_path / "bad_check.py"
    check_file.write_text(
        'def check_module(module_path, bypass_rules=None):\n    return {"passed": True}\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_proof.interface import scan

    result = scan(tmp_path)
    assert result["fail_count"] >= 1
    assert any("AUDIT_SCOPE" in issue for issue in result["issues"])


def test_interface_scan_branch_level_checker(tmp_path):
    """interface.scan validates branch_level checkers expect check_branch."""
    check_file = tmp_path / "branch_check.py"
    check_file.write_text(
        'AUDIT_SCOPE = "branch_level"\n\n'
        "def check_branch(branch_path, bypass_rules=None):\n"
        '    return {"passed": True}\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_proof.interface import scan

    result = scan(tmp_path)
    assert result["passed"] is True
    assert result["pass_count"] == 1


# ---------------------------------------------------------------------------
# Tests -- interface AST helpers
# ---------------------------------------------------------------------------


def test_extract_audit_scope_from_source():
    """_extract_audit_scope extracts AUDIT_SCOPE value from AST."""
    import ast
    from aipass.seedgo.apps.handlers.aipass_proof.interface import _extract_audit_scope

    source = 'AUDIT_SCOPE = "entry_point"\nx = 1\n'
    tree = ast.parse(source)
    assert _extract_audit_scope(tree) == "entry_point"


def test_extract_audit_scope_none_when_missing():
    """_extract_audit_scope returns None when AUDIT_SCOPE not defined."""
    import ast
    from aipass.seedgo.apps.handlers.aipass_proof.interface import _extract_audit_scope

    source = "x = 1\ny = 2\n"
    tree = ast.parse(source)
    assert _extract_audit_scope(tree) is None


# ---------------------------------------------------------------------------
# Tests -- triplet.scan
# ---------------------------------------------------------------------------


def test_triplet_scan_complete_triplet(tmp_path):
    """triplet.scan identifies a complete triplet (check + content + md)."""
    (tmp_path / "naming_check.py").write_text("# check", encoding="utf-8")
    (tmp_path / "naming_content.py").write_text("# content", encoding="utf-8")
    (tmp_path / "naming.md").write_text("# doc", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_proof.triplet import scan

    result = scan(tmp_path)
    assert "naming" in result["complete"]
    assert result["total"] >= 1


def test_triplet_scan_check_only(tmp_path):
    """triplet.scan flags a check-only standard (missing content + md)."""
    (tmp_path / "orphan_check.py").write_text("# check only", encoding="utf-8")

    from aipass.seedgo.apps.handlers.aipass_proof.triplet import scan

    result = scan(tmp_path)
    assert "orphan" in result["check_only"]
    assert result["passed"] is False


def test_triplet_scan_empty_directory(tmp_path):
    """triplet.scan on empty directory returns passed=True, total=0."""
    from aipass.seedgo.apps.handlers.aipass_proof.triplet import scan

    result = scan(tmp_path)
    assert result["total"] == 0
    assert result["passed"] is True
