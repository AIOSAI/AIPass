"""Tests for path_builder — backup destination path construction."""

from pathlib import Path
from unittest.mock import patch, MagicMock


def _import_build_backup_path():
    """Import build_backup_path after autouse fixture has mocked prax."""
    from aipass.backup.apps.handlers.operations.path_builder import build_backup_path
    return build_backup_path


class TestSnapshotMode:
    """Snapshot mode preserves original relative structure."""

    def test_snapshot_mode_preserves_relative_path(self, tmp_path):
        """Snapshot mode mirrors source directory layout under backup root."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            source_dir = tmp_path / "source"
            source_file = source_dir / "subdir" / "file.py"
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "snapshot")

            assert result == backup_root / "subdir" / "file.py"


class TestVersionedMode:
    """Versioned mode creates file-named folders for version tracking."""

    def test_versioned_mode_creates_file_folder(self, tmp_path):
        """Versioned mode nests file inside a folder named after itself."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            source_dir = tmp_path / "source"
            source_file = source_dir / "subdir" / "backup.py"
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            assert result == backup_root / "subdir" / "backup.py" / "backup.py"

    def test_root_level_file_uses_root_subdir(self, tmp_path):
        """Files at source root go into a 'root/' subdirectory in versioned mode."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            source_dir = tmp_path / "source"
            source_file = source_dir / "AGENTS.md"
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            assert result == backup_root / "root" / "AGENTS.md" / "AGENTS.md"

    def test_nested_path_structure(self, tmp_path):
        """Deeply nested files maintain correct versioned structure."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            source_dir = tmp_path / "source"
            source_file = source_dir / "a" / "b" / "c" / "deep.py"
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            expected = backup_root / "a" / "b" / "c" / "deep.py" / "deep.py"
            assert result == expected


class TestLongFilenames:
    """Long filenames get hashed to avoid filesystem limits."""

    def _make_long_name(self, ext: str = ".py") -> str:
        """Create a filename longer than 50 characters."""
        return "a" * 51 + ext

    def test_long_filename_gets_hashed(self, tmp_path):
        """Filenames >50 chars get shortened to 30 chars + underscore + 8-char md5 hash."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            long_name = self._make_long_name()
            source_dir = tmp_path / "source"
            source_file = source_dir / "subdir" / long_name
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            # The folder name should be shortened (30 chars + _ + 8 hex chars = 39 chars)
            folder_name = result.parent.name
            assert len(folder_name) == 39
            assert folder_name[:30] == long_name[:30]
            assert folder_name[30] == "_"
            # The actual file inside keeps its original long name
            assert result.name == long_name

    def test_hashed_filename_preserves_extension(self, tmp_path):
        """The original file (with extension) is preserved inside the hashed folder."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            long_name = "a" * 51 + ".json"
            source_dir = tmp_path / "source"
            source_file = source_dir / "sub" / long_name
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            assert result.name == long_name
            assert result.suffix == ".json"

    def test_hashed_filename_is_deterministic(self, tmp_path):
        """Same input always produces the same hashed folder name."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            long_name = self._make_long_name()
            source_dir = tmp_path / "source"
            source_file = source_dir / "subdir" / long_name
            backup_root = tmp_path / "backup"

            result_a = build_backup_path(source_file, source_dir, backup_root, "versioned")
            result_b = build_backup_path(source_file, source_dir, backup_root, "versioned")

            assert result_a == result_b

    def test_exactly_50_chars_not_hashed(self, tmp_path):
        """Filename exactly 50 chars is NOT hashed (boundary: >50 triggers hash)."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            name_50 = "a" * 46 + ".py"  # 46 + 3 = 49... need exactly 50
            name_50 = "a" * 47 + ".py"  # 47 + 3 = 50 chars
            assert len(name_50) == 50

            source_dir = tmp_path / "source"
            source_file = source_dir / "subdir" / name_50
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            # Folder name should be the original filename (no hash applied)
            assert result.parent.name == name_50
            assert result.name == name_50

    def test_long_filename_at_root_level_gets_hashed(self, tmp_path):
        """Long root-level filename uses 'root/' prefix AND gets hashed folder name."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            long_name = "b" * 51 + ".md"
            source_dir = tmp_path / "source"
            source_file = source_dir / long_name  # root level
            backup_root = tmp_path / "backup"

            result = build_backup_path(source_file, source_dir, backup_root, "versioned")

            # Should be under root/ with hashed folder name
            assert "root" in result.parts
            folder_name = result.parent.name
            assert len(folder_name) == 39  # 30 + _ + 8 hex
            assert folder_name[:30] == long_name[:30]
            assert result.name == long_name


class TestReturnType:
    """build_backup_path always returns a Path object."""

    def test_returns_path_object(self, tmp_path):
        """Result is always a pathlib.Path regardless of mode."""
        build_backup_path = _import_build_backup_path()
        with patch("aipass.backup.apps.handlers.operations.path_builder.json_handler", MagicMock()):
            source_dir = tmp_path / "source"
            source_file = source_dir / "readme.md"
            backup_root = tmp_path / "backup"

            for mode in ("snapshot", "versioned"):
                result = build_backup_path(source_file, source_dir, backup_root, mode)
                assert isinstance(result, Path)
