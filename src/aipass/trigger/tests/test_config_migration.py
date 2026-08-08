# =================== AIPass ====================
# Name: test_config_migration.py
# Description: Tests for migrate_json_file - moving live state off trio-owned paths
# Version: 1.0.0
# Created: 2026-08-07
# Modified: 2026-08-07
# =============================================

"""Tests for config.migrate_json_file and config._archive_legacy_file.

The migration exists because json_handler's trio machinery owns every
`<module>_<config|data|log>.json` name in trigger_json/ and regenerates any
such file whose shape does not match its template. Live hand-written state
parked on one of those names is one caller-name resolution away from being
replaced by a blank template.
"""

import json
from pathlib import Path

from aipass.trigger.apps.config import ARCHIVE_DIR_NAME, migrate_json_file

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
        """Legacy contents land in the new file byte-for-byte in meaning."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        _write(legacy, LIVE_STATE)

        assert migrate_json_file(legacy, new) is True
        assert json.loads(new.read_text(encoding="utf-8")) == LIVE_STATE

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

        Two things are being protected. Copying a blank template forward would
        destroy the live state the migration just rescued. Archiving it on every
        read would fight json_handler — which legitimately owns that filename —
        and grow .archive/ without bound.
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
        """Corrupt legacy file is not archived and not guessed at — a human decides."""
        legacy = tmp_path / "trigger_config.json"
        new = tmp_path / "medic_state.json"
        legacy.parent.mkdir(parents=True, exist_ok=True)
        legacy.write_text("{not json", encoding="utf-8")

        assert migrate_json_file(legacy, new) is False
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
