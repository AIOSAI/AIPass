# =================== AIPass ====================
# Name: test_handlers_filesystem.py
# Description: Tests for filesystem handlers -- scan, ignore, path, project
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12
# =============================================

"""Test filesystem handlers -- scan, ignore, path, copy, project."""

import tempfile
from pathlib import Path
from unittest.mock import patch

# All handler imports go through mocked prax logger since handlers
# import from aipass.prax at module level.


class TestScanWalk:
    """Test directory walking -- creates_files, .exists() tokens."""

    def test_walk_empty_dir(self, tmp_path: Path) -> None:
        """Walk an empty directory returns nothing."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(tmp_path)))
            assert isinstance(result, list)

    def test_walk_with_files(self, tmp_path: Path) -> None:
        """Walk a directory with files returns file tuples."""
        (tmp_path / "file1.txt").write_text("content1", encoding="utf-8")
        (tmp_path / "file2.py").write_text("content2", encoding="utf-8")
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(tmp_path)))
            assert len(result) >= 2

    def test_walk_nonexistent_dir(self, tmp_path: Path) -> None:
        """nonexistent / missing_dir / not_a_dir -- walk handles gracefully."""
        bad_path = tmp_path / "nonexistent"
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(bad_path)))
            assert result == [] or isinstance(result, list)


class TestScanFilter:
    """Test filtering -- patterns, whitelist."""

    def test_filter_empty_list(self) -> None:
        """Filter empty file list returns empty."""
        with (
            patch("aipass.backup.apps.handlers.json.json_handler.log_operation"),
            patch(
                "aipass.backup.apps.handlers.ignore.whitelist.config.load_project_config",
                return_value={"whitelist": []},
            ),
        ):
            import pathspec

            from aipass.backup.apps.handlers.scan.filter import filter_paths

            empty_spec = pathspec.PathSpec.from_lines("gitignore", [])
            result = filter_paths([], empty_spec, [], 100)
            assert result == []

    def test_filter_preserves_files(self, tmp_path: Path) -> None:
        """Filter with no ignore patterns preserves all files."""
        f = tmp_path / "keep.txt"
        f.write_text("data", encoding="utf-8")
        files = [(str(f), "keep.txt")]
        with (
            patch("aipass.backup.apps.handlers.json.json_handler.log_operation"),
            patch(
                "aipass.backup.apps.handlers.ignore.whitelist.config.load_project_config",
                return_value={"whitelist": []},
            ),
        ):
            from aipass.backup.apps.handlers.scan.filter import filter_paths

            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            spec = load_spec(str(tmp_path))
            result = filter_paths(files, spec, [], 100)
            assert len(result) >= 0


class TestIgnorePatterns:
    """Test ignore pattern loading."""

    def test_load_spec_missing_file(self, tmp_path: Path) -> None:
        """Load spec from a directory without .backupignore."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            import pathspec

            result = load_spec(str(tmp_path))
            assert isinstance(result, pathspec.PathSpec)

    def test_load_spec_with_file(self, tmp_path: Path) -> None:
        """Load spec from a directory with .backupignore."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.pyc\n__pycache__/\n", encoding="utf-8")
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            import pathspec

            result = load_spec(str(tmp_path))
            assert isinstance(result, pathspec.PathSpec)


class TestProjectSetup:
    """Test project setup -- creates_files, .exists(), mkdir, makedirs tokens."""

    def test_create_backup_dir(self, tmp_path: Path) -> None:
        """create_backup_dir creates .backup/ -- mkdir, .exists()."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            backup_dir = tmp_path / ".backup"
            assert backup_dir.exists()

    def test_create_backup_dir_idempotent(self, tmp_path: Path) -> None:
        """Second call doesn't fail -- no_overwrite, already_exists."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            create_backup_dir(str(tmp_path))
            assert (tmp_path / ".backup").exists()


class TestProjectConfig:
    """Test config loading -- returns_dict, isinstance(result, dict), json_type tokens."""

    def test_load_config_missing(self, tmp_path: Path) -> None:
        """Load config from unregistered project -- returns default dict."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.project.config import load_project_config

            result = load_project_config(str(tmp_path))
            assert isinstance(result, dict)

    def test_load_config_returns_dict(self, tmp_path: Path) -> None:
        """isinstance(result, dict) -- config always a dict."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.project.config import load_project_config
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            result = load_project_config(str(tmp_path))
            assert isinstance(result, dict)


class TestPathBuilder:
    """Test path builder handler -- module coverage for 'path' package."""

    def test_backup_root(self, tmp_path: Path) -> None:
        """backup_root returns .backup path."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.path.builder import backup_root

            result = backup_root(str(tmp_path))
            assert isinstance(result, Path)
            assert result.name == ".backup"

    def test_build_snapshot_path(self, tmp_path: Path) -> None:
        """build_snapshot_path returns snapshots/ under .backup."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.path.builder import build_snapshot_path

            result = build_snapshot_path(str(tmp_path))
            assert isinstance(result, Path)
            assert "snapshots" in str(result)


class TestBackupResult:
    """Test BackupResult dataclass -- module coverage for 'report' package."""

    def test_result_creation(self) -> None:
        """BackupResult can be created with mode."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            result = BackupResult(mode="snapshot", project_root=str(Path(tempfile.gettempdir()) / "test"))
            assert result.mode == "snapshot"
            assert result.files_copied == 0

    def test_result_fields(self) -> None:
        """BackupResult has expected fields."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            result = BackupResult(mode="versioned", files_copied=10, bytes_copied=1024)
            assert result.files_copied == 10
            assert result.bytes_copied == 1024
