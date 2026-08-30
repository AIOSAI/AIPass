# =================== AIPass ====================
# Name: test_timer_install.py
# Description: Tests for the timer_install module (systemd user timer installer)
# Version: 1.0.0
# Created: 2026-06-25
# Modified: 2026-06-25
# =============================================

"""Tests for the timer_install module (systemd user timer installer)."""

import subprocess

import pytest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

from aipass.daemon.apps.modules.timer_install import (
    handle_command,
    HANDLED_COMMANDS,
    _run_systemctl,
    _install,
    _uninstall,
)


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
        """Help flag prints usage and returns True."""
        result = handle_command("install-timer", ["--help"])
        assert result is True


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
    def test_systemctl_not_found(self, mock_run):
        """Missing systemctl returns False."""
        assert _run_systemctl("status", "daemon-tick.timer") is False

    @patch(
        "subprocess.run",
        side_effect=subprocess.TimeoutExpired(cmd="systemctl", timeout=15),
    )
    def test_timeout(self, mock_run):
        """Timed-out systemctl returns False."""
        assert _run_systemctl("status", "daemon-tick.timer") is False


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

    def test_install_missing_unit_file(self):
        """Returns 1 when unit files are missing."""
        with patch(
            "aipass.daemon.apps.modules.timer_install._DAEMON_ROOT",
            Path("/nonexistent"),
        ):
            result = _install()
            assert result == 1

    @patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True)
    @patch("shutil.copy2")
    def test_install_success(self, mock_copy, mock_systemctl, tmp_path):
        """Successful install copies files and calls systemctl 3 times."""
        service = tmp_path / "daemon-tick.service"
        timer = tmp_path / "daemon-tick.timer"
        service.write_text("[Unit]\n")
        timer.write_text("[Unit]\n")

        install_dir = tmp_path / "systemd"
        install_dir.mkdir()

        with (
            patch("aipass.daemon.apps.modules.timer_install._DAEMON_ROOT", tmp_path),
            patch("aipass.daemon.apps.modules.timer_install._UNIT_DIR", install_dir),
        ):
            result = _install()
            assert result == 0
            assert mock_systemctl.call_count == 3

    @patch("aipass.daemon.apps.modules.timer_install._run_systemctl")
    @patch("shutil.copy2")
    def test_install_systemctl_fails(self, mock_copy, mock_systemctl, tmp_path):
        """Returns 1 when systemctl fails."""
        service = tmp_path / "daemon-tick.service"
        timer = tmp_path / "daemon-tick.timer"
        service.write_text("[Unit]\n")
        timer.write_text("[Unit]\n")

        install_dir = tmp_path / "systemd"
        install_dir.mkdir()

        mock_systemctl.return_value = False

        with (
            patch("aipass.daemon.apps.modules.timer_install._DAEMON_ROOT", tmp_path),
            patch("aipass.daemon.apps.modules.timer_install._UNIT_DIR", install_dir),
        ):
            result = _install()
            assert result == 1


class TestUninstall:
    """Tests for the uninstall flow."""

    @patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True)
    def test_uninstall_files_not_present(self, mock_systemctl, tmp_path):
        """Returns 0 even when unit files are already absent."""
        with patch("aipass.daemon.apps.modules.timer_install._UNIT_DIR", tmp_path):
            result = _uninstall()
            assert result == 0

    @patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True)
    def test_uninstall_removes_files(self, mock_systemctl, tmp_path):
        """Removes unit files from the target directory."""
        service = tmp_path / "daemon-tick.service"
        timer = tmp_path / "daemon-tick.timer"
        service.write_text("[Unit]\n")
        timer.write_text("[Unit]\n")

        with patch("aipass.daemon.apps.modules.timer_install._UNIT_DIR", tmp_path):
            result = _uninstall()
            assert result == 0
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

        service = tmp_path / "daemon-tick.service"
        timer = tmp_path / "daemon-tick.timer"
        service.write_text("[Unit]\n")
        timer.write_text("[Unit]\n")
        install_dir = tmp_path / "systemd"
        install_dir.mkdir()
        state_dir = tmp_path / "state"

        sys.addaudithook(watch)
        with (
            patch("aipass.daemon.apps.modules.timer_install._DAEMON_ROOT", tmp_path),
            patch("aipass.daemon.apps.modules.timer_install._UNIT_DIR", install_dir),
            patch("aipass.daemon.apps.modules.timer_install._STATE_DIR", state_dir),
            patch("aipass.daemon.apps.modules.timer_install._run_systemctl", return_value=True),
            patch("shutil.copy2"),
        ):
            assert _install() == 0

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
            if p.startswith(str(Path.home()))
            and not p.startswith(str(repo_root))
            and not p.startswith(str(tmp_path))
        ]
        assert home_state == [], f"suite wrote into the real home: {home_state}"
        assert state_dir.is_dir(), "the state dir should still be created, just where it was told"
