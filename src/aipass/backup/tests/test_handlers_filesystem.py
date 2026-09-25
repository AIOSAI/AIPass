# =================== META ====================
# Name: test_handlers_filesystem.py
# Description: Backup handlers: scan/{walk,filter}.py, ignore/patterns.py, audit/trail.py, project/, path/, report/
# Version: 1.2.4
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Backup handlers: scan/{walk,filter}.py, ignore/patterns.py, audit/trail.py, project/, path/, report/."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — scan/, ignore/, project/, path/, report/, audit/ parse without errors
# seedgo: no-test-needed(documentation) — handler functions carry docstrings
# seedgo: no-test-needed(constant) — project/config.py DEFAULTS' max_file_size_mb, auto_ignore_git and drive_sync values
# seedgo: no-test-needed(stdlib) — os.walk, os.path.islink and os.path.getsize in scan/walk.py and scan/filter.py

import json
from pathlib import Path

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import backup_root, build_snapshot_path
from aipass.backup.apps.handlers.project.config import load_project_config, save_project_config
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.report.formatter import format_result
from aipass.backup.apps.handlers.report.result import BackupResult, new_result
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.handlers.ignore.patterns import is_ignored, load_spec


class TestScanWalk:
    """walk_project lists a project's files as absolute and relative paths."""

    def test_empty_project_walks_to_nothing_and_logs_the_walk(self, tmp_path: Path) -> None:
        """An empty project walks to nothing, and the walk is recorded in the audit trail."""
        proj = tmp_path / "proj"
        proj.mkdir()

        result = list(walk_project(str(proj)))

        assert result == []
        records = [json.loads(line) for line in trail.log_path().read_text(encoding="utf-8").splitlines()]
        assert [r["root"] for r in records if r["operation"] == "walk_project"] == [str(proj)]

    def test_walk_yields_each_file_as_absolute_and_relative_path(self, tmp_path: Path) -> None:
        """Walk a directory with files yields one (absolute, relative) tuple per file."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "file1.txt").write_text("content1", encoding="utf-8")
        (proj / "file2.py").write_text("content2", encoding="utf-8")

        result = list(walk_project(str(proj)))

        assert sorted(result) == [
            (str(proj / "file1.txt"), "file1.txt"),
            (str(proj / "file2.py"), "file2.py"),
        ]

    def test_missing_directory_walks_to_empty_without_raising(self, tmp_path: Path) -> None:
        """A missing directory walks to empty, and does not raise."""
        bad_path = tmp_path / "nonexistent"

        result = list(walk_project(str(bad_path)))

        assert result == []


class TestScanFilter:
    """Test filtering -- patterns, whitelist."""

    def test_filter_of_no_paths_is_empty(self) -> None:
        """No paths in, none out -- a filter that drops real files is the next test's to catch."""
        import pathspec

        empty_spec = pathspec.PathSpec.from_lines("gitignore", [])
        result = filter_paths([], empty_spec, [], 100)
        assert result == []

    def test_filter_without_ignore_rules_keeps_every_file(self, tmp_path: Path) -> None:
        """With no ignore rules a real file comes through the filter, not dropped and not rewritten."""
        f = tmp_path / "keep.txt"
        f.write_text("data", encoding="utf-8")
        files = [(str(f), "keep.txt")]
        spec = load_spec(str(tmp_path))
        result = filter_paths(files, spec, [], 100)

        assert len(result) == 1
        assert result[0] == (str(f), "keep.txt")


class TestIgnorePatterns:
    """Test ignore pattern loading."""

    def test_spec_without_backupignore_matches_no_ordinary_file(self, tmp_path: Path) -> None:
        """With no .backupignore only the *.tmp floor is ignored -- no ordinary file is."""
        spec = load_spec(str(tmp_path))

        assert is_ignored("x.tmp", spec) is True
        assert is_ignored("a.pyc", spec) is False
        assert is_ignored("src/main.py", spec) is False

    def test_spec_enforces_the_backupignore_patterns(self, tmp_path: Path) -> None:
        """.backupignore's patterns ignore their matches, backslash-separated too, and spare the rest."""
        ignore = tmp_path / ".backupignore"
        ignore.write_text("*.pyc\n__pycache__/\n", encoding="utf-8")

        spec = load_spec(str(tmp_path))

        assert is_ignored("a.pyc", spec) is True
        assert is_ignored("__pycache__/mod.py", spec) is True
        assert is_ignored("__pycache__\\mod.py", spec) is True
        assert is_ignored("src/main.py", spec) is False


