# =================== AIPass ====================
# Name: conftest.py
# Description: Skills test configuration
# Version: 3.3.0
# Created: 2026-03-07
# Modified: 2026-10-17
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v3.3.0 (2026-10-10): sample_data retired - requested only by the .archive scaffold (seedgo, PR #774)
#   - v3.2.0 (2026-10-04): audit_guard - file denials ride an audit hook, no stdlib name replaced
#   - v3.1.0 (2026-09-27): C1 console width pin, C2 command-state reset; unused temp_dir, mock_logger removed
#   - v3.0.0 (2026-09-03): The json redirect is the AIPASS_TEST_LOG_DIR seam - no attribute to patch (DPLAN-0325)
#   - v2.1.0 (2026-07-22): mock_infrastructure re-resolves json_handler at setup - fixed real-file leaks
#   - v2.0.0 (2026-03-28): Added sample_data, mock_infrastructure, mock_json_handler fixtures
#
# CODE STANDARDS:
#   - Sets the AIPASS_TEST_LOG_DIR seam before the first aipass import
# =============================================

"""Skills test configuration."""

import os
import tempfile

# Must be set before the first aipass import: loggers and the json service read it at init.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import logging
import sys
from pathlib import Path
from typing import Callable, Generator

import pytest

# No sys.path hack: prepending src/ would hide a broken install and shadow the wheel e2e measures.
from aipass.cli.apps.modules import display
from aipass.skills.apps.handlers.json import json_handler
from aipass.skills.apps.modules import creator

BRANCH_MODULE = "aipass.skills"

# Nothing under .archive/ is collected: a rglob there yields dotted names that do not parse.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Redirect json writes to a per-test sandbox (autouse: unset, they hit the real skills_json/)."""
    # A seam AT tmp_path would create tmp_path/skills/ and collide with tests that build that dir.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)

    logger_names = [
        BRANCH_MODULE,
        "aipass.prax.json",
    ]
    for logger_name in logger_names:
        log = logging.getLogger(logger_name)
        monkeypatch.setattr(log, "handlers", [logging.NullHandler()])

    return sandbox


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def bus_recorder(monkeypatch: pytest.MonkeyPatch) -> list:
    """Every trigger event the creator fires lands here, never on the real bus (creator binds it at import)."""
    fired: list = []

    class _Recorder:
        def fire(self, event: str, **data: object) -> None:
            fired.append((event, data))

    monkeypatch.setattr(creator, "trigger", _Recorder())
    return fired


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


# The guards the one audit hook runs: armed per test by audit_guard, else empty.
_AUDIT_GUARDS: list = []


def _run_audit_guards(event: str, args: tuple) -> None:
    """The process's one audit hook: run every armed guard, nothing when none is."""
    for guard in tuple(_AUDIT_GUARDS):
        guard(event, args)


@pytest.fixture(scope="session")
def audit_hook_installed() -> None:
    """Install the audit hook once per process - sys.addaudithook cannot be undone."""
    sys.addaudithook(_run_audit_guards)


@pytest.fixture()
def audit_guard(audit_hook_installed: None) -> Generator[Callable, None, None]:
    """Arm guards on the interpreter's audit events ("open" covers every file route) for one test."""
    armed: list = []

    def arm(guard: Callable[[str, tuple], None]) -> None:
        _AUDIT_GUARDS.append(guard)
        armed.append(guard)

    yield arm
    for guard in armed:
        _AUDIT_GUARDS.remove(guard)
