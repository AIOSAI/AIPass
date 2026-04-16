# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_memory_files.py
# Date: 2026-03-24
# Version: 1.2.0
# Category: memory/tests
# =============================================

"""
Tests for memory_files.py -- Memory File Safe I/O Handler.

Covers read_memory_file, write_memory_file, read_memory_file_data,
write_memory_file_simple, and update_metadata.

The module under test imports ``json_handler`` and ``get_system_logger``
at module level.  The conftest autouse fixture mocks those via
``sys.modules``, but the conftest also replaces the entire
``aipass.memory.apps.handlers.json`` package with a MagicMock -- which
prevents Python from resolving child modules like ``memory_files``.

The fix: each test pops the cached ``memory_files`` module from
``sys.modules`` and re-imports, after ensuring the parent package mock
is in place AND the real ``memory_files`` module is registered.
"""

import json
import sys
import importlib
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Per-test fixture: force-reimport memory_files with fresh mocks
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _fresh_memory_files(monkeypatch):
    """Ensure memory_files module is freshly imported each test.

    The conftest autouse fixture replaces ``aipass.memory.apps.handlers.json``
    with a MagicMock, which blocks ``from ... import memory_files``.  We fix
    this by:
    1. Popping the cached memory_files module (if any) from sys.modules.
    2. Temporarily restoring the REAL json package so importlib can find
       the submodule.
    """
    # If the real package was ever imported, restore it for the duration
    # of the import.  Otherwise, remove the mock so Python can discover
    # the real package on disk.
    # Try to find the real package by importing with the mock removed
    saved = sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.memory_files", None)

    try:
        # Import the real package so memory_files can be found
        sys.modules.get("aipass.memory.apps.handlers.json")
    except Exception:
        # If we can't import the real package, restore the mock
        if saved is not None:
            sys.modules["aipass.memory.apps.handlers.json"] = saved

    # Now force-reimport memory_files via importlib.reload or fresh import
    mem_files_key = "aipass.memory.apps.handlers.json.memory_files"
    existing = sys.modules.get(mem_files_key)
    if existing is not None:
        importlib.reload(existing)
    else:
        sys.modules.pop(mem_files_key, None)

    yield

    # Teardown: restore the mock that conftest set up
    # (monkeypatch will also restore on its own, but be safe)


# =============================================================================
# read_memory_file
# =============================================================================


class TestReadMemoryFile:
    """Tests for read_memory_file(path) -- safe JSON read with error handling."""

    def test_reads_valid_json_file(self, tmp_path: Path) -> None:
        """Returns success=True and parsed data for a well-formed JSON file."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        data = {"document_metadata": {"document_type": "test"}, "key": "value"}
        file_path = tmp_path / "test.local.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = read_memory_file(file_path)

        assert result["success"] is True
        assert result["data"] == data
        assert result["file"] == str(file_path)

    def test_nonexistent_file_returns_error(self, tmp_path: Path) -> None:
        """Returns success=False with descriptive error for missing files."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        missing = tmp_path / "does_not_exist.json"

        result = read_memory_file(missing)

        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_corrupted_json_returns_error(self, tmp_path: Path) -> None:
        """Returns success=False for files with invalid JSON content."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        corrupt_file = tmp_path / "corrupt.json"
        corrupt_file.write_text("{invalid json content", encoding="utf-8")

        result = read_memory_file(corrupt_file)

        assert result["success"] is False
        assert "Corrupt JSON" in result["error"]

    def test_empty_file_returns_error(self, tmp_path: Path) -> None:
        """An empty file is not valid JSON -- returns success=False."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        empty_file = tmp_path / "empty.json"
        empty_file.write_text("", encoding="utf-8")

        result = read_memory_file(empty_file)

        assert result["success"] is False
        assert "Corrupt JSON" in result["error"]

    def test_empty_json_object_reads_successfully(self, tmp_path: Path) -> None:
        """An empty JSON object {} reads without error."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        file_path = tmp_path / "empty_obj.json"
        file_path.write_text("{}", encoding="utf-8")

        result = read_memory_file(file_path)

        assert result["success"] is True
        assert result["data"] == {}

    def test_nested_data_preserved(self, tmp_path: Path) -> None:
        """Deeply nested structures survive the round-trip."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        data = {
            "document_metadata": {
                "status": {"health": "healthy", "current_lines": 120}
            },
            "sessions": [
                {"session_number": 1, "entries": [{"type": "learning", "text": "test"}]}
            ],
        }
        file_path = tmp_path / "nested.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = read_memory_file(file_path)

        assert result["success"] is True
        assert result["data"]["sessions"][0]["entries"][0]["text"] == "test"

    def test_return_type_is_dict_with_success_key(self, tmp_path: Path) -> None:
        """Return value is always a dict containing 'success'."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        file_path = tmp_path / "simple.json"
        file_path.write_text('{"a": 1}', encoding="utf-8")

        result = read_memory_file(file_path)

        assert isinstance(result, dict)
        assert "success" in result

    def test_result_contains_file_key_on_success(self, tmp_path: Path, sample_memory_data: dict) -> None:
        """Successful result includes 'file' key with the path string."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file

        file_path = tmp_path / "with_file_key.json"
        file_path.write_text(json.dumps(sample_memory_data), encoding="utf-8")

        result = read_memory_file(file_path)

        assert result["success"] is True
        assert "file" in result
        assert "data" in result


