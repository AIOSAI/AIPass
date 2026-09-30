# =================== AIPass ====================
# Name: test_service_control.py
# Description: Tests for the systemd unit lifecycle of the log watcher
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-09-28
# =============================================

"""Tests for apps/handlers/service_control.py, the systemd control surface extracted from medic.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — medic's start/stop decisions on top of _systemctl, in test_medic.py
# seedgo: no-test-needed(external) — what systemctl itself does with SERVICE_NAME; AIPass tests only its own files

import subprocess
import tempfile
from pathlib import Path

import pytest

from aipass.trigger.apps.handlers import service_control

# Nothing here shells out to the real systemctl: the host fact is stated per
# test through PATH (systemd_present / systemd_absent), and every test that
# can reach exec replaces subprocess.run, the boundary under test.


class RecordingLogger:
    """Captures the warnings the door emits, formatted as the log would."""

    def __init__(self) -> None:
        self.warnings: list[str] = []

    def warning(self, msg, *args) -> None:
        self.warnings.append(msg % args if args else str(msg))

    def info(self, msg, *args) -> None:
        pass


@pytest.fixture
def systemd_present(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A host that has systemctl on PATH - stated, never inherited: PATH holds only an inert stub."""
    bin_dir = tmp_path / "systemd_bin"
    bin_dir.mkdir()
    for name in ("systemctl", "systemctl.exe"):  # the .exe is what which() finds on Windows
        stub = bin_dir / name
        stub.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        stub.chmod(0o755)
    monkeypatch.setenv("PATH", str(bin_dir))


