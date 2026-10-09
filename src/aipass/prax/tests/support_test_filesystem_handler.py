# =================== AIPass ====================
# Name: support_test_filesystem_handler.py
# Description: Shared helpers for test_filesystem_handler.py and its split siblings
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Helpers shared by the filesystem_handler test files (no test_ prefix: never collected).

Supports test_filesystem_handler.py (the watchdog events), and its siblings
test_filesystem_handler_tool_action.py, test_filesystem_handler_codex.py and
test_filesystem_handler_agent_activity.py: the doubles table the conftest
fixture _filesystem_handler_doubled fills, the module accessor, the handler
builder and the on-disk session writer, moved here whole when the file was
split (2026-10-08).
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — MonitoringFileHandler, covered by tests/test_filesystem_handler.py

from pathlib import Path

from aipass.prax.apps.handlers.monitoring import filesystem_handler

# The doubles _filesystem_handler_doubled set on the module for the running test.
_DOUBLES: dict = {}


# =============================================
# MODULE IMPORT HELPER
# =============================================


def _import_filesystem_handler():
    """The top-bound module and the doubles the autouse fixture set on it:
    (module, event_queue, branch_detector, filters, queue)."""
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
    """Write ``data`` to a real file under tmp_path and return its path.

    The handler opens, seeks and stats the file itself, so the file is real
    (prax, leg 12): a mocked open stood in for the very read under test.
    Bytes, so the size on disk is the size of ``data`` on every platform.
    """
    path = tmp_path / name
    path.write_bytes(data.encode("utf-8"))
    return path
