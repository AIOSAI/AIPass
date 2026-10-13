# =================== AIPass ====================
# Name: test_host_autostart.py
# Description: Tests for the supervisor seam — a server that comes back on its own
# Version: 1.1.0
# Created: 2026-08-27
# Modified: 2026-10-12
# =============================================

"""Tests for apps/handlers/host/autostart.py and the host-api autostart verb that drives it."""

# Tests for the Host API Autostart Lane
#
# On 2026-08-27 @baud's phone face went dark. host_api_serve.log showed normal
# traffic and then silence — no traceback, no shutdown line, which is what a
# reboot looks like from inside a log. A detached server dies with the machine and
# nothing brought it back.
#
# WHAT THESE TESTS GUARD MOST CAREFULLY are the two promises that make handing the
# server to systemd safe rather than merely automatic, because both fail SILENTLY:
#
#     status must not lie. A unit-managed server writes no record file, so the old
#     running() would have called a healthy server absent — at exactly the moment
#     an operator needs the opposite.
#
#     stop must not be a trap. Signalling a supervised pid directly leaves the
#     restart policy free to undo it, so the command prints success and the server
#     is back before anyone finishes reading.
#
# And one that fails silently in systemd itself: StartLimitIntervalSec/Burst moved
# from [Service] to [Unit] in v230, and the old spelling is not an error — it is
# IGNORED. A rate limit in the wrong section is an absence wearing a config's
# clothes.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that autostart.py parses and imports
# seedgo: no-test-needed(constant) — RESTART_SECONDS, START_LIMIT_INTERVAL_SECONDS and START_LIMIT_BURST's values
# seedgo: no-test-needed(external) — a real systemd; subprocess.run is scripted and is_supported pinned
# seedgo: no-test-needed(external) — linger_enabled's real loginctl query; it is patched where it is read

from pathlib import Path
from typing import Any, Iterator
from unittest.mock import MagicMock, patch

import pytest

from aipass.api.apps.handlers.host import autostart as host_autostart
from aipass.api.apps.handlers.host import config as host_config
from aipass.api.apps.handlers.host import lifetime as host_lifetime
from aipass.api.apps.modules import host_api as host_api_module
from aipass.api.apps.modules import host_serve as host_serve_module
from aipass.api.apps.modules.host_api import handle_command


@pytest.fixture
def quiet(monkeypatch: pytest.MonkeyPatch) -> None:
    """No real logging or operation records out of a unit test."""
    monkeypatch.setattr(host_autostart, "logger", MagicMock())
    monkeypatch.setattr(host_autostart, "json_handler", MagicMock())
    monkeypatch.setattr(host_lifetime, "logger", MagicMock())
    monkeypatch.setattr(host_lifetime, "json_handler", MagicMock())


