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
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.memory_files", None)

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
            "document_metadata": {"status": {"health": "healthy", "current_lines": 120}},
            "sessions": [{"session_number": 1, "entries": [{"type": "learning", "text": "test"}]}],
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


# =============================================================================
# _check_entry_counts (soft count guard)
# =============================================================================


class TestCheckEntryCounts:
    """Tests for the soft entry-count guard added for #664."""

    @staticmethod
    def _warn_calls(memory_files_mod):  # type: ignore[no-untyped-def]
        """Get warning call args from the mocked logger."""
        return getattr(memory_files_mod.logger, "warning").call_args_list

    @staticmethod
    def _reset_warns(memory_files_mod):  # type: ignore[no-untyped-def]
        """Reset warning mock on the mocked logger."""
        getattr(memory_files_mod.logger, "warning").reset_mock()

    def test_warns_when_over_rollover_limit(self, tmp_path: Path, monkeypatch) -> None:
        """Writing more entries than rollover count limit should log a warning."""
        from aipass.memory.apps.handlers.json import memory_files

        monkeypatch.setattr(
            memory_files.config_loader,
            "section",
            lambda name: {
                "per_branch": {},
                "defaults": {"local": {"sessions": {"count": 5}}},
            },
        )

        trinity_dir = tmp_path / "testbranch" / ".trinity"
        trinity_dir.mkdir(parents=True)
        file_path = trinity_dir / "local.json"

        data = {"sessions": [{"id": f"s{i}"} for i in range(10)]}

        memory_files._check_entry_counts(file_path, data)

        calls = self._warn_calls(memory_files)
        assert any("ENTRY COUNT" in str(c) and "10/5" in str(c) for c in calls)

    def test_no_warn_when_under_limit(self, tmp_path: Path, monkeypatch) -> None:
        """Entries under rollover limit should produce no warning."""
        from aipass.memory.apps.handlers.json import memory_files

        monkeypatch.setattr(
            memory_files.config_loader,
            "section",
            lambda name: {
                "per_branch": {},
                "defaults": {"local": {"sessions": {"count": 20}}},
            },
        )

        trinity_dir = tmp_path / "testbranch" / ".trinity"
        trinity_dir.mkdir(parents=True)
        file_path = trinity_dir / "local.json"

        data = {"sessions": [{"id": f"s{i}"} for i in range(5)]}

        self._reset_warns(memory_files)
        memory_files._check_entry_counts(file_path, data)

        calls = self._warn_calls(memory_files)
        assert not any("ENTRY COUNT" in str(c) for c in calls)

    def test_skips_non_trinity_files(self, tmp_path: Path, monkeypatch) -> None:
        """Non-.trinity/ files should be silently skipped."""
        from aipass.memory.apps.handlers.json import memory_files

        file_path = tmp_path / "random.json"
        data = {"sessions": [{"id": f"s{i}"} for i in range(100)]}

        self._reset_warns(memory_files)
        memory_files._check_entry_counts(file_path, data)

        calls = self._warn_calls(memory_files)
        assert not any("ENTRY COUNT" in str(c) for c in calls)

    def test_uses_per_branch_override(self, tmp_path: Path, monkeypatch) -> None:
        """Per-branch rollover config should take precedence over defaults."""
        from aipass.memory.apps.handlers.json import memory_files

        monkeypatch.setattr(
            memory_files.config_loader,
            "section",
            lambda name: {
                "per_branch": {"mybranch": {"local": {"sessions": {"count": 3}}}},
                "defaults": {"local": {"sessions": {"count": 100}}},
            },
        )

        trinity_dir = tmp_path / "mybranch" / ".trinity"
        trinity_dir.mkdir(parents=True)
        file_path = trinity_dir / "local.json"

        data = {"sessions": [{"id": f"s{i}"} for i in range(5)]}

        memory_files._check_entry_counts(file_path, data)

        calls = self._warn_calls(memory_files)
        assert any("ENTRY COUNT" in str(c) and "5/3" in str(c) for c in calls)

    def test_does_not_block_write(self, tmp_path: Path, monkeypatch) -> None:
        """Entry count guard should never prevent write_memory_file from succeeding."""
        from aipass.memory.apps.handlers.json import memory_files

        monkeypatch.setattr(
            memory_files.config_loader,
            "section",
            lambda name: {
                "per_branch": {},
                "defaults": {"local": {"sessions": {"count": 2}}},
            },
        )

        trinity_dir = tmp_path / "testbranch" / ".trinity"
        trinity_dir.mkdir(parents=True)
        file_path = trinity_dir / "local.json"

        data = {
            "document_metadata": {"document_type": "test"},
            "sessions": [{"id": f"s{i}"} for i in range(20)],
        }

        result = memory_files.write_memory_file(file_path, data)

        assert result["success"] is True
        assert file_path.exists()


