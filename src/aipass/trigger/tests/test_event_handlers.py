# =================== AIPass ====================
# Name: test_event_handlers.py
# Description: Tests for simple event handler functions
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for cli, memory_template_updated, and warning_logged event handlers."""

import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports for all six handler modules."""
    from aipass.trigger.apps.config import atomic_write_json, migrate_json_file

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
    mock_config.AIPASS_PKG_ROOT = tmp_path / "aipass"
    mock_config.atomic_write_json = atomic_write_json
    mock_config.TRIGGER_JSON_DIR = tmp_path / "trigger_json"
    mock_config.migrate_json_file = migrate_json_file
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.config", mock_config)

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.trigger.apps.handlers.json", json_pkg)
    monkeypatch.setitem(
        sys.modules,
        "aipass.trigger.apps.handlers.json.json_handler",
        mock_json_handler,
    )

    for mod_name in (
        "aipass.trigger.apps.handlers.events.cli",
        "aipass.trigger.apps.handlers.events.memory_template_updated",
        "aipass.trigger.apps.handlers.events.warning_logged",
    ):
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


def _import_cli():
    """Import cli handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.cli as m

    return m


def _import_memory_template_updated():
    """Import memory_template_updated handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.memory_template_updated as m

    return m


def _import_warning_logged():
    """Import warning_logged handler module fresh after mocking."""
    import aipass.trigger.apps.handlers.events.warning_logged as m

    return m


# ---------------------------------------------------------------------------
# cli.py -- handle_cli_header_displayed
# ---------------------------------------------------------------------------


class TestHandleCliHeaderDisplayed:
    """Tests for handle_cli_header_displayed from cli.py."""

    def test_calls_log_operation(self) -> None:
        """Logs cli_event via json_handler."""
        mod = _import_cli()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_cli_header_displayed()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "cli_event", {"success": True}
        )

    def test_accepts_arbitrary_kwargs(self) -> None:
        """Does not crash when extra kwargs are passed."""
        mod = _import_cli()
        mod.handle_cli_header_displayed(foo="bar", baz=42)

    def test_returns_none(self) -> None:
        """Handler returns None (handlers must not return values)."""
        mod = _import_cli()
        result = mod.handle_cli_header_displayed()
        assert result is None


# ---------------------------------------------------------------------------
# memory_template_updated.py -- handle_memory_template_updated
# ---------------------------------------------------------------------------


class TestHandleMemoryTemplateUpdated:
    """Tests for handle_memory_template_updated from memory_template_updated.py."""

    def test_calls_log_operation(self) -> None:
        """Logs memory_template_event via json_handler."""
        mod = _import_memory_template_updated()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_memory_template_updated()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "memory_template_event", {"success": True}
        )

    def test_accepts_kwargs(self) -> None:
        """Does not crash when event data kwargs are passed."""
        mod = _import_memory_template_updated()
        mod.handle_memory_template_updated(template_name="local", updated_by="drone")

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = _import_memory_template_updated()
        result = mod.handle_memory_template_updated()
        assert result is None


# ---------------------------------------------------------------------------
# warning_logged.py -- handle_warning_logged
# ---------------------------------------------------------------------------


class TestHandleWarningLogged:
    """Tests for handle_warning_logged from warning_logged.py."""

    def test_calls_log_operation(self) -> None:
        """Logs warning_logged_event via json_handler."""
        mod = _import_warning_logged()
        from aipass.trigger.apps.handlers.json import json_handler

        json_handler.log_operation.reset_mock()  # type: ignore[union-attr]

        mod.handle_warning_logged()

        json_handler.log_operation.assert_called_once_with(  # type: ignore[union-attr]
            "warning_logged_event", {"success": True}
        )

    def test_accepts_all_named_params(self) -> None:
        """Accepts all documented event parameters without error."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(
            branch="flow",
            message="disk almost full",
            error_hash="w1",
            timestamp="2026-04-25T12:00:00",
            log_file="flow.log",
            module_name="watcher",
            level="warning",
        )

    def test_does_not_crash_with_none_params(self) -> None:
        """Handles None for every named parameter gracefully."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(
            branch=None,
            message=None,
            error_hash=None,
            timestamp=None,
            log_file=None,
            module_name=None,
            level=None,
        )

    def test_accepts_extra_kwargs(self) -> None:
        """Accepts unexpected kwargs via **kwargs."""
        mod = _import_warning_logged()
        mod.handle_warning_logged(extra_field="unexpected")

    def test_returns_none(self) -> None:
        """Handler returns None."""
        mod = _import_warning_logged()
        result = mod.handle_warning_logged()
        assert result is None
