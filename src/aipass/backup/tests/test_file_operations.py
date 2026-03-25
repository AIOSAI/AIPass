"""Tests for file_operations module - copy and backup-need checks."""

import os
from contextlib import nullcontext
from pathlib import Path
from unittest.mock import MagicMock, patch


# ─── file_needs_backup ──────────────────────────────────


class TestFileNeedsBackup:
    """Tests for file_needs_backup function."""

    def test_file_needs_backup_newer_file(self, tmp_path):
        """Returns True when source is newer than last recorded timestamp."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "readme.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "readme.txt"
        backup_file.parent.mkdir(parents=True)
        backup_file.write_text("old content", encoding="utf-8")

        # Set source mtime to 2000, timestamp recorded at 1000 => newer
        os.utime(source_file, (2000.0, 2000.0))
        last_timestamps = {"readme.txt": 1000.0}

        assert file_needs_backup(source_file, backup_file, last_timestamps, source_dir) is True

    def test_file_needs_backup_unchanged(self, tmp_path):
        """Returns False when source mtime equals the last recorded timestamp."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "readme.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "readme.txt"
        backup_file.parent.mkdir(parents=True)
        backup_file.write_text("content", encoding="utf-8")

        os.utime(source_file, (1000.0, 1000.0))
        last_timestamps = {"readme.txt": 1000.0}

        assert file_needs_backup(source_file, backup_file, last_timestamps, source_dir) is False

    def test_file_needs_backup_older_than_timestamp(self, tmp_path):
        """Returns False when source mtime is older than the last recorded timestamp."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "readme.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "readme.txt"
        backup_file.parent.mkdir(parents=True)
        backup_file.write_text("content", encoding="utf-8")

        os.utime(source_file, (500.0, 500.0))
        last_timestamps = {"readme.txt": 1000.0}

        assert file_needs_backup(source_file, backup_file, last_timestamps, source_dir) is False

    def test_file_needs_backup_no_timestamp(self, tmp_path):
        """Returns True when no timestamp exists for the file (defaults to 0)."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "readme.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "readme.txt"
        backup_file.parent.mkdir(parents=True)
        backup_file.write_text("content", encoding="utf-8")

        # Any positive mtime > 0 (the default) means it needs backup
        os.utime(source_file, (100.0, 100.0))
        last_timestamps: dict[str, float] = {}  # no entry

        assert file_needs_backup(source_file, backup_file, last_timestamps, source_dir) is True

    def test_file_needs_backup_no_backup_file(self, tmp_path):
        """Returns True when backup file does not exist (regardless of timestamps)."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "readme.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "readme.txt"
        # backup_file does not exist

        last_timestamps = {"readme.txt": 99999.0}

        assert file_needs_backup(source_file, backup_file, last_timestamps, source_dir) is True


# ─── copy_file_with_structure ────────────────────────────


class TestCopyFileWithStructure:
    """Tests for copy_file_with_structure function."""

    def test_creates_dirs(self, tmp_path):
        """Creates parent directories when they do not exist."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "hello.txt"
        source.parent.mkdir(parents=True)
        source.write_text("data", encoding="utf-8")

        target = tmp_path / "dst" / "nested" / "deep" / "hello.txt"
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_checked = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert target.parent.exists()
        assert target.parent.is_dir()

    def test_copies_content(self, tmp_path):
        """Copied file content matches the source."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "file.txt"
        source.parent.mkdir(parents=True)
        source.write_text("important content here", encoding="utf-8")

        target = tmp_path / "dst" / "file.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_checked = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert rv is True
        assert target.read_text(encoding="utf-8") == "important content here"

    def test_long_path_rejected(self, tmp_path):
        """Paths longer than 260 characters are rejected and return False."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "file.txt"
        source.parent.mkdir(parents=True)
        source.write_text("data", encoding="utf-8")

        # Build a path >260 chars
        long_segment = "a" * 250
        target = tmp_path / "dst" / long_segment / "file.txt"
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.add_warning = MagicMock()

        assert len(str(target)) > 260

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert rv is False
        result.add_warning.assert_called_once()

    def test_updates_result(self, tmp_path):
        """json_handler.log_operation is called on success, confirming result tracking."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "file.txt"
        source.parent.mkdir(parents=True)
        source.write_text("data", encoding="utf-8")

        target = tmp_path / "dst" / "file.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_checked = 0

        mock_jh = MagicMock()
        with patch.object(file_operations, "json_handler", mock_jh), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert rv is True
        mock_jh.log_operation.assert_called_once_with("file_copied")


# ─── copy_versioned_file ─────────────────────────────────


class TestCopyVersionedFile:
    """Tests for copy_versioned_file function."""

    def test_creates_baseline(self, tmp_path):
        """New file creates a baseline snapshot alongside the target."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "app.py"
        source.parent.mkdir(parents=True)
        source.write_text("print('hello')", encoding="utf-8")

        target = tmp_path / "dst" / "app.py"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_added = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_versioned_file(source, target, backup_root, result)

        assert rv is True
        assert target.exists()
        assert target.read_text(encoding="utf-8") == "print('hello')"

        # Baseline file should exist in the same directory
        baselines = list(target.parent.glob("app-baseline-*.py"))
        assert len(baselines) == 1

    def test_updates_result(self, tmp_path):
        """BackupResult.files_added is incremented for new files."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "config.json"
        source.parent.mkdir(parents=True)
        source.write_text('{"key": "val"}', encoding="utf-8")

        target = tmp_path / "dst" / "config.json"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_added = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            file_operations.copy_versioned_file(source, target, backup_root, result)

        # files_added is incremented once by copy_versioned_file (result.files_added += 1)
        assert result.files_added == 1


# ─── Contract: return type verification ──────────────────


class TestFileNeedsBackupReturnType:
    """file_needs_backup always returns exactly bool."""

    def test_returns_bool_true(self, tmp_path):
        """Returns exactly bool True when file needs backup."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "f.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "f.txt"
        # No backup file => needs backup

        result = file_needs_backup(source_file, backup_file, {}, source_dir)
        assert type(result) is bool
        assert result is True

    def test_returns_bool_false(self, tmp_path):
        """Returns exactly bool False when file is unchanged."""
        from aipass.backup.apps.handlers.operations.file_operations import file_needs_backup

        source_dir = tmp_path / "source"
        source_dir.mkdir()
        source_file = source_dir / "f.txt"
        source_file.write_text("content", encoding="utf-8")

        backup_file = tmp_path / "backup" / "f.txt"
        backup_file.parent.mkdir(parents=True)
        backup_file.write_text("content", encoding="utf-8")

        os.utime(source_file, (1000.0, 1000.0))
        result = file_needs_backup(source_file, backup_file, {"f.txt": 1000.0}, source_dir)
        assert type(result) is bool
        assert result is False


