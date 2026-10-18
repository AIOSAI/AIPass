# =================== AIPass ====================
# META DATA HEADER
# Name: tests/conftest.py
# Description: Shared pytest fixtures for daemon tests - host-state seals, sentinels, console pin
# Version: 1.3.0
# Created: 2026-03-07
# Modified: 2026-10-17
# Category: daemon/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.3.0 (2026-10-10): temp_test_dir, sample_test_data retired - requested only by the .archive scaffold (PR #774)
#   - v1.2.0 (2026-10-06): timer seal keeps the real systemctl wrapper behind an empty PATH for systemctl_on_path
#   - v1.1.0 (2026-09-27): Console width pin + command-state reset (item 20); catches log; unused fixtures removed
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================
#
# @Meta header not seedgo standards

"""Shared pytest fixtures for daemon tests

Reference: docs/testing.md
"""

import json
import logging
import os
import sys
import tempfile

# Must be set before any prax import, which reads it at logger initialization.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
import subprocess
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

from aipass.cli.apps.modules import console, err_console, reset_command_state
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.modules import timer_install
from aipass.daemon.apps.handlers.schedule import command_job as command_job_mod
from aipass.daemon.apps.handlers.schedule import recovery as recovery_mod
from aipass.daemon.apps.handlers.schedule import runstate as runstate_mod
from aipass.daemon.apps.handlers.schedule.discovery import active_citizens, discover_jobs

logger = logging.getLogger(__name__)

_TIMER_UNITS = ("daemon-tick.service", "daemon-tick.timer")
_LIVE_UNIT_DIR = Path.home() / ".config" / "systemd" / "user"

# .archive/ holds disposal copies; collecting them yields a dotted module name that is a SyntaxError.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


# Seals are autouse on the seam, never on the test that bit: the next test has no reason to know.


def _systemctl(*args: str) -> tuple:
    """Ask systemd --user something. Returns (ok, stdout); ok=False is unreachable, not absent."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", *args], capture_output=True, text=True, encoding="utf-8", timeout=15
        )
        return True, result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as e:
        logger.info("systemd --user unreachable for %s: %s", args, e)
        return False, ""


def _host_timer_snapshot() -> dict:
    """Record the live daemon-tick timer state: files, enabled, active. Read-only."""
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
def _seal_timer_host_state(tmp_path, request):
    """Make live systemd unreachable from every test in this suite.

    Patched at the module, so the real router reaches the stand-ins even with the gate absent.
    `systemctl_on_path` keeps the real wrapper and empties PATH instead, leaving only its stub.
    """
    if "systemctl_on_path" in request.fixturenames:
        no_systemctl = tmp_path / "_sealed_empty_path"
        no_systemctl.mkdir()
        with (
            patch.dict(os.environ, {"PATH": str(no_systemctl)}),
            patch.object(timer_install, "_UNIT_DIR", tmp_path / "_sealed_unit_dir"),
            patch.object(timer_install, "_STATE_DIR", tmp_path / "_sealed_state_dir"),
        ):
            yield None
        return
    with (
        patch.object(timer_install, "_run_systemctl", MagicMock(return_value=True)) as fake_systemctl,
        patch.object(timer_install, "_UNIT_DIR", tmp_path / "_sealed_unit_dir"),
        patch.object(timer_install, "_STATE_DIR", tmp_path / "_sealed_state_dir"),
    ):
        yield fake_systemctl


@pytest.fixture(autouse=True)
def _seal_runstate_file(tmp_path):
    """Keep the suite out of the LIVE scheduler runstate: every non-dry run_tick() saves."""
    with patch.object(runstate_mod, "RUNSTATE_FILE", tmp_path / "_sealed_runstate.json"):
        yield


def _live_job_keys(path):
    """The job keys the live scheduler runstate currently holds."""
    if not path.exists():
        return None
    try:
        return set(json.loads(path.read_text(encoding="utf-8")).get("jobs", {}))
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("live runstate %s unreadable, sentinel stands down: %s", path, e)
        return None


WAKE_PROMPT_FILE = "last_wake_prompt.txt"


@pytest.fixture(autouse=True)
def _seal_branch_wake_prompt(tmp_path):
    """Keep the suite out of every OTHER citizen's .daemon/ directory.

    Fixture owners are real citizens, so _branch_daemon_dir resolves to live trees.
    Yields a tmp dir, not None, so a test can still assert the branch-side write happened.
    """
    sealed = tmp_path / "_sealed_branch_daemon"
    with patch.object(recovery_mod, "_branch_daemon_dir", return_value=sealed):
        yield sealed


# Exits 1 naming the seal, so a test that forgot its own fake sees a FAILED fire.
SEALED_LAUNCHER = (sys.executable, "-c", "import sys; sys.exit('sealed: a test reached the real drone launcher')")


@pytest.fixture(autouse=True)
def _seal_command_launcher():
    """No test may run the real drone through a command job; LAUNCHER also prefixes notify mail."""
    with patch.object(command_job_mod, "LAUNCHER", SEALED_LAUNCHER):
        yield SEALED_LAUNCHER


def _live_wake_prompts() -> dict:
    """Every citizen's live wake transcript, keyed by path. Missing files are None."""
    prompts = {}
    try:
        citizens = active_citizens()
    except OSError as e:
        logger.warning("cannot list citizens for the wake-prompt sentinel: %s", e)
        return prompts

    for citizen in citizens:
        f = Path(citizen["path"]) / ".daemon" / WAKE_PROMPT_FILE
        try:
            prompts[str(f)] = f.read_text(encoding="utf-8") if f.exists() else None
        except OSError as e:
            logger.warning("cannot read live wake prompt %s: %s", f, e)
            prompts[str(f)] = None
    return prompts


