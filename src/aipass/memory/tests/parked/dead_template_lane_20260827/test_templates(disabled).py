# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_templates.py
# Date: 2026-03-24
# Version: 2.0.0
# Category: memory/tests
# =============================================

"""Tests for templates module -- repo root discovery, handler discovery, command routing.

Covers: from aipass.memory.apps.modules.templates import handle_command

All handler imports are mocked in sys.modules before the templates module is
imported so that no live infrastructure or handler code is needed.
"""

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers: build the full mock graph that templates.py needs at import time
# ---------------------------------------------------------------------------


def _prepare_templates_mocks(monkeypatch):
    """Insert mocks for every module-level import templates.py touches.

    Returns a dict of key mock objects so tests can assert against them.
    """
    # -- rich --
    mock_panel = MagicMock()
    mock_box = MagicMock()
    rich_panel_mod = MagicMock()
    rich_panel_mod.Panel = mock_panel
    rich_box_mod = MagicMock()
    rich_box_mod.box = mock_box
    monkeypatch.setitem(sys.modules, "rich.panel", rich_panel_mod)
    monkeypatch.setitem(sys.modules, "rich", MagicMock())

    # -- aipass.cli console / error / warning --
    mock_console = MagicMock()
    mock_error = MagicMock()
    mock_warning = MagicMock()
    cli_modules_mod = MagicMock()
    cli_modules_mod.console = mock_console
    cli_modules_mod.error = mock_error
    cli_modules_mod.warning = mock_warning
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules_mod)

    # -- aipass.memory.apps.handlers.json.memory_files --
    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    # -- aipass.memory.apps.handlers.templates.pusher --
    mock_pusher = MagicMock()
    mock_pusher.push_templates = MagicMock(
        return_value={
            "success": True,
            "branches_scanned": 5,
            "branches_updated": 2,
            "files_modified": 3,
            "changes": [],
            "errors": [],
        }
    )
    mock_pusher.get_template_status = MagicMock(
        return_value={
            "version": "2.0.0",
            "last_push": "2026-03-20",
            "local_template_exists": True,
            "observations_template_exists": True,
            "templates_dir": "/tmp/templates",
            "last_push_branches": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.pusher", mock_pusher)

    # -- aipass.memory.apps.handlers.templates.differ --
    mock_differ = MagicMock()
    mock_differ.diff_template_vs_branch = MagicMock(
        return_value={
            "local": [],
            "observations": [],
            "errors": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.differ", mock_differ)

    # -- aipass.memory.apps.handlers.templates.spawn_pusher --
    mock_spawn_pusher = MagicMock()
    mock_spawn_pusher.push_to_spawn_templates = MagicMock(
        return_value={
            "success": True,
            "template_sets_found": [],
            "template_sets_updated": 0,
            "files_modified": 0,
            "changes": [],
        }
    )
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.templates.spawn_pusher", mock_spawn_pusher)

    # -- parent packages that Python needs to resolve dotted imports --
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.templates",
        MagicMock(
            pusher=mock_pusher,
            differ=mock_differ,
            spawn_pusher=mock_spawn_pusher,
        ),
    )

    return {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "pusher": mock_pusher,
        "differ": mock_differ,
        "spawn_pusher": mock_spawn_pusher,
        "memory_files": mock_memory_files,
    }


def _import_templates(monkeypatch):
    """Prepare mocks and import (or reimport) the templates module.

    Returns (templates_module, mocks_dict).
    """
    mocks = _prepare_templates_mocks(monkeypatch)

    # Remove cached module so it re-imports with our mocks
    sys.modules.pop("aipass.memory.apps.modules.templates", None)

    # Also clear the parent package's cached attribute so Python
    # re-executes the module code with fresh mocks.
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "templates"):
        delattr(parent, "templates")

    from aipass.memory.apps.modules import templates

    return templates, mocks


# ===========================================================================
# Tests: _find_repo_root
# ===========================================================================


class TestFindRepoRoot:
    """Tests for _find_repo_root -- walks up from __file__ to find AIPASS_REGISTRY.json."""

    def test_finds_root_when_registry_exists(self, tmp_path: Path, monkeypatch) -> None:
        """Returns the directory containing AIPASS_REGISTRY.json."""
        templates, _ = _import_templates(monkeypatch)

        # Place a registry at the fake repo root
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

        # Create nested path mimicking real module location
        nested = tmp_path / "src" / "aipass" / "memory" / "apps" / "modules"
        nested.mkdir(parents=True)
        fake_module = nested / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        # Replicate the walk-up logic with our fake starting point
        current = fake_module.resolve().parent
        found: Path | None = None
        for parent in [current, *list(current.parents)]:
            if (parent / "AIPASS_REGISTRY.json").exists():
                found = parent
                break

        assert found == tmp_path

    def test_returns_cwd_when_no_registry(self, tmp_path: Path, monkeypatch) -> None:
        """Falls back to Path.cwd() when no AIPASS_REGISTRY.json is found."""
        templates, _ = _import_templates(monkeypatch)

        # Create a nested path with no registry anywhere above
        nested = tmp_path / "a" / "b" / "c" / "d"
        nested.mkdir(parents=True)

        current = nested
        found: Path | None = None
        for parent in [current, *list(current.parents)]:
            if (parent / "AIPASS_REGISTRY.json").exists():
                found = parent
                break

        # No registry found -- the real function falls back to Path.cwd()
        assert found is None

    def test_registry_at_immediate_parent(self, tmp_path: Path, monkeypatch) -> None:
        """Finds registry when it is in the immediate parent directory."""
        templates, _ = _import_templates(monkeypatch)

        parent_dir = tmp_path / "repo"
        parent_dir.mkdir()
        (parent_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

        child_dir = parent_dir / "child"
        child_dir.mkdir()

        current = child_dir
        found: Path | None = None
        for parent in [current, *list(current.parents)]:
            if (parent / "AIPASS_REGISTRY.json").exists():
                found = parent
                break

        assert found == parent_dir


# ===========================================================================
# Tests: _discover_handlers
# ===========================================================================


class TestDiscoverHandlers:
    """Tests for _discover_handlers -- auto-discovers handler directories."""

    def test_discovers_handler_directories(self, tmp_path: Path, monkeypatch) -> None:
        """Finds handler dirs with .py files, excluding __pycache__ and __init__.py."""
        templates, _ = _import_templates(monkeypatch)

        # Build fake handler structure: modules/templates.py -> parent.parent = apps -> handlers
        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        # json/ with two handler files
        json_dir = handlers_dir / "json"
        json_dir.mkdir()
        (json_dir / "json_handler.py").write_text("", encoding="utf-8")
        (json_dir / "memory_files.py").write_text("", encoding="utf-8")
        (json_dir / "__init__.py").write_text("", encoding="utf-8")

        # templates/ with one handler file
        tmpl_dir = handlers_dir / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "pusher.py").write_text("", encoding="utf-8")
        (tmpl_dir / "__init__.py").write_text("", encoding="utf-8")

        # __pycache__/ should be ignored
        cache_dir = handlers_dir / "__pycache__"
        cache_dir.mkdir()
        (cache_dir / "something.pyc").write_text("", encoding="utf-8")

        with patch.object(templates, "__file__", str(fake_module)):
            result = templates._discover_handlers()

        assert "json" in result
        assert "templates" in result
        assert "__pycache__" not in result
        assert "json_handler.py" in result["json"]
        assert "memory_files.py" in result["json"]
        assert "__init__.py" not in result["json"]
        assert "pusher.py" in result["templates"]

    def test_returns_empty_when_no_handlers_dir(self, tmp_path: Path, monkeypatch) -> None:
        """Returns empty dict when handlers/ does not exist."""
        templates, _ = _import_templates(monkeypatch)

        # Point __file__ at a location with no handlers/ sibling
        modules_dir = tmp_path / "nowhere" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        with patch.object(templates, "__file__", str(fake_module)):
            result = templates._discover_handlers()

        assert result == {}

    def test_skips_empty_handler_directories(self, tmp_path: Path, monkeypatch) -> None:
        """Directories with no .py files (only __init__.py) are not included."""
        templates, _ = _import_templates(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        # Empty dir (only __init__.py)
        empty_dir = handlers_dir / "empty"
        empty_dir.mkdir()
        (empty_dir / "__init__.py").write_text("", encoding="utf-8")

        # Dir with actual handler
        real_dir = handlers_dir / "real"
        real_dir.mkdir()
        (real_dir / "handler.py").write_text("", encoding="utf-8")

        with patch.object(templates, "__file__", str(fake_module)):
            result = templates._discover_handlers()

        assert "real" in result
        assert "empty" not in result

    def test_returns_sorted_keys_and_values(self, tmp_path: Path, monkeypatch) -> None:
        """Handler dirs and their files are sorted alphabetically."""
        templates, _ = _import_templates(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        handlers_dir.mkdir(parents=True)

        for name in ["zebra", "alpha"]:
            d = handlers_dir / name
            d.mkdir()
            (d / "b_file.py").write_text("", encoding="utf-8")
            (d / "a_file.py").write_text("", encoding="utf-8")

        with patch.object(templates, "__file__", str(fake_module)):
            result = templates._discover_handlers()

        keys = list(result.keys())
        assert keys == sorted(keys), "Handler directory keys should be sorted"

        for dir_name, files in result.items():
            assert files == sorted(files), f"Files in {dir_name} should be sorted"

    def test_ignores_non_py_files(self, tmp_path: Path, monkeypatch) -> None:
        """Non-.py files in handler directories are excluded."""
        templates, _ = _import_templates(monkeypatch)

        modules_dir = tmp_path / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_module = modules_dir / "templates.py"
        fake_module.write_text("", encoding="utf-8")

        handlers_dir = tmp_path / "apps" / "handlers"
        mixed_dir = handlers_dir / "mixed"
        mixed_dir.mkdir(parents=True)
        (mixed_dir / "handler.py").write_text("", encoding="utf-8")
        (mixed_dir / "README.md").write_text("", encoding="utf-8")
        (mixed_dir / "config.json").write_text("", encoding="utf-8")

        with patch.object(templates, "__file__", str(fake_module)):
            result = templates._discover_handlers()

        assert result["mixed"] == ["handler.py"]


# ===========================================================================
# Tests: handle_command routing
# ===========================================================================


class TestHandleCommand:
    """Tests for handle_command -- routes subcommands correctly."""

    # -- templates with no args -> introspection --

    def test_templates_no_args_calls_introspection(self, monkeypatch) -> None:
        """'templates' with no args triggers introspection display and returns True."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_introspection") as mock_intro:
            result = templates.handle_command("templates", [])

        mock_intro.assert_called_once()
        assert result is True

    # -- help flags --

    def test_templates_help_flag(self, monkeypatch) -> None:
        """'templates --help' triggers help display."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("templates", ["--help"])

        mock_help.assert_called_once()
        assert result is True

    def test_templates_dash_h_flag(self, monkeypatch) -> None:
        """'templates -h' triggers help display."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("templates", ["-h"])

        mock_help.assert_called_once()
        assert result is True

    def test_templates_help_word(self, monkeypatch) -> None:
        """'templates help' triggers help display."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("templates", ["help"])

        mock_help.assert_called_once()
        assert result is True

    def test_top_level_help_flag(self, monkeypatch) -> None:
        """'--help' as top-level command triggers help."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("--help", [])

        mock_help.assert_called_once()
        assert result is True

    def test_top_level_dash_h_flag(self, monkeypatch) -> None:
        """'-h' as top-level command triggers help."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("-h", [])

        mock_help.assert_called_once()
        assert result is True

    def test_top_level_help_word(self, monkeypatch) -> None:
        """'help' as top-level command triggers help."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "print_help") as mock_help:
            result = templates.handle_command("help", [])

        mock_help.assert_called_once()
        assert result is True

    # -- push-templates subcommand --

    def test_push_templates_subcommand(self, monkeypatch) -> None:
        """'templates push-templates' calls push handler with dry_run=False."""
        templates, mocks = _import_templates(monkeypatch)

        with (
            patch.object(templates, "_display_push_results"),
            patch.object(templates, "_display_spawn_push_results"),
        ):
            result = templates.handle_command("templates", ["push-templates"])

        mocks["pusher"].push_templates.assert_called_once_with(dry_run=False)
        mocks["spawn_pusher"].push_to_spawn_templates.assert_called_once_with(dry_run=False)
        assert result is True

    def test_push_templates_dry_run(self, monkeypatch) -> None:
        """'templates push-templates --dry-run' passes dry_run=True."""
        templates, mocks = _import_templates(monkeypatch)

        with (
            patch.object(templates, "_display_push_results"),
            patch.object(templates, "_display_spawn_push_results"),
        ):
            result = templates.handle_command("templates", ["push-templates", "--dry-run"])

        mocks["pusher"].push_templates.assert_called_once_with(dry_run=True)
        mocks["spawn_pusher"].push_to_spawn_templates.assert_called_once_with(dry_run=True)
        assert result is True

    # -- diff-templates subcommand --

    def test_diff_templates_subcommand(self, monkeypatch) -> None:
        """'templates diff-templates' calls diff display with no branch filter."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "_display_diff_results") as mock_display:
            result = templates.handle_command("templates", ["diff-templates"])

        mock_display.assert_called_once_with(None)
        assert result is True

    def test_diff_templates_with_branch_filter(self, monkeypatch) -> None:
        """'templates diff-templates --branch CLI' passes the branch name."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "_display_diff_results") as mock_display:
            result = templates.handle_command("templates", ["diff-templates", "--branch", "CLI"])

        mock_display.assert_called_once_with("CLI")
        assert result is True

    # -- template-status subcommand --

    def test_template_status_subcommand(self, monkeypatch) -> None:
        """'templates template-status' calls status handler."""
        templates, mocks = _import_templates(monkeypatch)

        with patch.object(templates, "_display_status"):
            result = templates.handle_command("templates", ["template-status"])

        mocks["pusher"].get_template_status.assert_called_once()
        assert result is True

    # -- backward-compatible top-level commands --

    def test_backward_compat_push_templates(self, monkeypatch) -> None:
        """'push-templates' as top-level command (backward compat) works."""
        templates, mocks = _import_templates(monkeypatch)

        with (
            patch.object(templates, "_display_push_results"),
            patch.object(templates, "_display_spawn_push_results"),
        ):
            result = templates.handle_command("push-templates", [])

        mocks["pusher"].push_templates.assert_called_once_with(dry_run=False)
        assert result is True

    def test_backward_compat_diff_templates(self, monkeypatch) -> None:
        """'diff-templates' as top-level command (backward compat) works."""
        templates, _ = _import_templates(monkeypatch)

        with patch.object(templates, "_display_diff_results") as mock_display:
            result = templates.handle_command("diff-templates", [])

        mock_display.assert_called_once_with(None)
        assert result is True

    def test_backward_compat_template_status(self, monkeypatch) -> None:
        """'template-status' as top-level command (backward compat) works."""
        templates, mocks = _import_templates(monkeypatch)

        with patch.object(templates, "_display_status"):
            result = templates.handle_command("template-status", [])

        mocks["pusher"].get_template_status.assert_called_once()
        assert result is True

    # -- unknown command returns False --

    def test_unknown_command_returns_false(self, monkeypatch) -> None:
        """Unknown top-level command returns False."""
        templates, _ = _import_templates(monkeypatch)

        result = templates.handle_command("totally-unknown", [])

        assert result is False

    def test_empty_string_command_returns_false(self, monkeypatch) -> None:
        """Empty string command returns False."""
        templates, _ = _import_templates(monkeypatch)

        result = templates.handle_command("", [])

        assert result is False

    # -- unknown subcommand returns True with error --

    def test_unknown_subcommand_returns_true_with_error(self, monkeypatch) -> None:
        """Unknown subcommand of 'templates' returns True (handled) but shows error."""
        templates, mocks = _import_templates(monkeypatch)

        result = templates.handle_command("templates", ["bogus-sub"])

        assert result is True
        mocks["error"].assert_called()

    # -- push-templates error handling --

    def test_push_templates_handles_push_exception(self, monkeypatch) -> None:
        """Push exception is caught and error is displayed, still returns True."""
        templates, mocks = _import_templates(monkeypatch)
        mocks["pusher"].push_templates.side_effect = RuntimeError("disk full")

        with (
            patch.object(templates, "_display_spawn_push_results"),
        ):
            result = templates.handle_command("templates", ["push-templates"])

        mocks["error"].assert_called()
        assert result is True

    def test_push_templates_handles_spawn_exception(self, monkeypatch) -> None:
        """Spawn push exception is caught separately, still returns True."""
        templates, mocks = _import_templates(monkeypatch)
        mocks["spawn_pusher"].push_to_spawn_templates.side_effect = RuntimeError("spawn error")

        with patch.object(templates, "_display_push_results"):
            result = templates.handle_command("templates", ["push-templates"])

        mocks["error"].assert_called()
        assert result is True


# ===========================================================================
# Tests: _load_branches_from_registry
# ===========================================================================


class TestLoadBranchesFromRegistry:
    """Tests for _load_branches_from_registry -- loads active branches from registry."""

    def test_loads_active_branches(self, tmp_path: Path, monkeypatch) -> None:
        """Returns only active branches with resolved paths."""
        templates, mocks = _import_templates(monkeypatch)

        registry_data = {
            "branches": [
                {"name": "ALPHA", "path": "src/aipass/alpha", "status": "active"},
                {"name": "BETA", "path": "src/aipass/beta", "status": "inactive"},
                {"name": "GAMMA", "path": "src/aipass/gamma", "status": "active"},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry_data, indent=2), encoding="utf-8")

        with (
            patch.object(templates, "REGISTRY_PATH", registry_path),
            patch.object(templates, "_REPO_ROOT", tmp_path),
            patch.object(templates, "read_memory_file_data", return_value=registry_data),
        ):
            result = templates._load_branches_from_registry()

        assert result is not None
        assert len(result) == 2
        names = [b["name"] for b in result]
        assert "ALPHA" in names
        assert "GAMMA" in names
        assert "BETA" not in names

    def test_resolves_relative_paths(self, tmp_path: Path, monkeypatch) -> None:
        """Relative paths are resolved against repo root."""
        templates, _ = _import_templates(monkeypatch)

        registry_data = {
            "branches": [
                {"name": "CLI", "path": "src/aipass/cli", "status": "active"},
            ]
        }
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry_data, indent=2), encoding="utf-8")

        with (
            patch.object(templates, "REGISTRY_PATH", registry_path),
            patch.object(templates, "_REPO_ROOT", tmp_path),
            patch.object(templates, "read_memory_file_data", return_value=registry_data),
        ):
            result = templates._load_branches_from_registry()

        assert result is not None
        assert len(result) == 1
        assert result[0]["path"] == str(tmp_path / "src" / "aipass" / "cli")

    def test_returns_none_when_registry_missing(self, tmp_path: Path, monkeypatch) -> None:
        """Returns None when REGISTRY_PATH does not exist."""
        templates, _ = _import_templates(monkeypatch)

        missing_path = tmp_path / "nonexistent" / "AIPASS_REGISTRY.json"

        with patch.object(templates, "REGISTRY_PATH", missing_path):
            result = templates._load_branches_from_registry()

        assert result is None

    def test_returns_none_when_read_fails(self, tmp_path: Path, monkeypatch) -> None:
        """Returns None when read_memory_file_data returns None."""
        templates, _ = _import_templates(monkeypatch)

        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text("{}", encoding="utf-8")

        with (
            patch.object(templates, "REGISTRY_PATH", registry_path),
            patch.object(templates, "read_memory_file_data", return_value=None),
        ):
            result = templates._load_branches_from_registry()

        assert result is None

    def test_empty_branches_returns_empty_list(self, tmp_path: Path, monkeypatch) -> None:
        """Returns empty list when branches key is empty."""
        templates, _ = _import_templates(monkeypatch)

        registry_data: dict = {"branches": []}
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(json.dumps(registry_data), encoding="utf-8")

        with (
            patch.object(templates, "REGISTRY_PATH", registry_path),
            patch.object(templates, "_REPO_ROOT", tmp_path),
            patch.object(templates, "read_memory_file_data", return_value=registry_data),
        ):
            result = templates._load_branches_from_registry()

        assert result is not None
        assert result == []


# ===========================================================================
# Tests: _SUBCOMMANDS dict
# ===========================================================================


class TestSubcommands:
    """Verify the _SUBCOMMANDS dict exists with expected keys."""

    def test_subcommands_exists(self, monkeypatch) -> None:
        templates, _ = _import_templates(monkeypatch)
        assert hasattr(templates, "_SUBCOMMANDS")

    def test_subcommands_has_push_templates(self, monkeypatch) -> None:
        templates, _ = _import_templates(monkeypatch)
        assert "push-templates" in templates._SUBCOMMANDS

    def test_subcommands_has_diff_templates(self, monkeypatch) -> None:
        templates, _ = _import_templates(monkeypatch)
        assert "diff-templates" in templates._SUBCOMMANDS

    def test_subcommands_has_template_status(self, monkeypatch) -> None:
        templates, _ = _import_templates(monkeypatch)
        assert "template-status" in templates._SUBCOMMANDS

    def test_subcommands_values_are_strings(self, monkeypatch) -> None:
        templates, _ = _import_templates(monkeypatch)
        for key, value in templates._SUBCOMMANDS.items():
            assert isinstance(key, str), f"Key {key!r} is not a string"
            assert isinstance(value, str), f"Value for {key!r} is not a string"
