# =================== META ====================
# Name: test_handlers_filesystem.py
# Description: Tests for filesystem handlers -- scan, ignore, path, project
# Version: 1.2.1
# Created: 2026-06-12
# Modified: 2026-09-25
# =============================================

"""Tests for aipass/backup/apps/handlers/scan/walk.py, filter.py and related packages."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — scan/, ignore/, project/, path/, report/, audit/ parse without errors
# seedgo: no-test-needed(documentation) — handler functions carry docstrings
# seedgo: no-test-needed(constant) — project/config.py DEFAULTS' max_file_size_mb, auto_ignore_git and drive_sync values
# seedgo: no-test-needed(stdlib) — os.walk, os.path.islink and os.path.getsize in scan/walk.py and scan/filter.py

from pathlib import Path
from unittest.mock import patch

from aipass.backup.apps.handlers.audit import trail
from aipass.backup.apps.handlers.path.builder import backup_root, build_snapshot_path
from aipass.backup.apps.handlers.project.config import load_project_config
from aipass.backup.apps.handlers.project.setup import create_backup_dir
from aipass.backup.apps.handlers.report.formatter import format_result
from aipass.backup.apps.handlers.report.result import BackupResult, new_result
from aipass.backup.apps.handlers.scan.filter import filter_paths
from aipass.backup.apps.handlers.scan.walk import walk_project
from aipass.backup.apps.handlers.ignore.patterns import load_spec


class TestScanWalk:
    """Test directory walking -- creates_files, .exists() tokens."""

    def test_walk_empty_dir(self, tmp_path: Path) -> None:
        """Walk an empty directory yields NOTHING -- the value, not the type.

        isinstance(result, list) was true of a walker that invented entries and
        true of one that returned the caller's own tree; only the emptiness is
        the claim this test's name makes.

        Walks its OWN subdirectory rather than tmp_path, and the seam is no
        longer inside tmp_path either -- two independent guards, kept both.

        The history, because it is the reason this test reads the way it does.
        conftest used to point the json seam at tmp_path/_aipass_json_seam,
        INSIDE tmp_path, and the walker logs its own start before os.walk runs,
        so a walk of BARE tmp_path found the seam's four files
        (backup/logs/operations.jsonl and three prax_json documents). The trail
        patch that used to wrap this call was the only thing keeping the list
        empty: the emptiness was the patch's, not the walker's. Giving the walk
        a root of its own put the audit write beside proj instead of within it,
        so the patch went and the record it used to swallow is asserted below.
        As of 2026-09-23 conftest's seam sits BESIDE tmp_path as well, so a bare
        tmp_path now walks to nothing on its own account -- measured, four
        entries before the move and zero after. This test does not rely on that:
        proj is its root either way, and the emptiness it asserts is the
        walker's.
        """
        proj = tmp_path / "proj"
        proj.mkdir()

        result = list(walk_project(str(proj)))

        assert result == []
        audit = trail.log_path().read_text(encoding="utf-8")
        assert f'"operation": "walk_project", "root": "{proj}"' in audit

    def test_walk_with_files(self, tmp_path: Path) -> None:
        """Walk a directory with files returns file tuples."""
        proj = tmp_path / "proj"
        proj.mkdir()
        (proj / "file1.txt").write_text("content1", encoding="utf-8")
        (proj / "file2.py").write_text("content2", encoding="utf-8")

        result = list(walk_project(str(proj)))

        assert len(result) >= 2

    def test_walk_nonexistent_dir(self, tmp_path: Path) -> None:
        """A missing directory walks to empty, and does not raise.

        The old spelling was 'result == [] or isinstance(result, list)': the
        second clause is true whenever the first one is, so the assertion could
        not fail. Measured 2026-09-08 -- the real answer is the empty list.
        """
        bad_path = tmp_path / "nonexistent"

        result = list(walk_project(str(bad_path)))

        assert result == []


class TestScanFilter:
    """Test filtering -- patterns, whitelist."""

    def test_filter_empty_list(self) -> None:
        """Filter empty file list returns empty."""
        with patch(
            "aipass.backup.apps.handlers.ignore.whitelist.config.load_project_config",
            return_value={"whitelist": []},
        ):
            import pathspec

            empty_spec = pathspec.PathSpec.from_lines("gitignore", [])
            result = filter_paths([], empty_spec, [], 100)
            assert result == []

    def test_filter_preserves_files(self, tmp_path: Path) -> None:
        """Filter with no ignore patterns preserves all files."""
        f = tmp_path / "keep.txt"
        f.write_text("data", encoding="utf-8")
        files = [(str(f), "keep.txt")]
        with patch(
            "aipass.backup.apps.handlers.ignore.whitelist.config.load_project_config",
            return_value={"whitelist": []},
        ):
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
        create_backup_dir(str(tmp_path))

        backup_dir = tmp_path / ".backup"
        assert backup_dir.exists()

    def test_create_backup_dir_idempotent(self, tmp_path: Path) -> None:
        """Second call doesn't fail -- no_overwrite, already_exists."""
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
        result = backup_root(str(tmp_path))

        assert isinstance(result, Path)
        assert result.name == ".backup"

    def test_build_snapshot_path(self, tmp_path: Path) -> None:
        """build_snapshot_path returns snapshots/ under THIS project's .backup.

        '"snapshots" in str(result)' is a substring test on an unpinned parent:
        it is true of Path("snapshots"), true of tmp_path / "snapshots" with
        .backup gone, and true of any snapshots/ directory anywhere on the
        disk. For a backup tool the parent is the whole point -- a destination
        that drifts out of the project writes a user's files somewhere they
        will never look for them. The full path is the claim the name makes.
        """
        result = build_snapshot_path(str(tmp_path))

        assert isinstance(result, Path)
        assert result == tmp_path / ".backup" / "snapshots"
        assert "snapshots" in str(result)


class TestBackupResult:
    """Test BackupResult dataclass -- module coverage for 'report' package."""

    def test_result_creation(self, tmp_path: Path) -> None:
        """new_result builds a run's result under the mode and root it was handed.

        The old spelling constructed a BackupResult with mode="snapshot" and
        read mode straight back: @dataclass decided that, not backup, and it
        held with every line of result.py deleted. new_result is the product's
        own constructor for a run's outcome, so what it decides -- which
        argument lands in which field -- is the claim now. A new_result that
        crossed mode with project_root passed the old test.
        """
        result = new_result("snapshot", str(tmp_path))

        assert result.mode == "snapshot"
        assert result.project_root == str(tmp_path)
        assert result.files_copied == 0

    def test_result_fields(self, tmp_path: Path) -> None:
        """The counts a result carries are the counts the report renders.

        files_copied=10 and bytes_copied=1024 read back off the constructor
        asserted @dataclass a second time. Routed through format_result, those
        two numbers are what the product computes WITH: the file count it
        prints, and _human_bytes turning 1024 bytes into "1.0 KB" rather than
        the raw number. The whole summary is pinned, so a field rendered from
        the wrong attribute has nowhere to hide.
        """
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
