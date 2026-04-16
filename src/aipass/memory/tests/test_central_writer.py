# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_central_writer.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the central writer handler.

Covers:
  - central_writer.py (count_chroma_vectors, count_archive_files,
    get_last_rollover_timestamp, collect_stats, read_central_file,
    write_central_file, update_central, get_current_stats)

All tests use mocks/tmp_path -- no live filesystem or infrastructure access.
"""

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _import_central_writer(monkeypatch, tmp_path):
    """Import central_writer with mocked dependencies and paths at tmp_path."""
    sys.modules.pop("aipass.memory.apps.handlers.central_writer", None)
    parent = sys.modules.get("aipass.memory.apps.handlers")
    if parent is not None and hasattr(parent, "central_writer"):
        delattr(parent, "central_writer")

    from aipass.memory.apps.handlers import central_writer

    # Redirect all path constants to tmp_path
    monkeypatch.setattr(central_writer, "_MEMORY_ROOT", tmp_path)
    monkeypatch.setattr(central_writer, "CENTRAL_FILE", tmp_path / "central" / "MEMORY.central.json")
    monkeypatch.setattr(central_writer, "CHROMA_DB_PATH", tmp_path / ".chroma")
    monkeypatch.setattr(central_writer, "ARCHIVE_DIR", tmp_path / ".archive")

    return central_writer


# ---------------------------------------------------------------------------
# Helper: create a tiny SQLite DB with embeddings table
# ---------------------------------------------------------------------------


def _create_chroma_db(db_path: Path, num_rows: int = 5) -> None:
    """Create a minimal SQLite DB mimicking ChromaDB structure."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE embeddings (id INTEGER PRIMARY KEY, data TEXT)")
    for i in range(num_rows):
        cursor.execute("INSERT INTO embeddings (data) VALUES (?)", (f"vec_{i}",))
    conn.commit()
    conn.close()


# ===========================================================================
# Tests: count_chroma_vectors
# ===========================================================================


class TestCountChromaVectors:
    """Test count_chroma_vectors SQLite reading."""

    def test_chroma_dir_does_not_exist(self, monkeypatch, tmp_path):
        """Should return 0 when .chroma directory is missing."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        assert cw.count_chroma_vectors() == 0

    def test_chroma_dir_exists_but_no_sqlite(self, monkeypatch, tmp_path):
        """Should return 0 when .chroma exists but chroma.sqlite3 is missing."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        (tmp_path / ".chroma").mkdir(parents=True)

        assert cw.count_chroma_vectors() == 0

    def test_with_real_sqlite_db(self, monkeypatch, tmp_path):
        """Should count rows from a real sqlite3 DB."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        db_file = tmp_path / ".chroma" / "chroma.sqlite3"
        _create_chroma_db(db_file, num_rows=7)

        result = cw.count_chroma_vectors()

        assert result == 7

    def test_empty_embeddings_table(self, monkeypatch, tmp_path):
        """Should return 0 when embeddings table exists but is empty."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        db_file = tmp_path / ".chroma" / "chroma.sqlite3"
        _create_chroma_db(db_file, num_rows=0)

        assert cw.count_chroma_vectors() == 0

    def test_db_error_returns_zero(self, monkeypatch, tmp_path):
        """Should return 0 if sqlite3 query fails."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        chroma_dir = tmp_path / ".chroma"
        chroma_dir.mkdir(parents=True)
        # Write garbage to the sqlite3 file
        (chroma_dir / "chroma.sqlite3").write_text("not a database", encoding="utf-8")

        assert cw.count_chroma_vectors() == 0


# ===========================================================================
# Tests: count_archive_files
# ===========================================================================


class TestCountArchiveFiles:
    """Test count_archive_files .md counting."""

    def test_dir_does_not_exist(self, monkeypatch, tmp_path):
        """Should return 0 when .archive directory is missing."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        assert cw.count_archive_files() == 0

    def test_with_md_files(self, monkeypatch, tmp_path):
        """Should count only .md files."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)

        (archive / "session1.md").write_text("# Session 1", encoding="utf-8")
        (archive / "session2.md").write_text("# Session 2", encoding="utf-8")
        (archive / "notes.txt").write_text("not counted", encoding="utf-8")

        assert cw.count_archive_files() == 2

    def test_empty_archive_dir(self, monkeypatch, tmp_path):
        """Should return 0 when .archive exists but has no .md files."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)

        assert cw.count_archive_files() == 0

    def test_access_failure_raises(self, monkeypatch, tmp_path):
        """Should raise Exception when directory access fails."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)

        # Force glob to fail
        monkeypatch.setattr(cw, "ARCHIVE_DIR", archive)
        original_glob = Path.glob

        def broken_glob(self, pattern):
            raise PermissionError("access denied")

        monkeypatch.setattr(Path, "glob", broken_glob)

        try:
            cw.count_archive_files()
            assert False, "Expected Exception"
        except Exception as exc:
            assert "Failed to count archive files" in str(exc)
        finally:
            monkeypatch.setattr(Path, "glob", original_glob)


# ===========================================================================
# Tests: get_last_rollover_timestamp
# ===========================================================================


class TestGetLastRolloverTimestamp:
    """Test get_last_rollover_timestamp file stat reading."""

    def test_no_archive_dir(self, monkeypatch, tmp_path):
        """Should return empty string when .archive does not exist."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        assert cw.get_last_rollover_timestamp() == ""

    def test_no_md_files(self, monkeypatch, tmp_path):
        """Should return empty string when .archive has no .md files."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)

        assert cw.get_last_rollover_timestamp() == ""

    def test_with_archive_files(self, monkeypatch, tmp_path):
        """Should return ISO timestamp of most recently modified .md file."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)

        (archive / "old.md").write_text("old", encoding="utf-8")
        (archive / "new.md").write_text("new", encoding="utf-8")

        result = cw.get_last_rollover_timestamp()

        assert result != ""
        # Should be a valid ISO timestamp string
        assert "T" in result


