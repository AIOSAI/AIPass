# =================== AIPass ====================
# Name: test_timer_install.py
# Description: Tests for the timer_install module (systemd user timer installer)
# Version: 1.1.1
# Created: 2026-06-25
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/timer_install.py — install-timer and uninstall-timer, the systemd user timer."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — shutil.copy2's metadata copy; the copies are asserted on disk, not their mode bits
# seedgo: no-test-needed(ruff) — that timer_install.py parses and imports; every test here imports it first

import json
import subprocess

import pytest
from unittest.mock import call, patch
import sys
from pathlib import Path

from aipass.daemon.apps.modules.timer_install import (
    handle_command,
    HANDLED_COMMANDS,
)

# Verbs are reached through handle_command, inside conftest's seal; a failed install is sys.exit(1).
TI = "aipass.daemon.apps.modules.timer_install"


def _units(directory: Path) -> tuple:
    """Write the two unit files the installer copies, and return them."""
    service = directory / "daemon-tick.service"
    timer = directory / "daemon-tick.timer"
    service.write_text("[Unit]\nDescription=tick service\n", encoding="utf-8")
    timer.write_text("[Unit]\nDescription=tick timer\n", encoding="utf-8")
    return service, timer


def _exit_of(verb: str) -> int:
    """The exit code a verb answers through handle_command: 0 when handled, else its SystemExit code."""
    try:
        handle_command(verb, [])
    except SystemExit as stopped:
        return int(stopped.code or 0)
    return 0


def _systemd_that_knows_no_timer(*args: str, not_loaded_ok: bool = False, not_found_ok: bool = False) -> bool:
    """A recorder in the place of _run_systemctl for a host where systemd does not know the timer."""
    if args[0] == "stop":
        return not_loaded_ok
    return args[0] != "disable"


def _host_with_no_systemctl(*args: str, not_loaded_ok: bool = False, not_found_ok: bool = False) -> bool | None:
    """A recorder in the place of _run_systemctl for a host where systemctl is not found."""
    return None if not_found_ok else False


class TestHandleCommand:
    """Tests for command routing."""

    def test_handles_install_timer(self):
        """Verify install-timer is in handled commands."""
        assert "install-timer" in HANDLED_COMMANDS

    def test_handles_uninstall_timer(self):
        """Verify uninstall-timer is in handled commands."""
        assert "uninstall-timer" in HANDLED_COMMANDS

    def test_rejects_unknown(self):
        """Unknown commands return False."""
        assert handle_command("unknown", []) is False

    def test_help_flag(self, capsys):
        """install-timer --help prints this module's own usage and returns True."""
        with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
            result = handle_command("install-timer", ["--help"])
        out = capsys.readouterr().out
        assert result is True
        assert "install-timer / uninstall-timer — Daemon Scheduler Timer" in out, (
            f"install-timer --help printed: {out[:200]!r}"
        )
        assert "USAGE:" in out, "install-timer --help must print a USAGE: block"


_STUB = """#!{python}
import json
import sys

answers = json.loads({answers!r})
with open({log!r}, "a", encoding="utf-8") as log:
    log.write(" ".join(sys.argv[1:]) + "\\n")
code, said = answers.get(sys.argv[2] if len(sys.argv) > 2 else "", [0, ""])
if said:
    print(said, file=sys.stderr)
sys.exit(code)
"""

# Windows CreateProcess finds a bare name on PATH only as name.exe, so no stub here can run there.
_NEEDS_A_STUB_ON_PATH = pytest.mark.skipif(
    sys.platform == "win32",
    reason="systemd does not exist on Windows; the verb's answer there is pinned by test_systemctl_not_found",
)