class TestCopyFileWithStructureErrorContract:
    """copy_file_with_structure error handling contracts."""

    def test_missing_source_returns_false_and_adds_error(self, tmp_path):
        """Returns False and calls result.add_error when source file is missing."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "missing.txt"
        # source intentionally does not exist
        target = tmp_path / "dst" / "missing.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_checked = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert rv is False
        result.add_error.assert_called_once()
        error_msg = result.add_error.call_args[0][0]
        assert "missing" in error_msg.lower() or "source" in error_msg.lower()

    def test_success_returns_bool_true(self, tmp_path):
        """Returns exactly bool True on successful copy."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "ok.txt"
        source.parent.mkdir(parents=True)
        source.write_text("data", encoding="utf-8")

        target = tmp_path / "dst" / "ok.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_checked = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_file_with_structure(source, target, backup_root, result)

        assert type(rv) is bool
        assert rv is True


class TestCopyVersionedFileErrorContract:
    """copy_versioned_file error handling contracts."""

    def test_long_path_returns_false_and_warns(self, tmp_path):
        """Returns False and calls result.add_warning for paths >260 chars."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "file.txt"
        source.parent.mkdir(parents=True)
        source.write_text("data", encoding="utf-8")

        long_segment = "a" * 250
        target = tmp_path / "dst" / long_segment / "file.txt"
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.add_warning = MagicMock()

        assert len(str(target)) > 260

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_versioned_file(source, target, backup_root, result)

        assert rv is False
        result.add_warning.assert_called_once()

    def test_missing_source_returns_false_and_adds_error(self, tmp_path):
        """Returns False and calls result.add_error when source is missing."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "ghost.txt"
        # source intentionally does not exist
        target = tmp_path / "dst" / "ghost.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_versioned_file(source, target, backup_root, result)

        assert rv is False
        result.add_error.assert_called_once()

    def test_success_returns_bool_true(self, tmp_path):
        """Returns exactly bool True on successful versioned copy."""
        from aipass.backup.apps.handlers.operations import file_operations

        source = tmp_path / "src" / "v.txt"
        source.parent.mkdir(parents=True)
        source.write_text("versioned content", encoding="utf-8")

        target = tmp_path / "dst" / "v.txt"
        target.parent.mkdir(parents=True)
        backup_root = tmp_path / "dst"

        result = MagicMock()
        result.files_added = 0

        with patch.object(file_operations, "json_handler"), \
             patch.object(file_operations, "safe_print"), \
             patch.object(file_operations, "temporarily_writable", return_value=nullcontext()):
            rv = file_operations.copy_versioned_file(source, target, backup_root, result)

        assert type(rv) is bool
        assert rv is True
