# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for aipass tests — json and profile redirects, console width, command state
# Version: 1.5.0
# Created: 2026-05-04
# Modified: 2026-10-26
#
# CHANGELOG (Max 5 entries):
#   - v1.5.0 (2026-10-26): no_real_codex keeps doctor's Codex rows off the real binary and ~/.codex
#   - v1.4.0 (2026-10-10): temp_test_dir, sample_test_data retired - requested only by the .archive scaffold (PR #774)
#   - v1.3.0 (2026-10-05): tools_on_path writes PATH so shutil.which answers for real (DPLAN-0354 leg 8)
#   - v1.2.0 (2026-09-28): header_events recorder keeps cli's header off the real trigger bus (DPLAN-0354 leg 3)
#   - v1.1.0 (2026-09-27): template C1/C2 fixtures; unused mock_json_handler removed (DPLAN-0354)
# =============================================

"""Shared pytest fixtures for aipass tests."""

import os
import tempfile
from pathlib import Path
from typing import Generator
from unittest.mock import patch

# At import time: the repo-root conftest guard refuses to import a json shim while it is unset.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.aipass.apps.handlers.json import json_handler
from aipass.aipass.apps.modules import profile as profile_mod
from aipass.cli.apps.modules import display


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    Autouse: without the seam the shim writes into the real ``aipass_json/``."""
    # Own subdir: a seam AT tmp_path makes tmp_path/aipass/, colliding with branch-named test dirs.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def isolate_profile_store(tmp_path_factory) -> Generator[Path, None, None]:
    """Point the user profile at a temp dir for EVERY test in this branch.

    Autouse: import order can bypass a sys.modules profile mock and write the live store."""
    store_dir = tmp_path_factory.mktemp("profile_store")
    with (
        patch.object(profile_mod, "_PROFILE_JSON", store_dir / "user_profile.json"),
        patch.object(profile_mod, "_LEGACY_LOCAL_JSON", store_dir / "local.json"),
    ):
        yield store_dir


@pytest.fixture
def tools_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Set PATH to one tmp directory holding an executable stub per name given.

    shutil.which answers for real; under PATHEXT (Windows) each stub takes its first extension."""

    def put(*names: str) -> Path:
        bin_dir = tmp_path / "path_bin"
        bin_dir.mkdir(exist_ok=True)
        pathext = os.environ.get("PATHEXT", "")
        suffix = pathext.split(os.pathsep)[0].lower() if pathext else ""
        for name in names:
            stub = bin_dir / f"{name}{suffix}"
            stub.write_text("", encoding="utf-8")
            stub.chmod(stub.stat().st_mode | 0o111)  # no effect where the platform has no mode bit
        monkeypatch.setenv("PATH", str(bin_dir))
        return bin_dir

    return put


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def no_real_codex(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Doctor's Codex rows see no codex on PATH unless a test hands them a fake, and
    CODEX_HOME is tmp_path/codex_home, so no test reads or writes the real ~/.codex."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex_home"))
    monkeypatch.setattr("aipass.aipass.apps.modules._doctor_wire._codex_which", lambda name: None)


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
    live handler, so every test gets a recorder in display's cached _TRIGGER (assert off .calls)."""
    events = _HeaderEvents()
    monkeypatch.setattr(display, "_TRIGGER", events)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return events
