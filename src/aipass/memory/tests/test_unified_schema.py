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
                    "status": {"last_health_check": "2026-06-13"},
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
