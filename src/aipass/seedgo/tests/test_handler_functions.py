# =================== META ====================
# Name: test_handler_functions.py
# Description: Unit tests for handler-level functions across multiple handler packages
# Version: 1.1.1
# Created: 2026-04-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/ functions: audit/audit_display.py, diagnostics_check.py, readme/readme_ops.py."""


# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered) — audit_display.print_system_summary, in tests/test_coverage_audit.py
# seedgo: no-test-needed(introspection) — audit_display.print_introspection, a static help blurb

import json
from typing import Dict
from unittest.mock import MagicMock, patch

import pytest

from aipass.seedgo.apps.handlers.audit import audit_display
from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import check_directory
from aipass.seedgo.apps.handlers.readme import readme_generator, readme_ops


# The console is the real one: audit_display prints through aipass.cli's console, which
# writes to sys.stdout at print time, so capsys reads what the user reads.


def test_print_branch_summary_basic(capsys: pytest.CaptureFixture[str]) -> None:
    """print_branch_summary renders the branch line, the score grid and the overall."""
    audit_result: Dict = {
        "branch": {"name": "seedgo"},
        "scores": {"meta": 100, "naming": 90},
        "average": 95,
        "files_checked": 10,
        "results": {},
    }
    audit_display.print_branch_summary(audit_result)

    lines = capsys.readouterr().out.splitlines()
    assert "seedgo (10 files measured — apps/ plus tests/ test_*.py and conftest.py)" in lines
    assert "  Meta            100% ✅    Naming           90% ✅" in lines
    assert "  Overall:          95% ✅" in lines


def test_print_branch_summary_with_violations(capsys: pytest.CaptureFixture[str]) -> None:
    """print_branch_summary renders the violation block: count, file, score, issue."""
    audit_result: Dict = {
        "branch": {"name": "testbranch"},
        "scores": {"meta": 60, "naming": 80},
        "average": 70,
        "files_checked": 5,
        "results": {
            "meta": {"checks": [{"name": "META block present", "passed": False, "message": "Missing META block"}]}
        },
        "meta_violations": [{"path": "file.py", "score": 50, "issues": ["Missing META block"]}],
    }
    audit_display.print_branch_summary(audit_result)

    lines = capsys.readouterr().out.splitlines()
    assert "testbranch (5 files measured — apps/ plus tests/ test_*.py and conftest.py)" in lines
    assert "  META VIOLATIONS (1 files):" in lines
    assert "    ✗ file.py (score: 50%)" in lines
    assert "      • Missing META block" in lines


def test_print_branch_summary_single_standard_at_full_marks(capsys: pytest.CaptureFixture[str]) -> None:
    """One standard at 100 renders its row and an Overall of 100."""
    audit_result: Dict = {
        "branch": {"name": "seedgo"},
        "scores": {"meta": 100},
        "average": 100,
        "files_checked": 1,
        "results": {},
    }
    audit_display.print_branch_summary(audit_result)

    lines = capsys.readouterr().out.splitlines()
    assert "  Meta            100% ✅" in lines
    assert "  Overall:         100% ✅" in lines
    assert not [line for line in lines if "90" in line]


def test_check_directory_missing(tmp_path):
    """check_directory on nonexistent directory returns error."""
    result = check_directory(str(tmp_path / "nonexistent"))
    assert result["total_files"] == 0
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_check_directory_exists(tmp_path):
    """check_directory on existing directory calls pyright."""
    py_file = tmp_path / "example.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "generalDiagnostics": [],
                    "summary": {"filesAnalyzed": 1},
                }
            ),
            stderr="",
        )
        result = check_directory(str(tmp_path))

    assert result["total_errors"] == 0
    assert result["total_files"] == 1


def test_check_directory_with_errors(tmp_path):
    """check_directory reports errors from pyright output."""
    py_file = tmp_path / "bad.py"
    py_file.write_text("x: int = 'not_int'\n", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=json.dumps(
                {
                    "generalDiagnostics": [
                        {
                            "file": str(py_file),
                            "severity": "error",
                            "range": {"start": {"line": 0}},
                            "message": "Type mismatch",
                            "rule": "reportAssignment",
                        }
                    ],
                    "summary": {"filesAnalyzed": 1},
                }
            ),
            stderr="",
        )
        result = check_directory(str(tmp_path))

    assert result["total_errors"] == 1
    assert result["files_with_errors"] == 1


