# =================== META ====================
# Name: test_snapshot_fidelity.py
# Description: Tests for snapshot fidelity -- mirror-delete, quick-check, long paths, error semantics
# Version: 2.1.1
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for aipass/backup/apps/handlers/report/result.py, cleanup/mirror.py, copy/snapshot.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — cleanup/, copy/, report/ handlers parse without errors
# seedgo: no-test-needed(documentation) — handler functions carry docstrings
# seedgo: no-test-needed(stdlib) — shutil, pathlib, os standard library usage

import json
import shutil
from pathlib import Path

import pathspec

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot
from aipass.backup.apps.handlers.report.result import BackupResult

# Why trail.log_operation is NOT patched out anywhere in this file:
# conftest's autouse mock_infrastructure points AIPASS_TEST_LOG_DIR at
# tmp_path/_aipass_json_seam, and trail.log_path() recomputes its path on every
# call, so the real audit append already lands inside the test's own directory.
# The seam sits BESIDE every tree these tests walk (source/, snapshot/, project/),
# never inside one, so no walk sees it. test_cleanup_records_audit_trail reads the
# real stream back through the product's own log_path().
#
# Why the should_ignore predicates name "keep.txt":
# mirror.py:95 accepts should_ignore and never calls it. That dead parameter is a
# held specimen, not cured here, so every predicate below is chosen to give the
# SAME outcome whether the product consults it or not: keep.txt either has a live
# source (so mirror-delete never considers it) or is absent from that tree. The
# answer depends on the path it is handed; the test's claim does not depend on the
# product's answer to it.


class TestBackupResultErrors:
    """BackupResult critical vs non-critical error semantics."""

    def test_add_error_non_critical(self) -> None:
        """Non-critical error appends to errors but keeps success True."""
        r = BackupResult(mode="snapshot")
        r.add_error("minor issue")
        assert len(r.errors) == 1
        assert r.success is True
        assert len(r.critical_errors) == 0

    def test_add_error_critical(self) -> None:
        """Critical error marks success False and appears in critical_errors."""
        r = BackupResult(mode="snapshot")
        r.add_error("disk failure", is_critical=True)
        assert r.success is False
        assert len(r.critical_errors) == 1
        assert "disk failure" in r.critical_errors

    def test_add_warning(self) -> None:
        """Warnings are tracked separately and do not affect success."""
        r = BackupResult(mode="snapshot")
        r.add_warning("path too long")
        assert len(r.warnings) == 1
        assert r.success is True

    def test_files_deleted_field(self, tmp_path: Path) -> None:
        """files_deleted defaults to 0 and carries the count cleanup_deleted_files computed."""
        r = BackupResult(mode="snapshot")
        assert r.files_deleted == 0

        source = tmp_path / "counted_source"
        source.mkdir()
        snapshot = tmp_path / "counted_snapshot"
        snapshot.mkdir()
        for name in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"):
            (snapshot / name).write_text(name, encoding="utf-8")

        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", r)
        assert r.files_deleted == 5

    def test_errors_list_still_works(self) -> None:
        """Backward compat -- errors as list[str] assignment still works."""
        r = BackupResult(mode="snapshot")
        r.errors = ["err1", "err2"]
        assert len(r.errors) == 2


class TestCleanupMirror:
    """Mirror-delete -- cleanup removes vanished files from snapshot."""

    def test_cleanup_removes_deleted_source(self, tmp_path: Path) -> None:
        """File in snapshot but not in source is deleted from snapshot."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "keep.txt").write_text("keep", encoding="utf-8")

        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "keep.txt").write_text("keep", encoding="utf-8")
        (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", result)

        assert not (snapshot / "gone.txt").exists()
        assert (snapshot / "keep.txt").exists()
        assert result.files_deleted == 1

    def test_cleanup_deletes_all_orphans(self, tmp_path: Path) -> None:
        """All files whose source is gone are deleted (no exceptions list)."""
        source = tmp_path / "source"
        source.mkdir()

        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "README.md").write_text("readme", encoding="utf-8")
        (snapshot / "old.txt").write_text("old", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", result)
        assert not (snapshot / "README.md").exists()
        assert not (snapshot / "old.txt").exists()
        assert result.files_deleted == 2

    def test_cleanup_empty_dir_removed(self, tmp_path: Path) -> None:
        """Empty dirs cleaned up after file deletion."""
        source = tmp_path / "source"
        source.mkdir()

        snapshot = tmp_path / "snapshot"
        subdir = snapshot / "old_dir"
        subdir.mkdir(parents=True)
        (subdir / "stale.txt").write_text("stale", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", result)
        assert not subdir.exists()

    def test_cleanup_nonexistent_backup(self, tmp_path: Path) -> None:
        """No error if backup_path does not exist."""
        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(
            tmp_path / "nonexistent",
            tmp_path / "source",
            lambda p: p.name == "keep.txt",
            result,
        )
        assert result.files_deleted == 0

    def test_cleanup_dry_run(self, tmp_path: Path) -> None:
        """Dry run counts deletions but does not actually delete."""
        source = tmp_path / "source"
        source.mkdir()
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", result, dry_run=True)
        assert (snapshot / "gone.txt").exists()
        assert result.files_deleted == 1

    def test_cleanup_records_audit_trail(self, tmp_path: Path) -> None:
        """cleanup_started and cleanup_complete reach the real JSONL audit stream."""
        source = tmp_path / "audited_source"
        source.mkdir()
        snapshot = tmp_path / "audited_snapshot"
        snapshot.mkdir()
        (snapshot / "orphan.txt").write_text("orphan", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, lambda p: p.name == "keep.txt", result)

        stream = trail.log_path()
        lines = stream.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
        operations = [entry["operation"] for entry in entries]
        assert operations.count("cleanup_started") == 1

        completed = [entry for entry in entries if entry["operation"] == "cleanup_complete"]
        assert len(completed) == 1
        assert completed[0]["files_deleted"] == 1
        assert completed[0]["dry_run"] is False


def _empty_spec() -> pathspec.PathSpec:
    """Build an empty PathSpec for tests."""
    return pathspec.PathSpec.from_lines("gitignore", [])


class TestCopySnapshotUpgrade:
    """Snapshot copy with mirror-delete and mtime skip."""

    def test_copy_skips_unchanged(self, tmp_path: Path) -> None:
        """Files with same mtime are skipped."""
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