@pytest.fixture
def systemctl_on_path(tmp_path, monkeypatch):
    """Lay a systemctl stub as the only one on PATH; answer the path of the log of every argv it receives.

    Asking for it keeps the real _run_systemctl (conftest's seal empties PATH instead).
    `answers` is verb -> (exit code, stderr line); None lays nothing, a host with no systemctl.
    """

    def lay(answers: dict | None) -> Path:
        log = tmp_path / "systemctl_argv.log"
        if answers is None:
            return log
        bin_dir = tmp_path / "stub_bin"
        bin_dir.mkdir()
        stub = bin_dir / "systemctl"
        stub.write_text(
            _STUB.format(python=sys.executable, answers=json.dumps(answers), log=str(log)),
            encoding="utf-8",
        )
        stub.chmod(0o755)
        monkeypatch.setenv("PATH", str(bin_dir))
        try:
            subprocess.run(["systemctl", "--user", "probe"], capture_output=True, encoding="utf-8", timeout=15)
        except OSError as refused:
            pytest.fail(f"a systemctl stub cannot run from PATH on this host ({sys.platform}): {refused}")
        log.write_text("", encoding="utf-8")
        return log

    return lay


def _argv(log: Path) -> list:
    """Every argv the stub received, one call a line, or [] when systemctl was never run."""
    return log.read_text(encoding="utf-8").splitlines() if log.exists() else []


class TestTheCommandsReadSystemctlsAnswers:
    """install-timer and uninstall-timer against a real systemctl on PATH: each answer the wrapper can give.

    Only the timeout patches subprocess.run: a stub cannot outwait the wrapper's 15 s in a suite.
    """

    @pytest.fixture(autouse=True)
    def _units_to_install(self, tmp_path):
        """The two unit files install-timer copies, under a daemon root of this test's own."""
        root = tmp_path / "daemon_root"
        root.mkdir()
        _units(root)
        with patch(f"{TI}._DAEMON_ROOT", root):
            yield

    @_NEEDS_A_STUB_ON_PATH
    def test_success_runs_reload_enable_start_in_that_order(self, systemctl_on_path):
        """Every step exits 0: install-timer answers True and systemctl saw daemon-reload, enable, start."""
        log = systemctl_on_path({})
        assert handle_command("install-timer", []) is True
        assert _argv(log) == [
            "--user daemon-reload",
            "--user enable daemon-tick.timer",
            "--user start daemon-tick.timer",
        ]

    @_NEEDS_A_STUB_ON_PATH
    def test_a_non_zero_exit_fails_the_install_and_prints_why(self, systemctl_on_path, capsys):
        """daemon-reload exits 1 with a stderr line: both print, install exits 1, nothing more is asked."""
        log = systemctl_on_path({"daemon-reload": [1, "Failed to connect to bus"]})
        assert _exit_of("install-timer") == 1
        said = "".join(capsys.readouterr())
        assert "FAIL: systemctl --user daemon-reload" in said, said
        assert "Failed to connect to bus" in said, said
        assert _argv(log) == ["--user daemon-reload"]

    @_NEEDS_A_STUB_ON_PATH
    def test_not_loaded_on_a_stop_is_nothing_to_stop(self, systemctl_on_path, tmp_path, capsys):
        """stop exits 5 (not loaded): uninstall-timer goes on to disable, removes the files and exits 0, with no FAIL.

        Exit 5 is what systemctl gives a stop of a unit it does not know.
        """
        unit_dir = tmp_path / "_sealed_unit_dir"
        unit_dir.mkdir()
        service, timer = _units(unit_dir)
        log = systemctl_on_path({"stop": [5, "Unit daemon-tick.timer not loaded."]})
        with patch("aipass.trigger.apps.modules.core.trigger.fire"):
            assert _exit_of("uninstall-timer") == 0
        assert _argv(log) == [
            "--user stop daemon-tick.timer",
            "--user disable daemon-tick.timer",
            "--user daemon-reload",
        ]
        assert not service.exists() and not timer.exists()
        assert "FAIL" not in "".join(capsys.readouterr()), "not loaded is nothing to stop, never a failure"

    @_NEEDS_A_STUB_ON_PATH
    def test_a_stop_refused_for_another_reason_fails_the_uninstall(self, systemctl_on_path, tmp_path):
        """stop exits 1: not loaded is exit 5 only, so the uninstall names the stop, exits 1 and keeps the files."""
        unit_dir = tmp_path / "_sealed_unit_dir"
        unit_dir.mkdir()
        service, timer = _units(unit_dir)
        log = systemctl_on_path({"stop": [1, "Access denied"]})
        assert _exit_of("uninstall-timer") == 1
        assert _argv(log) == ["--user stop daemon-tick.timer"]
        assert service.exists() and timer.exists()

    @_NEEDS_A_STUB_ON_PATH
    def test_not_loaded_anywhere_but_a_stop_is_a_failure(self, systemctl_on_path, capsys):
        """enable exits 5: install-timer passes no not_loaded_ok, so the install fails at enable and never starts."""
        log = systemctl_on_path({"enable": [5, "Unit daemon-tick.timer not loaded."]})
        assert _exit_of("install-timer") == 1
        assert "FAIL: systemctl --user enable daemon-tick.timer" in "".join(capsys.readouterr())
        assert _argv(log) == ["--user daemon-reload", "--user enable daemon-tick.timer"]

    def test_systemctl_not_found(self, systemctl_on_path, capsys):
        """No systemctl on PATH: uninstall-timer (not_found_ok) says not installed and exits 0; install-timer fails.

        Only uninstall's stop passes not_found_ok; its None tells nothing installed from a failed stop.
        """
        systemctl_on_path(None)
        assert _exit_of("uninstall-timer") == 0
        said = "".join(capsys.readouterr())
        assert "Not installed:" in said and "no systemctl on this host" in said, said
        assert "systemctl not found" not in said, "not found asked for is not an error"
        assert _exit_of("install-timer") == 1
        said = "".join(capsys.readouterr())
        assert "systemctl not found — systemd not available" in said, said

    def test_a_timeout_is_a_failure_never_not_found(self, systemctl_on_path, capsys):
        """systemctl times out: install-timer exits 1 naming the timeout; uninstall's stop is a failure, not None."""
        systemctl_on_path(None)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=15)):
            # Uninstall first, with no unit file standing: only there does None (exit 0) differ from False (exit 1).
            assert _exit_of("uninstall-timer") == 1
            assert "uninstall-timer: systemctl --user stop daemon-tick.timer failed" in capsys.readouterr().err
            assert _exit_of("install-timer") == 1
            said = "".join(capsys.readouterr())
            assert "systemctl timed out" in said, said
            assert "not found" not in said, f"a timeout reported as a missing systemctl: {said}"


