# =================== AIPass ====================
# Name: test_versioned_engine.py
# Description: Tests for versioned engine — baseline, diff, skip, never-delete, restore
# Version: 1.0.0
# Created: 2026-06-12
# Modified: 2026-06-12

"""Test versioned engine — baseline, diff, skip, never-delete, restore."""

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

# Inert path input for the path builder — never touched on disk, so it only
# needs to be a valid absolute path on the running OS.
FAKE_PROJECT_ROOT = str(Path(tempfile.gettempdir()) / "project")


class TestVersionedBaseline:
    """First run creates baseline + current."""

    def test_first_run_creates_baseline(self, tmp_path: Path):
        """New file -> baseline + current in file-folder."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            (project / "hello.py").write_text("print('hello')", encoding="utf-8")

            files = [(str(project / "hello.py"), "hello.py")]
            result = copy_versioned(files, str(project))

            assert result["files_copied"] == 1

            target = Path(build_versioned_file_path(str(project), "hello.py"))
            assert target.exists()

            # Check baseline exists in same folder
            baselines = [f for f in target.parent.iterdir() if "-baseline-" in f.name]
            assert len(baselines) == 1
            assert baselines[0].name.endswith(".py")

    def test_first_run_current_matches_source(self, tmp_path: Path):
        """Current copy has same content as source."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            (project / "data.txt").write_text("original content", encoding="utf-8")

            copy_versioned([(str(project / "data.txt"), "data.txt")], str(project))

            target = Path(build_versioned_file_path(str(project), "data.txt"))
            assert target.read_text(encoding="utf-8") == "original content"


class TestVersionedDiff:
    """Change creates diff + overwrites current."""

    def test_change_creates_diff(self, tmp_path: Path):
        """Modified file -> diff file appears in _diffs/ folder."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "code.py"
            src.write_text("v1", encoding="utf-8")

            # First run
            copy_versioned([(str(src), "code.py")], str(project))

            # Modify source (ensure different mtime)
            time.sleep(0.05)
            src.write_text("v2", encoding="utf-8")

            # Second run
            copy_versioned([(str(src), "code.py")], str(project))

            target = Path(build_versioned_file_path(str(project), "code.py"))
            diff_dir = target.parent / f"{target.name}_diffs"
            assert diff_dir.exists()
            diffs = list(diff_dir.glob("*.diff"))
            assert len(diffs) == 1

    def test_change_overwrites_current(self, tmp_path: Path):
        """After change, current has new content."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "file.txt"
            src.write_text("old", encoding="utf-8")

            copy_versioned([(str(src), "file.txt")], str(project))

            time.sleep(0.05)
            src.write_text("new", encoding="utf-8")
            copy_versioned([(str(src), "file.txt")], str(project))

            target = Path(build_versioned_file_path(str(project), "file.txt"))
            assert target.read_text(encoding="utf-8") == "new"

    def test_baseline_untouched_after_change(self, tmp_path: Path):
        """Baseline is never overwritten after first creation."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "config.py"
            src.write_text("original", encoding="utf-8")

            copy_versioned([(str(src), "config.py")], str(project))

            time.sleep(0.05)
            src.write_text("modified", encoding="utf-8")
            copy_versioned([(str(src), "config.py")], str(project))

            target = Path(build_versioned_file_path(str(project), "config.py"))
            baselines = [f for f in target.parent.iterdir() if "-baseline-" in f.name]
            assert len(baselines) == 1
            assert baselines[0].read_text(encoding="utf-8") == "original"


class TestVersionedSkip:
    """Unchanged files are skipped."""

    def test_unchanged_skipped(self, tmp_path: Path):
        """File with same mtime -> files_unchanged incremented."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned

            project = tmp_path / "project"
            project.mkdir()
            src = project / "stable.txt"
            src.write_text("no change", encoding="utf-8")

            copy_versioned([(str(src), "stable.txt")], str(project))

            # Run again without modifying
            result = copy_versioned([(str(src), "stable.txt")], str(project))
            assert result["files_unchanged"] == 1
            assert result["files_copied"] == 0


