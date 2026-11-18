# =================== AIPass ====================
# Name: test_config_migration.py
# Description: Tests for migrate_json_file - moving live state off trio-owned paths
# Version: 1.0.0
# Created: 2026-08-07
# Modified: 2026-11-18
# =============================================

"""Tests for apps/config.py: migrate_json_file, _archive_legacy_file and where trigger_json lives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(behaviour) — the trio regeneration in apps/handlers/json/json_handler.py; that handler owns it

import json
from pathlib import Path

import pytest

from aipass.trigger.apps.config import ARCHIVE_DIR_NAME, TRIGGER_JSON_DIR, TRIGGER_ROOT, migrate_json_file
from aipass.trigger.apps.handlers import error_registry, escalation, failure_report, log_watcher, medic_state
from aipass.trigger.apps.handlers.events import runaway_handler, startup
from aipass.trigger.apps.handlers.json import config_loader

# conftest's sandboxes swap these per test; the values bound at import are the ones under test.
_STARTUP_SUPPRESSED_LOG = startup.SUPPRESSED_LOG
_CONFIG_LOADER_TRAIL = config_loader.logger.path

LIVE_STATE = {
    "config": {"medic_enabled": True, "muted_branches": [{"name": "flow", "expires_at": None}]},
    "circuit_breaker": {"state": "closed"},
}


def _write(path: Path, data) -> None:
    """Write JSON to path, creating parents."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


class TestMigrateJsonFile:
    """Migration of live state from a legacy path to its new home."""

    def test_no_legacy_file_is_noop(self, tmp_path: Path) -> None:
        """Nothing to migrate — returns False, creates nothing."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"

        assert migrate_json_file(legacy, new) is False
        assert not new.exists()
        assert not (tmp_path / ARCHIVE_DIR_NAME).exists()

    def test_migrates_contents_when_new_absent(self, tmp_path: Path) -> None:
        """Legacy contents land in the new file byte-for-byte in meaning.

        Swapped into place, not copied: no staging `.tmp` is left in the trio-owned directory.
        """
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        _write(legacy, LIVE_STATE)

        assert migrate_json_file(legacy, new) is True
        assert json.loads(new.read_text(encoding="utf-8")) == LIVE_STATE
        assert sorted(p.name for p in tmp_path.glob("*.tmp")) == []

    def test_legacy_is_archived_not_deleted(self, tmp_path: Path) -> None:
        """The legacy file moves to .archive/ — never deleted."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        _write(legacy, LIVE_STATE)

        migrate_json_file(legacy, new)

        assert not legacy.exists()
        archived = tmp_path / ARCHIVE_DIR_NAME / "trigger_config.json"
        assert archived.exists()
        assert json.loads(archived.read_text(encoding="utf-8")) == LIVE_STATE

    def test_second_call_is_noop(self, tmp_path: Path) -> None:
        """Idempotent — safe to call on every read."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        _write(legacy, LIVE_STATE)

        assert migrate_json_file(legacy, new) is True
        assert migrate_json_file(legacy, new) is False
        assert json.loads(new.read_text(encoding="utf-8")) == LIVE_STATE

    def test_new_file_wins_and_legacy_name_is_left_to_its_owner(self, tmp_path: Path) -> None:
        """Once migrated, a file re-created at the legacy name is not touched.

        Copying it forward would destroy rescued state; archiving it would fight json_handler, its owner.
        """
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        blank_template = {"module_name": "trigger", "version": "1.0.0", "config": {}}
        _write(new, LIVE_STATE)
        _write(legacy, blank_template)

        assert migrate_json_file(legacy, new) is False
        assert json.loads(new.read_text(encoding="utf-8")) == LIVE_STATE
        assert json.loads(legacy.read_text(encoding="utf-8")) == blank_template
        assert not (tmp_path / ARCHIVE_DIR_NAME).exists()

    def test_unreadable_legacy_is_left_in_place(self, tmp_path: Path) -> None:
        """Pins the default: an unreadable legacy file answered None under a warning; now it raises, left in place."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("{not json", encoding="utf-8")

        with pytest.raises(RuntimeError, match=r"trigger_config\.json unreadable"):
            migrate_json_file(legacy, new)
        assert legacy.exists()
        assert not new.exists()

    def test_archive_collision_keeps_both_copies(self, tmp_path: Path) -> None:
        """A pre-existing archived file is never overwritten."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        archive_dir = tmp_path / ARCHIVE_DIR_NAME
        _write(archive_dir / "trigger_config.json", {"older": True})
        _write(legacy, LIVE_STATE)

        assert migrate_json_file(legacy, new) is True

        archived = sorted(p.name for p in archive_dir.glob("trigger_config*.json"))
        assert len(archived) == 2
        assert json.loads((archive_dir / "trigger_config.json").read_text(encoding="utf-8")) == {"older": True}


class TestStateFolder:
    """trigger_json comes from prax's state root, never from counting folders up from config.py."""

    def test_trigger_json_follows_the_state_root_redirect_not_the_code_folder(self) -> None:
        # conftest set AIPASS_TEST_LOG_DIR before import, so prax's root sits outside the code folder.
        assert TRIGGER_JSON_DIR.name == "trigger_json"
        assert TRIGGER_JSON_DIR.parent.name == "trigger"
        assert not TRIGGER_JSON_DIR.is_relative_to(TRIGGER_ROOT)

    def test_every_state_file_and_log_sits_under_the_state_root_beside_trigger_json(self) -> None:
        root = TRIGGER_JSON_DIR.parent
        logs = root / "logs"
        assert [
            error_registry.REGISTRY_FILE,
            error_registry.CB_STATE_FILE,
            log_watcher.TRIGGER_DATA_FILE,
            escalation.ESCALATION_LOG,
            failure_report.FAILURES_LOG,
            runaway_handler.DECISION_LOG,
            _STARTUP_SUPPRESSED_LOG,
            medic_state.MEDIC_SUPPRESSED_LOG,
            medic_state.RATE_LIMITED_LOG,
            _CONFIG_LOADER_TRAIL,
        ] == [
            root / "trigger_json" / "error_registry.json",
            root / "trigger_json" / "trigger_cb_state.json",
            root / "trigger_data.json",
            logs / "escalation.jsonl",
            logs / "failures.jsonl",
            logs / "runaway_suppressed.jsonl",
            logs / "medic_suppressed.jsonl",
            logs / "medic_suppressed.jsonl",
            logs / "rate_limited.jsonl",
            logs / "config_loader.jsonl",
        ]
