# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for ai_mail tests - sandbox redirects, console pin, state reset
# Version: 1.9.0
# Created: 2026-03-05
# Modified: 2026-10-23
# Category: ai_mail/tests
# CHANGELOG (Max 5 entries):
#   - v1.9.0 (2026-10-23): sandboxed_central answers get_all_branches from the sandbox registry; daemon_* fixtures go
#   - v1.7.2 (2026-10-10): temp_test_dir, sample_test_data removed - spawn template leftovers no live test requests
#   - v1.7.1 (2026-10-08): monitor_wake_stubbed patches the public doors wake_sender, log_wake_result
#   - v1.7.0 (2026-10-08): wake_log_operation_suppressed, repo_root - test_wake.py's own
#     fixtures, shared by its split siblings; monitor_json_silenced, monitor_logger_silenced,
#     monitor_wake_stubbed, main_argv - the same for test_dispatch_monitor.py
#   - v1.5.1 (2026-09-29): sandboxed_central docstring names the live caller, not a retired name
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for ai_mail tests"""

import os
import tempfile

# Must be set before any prax import: the logger reads it at initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import sys
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import aipass.ai_mail.apps.handlers.central_writer as central_writer
import aipass.ai_mail.apps.handlers.dispatch.dispatch_monitor as monitor_mod
import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
import aipass.ai_mail.apps.handlers.email.contacts as contacts_mod
import aipass.ai_mail.apps.handlers.notify as notify_mod
import aipass.ai_mail.apps.handlers.registry.read as registry_read
import aipass.ai_mail.apps.modules.email_send as email_send_mod
import aipass.trigger.apps.modules.core as trigger_core
from aipass.ai_mail.apps.handlers.dispatch import register, report
from aipass.ai_mail.apps.handlers.json import json_handler
from aipass.ai_mail.apps.modules import email as email_mod
from aipass.cli.apps.modules import display

# Archived tests import modules that no longer exist; state the skip rather than rely on norecursedirs.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture
def email_modules_pinned():
    """Fail where a string-path patch would resolve to another module object."""
    # Fails rather than re-pinning: a quiet re-pin hides whichever test evicted them.
    assert sys.modules["aipass.ai_mail.apps.modules.email"] is email_mod
    assert sys.modules["aipass.ai_mail.apps.modules.email_send"] is email_send_mod


@pytest.fixture
def email_json_silenced():
    """Prevent log_operation from writing real JSON files during tests."""
    with (
        patch.object(email_mod, "json_handler") as mock_email_jh,
        patch.object(email_send_mod, "json_handler") as mock_send_jh,
    ):
        mock_email_jh.log_operation.return_value = True
        mock_send_jh.log_operation.return_value = True
        yield


@pytest.fixture
def wake_log_operation_suppressed(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(
        "aipass.ai_mail.apps.handlers.dispatch.wake.json_handler.log_operation",
        lambda *args, **kwargs: None,
    )


@pytest.fixture
def repo_root(tmp_path, monkeypatch):
    """Redirect _REPO_ROOT and BRANCH_REGISTRY to tmp_path."""
    registry_file = tmp_path / "AIPASS_REGISTRY.json"
    monkeypatch.setattr(wake_mod, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(wake_mod, "BRANCH_REGISTRY", registry_file)
    return tmp_path


@pytest.fixture
def monitor_json_silenced(monkeypatch):
    """Prevent json_handler.log_operation from touching real files."""
    monkeypatch.setattr(
        monitor_mod,
        "json_handler",
        MagicMock(),
    )


@pytest.fixture
def monitor_logger_silenced(monkeypatch):
    """Suppress logger output during tests."""
    monkeypatch.setattr(monitor_mod, "logger", MagicMock())


@pytest.fixture
def monitor_wake_stubbed(monkeypatch):
    """Prevent wake_sender from importing/calling real wake_branch in unrelated tests."""
    monkeypatch.setattr(monitor_mod, "wake_sender", MagicMock(return_value="skipped_sender"))
    monkeypatch.setattr(monitor_mod, "log_wake_result", MagicMock())


@pytest.fixture
def main_argv(tmp_path):
    """Build sys.argv and supporting files for main() tests."""
    branch_dir = tmp_path / "branch"
    ai_mail_dir = branch_dir / ".ai_mail.local"
    ai_mail_dir.mkdir(parents=True)
    logs_dir = branch_dir / "logs"
    logs_dir.mkdir(parents=True)

    lock_file = ai_mail_dir / ".dispatch.lock"
    lock_file.write_text("{}", encoding="utf-8")

    stderr_log = tmp_path / "stderr.log"
    stderr_log.write_text("", encoding="utf-8")

    argv = [
        "dispatch_monitor.py",
        "@test_branch",
        str(lock_file),
        "@sender",
        str(stderr_log),
        "--",
        "claude",
        "-c",
        "--model",
        "opus",
    ]
    return argv, lock_file, stderr_log


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


def _branches_of(registry: Path) -> list:
    """get_all_branches, answered from `registry` in place of the live one."""
    with patch.object(registry_read, "BRANCH_REGISTRY_PATH", registry):
        return registry_read.get_all_branches()


@pytest.fixture(autouse=True)
def sandboxed_central(tmp_path, monkeypatch) -> None:
    """No test reaches the live central file: update_central scans and writes under tmp_path."""
    central = tmp_path / "central_sandbox"
    registry = central / "AIPASS_REGISTRY.json"
    monkeypatch.setattr(central_writer, "_REPO_ROOT", central)
    monkeypatch.setattr(central_writer, "BRANCH_REGISTRY", registry)
    monkeypatch.setattr(central_writer, "get_all_branches", lambda: _branches_of(registry))
    monkeypatch.setattr(central_writer, "AI_CENTRAL_DIR", central / ".ai_central")
    monkeypatch.setattr(central_writer, "CENTRAL_FILE", central / ".ai_central" / "AI_MAIL.central.json")


class _BusRecorder:
    """Stands where trigger stands: records each fire and delivers it nowhere."""

    def __init__(self) -> None:
        self.fires: list[tuple[str, dict]] = []

    def fire(self, event: str, **data) -> None:
        self.fires.append((event, data))

    def events(self) -> list[str]:
        return [event for event, _ in self.fires]


@pytest.fixture(autouse=True)
def recorded_bus(monkeypatch) -> _BusRecorder:
    """No test fires on the real trigger bus; a test asserts what fired here."""
    # report/send/dispatch import trigger at call time, email_send binds it at import: both homes replaced.
    recorder = _BusRecorder()
    monkeypatch.setattr(trigger_core, "trigger", recorder)
    monkeypatch.setattr(trigger_core.Trigger, "fire", staticmethod(recorder.fire))
    monkeypatch.setattr(email_send_mod, "trigger", recorder)
    return recorder


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir."""
    # Own subdirectory: a seam AT tmp_path creates tmp_path/ai_mail/, colliding with tests that build it.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def _isolate_notification_feed(tmp_path, monkeypatch):
    """Point the notification feed at tmp_path for EVERY test."""
    monkeypatch.setattr(notify_mod, "FEED_PATH", tmp_path / "feed" / "notifications.jsonl")


