# =================== AIPass ====================
# Name: test_snapshot_fidelity.py
# Description: Tests for snapshot fidelity -- mirror-delete, quick-check, long paths, error semantics
# Version: 2.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Test snapshot fidelity -- mirror-delete, quick-check, long paths, error semantics."""

import shutil
from pathlib import Path
from unittest.mock import patch

import pathspec


class TestBackupResultErrors:
    """BackupResult critical vs non-critical error semantics."""

    def test_add_error_non_critical(self) -> None:
        """Non-critical error appends to errors but keeps success True."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            r = BackupResult(mode="snapshot")
            r.add_error("minor issue")
            assert len(r.errors) == 1
            assert r.success is True
            assert len(r.critical_errors) == 0

    def test_add_error_critical(self) -> None:
        """Critical error marks success False and appears in critical_errors."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            r = BackupResult(mode="snapshot")
            r.add_error("disk failure", is_critical=True)
            assert r.success is False
            assert len(r.critical_errors) == 1
            assert "disk failure" in r.critical_errors

    def test_add_warning(self) -> None:
        """Warnings are tracked separately and do not affect success."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            r = BackupResult(mode="snapshot")
            r.add_warning("path too long")
            assert len(r.warnings) == 1
            assert r.success is True

    def test_files_deleted_field(self) -> None:
        """files_deleted field defaults to 0 and is assignable."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            r = BackupResult(mode="snapshot")
            assert r.files_deleted == 0
            r.files_deleted = 5
            assert r.files_deleted == 5

    def test_errors_list_still_works(self) -> None:
        """Backward compat -- errors as list[str] assignment still works."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            r = BackupResult(mode="snapshot")
            r.errors = ["err1", "err2"]
            assert len(r.errors) == 2


class TestCleanupMirror:
    """Mirror-delete -- cleanup removes vanished files from snapshot."""

    def test_cleanup_removes_deleted_source(self, tmp_path: Path) -> None:
        """File in snapshot but not in source is deleted from snapshot."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
            from aipass.backup.apps.handlers.report.result import BackupResult

            source = tmp_path / "source"
            source.mkdir()
            (source / "keep.txt").write_text("keep", encoding="utf-8")

            snapshot = tmp_path / "snapshot"
            snapshot.mkdir()
            (snapshot / "keep.txt").write_text("keep", encoding="utf-8")
            (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

            result = BackupResult(mode="snapshot")
            cleanup_deleted_files(snapshot, source, lambda p: False, result)

            assert not (snapshot / "gone.txt").exists()
            assert (snapshot / "keep.txt").exists()
            assert result.files_deleted == 1

    def test_cleanup_deletes_all_orphans(self, tmp_path: Path) -> None:
        """All files whose source is gone are deleted (no exceptions list)."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
            from aipass.backup.apps.handlers.report.result import BackupResult

            source = tmp_path / "source"
            source.mkdir()

            snapshot = tmp_path / "snapshot"
            snapshot.mkdir()
            (snapshot / "README.md").write_text("readme", encoding="utf-8")
            (snapshot / "old.txt").write_text("old", encoding="utf-8")

            result = BackupResult(mode="snapshot")
            cleanup_deleted_files(snapshot, source, lambda p: False, result)
            assert not (snapshot / "README.md").exists()
            assert not (snapshot / "old.txt").exists()
            assert result.files_deleted == 2

    def test_cleanup_empty_dir_removed(self, tmp_path: Path) -> None:
        """Empty dirs cleaned up after file deletion."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
            from aipass.backup.apps.handlers.report.result import BackupResult

            source = tmp_path / "source"
            source.mkdir()

            snapshot = tmp_path / "snapshot"
            subdir = snapshot / "old_dir"
            subdir.mkdir(parents=True)
            (subdir / "stale.txt").write_text("stale", encoding="utf-8")

            result = BackupResult(mode="snapshot")
            cleanup_deleted_files(snapshot, source, lambda p: False, result)
            assert not subdir.exists()

    def test_cleanup_nonexistent_backup(self, tmp_path: Path) -> None:
        """No error if backup_path does not exist."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
            from aipass.backup.apps.handlers.report.result import BackupResult

            result = BackupResult(mode="snapshot")
            cleanup_deleted_files(
                tmp_path / "nonexistent",
                tmp_path / "source",
                lambda p: False,
                result,
            )
            assert result.files_deleted == 0

    def test_cleanup_dry_run(self, tmp_path: Path) -> None:
        """Dry run counts deletions but does not actually delete."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
            from aipass.backup.apps.handlers.report.result import BackupResult

            source = tmp_path / "source"
            source.mkdir()
            snapshot = tmp_path / "snapshot"
            snapshot.mkdir()
            (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

            result = BackupResult(mode="snapshot")
            cleanup_deleted_files(snapshot, source, lambda p: False, result, dry_run=True)
            assert (snapshot / "gone.txt").exists()
            assert result.files_deleted == 1


def _empty_spec() -> pathspec.PathSpec:
    """Build an empty PathSpec for tests."""
    return pathspec.PathSpec.from_lines("gitignore", [])


class TestCopySnapshotUpgrade:
    """Snapshot copy with mirror-delete and mtime skip."""

    def test_copy_skips_unchanged(self, tmp_path: Path) -> None:
        """Files with same mtime are skipped."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot

            source = tmp_path / "project"
            source.mkdir()
            f = source / "file.txt"
            f.write_text("content", encoding="utf-8")

            dest = tmp_path / "snapshot"
            dest.mkdir()
            target = dest / "file.txt"
            target.write_text("content", encoding="utf-8")
            shutil.copy2(str(f), str(target))

            files = [(str(f), "file.txt")]
            result = copy_snapshot(files, str(dest), str(source), _empty_spec())
            assert result["files_copied"] == 0

    def test_copy_handles_new_file(self, tmp_path: Path) -> None:
        """New file is copied to snapshot destination."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot

            source = tmp_path / "project"
            source.mkdir()
            f = source / "new.txt"
            f.write_text("new content", encoding="utf-8")

            dest = tmp_path / "snapshot"
            files = [(str(f), "new.txt")]
            result = copy_snapshot(files, str(dest), str(source), _empty_spec())
            assert result["files_copied"] == 1
            assert (dest / "new.txt").exists()

    def test_copy_mirror_deletes(self, tmp_path: Path) -> None:
        """Existing snapshot files not in source are mirror-deleted."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot

            source = tmp_path / "project"
            source.mkdir()
            f = source / "keep.txt"
            f.write_text("keep", encoding="utf-8")

            dest = tmp_path / "snapshot"
            dest.mkdir()
            (dest / "keep.txt").write_text("keep", encoding="utf-8")
            (dest / "stale.txt").write_text("stale", encoding="utf-8")

            files = [(str(f), "keep.txt")]
            result = copy_snapshot(files, str(dest), str(source), _empty_spec())
            assert not (dest / "stale.txt").exists()
            assert result.get("files_deleted", 0) >= 1


# =============================================
