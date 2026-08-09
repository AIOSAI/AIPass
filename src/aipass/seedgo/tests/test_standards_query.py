"""Tests for standards_query module."""

# =================== META ====================
# Name: test_standards_query.py
# Description: Unit tests for the standards_query module
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-08-07
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards_query."""
    import sys

    mock_logger = MagicMock()
    mock_console = MagicMock()
    mock_header = MagicMock()
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
    monkeypatch.delitem(sys.modules, "aipass.seedgo.apps.modules.standards_query", raising=False)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_handle_command_wrong_command_returns_false():
    """handle_command returns False for unrecognised commands."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("wrong_command", []) is False


def test_handle_command_no_args_shows_introspection():
    """No args triggers introspection (returns True)."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    result = handle_command("standards_query", [])
    assert result is True


def test_handle_command_help_flag():
    """--help flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    result = handle_command("standards_query", ["--help"])
    assert result is True


def test_handle_command_h_flag():
    """-h flag is handled without error."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    result = handle_command("standards_query", ["-h"])
    assert result is True


def test_handle_command_help_word():
    """'help' word is handled without error."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    result = handle_command("standards_query", ["help"])
    assert result is True


def test_handle_command_unknown_pack():
    """Unknown pack name returns True (error displayed to user)."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    result = handle_command("standards_query", ["nonexistent_pack_xyz"])
    assert result is True


def test_print_introspection_runs():
    """print_introspection executes without raising."""
    from aipass.seedgo.apps.modules.standards_query import print_introspection

    print_introspection()


def test_print_help_runs():
    """print_help executes without raising."""
    from aipass.seedgo.apps.modules.standards_query import print_help

    print_help()


def test_discover_packs_returns_dict():
    """_discover_packs returns a dict."""
    from aipass.seedgo.apps.modules.standards_query import _discover_packs

    packs = _discover_packs()
    assert isinstance(packs, dict)


def test_discover_standards_empty_dir(tmp_path):
    """_discover_standards returns empty dict for a directory with no content files."""
    from aipass.seedgo.apps.modules.standards_query import _discover_standards

    result = _discover_standards(tmp_path)
    assert result == {}


def test_discover_standards_finds_content_files(tmp_path):
    """_discover_standards discovers *_content.py files correctly."""
    from aipass.seedgo.apps.modules.standards_query import _discover_standards

    # Create a fake content file
    (tmp_path / "architecture_content.py").write_text("# fake", encoding="utf-8")
    (tmp_path / "not_a_content.py").write_text("# fake", encoding="utf-8")
    result = _discover_standards(tmp_path)
    assert "architecture" in result
    assert "not_a_content" not in result


# ---------------------------------------------------------------------------
# `standard <name>` short alias
# ---------------------------------------------------------------------------


def test_alias_no_args_lists_all_standards():
    """`standard` with no args lists every standard (returns True)."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("standard", []) is True


def test_alias_shows_content_for_known_standard():
    """`standard json_structure` resolves the pack itself and displays content."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("standard", ["json_structure"]) is True


def test_alias_unknown_standard_returns_true():
    """Unknown standard name is reported to the user, not silently passed on."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("standard", ["nonexistent_standard_xyz"]) is True


def test_alias_help_flag():
    """`standard --help` is handled without error."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("standard", ["--help"]) is True


def test_print_alias_help_runs():
    """print_alias_help executes without raising."""
    from aipass.seedgo.apps.modules.standards_query import print_alias_help

    print_alias_help()


def test_resolve_standard_finds_single_owner():
    """_resolve_standard finds exactly one pack owning a real standard."""
    from aipass.seedgo.apps.modules.standards_query import _resolve_standard

    matches = _resolve_standard("json_structure")
    assert len(matches) == 1
    pack_name, content_file = matches[0]
    assert pack_name.endswith("_standards")
    assert content_file.name == "json_structure_content.py"


def test_resolve_standard_unknown_returns_empty():
    """_resolve_standard returns no matches for an unknown name."""
    from aipass.seedgo.apps.modules.standards_query import _resolve_standard

    assert _resolve_standard("nonexistent_standard_xyz") == []


def test_all_standard_names_maps_name_to_packs():
    """_all_standard_names maps each standard name to the packs defining it."""
    from aipass.seedgo.apps.modules.standards_query import _all_standard_names

    names = _all_standard_names()
    assert "json_structure" in names
    assert isinstance(names["json_structure"], list)
    assert all(pack.endswith("_standards") for pack in names["json_structure"])


def test_alias_ambiguous_name_refuses_to_guess(monkeypatch):
    """Two packs defining one name → error + explicit form, no content loaded."""
    from aipass.seedgo.apps.modules import standards_query

    fake = {"a_standards": "a", "b_standards": "b"}
    monkeypatch.setattr(standards_query, "_discover_packs", lambda: fake)
    monkeypatch.setattr(standards_query, "_discover_standards", lambda _p: {"dupe": "dupe_content.py"})

    loaded = []
    monkeypatch.setattr(standards_query, "_display_content", lambda *a: loaded.append(a))

    assert standards_query.handle_command("standard", ["dupe"]) is True
    assert loaded == []


def test_alias_does_not_swallow_other_commands():
    """The alias must not claim commands owned by other modules."""
    from aipass.seedgo.apps.modules.standards_query import handle_command

    assert handle_command("audit", ["aipass"]) is False
    assert handle_command("checklist", ["some_file.py"]) is False


# ---------------------------------------------------------------------------
# Embedded pointer canary
# ---------------------------------------------------------------------------


def test_custom_config_guide_pointer_actually_resolves():
    """The guide command embedded in audit output must be a real, working command.

    The whole point of the info line is that a reader can paste it and get the
    standard. A command that errors makes the pointer worse than useless, so
    this parses the shipped constant and resolves it for real.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import CUSTOM_CONFIG_GUIDE
    from aipass.seedgo.apps.modules.standards_query import (
        ALIAS_COMMAND,
        QUERY_COMMAND,
        _discover_packs,
        _discover_standards,
        _resolve_standard,
    )

    command_text = CUSTOM_CONFIG_GUIDE.split("Guide:", 1)[-1].strip()
    tokens = command_text.split()
    assert tokens[:2] == ["drone", "@seedgo"], f"Pointer is not a drone command: {command_text}"

    command, args = tokens[2], tokens[3:]
    assert command in (QUERY_COMMAND, ALIAS_COMMAND), f"Pointer cites unknown command '{command}'"

    if command == ALIAS_COMMAND:
        assert len(_resolve_standard(args[0])) == 1, f"Alias pointer does not resolve: {command_text}"
        return

    pack_name, standard_name = args[0], args[1]
    packs = _discover_packs()
    assert pack_name in packs, f"Pointer cites unknown pack '{pack_name}'"
    assert standard_name in _discover_standards(packs[pack_name]), f"Pointer cites unknown standard '{standard_name}'"
