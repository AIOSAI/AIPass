# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_unified_schema.py
# Date: 2026-06-13
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""
Tests for FPLAN-0272: unified entry schema changes.

Covers:
  - normalize.py: number-sort self-heal guardrail (sort, skip, no-op)
  - extractor.py: key_learnings list trimming (oldest from end, under-limit skip)
  - entry_limits.py: list-kind key_learnings char-limit enforcement via changed_entries
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------


def _import_normalize(monkeypatch):
    """Import normalize with mocked infrastructure dependencies."""
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    json_pkg = MagicMock()
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


@pytest.fixture(autouse=True)
def _fresh_entry_limits_modules(monkeypatch):
    """Drop cached entry_limits modules so each test gets fresh imports."""
    sys.modules.pop("aipass.memory.apps.handlers.json", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.json_handler", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.config_loader", None)
    sys.modules.pop("aipass.memory.apps.handlers.json.entry_limits", None)
    yield


def _get_entry_limits():
    """Import and return the entry_limits module."""
    return importlib.import_module("aipass.memory.apps.handlers.json.entry_limits")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


# ===========================================================================
# 1. Normalizer: number-sort self-heal guardrail
# ===========================================================================


class TestNormalizerNumberSort:
    """Tests for the number-sort normalizer in normalize.py."""

    def test_sorts_entries_by_number_descending(self, monkeypatch, tmp_path):
        """Feed out-of-order entries with number fields -> verify re-sorted newest-first."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        _write_json(
            f,
            {
                "document_metadata": {
                    "status": {"last_health_check": "2026-06-13"},
                },
                "sessions": [
                    {"number": 2, "date": "2026-01-02", "summary": "Second"},
                    {"number": 5, "date": "2026-01-05", "summary": "Fifth"},
                    {"number": 1, "date": "2026-01-01", "summary": "First"},
                    {"number": 4, "date": "2026-01-04", "summary": "Fourth"},
                    {"number": 3, "date": "2026-01-03", "summary": "Third"},
                ],
            },
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        data = json.loads(f.read_text(encoding="utf-8"))
        numbers = [e["number"] for e in data["sessions"]]
        assert numbers == [5, 4, 3, 2, 1], f"Expected descending order, got {numbers}"
        assert any("re-sorted" in c for c in result["changes"])

    def test_skips_sort_when_no_numbers(self, monkeypatch, tmp_path):
        """Entries without number field -> no sort applied."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        original_sessions = [
            {"date": "2026-01-03", "summary": "Third"},
            {"date": "2026-01-01", "summary": "First"},
            {"date": "2026-01-02", "summary": "Second"},
        ]
        _write_json(
            f,
            {
                "document_metadata": {
                    "status": {"last_health_check": "2026-06-13"},
                },
                "sessions": original_sessions,
            },
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        data = json.loads(f.read_text(encoding="utf-8"))
        # Order should be unchanged since no number fields exist
        summaries = [e["summary"] for e in data["sessions"]]
        assert summaries == ["Third", "First", "Second"]
        assert not any("re-sorted" in c for c in result["changes"])

    def test_no_change_when_already_sorted(self, monkeypatch, tmp_path):
        """Already-sorted entries (descending by number) -> no changes reported."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        _write_json(
            f,
            {
                "document_metadata": {
                    # No status block: the gold-source templates stopped declaring one on
                    # 2026-08-25, so a file carrying one is drifted and gets it
                    # stripped — which is a change, and these tests assert none.
                },
                "sessions": [
                    {"number": 5, "date": "2026-01-05", "summary": "Fifth"},
                    {"number": 4, "date": "2026-01-04", "summary": "Fourth"},
                    {"number": 3, "date": "2026-01-03", "summary": "Third"},
                    {"number": 2, "date": "2026-01-02", "summary": "Second"},
                    {"number": 1, "date": "2026-01-01", "summary": "First"},
                ],
            },
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        assert result["changes"] == []


class TestNormalizerUnsortableEntries:
    """GH #728 — the newest-first guardrail must never fail open silently.

    One entry with an unusable 'number' used to disable the re-sort for the
    whole container with no log line and no changes record; repairing only
    that entry then crashed sorted() on a sibling whose number was a string.
    """

    @staticmethod
    def _write(f: Path, sessions: list) -> None:
        _write_json(
            f,
            {
                # No status block — stripped by the template-conformance pass
                # since 2026-08-25; see test_trinity_standard.py.
                "document_metadata": {},
                "sessions": sessions,
            },
        )

    def test_numbered_entries_still_sort_around_an_unsortable_row(self, monkeypatch, tmp_path):
        """One entry without 'number' must not forfeit protection for the good rows."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
                {"date": "2026-01-09", "summary": "NO NUMBER"},
                {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
                {"number": 5, "date": "2026-01-05", "summary": "Fifth"},
            ],
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        sessions = json.loads(f.read_text(encoding="utf-8"))["sessions"]
        # Unsortable row keeps its exact index; numbered rows fill the slots they held.
        assert sessions[1]["summary"] == "NO NUMBER"
        assert [e.get("number") for e in sessions] == [9, None, 5, 2]
        assert any("re-sorted" in c for c in result["changes"])

    def test_unsortable_row_is_reported_in_the_result(self, monkeypatch, tmp_path):
        """The skip must be recorded — container name and offending index."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
                {"date": "2026-01-05", "summary": "NO NUMBER"},
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
            ],
        )

        result = norm.normalize_memory_file(f)

        warnings = result["warnings"]
        assert len(warnings) == 1
        assert "sessions" in warnings[0]
        assert "[1]" in warnings[0]

    def test_unsortable_row_is_logged_at_warning(self, monkeypatch, tmp_path):
        """Operators get a log line — a guardrail that declines to run says so."""
        norm, _ = _import_normalize(monkeypatch)
        mock_logger = MagicMock()
        monkeypatch.setattr(norm, "logger", mock_logger)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
                {"date": "2026-01-05", "summary": "NO NUMBER"},
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
            ],
        )

        norm.normalize_memory_file(f)

        assert mock_logger.warning.called
        logged = " ".join(str(call) for call in mock_logger.warning.call_args_list)
        assert "sessions" in logged

    def test_string_number_does_not_crash_and_is_repaired(self, monkeypatch, tmp_path):
        """The half-repaired container from the issue: 'number' as a string."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
                {"number": "9", "date": "2026-01-09", "summary": "Ninth"},
                {"number": 5, "date": "2026-01-05", "summary": "Fifth"},
            ],
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        sessions = json.loads(f.read_text(encoding="utf-8"))["sessions"]
        assert [e["number"] for e in sessions] == [9, 5, 2]
        assert all(isinstance(e["number"], int) for e in sessions)
        assert any("repaired" in c for c in result["changes"])

    def test_both_defects_together_is_the_real_world_case(self, monkeypatch, tmp_path):
        """One string number AND one missing key — the file that prompted #728."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
                {"date": "2026-01-04", "summary": "NO NUMBER"},
                {"number": "9", "date": "2026-01-09", "summary": "Ninth"},
            ],
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        sessions = json.loads(f.read_text(encoding="utf-8"))["sessions"]
        assert [e.get("number") for e in sessions] == [9, None, 2]
        assert result["warnings"]

    def test_non_dict_entry_is_tolerated_not_fatal(self, monkeypatch, tmp_path):
        """A stray scalar in the list must not crash the normalize path."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 2, "date": "2026-01-02", "summary": "Second"},
                "corrupt-scalar",
                {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
            ],
        )

        result = norm.normalize_memory_file(f)

        assert result["success"] is True
        sessions = json.loads(f.read_text(encoding="utf-8"))["sessions"]
        assert sessions[1] == "corrupt-scalar"
        assert [e.get("number") for e in sessions if isinstance(e, dict)] == [9, 2]
        assert result["warnings"]

    def test_container_without_any_numbers_stays_silent(self, monkeypatch, tmp_path):
        """todos carry no numbers by design — that shape must not warn."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        _write_json(
            f,
            {
                "document_metadata": {"status": {"last_health_check": "2026-08-12"}},
                "todos": [
                    {"task": "Second thing", "status": "open"},
                    {"task": "First thing", "status": "open"},
                ],
            },
        )

        result = norm.normalize_memory_file(f)

        assert result["warnings"] == []
        assert not any("re-sorted" in c for c in result["changes"])

    def test_warning_alone_does_not_rewrite_the_file(self, monkeypatch, tmp_path):
        """Reporting is not a mutation — a correctly ordered file is left byte-identical."""
        norm, _ = _import_normalize(monkeypatch)
        f = tmp_path / "test.local.json"
        self._write(
            f,
            [
                {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
                {"number": 5, "date": "2026-01-05", "summary": "Fifth"},
                {"date": "2026-01-02", "summary": "NO NUMBER"},
            ],
        )
        before = f.read_text(encoding="utf-8")

        result = norm.normalize_memory_file(f)

        assert result["warnings"]
        assert result["changes"] == []
        assert f.read_text(encoding="utf-8") == before

    def test_number_reader_accepts_only_real_entry_numbers(self, monkeypatch):
        """Pin the readable/unreadable boundary — bools and odd digits are not numbers."""
        norm, _ = _import_normalize(monkeypatch)

        readable = {3: 3, "9": 9, " 12 ": 12, "-4": -4, 1.0: 1}
        for value, expected in readable.items():
            assert norm._read_entry_number({"number": value}) == expected, value

        for value in (True, False, None, 1.5, "1.5", "nine", "12a", "", "²", {"x": 1}):
            assert norm._read_entry_number({"number": value}) is None, value

        assert norm._read_entry_number({}) is None
        assert norm._read_entry_number("corrupt-scalar") is None

    def test_all_files_run_counts_warned_files(self, monkeypatch, tmp_path):
        """normalize_all surfaces warned files instead of reporting clean."""
        norm, _ = _import_normalize(monkeypatch)
        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()
        _write_json(
            branch_dir / "BRANCH.local.json",
            {
                "document_metadata": {"status": {"last_health_check": "2026-08-12"}},
                "sessions": [
                    {"number": 9, "date": "2026-01-09", "summary": "Ninth"},
                    {"date": "2026-01-05", "summary": "NO NUMBER"},
                    {"number": 2, "date": "2026-01-02", "summary": "Second"},
                ],
            },
        )
        registry_path = tmp_path / "AIPASS_REGISTRY.json"
        registry_path.write_text(
            json.dumps({"branches": [{"name": "BRANCH", "path": str(branch_dir)}]}), encoding="utf-8"
        )

        with patch.object(norm, "_find_repo_root", return_value=tmp_path):
            result = norm.normalize_all_memory_files()

        assert result["files_with_warnings"] == 1
        assert result["details"][0]["warnings"]


# ===========================================================================
# 2. Extractor: key_learnings list trimming
# ===========================================================================


class TestExtractorKeyLearningsList:
    """Tests for key_learnings list extraction in extractor.py."""

    def _make_kl_data(self, num_kl: int, max_kl: int) -> dict[str, Any]:
        """Build v2 memory data with key_learnings as a list (newest-first by number)."""
        key_learnings = [
            {
                "number": num_kl - i,
                "date": f"2026-01-{(i + 1):02d}",
                "key": f"learning_{num_kl - i}",
                "value": f"value_{num_kl - i}",
            }
            for i in range(num_kl)
        ]
        return {
            "document_metadata": {
                "schema_version": "2.0.0",
                "limits": {
                    "max_sessions": 100,
                    "max_key_learnings": max_kl,
                },
                "status": {"current_lines": 100},
            },
            "sessions": [],
            "key_learnings": key_learnings,
        }

    def test_kl_list_trims_oldest_from_end(self, monkeypatch, tmp_path):
        """List with 5 key_learnings, max 3 -> extracts 2 oldest (lowest numbers at end), keeps 3 newest."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_kl_data(num_kl=5, max_kl=3)

        branch_name = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_name: {
                    "local": {"sessions": {"count": 100}, "key_learnings": {"count": 3}},
                },
            },
        }

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        def fake_write(fp, d):
            """Write JSON data to file, bypassing mocked memory_files."""
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert result["extracted_count"] == 2

        # Kept entries: the first 3 (newest, highest numbers)
        kept_numbers = [e["number"] for e in data["key_learnings"]]
        assert kept_numbers == [5, 4, 3]

        # Extracted entries: the last 2 (oldest, lowest numbers)
        extracted_numbers = [e["number"] for e in result["extracted"]]
        assert extracted_numbers == [2, 1]

    def test_kl_list_under_limit_no_trim(self, monkeypatch, tmp_path):
        """List with 2 key_learnings, max 5 -> skipped, no extraction."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_kl_data(num_kl=2, max_kl=5)

        branch_name = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {},
            "per_branch": {
                branch_name: {
                    "local": {"sessions": {"count": 100}, "key_learnings": {"count": 5}},
                },
            },
        }

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert result.get("skipped") is True
        # All entries should still be present
        assert len(data["key_learnings"]) == 2

    def test_falls_back_to_defaults_when_branch_has_no_per_branch_entry(self, monkeypatch, tmp_path):
        """Regression: per_branch-only lookup made rollover a silent no-op.

        With config carrying defaults but no per_branch entry for this branch,
        the extract_items gate passes on defaults — so _extract_items_v2 must
        read the same defaults, or it archives nothing and reports success.
        """
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_kl_data(num_kl=5, max_kl=3)

        mocks["config_loader"].section.return_value = {
            "defaults": {
                "local": {"sessions": {"count": 100}, "key_learnings": {"count": 3}},
            },
            "per_branch": {},
        }

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        assert result["success"] is True
        assert result.get("skipped") is not True
        assert result["extracted_count"] == 2
        assert [e["number"] for e in result["extracted"]] == [2, 1]
        assert [e["number"] for e in data["key_learnings"]] == [5, 4, 3]

    def test_per_branch_entry_still_wins_over_defaults(self, monkeypatch, tmp_path):
        """The defaults fallback must not shadow a real per-branch override."""
        ext, mocks = _import_extractor(monkeypatch)
        data = self._make_kl_data(num_kl=5, max_kl=4)

        branch_name = tmp_path.name.lower()
        mocks["config_loader"].section.return_value = {
            "defaults": {
                "local": {"sessions": {"count": 100}, "key_learnings": {"count": 1}},
            },
            "per_branch": {
                branch_name: {
                    "local": {"sessions": {"count": 100}, "key_learnings": {"count": 4}},
                },
            },
        }

        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True)
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        with patch.object(ext, "_write_memory_file", side_effect=fake_write):
            result = ext._extract_items_v2(mem_file, data)

        # keep 4 (per_branch), not 1 (defaults)
        assert result["extracted_count"] == 1
        assert [e["number"] for e in data["key_learnings"]] == [5, 4, 3, 2]


class TestExtractWithMetadataEntryIdentity:
    """extract_with_metadata must carry each entry's own number/date into
    _metadata, which becomes the ChromaDB metadata for the archived vector.

    Without it, an archived entry can only be matched on exact text — which
    stops working as soon as two entries share wording, and makes renumbering
    a recovered entry guesswork.
    """

    def _run(self, ext, tmp_path, sessions):
        mem_file = tmp_path / ".trinity" / "local.json"
        mem_file.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "document_metadata": {"schema_version": "3.0.0", "status": {"current_lines": 100}},
            "todos": [],
            "key_learnings": [],
            "sessions": sessions,
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        def fake_write(fp, d):
            fp.write_text(json.dumps(d, indent=2), encoding="utf-8")

        def fake_read(fp):
            return json.loads(fp.read_text(encoding="utf-8"))

        with (
            patch.object(ext, "_write_memory_file", side_effect=fake_write),
            patch.object(ext, "_read_memory_file", side_effect=fake_read),
        ):
            return ext.extract_with_metadata(mem_file)

    def _sessions(self, count, **overrides):
        out = []
        for i in range(count):
            n = count - i
            entry = {
                "number": n,
                "date": f"2026-01-{(count - i):02d}",
                "summary": f"summary {n}",
                "status": "completed",
            }
            if n <= overrides.get("apply_to_below", 0):
                entry.update(overrides.get("patch", {}))
            out.append(entry)
        return out

    def test_entry_number_and_date_land_in_metadata(self, monkeypatch, tmp_path):
        ext, mocks = _import_extractor(monkeypatch)
        mocks["config_loader"].section.return_value = {
            "defaults": {"local": {"sessions": {"count": 2}}},
            "per_branch": {},
        }

        result = self._run(ext, tmp_path, self._sessions(4))

        assert result["success"] is True
        assert result["count"] == 2
        archived = {e["_metadata"]["entry_number"]: e["_metadata"] for e in result["entries"]}
        assert sorted(archived) == [1, 2]
        assert archived[1]["entry_date"] == "2026-01-01"
        assert archived[2]["entry_date"] == "2026-01-02"
        # existing metadata must survive untouched
        assert archived[1]["type"] == "local"
        assert archived[1]["source_file"] == "local.json"

    def test_missing_number_or_date_is_omitted_not_none(self, monkeypatch, tmp_path):
        """ChromaDB rejects None metadata values — absent keys must stay absent."""
        ext, mocks = _import_extractor(monkeypatch)
        mocks["config_loader"].section.return_value = {
            "defaults": {"local": {"sessions": {"count": 2}}},
            "per_branch": {},
        }

        sessions = self._sessions(4)
        # strip identity off the two oldest (the ones that get archived)
        sessions[-1].pop("date")
        sessions[-2].pop("number")

        result = self._run(ext, tmp_path, sessions)

        assert result["count"] == 2
        for entry in result["entries"]:
            meta = entry["_metadata"]
            assert "entry_number" not in meta or isinstance(meta["entry_number"], int)
            assert "entry_date" not in meta or isinstance(meta["entry_date"], str)
            assert None not in meta.values()


# ===========================================================================
# 3. Entry limits: list-kind key_learnings char-limit enforcement
# ===========================================================================


class TestListKeyLearningCharLimit:
    """Tests for key_learnings as kind='list' in changed_entries."""

    def test_list_key_learning_over_char_limit(self):
        """changed_entries with a new key_learning entry where value exceeds 200 chars -> violation."""
        mod = _get_entry_limits()

        # key_learnings as a list with kind="list"
        limits: dict[str, Any] = {
            "enabled": True,
            "enforce": False,
            "entry_types": {
                "key_learnings": {
                    "file": "local.json",
                    "container": "key_learnings",
                    "kind": "list",
                    "field": "value",
                    "max_chars": 200,
                },
            },
        }

        before: dict[str, Any] = {"key_learnings": []}
        fat_value = "x" * 250
        after: dict[str, Any] = {
            "key_learnings": [
                {"number": 1, "key": "new_learning", "value": fat_value},
            ],
        }

        result = mod.changed_entries(before, after, limits)

        assert len(result) == 1
        assert result[0]["entry_type"] == "key_learnings"
        assert result[0]["container"] == "key_learnings"
        assert result[0]["key"] == "0"
        assert result[0]["length"] == 250
        assert result[0]["cap"] == 200
        assert result[0]["over_by"] == 50


# ===========================================================================
# 4. Entry limits: casing normalization + char-cap is single source
# ===========================================================================


class TestEntryLimitsCasingAndCaps:
    """P6 — verify entry_limits normalizes branch casing and is the single cap home."""

    def test_uppercase_branch_resolves_per_branch_overrides(self):
        """load_entry_limits('DEVPULSE') should find per_branch['devpulse'] overrides."""
        mod = _get_entry_limits()

        limits: dict[str, Any] = {
            "enabled": True,
            "enforce": True,
            "entry_types": {
                "sessions": {
                    "file": "local.json",
                    "container": "sessions",
                    "kind": "list",
                    "field": "summary",
                    "max_chars": 300,
                },
            },
            "per_branch": {
                "devpulse": {"sessions": {"max_chars": 500}},
            },
        }
        with patch.object(mod.config_loader, "load", return_value={"entry_limits": limits}):
            result = mod.load_entry_limits("DEVPULSE")

        assert result["entry_types"]["sessions"]["max_chars"] == 500

    def test_mixed_case_branch_resolves(self):
        """load_entry_limits('DevPulse') should normalize to lowercase."""
        mod = _get_entry_limits()

        limits: dict[str, Any] = {
            "enabled": True,
            "enforce": False,
            "entry_types": {
                "key_learnings": {
                    "file": "local.json",
                    "container": "key_learnings",
                    "kind": "list",
                    "field": "value",
                    "max_chars": 200,
                },
            },
            "per_branch": {
                "devpulse": {"key_learnings": {"max_chars": 150}},
            },
        }
        with patch.object(mod.config_loader, "load", return_value={"entry_limits": limits}):
            result = mod.load_entry_limits("DevPulse")

        assert result["entry_types"]["key_learnings"]["max_chars"] == 150

    def test_rollover_defaults_have_no_max_chars(self):
        """rollover.defaults should only carry counts, not max_chars (P6 unification)."""
        mod = _get_entry_limits()
        default_rollover = mod.config_loader.DEFAULT_CONFIG["rollover"]["defaults"]

        for file_type, sections in default_rollover.items():
            if file_type.startswith("_"):
                continue
            for section_name, section_val in sections.items():
                assert "max_chars" not in section_val, (
                    f"rollover.defaults.{file_type}.{section_name} still has max_chars"
                )
