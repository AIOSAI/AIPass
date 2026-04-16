# =================== META ====================
# Name: test_verify.py
# Description: Tests for verify module (plan vectorization check)
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Tests for the verify module: _get_memory_python, _check_plan_subprocess,
is_plan_vectorized, handle_command, _discover_handlers.

Covers: from aipass.memory.apps.modules.verify import handle_command
"""

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Helper: mock CLI modules that verify.py imports at module level
# ---------------------------------------------------------------------------


def _mock_cli_modules(monkeypatch):
    """Inject mocks for aipass.cli.apps.modules (console, error)."""
    mock_console = MagicMock()
    mock_error = MagicMock()
    cli_modules = MagicMock()
    cli_modules.console = mock_console
    cli_modules.error = mock_error
    monkeypatch.setitem(sys.modules, "aipass.cli", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.cli.apps.modules", cli_modules)
    return mock_console, mock_error


def _import_verify():
    """Import verify module inside the test (after mocks are in place)."""
    from aipass.memory.apps.modules import verify

    return verify


# ===========================================================================
# 1. _get_memory_python()
# ===========================================================================


class TestGetMemoryPython:
    """Tests for _get_memory_python() resolution logic."""

    def test_env_override_takes_precedence(self, monkeypatch):
        """AIPASS_MEMORY_PYTHON env var overrides all other paths."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        monkeypatch.setenv("AIPASS_MEMORY_PYTHON", "/custom/bin/python3")
        result = verify._get_memory_python()
        assert result == "/custom/bin/python3"

    def test_venv_python_used_when_exists(self, monkeypatch, tmp_path):
        """When the memory .venv python exists, it should be returned."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        # Remove env override so it doesn't interfere
        monkeypatch.delenv("AIPASS_MEMORY_PYTHON", raising=False)

        # Create a fake venv python
        fake_python = tmp_path / ".venv" / "bin" / "python"
        fake_python.parent.mkdir(parents=True)
        fake_python.touch()

        # Patch the module-level constant
        monkeypatch.setattr(verify, "_MEMORY_VENV_PYTHON", fake_python)
        result = verify._get_memory_python()
        assert result == str(fake_python)

    def test_fallback_to_sys_executable(self, monkeypatch):
        """When no env var and no venv, fall back to sys.executable."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        monkeypatch.delenv("AIPASS_MEMORY_PYTHON", raising=False)
        # Point to a path that does not exist
        monkeypatch.setattr(verify, "_MEMORY_VENV_PYTHON", Path("/nonexistent/.venv/bin/python"))
        result = verify._get_memory_python()
        assert result == sys.executable

    def test_env_override_empty_string_is_falsy(self, monkeypatch):
        """An empty AIPASS_MEMORY_PYTHON env var should be treated as unset."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        monkeypatch.setenv("AIPASS_MEMORY_PYTHON", "")
        # Empty string is falsy, so it should NOT be returned
        monkeypatch.setattr(verify, "_MEMORY_VENV_PYTHON", Path("/nonexistent/.venv/bin/python"))
        result = verify._get_memory_python()
        # Falls through to venv check (missing) then sys.executable
        assert result == sys.executable


# ===========================================================================
# 2. _check_plan_subprocess()
# ===========================================================================


class TestCheckPlanSubprocess:
    """Tests for _check_plan_subprocess() subprocess orchestration."""

    def test_success_returns_parsed_json(self, monkeypatch):
        """Successful subprocess returns parsed JSON dict."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        expected = {"success": True, "found": True, "count": 5, "source_files": ["a.md"]}
        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = json.dumps(expected)

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        result = verify._check_plan_subprocess("FPLAN-0126")
        assert result["success"] is True
        assert result["found"] is True
        assert result["count"] == 5
        assert "a.md" in result["source_files"]

    def test_nonzero_returncode_returns_error(self, monkeypatch):
        """Non-zero return code produces error dict with stderr message."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = "collection not found"

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        result = verify._check_plan_subprocess("FPLAN-9999")
        assert result["success"] is False
        assert "collection not found" in result["error"]

    def test_nonzero_returncode_empty_stderr(self, monkeypatch):
        """Non-zero return with empty stderr gives generic failure message."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_result = MagicMock()
        fake_result.returncode = 1
        fake_result.stderr = ""

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        result = verify._check_plan_subprocess("FPLAN-0001")
        assert result["success"] is False
        assert result["error"] == "Subprocess failed"

    def test_timeout_returns_error(self, monkeypatch):
        """Subprocess timeout produces a clear error message."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        def raise_timeout(*args, **kwargs):
            raise subprocess.TimeoutExpired(cmd="python", timeout=60)

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", raise_timeout)

        result = verify._check_plan_subprocess("FPLAN-0126")
        assert result["success"] is False
        assert "timed out" in result["error"]

    def test_invalid_json_returns_error(self, monkeypatch):
        """Invalid JSON stdout produces a JSON decode error."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_result = MagicMock()
        fake_result.returncode = 0
        fake_result.stdout = "not valid json {{"

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", lambda *a, **kw: fake_result)

        result = verify._check_plan_subprocess("FPLAN-0126")
        assert result["success"] is False
        assert "Invalid JSON" in result["error"]

    def test_generic_exception_returns_error(self, monkeypatch):
        """Any other exception is caught and returned as error."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        def raise_oserror(*args, **kwargs):
            raise OSError("No such file or directory")

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", raise_oserror)

        result = verify._check_plan_subprocess("FPLAN-0126")
        assert result["success"] is False
        assert "No such file or directory" in result["error"]

    def test_subprocess_receives_correct_input(self, monkeypatch):
        """Verify the input JSON sent to subprocess contains correct fields."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        captured_kwargs = {}

        def capture_run(*args, **kwargs):
            captured_kwargs.update(kwargs)
            result = MagicMock()
            result.returncode = 0
            result.stdout = json.dumps({"success": True, "found": False, "count": 0})
            return result

        monkeypatch.setattr(verify, "_get_memory_python", lambda: "/usr/bin/python3")
        monkeypatch.setattr(subprocess, "run", capture_run)

        verify._check_plan_subprocess("HPLAN-0042")
        input_data = json.loads(captured_kwargs["input"])
        assert input_data["operation"] == "check_plan"
        assert input_data["plan_label"] == "HPLAN-0042"