# =============================================================================
# write_memory_file
# =============================================================================


class TestWriteMemoryFile:
    """Tests for write_memory_file(path, data) -- atomic write with temp file + rename."""

    def test_writes_valid_data(self, tmp_path: Path) -> None:
        """Creates file with correct JSON content and returns success."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        data = {"document_metadata": {"document_type": "test"}, "sessions": []}
        file_path = tmp_path / "output.json"

        result = write_memory_file(file_path, data)

        assert result["success"] is True
        assert result["file"] == str(file_path)
        assert file_path.exists()

        written = json.loads(file_path.read_text(encoding="utf-8"))
        assert written == data

    def test_atomic_write_no_temp_files_left(self, tmp_path: Path) -> None:
        """After a successful write, no temp files remain in the directory."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        data = {"clean": True}
        file_path = tmp_path / "clean.json"

        write_memory_file(file_path, data)

        # Temp files follow the pattern .<name>.*.tmp
        remaining_tmp = list(tmp_path.glob("*.tmp"))
        remaining_hidden = list(tmp_path.glob(".*.tmp"))
        assert remaining_tmp == []
        assert remaining_hidden == []
        assert file_path.exists()

    def test_preserves_formatting_indent2(self, tmp_path: Path) -> None:
        """Written JSON uses indent=2 and ends with a trailing newline."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        data = {"key": "value"}
        file_path = tmp_path / "formatted.json"

        write_memory_file(file_path, data)

        raw = file_path.read_text(encoding="utf-8")
        assert raw.endswith("\n")
        assert '  "key": "value"' in raw

    def test_rejects_non_dict_list(self, tmp_path: Path) -> None:
        """Returns error when data is a list instead of a dict."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        result = write_memory_file(tmp_path / "bad.json", ["not", "a", "dict"])  # type: ignore[arg-type]

        assert result["success"] is False
        assert "Data must be dict" in result["error"]
        assert "list" in result["error"]

    def test_rejects_non_dict_string(self, tmp_path: Path) -> None:
        """Returns error when data is a string instead of a dict."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        result = write_memory_file(tmp_path / "bad.json", "a string")  # type: ignore[arg-type]

        assert result["success"] is False
        assert "Data must be dict" in result["error"]
        assert "str" in result["error"]

    def test_rejects_non_dict_int(self, tmp_path: Path) -> None:
        """Returns error when data is an integer instead of a dict."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        result = write_memory_file(tmp_path / "bad.json", 42)  # type: ignore[arg-type]

        assert result["success"] is False
        assert "Data must be dict" in result["error"]

    def test_nonexistent_parent_dir_returns_error(self, tmp_path: Path) -> None:
        """Returns error when parent directory does not exist."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        bad_path = tmp_path / "nonexistent" / "subdir" / "file.json"

        result = write_memory_file(bad_path, {"key": "value"})

        assert result["success"] is False
        assert "error" in result

    def test_overwrites_existing_file(self, tmp_path: Path) -> None:
        """Atomic rename replaces original file content entirely."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        file_path = tmp_path / "overwrite.json"
        file_path.write_text(json.dumps({"old": True}), encoding="utf-8")

        write_memory_file(file_path, {"new": True})

        written = json.loads(file_path.read_text(encoding="utf-8"))
        assert "new" in written
        assert "old" not in written

    def test_unicode_content_preserved(self, tmp_path: Path) -> None:
        """ensure_ascii=False means unicode characters are written directly."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file

        data = {"greeting": "Bonjour, le monde!"}
        file_path = tmp_path / "unicode.json"

        write_memory_file(file_path, data)

        raw = file_path.read_text(encoding="utf-8")
        assert "Bonjour" in raw
        assert "\\u" not in raw


# =============================================================================
# read_memory_file_data
# =============================================================================


class TestReadMemoryFileData:
    """Tests for read_memory_file_data(path) -- convenience unwrapper returning data or None."""

    def test_returns_data_directly(self, tmp_path: Path) -> None:
        """Returns just the parsed dict, not the success/error wrapper."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data

        data = {"document_metadata": {"version": "2.0.0"}, "sessions": []}
        file_path = tmp_path / "direct.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = read_memory_file_data(file_path)

        assert result is not None
        assert isinstance(result, dict)
        assert result == data

    def test_returns_none_on_missing_file(self, tmp_path: Path) -> None:
        """Returns None when file does not exist."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data

        result = read_memory_file_data(tmp_path / "missing.json")

        assert result is None

    def test_returns_none_on_corrupt_file(self, tmp_path: Path) -> None:
        """Returns None when JSON is malformed."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data

        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("not valid json {{{", encoding="utf-8")

        result = read_memory_file_data(bad_file)

        assert result is None

    def test_returns_none_on_empty_file(self, tmp_path: Path) -> None:
        """Returns None for an empty file (not valid JSON)."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data

        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")

        result = read_memory_file_data(empty)

        assert result is None

    def test_extracts_full_data_with_sample(self, tmp_path: Path, sample_memory_data: dict) -> None:
        """Extracts full data portion including metadata, sessions, and learnings."""
        from aipass.memory.apps.handlers.json.memory_files import read_memory_file_data

        file_path = tmp_path / "sample.local.json"
        file_path.write_text(json.dumps(sample_memory_data, indent=2), encoding="utf-8")

        result = read_memory_file_data(file_path)

        assert result is not None
        assert result["document_metadata"]["document_type"] == "session_history"
        assert len(result["sessions"]) == 1
        assert "key_learnings" in result


# =============================================================================
# write_memory_file_simple
# =============================================================================


class TestWriteMemoryFileSimple:
    """Tests for write_memory_file_simple(path, data) -- boolean convenience wrapper."""

    def test_returns_true_on_success(self, tmp_path: Path) -> None:
        """Returns True when write succeeds."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file_simple

        file_path = tmp_path / "simple.json"

        result = write_memory_file_simple(file_path, {"success": True})

        assert result is True
        assert file_path.exists()

    def test_returns_false_on_missing_parent(self, tmp_path: Path) -> None:
        """Returns False when parent directory does not exist."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file_simple

        bad_path = tmp_path / "no" / "such" / "dir" / "file.json"

        result = write_memory_file_simple(bad_path, {"test": True})

        assert result is False

    def test_returns_false_for_non_dict(self, tmp_path: Path) -> None:
        """Returns False when data is not a dict."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file_simple

        result = write_memory_file_simple(tmp_path / "bad_type.json", [1, 2, 3])  # type: ignore[arg-type]

        assert result is False

    def test_file_content_matches_input(self, tmp_path: Path) -> None:
        """Written file content matches the input data exactly."""
        from aipass.memory.apps.handlers.json.memory_files import write_memory_file_simple

        data = {"branch": "memory", "version": "1.0.0"}
        file_path = tmp_path / "verify.json"

        write_memory_file_simple(file_path, data)

        written = json.loads(file_path.read_text(encoding="utf-8"))
        assert written == data

    def test_roundtrip_with_read_data(self, tmp_path: Path) -> None:
        """Data survives a write-then-read roundtrip via convenience functions."""
        from aipass.memory.apps.handlers.json.memory_files import (
            write_memory_file_simple,
            read_memory_file_data,
        )

        payload = {"sessions": [{"id": 1}], "meta": "test"}
        file_path = tmp_path / "roundtrip.json"

        assert write_memory_file_simple(file_path, payload) is True

        result = read_memory_file_data(file_path)
        assert result == payload


