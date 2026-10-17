# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for api tests
# Version: 2.1.2
# Created: 2026-03-05
# Modified: 2026-10-17
# Category: api/tests
#
# CHANGELOG (Max 5 entries):
#   - v2.1.0 (2026-09-27): Console width pin + command-state reset (C1, C2);
#     host imports hoisted to module level; mock_json_handler removed (unused)
#   - v2.0.0 (2026-03-27): Added mock_infrastructure, mock_logger,
#     mock_json_handler fixtures for test quality compliance
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Shared pytest fixtures for api tests"""

import os
import tempfile

# Set before any prax import: the logger reads it at initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import importlib
import json
import logging
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Generator
from unittest.mock import MagicMock, patch

import pytest

from aipass.cli.apps.modules import display

BRANCH_MODULE = "api"

_HANDLER_PKG = f"aipass.{BRANCH_MODULE}.apps.handlers"
_JSON_MOD_PATH = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# Imported explicitly: apps/__init__ no longer binds handlers, so a dotted patch cannot walk to it otherwise.
importlib.import_module(_HANDLER_PKG)
_json_mod = importlib.import_module(_JSON_MOD_PATH)

# Plain imports: none needs the [host] extra, and a catch-all would silently switch off its reset fixture.
from aipass.api.apps.handlers.host import attach as _attach
from aipass.api.apps.handlers.host import fleet as _fleet
from aipass.api.apps.handlers.host import refusals as _refusals

from aipass.api.apps.handlers.host import attach as host_attach
from aipass.api.tests.support_host_attach import _forced_tmux_which

PATCH_ATTACH_JSON = "aipass.api.apps.handlers.host.attach.json_handler"
PATCH_ATTACH_LOGGER = "aipass.api.apps.handlers.host.attach.logger"
PATCH_SECRETS_BASE = "aipass.api.apps.handlers.auth.secrets.SECRETS_BASE"
PATCH_SECRETS_JSON = "aipass.api.apps.handlers.auth.secrets.json_handler"
PATCH_SECRETS_LOGGER = "aipass.api.apps.handlers.auth.secrets.logger"
PATCH_TOKENS_JSON = "aipass.api.apps.handlers.host.tokens.json_handler"
PATCH_TOKENS_LOGGER = "aipass.api.apps.handlers.host.tokens.logger"
# The project this server is seated in, as the registry names it.
SEAT = "AIPass"


@pytest.fixture
def quiet():
    """Silence the attach lane's own logging."""
    with patch(PATCH_ATTACH_JSON), patch(PATCH_ATTACH_LOGGER):
        yield


@pytest.fixture
def tmux_preflight(monkeypatch: Any):
    """Satisfy `open_attach`'s tmux preflight on a host that has no tmux."""
    # Without it a tmux-less runner raises AttachUnavailable in the preflight, so a spawn-failure case passes blind.
    # Only tmux is answered for: the monitor lane's own drone preflight still sees the real `shutil.which`.
    monkeypatch.setattr(host_attach.shutil, "which", _forced_tmux_which(shutil.which))


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the token store to a temp dir — no real token is ever touched."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