@pytest.fixture
def systemd_absent(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """A host with no systemd at all: macOS, Windows, a bare container - PATH holds nothing."""
    empty = tmp_path / "empty_bin"
    empty.mkdir()
    monkeypatch.setenv("PATH", str(empty))


@pytest.fixture
def recorded_ops(monkeypatch: pytest.MonkeyPatch) -> list[tuple]:
    """Stand-in for json_handler.log_operation, which writes the live trigger_json/ logs."""
    ops: list[tuple] = []
    monkeypatch.setattr(service_control.json_handler, "log_operation", lambda *a, **kw: ops.append((a, kw)))
    return ops


@pytest.fixture
def recorded_log(monkeypatch: pytest.MonkeyPatch) -> RecordingLogger:
    recorder = RecordingLogger()
    monkeypatch.setattr(service_control, "logger", recorder)
    return recorder


class TestSystemctl:
    """_systemctl reports whether the command succeeded, and never raises."""

    def test_zero_exit_is_success(self, monkeypatch: pytest.MonkeyPatch, systemd_present) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(service_control.subprocess, "run", fake_run)

        assert service_control._systemctl("start") is True
        assert calls == [["systemctl", "--user", "start", service_control.SERVICE_NAME]]

    def test_non_zero_exit_is_failure(self, monkeypatch: pytest.MonkeyPatch, systemd_present) -> None:
        """The mutant that survived: returning True regardless dies here."""
        monkeypatch.setattr(
            service_control.subprocess,
            "run",
            lambda cmd, **kw: subprocess.CompletedProcess(cmd, 3, "", "unit not found"),
        )

        assert service_control._systemctl("start") is False

    def test_a_hung_systemctl_is_unanswered_not_a_failure(
        self, monkeypatch: pytest.MonkeyPatch, systemd_present
    ) -> None:
        """A hung systemctl must not take the caller down, and must not read as "stopped".

        None is the answer systemctl never gave; False is a unit that answered no.
        Red first 2026-09-28 on the code that answered False for both.
        Mutant 2026-09-28: the generic except answering False again reddens this.
        """

        def boom(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd, 10)

        monkeypatch.setattr(service_control.subprocess, "run", boom)

        assert service_control._systemctl("is-active") is None


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

    def test_existing_unit_short_circuits_before_any_write(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_present
    ) -> None:
        unit = tmp_path / "trigger-log-watcher.service"
        unit.write_text("[Unit]\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)

        def must_not_run(*a, **kw):
            raise AssertionError("systemctl was called for an already-installed unit")

        monkeypatch.setattr(service_control.subprocess, "run", must_not_run)

        assert service_control._ensure_service_installed() is True

    def test_a_missing_template_refuses_rather_than_writing_a_broken_unit(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_present
    ) -> None:
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", tmp_path / "absent.service")
        monkeypatch.setattr(service_control, "_TEMPLATE_PATH", tmp_path / "absent.template")

        assert service_control._ensure_service_installed() is False


class TestNoSystemdHost:
    """The 2026-09-12 cure: no systemctl is a named refusal, never a False.

    seedgo host_portability, arm B. macOS and Windows have no systemctl and a
    Linux container may have none; a missing binary raises FileNotFoundError
    out of exec, so ``check=False`` does not save the caller. Every case here
    fails on the pre-cure code, which shelled out blind.
    """

    def test_a_host_without_systemctl_never_reaches_exec(
        self, monkeypatch: pytest.MonkeyPatch, systemd_absent, recorded_log: RecordingLogger
    ) -> None:
        def must_not_run(*a, **kw):
            raise AssertionError("systemctl was executed on a host that has none")

        monkeypatch.setattr(service_control.subprocess, "run", must_not_run)

        assert service_control._systemctl("start") is None
        assert any("no systemctl" in line and "systemd" in line for line in recorded_log.warnings), (
            f"the refusal must name the missing host fact, got {recorded_log.warnings}"
        )

    def test_the_refusal_names_the_action_it_refused(
        self, monkeypatch: pytest.MonkeyPatch, systemd_absent, recorded_log: RecordingLogger
    ) -> None:
        """ "systemctl failed" sends a reader to the unit; this sends them to the host."""
        ran: list[tuple] = []
        monkeypatch.setattr(service_control.subprocess, "run", lambda *a, **kw: ran.append(a))

        service_control._systemctl("is-active")

        assert any("is-active" in line for line in recorded_log.warnings), recorded_log.warnings
        assert ran == [], "the refusal must come before exec"

    def test_systemd_available_reads_the_path_not_the_platform(self, systemd_absent) -> None:
        assert service_control.systemd_available() is False

    def test_systemd_available_is_true_when_the_binary_is_there(self, systemd_present) -> None:
        assert service_control.systemd_available() is True

    def test_install_refuses_before_writing_a_unit_no_systemd_can_read(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_absent, recorded_log: RecordingLogger
    ) -> None:
        unit = tmp_path / "trigger-log-watcher.service"
        template = tmp_path / "unit.template"
        template.write_text("[Service]\nExecStart={{AIPASS_HOME}}/run\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)
        monkeypatch.setattr(service_control, "_TEMPLATE_PATH", template)

        assert service_control._ensure_service_installed() is False
        assert not unit.exists(), "a unit file was installed on a host with no systemd"

    def test_a_unit_file_from_another_host_is_not_a_ready_service(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_absent
    ) -> None:
        """The probe comes before the exists() short-circuit, or True is a lie."""
        unit = tmp_path / "trigger-log-watcher.service"
        unit.write_text("[Unit]\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)

        assert service_control._ensure_service_installed() is False

    def test_a_binary_that_vanishes_between_probe_and_exec_is_still_a_refusal(
        self, monkeypatch: pytest.MonkeyPatch, systemd_present, recorded_log: RecordingLogger
    ) -> None:
        """PATH can change under us; FileNotFoundError says which fact was missing."""

        def gone(cmd, **kwargs):
            raise FileNotFoundError(2, "No such file or directory: 'systemctl'")

        monkeypatch.setattr(service_control.subprocess, "run", gone)

        assert service_control._systemctl("stop") is None
        assert any("no systemctl" in line for line in recorded_log.warnings), recorded_log.warnings


class TestInstallArgv:
    """What the install actually says to systemd, argv by argv."""

    def test_daemon_reload_carries_no_unit_name_and_enable_carries_one(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_present, recorded_ops
    ) -> None:
        """Measured 2026-09-12: ``daemon-reload <unit>`` exits 1, "Too many
        arguments." — the reload between install and enable had never run.
        """
        unit = tmp_path / "trigger-log-watcher.service"
        template = tmp_path / "unit.template"
        template.write_text("[Service]\nExecStart={{AIPASS_HOME}}/run\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)
        monkeypatch.setattr(service_control, "_TEMPLATE_PATH", template)
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))

        calls: list[list[str]] = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return subprocess.CompletedProcess(cmd, 0, "", "")

        monkeypatch.setattr(service_control.subprocess, "run", fake_run)

        assert service_control._ensure_service_installed() is True
        assert calls == [
            ["systemctl", "--user", "daemon-reload"],
            ["systemctl", "--user", "enable", service_control.SERVICE_NAME],
        ]
        assert [op[0][0] for op in recorded_ops] == ["systemd_unit_installed"]

    def test_the_rendered_unit_carries_the_resolved_home(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path, systemd_present, recorded_ops
    ) -> None:
        """The unit on disk and the install record both carry it (mutant: the install record dropped)."""
        unit = tmp_path / "trigger-log-watcher.service"
        template = tmp_path / "unit.template"
        template.write_text("ExecStart={{AIPASS_HOME}}/run\n", encoding="utf-8")
        monkeypatch.setattr(service_control, "_SERVICE_UNIT_PATH", unit)
        monkeypatch.setattr(service_control, "_TEMPLATE_PATH", template)
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
        monkeypatch.setattr(
            service_control.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, "", "")
        )

        assert service_control._ensure_service_installed() is True
        assert unit.read_text(encoding="utf-8") == f"ExecStart={tmp_path}/run\n"
        assert recorded_ops == [
            (
                ("systemd_unit_installed", {"unit": str(unit), "aipass_home": str(tmp_path)}),
                {"module_name": service_control.MODULE_NAME},
            )
        ]
