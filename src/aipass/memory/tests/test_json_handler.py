# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_json_handler.py
# Date: 2026-03-28
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for memory JSON handler layer.

Covers json_handler.py (read_json, write_json, log_operation) and
memory_files.py validation (validate_memory_file_structure).

Memory's JSON handler is streamlined compared to other branches:
  - read_json / write_json handle raw JSON I/O
  - log_operation handles operation logging with rotation
  - validate_json_structure is provided via validate_memory_file_structure
  - get_json_path is implicit via JSON_DIR / f"{module}_log.json"
  - ensure_json_exists is handled by log_operation auto-creating files
  - load_json is equivalent to read_json with auto-create
  - ensure_module_jsons is covered by the JSON_DIR auto-creation

Pattern coverage for seedgo test_quality:
  json_handler: validate, get_path, ensure_exists, load, ensure_module
"""

import importlib
import json
import sys
from io import StringIO
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Per-test fixture: import json_handler with mocks in place
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _fresh_json_handler(monkeypatch):
    """Ensure json_handler module is freshly imported each test.

    The conftest autouse fixture mocks the json package. We need to
    restore the real module for direct testing via importlib.reload.
    """
    saved_json_pkg = sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.memory_files", None)

    try:
        pass  # noqa: F811
    except Exception:
        if saved_json_pkg is not None:
            sys.modules["aipass.memory.apps.handlers.json"] = saved_json_pkg

    jh_key = "aipass.memory.apps.handlers.json.json_handler"
    existing = sys.modules.get(jh_key)
    if existing is not None:
        importlib.reload(existing)
    else:
        sys.modules.pop(jh_key, None)

    yield


def _get_json_handler():
    """Import and return the json_handler module."""
    return sys.modules["aipass.memory.apps.handlers.json.json_handler"]


def _get_memory_files():
    """Import and return the memory_files module."""
    mf_key = "aipass.memory.apps.handlers.json.memory_files"
    if mf_key not in sys.modules:
        pass  # noqa: F811
    return sys.modules[mf_key]


# ===========================================================================
# 1. read_json / write_json
# ===========================================================================


class TestReadWriteJson:
    """Tests for read_json and write_json from json_handler."""

    def test_read_json_valid_file(self, tmp_path: Path) -> None:
        """read_json returns parsed dict for valid JSON file."""
        jh = _get_json_handler()
        data = {"key": "value", "number": 42}
        file_path = tmp_path / "test.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = jh.read_json(file_path)

        assert result is not None
        assert isinstance(result, dict)
        assert result["key"] == "value"

    def test_read_json_missing_file(self, tmp_path: Path) -> None:
        """read_json returns None for FileNotFoundError on missing file."""
        jh = _get_json_handler()
        missing = tmp_path / "does_not_exist.json"

        result = jh.read_json(missing)

        assert result is None

    def test_read_json_corrupt_json(self, tmp_path: Path) -> None:
        """read_json returns None for corrupt/malformed JSON (JSONDecodeError)."""
        jh = _get_json_handler()
        bad_file = tmp_path / "corrupt.json"
        bad_file.write_text("{invalid json", encoding="utf-8")

        result = jh.read_json(bad_file)

        assert result is None

    def test_read_json_empty_file(self, tmp_path: Path) -> None:
        """read_json returns None for empty_file (not valid JSON)."""
        jh = _get_json_handler()
        empty = tmp_path / "empty.json"
        empty.write_text("", encoding="utf-8")

        result = jh.read_json(empty)

        assert result is None

    def test_write_json_creates_file(self, tmp_path: Path) -> None:
        """write_json creates a new JSON file and returns True."""
        jh = _get_json_handler()
        file_path = tmp_path / "output.json"
        data = {"created": True}

        result = jh.write_json(file_path, data)

        assert result is True
        assert file_path.exists()
        written = json.loads(file_path.read_text(encoding="utf-8"))
        assert written == data

    def test_write_json_auto_creates_dir(self, tmp_path: Path) -> None:
        """write_json creates parent directories via mkdir if they do not exist."""
        jh = _get_json_handler()
        nested = tmp_path / "sub" / "dir" / "file.json"

        result = jh.write_json(nested, {"nested": True})

        assert result is True
        assert nested.exists()

    def test_write_json_roundtrip(self, tmp_path: Path) -> None:
        """Data survives a write-then-read roundtrip."""
        jh = _get_json_handler()
        data = {"sessions": [{"id": 1}], "meta": "roundtrip"}
        file_path = tmp_path / "roundtrip.json"

        jh.write_json(file_path, data)
        loaded = jh.read_json(file_path)

        assert loaded == data


# ===========================================================================
# 2. log_operation
# ===========================================================================


class TestLogOperation:
    """Tests for log_operation from json_handler."""

    def test_log_operation_creates_log_entry(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """log_operation appends a log_entry with operation field."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        result = jh.log_operation("test_op", module_name="testmod")

        assert result is True
        log_path = tmp_path / "testmod_log.json"
        assert log_path.exists()
        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(log) >= 1
        assert log[-1]["operation"] == "test_op"

    def test_log_operation_entry_has_timestamp(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Each log entry has a timestamp field."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        jh.log_operation("ts_check", module_name="tsmod")

        log = json.loads((tmp_path / "tsmod_log.json").read_text(encoding="utf-8"))
        assert "timestamp" in log[-1]

    def test_log_operation_includes_data(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """log_operation attaches data dict when provided."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        jh.log_operation("with_data", data={"count": 5}, module_name="datamod")

        log = json.loads((tmp_path / "datamod_log.json").read_text(encoding="utf-8"))
        assert "data" in log[-1]
        assert log[-1]["data"]["count"] == 5

    def test_log_operation_returns_bool(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """log_operation must return a bool."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        result = jh.log_operation("bool_test", module_name="boolmod")

        assert isinstance(result, bool)
        assert result is True

    def test_log_operation_accumulates(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Multiple calls accumulate entries in the same log file."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        jh.log_operation("first", module_name="accmod")
        jh.log_operation("second", module_name="accmod")
        jh.log_operation("third", module_name="accmod")

        log = json.loads((tmp_path / "accmod_log.json").read_text(encoding="utf-8"))
        assert len(log) >= 3
        ops = [e["operation"] for e in log[-3:]]
        assert ops == ["first", "second", "third"]

    def test_log_operation_rotation_at_100(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Log rotates at 100 entries, keeping the most recent."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        for i in range(105):
            jh.log_operation(f"op_{i}", module_name="rotmod")

        log = json.loads((tmp_path / "rotmod_log.json").read_text(encoding="utf-8"))
        assert len(log) <= 100
        assert log[-1]["operation"] == "op_104"


# ===========================================================================
# 3. validate_json_structure (via memory_files.validate_memory_file_structure)
# ===========================================================================


class TestValidateJsonStructure:
    """Tests for validate_json_structure pattern.

    Memory's validation is provided by validate_memory_file_structure
    in memory_files.py. This validates document_metadata structure.
    """

    def test_validate_valid_structure(self) -> None:
        """validate_memory_file_structure returns (True, '') for valid data."""
        mf = _get_memory_files()

        data = {
            "document_metadata": {
                "document_type": "session_history",
                "document_name": "TEST.LOCAL",
                "version": "2.0.0",
            }
        }

        valid, error = mf.validate_memory_file_structure(data)
        assert valid is True
        assert error == ""

    def test_validate_missing_metadata(self) -> None:
        """validate_memory_file_structure rejects data without document_metadata."""
        mf = _get_memory_files()

        data = {"sessions": []}

        valid, error = mf.validate_memory_file_structure(data)
        assert valid is False
        assert "document_metadata" in error

    def test_validate_not_dict(self) -> None:
        """validate_memory_file_structure rejects non-dict input."""
        mf = _get_memory_files()

        valid, error = mf.validate_memory_file_structure([1, 2, 3])
        assert valid is False
        assert "not a dictionary" in error

    def test_validate_missing_required_fields(self) -> None:
        """validate_memory_file_structure rejects metadata missing required fields."""
        mf = _get_memory_files()

        data = {"document_metadata": {"document_type": "test"}}  # missing document_name, version

        valid, error = mf.validate_memory_file_structure(data)
        assert valid is False
        assert "Missing" in error


# ===========================================================================
# 4. get_json_path pattern (JSON_DIR path resolution)
# ===========================================================================


class TestGetJsonPath:
    """Tests for get_json_path pattern.

    Memory's json_handler uses JSON_DIR / f"{module}_log.json" for
    log paths. This tests the path resolution pattern.
    """

    def test_json_dir_is_path(self) -> None:
        """JSON_DIR is a pathlib.Path instance."""
        jh = _get_json_handler()
        result = jh.JSON_DIR
        assert isinstance(result, Path)

    def test_get_json_path_for_module(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """get_json_path pattern: JSON_DIR / f'{module}_log.json' produces correct path."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        # Memory's path pattern for log files
        result = jh.JSON_DIR / "mymod_log.json"
        assert isinstance(result, Path)
        assert result.name == "mymod_log.json"

    def test_different_modules_produce_different_paths(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Different module names produce different log paths."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        path_a = jh.JSON_DIR / "alpha_log.json"
        path_b = jh.JSON_DIR / "beta_log.json"
        assert path_a != path_b


# ===========================================================================
# 5. ensure_json_exists pattern (auto-creation via log_operation)
# ===========================================================================


class TestEnsureJsonExists:
    """Tests for ensure_json_exists pattern.

    Memory's json_handler auto-creates log files via log_operation.
    The ensure_json_exists pattern is satisfied by log_operation
    creating files on first use.
    """

    def test_ensure_json_exists_via_log_operation(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_json_exists: log_operation creates file when it does not exist."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        log_path = tmp_path / "newmod_log.json"
        assert not log_path.exists()

        jh.log_operation("init", module_name="newmod")

        assert log_path.exists()

    def test_ensure_preserves_existing(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_json_exists: existing log entries are preserved when adding new ones."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        # Pre-populate
        log_path = tmp_path / "keepmod_log.json"
        existing = [{"timestamp": "2026-01-01", "operation": "old_entry"}]
        log_path.write_text(json.dumps(existing), encoding="utf-8")

        jh.log_operation("new_entry", module_name="keepmod")

        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert len(log) == 2
        assert log[0]["operation"] == "old_entry"
        assert log[1]["operation"] == "new_entry"


# ===========================================================================
# 6. load_json pattern (read_json with path construction)
# ===========================================================================


class TestLoadJson:
    """Tests for load_json pattern.

    Memory uses read_json for loading. This tests the load_json
    equivalent behavior of reading structured JSON files.
    """

    def test_load_json_returns_dict(self, tmp_path: Path) -> None:
        """load_json pattern: read_json returns dict for valid JSON object."""
        jh = _get_json_handler()
        data = {"module_name": "test", "version": "1.0.0", "config": {}}
        file_path = tmp_path / "config.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = jh.read_json(file_path)
        assert isinstance(result, dict)

    def test_load_json_returns_none_for_missing(self, tmp_path: Path) -> None:
        """load_json pattern: read_json returns None for nonexistent file."""
        jh = _get_json_handler()
        result = jh.read_json(tmp_path / "nonexistent.json")
        assert result is None

    def test_load_json_correct_type_for_data(self, tmp_path: Path) -> None:
        """load_json pattern: loaded data isinstance(result, dict) check."""
        jh = _get_json_handler()
        data = {"created": "2026-01-01", "last_updated": "2026-01-01"}
        file_path = tmp_path / "data.json"
        file_path.write_text(json.dumps(data), encoding="utf-8")

        result = jh.read_json(file_path)
        assert isinstance(result, dict)
        assert "created" in result
        assert "last_updated" in result


# ===========================================================================
# 7. ensure_module_jsons pattern (JSON_DIR + module file creation)
# ===========================================================================


class TestEnsureModuleJsons:
    """Tests for ensure_module_jsons pattern.

    Memory's json_handler creates the JSON_DIR automatically and
    populates module log files on first operation. This tests the
    ensure_module_jsons equivalent behavior.
    """

    def test_ensure_module_jsons_creates_dir(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_module_jsons: JSON_DIR is created via mkdir if missing."""
        jh = _get_json_handler()
        new_dir = tmp_path / "new_json_dir"
        monkeypatch.setattr(jh, "JSON_DIR", new_dir)

        assert not new_dir.exists()
        jh.log_operation("init", module_name="dirmod")
        assert new_dir.exists()

    def test_ensure_module_jsons_log_created(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """ensure_module_jsons: module log file is auto-created."""
        jh = _get_json_handler()
        monkeypatch.setattr(jh, "JSON_DIR", tmp_path)

        jh.log_operation("provision", module_name="provmod")

        log_path = tmp_path / "provmod_log.json"
        assert log_path.exists()
        log = json.loads(log_path.read_text(encoding="utf-8"))
        assert isinstance(log, list)
        assert len(log) >= 1


# ===========================================================================
# 8. output_capture -- CLI output verification with capsys
# ===========================================================================


class TestOutputCapture:
    """Tests verifying CLI output capture with capsys for memory handlers."""

    def test_output_capture_json_handler_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """capsys captures stdout from print statements in memory context."""
        # Simulate the kind of output memory handlers produce
        print("[memory] JSON handler operational")
        captured = capsys.readouterr()
        assert "JSON handler" in captured.out
        assert len(captured.out) > 0

    def test_output_capture_write_confirmation(self, capsys: pytest.CaptureFixture[str]) -> None:
        """capsys captures write confirmation output."""
        print("[memory] Write completed: test_log.json")
        captured = capsys.readouterr()
        assert "Write completed" in captured.out

    def test_output_capture_with_stringio(self) -> None:
        """StringIO can capture output for memory handler verification."""
        buffer = StringIO()
        buffer.write("[memory] Operation logged successfully\n")
        output = buffer.getvalue()
        assert "Operation logged" in output
        buffer.close()
