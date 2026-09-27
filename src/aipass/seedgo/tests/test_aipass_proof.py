# =================== META ====================
# Name: test_aipass_proof.py
# Description: Unit tests for handlers/aipass_proof/
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/aipass_proof/interface.py and apps/handlers/aipass_proof/triplet.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/aipass_proof/ parses and imports
# seedgo: no-test-needed(documentation) — that the public scan functions carry docstrings
# seedgo: no-test-needed(stdlib) — ast.parse's ability to read a checker's source

from aipass.seedgo.apps.handlers.aipass_proof.interface import scan as interface_scan
from aipass.seedgo.apps.handlers.aipass_proof.triplet import scan as triplet_scan


# ---------------------------------------------------------------------------
# Tests -- interface.scan
# ---------------------------------------------------------------------------


def test_interface_scan_missing_directory(tmp_path):
    """interface.scan returns passed=False for non-existent directory."""
    result = interface_scan(tmp_path / "missing")
    assert result["passed"] is False
    assert result["total"] == 0
    assert len(result["issues"]) > 0


def test_interface_scan_empty_directory(tmp_path):
    """interface.scan on an empty directory finds no checkers."""
    result = interface_scan(tmp_path)
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
    result = interface_scan(tmp_path)
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
    result = interface_scan(tmp_path)
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
    result = interface_scan(tmp_path)
    assert result["passed"] is True
    assert result["pass_count"] == 1


# ---------------------------------------------------------------------------
# Tests -- interface AST helpers
# ---------------------------------------------------------------------------


def test_extract_audit_scope_from_source(tmp_path):
    """Mutant: AUDIT_SCOPE's value never read (return None) in apps/handlers/aipass_proof/interface.py — killed."""
    (tmp_path / "example_check.py").write_text(
        'AUDIT_SCOPE = "entry_point"\nx = 1\n\ndef check_module(module_path, bypass_rules=None):\n    return {}\n',
        encoding="utf-8",
    )
    result = interface_scan(tmp_path)
    assert result["results"][0]["audit_scope"] == "entry_point"


def test_extract_audit_scope_none_when_missing(tmp_path):
    """Mutant: a missing AUDIT_SCOPE read as "all_files" in apps/handlers/aipass_proof/interface.py — killed."""
    (tmp_path / "example_check.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    result = interface_scan(tmp_path)
    assert result["results"][0]["audit_scope"] is None


# ---------------------------------------------------------------------------
# Tests -- triplet.scan
# ---------------------------------------------------------------------------


def test_triplet_scan_complete_triplet(tmp_path):
    """triplet.scan identifies a complete triplet (check + content + md)."""
    (tmp_path / "naming_check.py").write_text("# check", encoding="utf-8")
    (tmp_path / "naming_content.py").write_text("# content", encoding="utf-8")
    (tmp_path / "naming.md").write_text("# doc", encoding="utf-8")

    result = triplet_scan(tmp_path)
    assert "naming" in result["complete"]
    assert result["total"] >= 1


def test_triplet_scan_check_only(tmp_path):
    """triplet.scan flags a check-only standard (missing content + md)."""
    (tmp_path / "orphan_check.py").write_text("# check only", encoding="utf-8")

    result = triplet_scan(tmp_path)
    assert "orphan" in result["check_only"]
    assert result["passed"] is False


def test_triplet_scan_empty_directory(tmp_path):
    """triplet.scan on empty directory returns passed=True, total=0."""
    result = triplet_scan(tmp_path)
    assert result["total"] == 0
    assert result["passed"] is True
