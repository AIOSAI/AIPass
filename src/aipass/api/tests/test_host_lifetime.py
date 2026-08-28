#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_lifetime.py
# Description: Tests for a serve that outlives the shell that started it
# =============================================

"""
Tests for the Host API Lifetime Lane

A `host-api serve` routed through drone is a child of drone's exec timeout.
@baud read the tailnet server's pane on 2026-08-19 and found fourteen cycles of
"timed out after 43200s" followed by "restarting in 2s" — and the churn cost
more than the downtime, because uvicorn's access log goes to stdout, stdout was
that pane, and a day of history scrolled out of a bounded scrollback. By evening
nobody could answer which bundle a phone had pulled.

The two halves are one defect: a server with nowhere to write has no history,
and a server held open by a caller cannot outlive that caller's patience.

WHAT THESE TESTS GUARD MOST CAREFULLY is the pair of promises that make
detaching safe rather than merely convenient — the bind is validated BEFORE
anything is spawned, and the log is APPENDED to rather than truncated. Both are
one keyword in the implementation and both fail silently if that keyword goes.
"""

import json
import os
import signal
import subprocess
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import autostart as host_autostart
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import lifetime as host_lifetime


@pytest.fixture
def runtime(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """
    A throwaway runtime directory, so no test touches the real logs/.

    THE SUPERVISOR IS ANSWERED "no" BY DEFAULT, added 2026-08-27 with the
    autostart lane. running() now asks systemd before it reads the record file,
    so without this every test in this file would shell out to the real
    systemctl and — on a host where the unit IS installed and running — would
    get a live pid back and fail for a reason that has nothing to do with it.
    A test whose result depends on whether the machine it runs on happens to be
    serving is not a test.
    """
    monkeypatch.setattr(host_lifetime, "_runtime_dir", lambda: tmp_path)
    monkeypatch.setattr(host_lifetime, "json_handler", MagicMock())
    monkeypatch.setattr(host_lifetime, "logger", MagicMock())
    monkeypatch.setattr(host_lifetime, "SETTLE_SECONDS", 0.0)
    monkeypatch.setattr(host_autostart, "supervised_pid", lambda: 0)
    return tmp_path


@pytest.fixture
def supervised(monkeypatch: pytest.MonkeyPatch) -> int:
    """A systemd unit that is holding the server, on pid 5150."""
    monkeypatch.setattr(host_autostart, "supervised_pid", lambda: 5150)
    monkeypatch.setattr(host_autostart, "supervised_bind", lambda: ("10.0.0.9", 8787))
    monkeypatch.setattr(host_lifetime, "_alive", lambda pid: pid == 5150)
    return 5150


@pytest.fixture
def bind_ok(monkeypatch: pytest.MonkeyPatch) -> None:
    """A stored config and a bind gate that says yes."""
    monkeypatch.setattr(host_config, "load_config", lambda: {"host": "127.0.0.1", "port": 8790})
    monkeypatch.setattr(host_config, "validate_bind", lambda host, port: None)


def _spawned(pid: int = 4242, poll: Any = None) -> Any:
    child = MagicMock()
    child.pid = pid
    child.poll.return_value = poll
    child.returncode = poll
    return child


class TestTheBindIsCheckedBeforeAnythingIsSpawned:
    """
    D1 holds across the detach seam, and this is where it would quietly stop.

    A refused address must never reach a listener. Validating inside the
    detached child would technically satisfy that — the child would refuse and
    die — but the operator who typed the command would see a success, and the
    refusal would be a line in a log file they have no reason to open. A
    refusal nobody reads is not a refusal.
    """

    def test_a_refused_bind_spawns_nothing(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The load-bearing one: no process, not even a short-lived one."""
        monkeypatch.setattr(host_config, "load_config", lambda: {"host": "0.0.0.0", "port": 8790})
        monkeypatch.setattr(
            host_config,
            "validate_bind",
            MagicMock(side_effect=host_config.BindRefused("wildcards are refused")),
        )

        with patch.object(subprocess, "Popen") as popen:
            with pytest.raises(host_config.BindRefused):
                host_lifetime.serve_detached()

        popen.assert_not_called()
        assert not host_lifetime.record_path().exists()

    def test_the_refusal_is_the_operators_to_read(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """It surfaces as an exception here, not as a line in a log file."""
        monkeypatch.setattr(host_config, "load_config", lambda: {"host": "0.0.0.0", "port": 8790})
        monkeypatch.setattr(
            host_config,
            "validate_bind",
            MagicMock(side_effect=host_config.BindRefused("this machine has no such address")),
        )

        with patch.object(subprocess, "Popen"):
            with pytest.raises(host_config.BindRefused) as refusal:
                host_lifetime.serve_detached()

        assert "no such address" in str(refusal.value)


class TestTheChildIsGenuinelyDetached:
    """
    The mechanism, asked of the call rather than assumed from the docstring.

    Without a new session the child stays in the process group drone is timing,
    which is the entire bug — the server would still die at twelve hours and
    these tests would still pass on every other assertion.
    """

    def test_the_child_gets_its_own_session(self, runtime: Path, bind_ok: None) -> None:
        """One keyword, and the whole fix is it — SPELLED PER PLATFORM.

        start_new_session is POSIX-only. Popen accepts it on Windows and
        silently does nothing, which is the worst failure this flag could have:
        `--detach` would report success and the server would still die with
        whatever timed out its parent. seedgo's Windows check caught that, not
        a test — so this asserts the spelling that is actually load-bearing
        HERE rather than the one that happens to be in the source.
        """
        with patch.object(subprocess, "Popen", return_value=_spawned()) as popen:
            host_lifetime.serve_detached()

        handed = popen.call_args.kwargs

        if sys.platform == "win32":
            detached_process = 0x00000008
            create_new_process_group = 0x00000200
            assert handed["creationflags"] & detached_process
            assert handed["creationflags"] & create_new_process_group
            assert "start_new_session" not in handed, "a POSIX no-op was passed on Windows"
        else:
            assert handed["start_new_session"] is True
            assert "creationflags" not in handed

    def test_the_detach_keywords_are_never_empty(self, runtime: Path, bind_ok: None) -> None:
        """Vacuity floor for the branch above.

        A _detach_kwargs() that returned {} would make the platform assertions
        the only thing standing between this and a server that is not detached
        at all — and on the untested platform, nothing would stand there.
        """
        assert host_lifetime._detach_kwargs(), "nothing detaches the child on this platform"

    def test_the_child_never_shares_the_callers_stdin(self, runtime: Path, bind_ok: None) -> None:
        """A detached server reading a closed terminal is a server that stalls."""
        with patch.object(subprocess, "Popen", return_value=_spawned()) as popen:
            host_lifetime.serve_detached()

        assert popen.call_args.kwargs["stdin"] is subprocess.DEVNULL

    def test_stderr_lands_in_the_same_file_as_stdout(self, runtime: Path, bind_ok: None) -> None:
        """A traceback that goes somewhere else is a traceback nobody correlates."""
        with patch.object(subprocess, "Popen", return_value=_spawned()) as popen:
            host_lifetime.serve_detached()

        assert popen.call_args.kwargs["stderr"] is subprocess.STDOUT

    def test_the_command_carries_the_resolved_bind_not_the_defaults(self, runtime: Path, bind_ok: None) -> None:
        """The child must serve what the parent validated, not re-decide it.

        If the child re-read the config it could bind something the gate never
        saw — the same class of hole as validating inside the child.
        """
        with patch.object(subprocess, "Popen", return_value=_spawned()) as popen:
            host_lifetime.serve_detached(host="127.0.0.1", port=9001)

        command = popen.call_args.args[0]

        assert command[0] == sys.executable
        assert "--host" in command and command[command.index("--host") + 1] == "127.0.0.1"
        assert "--port" in command and command[command.index("--port") + 1] == "9001"


class TestTheLogSurvivesARestart:
    """
    The half that actually cost @baud an answer.

    Fourteen restarts destroyed a day of access history because the only copy
    lived in a pane's scrollback. Giving the server a file fixes that ONLY if
    the file is appended to — a truncating open would reproduce the same loss
    with extra steps, and would look completely fine in every other test here.
    """

    def test_earlier_output_is_not_truncated_by_a_new_server(self, runtime: Path, bind_ok: None) -> None:
        """The pin that would catch "w" replacing "a"."""
        host_lifetime.log_path().write_text("a request from this morning\n", encoding="utf-8")

        with patch.object(subprocess, "Popen", return_value=_spawned()):
            host_lifetime.serve_detached()

        assert "this morning" in host_lifetime.log_path().read_text(encoding="utf-8")

    def test_the_child_writes_to_that_file(self, runtime: Path, bind_ok: None) -> None:
        """Opened for the child, not merely created beside it."""
        with patch.object(subprocess, "Popen", return_value=_spawned()) as popen:
            host_lifetime.serve_detached()

        handed = popen.call_args.kwargs["stdout"]

        assert Path(handed.name) == host_lifetime.log_path()

    def test_the_record_says_where_the_log_is(self, runtime: Path, bind_ok: None) -> None:
        """An operator should never have to guess, or read this source."""
        with patch.object(subprocess, "Popen", return_value=_spawned()):
            record = host_lifetime.serve_detached()

        assert record["log"] == str(host_lifetime.log_path())


class TestAServerThatDiedOnStartIsNotReportedAsRunning:
    """A launcher that reports success for a corpse is worse than no launcher."""

    def test_an_immediate_exit_is_raised_not_recorded(self, runtime: Path, bind_ok: None) -> None:
        """The child is asked whether it is still there before anything is written."""
        with patch.object(subprocess, "Popen", return_value=_spawned(poll=1)):
            with pytest.raises(host_lifetime.LifetimeError) as failure:
                host_lifetime.serve_detached()

        assert not host_lifetime.record_path().exists(), "a dead server left a record claiming it is alive"
        assert str(host_lifetime.log_path()) in str(failure.value), "the failure did not say where to read why"


class TestFindingTheRunningServer:
    """`status` has to answer from reality, not from a file somebody left behind."""

    def test_no_record_means_no_server(self, runtime: Path) -> None:
        """The ordinary case, and it must not raise."""
        assert host_lifetime.running() is None

    def test_a_record_naming_a_dead_process_is_not_a_server(self, runtime: Path) -> None:
        """A reboot leaves one of these. It is not a fault to clear by hand."""
        host_lifetime.record_path().write_text(json.dumps({"pid": 999999999}), encoding="utf-8")

        assert host_lifetime.running() is None

    def test_a_live_record_is_returned(self, runtime: Path) -> None:
        """This process is alive by construction, which makes it a safe stand-in."""
        host_lifetime.record_path().write_text(
            json.dumps({"pid": os.getpid(), "host": "127.0.0.1", "port": 8790}), encoding="utf-8"
        )

        record = host_lifetime.running()

        assert record is not None
        assert record["port"] == 8790

    def test_an_unreadable_record_is_not_a_crash(self, runtime: Path) -> None:
        """Half a JSON file is a state, not an exception for `status` to raise."""
        host_lifetime.record_path().write_text("{ not json", encoding="utf-8")

        assert host_lifetime.running() is None

    def test_a_second_serve_is_refused_while_one_is_running(self, runtime: Path, bind_ok: None) -> None:
        """Two servers on one port is a race whose loser dies silently."""
        host_lifetime.record_path().write_text(json.dumps({"pid": os.getpid()}), encoding="utf-8")

        with patch.object(subprocess, "Popen") as popen:
            with pytest.raises(host_lifetime.LifetimeError) as refusal:
                host_lifetime.serve_detached()

        popen.assert_not_called()
        assert "already running" in str(refusal.value)


@pytest.mark.skipif(sys.platform == "win32", reason="zombies and os.kill(pid, 0) are POSIX")
class TestADeadChildIsDead:
    """
    The defect the first LIVE start/stop found, on 2026-08-19.

    Every test above mocks os.kill, so every one of them was green while stop()
    was broken. A real detached server shut down cleanly — its log says
    "Finished server process" — and stop() waited the full ten seconds and then
    reported that the server would not go.

    The reason is that a process which has exited but has not been REAPED still
    holds a pid entry, so os.kill(pid, 0) answers yes to a corpse. It only
    bites when the caller is the server's own parent, which is why no mocked
    test could see it and why a real one had to.

    This uses a real process for exactly that reason. It is the only test here
    that could have caught it.
    """

    def test_a_reaped_child_is_not_reported_alive(self) -> None:
        """The pin. Without the reap in _alive, this hangs on a zombie forever."""
        child = subprocess.Popen([sys.executable, "-c", "pass"])
        child.wait()

        # Deliberately NOT calling child.poll() again — Popen.wait() has already
        # reaped it, so this is the easy half and only proves the floor.
        assert host_lifetime._alive(child.pid) is False

    def test_an_unreaped_child_is_not_reported_alive_either(self) -> None:
        """The real case: nobody has waited on it, so the zombie is still there.

        This is the exact situation stop() is in when it runs in the process
        that spawned the server.
        """
        child = subprocess.Popen([sys.executable, "-c", "pass"])

        # Wait for it to exit WITHOUT reaping it, the way a caller polling
        # _alive would. os.waitid with WNOWAIT leaves the zombie in place.
        os.waitid(os.P_PID, child.pid, os.WEXITED | os.WNOWAIT)

        try:
            assert host_lifetime._alive(child.pid) is False, "a zombie was reported as a running server"
        finally:
            child.wait()

    def test_a_process_that_is_genuinely_running_is_reported_alive(self) -> None:
        """Vacuity floor: an _alive that always said False would pass the above."""
        assert host_lifetime._alive(os.getpid()) is True


@pytest.mark.skipif(sys.platform == "win32", reason="SIGTERM and os.kill(pid, 0) are POSIX")
class TestStopping:
    """Asked to leave, never shot — and the record is cleared either way."""

    def test_stopping_nothing_is_not_an_error(self, runtime: Path) -> None:
        """`stop` twice must be safe; the second one has nothing to do."""
        assert host_lifetime.stop() is None

    def test_a_stale_record_is_cleared_rather_than_reported(self, runtime: Path) -> None:
        """Otherwise a ghost refuses every future serve."""
        host_lifetime.record_path().write_text(json.dumps({"pid": 999999999}), encoding="utf-8")

        assert host_lifetime.stop() is None
        assert not host_lifetime.record_path().exists()

    def test_the_server_is_asked_to_exit_not_killed(self, runtime: Path) -> None:
        """SIGTERM, so uvicorn gets to finish its shutdown.

        SIGKILL would cut that short, and this handler does not get to decide
        that a server taking its time is a server that has hung.
        """
        alive = [True]
        host_lifetime.record_path().write_text(json.dumps({"pid": 4242}), encoding="utf-8")

        def _signalled(pid: int, sig: int) -> None:
            if sig == 0:
                if alive[0]:
                    return
                raise ProcessLookupError()
            alive[0] = False

        with patch.object(os, "kill", side_effect=_signalled) as killed:
            record = host_lifetime.stop()

        assert record is not None
        assert signal.SIGTERM in [call.args[1] for call in killed.call_args_list]
        assert not hasattr(signal, "SIGKILL") or signal.SIGKILL not in [
            call.args[1] for call in killed.call_args_list
        ], "a graceful shutdown was cut short"
        assert not host_lifetime.record_path().exists()

    def test_a_server_that_will_not_go_is_said_out_loud(
        self,
        runtime: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Never silently escalated, and never silently given up on.

        Time is driven rather than slept — a real ten-second wait in a suite is
        not a test, it is a delay.
        """
        monkeypatch.setattr(host_lifetime, "STOP_POLL_SECONDS", 0.0)
        host_lifetime.record_path().write_text(json.dumps({"pid": 4242}), encoding="utf-8")

        clock = [1000.0]
        monkeypatch.setattr(host_lifetime.time, "monotonic", lambda: clock[0])

        def _never_dies(pid: int, sig: int) -> None:
            clock[0] += 1.0

        with patch.object(os, "kill", side_effect=_never_dies):
            with pytest.raises(host_lifetime.LifetimeError) as failure:
                host_lifetime.stop()

        assert "did not exit" in str(failure.value)
        assert host_lifetime.record_path().exists(), "the record was cleared for a server still running"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


class TestStatusTellsTheTruthAboutAServerItDidNotStart:
    """
    Requirement four of the autostart ruling, and the reason it is a
    requirement: a unit-managed server writes no record file, so the lane that
    only ever read that file called a perfectly healthy server absent.

    This is the failure mode that costs an operator an hour at 3am — the command
    you run to find out whether it is up, telling you the opposite of the truth.
    """

    def test_a_supervised_server_is_reported_running(self, runtime: Path, supervised: int) -> None:
        record = host_lifetime.running()

        assert record is not None
        assert record["pid"] == supervised
        assert record["owner"] == host_lifetime.OWNER_SUPERVISOR
        assert record["unit"] == host_autostart.unit_name()

    def test_the_supervisor_outranks_a_stale_record_from_before_the_reboot(
        self, runtime: Path, supervised: int
    ) -> None:
        """
        A reboot leaves a record naming a pid that is gone, and the unit then
        starts the real server. Reading the file first would answer with the
        dead pid while a healthy server listened on the same port.
        """
        host_lifetime.record_path().write_text(json.dumps({"pid": 999, "host": "127.0.0.1", "port": 1}))

        record = host_lifetime.running()

        assert record["pid"] == supervised
        assert record["owner"] == host_lifetime.OWNER_SUPERVISOR

    def test_a_hand_started_server_is_still_named_as_such(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """The detached path keeps working and now says what it is."""
        host_lifetime.record_path().write_text(json.dumps({"pid": 321, "host": "127.0.0.1", "port": 8787}))
        monkeypatch.setattr(host_lifetime, "_alive", lambda pid: True)

        record = host_lifetime.running()

        assert record["owner"] == host_lifetime.OWNER_DETACHED

    def test_no_supervisor_and_no_record_is_still_none(self, runtime: Path) -> None:
        assert host_lifetime.running() is None


class TestStoppingASupervisedServerIsNotATrap:
    """
    Requirement five. Signalling a supervised pid directly leaves the restart
    policy free to start it again — the command prints success and the server is
    back before the operator finishes reading it.

    A stop that undoes itself is worse than a stop that refuses, because the
    operator walks away.
    """

    def test_the_supervisor_is_asked_and_the_pid_is_never_signalled(
        self, runtime: Path, supervised: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gone = {"yet": False}
        monkeypatch.setattr(host_lifetime, "_alive", lambda pid: not gone["yet"])

        def accept() -> bool:
            gone["yet"] = True
            return True

        monkeypatch.setattr(host_autostart, "stop_unit", accept)

        with patch.object(host_lifetime.os, "kill") as kill:
            record = host_lifetime.stop()

        assert record["owner"] == host_lifetime.OWNER_SUPERVISOR
        kill.assert_not_called()

    def test_a_refused_stop_is_reported_rather_than_forced(
        self, runtime: Path, supervised: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(host_autostart, "stop_unit", lambda: False)

        with pytest.raises(host_lifetime.LifetimeError, match="would not stop"):
            host_lifetime.stop()

    def test_an_accepted_stop_whose_process_stays_is_not_reported_as_success(
        self, runtime: Path, supervised: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The supervisor ACCEPTING a stop and the process being gone are two
        facts. This branch has already been caught once believing the first
        implies the second — os.kill(pid, 0) answering yes to an unreaped
        corpse, found by running the thing for real rather than by a mock.
        """
        monkeypatch.setattr(host_autostart, "stop_unit", lambda: True)
        monkeypatch.setattr(host_autostart, "STOP_TIMEOUT_SECONDS", 0.0)

        with pytest.raises(host_lifetime.LifetimeError, match="still running"):
            host_lifetime.stop()

    def test_a_detached_server_is_still_stopped_by_signal(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """No regression: the hand-started path did not change."""
        host_lifetime.record_path().write_text(json.dumps({"pid": 321, "host": "127.0.0.1", "port": 8787}))
        alive = {"still": True}
        monkeypatch.setattr(host_lifetime, "_alive", lambda pid: alive["still"])

        def signalled(pid: int, sig: int) -> None:
            alive["still"] = False

        with patch.object(host_lifetime.os, "kill", side_effect=signalled) as kill:
            record = host_lifetime.stop()

        assert record["owner"] == host_lifetime.OWNER_DETACHED
        kill.assert_called_once_with(321, signal.SIGTERM)


class TestTheUnitIsWrittenOnlyForAnAddressThatCleared:
    """
    D1 reaches the unit too, and this is the one place it matters most: a unit
    is a spawn that repeats at every boot with nobody watching. An address
    refused at the CLI and then baked into one is D1 holding everywhere except
    forever.
    """

    def test_a_refused_bind_writes_nothing(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_config, "load_config", lambda: {"host": "0.0.0.0", "port": 8787})
        monkeypatch.setattr(host_config, "validate_bind", MagicMock(side_effect=host_config.BindRefused("wildcard")))
        monkeypatch.setattr(host_autostart, "is_supported", lambda: True)

        with pytest.raises(host_config.BindRefused):
            host_lifetime.write_unit()

        assert not host_lifetime.unit_path().exists()

    def test_a_platform_without_systemd_writes_nothing(self, runtime: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(host_autostart, "is_supported", lambda: False)

        with pytest.raises(host_autostart.AutostartUnsupported):
            host_lifetime.write_unit()

        assert not host_lifetime.unit_path().exists()

    def test_the_written_unit_carries_the_cleared_address(
        self, runtime: Path, bind_ok: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(host_autostart, "is_supported", lambda: True)

        written = host_lifetime.write_unit()

        assert "--host 127.0.0.1 --port 8790" in written.read_text()


class TestTwoServersAreNeverStartedByAccident:
    """A supervised server and a detached one would fight over one port."""

    def test_a_detach_is_refused_while_the_supervisor_holds_it(
        self, runtime: Path, bind_ok: None, supervised: int
    ) -> None:
        """
        And the refusal NAMES the supervisor, because the two cases need
        different commands from the operator: a supervised server signalled by
        hand comes straight back, so "already running" alone sends them to the
        wrong one.
        """
        with pytest.raises(host_lifetime.LifetimeError, match="supervisor"):
            host_lifetime.serve_detached()


class TestAnUnreachableSupervisorIsNeverReportedAsAnEmptyOne:
    """
    The 2026-08-27 ruling, at the three places that act on it.

    A probe that failed on a machine that HAS systemd leaves the question
    unanswered. Flattening that to None would be the original defect one layer
    down: the tailnet unit writes no record file, so every caller would take the
    record path and conclude that nothing is running.
    """

    def test_running_refuses_rather_than_reporting_no_server(
        self, runtime: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        with pytest.raises(host_autostart.SupervisorUnreachable):
            host_lifetime.running()

    def test_a_stale_record_cannot_stand_in_for_an_unanswered_probe(
        self, runtime: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The trap this closes: a record left over from before the unit was
        installed is still on disk. Swallowing the refusal would report THAT
        pid — a hand-started server that has not existed since this morning.
        """
        host_lifetime.record_path().write_text(json.dumps({"pid": 177102, "host": "10.0.0.1", "port": 8787}))

        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        with pytest.raises(host_autostart.SupervisorUnreachable):
            host_lifetime.running()

    def test_nothing_is_spawned_while_the_supervisor_is_unreadable(
        self, runtime: Path, bind_ok: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        A second listener started blind is how one port gets two servers and a
        log that cannot say which of them wrote a line.
        """
        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        with patch.object(host_lifetime.subprocess, "Popen") as popen:
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_lifetime.serve_detached()

        popen.assert_not_called()

    def test_no_signal_is_sent_into_the_dark(
        self, runtime: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        If a unit IS holding the server, a bare SIGTERM is a stop its restart
        policy may undo — so an unanswered probe must refuse, not guess.
        """
        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        with patch.object(host_lifetime.os, "kill") as kill:
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_lifetime.stop()

        kill.assert_not_called()

    def test_a_platform_without_systemd_still_reads_its_detached_record(
        self, runtime: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The ruling's other half, at the caller: zero is not a refusal, so a
        machine with no systemd still finds a hand-started server exactly as it
        did before any of this existed.
        """
        host_lifetime.record_path().write_text(json.dumps({"pid": 321, "host": "127.0.0.1", "port": 8787}))
        monkeypatch.setattr(host_autostart, "supervised_pid", lambda: 0)
        monkeypatch.setattr(host_lifetime, "_alive", lambda pid: True)

        record = host_lifetime.running()

        assert record["owner"] == host_lifetime.OWNER_DETACHED


class TestTheStatusLaneGetsAThirdAnswer:
    """
    running() raises when the supervisor cannot be asked, which is right for
    stop and serve — both must refuse rather than act blind. Status is the one
    caller whose whole job is to report a state, and "I cannot tell" IS a state.
    """

    def test_an_unreachable_supervisor_is_unknown_not_none(
        self, runtime: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        answer = host_lifetime.server_state()

        assert answer["state"] == "unknown"
        assert answer["record"] is None
        assert "did not answer" in answer["reason"]

    def test_unknown_is_not_the_same_as_nothing_running(self, runtime: Path) -> None:
        """
        The distinction the whole fix rests on. Both print differently and one
        of them is a lie when the unit is live.
        """
        assert host_lifetime.server_state()["state"] == "none"

    def test_a_live_server_still_reports_running(self, runtime: Path, supervised: int) -> None:
        answer = host_lifetime.server_state()

        assert answer["state"] == "running"
        assert answer["record"]["pid"] == supervised


class TestTheInstallReportNamesAConflictItCanSee:
    """
    A hand-started server holding the port turns `enable --now` into a unit that
    cannot bind, burns its retry window and lands in `failed` — which reads as
    "autostart is broken" rather than as the real cause.
    """

    def test_a_detached_server_on_the_port_is_reported(
        self, runtime: Path, bind_ok: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(host_autostart, "is_supported", lambda: True)
        monkeypatch.setattr(host_autostart, "supervised_pid", lambda: 0)
        monkeypatch.setattr(host_autostart, "linger_enabled", lambda: True)
        monkeypatch.setattr(host_lifetime, "_alive", lambda pid: True)
        host_lifetime.record_path().write_text(json.dumps({"pid": 4242, "host": "127.0.0.1", "port": 8790}))

        report = host_lifetime.autostart_report()

        assert report["conflict"]["pid"] == 4242

    def test_a_supervised_server_is_not_a_conflict(
        self, runtime: Path, bind_ok: None, supervised: int, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        Reinstalling over a unit that is already running is normal — the
        supervisor restarts it. Only a HAND-started server is in the way.
        """
        monkeypatch.setattr(host_autostart, "is_supported", lambda: True)
        monkeypatch.setattr(host_autostart, "linger_enabled", lambda: True)

        report = host_lifetime.autostart_report()

        assert report["conflict"] is None

    def test_an_unreachable_supervisor_never_retracts_a_written_unit(
        self, runtime: Path, bind_ok: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        The conflict check is a courtesy and runs AFTER the write. Letting it
        raise would hand the operator a rendered unit plus an error saying it
        did not happen.
        """
        monkeypatch.setattr(host_autostart, "is_supported", lambda: True)
        monkeypatch.setattr(host_autostart, "linger_enabled", lambda: True)

        def unreachable() -> int:
            raise host_autostart.SupervisorUnreachable("systemctl did not answer")

        monkeypatch.setattr(host_autostart, "supervised_pid", unreachable)

        report = host_lifetime.autostart_report()

        assert report["conflict"] is None
        assert host_lifetime.unit_path().exists()
