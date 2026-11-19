# =================== AIPass ====================
# Name: test_memory_files.py
# Description: Tests for memory_files.py, the memory file safe I/O handler
# Version: 1.3.0
# Created: 2026-03-24
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/json/memory_files.py."""

# update_metadata is gone on purpose: the trinity standard forbids a stored status block.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(covered_elsewhere) — read_memory_file() and write_memory_file(), tests/test_changed_entries.py
# sentry: no-test-needed(covered_elsewhere) — violation_line(), read_memory_file_data(): tests/test_changed_entries.py
# sentry: no-test-needed(covered_elsewhere) — write_memory_file_simple(), pinned in tests/test_handlers.py

import pytest

from aipass.memory.apps.handlers import write_fence
from aipass.memory.apps.handlers.json import memory_files
from aipass.memory.apps.handlers.json.memory_files import validate_memory_file_structure


class TestValidateMemoryFileStructure:
    def test_a_complete_header_is_accepted(self):
        data = {"document_metadata": {"document_type": "t", "document_name": "n", "version": "1.0.0"}, "sessions": []}

        assert validate_memory_file_structure(data) == (True, "")

    @pytest.mark.parametrize(
        ("data", "reason"),
        [
            ([{"document_metadata": {}}], "Data is not a dictionary"),
            ({"sessions": []}, "Missing 'document_metadata' field"),
            ({"document_metadata": ["document_type"]}, "'document_metadata' is not a dictionary"),
            ({"document_metadata": {"document_type": "t"}}, "Missing metadata fields: document_name, version"),
        ],
    )
    def test_a_malformed_file_is_refused_with_its_reason(self, data, reason):
        assert validate_memory_file_structure(data) == (False, reason)


class TestTheEntryLimitsGateCannotBeSkipped:
    """A gate that crashed has not passed: the write is refused, the file on disk is untouched."""

    def test_a_crashing_gate_refuses_the_write(self, tmp_path, monkeypatch):
        monkeypatch.setattr(write_fence, "ROOT", tmp_path)
        target = tmp_path / "branch" / ".trinity" / "local.json"
        target.parent.mkdir(parents=True)
        target.write_text('{\n  "sessions": []\n}\n', encoding="utf-8")
        before = target.read_bytes()

        def _crash(file_path, data):
            raise RuntimeError("gate on fire")

        monkeypatch.setattr(memory_files, "_validate_entry_limits", _crash)

        result = memory_files.write_memory_file(target, {"sessions": [{"number": 1, "summary": "new"}]})

        assert result["success"] is False
        assert "entry-limits gate crashed" in result["error"] and "gate on fire" in result["error"]
        assert target.read_bytes() == before
        assert sorted(q.name for q in target.parent.iterdir()) == ["local.json"]