class TestInstall:
    @pytest.fixture(autouse=True)
    def _no_real_home(self, tmp_path_factory):
        """Redirect the shared state dir for EVERY test in this class: a seam a test can forget is no fix."""
        with patch(
            "aipass.daemon.apps.modules.timer_install._STATE_DIR",
            tmp_path_factory.mktemp("state"),
        ):
            yield

    """Tests for the install flow."""

    def test_install_missing_unit_file(self, tmp_path):
        """install-timer exits 1 when the unit files are missing, and copies nothing."""
        install_dir = tmp_path / "systemd"
        with (
            patch(f"{TI}._DAEMON_ROOT", tmp_path / "no_unit_files"),
            patch(f"{TI}._UNIT_DIR", install_dir),
            pytest.raises(SystemExit) as stopped,
        ):
            handle_command("install-timer", [])
        assert stopped.value.code == 1
        assert not install_dir.exists(), "a refused install must not create the unit directory"

    @patch(f"{TI}._run_systemctl", return_value=True)
    def test_install_success(self, mock_systemctl, tmp_path):
        """A good install copies both units into the unit dir and runs reload, enable, start."""
        service, timer = _units(tmp_path)
        install_dir = tmp_path / "systemd"
        install_dir.mkdir()

        with (
            patch(f"{TI}._DAEMON_ROOT", tmp_path),
            patch(f"{TI}._UNIT_DIR", install_dir),
        ):
            assert handle_command("install-timer", []) is True
        for unit in (service, timer):
            copied = install_dir / unit.name
            assert copied.read_text(encoding="utf-8") == unit.read_text(encoding="utf-8"), unit.name
        assert [c.args for c in mock_systemctl.call_args_list] == [
            ("daemon-reload",),
            ("enable", "daemon-tick.timer"),
            ("start", "daemon-tick.timer"),
        ]

    @patch(f"{TI}._run_systemctl", return_value=False)
    def test_install_systemctl_fails(self, mock_systemctl, tmp_path):
        """install-timer exits 1 when systemctl fails, and stops at the first refusal."""
        _units(tmp_path)
        install_dir = tmp_path / "systemd"
        install_dir.mkdir()

        with (
            patch(f"{TI}._DAEMON_ROOT", tmp_path),
            patch(f"{TI}._UNIT_DIR", install_dir),
            pytest.raises(SystemExit) as stopped,
        ):
            handle_command("install-timer", [])
        assert stopped.value.code == 1
        mock_systemctl.assert_called_once_with("daemon-reload")


