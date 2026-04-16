# =================== AIPass ====================
# Name: test_generic_adapter.py
# Description: Tests for generic_adapter.capture_main()
# Version: 1.0.0
# Created: 2026-04-03
# Modified: 2026-04-03
# =============================================

"""Tests for generic_adapter.capture_main().

Covers:
- stdout / stderr capture from a target module's ``main()``
- exit_code from normal return, SystemExit(0), SystemExit(1), SystemExit(None)
- Exception handling (ValueError, ImportError)
- Non-int exit codes coerced to 1
- sys.argv construction with various combinations
- sys.argv / sys.stdout / sys.stderr restoration after success and failure
- json_handler.log_operation is called with expected args
"""

from __future__ import annotations

import sys
import types
from collections.abc import Callable
from unittest.mock import MagicMock, patch

import pytest

from aipass.drone.apps.handlers.generic_adapter import capture_main


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_log_operation():
    """Prevent json_handler.log_operation from touching disk."""
    with patch("aipass.drone.apps.handlers.generic_adapter.json_handler") as mock_jh:
        mock_jh.log_operation = MagicMock()
        yield


@pytest.fixture()
def _fake_module_factory(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[str, Callable[[], object]], None]:
    """Return a helper that registers a fake module with a given ``main``."""

    def _make(module_name: str, main_fn: Callable[[], object]) -> None:
        mod = types.ModuleType(module_name)
        mod.main = main_fn  # type: ignore[attr-defined]
        monkeypatch.setitem(sys.modules, module_name, mod)

    return _make


# ---------------------------------------------------------------------------
# stdout capture
# ---------------------------------------------------------------------------


class TestStdoutCapture:
    """Verify that output written to stdout is captured."""

    def test_stdout_printed_by_main(self, _fake_module_factory):
        _fake_module_factory("fake_stdout", lambda: print("hello world") or 0)
        result = capture_main("fake_stdout", "prog")
        assert result["stdout"] == "hello world\n"
        assert result["stderr"] == ""
        assert result["exit_code"] == 0

    def test_stdout_multiline(self, _fake_module_factory):
        def _main():
            print("line1")
            print("line2")
            return 0

        _fake_module_factory("fake_multi", _main)
        result = capture_main("fake_multi", "prog")
        assert result["stdout"] == "line1\nline2\n"


# ---------------------------------------------------------------------------
# stderr capture
# ---------------------------------------------------------------------------


class TestStderrCapture:
    """Verify that output written to stderr is captured."""

    def test_stderr_written_by_main(self, _fake_module_factory):
        def _main():
            sys.stderr.write("warning msg")
            return 0

        _fake_module_factory("fake_stderr", _main)
        result = capture_main("fake_stderr", "prog")
        assert result["stderr"] == "warning msg"
        assert result["stdout"] == ""
        assert result["exit_code"] == 0


# ---------------------------------------------------------------------------
# exit_code handling
# ---------------------------------------------------------------------------


class TestExitCode:
    """Various return / SystemExit / exception exit-code scenarios."""

    def test_normal_return_int(self, _fake_module_factory):
        _fake_module_factory("ret_int", lambda: 42)
        result = capture_main("ret_int", "prog")
        assert result["exit_code"] == 42

    def test_normal_return_zero(self, _fake_module_factory):
        _fake_module_factory("ret_zero", lambda: 0)
        result = capture_main("ret_zero", "prog")
        assert result["exit_code"] == 0

    def test_system_exit_zero(self, _fake_module_factory):
        def _main():
            raise SystemExit(0)

        _fake_module_factory("se0", _main)
        result = capture_main("se0", "prog")
        assert result["exit_code"] == 0

    def test_system_exit_one(self, _fake_module_factory):
        def _main():
            raise SystemExit(1)

        _fake_module_factory("se1", _main)
        result = capture_main("se1", "prog")
        assert result["exit_code"] == 1

    def test_system_exit_none(self, _fake_module_factory):
        def _main():
            raise SystemExit(None)

        _fake_module_factory("se_none", _main)
        result = capture_main("se_none", "prog")
        assert result["exit_code"] == 0

    def test_non_int_exit_code_coerced_to_one(self, _fake_module_factory):
        """main() returns a string -- adapter coerces to exit_code=1."""
        _fake_module_factory("ret_str", lambda: "oops")
        result = capture_main("ret_str", "prog")
        assert result["exit_code"] == 1

    def test_none_return_coerced_to_one(self, _fake_module_factory):
        """main() returns None (implicit) -- not an int, coerced to 1."""
        _fake_module_factory("ret_none", lambda: None)
        result = capture_main("ret_none", "prog")
        assert result["exit_code"] == 1


