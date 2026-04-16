# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_archive.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the archive indexer handler.

Covers:
  - archive/indexer.py (extract_file_info, get_archive_files, load_index,
    save_index, build_index, check_for_new_files, get_index_status)

All tests use mocks/tmp_path -- no live filesystem or infrastructure access.
"""

import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _import_indexer(monkeypatch, tmp_path):
    """Import indexer with mocked dependencies and paths pointed at tmp_path."""
    sys.modules.pop("aipass.memory.apps.handlers.archive.indexer", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.archive")
    if parent is not None and hasattr(parent, "indexer"):
        delattr(parent, "indexer")

    from aipass.memory.apps.handlers.archive import indexer

    # Redirect constants to tmp_path
    code_archive = tmp_path / "code_archive"
    index_path = code_archive / "index.json"
    monkeypatch.setattr(indexer, "CODE_ARCHIVE_PATH", code_archive)
    monkeypatch.setattr(indexer, "INDEX_PATH", index_path)

    return indexer


# ===========================================================================
# Tests: extract_file_info
# ===========================================================================


class TestExtractFileInfo:
    """Test extract_file_info metadata extraction."""

    def test_valid_python_file(self, monkeypatch, tmp_path):
        """Extract info from a well-formed Python file."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        py_file = archive_dir / "example.py"
        py_file.write_text(
            '"""Module docstring."""\n'
            "\n"
            "def hello():\n"
            '    """Say hello."""\n'
            "    pass\n"
            "\n"
            "class Greeter:\n"
            '    """A greeter class."""\n'
            "    pass\n",
            encoding="utf-8",
        )

        info = indexer.extract_file_info(py_file)

        assert info["filename"] == "example.py"
        assert info["docstring"] == "Module docstring."
        assert "hello" in info["functions"]
        assert "Greeter" in info["classes"]
        assert info["size"] == py_file.stat().st_size
        assert info["lines"] == 9
        assert "indexed_at" in info
        assert info["path"] == "example.py"

    def test_syntax_error_file(self, monkeypatch, tmp_path):
        """A file with invalid syntax should return error dict, not raise."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        bad_file = archive_dir / "broken.py"
        bad_file.write_text("def broken(\n    # missing close paren", encoding="utf-8")

        info = indexer.extract_file_info(bad_file)

        assert info["filename"] == "broken.py"
        assert "error" in info
        assert "Syntax error" in info["error"]
        assert info["docstring"] is None
        assert "functions" not in info
        assert "classes" not in info

    def test_unreadable_file(self, monkeypatch, tmp_path):
        """A file that cannot be read should return an error dict."""
        indexer = _import_indexer(monkeypatch, tmp_path)

        missing_file = tmp_path / "code_archive" / "nonexistent.py"

        info = indexer.extract_file_info(missing_file)

        assert info["filename"] == "nonexistent.py"
        assert "error" in info
        assert "indexed_at" in info

    def test_file_no_docstring(self, monkeypatch, tmp_path):
        """A file with no module docstring should return None for docstring."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        py_file = archive_dir / "nodoc.py"
        py_file.write_text("x = 1\n", encoding="utf-8")

        info = indexer.extract_file_info(py_file)

        assert info["docstring"] is None
        assert info["functions"] == []
        assert info["classes"] == []

    def test_long_docstring_truncated(self, monkeypatch, tmp_path):
        """A docstring longer than 200 chars should be truncated with '...'."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        long_doc = "A" * 300
        py_file = archive_dir / "longdoc.py"
        py_file.write_text(f'"""{long_doc}"""\n', encoding="utf-8")

        info = indexer.extract_file_info(py_file)

        assert info["docstring"].endswith("...")
        assert len(info["docstring"]) == 203  # 200 + "..."

    def test_relative_path_in_subdirectory(self, monkeypatch, tmp_path):
        """File in subdirectory should have relative path from CODE_ARCHIVE_PATH."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        sub_dir = archive_dir / "utils"
        sub_dir.mkdir(parents=True)

        py_file = sub_dir / "helper.py"
        py_file.write_text("pass\n", encoding="utf-8")

        info = indexer.extract_file_info(py_file)

        assert info["path"] == str(Path("utils") / "helper.py")


# ===========================================================================
# Tests: get_archive_files
# ===========================================================================