class TestUninstall:
    """Tests for the uninstall flow.

    Installed is a unit file in _UNIT_DIR or a unit systemd knows, so the stop is always asked.
    """

    @patch(f"{TI}._run_systemctl", side_effect=_systemd_that_knows_no_timer)
    def test_uninstall_files_not_present(self, mock_systemctl, tmp_path, capsys):
        """uninstall-timer of a timer that is not installed is a success: stop answers not loaded, nothing to remove."""
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        with patch(f"{TI}._UNIT_DIR", unit_dir):
            assert _exit_of("uninstall-timer") == 0
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
            call("daemon-reload"),
        ]
        out = capsys.readouterr().out
        assert "nothing to remove" in out, f"an uninstall with no unit file must say so: {out!r}"
        assert list(unit_dir.iterdir()) == [], "an uninstall with nothing to remove must create nothing"

    @patch(f"{TI}._run_systemctl", return_value=True)
    def test_a_timer_still_loaded_after_its_files_were_deleted_is_stopped(self, mock_systemctl, tmp_path):
        """A timer systemd still runs, whose unit files were deleted by hand, is stopped and reloaded away.

        Disable is not asked: it needs the unit file, which is gone.
        """
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        with patch(f"{TI}._UNIT_DIR", unit_dir):
            assert _exit_of("uninstall-timer") == 0
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
            call("daemon-reload"),
        ]

    @patch(f"{TI}._run_systemctl", side_effect=_systemd_that_knows_no_timer)
    def test_a_half_install_systemd_does_not_know_is_removed(self, mock_systemctl, tmp_path):
        """One unit file stands and systemd does not know the timer: the file goes and the verb exits 0."""
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        service, _ = _units(tmp_path)
        half = unit_dir / service.name
        half.write_text(service.read_text(encoding="utf-8"), encoding="utf-8")

        with (
            patch(f"{TI}._UNIT_DIR", unit_dir),
            patch("aipass.trigger.apps.modules.core.trigger.fire") as fire,
        ):
            assert _exit_of("uninstall-timer") == 0
        assert not half.exists(), "the half install must be removed"
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
            call("daemon-reload"),
        ]
        fire.assert_called_once_with("file_deleted", path=str(half), source="timer_install")

    @patch(f"{TI}._run_systemctl", side_effect=_host_with_no_systemctl)
    def test_no_systemctl_and_no_unit_file_is_not_installed(self, mock_systemctl, tmp_path, capsys):
        """No systemctl and no unit file: nothing is installed, exit 0, and nothing more is asked."""
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        with patch(f"{TI}._UNIT_DIR", unit_dir):
            assert _exit_of("uninstall-timer") == 0
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
        ]
        out = capsys.readouterr().out
        assert "Not installed:" in out, f"an uninstall with nothing installed must say so: {out!r}"

    @patch(f"{TI}._run_systemctl", side_effect=_host_with_no_systemctl)
    def test_no_systemctl_with_a_unit_file_fails_and_keeps_it(self, mock_systemctl, tmp_path, capsys):
        """No systemctl while a unit file stands: the stop is named as the failed step, exit 1, the file stays."""
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        service, timer = _units(unit_dir)
        with patch(f"{TI}._UNIT_DIR", unit_dir):
            assert _exit_of("uninstall-timer") == 1
        assert service.exists() and timer.exists(), "a timer that could not be stopped keeps its files"
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
        ]
        assert "uninstall-timer: systemctl --user stop daemon-tick.timer failed" in capsys.readouterr().err

    @patch(f"{TI}._run_systemctl", return_value=True)
    def test_uninstall_removes_files(self, mock_systemctl, tmp_path):
        """uninstall-timer stops, disables, removes both unit files, reloads, and fires file_deleted per file.

        fire is patched on the core `trigger` object _uninstall imports at call time; unpatched it hits the real bus.
        """
        service, timer = _units(tmp_path)

        with (
            patch(f"{TI}._UNIT_DIR", tmp_path),
            patch("aipass.trigger.apps.modules.core.trigger.fire") as fire,
        ):
            assert _exit_of("uninstall-timer") == 0
        assert not service.exists()
        assert not timer.exists()
        assert mock_systemctl.call_args_list == [
            call("stop", "daemon-tick.timer", not_loaded_ok=True, not_found_ok=True),
            call("disable", "daemon-tick.timer"),
            call("daemon-reload"),
        ]
        assert [c.args for c in fire.call_args_list] == [("file_deleted",), ("file_deleted",)]
        assert [c.kwargs for c in fire.call_args_list] == [
            {"path": str(service), "source": "timer_install"},
            {"path": str(timer), "source": "timer_install"},
        ]

    @pytest.mark.parametrize("failing", ["stop", "disable", "daemon-reload"])
    def test_a_failed_step_while_installed_exits_nonzero_and_names_it(
        self, failing, _seal_timer_host_state, tmp_path, capsys
    ):
        """A stop, disable or daemon-reload that fails while the timer is installed exits 1 and names the step."""
        unit_dir = tmp_path / "_sealed_unit_dir"
        unit_dir.mkdir()
        service, timer = _units(unit_dir)
        _seal_timer_host_state.side_effect = lambda *args, **kwargs: args[0] != failing

        with (
            patch("aipass.trigger.apps.modules.core.trigger.fire") as fire,
            pytest.raises(SystemExit) as stopped,
        ):
            handle_command("uninstall-timer", [])
        assert stopped.value.code == 1
        err = capsys.readouterr().err
        assert f"uninstall-timer: systemctl --user {failing}" in err, err
        called = [c.args[0] for c in _seal_timer_host_state.call_args_list]
        steps = ["stop", "disable", "daemon-reload"]
        assert called == steps[: steps.index(failing) + 1], f"the uninstall did not walk up to {failing}: {called}"
        if failing == "daemon-reload":
            # Stop and disable held, so the files went before the reload was asked.
            assert not service.exists() and not timer.exists()
            assert fire.call_count == 2
        else:
            # A timer that would not stop or disable is still installed: its files stay.
            assert service.exists() and timer.exists()
            fire.assert_not_called()