# =============================================================================
# _check_entry_counts — auto-compact snapshots carry their own budget
# =============================================================================


class TestSessionSnapshotBudget:
    """Auto-compact snapshots never count against the regular session cap.

    The extractor has budgeted them separately since fd091c25.  This guard
    counted the combined array, so a branch sitting legally at 14 regular
    + 2 snapshots warned 16/15 on every .trinity write, fleet-wide, and no
    amount of rollover could ever satisfy it — rollover was right to archive
    nothing.  The two must agree on what counts.
    """

    _LIMITS = {
        "per_branch": {},
        "defaults": {"local": {"sessions": {"count": 15, "auto_compact_cap": 3}}},
    }

    def _run(self, tmp_path: Path, monkeypatch, sessions: list) -> list:  # type: ignore[no-untyped-def]
        """Run the guard over *sessions* and return ENTRY COUNT warning strings."""
        from aipass.memory.apps.handlers.json import memory_files

        monkeypatch.setattr(memory_files.config_loader, "section", lambda name: self._LIMITS)

        trinity_dir = tmp_path / "testbranch" / ".trinity"
        trinity_dir.mkdir(parents=True, exist_ok=True)
        file_path = trinity_dir / "local.json"

        warn_mock = getattr(memory_files.logger, "warning")
        warn_mock.reset_mock()
        memory_files._check_entry_counts(file_path, {"sessions": sessions})

        return [str(c) for c in warn_mock.call_args_list if "ENTRY COUNT" in str(c)]

    @staticmethod
    def _regular(n: int) -> list:
        return [{"number": i, "summary": f"s{i}"} for i in range(n)]

    @staticmethod
    def _snapshots(n: int) -> list:
        return [{"number": 900 + i, "summary": f"snap{i}", "status": "auto-compact"} for i in range(n)]

    def test_live_fleet_state_warns_nothing(self, tmp_path: Path, monkeypatch) -> None:
        """14 regular + 2 snapshots = 16 total, both budgets under cap.

        This is the exact state every warned branch was in tonight.
        """
        sessions = self._regular(14) + self._snapshots(2)

        warnings = self._run(tmp_path, monkeypatch, sessions)

        assert warnings == []

    def test_regular_sessions_over_cap_still_warns(self, tmp_path: Path, monkeypatch) -> None:
        """The guard must still do its job — 17 regular is genuinely over."""
        sessions = self._regular(17) + self._snapshots(2)

        warnings = self._run(tmp_path, monkeypatch, sessions)

        assert len(warnings) == 1
        assert "17/15" in warnings[0]
        assert "auto-compact" not in warnings[0]

    def test_snapshots_over_their_own_cap_warns(self, tmp_path: Path, monkeypatch) -> None:
        """Snapshots have a budget too — 5 against a cap of 3 is over."""
        sessions = self._regular(10) + self._snapshots(5)

        warnings = self._run(tmp_path, monkeypatch, sessions)

        assert len(warnings) == 1
        assert "sessions(auto-compact)" in warnings[0]
        assert "5/3" in warnings[0]

    def test_both_over_warns_separately(self, tmp_path: Path, monkeypatch) -> None:
        """Two independent budgets means two distinct warnings, not one blur."""
        sessions = self._regular(20) + self._snapshots(6)

        warnings = self._run(tmp_path, monkeypatch, sessions)

        assert len(warnings) == 2
        assert any("sessions(auto-compact)" in w and "6/3" in w for w in warnings)
        assert any("20/15" in w and "auto-compact" not in w for w in warnings)

    def test_snapshot_split_matches_the_extractor(self, tmp_path: Path, monkeypatch) -> None:
        """Non-dict junk counts as regular in both places.

        The extractor treats anything that is not a dict with
        status == "auto-compact" as a regular entry.  If this guard split
        differently, the two would disagree again in a subtler way.
        """
        from aipass.memory.apps.handlers.rollover import extractor  # noqa: F401

        sessions = self._regular(14) + self._snapshots(2) + ["a bare string", None]

        warnings = self._run(tmp_path, monkeypatch, sessions)

        # 16 regular (14 + 2 junk) against a cap of 15 -> exactly one warning
        assert len(warnings) == 1
        assert "16/15" in warnings[0]
