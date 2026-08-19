# =================== AIPass ====================
# Name: test_log_watcher_service.py
# Description: Tests for the log watcher service entry point
# Version: 1.0.0
# Created: 2026-04-26
# Modified: 2026-04-26
# =============================================

"""Tests for log_watcher_service — the persistent service entry point."""

import signal
import sys
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Mock heavy watcher module imports before log_watcher_service loads."""

    # Mock branch_log_events module
    mock_branch = MagicMock()
    mock_branch.start = MagicMock(return_value=True)
    mock_branch.stop = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.modules.branch_log_events",
        mock_branch,
    )

    # Mock log_events module
    mock_system = MagicMock()
    mock_system.start = MagicMock(return_value=True)
    mock_system.stop = MagicMock()
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.modules.log_events",
        mock_system,
    )

    # Force re-import so mocks take effect
    monkeypatch.delitem(
        sys.modules,
        "aipass.trigger.apps.log_watcher_service",
        raising=False,
    )


def _import_module():
    """Import log_watcher_service fresh (after mocks are in place)."""
    import aipass.trigger.apps.log_watcher_service as mod

    return mod


# ---------------------------------------------------------------------------
# Tests -- print_introspection
# ---------------------------------------------------------------------------


class TestPrintIntrospection:
    """Tests for print_introspection output."""

    def test_prints_module_name(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Output includes the module name."""
        mod = _import_module()
        mod.print_introspection()
        captured = capsys.readouterr()
        assert "log_watcher_service" in captured.out

    def test_prints_description(self, capsys: pytest.CaptureFixture[str]) -> None:
        """Output includes the service description."""
        mod = _import_module()
        mod.print_introspection()
        captured = capsys.readouterr()
        assert "systemd" in captured.out and "service" in captured.out


# ---------------------------------------------------------------------------
# Tests -- main
# ---------------------------------------------------------------------------


class TestMain:
    """Tests for main() entry point."""

    def test_both_watchers_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both watchers start successfully, prints both names."""
        mod = _import_module()

        # Make stop_event.wait() return immediately
        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        # Both start functions return True (already the default from fixture)
        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        captured: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: captured.append(str(a)))

        mod.main()

        output = " ".join(captured)
        assert "branch" in output
        assert "system" in output
        assert "Stopped" in output

    def test_only_branch_watcher_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only branch watcher starts, prints only 'branch'."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=None)

        captured: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: captured.append(str(a)))

        mod.main()

        output = " ".join(captured)
        assert "branch" in output
        assert "system" not in output.replace("Stopped", "").split("Running")[1] if "Running" in output else True

    def test_only_system_watcher_starts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When only system watcher starts, prints only 'system'."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=None)
        mod.start_system_watcher = MagicMock(return_value=True)

        captured: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: captured.append(str(a)))

        mod.main()

        output = " ".join(captured)
        assert "system" in output

    def test_both_fail_exits_1(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both watchers fail, exits with code 1."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=None)
        mod.start_system_watcher = MagicMock(return_value=None)

        with pytest.raises(SystemExit) as exc_info:
            mod.main()

        assert exc_info.value.code == 1

    def test_calls_stop_on_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After stop_event is set, both stop functions are called."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        mock_stop_branch = MagicMock()
        mock_stop_system = MagicMock()
        mod.stop_branch_watcher = mock_stop_branch
        mod.stop_system_watcher = mock_stop_system

        # Suppress print output
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        mod.main()

        mock_stop_branch.assert_called_once()
        mock_stop_system.assert_called_once()

    def test_signal_handler_sets_stop_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shutdown closure sets the stop_event when invoked."""
        mod = _import_module()

        # Use a real Event but do NOT pre-set it; we will trigger it via
        # the signal handler that main() installs.
        real_event = threading.Event()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: real_event))

        # Capture the signal handler that main() registers (no-op stub
        # avoids calling real signal.signal which fails in threads).
        installed_handlers: dict[int, object] = {}

        def capture_signal(signum: int, handler: object) -> object:
            """Record installed signal handler for later inspection."""
            installed_handlers[signum] = handler
            return signal.SIG_DFL

        monkeypatch.setattr(signal, "signal", capture_signal)

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        # Suppress print output
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        # main() is called on the main thread; capture_signal is a no-op so
        # signal registration is safe.  The pre-set Event makes wait() return
        # immediately, but we need it NOT set yet so we can trigger via handler.
        # Instead, run main() in a background thread.
        t = threading.Thread(target=mod.main, daemon=True)
        t.start()

        # Poll-wait for main() to register the SIGTERM handler instead of a
        # fixed sleep, which can flake under load (deadline avoids a hang).
        import time

        deadline = time.monotonic() + 2.0
        while signal.SIGTERM not in installed_handlers and time.monotonic() < deadline:
            time.sleep(0.01)

        # Invoke the captured SIGTERM handler
        assert signal.SIGTERM in installed_handlers
        handler = installed_handlers[signal.SIGTERM]
        handler(signal.SIGTERM, None)  # type: ignore[operator]

        # The event should now be set, unblocking main()
        assert real_event.is_set()
        t.join(timeout=2)
        assert not t.is_alive()

    def test_registers_both_signal_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() registers handlers for both SIGTERM and SIGINT."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        installed_signals: list[int] = []
        original_signal = signal.signal

        def capture_signal(signum: int, handler: object) -> object:
            """Record which signal numbers are registered."""
            installed_signals.append(signum)
            return original_signal(signum, signal.SIG_DFL)

        monkeypatch.setattr(signal, "signal", capture_signal)

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        mod.main()

        assert signal.SIGTERM in installed_signals
        assert signal.SIGINT in installed_signals

    def test_both_fail_prints_stderr(self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
        """When both watchers fail, error message goes to stderr."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=False)
        mod.start_system_watcher = MagicMock(return_value=False)

        with pytest.raises(SystemExit):
            mod.main()

        captured = capsys.readouterr()
        assert "Both watchers failed" in captured.err


class TestReloadExit:
    """How the process leaves decides whether it comes back.

    The systemd unit ships `Restart=on-failure`. A reload that exited 0 would
    be read as a completed job and the watcher would simply stay down — the
    stale-code problem replaced by a missing-watcher problem.
    """

    def test_a_requested_reload_exits_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Reload requested -> exit RELOAD_EXIT_CODE so the supervisor restarts us."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        monkeypatch.setattr(mod.reload_sentinel, "start", lambda _stop: lambda: True)

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        with pytest.raises(SystemExit) as exit_info:
            mod.main()

        assert exit_info.value.code == mod.reload_sentinel.RELOAD_EXIT_CODE

    def test_an_ordinary_shutdown_does_not_exit_non_zero(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A SIGTERM must still look like a clean stop, not a failed unit."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        monkeypatch.setattr(mod.reload_sentinel, "start", lambda _stop: lambda: False)

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        captured: list[str] = []
        monkeypatch.setattr("builtins.print", lambda *a, **kw: captured.append(str(a)))

        mod.main()  # must not raise SystemExit

        assert "Stopped" in " ".join(captured)

    def test_the_watchers_are_stopped_before_the_reload_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Inotify watches must be released, or the restarted process inherits the leak."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        monkeypatch.setattr(mod.reload_sentinel, "start", lambda _stop: lambda: True)

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        mod.stop_branch_watcher = MagicMock()
        mod.stop_system_watcher = MagicMock()
        monkeypatch.setattr("builtins.print", lambda *a, **kw: None)

        with pytest.raises(SystemExit):
            mod.main()

        assert mod.stop_branch_watcher.called
        assert mod.stop_system_watcher.called
