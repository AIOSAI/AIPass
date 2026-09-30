# =================== AIPass ====================
# Name: test_log_watcher_service.py
# Description: Tests for the log watcher service entry point
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-09-27
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


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Patch every door main() opens onto the live watchers and the catch-up.

    The service binds its five collaborators by name at import, so they are
    replaced on the service module itself. monkeypatch records the real
    binding first, which also undoes the tests below that assign
    ``mod.start_branch_watcher = MagicMock(...)`` directly on the shared module.
    """
    # The real watchers arm watchdog observers over the LIVE log tree.
    monkeypatch.setattr(log_watcher_service, "start_branch_watcher", MagicMock(return_value=True))
    monkeypatch.setattr(log_watcher_service, "stop_branch_watcher", MagicMock())
    monkeypatch.setattr(log_watcher_service, "start_system_watcher", MagicMock(return_value=True))
    monkeypatch.setattr(log_watcher_service, "stop_system_watcher", MagicMock())

    # Stub the catch-up. main() now calls it for real (DPLAN-0339 step 2), and
    # the real one walks the LIVE system_logs and fires error_detected for
    # anything it finds — every main() test below would scan the tree and
    # dispatch other branches' errors through medic. The tests that care about
    # the call assert on this mock; trigger.fire is only handed to it, never
    # called.
    monkeypatch.setattr(log_watcher_service, "run_error_catchup", MagicMock())

    # The shell may be systemd-supervised: main() starts reload_sentinel,
    # whose evaluate() only acts under INVOCATION_ID.
    monkeypatch.delenv("INVOCATION_ID", raising=False)


def _import_module():
    """Hand each test the service module, its doors already patched."""
    return log_watcher_service


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

        # Use a real Event but do NOT pre-set it; we will trigger it via
        # the signal handler that main() installs.
        real_event = threading.Event()
        monkeypatch.setattr(mod, "threading", SimpleNamespace(Event=lambda: real_event))

        # main() runs on this thread and installs the real handlers. The
        # sentinel start is the product's own hook between installing them and
        # wait(): the handler main() installed is invoked there, so wait()
        # returns only if that handler set the event (else --timeout fails it).
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

        This used to assert on stderr. The five lifecycle print() calls became
        prax logger calls on 2026-08-31 (unstructured output invisible to the
        monitoring surface this process feeds), so the claim moved with the
        transport — and the LEVEL is now part of it, which stderr could not
        express: a failed startup is the one message here that is not INFO.
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
    """The service runs its own error catch-up (DPLAN-0339 step 2, part a).

    Before this, recovery reached this process only because prax's logger
    fires `startup` on the first log line of every process (logger.py:132).
    The one long-lived process that owns recovery got it as a side effect,
    exactly like a two-second drone command did — and since
    last_scan_timestamp is a single shared value, whichever short-lived
    process fired last had usually already consumed this service's window.
    Measured 2026-09-11: 0 of the last 100 catch-up runs found anything.
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

        An error arriving between the scan and the first watch would fall
        through if the scan ran first. Scanning after means the watcher may
        also see the line, which the registry dedupes on fingerprint.
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

        A raising catch-up used to be impossible here because there was no
        call. Now there is one, and it must not be able to take the process
        down on start — that would trade a missed scan for no watching at all.
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

        mock_stop_branch.assert_called_once(), "the service still ran and shut down cleanly"
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
