"""Tests for backup_metadata_builder — backup metadata construction."""

import datetime
from pathlib import Path
from unittest.mock import MagicMock


class TestCreateBackupMetadataVersioned:
    """create_backup_metadata with versioned behavior appends to backup list."""

    def test_versioned_inserts_at_front(self):
        """New backup entry is inserted at position 0 in the backups list."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 10
        result.files_copied = 5
        result.files_added = 2
        result.files_skipped = 3
        result.errors = 0

        existing = {"backups": [{"backup_name": "old"}]}

        info = create_backup_metadata(
            mode="versioned",
            behavior="versioned",
            backup_note="test note",
            backup_folder_name="v1",
            backup_path=Path("/tmp/backup/v1"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps={},
            existing_backup_info=existing,
        )

        assert len(info["backups"]) == 2
        assert info["backups"][0]["backup_name"] == "v1"
        assert info["backups"][1]["backup_name"] == "old"

    def test_versioned_entry_contains_stats(self):
        """Versioned entry includes all expected stat fields."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 20
        result.files_copied = 15
        result.files_added = 4
        result.files_skipped = 1
        result.errors = 2

        existing = {"backups": []}

        info = create_backup_metadata(
            mode="versioned",
            behavior="versioned",
            backup_note="stats check",
            backup_folder_name="v2",
            backup_path=Path("/tmp/v2"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps={},
            existing_backup_info=existing,
        )

        stats = info["backups"][0]["stats"]
        assert stats["files_checked"] == 20
        assert stats["files_copied"] == 15
        assert stats["files_added"] == 4
        assert stats["files_skipped"] == 1
        assert stats["errors"] == 2

    def test_versioned_entry_has_timestamp(self):
        """Versioned entry includes an ISO-format timestamp."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 0
        result.files_copied = 0
        result.files_added = 0
        result.files_skipped = 0
        result.errors = 0

        existing = {"backups": []}

        info = create_backup_metadata(
            mode="versioned",
            behavior="versioned",
            backup_note="",
            backup_folder_name="v3",
            backup_path=Path("/tmp/v3"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps={},
            existing_backup_info=existing,
        )

        ts = info["backups"][0]["timestamp"]
        # Should parse without error
        datetime.datetime.fromisoformat(ts)

    def test_versioned_preserves_note_and_paths(self):
        """Versioned entry stores backup_note, backup_path, and source_path."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 0
        result.files_copied = 0
        result.files_added = 0
        result.files_skipped = 0
        result.errors = 0

        existing = {"backups": []}

        info = create_backup_metadata(
            mode="versioned",
            behavior="versioned",
            backup_note="my note",
            backup_folder_name="v4",
            backup_path=Path("/tmp/v4"),
            source_dir=Path("/my/src"),
            result=result,
            current_timestamps={},
            existing_backup_info=existing,
        )

        entry = info["backups"][0]
        assert entry["backup_note"] == "my note"
        assert entry["backup_path"] == "/tmp/v4"
        assert entry["source_path"] == "/my/src"
        assert entry["mode"] == "versioned"


class TestCreateBackupMetadataDynamic:
    """create_backup_metadata with non-versioned behavior returns flat dict."""

    def test_dynamic_returns_flat_dict(self):
        """Dynamic mode returns a dict with top-level keys (not a backups list)."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 8
        result.files_copied = 4
        result.files_added = 1
        result.files_skipped = 3
        result.files_deleted = 2
        result.errors = 0

        timestamps = {"file_a.txt": "2026-01-01T00:00:00"}

        info = create_backup_metadata(
            mode="snapshot",
            behavior="dynamic",
            backup_note="dyn note",
            backup_folder_name="snap1",
            backup_path=Path("/tmp/snap1"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps=timestamps,
            existing_backup_info={},
        )

        assert "backups" not in info
        assert info["backup_note"] == "dyn note"
        assert info["mode"] == "snapshot"
        assert info["backup_path"] == "/tmp/snap1"
        assert info["file_timestamps"] == timestamps

    def test_dynamic_includes_files_deleted(self):
        """Dynamic mode stats include files_deleted (versioned does not)."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 5
        result.files_copied = 3
        result.files_added = 0
        result.files_skipped = 2
        result.files_deleted = 7
        result.errors = 1

        info = create_backup_metadata(
            mode="snapshot",
            behavior="dynamic",
            backup_note="",
            backup_folder_name="snap2",
            backup_path=Path("/tmp/snap2"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps={},
            existing_backup_info={},
        )

        stats = info["stats"]
        assert stats["files_deleted"] == 7
        assert stats["errors"] == 1

    def test_dynamic_has_last_backup_timestamp(self):
        """Dynamic mode includes a parseable last_backup timestamp."""
        from aipass.backup.apps.handlers.json.backup_metadata_builder import (
            create_backup_metadata,
        )

        result = MagicMock()
        result.files_checked = 0
        result.files_copied = 0
        result.files_added = 0
        result.files_skipped = 0
        result.files_deleted = 0
        result.errors = 0

        info = create_backup_metadata(
            mode="snapshot",
            behavior="dynamic",
            backup_note="",
            backup_folder_name="snap3",
            backup_path=Path("/tmp/snap3"),
            source_dir=Path("/src"),
            result=result,
            current_timestamps={},
            existing_backup_info={},
        )

        datetime.datetime.fromisoformat(info["last_backup"])
