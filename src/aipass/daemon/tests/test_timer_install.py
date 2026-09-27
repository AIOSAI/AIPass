# =================== AIPass ====================
# Name: test_timer_install.py
# Description: Tests for the timer_install module (systemd user timer installer)
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/timer_install.py — install-timer and uninstall-timer, the systemd user timer."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — shutil.copy2's metadata copy; the copied files are asserted on disk, not their mode bits
# seedgo: no-test-needed(ruff) — that timer_install.py parses and imports; every test here imports it first

import subprocess

import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

from aipass.daemon.apps.modules.timer_install import (
    handle_command,
    HANDLED_COMMANDS,
    _run_systemctl,
)

# install and uninstall are reached the way a user reaches them: through
# handle_command, inside conftest's session-wide seal on _run_systemctl,
# _UNIT_DIR and _STATE_DIR. A failed install is sys.exit(1) at the router.
TI = "aipass.daemon.apps.modules.timer_install"


def _units(directory: Path) -> tuple:
    """Write the two unit files the installer copies, and return them."""
    service = directory / "daemon-tick.service"
    timer = directory / "daemon-tick.timer"
    service.write_text("[Unit]\nDescription=tick service\n", encoding="utf-8")
    timer.write_text("[Unit]\nDescription=tick timer\n", encoding="utf-8")
    return service, timer


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
        # The seam, named here even though --help returns before the gate and
        # before _install() ever runs. conftest's autouse seal already covers
        # this, but both guards live outside the unit, and a reader arriving at
        # "handle_command('install-timer', ...)" has to prove the short-circuit
        # for themselves before they can believe nothing happened.
        with patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True):
            result = handle_command("install-timer", ["--help"])
        out = capsys.readouterr().out
        assert result is True
        # The capture was requested and never read, so the docstring's "prints
        # usage" half was never checked. The heading names both verbs this
        # module owns; another module's help would not carry it.
        assert "install-timer / uninstall-timer — Daemon Scheduler Timer" in out, (
            f"install-timer --help printed: {out[:200]!r}"
        )
        assert "USAGE:" in out, "install-timer --help must print a USAGE: block"


class TestRunSystemctl:
    """Tests for the systemctl wrapper."""

    @patch("subprocess.run")
    def test_success(self, mock_run):
        """Successful systemctl returns True."""
        mock_run.return_value = MagicMock(returncode=0)
        assert _run_systemctl("status", "daemon-tick.timer") is True

    @patch("subprocess.run")
    def test_failure_returncode(self, mock_run):
        """Non-zero returncode returns False."""
        mock_run.return_value = MagicMock(returncode=1, stderr="unit not found")
        assert _run_systemctl("start", "daemon-tick.timer") is False

    @patch("subprocess.run", side_effect=FileNotFoundError)
    def test_systemctl_not_found(self, mock_run, capsys):
        """Missing systemctl returns False and says systemd is not there."""
        assert _run_systemctl("status", "daemon-tick.timer") is False
        said = "".join(capsys.readouterr())
        assert "systemctl not found — systemd not available" in said, said

    @patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=15),
    )
    def test_timeout(self, mock_run, capsys):
        """Timed-out systemctl returns False and names the timeout, not a missing systemd.

        Mutant killed: the TimeoutExpired branch printing the not-found message.
        """
        assert _run_systemctl("status", "daemon-tick.timer") is False
        said = "".join(capsys.readouterr())
        assert "systemctl timed out" in said, said
        assert "not found" not in said, f"a timeout reported as a missing systemctl: {said}"


