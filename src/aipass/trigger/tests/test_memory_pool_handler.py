# =================== AIPass ====================
# Name: test_memory_pool_handler.py
# Description: Tests for memory_pool_auto_processed event handler
# Version: 1.1.0
# Created: 2026-06-06
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/events/memory_pool.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — the event wiring in apps/handlers/events/registry.py; the bus tests cover delivery

import pytest
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock
from pathlib import Path

from aipass.ai_mail.apps.modules import email_send
from aipass.trigger.apps.config import trail_logger
from aipass.trigger.apps.handlers import error_registry, error_reporter
from aipass.trigger.apps.handlers.events import error_detected, memory_pool, registry
from aipass.trigger.apps.handlers.json import json_handler
from aipass.trigger.apps.modules import core


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Point the real handler's two outward writes away from live state.

    A real trail_logger on tmp_path: test_writes_handler_log_on_failure reads its sidecar back.
    """
    monkeypatch.setattr(memory_pool, "logger", trail_logger(tmp_path / "logs" / "memory_pool_handler.jsonl"))
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(memory_pool, "json_handler", mock_json_handler)
    monkeypatch.setattr(memory_pool, "report_error", MagicMock(return_value={}))


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

        Absent is reported as zero counts and an "unknown" status, never as a missing key.
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
        """Reports the failure through the registry, which fires error_detected on the bus."""
        mod = _import_module()

        mod.handle_memory_pool_auto_processed(
            success=False,
            branch="memory",
            error="ChromaDB connection refused",
            fire_event=MagicMock(),
        )

        mod.report_error.assert_called_once_with(  # type: ignore[attr-defined]
            error_type="MemoryPoolAutoProcessError",
            message="ChromaDB connection refused",
            component="MEMORY",
            fire_event=True,
        )

    def test_the_fired_payload_gets_past_the_handler_first_guard(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The real report_error and handle_error_detected: the failure reaches the gates, never dropped at the guard.
        Red first: a payload with no module or error_hash returned before any gate ran.
        """
        monkeypatch.setattr(memory_pool, "report_error", error_reporter.report_error)
        monkeypatch.setattr(error_registry, "REGISTRY_FILE", tmp_path / "error_registry.json")
        monkeypatch.setattr(error_registry, "CB_STATE_FILE", tmp_path / "trigger_cb_state.json")
        monkeypatch.setattr(json_handler, "log_operation", MagicMock(return_value=True))
        monkeypatch.setattr(error_detected, "_is_medic_enabled", MagicMock(return_value=False))
        suppressed = MagicMock()
        monkeypatch.setattr(error_detected, "_write_suppression_log", suppressed)

        def _bus(event: str, **data: Any) -> None:
            assert event == "error_detected"
            error_detected.handle_error_detected(**data)

        monkeypatch.setattr(core, "trigger", SimpleNamespace(fire=_bus))

        memory_pool.handle_memory_pool_auto_processed(
            success=False, branch="memory", error="pool down", fire_event=_bus
        )

        reason, branch, module, _ = suppressed.call_args.args
        assert (reason, branch, module) == (
            "Medic OFF - suppressed dispatch for",
            "MEMORY",
            "MemoryPoolAutoProcessError",
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

        assert "no detail" in mod.report_error.call_args.kwargs["message"]  # type: ignore[attr-defined]

    def test_failure_default_branch(self) -> None:
        """Defaults branch to 'memory' when not provided."""
        mod = _import_module()
        fire_event = MagicMock()

        mod.handle_memory_pool_auto_processed(
            success=False,
            error="test error",
            fire_event=fire_event,
        )

        assert mod.report_error.call_args.kwargs["component"] == "MEMORY"  # type: ignore[attr-defined]

    def test_a_failure_with_no_fire_event_still_records_the_failure(self) -> None:
        """No callback means no dispatch — it must not also mean no record.

        fire_event is optional by construction (**kwargs); an absent one must not drop the failure.
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
        from unittest.mock import MagicMock

        mock_trigger = MagicMock()
        mock_trigger.on = MagicMock()

        # setup_handlers resolves core at call time: swapping its bus wires nothing live.
        monkeypatch.setattr(core, "trigger", mock_trigger)

        # Keeps the adapter setup_handlers builds off ai_mail's real delivery.
        monkeypatch.setattr(email_send, "deliver_email_to_branch", MagicMock(return_value=(True, None)))

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
