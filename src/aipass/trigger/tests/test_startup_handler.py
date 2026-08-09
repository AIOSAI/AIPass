# =================== AIPass ====================
# Name: test_startup_handler.py
# Description: Tests for startup event handler
# Version: 1.0.0
# Created: 2026-04-25
# Modified: 2026-04-25
# =============================================

"""Tests for startup event handler."""

import pytest
from unittest.mock import MagicMock
from pathlib import Path


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Mock heavy infrastructure imports before importing the handler module."""
    import sys

    from aipass.trigger.apps.config import atomic_write_json, migrate_json_file

    mock_config = MagicMock()
    mock_config.TRIGGER_ROOT = tmp_path
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

    monkeypatch.delitem(
        sys.modules,
        "aipass.trigger.apps.handlers.events.startup",
        raising=False,
    )


def _import_startup():
    """Import fresh after mocking."""
    import aipass.trigger.apps.handlers.events.startup as m

    return m


class TestHandleStartup:
    """Tests for handle_startup."""

    def test_calls_error_catchup_with_fire_event(self) -> None:
        """Passes fire_event kwarg to _run_error_catchup."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        fire_event = MagicMock()
        mod.handle_startup(fire_event=fire_event)

        mod._run_error_catchup.assert_called_once_with(fire_event)  # type: ignore[union-attr]

    def test_passes_none_when_no_fire_event(self) -> None:
        """Without fire_event kwarg, passes None to error catchup."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        mod.handle_startup()

        mod._run_error_catchup.assert_called_once_with(None)  # type: ignore[union-attr]

    def test_extra_kwargs_do_not_crash(self) -> None:
        """Arbitrary extra kwargs are silently ignored."""
        mod = _import_startup()
        mod._run_error_catchup = MagicMock()

        mod.handle_startup(fire_event=MagicMock(), extra_arg="ignored", count=42)

        mod._run_error_catchup.assert_called_once()  # type: ignore[union-attr]


class TestCatchupStateMigration:
    """Catch-up state moves off the trio-owned trigger_data.json name."""

    def test_load_migrates_legacy_catchup_file(self) -> None:
        """Processed hashes survive the move — nothing is re-dispatched."""
        import json

        mod = _import_startup()
        legacy = mod.LEGACY_CATCHUP_STATE_FILE
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text(
            json.dumps(
                {"error_catchup": {"last_scan_timestamp": "2026-08-07T12:00:00", "processed_hashes": ["a1", "b2"]}}
            ),
            encoding="utf-8",
        )

        data = mod._load_trigger_data()

        assert data["error_catchup"]["processed_hashes"] == ["a1", "b2"]
        assert mod.CATCHUP_STATE_FILE.exists()
        assert not legacy.exists()

    def test_save_targets_new_file(self) -> None:
        """Saves go to error_catchup.json, never back to the legacy name."""
        mod = _import_startup()

        mod._save_trigger_data({"error_catchup": {"processed_hashes": []}})

        assert mod.CATCHUP_STATE_FILE.exists()
        assert not mod.LEGACY_CATCHUP_STATE_FILE.exists()