@pytest.fixture
def has_systemd(quiet: None, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """
    A machine that HAS a user-level systemd, whatever machine this really is.

    WHY THIS EXISTS, and it is the whole of the 2026-08-27 CI red. Every test
    below patches subprocess.run to script what the supervisor says — but
    `_systemctl` asks `is_supported()` BEFORE it runs anything, so on the
    Windows runner the platform gate returned first and the mock was never
    reached. Five tests failed there and SIX MORE PASSED FOR THE WRONG REASON:
    they assert 0 or (None, None), which is exactly what the untouched gate
    returns, so they were green while measuring nothing at all.

    The vacuous ones are the reason this is a fixture rather than five patches.
    A red test tells you it is broken; a test that passes without running its
    subject tells you nothing, forever, and looks like coverage while doing it.

    These tests are about what the probe DOES WITH an answer. Whether the
    platform can be asked at all is a separate question with its own tests
    below, which patch the gate in the other direction.

    The gate is a recorder, and the teardown asserts it was asked: a test that
    takes this fixture and never reaches the gate is measuring something else
    (api, fleet green leg 8).
    """
    asked: list = []
    monkeypatch.setattr(host_autostart, "is_supported", lambda: asked.append("is_supported") or True)
    yield
    assert asked, "the product never asked is_supported, so this fixture stood in for nothing"


@pytest.fixture
def quiet_serve(monkeypatch: pytest.MonkeyPatch) -> dict:
    """
    Silence the CLI module and hand back what it tried to say.

    The verb tests below assert on the operator-facing output. The error
    reporter is captured; the console is the real one, read through capsys
    (api, fleet green leg 8: it was a MagicMock read by its call list).
    """
    reporter = MagicMock()
    monkeypatch.setattr(host_serve_module, "header", MagicMock())
    monkeypatch.setattr(host_serve_module, "error", reporter)
    monkeypatch.setattr(host_serve_module, "logger", MagicMock())
    monkeypatch.setattr(host_serve_module, "json_handler", MagicMock())
    return {"error": reporter}


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

    def test_the_rate_limit_is_in_unit_not_service(self, tmp_path: Path) -> None:
        """
        systemd moved StartLimit* to [Unit] in v230 and IGNORES it in [Service].

        The wrong section does not fail to parse. It parses fine and the limit
        is simply not there, which is the difference between a server that gives
        up after ten minutes of impossible binds and one that retries forever
        into a growing log.
        """
        branch = tmp_path / "branch"
        text = host_autostart.unit_text(["/py", "/app.py"], branch, branch / "logs" / "x.log")

        unit_section = text.split("[Service]")[0]
        service_section = text.split("[Service]")[1]

        assert "StartLimitIntervalSec" in unit_section
        assert "StartLimitBurst" in unit_section
        assert "StartLimitIntervalSec" not in service_section
        assert "StartLimitBurst" not in service_section

    def test_both_streams_append_to_the_one_log(self, tmp_path: Path) -> None:
        """
        Requirement three, and the reason this morning was diagnosable at all.

        `append:` rather than `file:` — file: TRUNCATES on every start, so the
        first restart after an outage would destroy the evidence of the outage.
        """
        branch = tmp_path / "branch"
        log = branch / "logs" / "host_api_serve.log"
        text = host_autostart.unit_text(["/py", "/app.py"], branch, log)

        assert f"StandardOutput=append:{log}" in text
        assert f"StandardError=append:{log}" in text
        # Scoped to the stream directives: Documentation= legitimately carries a
        # file:// URL, and a bare "file:" search would have matched THAT and
        # called a correct unit broken.
        assert "StandardOutput=file:" not in text
        assert "StandardError=file:" not in text

    def test_the_unit_starts_the_server_the_same_way_a_detach_does(self, tmp_path: Path) -> None:
        """
        One spelling of how this server starts, or the two drift.

        The unit's copy is the one nobody re-reads: it lives under somebody's
        home directory where this tree cannot see it.
        """
        argv = host_lifetime.serve_argv("10.0.0.1", 8787)
        text = host_autostart.unit_text(argv, tmp_path / "branch", tmp_path / "log")

        assert f"ExecStart={' '.join(argv)}" in text

    def test_a_crash_restarts_and_a_clean_exit_does_not(self, tmp_path: Path) -> None:
        """
        on-failure, never always.

        `always` would restart a server that exited cleanly because its bind was
        refused, turning a clear refusal into a spin.
        """
        text = host_autostart.unit_text(["/py"], tmp_path / "branch", tmp_path / "log")

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

    def test_no_unit_is_zero_not_an_error(self, has_systemd: None) -> None:
        """An uninstalled unit answers MainPID=0 with a successful exit."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("0\n")):
            assert host_autostart.supervised_pid() == 0

    def test_a_live_unit_reports_its_pid(self, has_systemd: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("4242\n")):
            assert host_autostart.supervised_pid() == 4242

    def test_an_unreadable_pid_refuses_rather_than_reading_as_unsupervised(self, has_systemd: None) -> None:
        """
        Garbage from a probe is the absence of a measurement, so it refuses.

        Zero would say "no unit holds the server" and send running() to a record
        the unit never writes. Every caller of running() already turns this
        refusal into a status line, so no traceback reaches an operator
        (api, fleet green leg 3).
        """
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("banana")):
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_autostart.supervised_pid()

    def test_a_negative_pid_is_zero_because_the_contract_says_zero(self, has_systemd: None) -> None:
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

    def test_a_probe_that_cannot_run_refuses_rather_than_answering_zero(self, has_systemd: None) -> None:
        """
        REVERSED 2026-08-27, deliberately, from "is zero" to "refuses".

        The old assertion was wrong in the way this whole lane exists to catch.
        A systemctl that IS here and cannot be run leaves the question
        unanswered, and zero does not mean unanswered — it means no unit is
        holding the server. On the tailnet host the unit writes NO record file,
        so a swallowed probe sends running() down the record path and status
        prints "No server is running" about a server answering requests.

        The no-systemd platform still answers zero. That case is a MEASUREMENT:
        there is no unit and there cannot be one. This one is the ABSENCE of a
        measurement, and the two must not share an answer.
        """
        with patch.object(host_autostart.subprocess, "run", side_effect=OSError("cannot exec")):
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_autostart.supervised_pid()

    def test_a_hung_supervisor_refuses_and_does_not_hang_the_caller(self, has_systemd: None) -> None:
        """A hung supervisor must not hang the caller, nor read as an empty one."""
        timeout = host_autostart.subprocess.TimeoutExpired(cmd="systemctl", timeout=5)

        with patch.object(host_autostart.subprocess, "run", side_effect=timeout):
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_autostart.supervised_pid()

    def test_a_platform_with_no_systemd_still_answers_zero(self, quiet: None) -> None:
        """
        THE RULING'S OTHER HALF, pinned so it cannot drift into a refusal.

        Zero here is the strongest answer available, not a dodge: a machine
        without systemd cannot have a unit, so "no unit is holding the server"
        has no uncertainty in it. running() then falls through to the detached
        record — the only kind of server that can exist there — and a caller
        gets the truth instead of an exception it would have to translate back
        into the same truth.
        """
        with patch.object(host_autostart, "is_supported", return_value=False) as gate:
            with patch.object(host_autostart.subprocess, "run") as run:
                assert host_autostart.supervised_pid() == 0
                run.assert_not_called()
        gate.assert_called_once_with()

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

    def test_the_bind_comes_out_of_execstart(self, has_systemd: None) -> None:
        exec_start = "{ path=/py ; argv[]=/py /app.py host-api serve --host 10.9.8.7 --port 9001 ; ignore_errors=no }"

        with patch.object(host_autostart.subprocess, "run", return_value=_completed(exec_start)):
            assert host_autostart.supervised_bind() == ("10.9.8.7", 9001)

    def test_an_unreadable_execstart_is_unknown_never_guessed(self, has_systemd: None) -> None:
        """
        A status line that invents a port is worse than one that says unknown.

        It would be confidently wrong exactly once — after somebody changes the
        port and before they reinstall — which is the worst possible time.
        """
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("")):
            assert host_autostart.supervised_bind() == (None, None)

    def test_an_unreachable_probe_costs_the_bind_and_not_the_verdict(self, has_systemd: None) -> None:
        """
        Found by a SURVIVING mutation: nothing pinned this tolerance.

        The pid probe has already established that a unit is live by the time
        this runs. If the bind probe propagated its refusal instead of
        swallowing it, a live server plus one wedged second call would make
        status REFUSE — trading a known-running server for "cannot tell", which
        is strictly worse than printing its address as unknown.
        """
        with patch.object(host_autostart.subprocess, "run", side_effect=OSError("wedged")):
            assert host_autostart.supervised_bind() == (None, None)

    def test_a_non_numeric_port_does_not_raise(self, has_systemd: None) -> None:
        exec_start = "argv[]=/py /app.py host-api serve --host 10.0.0.1 --port eighty"

        with patch.object(host_autostart.subprocess, "run", return_value=_completed(exec_start)):
            assert host_autostart.supervised_bind() == ("10.0.0.1", None)


class TestStoppingGoesThroughTheSupervisor:
    """`systemctl stop` outranks Restart= by definition. A signal does not."""

    def test_a_refused_stop_is_false_not_an_exception(self, has_systemd: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed(returncode=1)):
            assert host_autostart.stop_unit() is False

    def test_an_accepted_stop_is_true(self, has_systemd: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed()):
            assert host_autostart.stop_unit() is True

    def test_a_platform_without_systemd_refuses_rather_than_pretends(
        self, quiet: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """
        stop_unit asks is_supported, the product's own gate, and refuses on its no.

        Answered through that gate, not by setting sys.platform for the whole
        process (api, fleet green leg 10); the platform half of the gate is
        test_a_platform_without_systemd_never_shells_out's.
        """
        asked: list = []
        monkeypatch.setattr(host_autostart, "is_supported", lambda: asked.append("is_supported") or False)

        with pytest.raises(host_autostart.AutostartUnsupported):
            host_autostart.stop_unit()

        assert asked == ["is_supported"], "stop_unit refused without asking the gate"


class TestTheInstallStepsAreOrderedAndOutsideTheTree:
    """Installing means writing under a home directory — theirs to run, not mine."""

    def test_the_unit_is_copied_before_it_is_enabled(self, tmp_path: Path) -> None:
        steps = host_autostart.install_commands(tmp_path / "branch" / "logs" / "u.service")
        joined = " || ".join(steps)

        assert joined.index("cp ") < joined.index("daemon-reload") < joined.index("enable --now")

    def test_lingering_is_part_of_the_instructions(self) -> None:
        """
        Without it a user unit waits for a login, which a headless reboot never
        provides — the exact failure this build exists to end.
        """
        assert any("enable-linger" in step for step in host_autostart.install_commands(Path("/u")))


class TestTheAutostartVerbAtTheLayerAnOperatorTypes:
    """
    The verb itself, routed the way a person reaches it.

    Everything above tests the handler. Nothing tested the CLI: seedgo's
    entry_point_diff named `autostart` as a declared entry point no test
    reaches, and it matched this branch's own APLAN-0013 N1a item, which had
    measured 29 lines in cmd_autostart with 1 of them executed. So the four
    outcomes an operator can actually produce are pinned here, through
    handle_command, and the handler underneath is mocked — the wiring is what
    was never run.

    The exit-code arm matters most. An operator scripting `autostart &&
    systemctl --user enable ...` must not reach the enable step when no unit
    was written, and that is a promise the CLI makes, not the handler.
    """

    def _report(self, base: Path, linger: Any = True, conflict: Any = None) -> dict:
        """The handler's real report shape — unit, steps, linger, conflict."""
        return {
            "unit": base / "branch" / "logs" / "aipass-host-api.service",
            "steps": ["cp /branch/logs/u.service ~/.config/systemd/user/", "systemctl --user enable --now x"],
            "linger": linger,
            "conflict": conflict,
        }

    def test_the_verb_routes_and_prints_the_installation_steps(
        self, quiet_serve: dict, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """The ordinary success path: every step reaches the operator's screen."""
        report = self._report(tmp_path)

        with patch.object(host_serve_module.host_lifetime, "autostart_report", return_value=report) as reporter:
            assert handle_command("host-api", ["autostart"]) is True

        reporter.assert_called_once_with(None, None)
        printed, _ = capsys.readouterr()
        for step in report["steps"]:
            assert step in printed, f"the operator was not shown the step they have to run: {step}"

    def test_lingering_being_off_is_a_warning_not_a_dim_note(self, quiet_serve: dict, tmp_path: Path) -> None:
        """
        The one report field whose absence is the original 08-27 failure.

        Without lingering the unit waits for a login that a headless reboot
        never provides — the server stays down and the unit looks installed.
        That has to reach `warning`, not the same dim line that says everything
        is fine, because the two are read at a glance and never re-read.
        """
        with patch.object(host_serve_module, "warning") as warned:
            with patch.object(
                host_serve_module.host_lifetime, "autostart_report", return_value=self._report(tmp_path, linger=False)
            ):
                assert handle_command("host-api", ["autostart"]) is True

        warned.assert_called_once()
        assert "linger" in str(warned.call_args).lower()

    def test_lingering_that_could_not_be_read_is_not_reported_as_off(self, quiet_serve: dict, tmp_path: Path) -> None:
        """
        None is a third answer, and collapsing it into False cries wolf.

        The handler returns None when the question could not be asked at all.
        An operator warned that lingering is OFF when nobody could tell is an
        operator who stops believing the next warning.
        """
        with patch.object(host_serve_module, "warning") as warned:
            with patch.object(
                host_serve_module.host_lifetime, "autostart_report", return_value=self._report(tmp_path, linger=None)
            ):
                assert handle_command("host-api", ["autostart"]) is True

        warned.assert_not_called()

    def test_a_non_numeric_port_is_refused_before_the_handler_runs(self, quiet_serve: dict) -> None:
        """
        A typo'd --port must not reach the unit renderer.

        The handler would take the string and bake it into a file that runs at
        every boot, so the refusal has to happen at the layer that parsed it.
        """
        with patch.object(host_serve_module.host_lifetime, "autostart_report") as reporter:
            assert handle_command("host-api", ["autostart", "--port", "eighty-seven"]) is True

        reporter.assert_not_called()
        quiet_serve["error"].assert_called_once()
        assert "eighty-seven" in str(quiet_serve["error"].call_args)

    def test_an_unsupported_platform_is_reported_and_writes_nothing(self, quiet_serve: dict) -> None:
        """No systemd is a refusal with a reason, never a traceback."""
        refusal = host_autostart.AutostartUnsupported("systemd is not available on this platform")

        with patch.object(host_serve_module.host_lifetime, "autostart_report", side_effect=refusal):
            assert handle_command("host-api", ["autostart"]) is True

        quiet_serve["error"].assert_called_once()
        assert "systemd is not available" in str(quiet_serve["error"].call_args)

    def test_a_refused_bind_exits_non_zero_so_a_chained_enable_never_runs(self, quiet_serve: dict) -> None:
        """
        D1 reaches the unit too, and the exit code is the whole point.

        An address refused at the CLI must not be baked into something that
        retries it at every boot forever, and an operator chaining the enable
        step behind `&&` has only the exit code to tell them it did not.
        """
        refusal = host_config.BindRefused("wildcards are refused")

        with patch.object(host_serve_module.host_lifetime, "autostart_report", side_effect=refusal):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("host-api", ["autostart"])

        assert exit_info.value.code == 1
        quiet_serve["error"].assert_called_once()


class TestTheInstallerDoorsRunTheStepsTheVerbPrints:
    """
    FPLAN-0642: host_api.install_unit and enable_unit RUN the steps the verb prints.

    The CLI still only prints them; these doors are for a caller that asked by
    name. Every run here is scripted: subprocess.run is a recorder and the home
    is tmp_path, so no real systemctl, loginctl or user unit dir is touched.
    """

    @pytest.fixture
    def home(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
        monkeypatch.setattr(host_autostart.Path, "home", lambda: tmp_path / "home")
        return tmp_path / "home"

    def _unit(self, tmp_path: Path) -> Path:
        unit = tmp_path / "rendered.service"
        unit.write_text("[Unit]\nDescription=stand-in\n", encoding="utf-8")
        return unit

    def test_a_dry_run_names_every_step_and_runs_none(self, has_systemd: None, home: Path, tmp_path: Path) -> None:
        with patch.object(host_autostart.subprocess, "run") as run:
            report = host_autostart.install_unit(self._unit(tmp_path), dry_run=True)

        run.assert_not_called()
        assert not home.exists()
        assert report["dry_run"] is True and report["ok"] is True
        assert [step["ok"] for step in report["steps"]] == [None, None, None]
        assert "daemon-reload" in report["steps"][2]["step"]

    def test_install_copies_the_unit_home_and_reloads(self, has_systemd: None, home: Path, tmp_path: Path) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed()) as run:
            report = host_autostart.install_unit(self._unit(tmp_path))

        installed = home / ".config" / "systemd" / "user" / host_autostart.UNIT_NAME
        assert installed.read_text(encoding="utf-8") == "[Unit]\nDescription=stand-in\n"
        assert run.call_args.args[0] == ["systemctl", "--user", "daemon-reload"]
        assert report["ok"] is True
        assert [step["ok"] for step in report["steps"]] == [True, True, True]

    def test_a_failed_step_stops_the_run_and_says_why(self, has_systemd: None, home: Path, tmp_path: Path) -> None:
        refused = _completed(returncode=1)
        refused.stderr = "Failed to enable unit"

        with patch.object(host_autostart, "linger_enabled", return_value=False):
            with patch.object(host_autostart.subprocess, "run", return_value=refused) as run:
                report = host_autostart.enable_unit()

        assert run.call_count == 1, "the linger step ran after the enable had already failed"
        assert report["ok"] is False
        assert [(step["ok"], step["detail"]) for step in report["steps"]] == [(False, "Failed to enable unit")]
        assert "enable --now" in report["steps"][0]["step"]

    def test_enable_turns_lingering_on_only_when_it_is_off(self, has_systemd: None) -> None:
        for linger, expected in ((False, 2), (True, 1)):
            with patch.object(host_autostart, "linger_enabled", return_value=linger):
                with patch.object(host_autostart.subprocess, "run", return_value=_completed()) as run:
                    report = host_autostart.enable_unit()

            assert run.call_count == expected
            assert run.call_args_list[0].args[0] == ["systemctl", "--user", "enable", "--now", host_autostart.UNIT_NAME]
            assert report["ok"] is True
        assert len(report["steps"]) == 1

    def test_the_module_door_refuses_to_enable_over_a_hand_started_server(self, quiet: None) -> None:
        """enable --now against a detached server's port would crash-loop the unit."""
        detached = {"owner": host_lifetime.OWNER_DETACHED, "pid": 5150}

        with patch.object(host_lifetime, "running", return_value=detached):
            with patch.object(host_autostart, "enable_unit") as enable:
                report = host_api_module.enable_unit()

        enable.assert_not_called()
        assert report["ok"] is False and report["steps"] == []
        assert "5150" in report["refused"]

    def test_the_module_door_leaves_a_live_unit_alone(self, quiet: None, tmp_path: Path) -> None:
        """Idempotent: a second install does not re-render the unit systemd is running."""
        with (
            patch.object(host_autostart, "supervised_pid", return_value=4242),
            patch.object(host_lifetime, "unit_path", return_value=tmp_path / "u.service"),
        ):
            with patch.object(host_autostart, "linger_enabled", return_value=True):
                with patch.object(host_lifetime, "write_unit") as write:
                    report = host_api_module.autostart("127.0.0.1", 9100)

        write.assert_not_called()
        assert report["rendered"] is False
        assert report["running"] == 4242

    def test_the_module_door_renders_when_no_unit_runs(self, quiet: None, tmp_path: Path) -> None:
        rendered = {"unit": tmp_path / "u.service", "steps": [], "linger": True, "conflict": None}

        with patch.object(host_autostart, "supervised_pid", return_value=0):
            with patch.object(host_lifetime, "autostart_report", return_value=rendered) as reporter:
                report = host_api_module.autostart("127.0.0.1", 9100)

        reporter.assert_called_once_with("127.0.0.1", 9100)
        assert report["rendered"] is True and report["running"] == 0

    def test_both_doors_refuse_without_systemd(self, quiet: None, tmp_path: Path) -> None:
        with patch.object(host_autostart, "is_supported", return_value=False):
            with pytest.raises(host_api_module.AutostartUnsupported):
                host_autostart.install_unit(tmp_path / "u.service")
            with pytest.raises(host_api_module.AutostartUnsupported):
                host_autostart.enable_unit()