def test_resolve_branch_found(tmp_path, monkeypatch):
    """resolve_branch finds a branch in the registry."""
    registry_data = {
        "branches": [
            {"name": "seedgo", "path": "/src/aipass/seedgo"},
            {"name": "drone", "path": "/src/aipass/drone"},
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@seedgo")
    assert result is not None
    assert result["name"] == "seedgo"


def test_resolve_branch_not_found(tmp_path, monkeypatch):
    """resolve_branch returns None for unknown branch."""
    registry_data = {"branches": [{"name": "seedgo"}]}
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@nonexistent")
    assert result is None


def test_resolve_branch_no_registry(tmp_path, monkeypatch):
    """resolve_branch returns None when registry does not exist."""
    monkeypatch.setattr(readme_ops, "_find_registry", lambda: tmp_path / "MISSING.json")

    result = readme_ops.resolve_branch("@seedgo")
    assert result is None


def test_resolve_branch_alias(tmp_path, monkeypatch):
    """resolve_branch resolves aliases."""
    registry_data = {
        "branches": [
            {"name": "seedgo", "aliases": ["@sg", "@standards"]},
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@sg")
    assert result is not None
    assert result["name"] == "seedgo"


def test_get_all_branches(tmp_path, monkeypatch):
    """get_all_branches returns all branches from registry."""
    registry_data = {
        "branches": [
            {"name": "seedgo"},
            {"name": "drone"},
            {"name": "spawn"},
        ]
    }
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    branches = readme_ops.get_all_branches()
    assert len(branches) == 3


def test_get_all_branches_empty_registry(tmp_path, monkeypatch):
    """get_all_branches returns empty list when registry has no branches."""
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps({"branches": []}), encoding="utf-8")

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    branches = readme_ops.get_all_branches()
    assert branches == []


def test_get_all_branches_no_registry(tmp_path, monkeypatch):
    """get_all_branches returns empty list when registry is missing."""
    monkeypatch.setattr(readme_ops, "_find_registry", lambda: tmp_path / "MISSING.json")

    branches = readme_ops.get_all_branches()
    assert branches == []


def test_generate_commands_section_no_entry_point(tmp_path):
    """generate_commands_section returns empty when no entry point exists."""
    branch_dir = tmp_path / "mybranch"
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir(parents=True)

    result = readme_generator.generate_commands_section(str(branch_dir))
    assert result == ""


def test_generate_commands_section_with_help(tmp_path):
    """generate_commands_section parses help output."""
    branch_dir = tmp_path / "mybranch"
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir(parents=True)
    entry = apps_dir / "mybranch.py"
    entry.write_text("pass", encoding="utf-8")

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="Commands: audit, report, check\n",
            stderr="",
        )
        result = readme_generator.generate_commands_section(str(branch_dir))

    assert "audit" in result
    assert "report" in result


def test_generate_header_section_with_passport(tmp_path):
    """generate_header_section reads passport.json and produces header."""
    branch_dir = tmp_path / "mybranch"
    trinity_dir = branch_dir / ".trinity"
    trinity_dir.mkdir(parents=True)
    passport = {
        "branch_info": {
            "branch_name": "MYBRANCH",
            "path": str(branch_dir),
            "profile": "library",
            "created": "2026-01-01",
            "role": "Testing branch",
        }
    }
    (trinity_dir / "passport.json").write_text(json.dumps(passport), encoding="utf-8")

    result = readme_generator.generate_header_section(str(branch_dir))
    assert "MYBRANCH" in result
    assert "library" in result
    assert "Testing branch" in result


def test_generate_header_section_no_passport(tmp_path):
    """generate_header_section returns empty when passport is missing."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()

    result = readme_generator.generate_header_section(str(branch_dir))
    assert result == ""


def test_update_readme_auto_sections_dry_run(tmp_path):
    """update_readme_auto_sections in dry_run mode does not modify the file."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()
    readme = branch_dir / "README.md"
    original = "# Branch\n<!-- AUTO:LAST_UPDATED -->\n*Last Updated: 2025-01-01*\n<!-- /AUTO:LAST_UPDATED -->\n"
    readme.write_text(original, encoding="utf-8")

    result = readme_generator.update_readme_auto_sections(str(branch_dir), dry_run=True)
    assert result["dry_run"] is True
    assert readme.read_text(encoding="utf-8") == original


def test_update_readme_auto_sections_no_readme(tmp_path):
    """update_readme_auto_sections reports error when README is missing."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()

    result = readme_generator.update_readme_auto_sections(str(branch_dir))
    assert "README.md not found" in result["errors"]


def test_update_readme_auto_sections_missing_markers(tmp_path):
    """update_readme_auto_sections reports exactly the two sections it generated."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()
    readme = branch_dir / "README.md"
    readme.write_text("# Branch\nNo markers here.\n", encoding="utf-8")

    result = readme_generator.update_readme_auto_sections(str(branch_dir))
    assert result["missing_markers"] == ["tree", "last_updated"]
    assert result["updated"] == []
    assert result["errors"] == []