class TestNoRealHomeWrites:
    """The suite must not touch the user's real home: `~/.aipass` holds real keys and databases."""

    def test_install_does_not_touch_the_real_home(self, tmp_path):
        """Red-first: fails while the path is computed inline at call time."""
        recorded = []

        def watch(event, args):
            if event == "os.mkdir" and args:
                recorded.append(str(args[0]))

        _units(tmp_path)
        install_dir = tmp_path / "systemd"
        install_dir.mkdir()
        state_dir = tmp_path / "state"

        sys.addaudithook(watch)
        with (
            patch(f"{TI}._DAEMON_ROOT", tmp_path),
            patch(f"{TI}._UNIT_DIR", install_dir),
            patch(f"{TI}._STATE_DIR", state_dir),
            patch(f"{TI}._run_systemctl", return_value=True),
        ):
            assert handle_command("install-timer", []) is True

        # Scoped to home state, not "outside tmp_path": the import-bound prax logger also writes into the
        # repo checkout, a defect this pin does not test and must not go red for.
        repo_root = Path(__file__).resolve().parents[4]
        home_state = [
            p
            for p in recorded
            if p.startswith(str(Path.home())) and not p.startswith(str(repo_root)) and not p.startswith(str(tmp_path))
        ]
        assert home_state == [], f"suite wrote into the real home: {home_state}"
        assert state_dir.is_dir(), "the state dir should still be created, just where it was told"
