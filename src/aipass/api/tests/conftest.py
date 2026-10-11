# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for api tests
# Version: 2.1.2
# Created: 2026-03-05
# Modified: 2026-10-10
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

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
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

# ============ BRANCH CONFIG ============
BRANCH_MODULE = "api"
# =======================================

# ---------------------------------------------------------------------------
# Dynamic import for json_handler isolation
# ---------------------------------------------------------------------------

_HANDLER_PKG = f"aipass.{BRANCH_MODULE}.apps.handlers"
_JSON_MOD_PATH = f"aipass.{BRANCH_MODULE}.apps.handlers.json.json_handler"

# The real handlers package, fence and all: this file is kin and pytest is
# transport, so the v2.1 fence lets it through. The stub that stood here kept
# the old guard from refusing pytest's frames; it was bound onto apps only by
# apps/__init__'s 'from . import handlers', and with that line gone a dotted
# patch could no longer walk to it (api, DPLAN-0404 fence leg).
importlib.import_module(_HANDLER_PKG)
_json_mod = importlib.import_module(_JSON_MOD_PATH)

# The host handlers the autouse fixtures below reset, imported plainly. None of
# the three imports the [host] extra (fastapi, starlette, uvicorn live in
# server.py and statics.py only), so the old catch-all around each guarded no
# missing extra: all it could swallow was a real import break, which then
# switched off its reset fixture without a word (api, fleet green leg 8).
from aipass.api.apps.handlers.host import attach as _attach
from aipass.api.apps.handlers.host import fleet as _fleet
from aipass.api.apps.handlers.host import refusals as _refusals

# ---------------------------------------------------------------------------
# The attach lane's shared fixtures. They moved here whole from
# test_host_attach.py when it split into three files along the unit under
# test, because two or more of the three use each (api, the oversize split
# leg, 2026-10-08). `store` serves test_host_api.py's files the same way.
# ---------------------------------------------------------------------------
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
    """
    Satisfy `open_attach`'s tmux preflight on a host that has no tmux.

    RUN 34704362515 (macOS, 2026-09-12): 15 failed and 8 errors in this file,
    every one of them `AttachUnavailable: tmux is not installed on this host`.
    Not one of those cases runs tmux — they replace the argv with `cat`, `echo`
    or `pwd`, or patch `Popen` outright — so what they measured was the runner's
    package list rather than this lane. The precedent is already in this file
    (`TestOneRoomHonoursAnOutsideSeat`, which forces the same preflight because
    argv composition is string work no binary takes part in).

    One of the fifteen was worse than a red: `test_a_failed_spawn_leaks_no_
    descriptors` asserts `AttachUnavailable` from a spawn that raises, and on a
    tmux-less host the preflight raised that exact class three lines earlier —
    the case would have passed while measuring nothing.

    Only the tmux binary is answered for; every other lookup goes to the real
    `shutil.which`, so the monitor lane's own drone preflight is untouched.
    """
    monkeypatch.setattr(host_attach.shutil, "which", _forced_tmux_which(shutil.which))


@pytest.fixture
def store(tmp_path: Path):
    """Redirect the token store to a temp dir — no real token is ever touched."""
    with patch(PATCH_SECRETS_BASE, tmp_path), patch(PATCH_SECRETS_JSON), patch(PATCH_SECRETS_LOGGER):
        with patch(PATCH_TOKENS_JSON), patch(PATCH_TOKENS_LOGGER):
            yield tmp_path


