# =================== AIPass ====================
# Name: support_test_filesystem_handler.py
# Description: Shared helpers for test_filesystem_handler.py and its split siblings
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Helpers shared by the filesystem_handler test files (no test_ prefix: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — MonitoringFileHandler, covered by tests/test_filesystem_handler.py

from pathlib import Path

from aipass.prax.apps.handlers.monitoring import filesystem_handler

# The doubles _filesystem_handler_doubled set on the module for the running test.
_DOUBLES: dict = {}


def _import_filesystem_handler():
    """The top-bound module and the doubles the autouse fixture set on it."""
    return (
        filesystem_handler,
        _DOUBLES["event_queue"],
        _DOUBLES["branch_detector"],
        _DOUBLES["filters"],
        _DOUBLES["queue"],
    )


def _make_handler(mod, queue=None, command_indicator_files=None):
    """Create a MonitoringFileHandler with a given queue."""
    return mod.MonitoringFileHandler(
        event_queue=queue,
        command_indicator_files=command_indicator_files,
    )


def _on_disk(tmp_path: Path, data: str, name: str = "session.jsonl") -> Path:
    """Write ``data`` as bytes to a real file: the handler opens, seeks and stats it itself."""
    path = tmp_path / name
    path.write_bytes(data.encode("utf-8"))
    return path
