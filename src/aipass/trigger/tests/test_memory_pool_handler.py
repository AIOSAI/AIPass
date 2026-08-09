# =================== AIPass ====================
# Name: test_memory_pool_handler.py
# Description: Tests for memory_pool_auto_processed event handler
# Version: 1.0.0
# Created: 2026-06-06
# Modified: 2026-06-06
# =============================================

"""Tests for memory_pool event handler."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports."""
    import sys

    from aipass.trigger.apps.config import atomic_write_json, trail_logger

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.atomic_write_json = atomic_write_json
    # Real trail_logger, not the auto-mock: the handler's sidecar is what
    # test_writes_handler_log_on_failure reads back, and TRIGGER_ROOT above
    # already points it at tmp_path.
    mock_config.trail_logger = trail_logger
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json.json_handler", mock_json_handler)

    monkeypatch.delitem(sys.modules, "aipass.trigger.apps.handlers.events.memory_pool", raising=False)


def _import_module():
    """Import fresh after mocking."""
    import aipass.trigger.apps.handlers.events.memory_pool as m

    return m


class TestHandleMemoryPoolAutoProcessedSuccess:
    """Tests for successful auto-process events."""

    def test_logs_success(self) -> None:
        """Logs pool stats via json_handler on success."""
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

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

    def test_none_defaults(self) -> None:
        """Handles all-None parameters gracefully."""
        mod = _import_module()
        mod.handle_memory_pool_auto_processed(success=True)

    def test_empty_pool_noop(self) -> None:
        """Zero files processed logs correctly."""
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

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
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

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

    def test_failure_without_fire_event(self) -> None:
        """Handles failure gracefully when fire_event callback not available."""
        mod = _import_module()
        mod.handle_memory_pool_auto_processed(
            success=False,
            error="something broke",
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
        content = log_file.read_text()
        assert "pool write failed" in content


class TestEventRegistration:
    """Tests for event registration in the event system."""

    def test_event_registered_and_discoverable(self, monkeypatch) -> None:
        """memory_pool_auto_processed is registered in the handler registry."""
        import sys
        from unittest.mock import MagicMock

        mock_trigger = MagicMock()
        mock_trigger.on = MagicMock()

        # setup_handlers resolves core/email_send at CALL time, so pinning the
        # sys.modules entries is enough — no registry re-import needed. The old
        # raw assignments here were never restored and left MagicMocks in
        # sys.modules for every later import on the same xdist worker.
        core_mod = MagicMock()
        core_mod.trigger = mock_trigger
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", core_mod)

        mock_mail = MagicMock()
        mock_mail.deliver_email_to_branch = MagicMock(return_value=(True, None))
        monkeypatch.setitem(sys.modules, "aipass.ai_mail.apps.modules.email_send", mock_mail)

        from aipass.trigger.apps.handlers.events.registry import setup_handlers

        setup_handlers()

        registered_events = [call[0][0] for call in mock_trigger.on.call_args_list]
        assert "memory_pool_auto_processed" in registered_events

    def test_fires_once_per_invocation(self) -> None:
        """Handler executes once per event fire (not per-turn)."""
        mod = _import_module()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_memory_pool_auto_processed(
            success=True,
            pool={"status": "success", "files_processed": 1, "total_chunks": 10},
        )

        assert json_handler.log_operation.call_count == 1  # type: ignore[union-attr]
