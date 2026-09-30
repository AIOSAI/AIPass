# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for aipass tests — json and profile redirects, console width, command state
# Version: 1.2.0
# Created: 2026-05-04
# Modified: 2026-09-28
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-09-28): header_events recorder keeps cli's header off the real trigger bus (DPLAN-0354 leg 3)
#   - v1.1.0 (2026-09-27): template C1/C2 fixtures; unused mock_json_handler removed (DPLAN-0354)
#   - v1.0.0 (2025-11-08): Initial implementation - Shared pytest fixtures
# =============================================

"""Shared pytest fixtures for aipass tests."""

import os
import shutil
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

# The seam must exist at IMPORT time, not only inside the autouse fixture: the
# repo-root conftest guard refuses to import a branch's json shim while
# AIPASS_TEST_LOG_DIR is unset (1081 errors under `-c pyproject.toml --rootdir=.`
# on 2026-09-06). Sixteen branches set it here; this one set it per-test only
# and passed in CI solely because a sibling conftest had already set it.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.modules import profile as profile_mod
from aipass.cli.apps.modules import display


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real ``aipass_json/``
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here -- after import -- still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/aipass/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def isolate_profile_store(tmp_path_factory) -> Generator[Path, None, None]:
    """Point the user profile at a temp dir for EVERY test in this branch.

    Not belt-and-braces — it closes a live-state leak found 2026-08-27:
    test_init_flow injects a MagicMock at
    sys.modules["aipass.aipass.apps.modules.profile"], but
    ``from ...modules import profile`` resolves the attribute already set on
    the parent package whenever another test file imported the real module
    first. The mock is then silently bypassed and the profile stage writes the
    REAL store. test_help_flag + test_init_flow together rewrote the live
    profile to null defaults; either file alone was clean, which is why no
    single-file run ever caught it.

    Autouse and unconditional because the leak is an ORDERING effect: any test
    that reaches profile code through an unmocked path is a candidate, and
    naming them one by one only holds until the next import order changes.
    """
    store_dir = tmp_path_factory.mktemp("profile_store")
    with (
        patch.object(profile_mod, "_PROFILE_JSON", store_dir / "user_profile.json"),
        patch.object(profile_mod, "_LEGACY_LOCAL_JSON", store_dir / "local.json"),
    ):
        yield store_dir


@pytest.fixture
def sample_test_data() -> dict:
    """Provides sample test data."""
    return {"test_key": "test_value", "sample_data": "example"}


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


class _HeaderEvents:
    """Stands where cli's display keeps its trigger, and records each fire."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def fire(self, event: str, **data: object) -> None:
        self.calls.append((event, data))


@pytest.fixture(autouse=True)
def header_events(monkeypatch: pytest.MonkeyPatch) -> _HeaderEvents:
    """cli's header() fires cli_header_displayed on the real trigger bus, which has a
    live handler, and display caches the trigger it loaded in _TRIGGER. A test that
    prints through the real console must not fire it, so every test gets a recorder
    in that slot; a test about a header asserts the title off .calls."""
    events = _HeaderEvents()
    monkeypatch.setattr(display, "_TRIGGER", events)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return events
