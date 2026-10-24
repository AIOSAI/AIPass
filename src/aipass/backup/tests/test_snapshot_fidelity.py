# =================== META ====================
# Name: test_snapshot_fidelity.py
# Description: Tests for the snapshot handlers -- BackupResult error semantics, mirror-delete cleanup, snapshot copy
# Version: 2.2.1
# Created: 2026-06-12
# Modified: 2026-10-23
# =============================================

"""Tests for the snapshot handlers in apps/handlers/: report/result.py, cleanup/mirror.py, copy/snapshot.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — cleanup/, copy/, report/ handlers parse without errors
# seedgo: no-test-needed(documentation) — handler functions carry docstrings
# seedgo: no-test-needed(stdlib) — shutil, pathlib, os standard library usage

import json
import os
import shutil
from pathlib import Path

import pytest

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.cleanup.mirror import cleanup_deleted_files
from aipass.backup.apps.handlers.copy.snapshot import copy_snapshot
from aipass.backup.apps.handlers.path import builder as path_builder
from aipass.backup.apps.handlers.report.result import BackupResult
from aipass.backup.apps.modules.snapshot import run_snapshot


# Why trail.log_operation is NOT patched out anywhere in this file:
# conftest's autouse mock_infrastructure points AIPASS_TEST_LOG_DIR at
# tmp_path.parent / f"{tmp_path.name}_aipass_json_seam" (conftest.py:155), and
# trail.log_path() recomputes its path on every call, so the real audit append
# lands in a per-test directory. The seam sits BESIDE tmp_path and every tree
# these tests walk (source/, snapshot/, project/), never inside one, so no walk
# sees it. test_cleanup_writes_started_and_complete_to_audit_stream reads the
# real stream back through the product's own log_path().


class TestBackupResultErrors:
    """BackupResult critical vs non-critical error semantics."""

    def test_non_critical_error_is_recorded_and_success_stays_true(self) -> None:
        """Non-critical error appends to errors but keeps success True."""
        r = BackupResult(mode="snapshot")
        r.add_error("minor issue")
        assert r.errors == ["minor issue"]
        assert r.success is True
        assert len(r.critical_errors) == 0

    def test_critical_error_sets_success_false_and_lands_in_critical_errors(self) -> None:
        """Critical error marks success False and appears in critical_errors."""
        r = BackupResult(mode="snapshot")
        r.add_error("disk failure", is_critical=True)
        assert r.success is False
        assert len(r.critical_errors) == 1
        assert "disk failure" in r.critical_errors

    def test_warning_is_recorded_and_success_stays_true(self) -> None:
        """Warnings are tracked separately and do not affect success."""
        r = BackupResult(mode="snapshot")
        r.add_warning("path too long")
        assert r.warnings == ["path too long"]
        assert r.success is True

    def test_files_deleted_starts_at_zero_and_carries_the_cleanup_count(self, tmp_path: Path) -> None:
        """files_deleted defaults to 0 and carries the count cleanup_deleted_files computed."""
        r = BackupResult(mode="snapshot")
        assert r.files_deleted == 0

        source = tmp_path / "counted_source"
        source.mkdir()
        snapshot = tmp_path / "counted_snapshot"
        snapshot.mkdir()
        for name in ("a.txt", "b.txt", "c.txt", "d.txt", "e.txt"):
            (snapshot / name).write_text(name, encoding="utf-8")

        cleanup_deleted_files(snapshot, source, r)
        assert r.files_deleted == 5

    def test_errors_field_accepts_direct_list_assignment(self) -> None:
        """errors is a plain list[str] dataclass field; a list assigned to it reads back unchanged."""
        r = BackupResult(mode="snapshot")
        r.errors = ["err1", "err2"]
        assert len(r.errors) == 2


class TestCleanupMirror:
    """Mirror-delete -- cleanup removes vanished files from snapshot."""

    def test_cleanup_deletes_orphan_and_keeps_file_with_live_source(self, tmp_path: Path) -> None:
        """File in snapshot but not in source is deleted from snapshot."""
        source = tmp_path / "source"
        source.mkdir()
        (source / "keep.txt").write_text("keep", encoding="utf-8")

        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "keep.txt").write_text("keep", encoding="utf-8")
        (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, result)

        assert not (snapshot / "gone.txt").exists()
        assert (snapshot / "keep.txt").exists()
        assert result.files_deleted == 1

    def test_cleanup_deletes_every_orphan_readme_included(self, tmp_path: Path) -> None:
        """All files whose source is gone are deleted (no exceptions list)."""
        source = tmp_path / "source"
        source.mkdir()

        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "README.md").write_text("readme", encoding="utf-8")
        (snapshot / "old.txt").write_text("old", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, result)
        assert not (snapshot / "README.md").exists()
        assert not (snapshot / "old.txt").exists()
        assert result.files_deleted == 2

    def test_cleanup_removes_directory_left_empty_by_deletion(self, tmp_path: Path) -> None:
        """Empty dirs cleaned up after file deletion."""
        source = tmp_path / "source"
        source.mkdir()

        snapshot = tmp_path / "snapshot"
        subdir = snapshot / "old_dir"
        subdir.mkdir(parents=True)
        (subdir / "stale.txt").write_text("stale", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, result)
        assert not subdir.exists()
        assert result.files_deleted == 1

    def test_cleanup_of_missing_snapshot_dir_deletes_nothing_without_raising(self, tmp_path: Path) -> None:
        """No error if backup_path does not exist."""
        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(
            tmp_path / "nonexistent",
            tmp_path / "source",
            result,
        )
        assert result.files_deleted == 0

    def test_cleanup_dry_run_counts_orphan_but_leaves_it_on_disk(self, tmp_path: Path) -> None:
        """Dry run counts deletions but does not actually delete."""
        source = tmp_path / "source"
        source.mkdir()
        snapshot = tmp_path / "snapshot"
        snapshot.mkdir()
        (snapshot / "gone.txt").write_text("gone", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, result, dry_run=True)
        assert (snapshot / "gone.txt").exists()
        assert result.files_deleted == 1

    def test_cleanup_writes_started_and_complete_to_audit_stream(self, tmp_path: Path) -> None:
        """cleanup_started and cleanup_complete reach the real JSONL audit stream."""
        source = tmp_path / "audited_source"
        source.mkdir()
        snapshot = tmp_path / "audited_snapshot"
        snapshot.mkdir()
        (snapshot / "orphan.txt").write_text("orphan", encoding="utf-8")

        result = BackupResult(mode="snapshot")
        cleanup_deleted_files(snapshot, source, result)

        stream = trail.log_path()
        lines = stream.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(line) for line in lines if line.strip()]
        operations = [entry["operation"] for entry in entries]
        assert operations.count("cleanup_started") == 1

        completed = [entry for entry in entries if entry["operation"] == "cleanup_complete"]
        assert len(completed) == 1
        assert completed[0]["files_deleted"] == 1
        assert completed[0]["dry_run"] is False


class TestCopySnapshotUpgrade:
    """Snapshot copy with mirror-delete and mtime skip."""

    def test_copy_skips_file_whose_snapshot_copy_has_same_mtime(self, tmp_path: Path) -> None:
        """Files with same mtime are skipped."""
        source = tmp_path / "project"
        source.mkdir()
        f = source / "file.txt"
        f.write_text("content", encoding="utf-8")

        dest = tmp_path / "snapshot"
        dest.mkdir()
        target = dest / "file.txt"
        target.write_text("older bytes", encoding="utf-8")
        shutil.copystat(str(f), str(target))

        files = [(str(f), "file.txt")]
        result = copy_snapshot(files, str(dest), str(source))
        assert result["files_copied"] == 0
        assert target.read_text(encoding="utf-8") == "older bytes"

    def test_copy_copies_file_absent_from_snapshot(self, tmp_path: Path) -> None:
        """New file is copied to snapshot destination."""
        source = tmp_path / "project"
        source.mkdir()
        f = source / "new.txt"
        f.write_text("new content", encoding="utf-8")

        dest = tmp_path / "snapshot"
        files = [(str(f), "new.txt")]
        result = copy_snapshot(files, str(dest), str(source))
        assert result["files_copied"] == 1
        assert (dest / "new.txt").read_text(encoding="utf-8") == "new content"

    def test_copy_mirror_deletes_snapshot_file_absent_from_source(self, tmp_path: Path) -> None:
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
        result = copy_snapshot(files, str(dest), str(source))
        assert not (dest / "stale.txt").exists()
        assert result["files_deleted"] == 1


class TestAFailedCopyIsRetried:
    """A run with a failed copy must not let the next run's quick-check call the snapshot current."""

    @pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs a POSIX file a user cannot read")
    def test_a_file_that_failed_to_copy_lands_on_the_next_run_with_nothing_else_changed(self, tmp_path: Path) -> None:
        """Mutant: the timestamp map is saved after a failed copy, so the next run returns "no changes"."""
        project = tmp_path / "project"
        project.mkdir()
        (project / "ok.txt").write_text("ok", encoding="utf-8")
        locked = project / "locked.txt"
        locked.write_text("locked", encoding="utf-8")
        mtime = locked.stat().st_mtime_ns

        locked.chmod(0)
        try:
            first = run_snapshot(str(project), show_panels=False)
        finally:
            locked.chmod(0o644)
        os.utime(locked, ns=(mtime, mtime))
        run_snapshot(str(project), show_panels=False)

        assert first.errors
        stored = path_builder.build_snapshot_path(str(project)) / "locked.txt"
        assert stored.read_text(encoding="utf-8") == "locked"


