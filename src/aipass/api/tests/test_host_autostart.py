#!/usr/bin/env python3
# =================== AIPass ====================
# Name: test_host_autostart.py
# Description: Tests for the supervisor seam — a server that comes back on its own
# =============================================

"""
Tests for the Host API Autostart Lane

On 2026-08-27 @baud's phone face went dark. host_api_serve.log showed normal
traffic and then silence — no traceback, no shutdown line, which is what a
reboot looks like from inside a log. A detached server dies with the machine and
nothing brought it back.

WHAT THESE TESTS GUARD MOST CAREFULLY are the two promises that make handing the
server to systemd safe rather than merely automatic, because both fail SILENTLY:

    status must not lie. A unit-managed server writes no record file, so the old
    running() would have called a healthy server absent — at exactly the moment
    an operator needs the opposite.

    stop must not be a trap. Signalling a supervised pid directly leaves the
    restart policy free to undo it, so the command prints success and the server
    is back before anyone finishes reading.

And one that fails silently in systemd itself: StartLimitIntervalSec/Burst moved
from [Service] to [Unit] in v230, and the old spelling is not an error — it is
IGNORED. A rate limit in the wrong section is an absence wearing a config's
clothes.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import autostart as host_autostart
from aipass.api.apps.handlers.host import lifetime as host_lifetime


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real logging or operation records out of a unit test."""
    monkeypatch.setattr(host_autostart, "logger", MagicMock())
    monkeypatch.setattr(host_lifetime, "logger", MagicMock())
    monkeypatch.setattr(host_lifetime, "json_handler", MagicMock())


def _completed(stdout: str = "", returncode: int = 0) -> MagicMock:
    result = MagicMock()
    result.stdout = stdout
    result.stderr = ""
    result.returncode = returncode
    return result


# =============================================
# THE UNIT FILE
# =============================================


class TestTheUnitSaysWhatItMeans:
    """
    The unit is written once and then read by systemd forever, unwatched.

    Every one of these is a line whose absence is not an error — it is a
    behaviour that quietly does not happen.
    """

    def test_the_rate_limit_is_in_unit_not_service(self) -> None:
        """
        systemd moved StartLimit* to [Unit] in v230 and IGNORES it in [Service].

        The wrong section does not fail to parse. It parses fine and the limit
        is simply not there, which is the difference between a server that gives
        up after ten minutes of impossible binds and one that retries forever
        into a growing log.
        """
        text = host_autostart.unit_text(["/py", "/app.py"], Path("/branch"), Path("/branch/logs/x.log"))

        unit_section = text.split("[Service]")[0]
        service_section = text.split("[Service]")[1]

        assert "StartLimitIntervalSec" in unit_section
        assert "StartLimitBurst" in unit_section
        assert "StartLimitIntervalSec" not in service_section
        assert "StartLimitBurst" not in service_section

    def test_both_streams_append_to_the_one_log(self) -> None:
        """
        Requirement three, and the reason this morning was diagnosable at all.

        `append:` rather than `file:` — file: TRUNCATES on every start, so the
        first restart after an outage would destroy the evidence of the outage.
        """
        log = Path("/branch/logs/host_api_serve.log")
        text = host_autostart.unit_text(["/py", "/app.py"], Path("/branch"), log)

        assert f"StandardOutput=append:{log}" in text
        assert f"StandardError=append:{log}" in text
        # Scoped to the stream directives: Documentation= legitimately carries a
        # file:// URL, and a bare "file:" search would have matched THAT and
        # called a correct unit broken.
        assert "StandardOutput=file:" not in text
        assert "StandardError=file:" not in text

    def test_the_unit_starts_the_server_the_same_way_a_detach_does(self) -> None:
        """
        One spelling of how this server starts, or the two drift.

        The unit's copy is the one nobody re-reads: it lives under somebody's
        home directory where this tree cannot see it.
        """
        argv = host_lifetime.serve_argv("10.0.0.1", 8787)
        text = host_autostart.unit_text(argv, Path("/branch"), Path("/log"))

        assert f"ExecStart={' '.join(argv)}" in text

    def test_a_crash_restarts_and_a_clean_exit_does_not(self) -> None:
        """
        on-failure, never always.

        `always` would restart a server that exited cleanly because its bind was
        refused, turning a clear refusal into a spin.
        """
        text = host_autostart.unit_text(["/py"], Path("/branch"), Path("/log"))

        assert "Restart=on-failure" in text
        assert "Restart=always" not in text

    def test_the_supervisor_gives_a_shutdown_longer_than_this_branch_waits(self) -> None:
        """
        A stop wait shorter than the supervisor's own budget reports a false hang.

        lifetime waits autostart.STOP_TIMEOUT_SECONDS for a supervised stop, and
        that has to outlast the TimeoutStopSec written into the unit, or the
        operator is sent looking for a hang that is a graceful shutdown halfway
        through.
        """
        assert host_autostart.STOP_TIMEOUT_SECONDS > host_autostart.TIMEOUT_STOP_SECONDS


# =============================================
# ASKING THE SUPERVISOR
# =============================================


