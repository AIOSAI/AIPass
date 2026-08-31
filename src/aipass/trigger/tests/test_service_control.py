# ===================AIPASS====================
# META DATA HEADER
# Name: test_service_control.py - systemd unit lifecycle for the log watcher
# Date: 2026-08-31
# Version: 1.0.0
# Category: trigger/tests
# =============================================

"""Pins for the systemd control surface extracted from medic.py.

WHY THIS FILE EXISTS. The extraction (2026-08-31, medic.py 599 -> 526 lines)
did not create these functions, it revealed that nothing tested them: all forty
medic tests patch ``_systemctl`` out, so its body — the subprocess call, the
exit-code reading, the failure path — had never been executed by the suite.
Measured, not assumed: mutating ``return result.returncode == 0`` to
``return True`` left all 40 medic tests green.

Nothing here shells out to the real systemctl. The subprocess boundary is the
thing under test, so it is the thing replaced.
"""

import subprocess
import tempfile
from pathlib import Path

import pytest

from aipass.trigger.apps.handlers import service_control


class TestSystemctl:
    """_systemctl reports whether the command succeeded, and never raises."""

    def test_zero_exit_is_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(service_control.subprocess, "run", fake_run)

        assert service_control._systemctl("start") is True
        assert calls == [["systemctl", "--user", "start", service_control.SERVICE_NAME]]

    def test_non_zero_exit_is_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The mutant that survived: returning True regardless dies here."""
        monkeypatch.setattr(
            service_control.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3, "", "unit not found"),
        )

        assert service_control._systemctl("start") is False

    def test_a_raising_subprocess_is_reported_as_failure_not_an_exception(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A missing or hung systemctl must not take the caller down."""

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr(service_control.subprocess, "run", boom)

        assert service_control._systemctl("is-active") is False


class TestIsServiceActive:
    """_is_service_active asks systemctl exactly one question."""

    def test_delegates_to_is_active(self, monkeypatch: pytest.MonkeyPatch) -> None:
        asked: list[str] = []
        monkeypatch.setattr(service_control, "_systemctl", lambda action: asked.append(action) or True)

        assert service_control._is_service_active() is True
        assert asked == ["is-active"]


class TestGetAipassHome:
    """Env var wins; the walk is the last resort and never reads the cwd."""

    def test_env_var_takes_precedence_over_everything(self, monkeypatch: pytest.MonkeyPatch) -> None:
        home = Path(tempfile.gettempdir()) / "aipass_home_probe"
        monkeypatch.setenv("AIPASS_HOME", str(home))

        def must_not_run(*a, **kw):
            raise AssertionError("git was consulted despite AIPASS_HOME being set")

        monkeypatch.setattr(service_control.subprocess, "run", must_not_run)

        assert service_control._get_aipass_home() == home

    def test_git_toplevel_is_used_when_no_env_var(self, monkeypatch: pytest.MonkeyPatch) -> None:
        toplevel = str(Path(tempfile.gettempdir()) / "repo_from_git")
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.setattr(
            service_control.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, toplevel + "\n", ""),
        )

        assert service_control._get_aipass_home() == Path(toplevel)

    def test_falls_back_to_the_marker_walk_when_git_fails(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Never Path.cwd(): the round-4 ruling, still holding after the move."""
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        monkeypatch.setattr(
            service_control.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 128, "", "not a git repository"),
        )
        sentinel = Path(tempfile.gettempdir()) / "walked_root"
        monkeypatch.setattr(service_control, "find_repo_root", lambda **kw: sentinel)

        assert service_control._get_aipass_home() == sentinel


class TestEnsureServiceInstalled:
    """Installation is skipped when the unit is already there."""

    def test_existing_unit_short_circuits_before_any_write(self, monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
        unit = tmp_path / "trigger-log-watcher.service"
        unit.write_text("[Unit]\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)

        def must_not_run(*a, **kw):
            raise AssertionError("systemctl was called for an already-installed unit")

        monkeypatch.setattr(service_control.subprocess, "run", must_not_run)

        assert service_control._ensure_service_installed() is True

    def test_a_missing_template_refuses_rather_than_writing_a_broken_unit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path
    ) -> None:
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", tmp_path / "absent.service")
        monkeypatch.setattr(service_control, "_TEMPLATE_PATH", tmp_path / "absent.template")

        assert service_control._ensure_service_installed() is False