# ===========================================================================
# Tests: collect_stats
# ===========================================================================


class TestCollectStats:
    """Test collect_stats aggregation."""

    def test_returns_all_fields(self, monkeypatch, tmp_path):
        """Should return dict with total_vectors, total_archives, last_rollover."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        # Set up minimal data
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)
        (archive / "session.md").write_text("# test", encoding="utf-8")

        stats = cw.collect_stats()

        assert "total_vectors" in stats
        assert "total_archives" in stats
        assert "last_rollover" in stats
        assert stats["total_archives"] == 1
        assert stats["total_vectors"] == 0  # no chroma DB

    def test_all_zeros_when_empty(self, monkeypatch, tmp_path):
        """Should return zeros/empty when no data exists."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        stats = cw.collect_stats()

        assert stats["total_vectors"] == 0
        assert stats["total_archives"] == 0
        assert stats["last_rollover"] == ""


# ===========================================================================
# Tests: read_central_file
# ===========================================================================


class TestReadCentralFile:
    """Test read_central_file JSON reading."""

    def test_file_does_not_exist(self, monkeypatch, tmp_path):
        """Should return default structure when file is missing."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        result = cw.read_central_file()

        assert result["service"] == "memory"
        assert result["last_updated"] == ""
        assert result["stats"]["total_vectors"] == 0
        assert result["stats"]["total_archives"] == 0

    def test_file_exists(self, monkeypatch, tmp_path):
        """Should read and return existing JSON contents."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        data = {
            "service": "memory",
            "last_updated": "2026-03-01T12:00:00",
            "stats": {"total_vectors": 42, "total_archives": 5, "last_rollover": "2026-02-28"},
            "extra_field": "preserved",
        }
        (central_dir / "MEMORY.central.json").write_text(json.dumps(data), encoding="utf-8")

        result = cw.read_central_file()

        assert result["stats"]["total_vectors"] == 42
        assert result["extra_field"] == "preserved"

    def test_corrupted_file_raises(self, monkeypatch, tmp_path):
        """Should raise Exception when file contains invalid JSON."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        (central_dir / "MEMORY.central.json").write_text("{{bad json", encoding="utf-8")

        try:
            cw.read_central_file()
            assert False, "Expected Exception"
        except Exception as exc:
            assert "Failed to read central file" in str(exc)


# ===========================================================================
# Tests: write_central_file
# ===========================================================================


class TestWriteCentralFile:
    """Test write_central_file JSON writing."""

    def test_creates_dirs_and_writes(self, monkeypatch, tmp_path):
        """Should create parent directories and write JSON."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        data = {"service": "memory", "stats": {"total_vectors": 10}}

        cw.write_central_file(data)

        central_file = tmp_path / "central" / "MEMORY.central.json"
        assert central_file.exists()

        written = json.loads(central_file.read_text(encoding="utf-8"))
        assert written["stats"]["total_vectors"] == 10

    def test_overwrites_existing_file(self, monkeypatch, tmp_path):
        """Should overwrite existing file content."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        central_file = central_dir / "MEMORY.central.json"
        central_file.write_text('{"old": true}', encoding="utf-8")

        cw.write_central_file({"new": True})

        written = json.loads(central_file.read_text(encoding="utf-8"))
        assert written["new"] is True
        assert "old" not in written

    def test_write_failure_raises(self, monkeypatch, tmp_path):
        """Should raise Exception on write failure."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        # Point to impossible path
        monkeypatch.setattr(cw, "CENTRAL_FILE", Path("/proc/0/impossible.json"))

        try:
            cw.write_central_file({"test": True})
            assert False, "Expected Exception"
        except Exception as exc:
            assert "Failed to write central file" in str(exc)