class TestTheProbeAnswersAbsenceAndFailureDifferently:
    """
    `show -p MainPID` rather than `is-active`, and this is why.

    is-active exits non-zero for "inactive" AND for "no such unit" AND for a
    real failure to run, so a caller reading the exit code cannot tell no from
    could-not-ask.
    """

    def test_no_unit_is_zero_not_an_error(self, quiet: None) -> None:
        """An uninstalled unit answers MainPID=0 with a successful exit."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("0\n")):
            assert host_autostart.supervised_pid() == 0

    def test_a_live_unit_reports_its_pid(self, quiet: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("4242\n")):
            assert host_autostart.supervised_pid() == 4242

    def test_an_unreadable_pid_is_zero_and_never_raises(self, quiet: None) -> None:
        """
        Garbage from a probe is a not-supervised answer, not a traceback.

        status is the command an operator runs when things are already strange;
        it does not get to be the second strange thing.
        """
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("banana")):
            assert host_autostart.supervised_pid() == 0

    def test_a_negative_pid_is_zero_because_the_contract_says_zero(self, quiet: None) -> None:
        """
        Found by a mutation that SURVIVED: dropping the `> 0` guard changed
        nothing any test could see, because systemd never emits a negative
        MainPID and every test fed it a realistic one.

        The guard stays and gets pinned rather than being deleted as dead code.
        This function's whole job is a clean yes-or-no — running() treats any
        truthy pid as "supervised", and a caller that trusted the documented
        "or 0" would be handed a number that is neither a pid nor an absence.
        """
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("-1")):
            assert host_autostart.supervised_pid() == 0

    def test_a_probe_that_cannot_run_is_zero(self, quiet: None) -> None:
        with patch.object(host_autostart.subprocess, "run", side_effect=OSError("no systemctl")):
            assert host_autostart.supervised_pid() == 0

    def test_a_probe_that_times_out_is_zero(self, quiet: None) -> None:
        """A hung supervisor must not hang the command asking about it."""
        timeout = host_autostart.subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

        with patch.object(host_autostart.subprocess, "run", side_effect=timeout):
            assert host_autostart.supervised_pid() == 0

    def test_a_platform_without_systemd_never_shells_out(self, quiet: None) -> None:
        """
        The Windows lesson, applied before the bug rather than after.

        `--detach` shipped start_new_session, which Windows accepts and silently
        ignores — reporting success while detaching nothing. Here the platform
        gate comes FIRST, so nothing is run and nothing can pretend.
        """
        with patch.object(host_autostart.sys, "platform", "win32"):
            with patch.object(host_autostart.subprocess, "run") as run:
                assert host_autostart.supervised_pid() == 0
                assert host_autostart.is_supported() is False
                run.assert_not_called()


class TestTheBindIsReadFromTheUnitNotTheConfig:
    """
    The unit pins its bind at install time; set-config afterwards changes what
    the NEXT install would use and nothing about the process listening now.
    """

    def test_the_bind_comes_out_of_execstart(self, quiet: None) -> None:
        exec_start = "{ path=/py ; argv[]=/py /app.py host-api serve --host 10.9.8.7 --port 9001 ; ignore_errors=no }"

        with patch.object(host_autostart.subprocess, "run", return_value=_completed(exec_start)):
            assert host_autostart.supervised_bind() == ("10.9.8.7", 9001)

    def test_an_unreadable_execstart_is_unknown_never_guessed(self, quiet: None) -> None:
        """
        A status line that invents a port is worse than one that says unknown.

        It would be confidently wrong exactly once — after somebody changes the
        port and before they reinstall — which is the worst possible time.
        """
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("")):
            assert host_autostart.supervised_bind() == (None, None)

    def test_a_non_numeric_port_does_not_raise(self, quiet: None) -> None:
        exec_start = "argv[]=/py /app.py host-api serve --host 10.0.0.1 --port eighty"

        with patch.object(host_autostart.subprocess, "run", return_value=_completed(exec_start)):
            assert host_autostart.supervised_bind() == ("10.0.0.1", None)


class TestStoppingGoesThroughTheSupervisor:
    """`systemctl stop` outranks Restart= by definition. A signal does not."""

    def test_a_refused_stop_is_false_not_an_exception(self, quiet: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed(returncode=1)):
            assert host_autostart.stop_unit() is False

    def test_an_accepted_stop_is_true(self, quiet: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed()):
            assert host_autostart.stop_unit() is True

    def test_a_platform_without_systemd_refuses_rather_than_pretends(self, quiet: None) -> None:
        with patch.object(host_autostart.sys, "platform", "win32"):
            with pytest.raises(host_autostart.AutostartUnsupported):
                host_autostart.stop_unit()


class TestTheInstallStepsAreOrderedAndOutsideTheTree:
    """Installing means writing under a home directory — theirs to run, not mine."""

    def test_the_unit_is_copied_before_it_is_enabled(self) -> None:
        steps = host_autostart.install_commands(Path("/branch/logs/u.service"))
        joined = " || ".join(steps)

        assert joined.index("cp ") < joined.index("daemon-reload") < joined.index("enable --now")

    def test_lingering_is_part_of_the_instructions(self) -> None:
        """
        Without it a user unit waits for a login, which a headless reboot never
        provides — the exact failure this build exists to end.
        """
        assert any("enable-linger" in step for step in host_autostart.install_commands(Path("/u")))