# =============================================================================
# update_metadata
# =============================================================================


class TestUpdateMetadata:
    """Tests for update_metadata(path, **updates) -- updates document_metadata.status fields."""

    def test_updates_existing_status_fields(self, tmp_path: Path) -> None:
        """Overwrites existing status fields with new values."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {
            "document_metadata": {
                "document_type": "session_history",
                "status": {"health": "unknown", "current_lines": 0},
            },
            "sessions": [],
        }
        file_path = tmp_path / "meta.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = update_metadata(file_path, health="healthy", current_lines=150)

        assert result["success"] is True

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        assert updated["document_metadata"]["status"]["health"] == "healthy"
        assert updated["document_metadata"]["status"]["current_lines"] == 150

    def test_adds_new_status_fields(self, tmp_path: Path) -> None:
        """New keys that did not exist before are added to the status section."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {
            "document_metadata": {
                "document_type": "session_history",
                "status": {"health": "healthy"},
            },
        }
        file_path = tmp_path / "add_field.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = update_metadata(file_path, last_health_check="2026-03-24")

        assert result["success"] is True

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        assert updated["document_metadata"]["status"]["last_health_check"] == "2026-03-24"
        # Existing field preserved
        assert updated["document_metadata"]["status"]["health"] == "healthy"

    def test_creates_metadata_structure_if_missing(self, tmp_path: Path) -> None:
        """Creates document_metadata and status keys when they do not exist at all."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {"sessions": []}
        file_path = tmp_path / "no_meta.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = update_metadata(file_path, health="healthy")

        assert result["success"] is True

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        assert updated["document_metadata"]["status"]["health"] == "healthy"

    def test_creates_status_when_metadata_exists_but_status_missing(self, tmp_path: Path) -> None:
        """Creates status key when document_metadata exists but status does not."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {"document_metadata": {"document_type": "test"}}
        file_path = tmp_path / "no_status.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = update_metadata(file_path, health="healthy", current_lines=10)

        assert result["success"] is True

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        assert updated["document_metadata"]["status"]["health"] == "healthy"
        assert updated["document_metadata"]["status"]["current_lines"] == 10
        # Original metadata field preserved
        assert updated["document_metadata"]["document_type"] == "test"

    def test_preserves_other_data(self, tmp_path: Path) -> None:
        """Fields outside document_metadata.status are not modified."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {
            "document_metadata": {
                "document_type": "session_history",
                "version": "2.0.0",
                "status": {"health": "unknown"},
            },
            "sessions": [{"session_number": 1}],
            "key_learnings": {"item": "preserved"},
        }
        file_path = tmp_path / "preserve.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        update_metadata(file_path, health="healthy")

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        assert updated["sessions"] == [{"session_number": 1}]
        assert updated["key_learnings"]["item"] == "preserved"
        assert updated["document_metadata"]["version"] == "2.0.0"

    def test_returns_error_for_missing_file(self, tmp_path: Path) -> None:
        """Returns success=False with error when source file does not exist."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        result = update_metadata(tmp_path / "missing.json", health="healthy")

        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_returns_error_for_corrupt_json(self, tmp_path: Path) -> None:
        """Returns success=False when the file contains invalid JSON."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        bad = tmp_path / "corrupt_meta.json"
        bad.write_text("{{{{not json", encoding="utf-8")

        result = update_metadata(bad, health="broken")

        assert result["success"] is False
        assert "Corrupt JSON" in result["error"]

    def test_multiple_fields_updated_at_once(self, tmp_path: Path) -> None:
        """Multiple keyword args update multiple status fields in one call."""
        from aipass.memory.apps.handlers.json.memory_files import update_metadata

        data = {"document_metadata": {"status": {}}}
        file_path = tmp_path / "multi.json"
        file_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

        update_metadata(
            file_path,
            health="healthy",
            current_lines=200,
            last_health_check="2026-03-24",
        )

        updated = json.loads(file_path.read_text(encoding="utf-8"))
        status = updated["document_metadata"]["status"]
        assert status["health"] == "healthy"
        assert status["current_lines"] == 200
        assert status["last_health_check"] == "2026-03-24"
