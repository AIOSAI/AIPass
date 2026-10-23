# =================== AIPass ====================
# Name: test_host_autostart.py
# Description: Tests for the supervisor seam — a server that comes back on its own
# Version: 1.2.0
# Created: 2026-08-27
# Modified: 2026-10-22
# =============================================

"""Tests for apps/handlers/host/autostart.py and the host-api autostart verb that drives it."""

# Both promises fail silently: status must see a unit-managed server (it writes no
# record), and stop must go through systemd (a signal is undone by Restart=).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that autostart.py parses and imports
# seedgo: no-test-needed(constant) — RESTART_SECONDS, START_LIMIT_INTERVAL_SECONDS and START_LIMIT_BURST's values
# seedgo: no-test-needed(external) — a real systemd; subprocess.run is scripted and is_supported pinned

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

    `_systemctl` asks is_supported() first, so without this a non-systemd runner
    never reaches the scripted subprocess and the zero-asserting tests pass vacuously."""
    asked: list = []
    monkeypatch.setattr(host_autostart, "is_supported", lambda: asked.append("is_supported") or True)
    yield
    assert asked, "the product never asked is_supported, so this fixture stood in for nothing"


@pytest.fixture
def quiet_serve(monkeypatch: pytest.MonkeyPatch) -> dict:
    """Silence the CLI module and hand back what it tried to say."""
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


class TestTheUnitSaysWhatItMeans:
    """The unit is written once and then read by systemd forever, unwatched."""

    def test_the_rate_limit_is_in_unit_not_service(self, tmp_path: Path) -> None:
        """systemd moved StartLimit* to [Unit] in v230 and IGNORES it in [Service]."""
        branch = tmp_path / "branch"
        text = host_autostart.unit_text(["/py", "/app.py"], branch, branch / "logs" / "x.log")

        unit_section = text.split("[Service]")[0]
        service_section = text.split("[Service]")[1]

        assert "StartLimitIntervalSec" in unit_section
        assert "StartLimitBurst" in unit_section
        assert "StartLimitIntervalSec" not in service_section
        assert "StartLimitBurst" not in service_section

    def test_the_unit_starts_and_stops_with_the_graphical_session(self, tmp_path: Path) -> None:
        """The login keyring opens at login: a unit started at boot dies at its start limit and stays dead."""
        text = host_autostart.unit_text(["/py", "/app.py"], tmp_path, tmp_path / "x.log")
        unit_section = text.split("[Service]")[0].splitlines()
        install_section = text.split("[Install]")[1].splitlines()

        assert "After=graphical-session.target" in unit_section
        assert "PartOf=graphical-session.target" in unit_section
        assert [line for line in install_section if line.startswith("WantedBy=")] == [
            "WantedBy=graphical-session.target"
        ]
        assert "default.target" not in text

    def test_both_streams_append_to_the_one_log(self, tmp_path: Path) -> None:
        """
        Requirement three, and the reason this morning was diagnosable at all.

        `append:` rather than `file:` — file: TRUNCATES on every start."""
        branch = tmp_path / "branch"
        log = branch / "logs" / "host_api_serve.log"
        text = host_autostart.unit_text(["/py", "/app.py"], branch, log)

        assert f"StandardOutput=append:{log}" in text
        assert f"StandardError=append:{log}" in text
        # Scoped: Documentation= legitimately carries a file:// URL.
        assert "StandardOutput=file:" not in text
        assert "StandardError=file:" not in text

    def test_the_unit_starts_the_server_the_same_way_a_detach_does(self, tmp_path: Path) -> None:
        """One spelling of how this server starts, or the two drift."""
        argv = host_lifetime.serve_argv("10.0.0.1", 8787)
        text = host_autostart.unit_text(argv, tmp_path / "branch", tmp_path / "log")

        assert f"ExecStart={' '.join(argv)}" in text

    def test_a_crash_restarts_and_a_clean_exit_does_not(self, tmp_path: Path) -> None:
        """
        on-failure, never always.

        `always` would turn a clean exit on a refused bind into a spin."""
        text = host_autostart.unit_text(["/py"], tmp_path / "branch", tmp_path / "log")

        assert "Restart=on-failure" in text
        assert "Restart=always" not in text

    def test_the_supervisor_gives_a_shutdown_longer_than_this_branch_waits(self) -> None:
        """A stop wait shorter than the supervisor's own budget reports a false hang."""
        assert host_autostart.STOP_TIMEOUT_SECONDS > host_autostart.TIMEOUT_STOP_SECONDS