@pytest.fixture(autouse=True)
def _no_real_mail_from_tests(monkeypatch):
    """Refuse any test that shells out to `drone @ai_mail send` (or dispatch)."""
    # The identity fence allows a dispatched agent's shell; send-path tests mock subprocess.run themselves.
    import subprocess

    real_run = subprocess.run

    def _guarded(cmd, *args, **kwargs):
        if isinstance(cmd, (list, tuple)) and len(cmd) >= 3:
            argv = [str(c) for c in cmd[:3]]
            if argv[0].endswith("drone") and argv[1] == "@ai_mail" and argv[2] in ("send", "email", "dispatch"):
                raise AssertionError(
                    f"test tried to deliver REAL mail: {' '.join(str(c) for c in cmd[:4])} — "
                    "mock subprocess.run in this test"
                )
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", _guarded)


@pytest.fixture(autouse=True)
def _strip_ambient_identity_source(monkeypatch):
    """Clear AIPASS_CALLER_IDENTITY_SOURCE for EVERY test."""
    # A credential: an ambient value from a dispatched agent's shell silently disables the identity fence.
    monkeypatch.delenv("AIPASS_CALLER_IDENTITY_SOURCE", raising=False)

    # Same trap: an ambient dispatch id would let a stamp test pass on the wrong id.
    monkeypatch.delenv("AIPASS_DISPATCH_ID", raising=False)


@pytest.fixture(autouse=True)
def _isolate_wake_depth(monkeypatch):
    """Start EVERY test with AIPASS_WAKE_DEPTH absent, and undo whatever it becomes."""
    # wake_sender() writes os.environ directly; setenv first records the undo, delenv gives the clean start.
    monkeypatch.setenv("AIPASS_WAKE_DEPTH", "0")
    monkeypatch.delenv("AIPASS_WAKE_DEPTH")


@pytest.fixture(autouse=True)
def _isolate_dispatch_register(tmp_path, monkeypatch):
    """Point the register and the reports directory at tmp_path for EVERY test."""
    # Patches the root, not the functions, so an explicit repo_root= still wins.
    # Never tmp_path itself: find_caller_registry tests control tmp_path's own registry marker.
    root = tmp_path / ".dispatch_register_root"
    root.mkdir(exist_ok=True)
    (root / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(register, "find_repo_root", lambda: root)
    monkeypatch.setattr(report, "find_repo_root", lambda: root)


@pytest.fixture(autouse=True)
def _isolate_contacts_file(tmp_path, monkeypatch):
    """Point CONTACTS_FILE at tmp_path for EVERY test."""
    # Delivery auto-registers contacts; leaked rows get trusted as verified identity.
    monkeypatch.setattr(contacts_mod, "CONTACTS_FILE", tmp_path / "contacts" / "contacts.json")