class TestInstall:
    @pytest.fixture(autouse=True)
    def _no_real_home(self, tmp_path_factory):
        """Redirect the shared state dir for EVERY test in this class.

        Autouse rather than a per-test patch, deliberately. Adding the
        _STATE_DIR seam fixed nothing on its own: the pre-existing
        test_install_success still patched only _DAEMON_ROOT and _UNIT_DIR, so
        the re-run artifact still showed the same single os.mkdir on the real
        ~/.aipass. A seam a test can forget to use is not a fix — the next
        _install() test would reach the real home again and the suite would
        stay green while doing it.
        """
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
        """A good install copies both units into the unit dir and runs reload, enable, start.

        Mutant killed: the shutil.copy2 line in _install dropped (the copy was
        mocked before, so nothing looked at the files).
        """
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
        """install-timer exits 1 when systemctl fails, and stops at the first refusal.

        Mutant killed: _install ignoring a failed daemon-reload and going on to enable.
        """
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
    """Tests for the uninstall flow."""

    @patch(f"{TI}._run_systemctl", return_value=True)
    def test_uninstall_files_not_present(self, mock_systemctl, tmp_path):
        """uninstall-timer succeeds even when the unit files are already absent, and still stops the timer.

        Mutant killed: _uninstall's stop call dropped.
        """
        unit_dir = tmp_path / "units"
        unit_dir.mkdir()
        with patch(f"{TI}._UNIT_DIR", unit_dir):
            assert handle_command("uninstall-timer", []) is True
        # Nothing to remove is not a reason to leave the timer running.
        assert [c.args for c in mock_systemctl.call_args_list] == [
            ("stop", "daemon-tick.timer"),
            ("disable", "daemon-tick.timer"),
            ("daemon-reload",),
        ]
        assert list(unit_dir.iterdir()) == [], "an uninstall with nothing to remove must create nothing"

    @patch(f"{TI}._run_systemctl", return_value=True)
    def test_uninstall_removes_files(self, mock_systemctl, tmp_path):
        """uninstall-timer removes both unit files from the unit directory."""
        service, timer = _units(tmp_path)

        with patch(f"{TI}._UNIT_DIR", tmp_path):
            assert handle_command("uninstall-timer", []) is True
        assert not service.exists()
        assert not timer.exists()


class TestNoRealHomeWrites:
    """The suite must not touch the user's real home.

    Found by `drone @seedgo audit tests @daemon` and confirmed by @seedgo as
    the ONE hygiene record in daemon's artifact that genuinely left the copy —
    everything else in that 1097 is real prax logging firing under an
    unrebindable module-scope binding, which is not this branch's to fix.

    `~/.aipass` is not a scratch directory: it holds `admin_grant.key`,
    `commons.db` with its -shm/-wal siblings, and `telegram_bots/`. The mkdir
    itself was harmless (`exist_ok=True` against a directory that already
    exists), so this is a seam defect rather than damage — but the next write
    added after that line would land in real state on every machine that runs
    the suite, and no test could have noticed.
    """

    def test_install_does_not_touch_the_real_home(self, tmp_path):
        """Red-first: fails while the path is computed inline at call time.

        The two existing patches (_DAEMON_ROOT, _UNIT_DIR) reach module
        constants. The .aipass mkdir was `Path.home().joinpath(...)` evaluated
        inside _install(), so no patch could reach it and this assertion caught
        a real os.mkdir on the real home.
        """
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

        # Scoped to the user's HOME STATE, deliberately, and not to "anything
        # outside tmp_path". A broader assertion also catches the prax/trigger/
        # daemon_json logging writes into the repo checkout — real, measured
        # (66 in this one test), and NOT this branch's to fix: they come from
        # `from aipass.prax import logger` binding the logger object at import,
        # which no conftest can rebind. @seedgo owns that standard and has
        # widened it; @prax has the contract question. Asserting on them here
        # would make this pin fail for a reason it is not testing, and a test
        # that goes red for someone else's open defect gets muted, not fixed.
        repo_root = Path(__file__).resolve().parents[4]
        home_state = [
            p
            for p in recorded
            if p.startswith(str(Path.home())) and not p.startswith(str(repo_root)) and not p.startswith(str(tmp_path))
        ]
        assert home_state == [], f"suite wrote into the real home: {home_state}"
        assert state_dir.is_dir(), "the state dir should still be created, just where it was told"
