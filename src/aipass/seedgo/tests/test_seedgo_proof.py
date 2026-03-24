"""Tests for seedgo_proof module."""

# =================== META ====================
# Name: test_seedgo_proof.py
# Description: Unit tests for the seedgo_proof module
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
    """Mock heavy infrastructure imports for seedgo_proof."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    mock_json_handler = MagicMock()

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
    cli_modules.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-import
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.seedgo_proof", raising=False)


# ---------------------------------------------------------------------------
# Tests — handle_command
# ---------------------------------------------------------------------------

def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    assert handle_command("wrong_command", []) is False


def test_handle_command_accepts_proof_name():
    """handle_command recognises 'proof' as its command."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("proof", [])
    assert result is True


def test_handle_command_accepts_seedgo_proof_name():
    """handle_command recognises 'seedgo_proof' as its command."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("seedgo_proof", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("proof", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("proof", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("proof", ["help"])
    assert result is True


def test_handle_command_unknown_pack():
    """Unknown pack name returns True (error displayed to user)."""
    from aipass.seedgo.apps.modules.seedgo_proof import handle_command
    result = handle_command("proof", ["nonexistent_pack_xyz"])
    assert result is True


# ---------------------------------------------------------------------------
# Tests — introspection / help
# ---------------------------------------------------------------------------

def test_print_introspection_runs():
    """print_introspection executes without raising."""
    from aipass.seedgo.apps.modules.seedgo_proof import print_introspection
    print_introspection()


def test_print_help_runs():
    """print_help executes without raising."""
    from aipass.seedgo.apps.modules.seedgo_proof import print_help
    print_help()


# ---------------------------------------------------------------------------
# Tests — discovery helpers
# ---------------------------------------------------------------------------

def test_discover_proof_packs_returns_dict():
    """_discover_proof_packs returns a dict."""
    from aipass.seedgo.apps.modules.seedgo_proof import _discover_proof_packs
    packs = _discover_proof_packs()
    assert isinstance(packs, dict)


def test_discover_proof_handlers_empty_dir(tmp_path):
    """_discover_proof_handlers returns empty list for empty directory."""
    from aipass.seedgo.apps.modules.seedgo_proof import _discover_proof_handlers
    result = _discover_proof_handlers(tmp_path)
    assert result == []


def test_discover_proof_handlers_skips_init(tmp_path):
    """_discover_proof_handlers skips __init__.py and _prefixed files."""
    from aipass.seedgo.apps.modules.seedgo_proof import _discover_proof_handlers
    (tmp_path / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "_private.py").write_text("", encoding="utf-8")
    (tmp_path / "valid_proof.py").write_text("", encoding="utf-8")
    result = _discover_proof_handlers(tmp_path)
    names = [p.name for p in result]
    assert "__init__.py" not in names
    assert "_private.py" not in names
    assert "valid_proof.py" in names


def test_discover_proof_handlers_skips_content_files(tmp_path):
    """_discover_proof_handlers skips *_content.py files."""
    from aipass.seedgo.apps.modules.seedgo_proof import _discover_proof_handlers
    (tmp_path / "architecture_content.py").write_text("", encoding="utf-8")
    (tmp_path / "real_proof.py").write_text("", encoding="utf-8")
    result = _discover_proof_handlers(tmp_path)
    names = [p.name for p in result]
    assert "architecture_content.py" not in names
    assert "real_proof.py" in names


def test_discover_proof_handlers_nonexistent_dir():
    """_discover_proof_handlers returns empty list for nonexistent directory."""
    from aipass.seedgo.apps.modules.seedgo_proof import _discover_proof_handlers
    result = _discover_proof_handlers(Path("/tmp/does_not_exist_xyz"))
    assert result == []


# ---------------------------------------------------------------------------
# Tests — proof execution helpers
# ---------------------------------------------------------------------------

def test_run_proof_pack_missing_target():
    """_run_proof_pack returns error when target standards pack is missing."""
    from aipass.seedgo.apps.modules.seedgo_proof import _run_proof_pack
    result = _run_proof_pack("nonexistent_xyz", Path("/tmp/does_not_exist"))
    assert result["certified"] is False
    assert "error" in result


def test_load_and_run_proof_missing_scan(tmp_path):
    """_load_and_run_proof returns error dict when handler has no scan() function."""
    from aipass.seedgo.apps.modules.seedgo_proof import _load_and_run_proof
    handler = tmp_path / "bad_proof.py"
    handler.write_text("# no scan function\nx = 1\n", encoding="utf-8")
    result = _load_and_run_proof(handler, tmp_path)
    assert result["passed"] is False
    assert result.get("not_implemented") is True


def test_load_and_run_proof_working_scan(tmp_path):
    """_load_and_run_proof correctly invokes scan() and returns its result."""
    from aipass.seedgo.apps.modules.seedgo_proof import _load_and_run_proof
    handler = tmp_path / "good_proof.py"
    handler.write_text(
        'from pathlib import Path\n'
        'def scan(pack_dir: Path) -> dict:\n'
        '    return {"passed": True, "issues": [], "summary": "All good"}\n',
        encoding="utf-8",
    )
    result = _load_and_run_proof(handler, tmp_path)
    assert result["passed"] is True
    assert result["summary"] == "All good"
