"""Tests for the audit handler directory (audit_display, discovery, branch_audit)."""

# =================== META ====================
# Name: test_audit.py
# Description: Unit tests for handlers/audit/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports shared by audit handlers."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- cli ----------------------------------------------------------------
    cli_mod = MagicMock()
    cli_mod.console = mock_console
    cli_mod.header = mock_header
    monkeypatch.setitem(sys.modules, "aipass.cli", cli_mod)

    cli_apps = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", cli_apps)

    cli_modules = MagicMock()
    cli_modules.error = mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # -- bypass handler (used by branch_audit) ------------------------------
    bypass_pkg = MagicMock()
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    bypass_ignore = MagicMock()
    bypass_ignore.get_audit_ignore_patterns = MagicMock(return_value=["__pycache__"])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.ignore_handler", bypass_ignore)

    bypass_handler = MagicMock()
    bypass_handler.load_bypass_rules = MagicMock(return_value=[])
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.bypass_handler", bypass_handler)

    # Force re-imports
    for mod_name in [
        "aipass.seedgo.apps.handlers.audit.audit_display",
        "aipass.seedgo.apps.handlers.audit.discovery",
        "aipass.seedgo.apps.handlers.audit.branch_audit",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- audit_display._format_standard_name
# ---------------------------------------------------------------------------


def test_format_standard_name_snake_case():
    """_format_standard_name converts DEEP_NESTING to 'Deep Nesting'."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name

    assert _format_standard_name("DEEP_NESTING") == "Deep Nesting"


def test_format_standard_name_lower_snake():
    """_format_standard_name converts lower_snake to title case."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name

    assert _format_standard_name("error_handling") == "Error Handling"


def test_format_standard_name_single_word():
    """_format_standard_name handles single words."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name

    assert _format_standard_name("naming") == "Naming"


def test_format_standard_name_empty():
    """_format_standard_name handles empty string."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _format_standard_name

    assert _format_standard_name("") == ""


# ---------------------------------------------------------------------------
# Tests -- audit_display._render_violations
# ---------------------------------------------------------------------------


def test_render_violations_shows_file_paths():
    """_render_violations prints file info for each violation."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _render_violations

    mock_console = MagicMock()
    violations = [
        {"path": "/some/file.py", "score": 60, "issues": ["bad naming"]},
    ]
    _render_violations("naming", violations, mock_console)
    # At least the header and one file entry should be printed
    assert mock_console.print.call_count >= 2


def test_render_violations_truncates_at_five():
    """_render_violations shows at most 5 violations then 'and N more'."""
    from aipass.seedgo.apps.handlers.audit.audit_display import _render_violations

    mock_console = MagicMock()
    violations = [{"path": f"/file_{i}.py", "score": 50, "issues": ["issue"]} for i in range(8)]
    _render_violations("test", violations, mock_console)
    printed = " ".join(str(c) for c in mock_console.print.call_args_list)
    assert "3 more" in printed


# ---------------------------------------------------------------------------
# Tests -- discovery helpers
# ---------------------------------------------------------------------------


def test_discover_branches_returns_list():
    """discover_branches returns a list (possibly empty)."""
    from aipass.seedgo.apps.handlers.audit.discovery import discover_branches

    with patch.object(Path, "exists", return_value=False):
        result = discover_branches()
    assert isinstance(result, list)


def test_discover_branches_no_registry_returns_empty():
    """When no registry file exists, discover_branches returns empty list."""
    from aipass.seedgo.apps.handlers.audit import discovery

    with patch.object(type(discovery._find_registry()), "exists", return_value=False):
        result = discovery.discover_branches()
    assert result == []


# ---------------------------------------------------------------------------
# Tests -- branch_audit.discover_checkers
# ---------------------------------------------------------------------------


def test_discover_checkers_returns_dict(tmp_path):
    """discover_checkers returns a dict mapping names to modules."""
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    # Empty directory => empty dict
    result = discover_checkers(tmp_path)
    assert isinstance(result, dict)
    assert len(result) == 0


def test_discover_checkers_finds_check_files(tmp_path):
    """discover_checkers finds *_check.py files with check_module or check_branch."""
    check_file = tmp_path / "example_check.py"
    check_file.write_text(
        'AUDIT_SCOPE = "all_files"\n'
        "def check_module(module_path, bypass_rules=None):\n"
        '    return {"passed": True, "checks": [], "score": 100}\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.audit.branch_audit import discover_checkers

    result = discover_checkers(tmp_path)
    assert "example" in result


def test_collect_py_files_empty_branch(tmp_path):
    """_collect_py_files returns empty list when branch has no apps/ dir."""
    from aipass.seedgo.apps.handlers.audit.branch_audit import _collect_py_files

    result = _collect_py_files(tmp_path)
    assert result == []