class TestGetArchiveFiles:
    """Test get_archive_files directory scanning."""

    def test_empty_directory(self, monkeypatch, tmp_path):
        """An empty archive directory should return []."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        result = indexer.get_archive_files()

        assert result == []

    def test_returns_py_files_sorted(self, monkeypatch, tmp_path):
        """Should return .py files sorted by path."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        (archive_dir / "beta.py").write_text("pass\n", encoding="utf-8")
        (archive_dir / "alpha.py").write_text("pass\n", encoding="utf-8")

        result = indexer.get_archive_files()

        assert len(result) == 2
        assert result[0].name == "alpha.py"
        assert result[1].name == "beta.py"

    def test_excludes_init_py(self, monkeypatch, tmp_path):
        """__init__.py files should be excluded."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        (archive_dir / "__init__.py").write_text("", encoding="utf-8")
        (archive_dir / "real.py").write_text("pass\n", encoding="utf-8")

        result = indexer.get_archive_files()

        assert len(result) == 1
        assert result[0].name == "real.py"

    def test_directory_does_not_exist(self, monkeypatch, tmp_path):
        """If CODE_ARCHIVE_PATH does not exist, return []."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        # Do NOT create the directory

        result = indexer.get_archive_files()

        assert result == []

    def test_includes_files_in_subdirectories(self, monkeypatch, tmp_path):
        """rglob should find .py files in subdirectories."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        sub_dir = archive_dir / "subpkg"
        sub_dir.mkdir(parents=True)

        (sub_dir / "nested.py").write_text("pass\n", encoding="utf-8")
        (archive_dir / "top.py").write_text("pass\n", encoding="utf-8")

        result = indexer.get_archive_files()

        names = [f.name for f in result]
        assert "nested.py" in names
        assert "top.py" in names


# ===========================================================================
# Tests: load_index
# ===========================================================================


class TestLoadIndex:
    """Test load_index file reading."""

    def test_file_exists(self, monkeypatch, tmp_path):
        """Should load existing index.json contents."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        index_data = {
            "metadata": {"name": "Test Index", "last_updated": "2026-01-01", "total_files": 1},
            "categories": {"utils": ["helper.py"]},
            "files": {"helper.py": {"filename": "helper.py"}},
        }
        (archive_dir / "index.json").write_text(json.dumps(index_data), encoding="utf-8")

        result = indexer.load_index()

        assert result["metadata"]["name"] == "Test Index"
        assert result["files"]["helper.py"]["filename"] == "helper.py"

    def test_file_does_not_exist(self, monkeypatch, tmp_path):
        """Should return empty structure with metadata/categories/files keys."""
        indexer = _import_indexer(monkeypatch, tmp_path)

        result = indexer.load_index()

        assert "metadata" in result
        assert "categories" in result
        assert "files" in result
        assert result["metadata"]["total_files"] == 0
        assert result["categories"] == {}
        assert result["files"] == {}

    def test_corrupted_file_returns_default(self, monkeypatch, tmp_path):
        """A corrupted index.json should return the default structure."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        (archive_dir / "index.json").write_text("not valid json{{{", encoding="utf-8")

        result = indexer.load_index()

        assert "metadata" in result
        assert result["files"] == {}


# ===========================================================================
# Tests: save_index
# ===========================================================================


class TestSaveIndex:
    """Test save_index file writing."""

    def test_success(self, monkeypatch, tmp_path):
        """Should write index.json and update metadata fields."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        index = {
            "metadata": {"name": "Test", "last_updated": None, "total_files": 0},
            "categories": {},
            "files": {"a.py": {"filename": "a.py"}, "b.py": {"filename": "b.py"}},
        }

        result = indexer.save_index(index)

        assert result["success"] is True

        saved = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
        assert saved["metadata"]["total_files"] == 2
        assert saved["metadata"]["last_updated"] is not None

    def test_failure_returns_error(self, monkeypatch, tmp_path):
        """If writing fails, return success=False with error."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        # Point INDEX_PATH to an impossible location
        monkeypatch.setattr(indexer, "INDEX_PATH", Path("/nonexistent/dir/index.json"))

        index = {
            "metadata": {"last_updated": None, "total_files": 0},
            "categories": {},
            "files": {},
        }

        result = indexer.save_index(index)

        assert result["success"] is False
        assert "error" in result


# ===========================================================================
# Tests: build_index
# ===========================================================================


class TestBuildIndex:
    """Test build_index full scan."""

    def test_with_files(self, monkeypatch, tmp_path):
        """Should index all .py files and return stats."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        sub_dir = archive_dir / "utils"
        sub_dir.mkdir(parents=True)

        (archive_dir / "main.py").write_text('"""Main module."""\npass\n', encoding="utf-8")
        (sub_dir / "helper.py").write_text('"""Helper."""\npass\n', encoding="utf-8")

        result = indexer.build_index()

        assert result["success"] is True
        assert result["files_indexed"] == 2
        assert "utils" in result["categories"]

        # Verify index.json was written
        saved = json.loads((archive_dir / "index.json").read_text(encoding="utf-8"))
        assert saved["metadata"]["total_files"] == 2

    def test_with_no_files(self, monkeypatch, tmp_path):
        """Should return success with 0 files when dir is empty or missing."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        # Do not create code_archive directory

        result = indexer.build_index()

        assert result["success"] is True
        assert result["files_indexed"] == 0

    def test_files_at_root_have_no_category(self, monkeypatch, tmp_path):
        """Files directly in code_archive should not create a category."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        (archive_dir / "standalone.py").write_text("pass\n", encoding="utf-8")

        result = indexer.build_index()

        assert result["success"] is True
        assert result["files_indexed"] == 1
        assert result["categories"] == []


