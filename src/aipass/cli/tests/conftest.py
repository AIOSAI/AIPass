# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for CLI branch tests
# Version: 4.2.0
# Created: 2026-03-05
# Modified: 2026-10-17
# =============================================

"""Shared pytest fixtures for CLI tests."""

import os
import re
import tempfile
from io import StringIO
from pathlib import Path
from typing import Generator, List, Tuple

# Must be set before any prax import, or logger initialization writes the real logs.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from rich.console import Console

from aipass.cli.apps import cli as branch_entry
from aipass.cli.apps.handlers.json import json_handler
from aipass.cli.apps.modules import display
from aipass.trigger.apps.modules import core as trigger_core

# .archive/ holds verbatim disposal copies of old suites; they must never be collected.
collect_ignore_glob = [".archive/*", "**/.archive/*"]

# Every CSI escape Rich can emit: colour and attributes (bold, dim, reset).
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Return only the characters a human would SEE in the terminal."""
    # Raw output depends on the shell: FORCE_COLOR makes Rich colour even a StringIO.
    return _ANSI_PATTERN.sub("", text)


def make_capture_console(**kwargs):
    """Build a Console whose rendering the environment CANNOT influence."""
    # Output still goes through strip_ansi(): pinning alone failed under TERM=dumb.
    buf = StringIO()
    console = Console(
        file=buf,
        force_terminal=False,
        color_system=None,
        no_color=True,
        width=120,
        **kwargs,
    )

    def get_output() -> str:
        return strip_ansi(buf.getvalue())

    return console, get_output


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


class TriggerRecorder:
    """Stands where display keeps its trigger and records what header() fires."""

    def __init__(self) -> None:
        self.fired: List[Tuple[str, dict]] = []

    def fire(self, event: str, **data) -> None:
        self.fired.append((event, data))


@pytest.fixture(autouse=True)
def trigger_recorder(monkeypatch) -> TriggerRecorder:
    """header() fires cli_header_displayed on the live trigger bus, which has a live
    handler; the recorder replaces display's cached _TRIGGER and trigger's own names."""
    recorder = TriggerRecorder()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    monkeypatch.setattr(trigger_core, "trigger", recorder)
    monkeypatch.setattr(trigger_core.Trigger, "fire", lambda _self, event, **data: recorder.fire(event, **data))
    return recorder


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect cli's json writes into a temp dir; autouse, or the real cli_json/ gets them."""
    # A seam AT tmp_path would create tmp_path/cli/ and collide with a test's own dir.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger as (level, args) tuples."""
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    monkeypatch.setattr(branch_entry, "logger", _CapturingLogger())
    return captured