class TestTheProbeAnswersAbsenceAndFailureDifferently:
    """
    `show -p MainPID` rather than `is-active`, and this is why.

    is-active exits non-zero for inactive, no such unit, and failure to run alike."""

    def test_no_unit_is_zero_not_an_error(self, has_systemd: None) -> None:
        """An uninstalled unit answers MainPID=0 with a successful exit."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("0\n")):
            assert host_autostart.supervised_pid() == 0

    def test_a_live_unit_reports_its_pid(self, has_systemd: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("4242\n")):
            assert host_autostart.supervised_pid() == 4242

    def test_an_unreadable_pid_refuses_rather_than_reading_as_unsupervised(self, has_systemd: None) -> None:
        """Garbage from a probe is the absence of a measurement, so it refuses."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("banana")):
            with pytest.raises(host_autostart.SupervisorUnreachable):
                host_autostart.supervised_pid()

    def test_a_negative_pid_is_zero_because_the_contract_says_zero(self, has_systemd: None) -> None:
        """
        Found by a mutation that SURVIVED: dropping the `> 0` guard changed
        nothing any test could see. running() reads any truthy pid as supervised."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("-1")):
            assert host_autostart.supervised_pid() == 0

    def test_a_probe_that_cannot_run_refuses_rather_than_answering_zero(self, has_systemd: None) -> None:
        """
        A probe that cannot run refuses; it never answers zero.

        Zero means no unit holds the server; an unrunnable probe answered nothing."""
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

        Without systemd there cannot be a unit, so zero is a measurement here."""
        with patch.object(host_autostart, "is_supported", return_value=False) as gate:
            with patch.object(host_autostart.subprocess, "run") as run:
                assert host_autostart.supervised_pid() == 0
                run.assert_not_called()
        gate.assert_called_once_with()

    def test_a_platform_without_systemd_never_shells_out(self, quiet: None) -> None:
        """The Windows lesson, applied before the bug rather than after."""
        with patch.object(host_autostart.sys, "platform", "win32"):
            with patch.object(host_autostart.subprocess, "run") as run:
                assert host_autostart.supervised_pid() == 0
                assert host_autostart.is_supported() is False
                run.assert_not_called()


class TestTheBindIsReadFromTheUnitNotTheConfig:
    """
    The unit pins its bind at install time; set-config afterwards changes what
    the NEXT install would use and nothing about the process listening now."""

    def test_the_bind_comes_out_of_execstart(self, has_systemd: None) -> None:
        exec_start = "{ path=/py ; argv[]=/py /app.py host-api serve --host 10.9.8.7 --port 9001 ; ignore_errors=no }"

        with patch.object(host_autostart.subprocess, "run", return_value=_completed(exec_start)):
            assert host_autostart.supervised_bind() == ("10.9.8.7", 9001)

    def test_an_unreadable_execstart_is_unknown_never_guessed(self, has_systemd: None) -> None:
        """A status line that invents a port is worse than one that says unknown."""
        with patch.object(host_autostart.subprocess, "run", return_value=_completed("")):
            assert host_autostart.supervised_bind() == (None, None)

    def test_an_unreachable_probe_costs_the_bind_and_not_the_verdict(self, has_systemd: None) -> None:
        """
        Found by a SURVIVING mutation: nothing pinned this tolerance.

        The pid probe already proved the unit live; refusing here would cost the verdict."""
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
        """stop_unit asks is_supported, the product's own gate, and refuses on its no."""
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

    def test_the_steps_are_four_and_none_touches_the_account(self) -> None:
        """Lingering is the account's setting for the daemon's timers, never this unit's install."""
        steps = host_autostart.install_commands(Path("/u"))

        assert len(steps) == 4
        assert not [step for step in steps if "linger" in step or "loginctl" in step]


