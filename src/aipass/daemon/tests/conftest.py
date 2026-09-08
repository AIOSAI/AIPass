# ===================AIPASS====================
# META DATA HEADER
# Name: tests/conftest.py
# Date: 2025-11-08
# Version: 1.0.0
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================
#
# @Meta header not seedgo standards

"""Shared pytest fixtures for daemon tests"""

import os
import tempfile

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import shutil
import subprocess
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.modules import timer_install

# The two units the scheduler runs on. Named here because both the seal and the
# host-state snapshot need them and a second spelling is a second thing to drift.
_TIMER_UNITS = ("daemon-tick.service", "daemon-tick.timer")
_LIVE_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

# Never discover out of .archive/: it holds verbatim disposal copies of the
# suites the one json service subsumed, and rglobbing into a dot-directory
# generates the dotted module name ...json..archive.json_handler, a SyntaxError
# that kills the file that walked there (DPLAN-0325, hooks' finding).
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# =============================================================================
# HOST STATE — the suite may not move the live scheduler timer
# =============================================================================
#
# PATRICK'S RULING (2026-09-08), his words: "tests can't disable processes, they
# should restore to exact same state before the test. The test is fine and good
# that it can enter something."
#
# WHAT HAPPENED. tests/test_cli_routing.py runs the REAL router over every verb
# in GATED_VERBS, and two of those verbs are install-timer and uninstall-timer.
# With the argument gate in place the refusal comes first and the verb never
# runs. Without it — a red-first run, or any mutation run that disables the gate
# — _install() and _uninstall() executed for real against the user's systemd.
# The journal recorded seven Started/Stopped pairs across four such runs on
# 2026-09-07, ending on a Stop at 11:46:40. Nothing ticked for twenty-three
# hours: @vera/release-watch and @daemon/inbox-sweep both missed their windows,
# and no MISSED line could even be written, because writing one needs a tick.
#
# WHY THE SEAL IS SESSION-WIDE AND NOT ON THOSE TWO ROWS. Scoping the guard to
# the rows that bit would leave the hole open for the next verb added to
# GATED_VERBS, and whoever adds it has no reason to know this file exists. The
# defect is not "two rows reach systemd", it is "a test can reach systemd at
# all". Same argument TestInstall._no_real_home already makes about ~/.aipass:
# a seam a test can forget to use is not a fix.


def _systemctl(*args: str) -> tuple:
    """Ask systemd --user something. Returns (ok, stdout) — never raises.

    Returns ok=False where systemd is not reachable at all (no systemctl on
    PATH, no user bus, a timeout), which is the honest answer on the Windows
    job and in a container. A snapshot built from an unreachable host is marked
    unavailable rather than being recorded as "absent", because those two are
    very different facts and only one of them is worth restoring.
    """
    try:
        result = subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=15)
        return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return False, ""


def _host_timer_snapshot() -> dict:
    """Record the live daemon-tick timer state: files, enabled, active.

    Read-only. This is the state the suite is required to give back.
    """
    reachable, enabled = _systemctl("is-enabled", "daemon-tick.timer")
    if not reachable:
        return {"available": False}
    _, active = _systemctl("is-active", "daemon-tick.timer")
    return {
        "available": True,
        "enabled": enabled,
        "active": active,
        "files": sorted(name for name in _TIMER_UNITS if (_LIVE_UNIT_DIR / name).exists()),
    }


@pytest.fixture(autouse=True)
def _seal_timer_host_state(tmp_path):
    """Make live systemd unreachable from every test in this suite.

    Autouse and unconditional. The three seams are the whole surface by which
    timer_install can change host state:

      _run_systemctl  every stop/disable/enable/start/daemon-reload
      _UNIT_DIR       where unit files are copied to and unlinked from
      _STATE_DIR      the ~/.aipass mkdir

    Patched at the MODULE, so _install() and _uninstall() — which look these up
    as globals at call time — get the stand-ins even when they are invoked
    through the real router with the gate absent. TestRunSystemctl is
    unaffected: it binds _run_systemctl by direct import at module load, so it
    still exercises the real function against a patched subprocess.run.

    The stand-in returns True, so an unpatched caller sees a successful install
    rather than a confusing failure — the point is that nothing happened, not
    that something failed.
    """
    with (
        patch.object(timer_install, "_run_systemctl", MagicMock(return_value=True)) as fake_systemctl,
        patch.object(timer_install, "_UNIT_DIR", tmp_path / "_sealed_unit_dir"),
        patch.object(timer_install, "_STATE_DIR", tmp_path / "_sealed_state_dir"),
    ):
        yield fake_systemctl


