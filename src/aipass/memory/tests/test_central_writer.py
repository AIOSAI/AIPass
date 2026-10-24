# =================== AIPass ====================
# Name: test_central_writer.py
# Description: Tests for the central writer handler
# Version: 1.0.2
# Created: 2026-04-05
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/central_writer.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — _find_repo_root's delegation to repo_root, in tests/test_repo_root.py
# seedgo: no-test-needed(covered_elsewhere) — when the rollover calls update_central, in tests/test_orchestrator_exec.py
# seedgo: no-test-needed(external) — the live central file CENTRAL_FILE names; every test here redirects it to tmp_path
# seedgo: no-test-needed(shared) — the json_handler.log_operation entry update_central writes; the json handler's lane

import json
import sqlite3
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from aipass.memory.apps.handlers import central_writer
from aipass.memory.apps.handlers import repo_root as rr


def _import_central_writer(monkeypatch, tmp_path):
    """The real central_writer, with every path constant it writes or reads at tmp_path.

    Its json_handler is conftest's stand-in, which repo_root's diagnostic also reaches.
    """
    monkeypatch.setattr(central_writer, "json_handler", sys.modules["aipass.memory.apps.handlers.json"].json_handler)
    monkeypatch.setattr(central_writer, "_MEMORY_ROOT", tmp_path)
    monkeypatch.setattr(central_writer, "CENTRAL_FILE", tmp_path / "central" / "MEMORY.central.json")
    monkeypatch.setattr(central_writer, "CHROMA_DB_PATH", tmp_path / ".chroma")

    return central_writer


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

    def test_an_unreadable_store_is_never_published_as_zero_vectors(self, monkeypatch, tmp_path):
        """A store that cannot be counted fails the update, never publishes 0 vectors as a success."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        chroma_dir = tmp_path / ".chroma"
        chroma_dir.mkdir(parents=True)
        (chroma_dir / "chroma.sqlite3").write_text("not a database", encoding="utf-8")

        result = cw.update_central()

        assert result["success"] is False
        assert result["error"]
        assert not cw.CENTRAL_FILE.exists()


class TestCollectStats:
    """Test collect_stats aggregation."""

    def test_returns_the_vector_count_only(self, monkeypatch, tmp_path):
        """The stats are the one number memory can measure."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        _create_chroma_db(tmp_path / ".chroma" / "chroma.sqlite3", num_rows=4)

        assert cw.collect_stats() == {"total_vectors": 4}

    def test_zero_when_empty(self, monkeypatch, tmp_path):
        """Should return zero when no data exists."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        assert cw.collect_stats() == {"total_vectors": 0}


class TestReadCentralFile:
    """Test read_central_file JSON reading."""

    def test_file_does_not_exist(self, monkeypatch, tmp_path):
        """Should return default structure when file is missing."""
        cw = _import_central_writer(monkeypatch, tmp_path)

        result = cw.read_central_file()

        assert result["service"] == "memory"
        assert result["last_updated"] == ""
        assert result["stats"] == {"total_vectors": 0}

    def test_file_exists(self, monkeypatch, tmp_path):
        """Should read and return existing JSON contents."""
        cw = _import_central_writer(monkeypatch, tmp_path)
        central_dir = tmp_path / "central"
        central_dir.mkdir(parents=True)

        data = {
            "service": "memory",
            "last_updated": "2026-03-01T12:00:00",
            "stats": {"total_vectors": 42},
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

        with pytest.raises(Exception, match="Failed to read central file"):
            cw.read_central_file()


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
        assert not central_file.with_suffix(".tmp").exists(), "the atomic write left its temp file"

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
        # A file as parent makes mkdir fail on all platforms.
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        monkeypatch.setattr(cw, "CENTRAL_FILE", blocker / "subdir" / "impossible.json")

        with pytest.raises(Exception, match="Failed to write central file"):
            cw.write_central_file({"test": True})


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
            "stats": {"total_vectors": 0},
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
            "stats": {"total_vectors": 0},
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
        """Should log update_central exactly once — counted by OPERATION, not by mock.

        A bare checkout adds a ``repo_root_fallback`` diagnostic on the same mock.
        """
        cw = _import_central_writer(monkeypatch, tmp_path)
        mock_handler: MagicMock = sys.modules["aipass.memory.apps.handlers.json"].json_handler

        cw.update_central()

        ours = [call for call in mock_handler.log_operation.call_args_list if call[0][0] == "update_central"]
        assert len(ours) == 1, (
            f"expected exactly one update_central log, got {mock_handler.log_operation.call_args_list}"
        )


class TestTheBareWorldTheOldPinCouldNotSurvive:
    """CI's world, built here: no marker above the walk, so the fallback fires and the write still lands.

    Only the real checkout's markers are denied; tests that build a marker in tmp_path must still find it.
    """

    @staticmethod
    def _bare(monkeypatch):
        """Deny the marker on the live tree only — prax's hide-the-marker trick."""
        real = rr.exists_exactly
        live = rr.SOURCE_ROOT

        def _exists_exactly(path):
            if Path(path).is_relative_to(live):
                return False
            return real(path)

        monkeypatch.setattr(rr, "exists_exactly", _exists_exactly)

    def test_the_fallback_really_does_fire_in_this_world(self, monkeypatch, tmp_path):
        """Arming probe: without this, the test below passes for the wrong reason."""
        self._bare(monkeypatch)
        cw = _import_central_writer(monkeypatch, tmp_path)
        mock_handler: MagicMock = sys.modules["aipass.memory.apps.handlers.json"].json_handler

        # The walk runs at import in life (CENTRAL_FILE); the module is imported once, at collection.
        cw._find_repo_root()
        cw.update_central()

        operations = [call[0][0] for call in mock_handler.log_operation.call_args_list]
        assert "repo_root_fallback" in operations, (
            "the marker denial did not reach repo_root, so the world below is not CI's: " + str(operations)
        )

    def test_the_write_still_lands_with_the_diagnostic_riding_along(self, monkeypatch, tmp_path):
        self._bare(monkeypatch)
        cw = _import_central_writer(monkeypatch, tmp_path)
        mock_handler: MagicMock = sys.modules["aipass.memory.apps.handlers.json"].json_handler

        cw._find_repo_root()
        result = cw.update_central()

        assert result["success"] is True
        ours = [call for call in mock_handler.log_operation.call_args_list if call[0][0] == "update_central"]
        assert len(ours) == 1