@pytest.fixture(scope="session", autouse=True)
def _branch_wake_prompt_sentinel():
    """Fail the session that rewrote a live citizen's wake transcript. Never restores.

    A real mid-suite fire writes the same text to daemon_json too; a change that does not match is the suite.
    """
    before = _live_wake_prompts()
    yield
    after = _live_wake_prompts()

    live_copy = runstate_mod.RUNSTATE_FILE.parent / WAKE_PROMPT_FILE
    try:
        daemons_own = live_copy.read_text(encoding="utf-8") if live_copy.exists() else None
    except OSError as e:
        logger.warning("cannot read daemon's own wake prompt %s: %s", live_copy, e)
        daemons_own = None

    escaped = [path for path, text in after.items() if before.get(path) != text and text != daemons_own]
    assert not escaped, (
        "THE SUITE WROTE INTO A LIVE CITIZEN'S .daemon/ DIRECTORY.\n"
        f"  files: {sorted(escaped)}\n"
        "A test reached recovery.record_wake_prompt with a REAL owner email and "
        "the transcript landed in that citizen's tree. Seal its seam — see "
        "_seal_branch_wake_prompt in this file.\n"
        "(If a real timer tick fired one of these mid-run, daemon_json's own copy "
        "would match it and this assert would not have fired. It did not match.)"
    )


@pytest.fixture(scope="session", autouse=True)
def _runstate_sentinel():
    """Fail the session that put fixture rows into the live scheduler runstate. Never restores.

    Compares keys, not bytes: the live timer ticks mid-suite and rewrites real rows' values.
    """
    live = runstate_mod.RUNSTATE_FILE
    before = _live_job_keys(live)
    yield
    after = _live_job_keys(live)
    if before is None or after is None:
        return

    try:
        real = {runstate_mod.job_key(j["owner"], j["id"]) for j in discover_jobs()}
    except OSError as e:
        logger.warning("cannot ask the fleet for its jobs, holding the pre-suite roster: %s", e)
        real = before

    invented = after - before - real
    assert not invented, (
        "THE SUITE WROTE FIXTURE ROWS INTO THE LIVE SCHEDULER RUNSTATE.\n"
        f"  file: {live}\n"
        f"  rows no citizen publishes: {sorted(invented)}\n"
        "Some test reached the real file. Find it and seal its seam — "
        "see _seal_runstate_file in this file."
    )

    lost = (before - after) & real
    assert not lost, (
        "THE SUITE DELETED LIVE SCHEDULER ROWS THAT THE FLEET STILL PUBLISHES.\n"
        f"  file: {live}\n"
        f"  rows lost: {sorted(lost)}\n"
        "Every one of these carries a citizen's last_run. Losing it makes the job "
        "look like it never ran, and the next tick fires it out of window."
    )


@pytest.fixture(scope="session", autouse=True)
def _host_state_sentinel():
    """Fail the session that moved the live timer, naming what moved.

    Never restores: putting the timer back quietly would hide the defect it reports.
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


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin the product's consoles to one width for the whole run.

    Unpinned, Rich wraps at 80 on POSIX and 79 on Windows, so substring asserts differ by OS.
    """
    for product_console in (console, err_console):
        product_console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect daemon's json writes into a temp subdir, not tmp_path itself (tmp_path/daemon/ collides)."""
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox
