"""Tests for seedgo handler functions (audit_display, diagnostics, json extras, readme, hooks_ext)."""

# =================== META ====================
# Name: test_handler_functions.py
# Description: Unit tests for handler-level functions across multiple handler packages
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

import json
import pytest
from typing import Dict
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for handler functions."""
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

    # -- bypass handler -----------------------------------------------------
    bypass_pkg = MagicMock()
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_ignore.get_audit_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    # -- cli (console for audit_display) ------------------------------------
    mock_console = MagicMock()
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    # -- cli.apps.modules (warning function for hooks_ext) ------------------
    cli_apps = MagicMock()
    cli_apps_modules = MagicMock()
    cli_apps_modules.warning = MagicMock()
    cli_apps.modules = cli_apps_modules
    cli_mod.apps = cli_apps
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_apps_modules)

    # Force re-imports so handler modules pick up fresh mocks
    for mod_name in [
        "aipass.seedgo.apps.handlers.audit.audit_display",
        "aipass.seedgo.apps.handlers.diagnostics.diagnostics_check",
        "aipass.seedgo.apps.handlers.json.json_handler",
        "aipass.seedgo.apps.handlers.readme.readme_ops",
        "aipass.seedgo.apps.handlers.readme.readme_generator",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# 1. audit_display -- print_branch_summary
# ===========================================================================


def test_print_branch_summary_basic():
    """print_branch_summary runs without error on minimal audit result."""
    from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary

    audit_result: Dict = {
        "branch": {"name": "seedgo"},
        "scores": {"meta": 100, "naming": 90},
        "average": 95,
        "files_checked": 10,
        "results": {},
    }
    # Should not raise
    print_branch_summary(audit_result)


def test_print_branch_summary_with_violations():
    """print_branch_summary handles violation lists."""
    from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary

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
    # Should not raise
    print_branch_summary(audit_result)


def test_print_branch_summary_with_system_averages():
    """print_branch_summary handles optional system averages."""
    from aipass.seedgo.apps.handlers.audit.audit_display import print_branch_summary

    audit_result: Dict = {
        "branch": {"name": "seedgo"},
        "scores": {"meta": 100},
        "average": 100,
        "files_checked": 1,
        "results": {},
    }
    system_averages: Dict[str, int] = {"meta": 90}
    # Should not raise
    print_branch_summary(audit_result, system_averages, 90)


# ===========================================================================
# 2. diagnostics_check -- check_directory
# ===========================================================================


def test_check_directory_missing(tmp_path):
    """check_directory on nonexistent directory returns error."""
    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
        check_directory,
    )

    result = check_directory(str(tmp_path / "nonexistent"))
    assert result["total_files"] == 0
    assert "error" in result
    assert "not found" in result["error"].lower()


def test_check_directory_exists(tmp_path):
    """check_directory on existing directory calls pyright."""
    # Create a Python file
    py_file = tmp_path / "example.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
        check_directory,
    )

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

    from aipass.seedgo.apps.handlers.diagnostics.diagnostics_check import (
        check_directory,
    )

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


# ===========================================================================
# 3-4. json_handler -- increment_counter, update_data_metrics: SUBJECT GONE
# ===========================================================================
#
# Both sections were removed with the pair-4 sweep (DPLAN-0325). seedgo's
# handler is now the fleet's canonical shim, which binds nine names, and
# neither of these is among them -- the one json service never had them.
#
# Deleted rather than re-pointed because there is nothing left to point at,
# and NOT quietly: a sweep that drops a public entry point should say so.
# Measured before removing, across every branch: outside the five handlers
# that still define them (flow, daemon, commons, drone, trigger, all
# unmigrated), the fleet has no caller of either function. They were handler
# surface nobody used, so the sweep retired dead code rather than breaking a
# consumer -- but the same two names will disappear from those five branches
# when their sweep lands, and each should check its own callers first.
#
# The helper these two sections shared, _get_real_json_handler, went with
# them: it existed to import the real module past this file's mock and then
# monkeypatch _BRANCH_ROOT / _BRANCH_NAME / JSON_DIR onto it. The shim has
# none of those three -- the service resolves its directory per call through
# the AIPASS_TEST_LOG_DIR seam that conftest's mock_infrastructure sets.

# 5. readme_ops -- resolve_branch
# ===========================================================================


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

    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@seedgo")
    assert result is not None
    assert result["name"] == "seedgo"


def test_resolve_branch_not_found(tmp_path, monkeypatch):
    """resolve_branch returns None for unknown branch."""
    registry_data = {"branches": [{"name": "seedgo"}]}
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@nonexistent")
    assert result is None


def test_resolve_branch_no_registry(tmp_path, monkeypatch):
    """resolve_branch returns None when registry does not exist."""
    from aipass.seedgo.apps.handlers.readme import readme_ops

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

    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    result = readme_ops.resolve_branch("@sg")
    assert result is not None
    assert result["name"] == "seedgo"


# ===========================================================================
# 6. readme_ops -- get_all_branches
# ===========================================================================


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

    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    branches = readme_ops.get_all_branches()
    assert len(branches) == 3


def test_get_all_branches_empty_registry(tmp_path, monkeypatch):
    """get_all_branches returns empty list when registry has no branches."""
    registry_path = tmp_path / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps({"branches": []}), encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: registry_path)

    branches = readme_ops.get_all_branches()
    assert branches == []


def test_get_all_branches_no_registry(tmp_path, monkeypatch):
    """get_all_branches returns empty list when registry is missing."""
    from aipass.seedgo.apps.handlers.readme import readme_ops

    monkeypatch.setattr(readme_ops, "_find_registry", lambda: tmp_path / "MISSING.json")

    branches = readme_ops.get_all_branches()
    assert branches == []


# ===========================================================================
# 7. readme_generator -- generate_commands_section
# ===========================================================================


def test_generate_commands_section_no_entry_point(tmp_path):
    """generate_commands_section returns empty when no entry point exists."""
    branch_dir = tmp_path / "mybranch"
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir(parents=True)

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        generate_commands_section,
    )

    result = generate_commands_section(str(branch_dir))
    assert result == ""


def test_generate_commands_section_with_help(tmp_path):
    """generate_commands_section parses help output."""
    branch_dir = tmp_path / "mybranch"
    apps_dir = branch_dir / "apps"
    apps_dir.mkdir(parents=True)
    entry = apps_dir / "mybranch.py"
    entry.write_text("pass", encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        generate_commands_section,
    )

    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout="Commands: audit, report, check\n",
            stderr="",
        )
        result = generate_commands_section(str(branch_dir))

    assert "audit" in result
    assert "report" in result


# ===========================================================================
# 8. readme_generator -- generate_header_section
# ===========================================================================


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

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        generate_header_section,
    )

    result = generate_header_section(str(branch_dir))
    assert "MYBRANCH" in result
    assert "library" in result
    assert "Testing branch" in result


def test_generate_header_section_no_passport(tmp_path):
    """generate_header_section returns empty when passport is missing."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        generate_header_section,
    )

    result = generate_header_section(str(branch_dir))
    assert result == ""


