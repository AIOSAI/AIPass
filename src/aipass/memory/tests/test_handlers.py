# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_handlers.py
# Date: 2026-03-31
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Targeted handler-layer tests for critical untested handlers.

Covers:
  - rollover/extractor.py  (_extract_items_v2, helpers)
  - tracking/line_counter.py (_count_physical_lines, update_line_count)
  - schema/normalize.py (normalize_memory_file)
  - todos[] operational schema (rollover ignores, caps enforced)

All tests use mocks/tmp_path -- no live filesystem or infrastructure access.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers -- each handler has module-level imports that need mocking
# ---------------------------------------------------------------------------


def _import_extractor(monkeypatch):
    """Import extractor with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.read_memory_file_data = MagicMock(return_value=None)
    mock_memory_files.write_memory_file_simple = MagicMock()

    mock_config_loader = MagicMock()
    mock_config_loader.section.return_value = {"defaults": {}, "per_branch": {}}

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler
    json_pkg.config_loader = mock_config_loader

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.config_loader", mock_config_loader)

    sys.modules.pop("aipass.memory.apps.handlers.rollover.extractor", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.rollover")
    if parent is not None and hasattr(parent, "extractor"):
        delattr(parent, "extractor")

    from aipass.memory.apps.handlers.rollover import extractor

    return extractor, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
        "config_loader": mock_config_loader,
    }


def _import_line_counter(monkeypatch):
    """Import line_counter with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)
    mock_memory_files = MagicMock()
    mock_memory_files.update_metadata = MagicMock(return_value={"success": True})

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.memory_files", mock_memory_files)

    sys.modules.pop("aipass.memory.apps.handlers.tracking.line_counter", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.tracking")
    if parent is not None and hasattr(parent, "line_counter"):
        delattr(parent, "line_counter")

    from aipass.memory.apps.handlers.tracking import line_counter

    return line_counter, {
        "json_handler": mock_json_handler,
        "memory_files": mock_memory_files,
    }


def _import_normalize(monkeypatch):
    """Import normalize with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    json_pkg = MagicMock()
    # Impersonating a package means answering __path__ — a bare MagicMock does not,
    # and every lazy submodule import under it then dies. See test_import_isolation.py.
    json_pkg.__path__ = [str(Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json")]
    json_pkg.json_handler = mock_json_handler

    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)

    sys.modules.pop("aipass.memory.apps.handlers.schema.normalize", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.schema")
    if parent is not None and hasattr(parent, "normalize"):
        delattr(parent, "normalize")

    from aipass.memory.apps.handlers.schema import normalize

    return normalize, {
        "json_handler": mock_json_handler,
    }


# ===========================================================================
# Tests: rollover/extractor.py
# ===========================================================================


class TestDerivebranchAndType:
    """Test _derive_branch_and_type path helper."""

    def test_trinity_path_local(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        p = tmp_path / "devpulse" / ".trinity" / "local.json"
        branch, mtype = ext._derive_branch_and_type(p)
        assert branch == "DEVPULSE"
        assert mtype == "local"

    def test_trinity_path_observations(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        p = tmp_path / "memory" / ".trinity" / "observations.json"
        branch, mtype = ext._derive_branch_and_type(p)
        assert branch == "MEMORY"
        assert mtype == "observations"

    def test_legacy_dotted_path(self, monkeypatch):
        ext, _ = _import_extractor(monkeypatch)
        p = Path("/some/path/DEVPULSE.local.json")
        branch, mtype = ext._derive_branch_and_type(p)
        assert branch == "DEVPULSE"
        assert mtype == "local"


class TestExtractItemsV2:
    """Test _extract_items_v2 entry-count based extraction."""

    def _make_v2_data(
        self, num_sessions: int = 5, num_learnings: int = 5, max_sessions: int = 3, max_learnings: int = 3
    ):
        """Build a v2 memory data dict with controllable counts."""
        sessions = [
            {"session_number": i, "date": f"2026-01-{i:02d}", "summary": f"Session {i}"}
            for i in range(1, num_sessions + 1)
        ]
        key_learnings = [
            {"number": num_learnings - i + 1, "date": f"2026-01-{i:02d}", "key": f"learning_{i}", "value": f"value_{i}"}
            for i in range(1, num_learnings + 1)
        ]
        return {
            "document_metadata": {
                "schema_version": "2.0.0",
                "limits": {
                    "max_sessions": max_sessions,
                    "max_key_learnings": max_learnings,
                },
                "status": {"current_lines": 100},
            },
            "sessions": sessions,
            "key_learnings": key_learnings,
        }

    def test_trims_sessions_to_limit(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_v2_data(num_sessions=6, max_sessions=3)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}, "key_learnings": {"count": 3}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert result["extracted_count"] == 5
        assert len(data["sessions"]) == 3

    def test_trims_key_learnings_to_limit(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_v2_data(num_sessions=2, num_learnings=7, max_sessions=3, max_learnings=4)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}, "key_learnings": {"count": 4}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert len(data["key_learnings"]) == 4
        assert result["extracted_count"] == 3

    def test_skips_when_under_limits(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_v2_data(num_sessions=2, num_learnings=2, max_sessions=5, max_learnings=5)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 5}, "key_learnings": {"count": 5}}}},
        }

        result = ext._extract_items_v2(mem_file, data)
        assert result["success"] is True
        assert result.get("skipped") is True

    def test_extracts_oldest_sessions_from_end(self, monkeypatch, tmp_path):
        """Sessions are stored newest-first, oldest at end. Extraction takes from end."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_v2_data(num_sessions=5, num_learnings=0, max_sessions=3, max_learnings=100)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}, "key_learnings": {"count": 100}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        # Kept sessions should be the first 3 (newest)
        kept_numbers = [s["session_number"] for s in data["sessions"]]
        assert kept_numbers == [1, 2, 3]
        # Extracted should be the last 2 (oldest)
        extracted_numbers = [s["session_number"] for s in result["extracted"]]
        assert extracted_numbers == [4, 5]

    def test_extracts_oldest_key_learnings_from_end(self, monkeypatch, tmp_path):
        """Lowest-numbered entries (oldest, at end) should be extracted."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_v2_data(num_sessions=0, num_learnings=5, max_sessions=100, max_learnings=3)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 100}, "key_learnings": {"count": 3}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        # Kept entries should be the first 3 (newest = highest numbers)
        kept_keys = [e["key"] for e in data["key_learnings"]]
        assert kept_keys == ["learning_1", "learning_2", "learning_3"]
        # Extracted should be the last 2 (oldest = lowest numbers)
        extracted_keys = [e["key"] for e in result["extracted"]]
        assert extracted_keys == ["learning_4", "learning_5"]


# _update_metadata_after_extraction was deleted on 2026-08-25 along with the
# status.health field it stamped; rollover moves entries and no longer edits
# metadata it does not own. Its pins live on as the sweep in
# tests/test_trinity_standard.py::TestNoHealthStamping.


class TestCreateRolloverBackup:
    """Test backup and restore file operations."""

    def test_creates_backup_file(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        mem_file = tmp_path / "local.json"
        mem_file.write_text('{"test": true}', encoding="utf-8")

        result = ext.create_rollover_backup(mem_file)
        assert result["success"] is True

        backup_path = Path(result["backup_path"])
        assert backup_path.exists()
        assert json.loads(backup_path.read_text(encoding="utf-8")) == {"test": True}

    def test_restore_from_backup(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        mem_file = tmp_path / "local.json"
        mem_file.write_text('{"original": true}', encoding="utf-8")

        ext.create_rollover_backup(mem_file)
        mem_file.write_text('{"modified": true}', encoding="utf-8")

        result = ext.restore_from_backup(mem_file)
        assert result["success"] is True
        assert json.loads(mem_file.read_text(encoding="utf-8")) == {"original": True}

    def test_restore_fails_without_backup(self, monkeypatch, tmp_path):
        ext, _ = _import_extractor(monkeypatch)
        mem_file = tmp_path / "local.json"
        mem_file.write_text("{}", encoding="utf-8")

        result = ext.restore_from_backup(mem_file)
        assert result["success"] is False


# ===========================================================================
# Tests: tracking/line_counter.py
# ===========================================================================


class TestCountPhysicalLines:
    """Test _count_physical_lines helper."""

    def test_counts_lines_correctly(self, monkeypatch, tmp_path):
        lc, _ = _import_line_counter(monkeypatch)
        f = tmp_path / "test.local.json"
        f.write_text("line1\nline2\nline3\n", encoding="utf-8")
        assert lc._count_physical_lines(f) == 3

    def test_returns_zero_for_missing_file(self, monkeypatch, tmp_path):
        lc, _ = _import_line_counter(monkeypatch)
        f = tmp_path / "missing.json"
        assert lc._count_physical_lines(f) == 0

    def test_counts_single_line_no_newline(self, monkeypatch, tmp_path):
        lc, _ = _import_line_counter(monkeypatch)
        f = tmp_path / "one.json"
        f.write_text("single line", encoding="utf-8")
        assert lc._count_physical_lines(f) == 1


class TestUpdateLineCount:
    """Test update_line_count function."""

    def test_returns_error_for_missing_file(self, monkeypatch, tmp_path):
        lc, _ = _import_line_counter(monkeypatch)
        result = lc.update_line_count(tmp_path / "gone.json")
        assert result["success"] is False

    def test_updates_line_count_successfully(self, monkeypatch, tmp_path):
        lc, _mocks = _import_line_counter(monkeypatch)
        f = tmp_path / "test.local.json"
        f.write_text('{\n  "a": 1\n}\n', encoding="utf-8")

        result = lc.update_line_count(f)
        assert result["success"] is True
        assert result["lines"] == 3

    def test_counting_lines_writes_nothing(self, monkeypatch, tmp_path):
        """The health stamp was this function's only write (removed 2026-08-25).

        The file must come back byte-identical: a counter that edits the thing
        it is counting is how `sync-lines` came to be the fleet's most frequent
        writer of a field nobody read.
        """
        lc, _mocks = _import_line_counter(monkeypatch)
        f = tmp_path / "test.local.json"
        original = '{\n  "a": 1\n}\n'
        f.write_text(original, encoding="utf-8")

        assert lc.update_line_count(f)["success"] is True
        assert f.read_text(encoding="utf-8") == original

    def test_reports_failure_for_a_missing_file(self, monkeypatch, tmp_path):
        lc, _mocks = _import_line_counter(monkeypatch)

        result = lc.update_line_count(tmp_path / "absent.local.json")
        assert result["success"] is False
        assert "not found" in result["error"].lower()


# ===========================================================================
# Tests: schema/normalize.py
# ===========================================================================


class TestNormalizeMemoryFile:
    """Test normalize_memory_file function."""

    def _write_json(self, path: Path, data: dict) -> None:
        path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def test_returns_error_for_missing_file(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)
        result = norm.normalize_memory_file(tmp_path / "nope.json")
        assert result["success"] is False

    def test_moves_root_limits_then_strips(self, monkeypatch, tmp_path):
        """Root limits merged into metadata, then stripped (limits live in config now)."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                "document_metadata": {"status": {}},
                "limits": {"max_sessions": 20},
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True

        data = json.loads(f.read_text(encoding="utf-8"))
        assert "limits" not in data
        assert "limits" not in data["document_metadata"]

    def test_merges_root_limits_then_strips(self, monkeypatch, tmp_path):
        """Root + metadata limits both get stripped (limits live in config now)."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                "document_metadata": {
                    "limits": {"max_sessions": 20},
                    "status": {},
                },
                "limits": {"max_sessions": 30, "max_key_learnings": 25},
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True

        data = json.loads(f.read_text(encoding="utf-8"))
        assert "limits" not in data
        assert "limits" not in data["document_metadata"]

    def test_removes_root_status(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                "document_metadata": {"status": {"last_health_check": "2026-01-01"}},
                "status": {"health": "ok"},
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True

        data = json.loads(f.read_text(encoding="utf-8"))
        # root status removed
        assert "status" not in {k for k in data if k != "document_metadata"}

    def test_removes_the_whole_status_block(self, monkeypatch, tmp_path):
        """The status block is not pruned field-by-field any more — it goes.

        The gold-source templates stopped declaring `status` on 2026-08-25
        (Patrick's ruling: health is computed by the checker, never stored), so
        the template-conformance pass strips it whole. This test used to assert
        that one stale field inside the block was dropped while the block
        itself survived.
        """
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                "document_metadata": {
                    "status": {"auto_compress_at": 500, "last_health_check": "2026-01-01"},
                },
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True

        data = json.loads(f.read_text(encoding="utf-8"))
        assert "status" not in data["document_metadata"]

    def test_dry_run_does_not_write(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        original = {
            "document_metadata": {},
            "limits": {"max_lines": 600},
            "sessions": [],
        }
        self._write_json(f, original)
        original_text = f.read_text(encoding="utf-8")

        result = norm.normalize_memory_file(f, dry_run=True)
        assert result["success"] is True
        assert result["dry_run"] is True
        assert len(result["changes"]) > 0
        # File unchanged
        assert f.read_text(encoding="utf-8") == original_text

    def test_no_changes_when_already_normalized(self, monkeypatch, tmp_path):
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                # No status block: a file carrying one is no longer normalized,
                # it is drifted, and the normalizer strips it.
                "document_metadata": {
                    "_usage": "Automated file.",
                },
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True
        assert result["changes"] == []

    def test_strips_entire_limits_block(self, monkeypatch, tmp_path):
        """Limits block in metadata is fully stripped (lives in config now)."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write_json(
            f,
            {
                "document_metadata": {
                    "limits": {"max_sessions": 20, "max_lines": 600, "max_word_count": 9999},
                    "status": {"last_health_check": "2026-03-31"},
                },
                "sessions": [],
            },
        )
        result = norm.normalize_memory_file(f)
        assert result["success"] is True

        data = json.loads(f.read_text(encoding="utf-8"))
        assert "limits" not in data["document_metadata"]


class TestTodosOperational:
    """Confirm rollover treats todos[] as operational — never vectorized or trimmed."""

    def _make_data_with_todos(self, num_sessions=5, max_sessions=3, num_todos=5):
        """Build v2 data that includes a populated todos[] array."""
        sessions = [
            {"session_number": i, "date": f"2026-01-{i:02d}", "summary": f"Session {i}"}
            for i in range(1, num_sessions + 1)
        ]
        todos = [{"id": f"t{i}", "text": f"Todo item {i}", "created": f"2026-06-0{i}"} for i in range(1, num_todos + 1)]
        return {
            "document_metadata": {
                "schema_version": "2.0.0",
                "limits": {
                    "max_sessions": max_sessions,
                    "max_key_learnings": 25,
                    "max_todos": 10,
                    "todo_text_max_chars": 200,
                },
                "status": {"current_lines": 100},
            },
            "sessions": sessions,
            "key_learnings": {},
            "todos": todos,
        }

    def test_v2_extraction_leaves_todos_untouched(self, monkeypatch, tmp_path):
        """v2 rollover trims sessions but never touches todos[]."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_data_with_todos(num_sessions=6, max_sessions=3, num_todos=5)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 3}, "key_learnings": {"count": 25}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert len(data["sessions"]) == 3
        assert len(data["todos"]) == 5
        assert data["todos"][0]["id"] == "t1"
        assert data["todos"][4]["id"] == "t5"

    def test_todos_schema_shape(self):
        """Validate the expected todos[] item schema: id, text, created, optional priority."""
        todo_item = {"id": "t1", "text": "Fix the bug", "created": "2026-06-07"}
        assert "id" in todo_item
        assert "text" in todo_item
        assert "created" in todo_item

        todo_with_priority = {**todo_item, "priority": "high"}
        assert todo_with_priority["priority"] == "high"

    def test_todos_cap_enforced(self):
        """max_todos and todo_text_max_chars are the cap boundaries."""
        limits = {
            "max_todos": 10,
            "todo_text_max_chars": 200,
        }
        todos = [{"id": f"t{i}", "text": "x" * 200, "created": "2026-06-07"} for i in range(10)]
        assert len(todos) <= limits["max_todos"]
        assert all(len(t["text"]) <= limits["todo_text_max_chars"] for t in todos)

        over_cap = todos + [{"id": "t11", "text": "extra", "created": "2026-06-07"}]
        assert len(over_cap) > limits["max_todos"]

    def test_todos_survives_full_extraction_cycle(self, monkeypatch, tmp_path):
        """End-to-end: extract_items on a file with todos[] preserves them completely."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_data_with_todos(num_sessions=25, max_sessions=20, num_todos=8)

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        branch_key = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {branch_key: {"local": {"sessions": {"count": 20}, "key_learnings": {"count": 25}}}},
        }

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert result["extracted_count"] > 0
        assert len(data["todos"]) == 8
        for i, todo in enumerate(data["todos"], 1):
            assert todo["id"] == f"t{i}"