class TestTheLongPathGuardIsWindowsOnly:
    """260 is Windows' MAX_PATH; elsewhere the OS enforces its own limit and the file is stored."""

    PARENT = "p" * 200

    def _long_source(self, tmp_path: Path) -> tuple[Path, Path, str]:
        """A project file whose snapshot copy is over 260 characters: 200 for the folder alone."""
        source = tmp_path / "project"
        (source / self.PARENT).mkdir(parents=True)
        (source / self.PARENT / "a.txt").write_text("deep", encoding="utf-8")
        dest = tmp_path / "snapshot"
        assert len(str(dest / self.PARENT / "a.txt")) > 260
        return source, dest, f"{self.PARENT}/a.txt"

    def test_a_path_over_260_is_stored_where_the_os_allows_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(path_builder, "_MAX_PATH", None)
        source, dest, rel = self._long_source(tmp_path)

        result = copy_snapshot([(str(source / rel), rel)], str(dest), str(source))

        assert (result["files_copied"], result["errors"]) == (1, [])
        assert (dest / self.PARENT / "a.txt").read_text(encoding="utf-8") == "deep"

    def test_under_the_windows_limit_a_path_over_260_is_refused_with_an_errors_row(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(path_builder, "_MAX_PATH", 260)
        source, dest, rel = self._long_source(tmp_path)

        result = copy_snapshot([(str(source / rel), rel)], str(dest), str(source))

        assert (result["files_copied"], result["errors"]) == (0, [f"{rel}: path too long (>260 chars)"])
        assert not (dest / self.PARENT).exists()


# =============================================
