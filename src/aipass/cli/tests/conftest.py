# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for CLI branch tests
# Version: 4.0.0
# Created: 2026-03-07
# Modified: 2026-09-03
# =============================================

"""Shared pytest fixtures for CLI tests."""

import os
import re
import tempfile
from io import StringIO
from pathlib import Path
from typing import List, Tuple

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from rich.console import Console

from aipass.cli.apps.handlers.json import json_handler

# Never discover out of .archive/: it holds verbatim disposal copies (the old
# handler's tests, the pre-service durability and provisioning suites) that must
# not be collected or rglob-walked into dotted module names (DPLAN-0325, spec 4c).
collect_ignore_glob = [".archive/*", "**/.archive/*"]

# Matches every ANSI escape sequence Rich can emit — colour AND attributes
# (bold, dim, reset). CSI form: ESC [ params ... final-byte.
_ANSI_PATTERN = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")


def strip_ansi(text: str) -> str:
    """Return only the characters a human would SEE in the terminal.

    A display test means to assert what is VISIBLE, not which bytes carried it.
    Asserting raw output makes the suite a function of the environment: Rich
    decides whether to emit escapes by probing the terminal, and FORCE_COLOR
    makes it treat even a StringIO as a colour terminal. `created: 5` then
    renders as `created: \\x1b[1m5\\x1b[0m`, so the plain substring is genuinely
    absent from the string while being perfectly legible on screen.

    Learned the expensive way twice in one night, @cli S42 and @daemon S39: the
    same suite was green at 09:00 and red at 22:00 on byte-identical code,
    because only the shell had changed. Green in one shell is luck, not proof.
    """
    return _ANSI_PATTERN.sub("", text)


def make_capture_console(**kwargs):
    """Build a Console whose rendering the environment CANNOT influence.

    force_terminal=False and color_system=None pin the two knobs FORCE_COLOR,
    NO_COLOR and TERM move. Callers still assert through strip_ansi(): pinning
    alone is one env-var away from being wrong again, and @daemon proved that
    layer failed under TERM=dumb after passing under FORCE_COLOR.
    """
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


@pytest.fixture
def sample_data():
    """Reusable sample test data for CLI module tests."""
    return {
        "module_name": "test_module",
        "version": "1.0.0",
        "config": {"max_log_entries": 100},
        "created": "2026-01-01",
        "last_updated": "2026-01-01",
    }


@pytest.fixture(autouse=True)
def _ensure_test_isolation():
    """Auto-applied fixture ensuring clean state between tests."""
    yield
    # teardown: no shared state to clean up currently


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect cli's json writes into a temp dir.

    autouse=True on purpose: the shim's names write into the real cli_json/
    unless the seam is set, so a test that forgets to redirect pollutes the
    branch. The guard belongs on every test, not on the ones that remember.

    The service recomputes its directory on every call, so setting the variable
    here — after import — still takes effect. The sandbox is MEASURED off the
    shim rather than spelled out, so it cannot drift from what the service does.

    Returns:
        The sandbox directory the handler now writes into.
    """
    # Own subdirectory on purpose: the service spells the sandbox
    # <seam>/<branch>/<branch>_json, so a seam AT tmp_path would create
    # tmp_path/cli/ in every test and collide with a test that builds a
    # directory of its own branch's name (backup hit it first, 2026-09-03).
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture
def mock_logger(monkeypatch) -> List[Tuple[str, tuple]]:
    """Capture calls made to the entry point's logger.

    Returns:
        A list that fills with (level, args) tuples as the code under test logs.
    """
    captured: List[Tuple[str, tuple]] = []

    class _CapturingLogger:
        def info(self, *args, **kwargs):
            captured.append(("info", args))

        def warning(self, *args, **kwargs):
            captured.append(("warning", args))

        def error(self, *args, **kwargs):
            captured.append(("error", args))

    from aipass.cli.apps import cli as cli_entry

    monkeypatch.setattr(cli_entry, "logger", _CapturingLogger())
    return captured
