# =================== AIPass ====================
# Name: conftest.py
# Description: Shared pytest fixtures for devpulse tests
# Version: 1.4.0
# Created: 2025-11-08
# Modified: 2026-10-17
# =============================================

"""Shared pytest fixtures for devpulse tests."""

import os
import sys
import tempfile

# Before any import of the json shim: the only redirect a suite needs.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from pathlib import Path
from typing import Generator

from aipass.cli.apps.modules import display
from aipass.devpulse.apps.handlers.json import json_handler
from aipass.devpulse.apps.handlers.watchdog import registry as watch_registry
from aipass.devpulse.apps.handlers.watchdog import timer as watch_timer


def pytest_configure(config: pytest.Config) -> None:
    # Not pytest.ini: the composed run never reads it, and --strict-markers fails an unknown marker.
    config.addinivalue_line("markers", "integration: live-dispatch integration tests (WATCHDOG_INTEGRATION=1)")
    config.addinivalue_line(
        "markers", "live_default_store: reads the watchdog's real default store path; the seal stands aside"
    )


@pytest.fixture(autouse=True)
def sealed_watchdog_store(request: pytest.FixtureRequest, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point the watchdog's default stores at tmp_path: unsealed, a sweep signals the seat's live wires."""
    if request.node.get_closest_marker("live_default_store"):
        return
    store = tmp_path / "_sealed_watchdog"
    monkeypatch.setattr(watch_registry, "default_storage_path", lambda: store / "watchdog_active.json")
    monkeypatch.setattr(watch_timer, "default_storage_path", lambda: store / "watchdog_timers.json")


class _SysAs:
    """One module's ``sys``: a pretended ``platform``, every other attribute the real ``sys``."""

    def __init__(self, platform: str) -> None:
        self.platform = platform

    def __getattr__(self, name: str):
        return getattr(sys, name)


@pytest.fixture
def pretend_platform(monkeypatch: pytest.MonkeyPatch):
    """Make ONE module see another ``sys.platform``; setting sys.platform itself is process-wide."""

    def _pretend(module, platform: str) -> None:
        monkeypatch.setattr(module, "sys", _SysAs(platform))

    return _pretend


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console per print, and the width differs by host and capture mode."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a per-test sandbox, measured off the shim so it cannot drift."""
    # A seam AT tmp_path would create tmp_path/<branch>/, colliding with a test's own dir of that name.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def hermetic_mail_doors(tmp_path_factory, monkeypatch):
    """Point @ai_mail's path doors at a fake live repo that carries the marker.

    The re-root walks up to AIPASS_REGISTRY.json, which no fresh checkout (CI) has.
    Opt-in, not branch-wide, so a test that MEANS live resolution can still exist.
    """
    live = tmp_path_factory.mktemp("live_mail_repo")
    (live / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    aipass_dir = live / ".aipass"
    aipass_dir.mkdir()
    feed = aipass_dir / "notifications.jsonl"
    register = aipass_dir / "dispatch_register.jsonl"
    monkeypatch.setattr("aipass.ai_mail.feed_path", lambda: feed)
    # One variable moves @ai_mail's register and its register_path door; its fence refuses a private patch.
    monkeypatch.setenv("AIPASS_DISPATCH_REGISTER", str(register))
    return live