@pytest.fixture(scope="session", autouse=True)
def _host_state_sentinel():
    """Fail the session that moved the live timer, naming what moved.

    The seal above prevents the known route. This one is the backstop for the
    route nobody has thought of yet — a test that shells out to
    `drone @daemon uninstall-timer`, a helper that calls systemctl directly, a
    future module with its own copy of the install logic. On 2026-09-07 the
    suite took the scheduler down and reported 594 passed; after this it cannot
    do both.

    Read-only and non-restoring on purpose. A sentinel that quietly put the
    timer back would hide the very defect it exists to report, and the session
    is over by the time it speaks — the honest move is to say loudly what
    changed and let a human decide.
    """
    before = _host_timer_snapshot()
    yield
    after = _host_timer_snapshot()
    if not before.get("available") or not after.get("available"):
        return
    assert after == before, (
        "THE SUITE CHANGED LIVE SYSTEMD STATE.\n"
        f"  before: {before}\n"
        f"  after:  {after}\n"
        "Some test reached the real user systemd. Find it and seal its seam — "
        "see _seal_timer_host_state in this file."
    )


@pytest.fixture
def timer_host_state():
    """Snapshot/restore for a test that DELIBERATELY reaches the live timer.

    Opt-in, and the only sanctioned way to write such a test. Records the state
    before, hands the snapshot to the test, and in a finally puts back exactly
    what it recorded — then asserts the restore actually matched, because a
    restore nobody checked is a hope.

    Idempotent by construction: it restores TO A RECORDED STATE rather than
    toggling, so running it twice leaves the host the same as running it once.
    Yields None where systemd is unreachable, so a test can skip itself.

    No test in this suite needs it today — the router pins run sealed instead.
    It lands as the contract for the next test that genuinely must exercise the
    real verb, so that test has somewhere safe to stand.
    """
    before = _host_timer_snapshot()
    if not before.get("available"):
        yield None
        return
    try:
        yield before
    finally:
        for name in _TIMER_UNITS:
            live = _LIVE_UNIT_DIR / name
            should_exist = name in before["files"]
            if should_exist and not live.exists():
                shutil.copy2(Path(timer_install._DAEMON_ROOT) / name, live)
            elif not should_exist and live.exists():
                live.unlink()
        _systemctl("daemon-reload")
        if before["enabled"] == "enabled":
            _systemctl("enable", "daemon-tick.timer")
        else:
            _systemctl("disable", "daemon-tick.timer")
        if before["active"] == "active":
            _systemctl("start", "daemon-tick.timer")
        else:
            _systemctl("stop", "daemon-tick.timer")
        restored = _host_timer_snapshot()
        assert restored == before, f"timer_host_state failed to restore: {before} -> {restored}"


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect daemon's json writes into a temp dir.

    autouse on purpose: since DPLAN-0325 the handler is a shim over the one
    prax service, and the service resolves its directory from
    AIPASS_TEST_LOG_DIR on EVERY call. Unset, the nine names write into the
    real daemon_json/, so a test that forgets to redirect pollutes the branch.
    The guard belongs on every test, not on the ones that remember.

    Own subdirectory on purpose: the service spells the sandbox
    <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    tmp_path/daemon/ in every test and collide with a test that builds a
    directory of its own branch's name.

    Returns:
        The sandbox directory the handler now writes into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after"""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data

    Customize this fixture for your module's needs
    """
    return {"test_key": "test_value", "sample_data": "example"}


@pytest.fixture()
def mock_json_handler() -> MagicMock:
    """Standalone mock json_handler for isolation tests."""
    handler = MagicMock()
    handler.load_json = MagicMock(return_value={})
    handler.save_json = MagicMock(return_value=True)
    handler.ensure_json_exists = MagicMock(return_value=True)
    handler.ensure_module_jsons = MagicMock(return_value=True)
    # gettempdir(), not a literal /tmp: this stand-in is only ever compared
    # against, never opened, but a POSIX literal is still a POSIX literal and
    # the fleet runs a Windows job.
    handler.get_json_path = MagicMock(return_value=Path(tempfile.gettempdir()) / "mock.json")
    handler.validate_json_structure = MagicMock(return_value=True)
    handler.log_operation = MagicMock(return_value=True)
    return handler
