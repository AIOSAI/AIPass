# =================== AIPass ====================
# Name: test_memory_pool_handler.py
# Description: Tests for memory_pool_auto_processed event handler
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/events/memory_pool.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the event wiring in apps/handlers/events/registry.py; the bus tests cover delivery

import pytest
from unittest.mock import MagicMock
from pathlib import Path

from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers.events import memory_pool, registry
from aipass.trigger.apps.modules import core


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the real handler's two outward writes away from live state.

    Real trail_logger, not a mock: the handler's sidecar is what
    test_writes_handler_log_on_failure reads back, so the logger is rebuilt
    on tmp_path. json_handler writes the live operation log and is mocked.
    """
    monkeypatch.setattr(memory_pool, "logger", trail_logger(tmp_path / "logs" / "memory_pool_handler.jsonl"))
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(memory_pool, "json_handler", mock_json_handler)


def _import_module():
    """Return the real memory_pool module the fixture patched."""
    return memory_pool


class TestHandleMemoryPoolAutoProcessedSuccess:
    """Tests for successful auto-process events."""

    def test_logs_success(self) -> None:
        """Logs pool stats via json_handler on success."""
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(
            success=True,
            branch="memory",
            pool={"status": "success", "files_processed": 3, "total_chunks": 42},
            rollover={"status": "skipped", "triggers": 0, "processed": 0},
        )

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_pool_auto_processed",
            {
                "success": True,
                "files_processed": 3,
                "total_chunks": 42,
                "pool_status": "success",
                "rollover_status": "skipped",
            },
        )

    def test_success_does_not_fire_error(self) -> None:
        """Success path does not fire error_detected."""
        mod = _import_module()
        fire_event = MagicMock()

        mod.handle_memory_pool_auto_processed(
            success=True,
            pool={"status": "success", "files_processed": 0, "total_chunks": 0},
            rollover={"status": "skipped"},
            fire_event=fire_event,
        )

        fire_event.assert_not_called()

    def test_absent_pool_and_rollover_log_as_unknown_not_as_a_crash(self) -> None:
        """Missing sections collapse to the documented defaults, and still log.

        `pool = pool or {}` is the whole reason a firer may omit them, and the
        payload it produces is the point: absent is reported as zero counts and
        a named "unknown" status, never as a silently missing key. Surviving
        the call proved only that .get was not reached on None — it passed
        equally if the handler returned early and logged nothing at all.
        """
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(success=True)

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_pool_auto_processed",
            {
                "success": True,
                "files_processed": 0,
                "total_chunks": 0,
                "pool_status": "unknown",
                "rollover_status": "unknown",
            },
        )

    def test_empty_pool_noop(self) -> None:
        """Zero files processed logs correctly."""
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(
            success=True,
            pool={"status": "success", "files_processed": 0, "total_chunks": 0},
        )

        call_args = json_handler.log_operation.call_args[0]  # type: ignore[union-attr]
        assert call_args[1]["files_processed"] == 0
        assert call_args[1]["total_chunks"] == 0


class TestHandleMemoryPoolAutoProcessedFailure:
    """Tests for failed auto-process events."""

    def test_fires_error_detected_on_failure(self) -> None:
        """Fires error_detected through the event bus on failure."""
        mod = _import_module()
        fire_event = MagicMock()

        mod.handle_memory_pool_auto_processed(
            success=False,
            branch="memory",
            error="ChromaDB connection refused",
            fire_event=fire_event,
        )

        fire_event.assert_called_once_with(
            "error_detected",
            branch="memory",
            error_type="MemoryPoolAutoProcessError",
            message="ChromaDB connection refused",
            source_file="auto_process.py",
        )

    def test_logs_failure(self) -> None:
        """Logs failure via json_handler."""
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(
            success=False,
            error="fastembed subprocess crashed",
        )

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_pool_auto_processed",
            {
                "success": False,
                "error": "fastembed subprocess crashed",
            },
        )

    def test_failure_default_error_message(self) -> None:
        """Uses default error message when none provided."""
        mod = _import_module()
        fire_event = MagicMock()

        mod.handle_memory_pool_auto_processed(
            success=False,
            fire_event=fire_event,
        )

        call_kwargs = fire_event.call_args[1]
        assert "no detail" in call_kwargs["message"]

    def test_failure_default_branch(self) -> None:
        """Defaults branch to 'memory' when not provided."""
        mod = _import_module()
        fire_event = MagicMock()

        mod.handle_memory_pool_auto_processed(
            success=False,
            error="test error",
            fire_event=fire_event,
        )

        assert fire_event.call_args[1]["branch"] == "memory"

    def test_a_failure_with_no_fire_event_still_records_the_failure(self) -> None:
        """No callback means no dispatch — it must not also mean no record.

        fire_event arrives through **kwargs, so it is optional by construction
        and every caller that forgets it lands here. The danger is not the
        crash this unit used to rule out; it is the handler treating an absent
        callback as nothing to do and dropping the failure on the floor, which
        would leave a memory pool error with no trace anywhere.
        """
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(
            success=False,
            error="something broke",
        )

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_pool_auto_processed",
            {"success": False, "error": "something broke"},
        )

    def test_writes_handler_log_on_failure(self, tmp_path: Path) -> None:
        """Writes to handler log file on failure."""
        mod = _import_module()

        mod.handle_memory_pool_auto_processed(
            success=False,
            error="pool write failed",
        )

        log_file = tmp_path / "logs" / "memory_pool_handler.jsonl"
        assert log_file.exists()
        content = log_file.read_text(encoding="utf-8")
        assert "pool write failed" in content


class TestEventRegistration:
    """Tests for event registration in the event system."""

    def test_event_registered_and_discoverable(self, monkeypatch) -> None:
        """memory_pool_auto_processed is registered in the handler registry."""
        import sys
        from unittest.mock import MagicMock

        mock_trigger = MagicMock()
        mock_trigger.on = MagicMock()

        # setup_handlers resolves core/email_send at CALL time, so no registry
        # re-import is needed. The real core module, its bus swapped for a recording mock, so
        # setup_handlers wires nothing onto the live bus.
        monkeypatch.setattr(core, "trigger", mock_trigger)

        # HELD: ai_mail's email_send is another branch's live delivery; the stub
        # keeps the adapter setup_handlers builds off real mail.
        mock_mail = MagicMock()
        mock_mail.deliver_email_to_branch = MagicMock(return_value=(True, None))
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email_send", mock_mail)

        registry.setup_handlers()

        registered_events = [call[0][0] for call in mock_trigger.on.call_args_list]
        assert "memory_pool_auto_processed" in registered_events

    def test_fires_once_per_invocation(self) -> None:
        """Handler executes once per event fire (not per-turn)."""
        mod = _import_module()
        json_handler = mod.json_handler

        mod.handle_memory_pool_auto_processed(
            success=True,
            pool={"status": "success", "files_processed": 1, "total_chunks": 10},
        )

        assert json_handler.log_operation.call_count == 1  # type: ignore[union-attr]
