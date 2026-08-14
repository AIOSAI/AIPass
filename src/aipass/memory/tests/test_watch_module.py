# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_watch_module.py
# Date: 2026-08-13
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for the watch module (APLAN-0010 encapsulation item).

`watch` used to be a built-in on the entry point, which imported two monitor
handlers directly — the encapsulation violation on apps/memory.py. It is now a
module like every other command.

Covers:
  - Routing: only the 'watch' command is claimed, everything else declines
  - Help interception via the shared wants_help() predicate, in any slot
  - No args starts the watcher (the live contract — 'drone @memory watch')
  - Unknown argument errors and does NOT start the watcher
  - Watcher start failure is reported, not swallowed
  - Introspection names the monitor handlers it is wired to
"""

import importlib
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers: import the module with the monitor handlers mocked out
# ---------------------------------------------------------------------------


@pytest.fixture
def watch_module(monkeypatch):
    """Import modules/watch.py with its two monitor handlers replaced by mocks.

    Returns:
        Tuple of (module, mocks) where mocks holds the patched handler functions.
    """
    watcher_mod = MagicMock()
    detector_mod = MagicMock()
    watcher_mod.start_memory_watcher.return_value = {"success": True, "count": 17}
    watcher_mod.stop_memory_watcher.return_value = None
    detector_mod.get_rollover_stats.return_value = {
        "success": True,
        "files_ready": 3,
        "files_checked": 34,
    }

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.memory_watcher", watcher_mod)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", detector_mod)
    sys.modules.pop("aipass.memory.apps.handlers.monitor.watch_runner", None)
    sys.modules.pop("aipass.memory.apps.modules.watch", None)

    module = importlib.import_module("aipass.memory.apps.modules.watch")
    runner = importlib.import_module("aipass.memory.apps.handlers.monitor.watch_runner")
    yield module, {"watcher": watcher_mod, "detector": detector_mod, "runner": runner}

    sys.modules.pop("aipass.memory.apps.modules.watch", None)
    sys.modules.pop("aipass.memory.apps.handlers.monitor.watch_runner", None)


# ---------------------------------------------------------------------------
# Routing
# ---------------------------------------------------------------------------


class TestWatchRouting:
    """handle_command claims 'watch' and nothing else."""

    def test_declines_other_commands(self, watch_module):
        """A module that eats foreign commands breaks entry-point routing."""
        module, _ = watch_module
        assert module.handle_command("rollover", []) is False
        assert module.handle_command("search", ["query"]) is False

    def test_claims_watch(self, watch_module):
        module, _ = watch_module
        with patch.object(module, "_start_session") as started:
            assert module.handle_command("watch", []) is True
        started.assert_called_once()

    def test_top_level_help_is_claimed(self, watch_module):
        """The entry point may forward bare help flags to modules."""
        module, _ = watch_module
        with patch.object(module, "print_help") as helped:
            assert module.handle_command("--help", []) is True
        helped.assert_called_once()


# ---------------------------------------------------------------------------
# Help interception
# ---------------------------------------------------------------------------


class TestWatchHelp:
    """A help flag is never an instruction — it must never start the watcher."""

    @pytest.mark.parametrize("args", [["--help"], ["-h"], ["help"]])
    def test_help_flag_prints_help_and_does_not_watch(self, watch_module, args):
        module, _ = watch_module
        with patch.object(module, "print_help") as helped, patch.object(module, "_start_session") as started:
            assert module.handle_command("watch", args) is True
        helped.assert_called_once()
        started.assert_not_called()

    def test_help_flag_in_later_slot_still_intercepts(self, watch_module):
        """Reading args[0] only is the bug this predicate exists to prevent."""
        module, _ = watch_module
        with patch.object(module, "print_help") as helped, patch.object(module, "_start_session") as started:
            assert module.handle_command("watch", ["now", "--help"]) is True
        helped.assert_called_once()
        started.assert_not_called()


# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------


class TestWatchArguments:
    """Unknown input fails loudly instead of starting a long-running process."""

    def test_unknown_argument_errors_without_watching(self, watch_module):
        module, _ = watch_module
        with patch.object(module, "_start_session") as started, patch.object(module, "error") as errored:
            assert module.handle_command("watch", ["forever"]) is True
        started.assert_not_called()
        errored.assert_called_once()

    def test_unknown_argument_names_the_valid_usage(self, watch_module):
        module, _ = watch_module
        with patch.object(module, "_start_session"), patch.object(module, "error") as errored:
            with patch.object(module.json_handler, "log_operation"):
                module.handle_command("watch", ["forever"])
        message = " ".join(str(a) for a in errored.call_args.args)
        suggestion = str(errored.call_args.kwargs.get("suggestion", ""))
        assert "forever" in message
        assert "watch" in suggestion

    def test_rejected_invocation_is_logged(self, watch_module):
        """A refused command is an operational event, not just terminal output."""
        module, _ = watch_module
        with patch.object(module, "_start_session"), patch.object(module, "error"):
            with patch.object(module.json_handler, "log_operation") as logged:
                module.handle_command("watch", ["forever"])
        logged.assert_called_once()
        assert "forever" in str(logged.call_args)


# ---------------------------------------------------------------------------
# Watcher startup
# ---------------------------------------------------------------------------


class TestWatchSession:
    """The session reports what it is watching, and fails loudly.

    Display lives in the module; the lifecycle calls it delegates to live in
    handlers/monitor/watch_runner.py (cli separation standard).
    """

    def test_session_starts_the_watcher_and_blocks(self, watch_module):
        module, mocks = watch_module
        with patch.object(module, "wait_forever") as loop:
            module._start_session()
        mocks["watcher"].start_memory_watcher.assert_called_once()
        loop.assert_called_once()

    def test_session_reports_failure_and_never_blocks(self, watch_module):
        """A failed start must not fall through into the wait loop, where it
        would look like a healthy watcher doing nothing."""
        module, mocks = watch_module
        mocks["watcher"].start_memory_watcher.return_value = {"success": False, "error": "no registry"}

        with patch.object(module, "wait_forever") as loop, patch.object(module, "error") as errored:
            module._start_session()

        errored.assert_called_once()
        assert "no registry" in " ".join(str(a) for a in errored.call_args.args)
        loop.assert_not_called()

    def test_session_shows_the_over_cap_count(self, watch_module):
        module, mocks = watch_module
        with patch.object(module, "wait_forever"):
            module._start_session()
        mocks["detector"].get_rollover_stats.assert_called_once()


class TestWatchRunnerHandler:
    """The handler returns data and prints nothing."""

    def test_start_watching_logs_and_returns_result(self, watch_module):
        _, mocks = watch_module
        runner = mocks["runner"]
        with patch.object(runner.json_handler, "log_operation") as logged:
            result = runner.start_watching()
        assert result["success"] is True
        logged.assert_called_once()

    def test_failed_start_is_logged_as_failure(self, watch_module):
        _, mocks = watch_module
        runner = mocks["runner"]
        mocks["watcher"].start_memory_watcher.return_value = {"success": False, "error": "boom"}
        with patch.object(runner.json_handler, "log_operation") as logged:
            result = runner.start_watching()
        assert result["success"] is False
        assert "boom" in str(logged.call_args)

    def test_stop_watching_delegates(self, watch_module):
        _, mocks = watch_module
        runner = mocks["runner"]
        with patch.object(runner.json_handler, "log_operation"):
            runner.stop_watching()
        mocks["watcher"].stop_memory_watcher.assert_called_once()

    def test_handler_prints_nothing(self, watch_module):
        """Display belongs to the module -- a printing handler breaks that."""
        _, mocks = watch_module
        source = Path(mocks["runner"].__file__).read_text(encoding="utf-8")
        assert "console.print" not in source


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


class TestWatchIntrospection:
    """Level 2 introspection: the module names the handlers it is wired to."""

    def test_introspection_names_monitor_handlers(self, watch_module, capsys):
        module, _ = watch_module
        module.print_introspection()
        out = capsys.readouterr().out
        assert "watch" in out
        assert "monitor" in out

    def test_help_mentions_the_live_command(self, watch_module, capsys):
        module, _ = watch_module
        module.print_help()
        out = capsys.readouterr().out
        assert "drone @memory watch" in out