# ===========================================================================
# 9. readme_generator -- update_readme_auto_sections
# ===========================================================================


def test_update_readme_auto_sections_dry_run(tmp_path):
    """update_readme_auto_sections in dry_run mode does not modify the file."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()
    readme = branch_dir / "README.md"
    original = "# Branch\n<!-- AUTO:LAST_UPDATED -->\n*Last Updated: 2025-01-01*\n<!-- /AUTO:LAST_UPDATED -->\n"
    readme.write_text(original, encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        update_readme_auto_sections,
    )

    result = update_readme_auto_sections(str(branch_dir), dry_run=True)
    assert result["dry_run"] is True
    # File should not be modified in dry run
    assert readme.read_text(encoding="utf-8") == original


def test_update_readme_auto_sections_no_readme(tmp_path):
    """update_readme_auto_sections reports error when README is missing."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        update_readme_auto_sections,
    )

    result = update_readme_auto_sections(str(branch_dir))
    assert "README.md not found" in result["errors"]


def test_update_readme_auto_sections_missing_markers(tmp_path):
    """update_readme_auto_sections reports missing markers."""
    branch_dir = tmp_path / "mybranch"
    branch_dir.mkdir()
    readme = branch_dir / "README.md"
    readme.write_text("# Branch\nNo markers here.\n", encoding="utf-8")

    from aipass.seedgo.apps.handlers.readme.readme_generator import (
        update_readme_auto_sections,
    )

    result = update_readme_auto_sections(str(branch_dir))
    # Some sections should report missing markers
    assert len(result["missing_markers"]) > 0 or len(result["updated"]) == 0