class TestVersionedNeverDelete:
    """Versioned NEVER deletes — append-only."""

    def test_deleted_source_preserved_in_store(self, tmp_path: Path):
        """Source file deleted -> versioned store still has it."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "temp.py"
            src.write_text("temp data", encoding="utf-8")

            copy_versioned([(str(src), "temp.py")], str(project))

            # Delete source
            src.unlink()

            # Run versioned again WITHOUT the deleted file
            copy_versioned([], str(project))

            # Store still has the file
            target = Path(build_versioned_file_path(str(project), "temp.py"))
            assert target.exists()
            assert target.read_text(encoding="utf-8") == "temp data"


class TestDiffGenerator:
    """Diff generator — binary detection, unified diff."""

    def test_text_diff(self, tmp_path: Path):
        """Text files produce unified diff."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.diff.generator import generate_diff_content

            old = tmp_path / "old.py"
            new = tmp_path / "new.py"
            old.write_text("line1\nline2\n", encoding="utf-8")
            new.write_text("line1\nline3\n", encoding="utf-8")

            diff = generate_diff_content(old, new)
            assert "---" in diff or "+++" in diff or "line" in diff

    def test_binary_marker(self, tmp_path: Path):
        """Binary files get marker instead of diff."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.diff.generator import is_binary_file

            binary = tmp_path / "image.bin"
            binary.write_bytes(b"\x89PNG\r\n\x1a\n\x00" + b"\x00" * 100)
            assert is_binary_file(binary) is True

    def test_should_create_diff_patterns(self):
        """Include patterns override ignore patterns."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.diff.generator import should_create_diff

            assert should_create_diff(Path("app.py")) is True
            assert should_create_diff(Path("image.png")) is False
            assert should_create_diff(Path("data.json")) is True


class TestRestore:
    """Restore handler — reconstruct from store."""

    def test_restore_current(self, tmp_path: Path):
        """Restore current version from store."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.diff.restore import restore_file
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "app.py"
            src.write_text("print('app')", encoding="utf-8")

            copy_versioned([(str(src), "app.py")], str(project))

            target = Path(build_versioned_file_path(str(project), "app.py"))
            output = tmp_path / "restored" / "app.py"
            assert restore_file(target.parent, output) is True
            assert output.read_text(encoding="utf-8") == "print('app')"

    def test_list_versions(self, tmp_path: Path):
        """list_versions finds baseline + current + diffs."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned
            from aipass.backup.apps.handlers.diff.restore import list_versions
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            project = tmp_path / "project"
            project.mkdir()
            src = project / "mod.py"
            src.write_text("v1", encoding="utf-8")

            copy_versioned([(str(src), "mod.py")], str(project))

            time.sleep(0.05)
            src.write_text("v2", encoding="utf-8")
            copy_versioned([(str(src), "mod.py")], str(project))

            target = Path(build_versioned_file_path(str(project), "mod.py"))
            versions = list_versions(target.parent)
            types = {v["type"] for v in versions}
            assert "baseline" in types
            assert "current" in types
            assert "diff" in types


class TestVersionedFilePath:
    """Path builder — file-folder packaging."""

    def test_root_level_file(self):
        """Root-level file -> root/<name>/<name>."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "README.md"))
            assert "root" in str(result)
            assert result.name == "README.md"

    def test_nested_file(self):
        """Nested file -> <parent>/<name>/<name>."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, "src/main.py"))
            assert "src" in str(result)
            assert result.name == "main.py"
            assert result.parent.name == "main.py"

    def test_long_filename_hashed(self):
        """Filename >50 chars -> shortened with hash."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.path.builder import build_versioned_file_path

            long_name = "a" * 60 + ".py"
            result = Path(build_versioned_file_path(FAKE_PROJECT_ROOT, long_name))
            assert result.name == long_name
            assert len(result.parent.name) < 50


class TestRestoreModule:
    """Restore module — version discovery and file restore via module layer."""

    def test_find_file_folder(self, tmp_path: Path):
        """_find_file_folder locates a file-folder in the versioned store."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned

            project = tmp_path / "project"
            project.mkdir()
            src = project / "config.py"
            src.write_text("cfg = True", encoding="utf-8")
            copy_versioned([(str(src), "config.py")], str(project))

        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.modules.restore import _find_file_folder

            folder = _find_file_folder(str(project), "config.py")
            assert folder is not None
            assert folder.name == "config.py"
            assert (folder / "config.py").is_file()

    def test_find_file_folder_missing(self, tmp_path: Path):
        """_find_file_folder returns None for missing file."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.modules.restore import _find_file_folder

            result = _find_file_folder(str(tmp_path), "nonexistent.py")
            assert result is None

    def test_run_restore_file_roundtrip(self, tmp_path: Path):
        """run_restore_file restores a file to an output path."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            from aipass.backup.apps.handlers.copy.versioned import copy_versioned

            project = tmp_path / "project"
            project.mkdir()
            src = project / "data.txt"
            src.write_text("important data", encoding="utf-8")
            copy_versioned([(str(src), "data.txt")], str(project))

        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            with patch("aipass.backup.apps.modules.restore.console"):
                from aipass.backup.apps.modules.restore import run_restore_file

                out = str(tmp_path / "restored" / "data.txt")
                result = run_restore_file(str(project), "data.txt", out)
                assert result is True
                assert Path(out).read_text(encoding="utf-8") == "important data"

    def test_handle_command_help(self):
        """handle_command responds to --help."""
        with patch("aipass.backup.apps.handlers.json.json_handler.log_operation"):
            with patch("aipass.backup.apps.modules.restore.console"):
                from aipass.backup.apps.modules.restore import handle_command

                assert handle_command("restore", ["--help"]) is True


# =============================================