@pytest.fixture
def seated(tmp_path: Path, monkeypatch: Any):
    """
    A citizen registry of this test's own, so the seat resolves to a KNOWN name.

    THE CI RED THIS FIXES (PR #734, run 32094572478): the attach route asks
    which project it is seated in before it opens anything, and that answer
    comes from drone's citizen registry. The live registry is machine-managed
    and ignored by version control, so a fresh runner has none — the ubuntu job
    installs the package and runs pytest, nothing more. Six tests here were
    therefore leaning on whatever this developer's machine happened to contain,
    and on CI the refusal fired at registry resolution BEFORE the contract under
    test was ever reached: close code 1011 where 1008 was expected, the tmux
    sentence replaced by a registry one, and empty resize and write lists
    downstream because the pump never started.

    None of those six tests are about registry resolution. A test that needs a
    registry brings its own, and then it is testing the thing it claims to.

    AIPASS_REGISTRY is drone's OWN documented door (priority 2 of 3 in
    get_registry_path, behind only an explicit set_registry_path), so the
    resolution under test stays drone's real one end to end — path normalising,
    credential check and all. Nothing here reaches for the live registry, and
    monkeypatch puts the environment back on the way out.

    The root is named for the real seat so the seat-versus-external branch of
    the route lands the same way here as it does on the developer machine.
    """
    root = tmp_path / SEAT
    branch_dir = root / "src" / "aipass" / "api"
    branch_dir.mkdir(parents=True)

    registry = root / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps(
            {
                # No metadata.id ON PURPOSE: drone only compares registries
                # against a passport when BOTH carry an id, so leaving it out
                # keeps this fixture from arguing with the citizen running it.
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


# ---------------------------------------------------------------------------
# The read lane's shared fixtures. They moved here whole from
# test_host_read_lane.py when it split into four files along the unit under
# test, because two or more of the four use each (api, the oversize split leg,
# 2026-10-08). The git-changes cache clear is a named fixture, requested by
# the files that reach the cache through a module pytestmark (2026-10-09).
# ---------------------------------------------------------------------------
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
    """
    Empty the git-changes cache around every case in a file that requests it.

    `read_git_changes` coalesces on (branch, project, grain) with a 1.5s TTL
    (2026-09-07, the stampede cure). Cases mock a different `drone @git
    status` answer under the same branch name, so without this the SECOND case
    to run is served the FIRST one's document and asserts against a subprocess
    that was never called. That failure reads as a broken lane and is not one —
    it is the cache doing its job across a boundary a suite does not have.

    Requested per file by a module pytestmark (usefixtures), never suite-wide
    autouse: every case in a requesting file gets it, so a case added later
    there cannot inherit the bleed silently. test_host_read_lane.py and
    test_host_read_lane_changes.py request it.
    """
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

    # Stand in for @drone's public surface — the door this handler resolves
    # through. Its real error classes are kept so the refused/unavailable split
    # is exercised rather than assumed.
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


# Never discover out of .archive/: it holds verbatim disposal copies of the
# suites the one json service subsumed, and rglobbing into a dot-directory
# generates the dotted module name ...json..archive.json_handler, a SyntaxError
# that kills the file that walked there (DPLAN-0325, hooks' finding).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def mock_infrastructure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Autouse fixture that isolates JSON operations and silences logging.

    This fixture:
      1. Redirects the branch's json writes into a temp dir (test isolation)
      2. Patches the branch logger to a NullHandler (no console noise)

    Redirected through the fleet seam, not by patching a module attribute.
    It used to search the handler for API_JSON_DIR / JSON_DIR / BRANCH_JSON_DIR
    / _JSON_DIR and monkeypatch whichever it found — and, finding none, do
    NOTHING and say nothing. Since DPLAN-0325 the handler is a shim over the
    one prax service, which holds no directory constant at all and resolves
    its directory from AIPASS_TEST_LOG_DIR on EVERY call, so the search would
    have gone silently empty and let the whole suite write into the real
    api_json/.

    Own subdirectory on purpose: the service spells the sandbox
    <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    tmp_path/api/ in every test and collide with a test that builds a
    directory of its own branch's name.

    Deliberately does NOT create the sandbox. It is autouse over 1560 tests,
    most of which never touch json at all, and an eager mkdir puts a directory
    in every one of their tmp_paths — measured: it turned
    test_the_staged_file_does_not_survive_a_failed_write red, a test that
    asserts its tmp_path is empty after a failed atomic write and was right to.
    The service builds the directory chain on the first call that needs it
    (pinned by test_auto_creates_directory), so nothing is lost by waiting.

    Returns:
        The sandbox directory the handler will write into. May not exist yet.
    """
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
    under pytest's capture, the terminal's width under -s, COLUMNS when exported.

    The row asserts of test_openrouter_client and test_google_client are green
    because of this pin: at 80 columns Rich wraps or cuts the rows they read
    whole (api, fleet green leg 4)."""
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
    trigger object display caches in _TRIGGER; a test that prints through the real console must
    never reach that bus (fleet green leg 2 bus probe: 10 fires)."""
    recorder = MagicMock()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


@pytest.fixture(autouse=True)
def _no_fleet_cache_between_tests() -> Generator[None, None, None]:
    """
    Clear the fleet snapshot cache around every test (DPLAN-0305).

    read_snapshot caches @baud's envelope for ~1.5s and coalesces concurrent
    callers onto one exec. That is right in a server and WRONG across tests: a
    case that patches subprocess and counts execs would count the previous
    case's cached answer instead, and pass while measuring nothing. Cleared
    both sides so neither the test nor its neighbour can inherit one.
    """
    _fleet.reset_snapshot_cache()
    yield
    _fleet.reset_snapshot_cache()


@pytest.fixture(autouse=True)
def _no_remembered_git_refusals_between_tests() -> Generator[None, None, None]:
    """
    Forget every remembered git refusal around each test (@trigger, 2026-08-19).

    The git lane keeps a could-not-read answer for 60s so a phone polling every
    5 seconds stops re-spawning drone at a root that cannot authenticate. Right
    in a server and WRONG across tests, for the same reason as the fleet cache
    above and then some: 60s outlives an entire suite run, so ONE test that
    provokes a refusal would silence every later test on that lane — and they
    would pass, because a remembered refusal raises exactly what a fresh one
    does. Cleared both sides.
    """
    _refusals._reset_refusals()
    yield
    _refusals._reset_refusals()


@pytest.fixture(autouse=True)
def _no_leaked_pump_reservations() -> Generator[None, None, None]:
    """
    Give the attach lane's thread count back after every test (DPLAN-0305).

    The socket pump has a real cap now, and a spawned PTY holds one slot until
    its session hangs up. Several tests in this suite spawn one and never do —
    correctly, they are testing the spawn, not the lifecycle — so the count
    only ever climbs across a run and would eventually refuse terminals to
    tests that never took one. Measured: 5 slots held by the end of a full run.

    PRODUCTION IS NOT PAPERED OVER BY THIS. The release is pinned where it
    belongs — _pump's finally always hangs up (test_the_pump_always_hangs_up),
    hangup always releases, and a failed spawn releases too, each proven by a
    mutation. This only stops one test's leftovers from being another's cap.
    """
    yield
    _attach._PUMP_SLOTS = threading.BoundedSemaphore(_attach.PUMP_WORKERS)
