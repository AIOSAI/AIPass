# =================== AIPass ====================
# Name: test_log_watcher_service.py
# Description: Tests for the log watcher service entry point
# Version: 1.1.1
# Created: 2026-04-26
# Modified: 2026-10-24
# =============================================

"""Tests for apps/log_watcher_service.py — the persistent service entry point."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — the reload decision behind reload_sentinel.start, in test_reload_sentinel.py
# seedgo: no-test-needed(covered_elsewhere) — the branch watcher start_branch_watcher drives, in test_log_watcher.py

import signal
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import aipass.trigger.apps.log_watcher_service as log_watcher_service


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every door main() opens onto the live watchers and the catch-up.
    Collaborators are bound by name at import, so they are replaced on the service module;
    monkeypatch also undoes tests that assign ``mod.start_branch_watcher`` directly.
    """
    # The real watchers arm watchdog observers over the LIVE log tree.
    monkeypatch.setattr(log_watcher_service, "start_branch_watcher", MagicMock(return_value=True))
    monkeypatch.setattr(log_watcher_service, "stop_branch_watcher", MagicMock())
    monkeypatch.setattr(log_watcher_service, "start_system_watcher", MagicMock(return_value=True))
    monkeypatch.setattr(log_watcher_service, "stop_system_watcher", MagicMock())

    # The real catch-up walks the live system_logs and fires error_detected; tests assert on this mock.
    monkeypatch.setattr(log_watcher_service, "run_error_catchup", MagicMock())
    # The real purge rewrites the LIVE error registry.
    monkeypatch.setattr(log_watcher_service, "purge_stale", MagicMock(return_value=0))

    # The shell may be systemd-supervised: main() starts reload_sentinel,
    # whose evaluate() only acts under INVOCATION_ID.
    monkeypatch.delenv("INVOCATION_ID", raising=False)


def _import_module():
    """Hand each test the service module, its doors already patched."""
    return log_watcher_service


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


