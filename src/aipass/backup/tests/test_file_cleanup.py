"""Tests for file_cleanup module - deleted file cleanup operations."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch


class TestCleanupDeletedFiles:
    """Tests for cleanup_deleted_files function."""

    def test_cleanup_removes_missing_files(self, tmp_path):
        """Files present in backup but absent from source get deleted."""
        from aipass.backup.apps.handlers.operations import file_cleanup

        source = tmp_path / "source"
        source.mkdir()
        (source / "kept.txt").write_text("keep me", encoding="utf-8")
        # "removed.txt" intentionally absent from source

        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "kept.txt").write_text("keep me", encoding="utf-8")
        (backup / "removed.txt").write_text("delete me", encoding="utf-8")

        result = MagicMock()
        result.files_deleted = 0

        with patch.object(file_cleanup, "json_handler"), \
             patch.object(file_cleanup, "safe_print"), \
             patch.object(file_cleanup, "temporarily_writable", return_value=nullcontext()):
            file_cleanup.cleanup_deleted_files(
                backup, source, should_ignore=lambda p: False, result=result,
            )

        assert not (backup / "removed.txt").exists()
        assert (backup / "kept.txt").exists()

    def test_cleanup_dry_run_preserves(self, tmp_path):
        """dry_run=True reports what would be deleted but preserves all files."""
        from aipass.backup.apps.handlers.operations import file_cleanup

        source = tmp_path / "source"
        source.mkdir()

        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "orphan.txt").write_text("should survive", encoding="utf-8")

        result = MagicMock()
        result.files_deleted = 0

        with patch.object(file_cleanup, "json_handler"), \
             patch.object(file_cleanup, "safe_print"), \
             patch.object(file_cleanup, "temporarily_writable", return_value=nullcontext()):
            file_cleanup.cleanup_deleted_files(
                backup, source, should_ignore=lambda p: False, result=result, dry_run=True,
            )

        # File still exists because dry_run is True
        assert (backup / "orphan.txt").exists()

    def test_cleanup_removes_empty_dirs(self, tmp_path):
        """Empty directories are cleaned up after their files are deleted."""
        from aipass.backup.apps.handlers.operations import file_cleanup

        source = tmp_path / "source"
        source.mkdir()
        # Source has no "subdir" => it should be removed from backup

        backup = tmp_path / "backup"
        sub = backup / "subdir"
        sub.mkdir(parents=True)
        (sub / "gone.txt").write_text("delete me", encoding="utf-8")

        result = MagicMock()
        result.files_deleted = 0

        with patch.object(file_cleanup, "json_handler"), \
             patch.object(file_cleanup, "safe_print"), \
             patch.object(file_cleanup, "temporarily_writable", return_value=nullcontext()):
            file_cleanup.cleanup_deleted_files(
                backup, source, should_ignore=lambda p: False, result=result,
            )

        # Both file and its parent directory should be gone
        assert not sub.exists()

    def test_cleanup_respects_ignore_exceptions(self, tmp_path):
        """Paths matched by should_ignore are treated as deletable.

        The should_ignore callback returns True for paths that SHOULD be ignored
        in backups, meaning they should be cleaned up from the backup destination.
        Paths that should_ignore returns False for are considered valid and preserved.
        """
        from aipass.backup.apps.handlers.operations import file_cleanup

        source = tmp_path / "source"
        source.mkdir()
        # "protected.txt" exists in source, should not be removed
        (source / "protected.txt").write_text("safe", encoding="utf-8")

        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "protected.txt").write_text("safe", encoding="utf-8")
        (backup / "ignored_file.txt").write_text("remove me", encoding="utf-8")

        result = MagicMock()
        result.files_deleted = 0

        # should_ignore returns True for "ignored" paths -> they get cleaned up
        # Returns False for everything else -> those are preserved if source exists
        with patch.object(file_cleanup, "json_handler"), \
             patch.object(file_cleanup, "safe_print"), \
             patch.object(file_cleanup, "temporarily_writable", return_value=nullcontext()):
            file_cleanup.cleanup_deleted_files(
                backup, source,
                should_ignore=lambda p: "ignored" in str(p),
                result=result,
            )

        assert (backup / "protected.txt").exists()
        assert not (backup / "ignored_file.txt").exists()

    def test_cleanup_updates_result(self, tmp_path):
        """BackupResult.files_deleted is incremented for each removed file."""
        from aipass.backup.apps.handlers.operations import file_cleanup
        from aipass.backup.apps.handlers.models.backup_models import BackupResult

        source = tmp_path / "source"
        source.mkdir()

        backup = tmp_path / "backup"
        backup.mkdir()
        (backup / "a.txt").write_text("gone", encoding="utf-8")
        (backup / "b.txt").write_text("gone", encoding="utf-8")

        result = MagicMock(spec=BackupResult)
        result.files_deleted = 0

        with patch.object(file_cleanup, "json_handler"), \
             patch.object(file_cleanup, "safe_print"), \
             patch.object(file_cleanup, "temporarily_writable", return_value=nullcontext()):
            file_cleanup.cleanup_deleted_files(
                backup, source, should_ignore=lambda p: False, result=result,
            )

        # files_deleted is incremented once per removed file (a.txt and b.txt = 2)
        assert result.files_deleted == 2
