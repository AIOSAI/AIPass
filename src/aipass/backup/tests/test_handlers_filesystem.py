# =================== AIPass ====================
# Name: test_handlers_filesystem.py
# Description: Tests for filesystem handlers -- scan, ignore, path, project
# Version: 1.1.0
# Created: 2026-06-12
# Modified: 2026-09-11
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
        """Walk an empty directory yields NOTHING -- the value, not the type.

        isinstance(result, list) was true of a walker that invented entries and
        true of one that returned the caller's own tree; only the emptiness is
        the claim this test's name makes.
        """
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(tmp_path)))
            assert result == []

    def test_walk_with_files(self, tmp_path: Path) -> None:
        """Walk a directory with files returns file tuples."""
        (tmp_path / "file1.txt").write_text("content1", encoding="utf-8")
        (tmp_path / "file2.py").write_text("content2", encoding="utf-8")
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(tmp_path)))
            assert len(result) >= 2

    def test_walk_nonexistent_dir(self, tmp_path: Path) -> None:
        """A missing directory walks to empty, and does not raise.

        The old spelling was 'result == [] or isinstance(result, list)': the
        second clause is true whenever the first one is, so the assertion could
        not fail. Measured 2026-09-08 -- the real answer is the empty list.
        """
        bad_path = tmp_path / "nonexistent"
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.scan.walk import walk_project

            result = list(walk_project(str(bad_path)))
            assert result == []


class TestScanFilter:
    """Test filtering -- patterns, whitelist."""

    def test_filter_empty_list(self) -> None:
        """Filter empty file list returns empty."""
        with (
            patch("aipass.backup.apps.handlers.audit.trail.log_operation"),
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
            patch("aipass.backup.apps.handlers.audit.trail.log_operation"),
            patch(
                "aipass.backup.apps.handlers.ignore.whitelist.config.load_project_config",
                return_value={"whitelist": []},
            ),
        ):
            from aipass.backup.apps.handlers.scan.filter import filter_paths

            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            spec = load_spec(str(tmp_path))
            result = filter_paths(files, spec, [], 100)

            # 'len(result) >= 0' is true of every sequence -- a filter that
            # dropped the one file it was handed passed it. The test is named
            # "preserves files", so preservation is what it now says.
            assert len(result) == 1
            assert result[0] == (str(f), "keep.txt")


class TestIgnorePatterns:
    """Test ignore pattern loading."""

    def test_load_spec_missing_file(self, tmp_path: Path) -> None:
        """With no .backupignore the spec matches nothing but the *.tmp floor.

        The type alone permitted a spec that ignored the whole project, which
        for a backup tool is the silent-data-loss direction: every file
        "matched" and none got copied. The behaviour is the claim.
        """
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            import pathspec

            result = load_spec(str(tmp_path))
            assert isinstance(result, pathspec.PathSpec)
            assert result.match_file("a.pyc") is False
            assert result.match_file("src/main.py") is False

    def test_load_spec_with_file(self, tmp_path: Path) -> None:
        """The patterns in .backupignore are the ones the spec enforces.

        Same file, same two patterns as the fixture writes: a spec that parsed
        the file and threw the rules away is a PathSpec too, so the type said
        nothing about whether load_spec had read a single line.
        """
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.pyc\n__pycache__/\n", encoding="utf-8")
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.ignore.patterns import load_spec

            import pathspec

            result = load_spec(str(tmp_path))
            assert isinstance(result, pathspec.PathSpec)
            assert result.match_file("a.pyc") is True
            assert result.match_file("__pycache__/mod.py") is True
            assert result.match_file("src/main.py") is False


class TestProjectSetup:
    """Test project setup -- creates_files, .exists(), mkdir, makedirs tokens."""

    def test_create_backup_dir(self, tmp_path: Path) -> None:
        """create_backup_dir creates .backup/ -- mkdir, .exists()."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            backup_dir = tmp_path / ".backup"
            assert backup_dir.exists()

    def test_create_backup_dir_idempotent(self, tmp_path: Path) -> None:
        """Second call doesn't fail -- no_overwrite, already_exists."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            create_backup_dir(str(tmp_path))
            assert (tmp_path / ".backup").exists()


class TestProjectConfig:
    """Test config loading -- returns_dict, isinstance(result, dict), json_type tokens."""

    def test_load_config_missing(self, tmp_path: Path) -> None:
        """An unregistered project gets the DEFAULTS, ceilings included.

        The docstring already said "returns default dict"; only the "dict" half
        was ever asserted, and {} is a dict. The ceilings matter most: if
        max_backup_files came back missing or zero, the run ceiling that refuses
        a runaway tree would either not arm or refuse everything.
        """
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.project.config import load_project_config

            result = load_project_config(str(tmp_path))
            assert isinstance(result, dict)
            assert result["backup_mode"] == "snapshot"
            assert result["max_versions"] == 10
            assert result["max_backup_files"] == 25000
            assert result["max_backup_size_gb"] == 10
            assert result["whitelist"] == []

    def test_config_written_by_setup_identifies_the_project(self, tmp_path: Path) -> None:
        """create_backup_dir writes a config that names the project it belongs to.

        Renamed off "returns_dict": that was the type, and the type is what the
        sibling above already covers. What create_backup_dir adds over the
        defaults is the identity block, and mixing that up is how one project's
        config could point at another project's tree.
        """
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.project.config import load_project_config
            from aipass.backup.apps.handlers.project.setup import create_backup_dir

            create_backup_dir(str(tmp_path))
            result = load_project_config(str(tmp_path))

            assert isinstance(result, dict)
            assert result["project_name"] == tmp_path.name
            assert Path(result["project_path"]) == tmp_path
            assert result["max_backup_files"] == 25000


class TestPathBuilder:
    """Test path builder handler -- module coverage for 'path' package."""

    def test_backup_root(self, tmp_path: Path) -> None:
        """backup_root returns .backup path."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.path.builder import backup_root

            result = backup_root(str(tmp_path))
            assert isinstance(result, Path)
            assert result.name == ".backup"

    def test_build_snapshot_path(self, tmp_path: Path) -> None:
        """build_snapshot_path returns snapshots/ under .backup."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.path.builder import build_snapshot_path

            result = build_snapshot_path(str(tmp_path))
            assert isinstance(result, Path)
            assert "snapshots" in str(result)


class TestBackupResult:
    """Test BackupResult dataclass -- module coverage for 'report' package."""

    def test_result_creation(self) -> None:
        """BackupResult can be created with mode."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            result = BackupResult(mode="snapshot", project_root=str(Path(tempfile.gettempdir()) / "test"))
            assert result.mode == "snapshot"
            assert result.files_copied == 0

    def test_result_fields(self) -> None:
        """BackupResult has expected fields."""
        with patch("aipass.backup.apps.handlers.audit.trail.log_operation"):
            from aipass.backup.apps.handlers.report.result import BackupResult

            result = BackupResult(mode="versioned", files_copied=10, bytes_copied=1024)
            assert result.files_copied == 10
            assert result.bytes_copied == 1024