# ===========================================================================
# Tests: update_central
# ===========================================================================


class TestUpdateCentral:
    """Test update_central end-to-end flow."""

    def test_success_verbose(self, monkeypatch, tmp_path):
        """Verbose mode should include stats in result."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        result = cw.update_central(verbose=True)

        assert result["success"] is True
        assert "updated" in result
        assert "stats" in result
        assert "total_vectors" in result["stats"]

        # Verify file was written
        central_file = tmp_path / "central" / "MEMORY.central.json"
        assert central_file.exists()

    def test_success_non_verbose(self, monkeypatch, tmp_path):
        """Non-verbose mode should NOT include stats in result."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        result = cw.update_central(verbose=False)

        assert result["success"] is True
        assert "updated" in result
        assert "stats" not in result

    def test_removes_placeholder_note(self, monkeypatch, tmp_path):
        """Should remove _note field from central data if present."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        old_data = {
            "service": "memory",
            "last_updated": "",
            "_note": "placeholder - not yet populated",
            "stats": {"total_vectors": 0, "total_archives": 0, "last_rollover": ""},
        }
        (central_dir / "MEMORY.central.json").write_text(json.dumps(old_data), encoding="utf-8")

        result = cw.update_central()

        assert result["success"] is True

        written = json.loads((central_dir / "MEMORY.central.json").read_text(encoding="utf-8"))
        assert "_note" not in written

    def test_preserves_extra_fields(self, monkeypatch, tmp_path):
        """Should preserve extra fields from existing central file."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        old_data = {
            "service": "memory",
            "last_updated": "2026-01-01",
            "custom_field": "keep_me",
            "stats": {"total_vectors": 0, "total_archives": 0, "last_rollover": ""},
        }
        (central_dir / "MEMORY.central.json").write_text(json.dumps(old_data), encoding="utf-8")

        result = cw.update_central()

        assert result["success"] is True

        written = json.loads((central_dir / "MEMORY.central.json").read_text(encoding="utf-8"))
        assert written["custom_field"] == "keep_me"

    def test_failure_returns_error(self, monkeypatch, tmp_path):
        """Should return success=False with error when collect_stats fails."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        monkeypatch.setattr(cw, "collect_stats", MagicMock(side_effect=RuntimeError("boom")))

        result = cw.update_central()

        assert result["success"] is False
        assert "error" in result

    def test_logs_operation(self, monkeypatch, tmp_path):
        """Should call json_handler.log_operation on success."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        mock_handler: MagicMock = sys.modules["aipass.memory.apps.handlers.json"].json_handler

        cw.update_central()

        mock_handler.log_operation.assert_called_once()
        call_args = mock_handler.log_operation.call_args
        assert call_args[0][0] == "update_central"


# ===========================================================================
# Tests: get_current_stats
# ===========================================================================


class TestGetCurrentStats:
    """Test get_current_stats read-only stats collection."""

    def test_success(self, monkeypatch, tmp_path):
        """Should return success=True with stats fields."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        result = cw.get_current_stats()

        assert result["success"] is True
        assert "total_vectors" in result
        assert "total_archives" in result
        assert "last_rollover" in result

    def test_does_not_write_file(self, monkeypatch, tmp_path):
        """Should NOT create or modify the central file."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        cw.get_current_stats()

        central_file = tmp_path / "central" / "MEMORY.central.json"
        assert not central_file.exists()

    def test_failure_returns_error(self, monkeypatch, tmp_path):
        """Should return success=False with error when stats collection fails."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        monkeypatch.setattr(cw, "collect_stats", MagicMock(side_effect=RuntimeError("db error")))

        result = cw.get_current_stats()

        assert result["success"] is False
        assert "error" in result
        assert "db error" in result["error"]

    def test_with_real_data(self, monkeypatch, tmp_path):
        """Should return actual counts from real test data."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        # Set up chroma DB
        db_file = tmp_path / ".chroma" / "chroma.sqlite3"
        _create_chroma_db(db_file, num_rows=3)

        # Set up archive files
        archive = tmp_path / ".archive"
        archive.mkdir(parents=True)
        (archive / "s1.md").write_text("session 1", encoding="utf-8")
        (archive / "s2.md").write_text("session 2", encoding="utf-8")

        result = cw.get_current_stats()

        assert result["success"] is True
        assert result["total_vectors"] == 3
        assert result["total_archives"] == 2
        assert result["last_rollover"] != ""