@pytest.fixture
def seated(tmp_path: Path, monkeypatch: Any):
    """A citizen registry of this test's own, so the seat resolves to a KNOWN name."""
    # The live registry is untracked, so a CI runner has none. AIPASS_REGISTRY is drone's own documented door,
    # so resolution stays drone's real one; the root is named for the real seat so the seat branch lands alike.
    root = tmp_path / SEAT
    branch_dir = root / "src" / "aipass" / "api"
    branch_dir.mkdir(parents=True)

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps(
            {
                # No metadata.id: drone checks a registry against the passport only when both carry one.
                "metadata": {"description": "hermetic registry for the attach tests"},
                "branches": [
                    {
                        "name": "API",
                        "path": "src/aipass/api",
                        "email": "@api",
                        "status": "active",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("AIPASS_REGISTRY", str(registry))
    yield root


from aipass.api.apps.handlers.host import git_reads as host_git
from aipass.api.tests.support_host_read_lane import _BranchNotFound, _RegistryBroken, remote_document

PATCH_FEED_PATH = "aipass.api.apps.handlers.host.feed.feed_path"
PATCH_FEED_LOGGER = "aipass.api.apps.handlers.host.feed.logger"
PATCH_FEED_JSON = "aipass.api.apps.handlers.host.feed.json_handler"
PATCH_READS_LOGGER = "aipass.api.apps.handlers.host.reads.logger"
PATCH_READS_JSON = "aipass.api.apps.handlers.host.reads.json_handler"
PATCH_READS_DRONE = "aipass.api.apps.handlers.host.reads.drone"
PATCH_GIT_LOGGER = "aipass.api.apps.handlers.host.git_reads.logger"
PATCH_GIT_JSON = "aipass.api.apps.handlers.host.git_reads.json_handler"


@pytest.fixture
def _clean_git_changes_cache():
    """Empty the git-changes cache around every case in a file that requests it."""
    # `read_git_changes` coalesces on (branch, project, grain) with a TTL: a later case gets an earlier one's mock.
    host_git._changes.clear()
    yield
    host_git._changes.clear()


@pytest.fixture
def feed_file(tmp_path: Path):
    """A temp feed file wired into the handler."""
    path = tmp_path / "notifications.jsonl"
    with patch(PATCH_FEED_PATH, return_value=path), patch(PATCH_FEED_LOGGER), patch(PATCH_FEED_JSON):
        yield path


@pytest.fixture
def fake_repo(tmp_path: Path):
    """A repo root with a registry and one branch, wired into the handler."""
    root = tmp_path / "FakeRepo"
    branch = root / "src" / "aipass" / "demo"
    branch.mkdir(parents=True)
    (branch / "hello.txt").write_text("hello world", encoding="utf-8")
    (branch / "nested").mkdir()
    (branch / "nested" / "deep.txt").write_text("deep", encoding="utf-8")
    (root / "secret.txt").write_text("do not read me", encoding="utf-8")

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
        encoding="utf-8",
    )

    # @drone's error classes are kept so the refused/unavailable split is exercised rather than assumed.
    fake_drone = MagicMock()
    fake_drone.BranchNotFoundError = _BranchNotFound
    fake_drone.RegistryError = _RegistryBroken
    fake_drone.get_registry_path.return_value = str(registry)

    def _info(name: str) -> dict:
        if name.lower() not in ("demo", "@demo"):
            raise _BranchNotFound(name)
        return {"name": "DEMO", "path": str(branch), "email": "@demo"}

    fake_drone.get_branch_info.side_effect = _info

    with (
        patch(PATCH_READS_DRONE, fake_drone),
        patch(PATCH_READS_LOGGER),
        patch(PATCH_READS_JSON),
        patch(PATCH_GIT_LOGGER),
        patch(PATCH_GIT_JSON),
    ):
        yield {"root": root, "branch": branch, "registry": registry, "drone": fake_drone}


def _raise(error: Exception) -> Any:
    """Raise inside a lambda — the fixture's resolver needs one expression."""
    raise error


@pytest.fixture
def remote_repo(tmp_path: Path):
    """A branch whose remote door can be made to answer anything, per test."""
    root = tmp_path / "RemoteRepo"
    branch = root / "src" / "aipass" / "demo"
    branch.mkdir(parents=True)
    (root / ".git").mkdir()

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "DEMO", "path": str(branch), "email": "@demo"}]}),
        encoding="utf-8",
    )

    fake_drone = MagicMock()
    fake_drone.BranchNotFoundError = _BranchNotFound
    fake_drone.RegistryError = _RegistryBroken
    fake_drone.get_registry_path.return_value = str(registry)
    fake_drone.get_branch_info.side_effect = lambda name: (
        {"name": "DEMO", "path": str(branch), "email": "@demo"}
        if name.lower() in ("demo", "@demo")
        else _raise(_BranchNotFound(name))
    )

    runner = MagicMock()

    def serve(stdout: str, returncode: int = 0, stderr: str = "") -> None:
        """What `drone @git remote --json` answers with, for this test."""
        completed = MagicMock()
        completed.stdout = stdout
        completed.stderr = stderr
        completed.returncode = returncode
        runner.return_value = completed

    serve(remote_document("https://github.com/AIOSAI/AIPass.git"))

    with (
        patch(PATCH_READS_DRONE, fake_drone),
        patch(PATCH_READS_LOGGER),
        patch(PATCH_READS_JSON),
        patch(PATCH_GIT_LOGGER),
        patch(PATCH_GIT_JSON),
        patch.object(subprocess, "run", runner),
    ):
        yield {"root": root, "branch": branch, "serve": serve, "runner": runner}


# Never discover out of .archive/: its disposal copies yield the dotted name ...json..archive.json_handler,
# a SyntaxError that kills the collecting file.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Autouse fixture that isolates JSON operations and silences logging."""
    # The fleet seam, not a module attribute: the shim resolves its directory from AIPASS_TEST_LOG_DIR on every call.
    # A subdirectory, since the service spells <seam>/<branch>/<branch>_json and would collide with a branch-named dir.
    # Never mkdir the sandbox: tests that assert their tmp_path stays empty would go red.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = _json_mod.get_json_path("probe", "config").parent

    logger_names = [
        f"aipass.{BRANCH_MODULE}",
        BRANCH_MODULE,
        f"{BRANCH_MODULE}.apps.handlers.json.json_handler",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    return sandbox


@pytest.fixture()
def mock_logger() -> MagicMock:
    """Standalone mock logger for tests that need to verify logging calls."""
    mock = MagicMock(spec=logging.Logger)
    mock.debug = MagicMock()
    mock.info = MagicMock()
    mock.warning = MagicMock()
    mock.error = MagicMock()
    mock.critical = MagicMock()
    return mock


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture; at 80 Rich cuts the rows test_openrouter_client and test_google_client read whole."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def header_fires_nowhere(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """header() fires cli_header_displayed on the live trigger bus through the
    trigger object display caches in _TRIGGER; a test that prints must never reach that bus."""
    recorder = MagicMock()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


@pytest.fixture(autouse=True)
def _no_fleet_cache_between_tests() -> Generator[None, None, None]:
    """Clear the fleet snapshot cache around every test (DPLAN-0305)."""
    # read_snapshot caches and coalesces execs: a case counting execs would count its neighbour's cached answer.
    _fleet.reset_snapshot_cache()
    yield
    _fleet.reset_snapshot_cache()


@pytest.fixture(autouse=True)
def _no_remembered_git_refusals_between_tests() -> Generator[None, None, None]:
    """Forget every remembered git refusal around each test (@trigger, 2026-08-19)."""
    # The 60s refusal memory outlives a suite: one refusal would silence every later test on the lane, still green.
    _refusals._reset_refusals()
    yield
    _refusals._reset_refusals()


@pytest.fixture(autouse=True)
def _no_leaked_pump_reservations() -> Generator[None, None, None]:
    """Give the attach lane's thread count back after every test (DPLAN-0305)."""
    # Spawn-only tests hold a pump slot they never hang up; production's release is pinned by its own tests.
    yield
    _attach._PUMP_SLOTS = threading.BoundedSemaphore(_attach.PUMP_WORKERS)