# ---------------------------------------------------------------------------
# Exception handling
# ---------------------------------------------------------------------------


class TestExceptionHandling:
    """Exceptions inside main() should be captured on stderr."""

    def test_value_error_captured(self, _fake_module_factory):
        def _main():
            raise ValueError("bad value")

        _fake_module_factory("raise_ve", _main)
        result = capture_main("raise_ve", "prog")
        assert result["exit_code"] == 1
        assert "bad value" in result["stderr"]

    def test_import_error_for_missing_module(self):
        """Non-existent module triggers ImportError -> exit_code=1."""
        result = capture_main("totally.nonexistent.module", "prog")
        assert result["exit_code"] == 1
        assert result["stderr"] != ""


# ---------------------------------------------------------------------------
# sys.argv construction
# ---------------------------------------------------------------------------


class TestArgvConstruction:
    """Ensure sys.argv is assembled correctly from name/command/args."""

    def test_name_only(self, _fake_module_factory):
        captured_argv: list[list[str]] = []

        def _main():
            captured_argv.append(list(sys.argv))
            return 0

        _fake_module_factory("argv_name", _main)
        capture_main("argv_name", "myprog")
        assert captured_argv[0] == ["myprog"]

    def test_name_and_command(self, _fake_module_factory):
        captured_argv: list[list[str]] = []

        def _main():
            captured_argv.append(list(sys.argv))
            return 0

        _fake_module_factory("argv_cmd", _main)
        capture_main("argv_cmd", "myprog", command="run")
        assert captured_argv[0] == ["myprog", "run"]

    def test_name_command_and_args(self, _fake_module_factory):
        captured_argv: list[list[str]] = []

        def _main():
            captured_argv.append(list(sys.argv))
            return 0

        _fake_module_factory("argv_full", _main)
        capture_main("argv_full", "myprog", command="run", args=["--verbose", "file.txt"])
        assert captured_argv[0] == ["myprog", "run", "--verbose", "file.txt"]

    def test_name_and_args_no_command(self, _fake_module_factory):
        captured_argv: list[list[str]] = []

        def _main():
            captured_argv.append(list(sys.argv))
            return 0

        _fake_module_factory("argv_nocommand", _main)
        capture_main("argv_nocommand", "myprog", args=["--flag"])
        assert captured_argv[0] == ["myprog", "--flag"]


# ---------------------------------------------------------------------------
# Restoration of sys.argv / stdout / stderr
# ---------------------------------------------------------------------------


class TestRestoration:
    """sys.argv, sys.stdout, sys.stderr must be restored after call."""

    def test_restoration_after_success(self, _fake_module_factory):
        _fake_module_factory("ok_mod", lambda: 0)

        orig_argv = sys.argv
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        capture_main("ok_mod", "prog")

        assert sys.argv is orig_argv
        assert sys.stdout is orig_stdout
        assert sys.stderr is orig_stderr

    def test_restoration_after_exception(self, _fake_module_factory):
        def _main():
            raise RuntimeError("boom")

        _fake_module_factory("err_mod", _main)

        orig_argv = sys.argv
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        capture_main("err_mod", "prog")

        assert sys.argv is orig_argv
        assert sys.stdout is orig_stdout
        assert sys.stderr is orig_stderr

    def test_restoration_after_system_exit(self, _fake_module_factory):
        def _main():
            raise SystemExit(2)

        _fake_module_factory("exit_mod", _main)

        orig_argv = sys.argv
        orig_stdout = sys.stdout
        orig_stderr = sys.stderr

        capture_main("exit_mod", "prog")

        assert sys.argv is orig_argv
        assert sys.stdout is orig_stdout
        assert sys.stderr is orig_stderr


# ---------------------------------------------------------------------------
# json_handler.log_operation call
# ---------------------------------------------------------------------------


class TestLogOperation:
    """Verify json_handler.log_operation is invoked with correct args."""

    def test_log_operation_called(self, _fake_module_factory):
        _fake_module_factory("log_mod", lambda: 0)
        with patch("aipass.drone.apps.handlers.generic_adapter.json_handler") as mock_jh:
            capture_main("log_mod", "myprog", command="status")
            mock_jh.log_operation.assert_called_once()
            call_args = mock_jh.log_operation.call_args
            assert call_args[0][0] == "generic_adapter.capture_main"
            payload = call_args[0][1]
            assert payload["entry_point"] == "log_mod"
            assert payload["name"] == "myprog"
            assert payload["command"] == "status"