# ===========================================================================
# 3. is_plan_vectorized()
# ===========================================================================


class TestIsPlanVectorized:
    """Tests for the public is_plan_vectorized() API."""

    def test_delegates_to_check_plan_subprocess(self, monkeypatch):
        """is_plan_vectorized is a thin wrapper around _check_plan_subprocess."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        expected = {"success": True, "found": True, "count": 3, "source_files": []}
        monkeypatch.setattr(verify, "_check_plan_subprocess", lambda label: expected)

        result = verify.is_plan_vectorized("FPLAN-0126")
        assert result is expected
        assert result["found"] is True
        assert result["count"] == 3

    def test_returns_failure_dict_on_error(self, monkeypatch):
        """When subprocess fails, the error dict propagates through."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        error_result = {"success": False, "error": "something broke"}
        monkeypatch.setattr(verify, "_check_plan_subprocess", lambda label: error_result)

        result = verify.is_plan_vectorized("FPLAN-0000")
        assert result["success"] is False
        assert result["error"] == "something broke"


# ===========================================================================
# 4. handle_command()
# ===========================================================================


class TestHandleCommand:
    """Tests for handle_command() routing."""

    def test_verify_no_args_calls_introspection(self, monkeypatch):
        """'verify' with no args triggers print_introspection."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"introspection": False}

        def fake_introspection():
            called["introspection"] = True

        monkeypatch.setattr(verify, "print_introspection", fake_introspection)

        result = verify.handle_command("verify", [])
        assert result is True
        assert called["introspection"] is True

    def test_verify_help_flag(self, monkeypatch):
        """'verify --help' triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}

        def fake_help():
            called["help"] = True

        monkeypatch.setattr(verify, "print_help", fake_help)

        result = verify.handle_command("verify", ["--help"])
        assert result is True
        assert called["help"] is True

    def test_verify_h_flag(self, monkeypatch):
        """'verify -h' triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}
        monkeypatch.setattr(verify, "print_help", lambda: called.update(help=True))

        result = verify.handle_command("verify", ["-h"])
        assert result is True
        assert called["help"] is True

    def test_verify_help_word(self, monkeypatch):
        """'verify help' triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}
        monkeypatch.setattr(verify, "print_help", lambda: called.update(help=True))

        result = verify.handle_command("verify", ["help"])
        assert result is True
        assert called["help"] is True

    def test_verify_with_plan_label(self, monkeypatch):
        """'verify FPLAN-0126' calls _verify_plan with the label."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        captured_label = {}

        def fake_verify_plan(label):
            captured_label["label"] = label

        monkeypatch.setattr(verify, "_verify_plan", fake_verify_plan)

        result = verify.handle_command("verify", ["FPLAN-0126"])
        assert result is True
        assert captured_label["label"] == "FPLAN-0126"

    def test_unknown_command_returns_false(self, monkeypatch):
        """Unknown command returns False (not handled)."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        result = verify.handle_command("bogus", ["arg1"])
        assert result is False

    def test_toplevel_help_flag(self, monkeypatch):
        """Top-level '--help' command triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}
        monkeypatch.setattr(verify, "print_help", lambda: called.update(help=True))

        result = verify.handle_command("--help", [])
        assert result is True
        assert called["help"] is True

    def test_toplevel_h_flag(self, monkeypatch):
        """Top-level '-h' command triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}
        monkeypatch.setattr(verify, "print_help", lambda: called.update(help=True))

        result = verify.handle_command("-h", [])
        assert result is True
        assert called["help"] is True

    def test_toplevel_help_word(self, monkeypatch):
        """Top-level 'help' command triggers print_help."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        called = {"help": False}
        monkeypatch.setattr(verify, "print_help", lambda: called.update(help=True))

        result = verify.handle_command("help", [])
        assert result is True
        assert called["help"] is True


# ===========================================================================
# 5. _discover_handlers()
# ===========================================================================


def _setup_fake_module_tree(tmp_path):
    """Build tmp_path/apps/modules/verify.py and apps/handlers/ so that
    patching verify.__file__ makes _discover_handlers() scan our fake tree.

    _discover_handlers does:
        Path(__file__).resolve().parent.parent / "handlers"
    so __file__ must sit at  <root>/apps/modules/verify.py
    and handlers at          <root>/apps/handlers/
    """
    modules_dir = tmp_path / "apps" / "modules"
    modules_dir.mkdir(parents=True)
    fake_file = modules_dir / "verify.py"
    fake_file.touch()
    handlers_dir = tmp_path / "apps" / "handlers"
    handlers_dir.mkdir(parents=True)
    return str(fake_file), handlers_dir


class TestDiscoverHandlers:
    """Tests for _discover_handlers() directory scanning."""

    def test_discovers_handler_directories_with_py_files(self, monkeypatch, tmp_path):
        """Finds handler dirs containing .py files (excluding __init__.py)."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, handlers_dir = _setup_fake_module_tree(tmp_path)

        storage_dir = handlers_dir / "storage"
        storage_dir.mkdir()
        (storage_dir / "__init__.py").write_text("", encoding="utf-8")
        (storage_dir / "chroma_subprocess.py").write_text("", encoding="utf-8")
        (storage_dir / "vector_store.py").write_text("", encoding="utf-8")

        search_dir = handlers_dir / "search"
        search_dir.mkdir()
        (search_dir / "__init__.py").write_text("", encoding="utf-8")
        (search_dir / "query_engine.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        assert "storage" in result
        assert "search" in result
        assert "chroma_subprocess.py" in result["storage"]
        assert "vector_store.py" in result["storage"]
        assert "query_engine.py" in result["search"]
        # __init__.py should be excluded
        assert "__init__.py" not in result["storage"]

    def test_skips_dunder_directories(self, monkeypatch, tmp_path):
        """Directories starting with __ (like __pycache__) are skipped."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, handlers_dir = _setup_fake_module_tree(tmp_path)

        pycache = handlers_dir / "__pycache__"
        pycache.mkdir()
        (pycache / "verify.cpython-312.pyc").write_text("", encoding="utf-8")

        real_dir = handlers_dir / "json"
        real_dir.mkdir()
        (real_dir / "json_handler.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        assert "__pycache__" not in result
        assert "json" in result

    def test_empty_handlers_dir_returns_empty(self, monkeypatch, tmp_path):
        """An empty handlers directory returns an empty dict."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, _handlers_dir = _setup_fake_module_tree(tmp_path)
        # handlers_dir exists but is empty (no subdirs)
        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        assert result == {}

    def test_missing_handlers_dir_returns_empty(self, monkeypatch, tmp_path):
        """A nonexistent handlers directory returns an empty dict."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        # Point __file__ at a tree with no handlers/ at all
        modules_dir = tmp_path / "no_handlers" / "apps" / "modules"
        modules_dir.mkdir(parents=True)
        fake_file = modules_dir / "verify.py"
        fake_file.touch()

        monkeypatch.setattr(verify, "__file__", str(fake_file))

        result = verify._discover_handlers()
        assert result == {}

    def test_dir_with_only_init_is_excluded(self, monkeypatch, tmp_path):
        """A handler dir with only __init__.py (no real modules) is excluded."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, handlers_dir = _setup_fake_module_tree(tmp_path)

        empty_handler = handlers_dir / "empty_handler"
        empty_handler.mkdir()
        (empty_handler / "__init__.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        assert "empty_handler" not in result
        assert result == {}

    def test_non_py_files_are_ignored(self, monkeypatch, tmp_path):
        """Non-.py files (README, .json, etc.) are not included."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, handlers_dir = _setup_fake_module_tree(tmp_path)

        config_dir = handlers_dir / "config"
        config_dir.mkdir()
        (config_dir / "settings.json").write_text("{}", encoding="utf-8")
        (config_dir / "README.md").write_text("docs", encoding="utf-8")
        (config_dir / "config_handler.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        assert "config" in result
        assert result["config"] == ["config_handler.py"]
        # Confirm non-py files are absent
        all_files = [f for files in result.values() for f in files]
        assert "settings.json" not in all_files
        assert "README.md" not in all_files

    def test_results_are_sorted(self, monkeypatch, tmp_path):
        """Handler dirs and files within them are returned in sorted order."""
        _mock_cli_modules(monkeypatch)
        verify = _import_verify()

        fake_file, handlers_dir = _setup_fake_module_tree(tmp_path)

        # Create dirs in reverse alphabetical order
        for name in ["zebra", "alpha", "middle"]:
            d = handlers_dir / name
            d.mkdir()
            (d / "handler.py").write_text("", encoding="utf-8")

        # Add multiple files to alpha in non-sorted order
        (handlers_dir / "alpha" / "z_module.py").write_text("", encoding="utf-8")
        (handlers_dir / "alpha" / "a_module.py").write_text("", encoding="utf-8")

        monkeypatch.setattr(verify, "__file__", fake_file)

        result = verify._discover_handlers()
        dir_names = list(result.keys())
        assert dir_names == ["alpha", "middle", "zebra"]
        assert result["alpha"] == ["a_module.py", "handler.py", "z_module.py"]