class TestProjectSetup:
    """create_backup_dir scaffolds a project's .backup/ and leaves an existing one alone."""

    def test_setup_creates_the_backup_dir(self, tmp_path: Path) -> None:
        """Setup returns the .backup it made -- a None beside a made directory is a failed setup."""
        created = create_backup_dir(str(tmp_path))

        backup_dir = tmp_path / ".backup"
        assert created == backup_dir
        assert backup_dir.exists()

    def test_second_setup_keeps_the_existing_config(self, tmp_path: Path) -> None:
        """A second setup returns the same .backup and keeps an edited config."""
        create_backup_dir(str(tmp_path))
        edited = {**load_project_config(str(tmp_path)), "max_versions": 3}
        assert save_project_config(str(tmp_path), edited) is True

        second = create_backup_dir(str(tmp_path))

        assert second == tmp_path / ".backup"
        assert load_project_config(str(tmp_path))["max_versions"] == 3


class TestProjectConfig:
    """load_project_config reads the DEFAULTS when unregistered, and setup's config after."""

    def test_unregistered_project_gets_the_default_config(self, tmp_path: Path) -> None:
        """An unregistered project gets the DEFAULTS, ceilings included."""
        result = load_project_config(str(tmp_path))

        assert isinstance(result, dict)
        assert result["backup_mode"] == "snapshot"
        assert result["max_versions"] == 10
        assert result["max_backup_files"] == 25000
        assert result["max_backup_size_gb"] == 10
        assert result["whitelist"] == []

    def test_config_written_by_setup_identifies_the_project(self, tmp_path: Path) -> None:
        """create_backup_dir writes a config that names the project it belongs to."""
        create_backup_dir(str(tmp_path))

        result = load_project_config(str(tmp_path))

        assert isinstance(result, dict)
        assert result["project_name"] == tmp_path.name
        assert Path(result["project_path"]) == tmp_path
        assert result["max_backup_files"] == 25000


class TestPathBuilder:
    """Test path builder handler -- module coverage for 'path' package."""

    def test_backup_root_is_the_projects_own_backup_dir(self, tmp_path: Path) -> None:
        """backup_root is this project's own .backup, not a .backup under any other root."""
        result = backup_root(str(tmp_path))

        assert isinstance(result, Path)
        assert result == tmp_path / ".backup"

    def test_snapshot_path_is_under_the_projects_backup_dir(self, tmp_path: Path) -> None:
        """build_snapshot_path returns snapshots/ under THIS project's .backup."""
        result = build_snapshot_path(str(tmp_path))

        assert isinstance(result, Path)
        assert result == tmp_path / ".backup" / "snapshots"


class TestBackupResult:
    """Test BackupResult dataclass -- module coverage for 'report' package."""

    def test_new_result_carries_the_mode_and_root_it_was_handed(self, tmp_path: Path) -> None:
        """new_result builds a run's result under the mode and root it was handed."""
        result = new_result("snapshot", str(tmp_path))

        assert result.mode == "snapshot"
        assert result.project_root == str(tmp_path)
        assert result.files_copied == 0

    def test_format_result_renders_the_counts_the_result_carries(self, tmp_path: Path) -> None:
        """The counts a result carries are the counts the report renders."""
        result = BackupResult(
            mode="versioned",
            project_root=str(tmp_path),
            files_copied=10,
            bytes_copied=1024,
        )

        summary = format_result(result)

        assert summary == "\n".join(
            [
                "Backup complete (versioned)",
                f"  Project:  {tmp_path}",
                "  Files:    10",
                "  Size:     1.0 KB",
                "  Duration: 0.0s",
            ]
        )
