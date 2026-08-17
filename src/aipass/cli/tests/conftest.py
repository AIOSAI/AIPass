# =================== AIPass ====================
# Name: tests/conftest.py
# Description: Shared pytest fixtures for CLI branch tests
# Version: 3.1.0
# Created: 2026-03-07
# Modified: 2026-08-16
# =============================================

"""Shared pytest fixtures for CLI tests."""

import os
import re
import tempfile
from io import StringIO

# Redirect prax logs to temp directory during tests
# Must be set before any prax imports to catch logger initialization
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest
from rich.console import Console

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