class TestTheAutostartVerbAtTheLayerAnOperatorTypes:
    """The verb itself, routed the way a person reaches it."""

    def _report(self, base: Path, conflict: Any = None) -> dict:
        """The handler's real report shape — unit, steps, conflict."""
        return {
            "unit": base / "branch" / "logs" / "aipass-host-api.service",
            "steps": ["cp /branch/logs/u.service ~/.config/systemd/user/", "systemctl --user enable --now x"],
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

    def test_the_verb_says_nothing_about_lingering(
        self, quiet_serve: dict, tmp_path: Path, capsys: pytest.CaptureFixture
    ) -> None:
        """No conflict means no warning, and no line about the account's lingering."""
        with patch.object(host_serve_module, "warning") as warned:
            with patch.object(host_serve_module.host_lifetime, "autostart_report", return_value=self._report(tmp_path)):
                assert handle_command("host-api", ["autostart"]) is True

        warned.assert_not_called()
        assert "linger" not in capsys.readouterr().out.lower()

    def test_a_non_numeric_port_is_refused_before_the_handler_runs(self, quiet_serve: dict) -> None:
        """A typo'd --port must not reach the unit renderer."""
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

        An operator chaining the enable step behind `&&` has only the exit code."""
        refusal = host_config.BindRefused("wildcards are refused")

        with patch.object(host_serve_module.host_lifetime, "autostart_report", side_effect=refusal):
            with pytest.raises(SystemExit) as exit_info:
                handle_command("host-api", ["autostart"])

        assert exit_info.value.code == 1
        quiet_serve["error"].assert_called_once()


class TestTheInstallerDoorsRunTheStepsTheVerbPrints:
    """The installer doors host_api.install_unit and enable_unit RUN the steps the verb prints."""

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

        with patch.object(host_autostart.subprocess, "run", return_value=refused) as run:
            report = host_autostart.enable_unit()

        assert run.call_count == 1
        assert report["ok"] is False
        assert [(step["ok"], step["detail"]) for step in report["steps"]] == [(False, "Failed to enable unit")]
        assert "enable --now" in report["steps"][0]["step"]

    def test_enable_runs_enable_now_and_nothing_else(self, has_systemd: None) -> None:
        with patch.object(host_autostart.subprocess, "run", return_value=_completed()) as run:
            report = host_autostart.enable_unit()

        assert [call.args[0] for call in run.call_args_list] == [
            ["systemctl", "--user", "enable", "--now", host_autostart.UNIT_NAME]
        ]
        assert report["ok"] is True
        assert [step["step"] for step in report["steps"]] == [
            f"systemctl --user enable --now {host_autostart.UNIT_NAME}"
        ]

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
            with patch.object(host_lifetime, "write_unit") as write:
                report = host_api_module.autostart("127.0.0.1", 9100)

        write.assert_not_called()
        assert report["rendered"] is False
        assert report["running"] == 4242

    def test_the_module_door_renders_when_no_unit_runs(self, quiet: None, tmp_path: Path) -> None:
        rendered = {"unit": tmp_path / "u.service", "steps": [], "conflict": None}

        with patch.object(host_autostart, "supervised_pid", return_value=0):
            with patch.object(host_lifetime, "autostart_report", return_value=rendered) as reporter:
                report = host_api_module.autostart("127.0.0.1", 9100)

        reporter.assert_called_once_with("127.0.0.1", 9100)
        assert report["rendered"] is True and report["running"] == 0

    def test_the_serve_detached_door_is_the_handler_with_the_same_refusals(self, quiet: None) -> None:
        """Where no user systemd exists the install starts the server
        through this door instead of printing the command."""
        record = {"pid": 7, "host": "100.64.0.9", "port": 9100, "log": "/l", "started": "t"}
        with patch.object(host_lifetime, "serve_detached", return_value=record) as start:
            assert host_api_module.serve_detached("100.64.0.9", 9100) == record
        start.assert_called_once_with(host="100.64.0.9", port=9100)

        with patch.object(host_lifetime, "serve_detached", side_effect=host_config.BindRefused("loopback")):
            with pytest.raises(host_api_module.BindRefused):
                host_api_module.serve_detached()

    def test_both_doors_refuse_without_systemd(self, quiet: None, tmp_path: Path) -> None:
        with patch.object(host_autostart, "is_supported", return_value=False):
            with pytest.raises(host_api_module.AutostartUnsupported):
                host_autostart.install_unit(tmp_path / "u.service")
            with pytest.raises(host_api_module.AutostartUnsupported):
                host_autostart.enable_unit()