# ===========================================================================
# Tests: check_for_new_files
# ===========================================================================


class TestCheckForNewFiles:
    """Test check_for_new_files sync logic."""

    def test_new_files_added(self, monkeypatch, tmp_path):
        """New files on disk should be indexed."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        # Save an empty index first
        empty_index = {
            "metadata": {"last_updated": None, "total_files": 0},
            "categories": {},
            "files": {},
        }
        (archive_dir / "index.json").write_text(json.dumps(empty_index), encoding="utf-8")

        # Now create a file on disk
        (archive_dir / "new_file.py").write_text("pass\n", encoding="utf-8")

        result = indexer.check_for_new_files()

        assert result["success"] is True
        assert result["new_files"] == 1
        assert result["deleted_files"] == 0
        assert result["action"] == "synced"

    def test_files_deleted(self, monkeypatch, tmp_path):
        """Deleted files should be removed from index."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        # Create index with a file that does not exist on disk
        index_with_ghost = {
            "metadata": {"last_updated": None, "total_files": 1},
            "categories": {},
            "files": {
                "ghost.py": {"filename": "ghost.py", "path": "ghost.py"},
            },
        }
        (archive_dir / "index.json").write_text(json.dumps(index_with_ghost), encoding="utf-8")

        result = indexer.check_for_new_files()

        assert result["success"] is True
        assert result["deleted_files"] == 1
        assert result["new_files"] == 0
        assert result["action"] == "synced"

    def test_no_changes(self, monkeypatch, tmp_path):
        """When index matches disk, no sync action needed."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        # Create a file and its index entry
        (archive_dir / "existing.py").write_text("pass\n", encoding="utf-8")
        index = {
            "metadata": {"last_updated": None, "total_files": 1},
            "categories": {},
            "files": {
                "existing.py": {"filename": "existing.py", "path": "existing.py"},
            },
        }
        (archive_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        result = indexer.check_for_new_files()

        assert result["success"] is True
        assert result["new_files"] == 0
        assert result["deleted_files"] == 0
        assert result["action"] == "none"

    def test_simultaneous_add_and_delete(self, monkeypatch, tmp_path):
        """Should handle both new and deleted files in one sync."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        # Index has old_file.py but not new_file.py
        index = {
            "metadata": {"last_updated": None, "total_files": 1},
            "categories": {},
            "files": {
                "old_file.py": {"filename": "old_file.py", "path": "old_file.py"},
            },
        }
        (archive_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        # Disk has new_file.py but not old_file.py
        (archive_dir / "new_file.py").write_text("pass\n", encoding="utf-8")

        result = indexer.check_for_new_files()

        assert result["success"] is True
        assert result["new_files"] == 1
        assert result["deleted_files"] == 1
        assert result["action"] == "synced"


# ===========================================================================
# Tests: get_index_status
# ===========================================================================


class TestGetIndexStatus:
    """Test get_index_status reporting."""

    def test_status_with_indexed_files(self, monkeypatch, tmp_path):
        """Should report correct counts and categories."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        sub_dir = archive_dir / "utils"
        sub_dir.mkdir(parents=True)

        (archive_dir / "a.py").write_text("pass\n", encoding="utf-8")
        (sub_dir / "b.py").write_text("pass\n", encoding="utf-8")

        index = {
            "metadata": {"last_updated": "2026-01-01", "total_files": 2},
            "categories": {"utils": ["b.py"]},
            "files": {
                "a.py": {"filename": "a.py"},
                str(Path("utils") / "b.py"): {"filename": "b.py"},
            },
        }
        (archive_dir / "index.json").write_text(json.dumps(index), encoding="utf-8")

        status = indexer.get_index_status()

        assert status["indexed_files"] == 2
        assert status["current_files"] == 2
        assert status["unindexed"] == 0
        assert "utils" in status["categories"]
        assert status["last_updated"] == "2026-01-01"

    def test_status_with_unindexed_files(self, monkeypatch, tmp_path):
        """Should report unindexed count when files exist but index is empty."""
        indexer = _import_indexer(monkeypatch, tmp_path)
        archive_dir = tmp_path / "code_archive"
        archive_dir.mkdir(parents=True)

        (archive_dir / "orphan.py").write_text("pass\n", encoding="utf-8")

        status = indexer.get_index_status()

        assert status["indexed_files"] == 0
        assert status["current_files"] == 1
        assert status["unindexed"] == 1
        assert status["last_updated"] is None

    def test_status_empty(self, monkeypatch, tmp_path):
        """Empty archive: all counts zero."""
        indexer = _import_indexer(monkeypatch, tmp_path)

        status = indexer.get_index_status()

        assert status["indexed_files"] == 0
        assert status["current_files"] == 0
        assert status["unindexed"] == 0
        assert status["categories"] == []