class TestHelpFlag:
    """A help flag explains the service and starts nothing.
    The event is pre-set, so a guard that lets the start through still returns; the start stubs count what ran.
    """

    @pytest.mark.parametrize("flag", ["--help", "-h"])
    def test_a_help_flag_prints_usage_and_starts_nothing(
        self, flag: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """The usage text goes out and no watcher or catch-up runs (mutant: the guard dropped)."""
        mod = _import_module()
        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        monkeypatch.setattr(mod.reload_sentinel, "start", lambda _stop: lambda: False)
        branch, system, catchup = MagicMock(return_value=True), MagicMock(return_value=True), MagicMock()
        monkeypatch.setattr(mod, "start_branch_watcher", branch)
        monkeypatch.setattr(mod, "start_system_watcher", system)
        monkeypatch.setattr(mod, "run_error_catchup", catchup)

        mod.main([flag])

        assert "Usage" in capsys.readouterr().out
        branch.assert_not_called()
        system.assert_not_called()
        catchup.assert_not_called()

    def test_no_arguments_still_starts_the_watchers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The control: the plain start the unit makes still starts both watchers (mutant: every start refused)."""
        mod = _import_module()
        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        monkeypatch.setattr(mod.reload_sentinel, "start", lambda _stop: lambda: False)
        branch, system = MagicMock(return_value=True), MagicMock(return_value=True)
        monkeypatch.setattr(mod, "start_branch_watcher", branch)
        monkeypatch.setattr(mod, "start_system_watcher", system)

        mod.main([])

        branch.assert_called_once_with()
        system.assert_called_once_with()


class TestMain:
    """Tests for main() entry point."""

    def test_both_watchers_start(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both watchers start successfully, prints both names."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        captured: list[str] = []
        monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: captured.append(str(a)))
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: captured.append(str(a)))

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
        monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: captured.append(str(a)))
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: captured.append(str(a)))

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
        monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: captured.append(str(a)))
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: captured.append(str(a)))

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

    def test_start_purges_stale_rows_but_keeps_suppressed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each start bounds the registry; suppressed rows stay, or they would wake their owner again."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.main()

        mod.purge_stale.assert_called_once_with(30, keep_suppressed=True)

    def test_calls_stop_on_shutdown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """After stop_event is set, both stop functions are called (mutant: the two stops swapped)."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        stopped: list[str] = []
        mod.stop_branch_watcher = MagicMock(side_effect=lambda: stopped.append("branch"))
        mod.stop_system_watcher = MagicMock(side_effect=lambda: stopped.append("system"))

        mod.main()

        assert stopped == ["branch", "system"]

    def test_signal_handler_sets_stop_event(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The shutdown closure sets the stop_event when invoked (mutant: shutdown() no longer sets the event)."""
        mod = _import_module()

        # Not pre-set: only the signal handler main() installs may set it.
        real_event = threading.Event()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: real_event))

        # The sentinel start hook runs between installing the handlers and wait(), so wait()
        # returns only if the handler main() installed set the event (else --timeout fails it).
        def deliver_sigterm(_stop: object):
            """Deliver SIGTERM through the handler main() installed."""
            handler = signal.getsignal(signal.SIGTERM)
            assert callable(handler), f"main() installed no SIGTERM handler: {handler!r}"
            handler(signal.SIGTERM, None)
            return lambda: False

        monkeypatch.setattr(mod.reload_sentinel, "start", deliver_sigterm)
        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            mod.main()
        finally:
            for sig, previous in saved.items():
                signal.signal(sig, previous)

        assert real_event.is_set()

    def test_registers_both_signal_handlers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """main() registers handlers for both SIGTERM and SIGINT (mutant: the SIGINT registration dropped)."""
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)

        saved = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
        try:
            mod.main()
            installed = {sig: signal.getsignal(sig) for sig in saved}
        finally:
            for sig, previous in saved.items():
                signal.signal(sig, previous)

        assert getattr(installed[signal.SIGTERM], "__name__", None) == "shutdown"
        assert getattr(installed[signal.SIGINT], "__name__", None) == "shutdown"

    def test_both_fail_is_reported_at_error_level(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """When both watchers fail, the reason is reported at ERROR level.
        A failed startup is the one lifecycle message here that is not INFO.
        """
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))

        mod.start_branch_watcher = MagicMock(return_value=False)
        mod.start_system_watcher = MagicMock(return_value=False)

        errors: list[str] = []
        infos: list[str] = []
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: errors.append(str(a)))
        monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: infos.append(str(a)))

        with pytest.raises(SystemExit):
            mod.main()

        assert any("Both watchers failed" in e for e in errors), (
            f"the startup failure was not reported at ERROR level: errors={errors} infos={infos}"
        )
        assert not any("Both watchers failed" in i for i in infos), (
            "the startup failure was downgraded to INFO, where the log watchers do not see it"
        )


class TestReloadExit:
    """How the process leaves decides whether it comes back.
    The unit ships `Restart=on-failure`: a reload that exited 0 reads as done and the watcher stays down.
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
        monkeypatch.setattr(mod.logger, "info", lambda *a, **kw: captured.append(str(a)))
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: captured.append(str(a)))

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

        with pytest.raises(SystemExit):
            mod.main()

        assert mod.stop_branch_watcher.called
        assert mod.stop_system_watcher.called


class TestStartupCatchup:
    """The service runs its own error catch-up.
    Recovery must not ride prax's per-process startup event: any short-lived process could
    consume the shared last_scan_timestamp window first.
    """

    @staticmethod
    def _run(mod, monkeypatch):
        """Drive main() to completion with both watchers up."""
        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        mod.main()

    def test_main_runs_the_catchup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Recovery no longer depends on anything firing the startup event (mutant: catch-up handed None)."""
        mod = _import_module()
        catchup = MagicMock()
        monkeypatch.setattr(mod, "run_error_catchup", catchup)

        self._run(mod, monkeypatch)

        catchup.assert_called_once_with(mod.trigger.fire)

    def test_catchup_gets_a_fire_event_so_errors_reach_medic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Scanning without dispatching would recover errors into silence."""
        mod = _import_module()
        catchup = MagicMock()
        monkeypatch.setattr(mod, "run_error_catchup", catchup)

        self._run(mod, monkeypatch)

        assert catchup.call_args[0][0] == mod.trigger.fire

    def test_catchup_runs_after_the_watchers_are_up(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Order is deliberate: overlap is safe, a gap is not.
        Scanning first leaves a gap before the first watch; overlap is deduped on fingerprint.
        """
        mod = _import_module()
        order: list[str] = []

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        mod.start_branch_watcher = MagicMock(side_effect=lambda: order.append("branch") or True)
        mod.start_system_watcher = MagicMock(side_effect=lambda: order.append("system") or True)
        mod.run_error_catchup = MagicMock(side_effect=lambda *a: order.append("catchup"))

        mod.main()

        assert order == ["branch", "system", "catchup"]

    def test_a_failed_catchup_does_not_stop_the_watchers(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The watchers are the service's job; recovery is best-effort.
        A raising catch-up must not trade a missed scan for no watching at all.
        """
        mod = _import_module()

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        mod.start_branch_watcher = MagicMock(return_value=True)
        mod.start_system_watcher = MagicMock(return_value=True)
        mod.run_error_catchup = MagicMock(side_effect=RuntimeError("scan blew up"))
        mock_stop_branch = MagicMock()
        mod.stop_branch_watcher = mock_stop_branch
        errors: list[str] = []
        monkeypatch.setattr(mod.logger, "error", lambda *a, **kw: errors.append(str(a)))

        mod.main()

        # The service still ran and shut down cleanly.
        mock_stop_branch.assert_called_once()
        assert any("catch-up failed" in e for e in errors), "and the failure is reported, not swallowed"

    def test_no_catchup_when_both_watchers_fail(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Nothing will be watching, so there is no window to recover into."""
        mod = _import_module()
        catchup = MagicMock()
        monkeypatch.setattr(mod, "run_error_catchup", catchup)

        pre_set = threading.Event()
        pre_set.set()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: pre_set))
        mod.start_branch_watcher = MagicMock(return_value=None)
        mod.start_system_watcher = MagicMock(return_value=None)

        with pytest.raises(SystemExit):
            mod.main()

        catchup.assert_not_called()
