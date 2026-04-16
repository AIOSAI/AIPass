# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_search.py
# Date: 2026-03-24
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the search orchestration module.

Covers: from aipass.memory.apps.modules.search import handle_command

Tests command routing, handler discovery, argument parsing, and help flags.
All tests use mocks or tmp_path -- no live filesystem or infrastructure access.
"""

import sys
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helpers: build the full mock graph that search.py needs at import time
# ---------------------------------------------------------------------------


def _prepare_search_mocks(monkeypatch):
    """Insert mocks for every module-level import search.py touches.

    Returns a dict of key mock objects so tests can assert against them.
    """
    # rich
    mock_panel = MagicMock()
    mock_box = MagicMock()
    rich_panel_mod = MagicMock()
    rich_panel_mod.Panel = mock_panel
    rich_box_mod = MagicMock()
    rich_box_mod.box = mock_box
    monkeypatch.setitem(sys.modules, "rich.panel", rich_panel_mod)
    monkeypatch.setitem(sys.modules, "rich", MagicMock())

    # aipass.cli console / error / warning
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

    # aipass.memory.apps.handlers.search.query_executor
    mock_execute_search = MagicMock(
        return_value={
            "success": True,
            "collections_searched": 2,
            "total_results": 1,
            "results": [
                {
                    "collection": "seed_observations",
                    "document": "Test document content",
                    "metadata": {"timestamp": "2026-01-01", "source": "local.json"},
                    "similarity": 0.85,
                }
            ],
        }
    )
    mock_query_executor = MagicMock()
    mock_query_executor.execute_search = mock_execute_search

    search_handlers_pkg = MagicMock()
    search_handlers_pkg.query_executor = mock_query_executor

    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.search",
        search_handlers_pkg,
    )
    monkeypatch.setitem(
        sys.modules,
        "aipass.memory.apps.handlers.search.query_executor",
        mock_query_executor,
    )

    return {
        "console": mock_console,
        "error": mock_error,
        "warning": mock_warning,
        "execute_search": mock_execute_search,
    }


def _import_search(monkeypatch):
    """Prepare mocks and import (or reimport) the search module.

    Returns (search_module, mocks_dict).
    """
    mocks = _prepare_search_mocks(monkeypatch)

    # Remove cached module so it gets re-imported with our mocks
    sys.modules.pop("aipass.memory.apps.modules.search", None)

    # Also clear the parent package's cached attribute so Python
    # re-executes the module code with fresh mocks.
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "search"):
        delattr(parent, "search")

    from aipass.memory.apps.modules import search

    return search, mocks


# ---------------------------------------------------------------------------
# handle_command: routing
# ---------------------------------------------------------------------------


class TestHandleCommandRouting:
    """Verify that handle_command routes known commands and rejects unknown."""

    def test_search_no_args_calls_introspection(self, monkeypatch):
        """'search' with no args should call print_introspection and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_introspect = MagicMock()
        monkeypatch.setattr(search_mod, "print_introspection", mock_introspect)

        result = search_mod.handle_command("search", [])

        assert result is True
        mock_introspect.assert_called_once()

    def test_search_with_query_calls_show_results(self, monkeypatch):
        """'search' with query text should delegate to show_search_results."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_show = MagicMock(return_value=True)
        monkeypatch.setattr(search_mod, "show_search_results", mock_show)

        result = search_mod.handle_command("search", ["hello", "world"])

        assert result is True
        mock_show.assert_called_once_with("hello world", branch=None, memory_type=None, n_results=5)

    def test_unknown_command_returns_false(self, monkeypatch):
        """An unrecognised command should return False."""
        search_mod, _mocks = _import_search(monkeypatch)

        result = search_mod.handle_command("nonexistent", ["foo"])

        assert result is False

    def test_search_routes_correctly(self, monkeypatch):
        """'search' command should return True (handled), not False."""
        search_mod, _mocks = _import_search(monkeypatch)

        result = search_mod.handle_command("search", ["some query"])

        assert result is True


# ---------------------------------------------------------------------------
# handle_command: help flags
# ---------------------------------------------------------------------------


class TestHandleCommandHelp:
    """Verify help flags route to print_help."""

    def test_search_help_flag(self, monkeypatch):
        """'search --help' should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("search", ["--help"])

        assert result is True
        mock_help.assert_called_once()

    def test_search_h_flag(self, monkeypatch):
        """'search -h' should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("search", ["-h"])

        assert result is True
        mock_help.assert_called_once()

    def test_search_help_word(self, monkeypatch):
        """'search help' should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("search", ["help"])

        assert result is True
        mock_help.assert_called_once()

    def test_toplevel_help_flag(self, monkeypatch):
        """Top-level '--help' command should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("--help", [])

        assert result is True
        mock_help.assert_called_once()

    def test_toplevel_h_flag(self, monkeypatch):
        """Top-level '-h' command should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("-h", [])

        assert result is True
        mock_help.assert_called_once()

    def test_toplevel_help_word(self, monkeypatch):
        """Top-level 'help' command should call print_help and return True."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_help = MagicMock()
        monkeypatch.setattr(search_mod, "print_help", mock_help)

        result = search_mod.handle_command("help", [])

        assert result is True
        mock_help.assert_called_once()


# ---------------------------------------------------------------------------
# handle_command: argument parsing
# ---------------------------------------------------------------------------


class TestHandleCommandArgParsing:
    """Verify argument parsing: --branch, --type, --n, and edge cases."""

    def test_branch_option_parsed(self, monkeypatch):
        """--branch value should be forwarded to show_search_results."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_show = MagicMock(return_value=True)
        monkeypatch.setattr(search_mod, "show_search_results", mock_show)

        search_mod.handle_command("search", ["my", "query", "--branch", "SEEDGO"])

        mock_show.assert_called_once_with("my query", branch="SEEDGO", memory_type=None, n_results=5)

    def test_type_option_parsed(self, monkeypatch):
        """--type value should be forwarded to show_search_results."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_show = MagicMock(return_value=True)
        monkeypatch.setattr(search_mod, "show_search_results", mock_show)

        search_mod.handle_command("search", ["test", "--type", "observations"])

        mock_show.assert_called_once_with("test", branch=None, memory_type="observations", n_results=5)

    def test_n_option_parsed(self, monkeypatch):
        """--n value should override the default n_results."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_show = MagicMock(return_value=True)
        monkeypatch.setattr(search_mod, "show_search_results", mock_show)

        search_mod.handle_command("search", ["test", "--n", "10"])

        mock_show.assert_called_once_with("test", branch=None, memory_type=None, n_results=10)

    def test_all_options_combined(self, monkeypatch):
        """All options together should be correctly parsed."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_show = MagicMock(return_value=True)
        monkeypatch.setattr(search_mod, "show_search_results", mock_show)

        search_mod.handle_command(
            "search",
            ["find", "stuff", "--branch", "CLI", "--type", "local", "--n", "3"],
        )

        mock_show.assert_called_once_with("find stuff", branch="CLI", memory_type="local", n_results=3)

    def test_invalid_n_shows_error(self, monkeypatch):
        """Non-numeric --n value should call error() and return True."""
        search_mod, mocks = _import_search(monkeypatch)

        result = search_mod.handle_command("search", ["test", "--n", "abc"])

        assert result is True
        mocks["error"].assert_called_once()

    def test_empty_query_after_options_shows_error(self, monkeypatch):
        """Options only, no query text, should call error() and return True."""
        search_mod, mocks = _import_search(monkeypatch)

        result = search_mod.handle_command("search", ["--branch", "SEEDGO"])

        assert result is True
        mocks["error"].assert_called_once_with("Search query required")

    def test_empty_args_calls_introspection(self, monkeypatch):
        """Empty args list should trigger introspection, not crash."""
        search_mod, mocks = _import_search(monkeypatch)
        mock_introspect = MagicMock()
        monkeypatch.setattr(search_mod, "print_introspection", mock_introspect)

        result = search_mod.handle_command("search", [])

        assert result is True
        mock_introspect.assert_called_once()


# ---------------------------------------------------------------------------
# _discover_handlers: handler directory scanning
# ---------------------------------------------------------------------------


class TestDiscoverHandlers:
    """Verify handler auto-discovery logic with synthetic directory trees."""

    def test_discovers_handler_dirs_with_py_files(self, monkeypatch, tmp_path):
        """Should return a dict mapping dir name to list of .py filenames."""
        search_mod, _mocks = _import_search(monkeypatch)

        # Build a synthetic handlers/ directory tree
        handlers_dir = tmp_path / "handlers"
        search_dir = handlers_dir / "search"
        search_dir.mkdir(parents=True)
        (search_dir / "__init__.py").write_text("", encoding="utf-8")
        (search_dir / "query_executor.py").write_text("", encoding="utf-8")
        (search_dir / "vector_search.py").write_text("", encoding="utf-8")

        intake_dir = handlers_dir / "intake"
        intake_dir.mkdir(parents=True)
        (intake_dir / "plans_processor.py").write_text("", encoding="utf-8")

        # Patch __file__ so _discover_handlers resolves to our tmp_path
        # _discover_handlers computes: Path(__file__).resolve().parent.parent / "handlers"
        # So __file__ needs to be at tmp_path / modules / search.py
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "search.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(search_mod, "__file__", str(fake_file))

        result = search_mod._discover_handlers()

        assert "search" in result
        assert "query_executor.py" in result["search"]
        assert "vector_search.py" in result["search"]
        assert "__init__.py" not in result["search"]

        assert "intake" in result
        assert "plans_processor.py" in result["intake"]

    def test_skips_dunder_directories(self, monkeypatch, tmp_path):
        """Directories starting with __ (like __pycache__) should be skipped."""
        search_mod, _mocks = _import_search(monkeypatch)

        handlers_dir = tmp_path / "handlers"
        pycache_dir = handlers_dir / "__pycache__"
        pycache_dir.mkdir(parents=True)
        (pycache_dir / "something.py").write_text("", encoding="utf-8")

        valid_dir = handlers_dir / "valid"
        valid_dir.mkdir(parents=True)
        (valid_dir / "handler.py").write_text("", encoding="utf-8")

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "search.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(search_mod, "__file__", str(fake_file))

        result = search_mod._discover_handlers()

        assert "__pycache__" not in result
        assert "valid" in result

    def test_empty_dir_excluded(self, monkeypatch, tmp_path):
        """A handler directory with no .py files (only __init__.py) should not appear."""
        search_mod, _mocks = _import_search(monkeypatch)

        handlers_dir = tmp_path / "handlers"
        empty_dir = handlers_dir / "empty_handler"
        empty_dir.mkdir(parents=True)
        (empty_dir / "__init__.py").write_text("", encoding="utf-8")

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "search.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(search_mod, "__file__", str(fake_file))

        result = search_mod._discover_handlers()

        assert "empty_handler" not in result

    def test_missing_handlers_dir_returns_empty(self, monkeypatch, tmp_path):
        """If handlers/ directory does not exist, return empty dict."""
        search_mod, _mocks = _import_search(monkeypatch)

        # Point __file__ at a location with no handlers/ sibling
        modules_dir = tmp_path / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "search.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(search_mod, "__file__", str(fake_file))

        result = search_mod._discover_handlers()

        assert result == {}

    def test_files_at_handlers_root_ignored(self, monkeypatch, tmp_path):
        """Loose .py files directly in handlers/ (not in subdirs) should be ignored."""
        search_mod, _mocks = _import_search(monkeypatch)

        handlers_dir = tmp_path / "handlers"
        handlers_dir.mkdir(parents=True)
        (handlers_dir / "stray_file.py").write_text("", encoding="utf-8")

        modules_dir = tmp_path / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "search.py"
        fake_file.write_text("", encoding="utf-8")

        monkeypatch.setattr(search_mod, "__file__", str(fake_file))

        result = search_mod._discover_handlers()

        assert result == {}


# ---------------------------------------------------------------------------
# show_search_results: display path
# ---------------------------------------------------------------------------


class TestShowSearchResults:
    """Verify show_search_results calls the handler and renders output."""

    def test_successful_search_returns_true(self, monkeypatch):
        """A successful search should return True."""
        search_mod, mocks = _import_search(monkeypatch)

        result = search_mod.show_search_results("test query")

        assert result is True
        mocks["execute_search"].assert_called_once_with(query="test query", branch=None, memory_type=None, n_results=5)

    def test_failed_search_returns_false(self, monkeypatch):
        """If the handler returns success=False, show_search_results returns False."""
        search_mod, mocks = _import_search(monkeypatch)
        mocks["execute_search"].return_value = {
            "success": False,
            "error": "Connection failed",
        }

        result = search_mod.show_search_results("broken query")

        assert result is False
        mocks["error"].assert_called_once()

    def test_no_results_shows_warning(self, monkeypatch):
        """Zero results should trigger a warning, not an error."""
        search_mod, mocks = _import_search(monkeypatch)
        mocks["execute_search"].return_value = {
            "success": True,
            "collections_searched": 3,
            "total_results": 0,
            "results": [],
        }

        result = search_mod.show_search_results("obscure query")

        assert result is True
        mocks["warning"].assert_called_once()

    def test_options_forwarded_to_handler(self, monkeypatch):
        """Branch, memory_type, and n_results should be forwarded."""
        search_mod, mocks = _import_search(monkeypatch)

        search_mod.show_search_results("q", branch="SEEDGO", memory_type="local", n_results=3)

        mocks["execute_search"].assert_called_once_with(query="q", branch="SEEDGO", memory_type="local", n_results=3)

    def test_handler_timeout_returns_false(self, monkeypatch):
        """When the handler returns a timeout error, show_search_results returns False."""
        search_mod, mocks = _import_search(monkeypatch)
        mocks["execute_search"].return_value = {
            "success": False,
            "error": "Search operation timed out",
        }

        result = search_mod.show_search_results("timeout query")

        assert result is False
        mocks["error"].assert_called_once()

    def test_handler_timeout_does_not_crash(self, monkeypatch):
        """A timeout error from the handler should not raise an exception."""
        search_mod, mocks = _import_search(monkeypatch)
        mocks["execute_search"].return_value = {
            "success": False,
            "error": "Embedding timed out",
        }

        # Must not raise -- graceful handling
        result = search_mod.show_search_results("slow query")

        assert result is False
        mocks["error"].assert_called_once()

    def test_handler_exception_does_not_crash(self, monkeypatch):
        """If the handler raises an unexpected exception, it should not propagate."""
        import subprocess

        search_mod, mocks = _import_search(monkeypatch)
        mocks["execute_search"].side_effect = subprocess.TimeoutExpired(cmd="python embed_subprocess.py", timeout=120)

        result = search_mod.show_search_results("crash query")

        assert result is False
        mocks["error"].assert_called_once()
