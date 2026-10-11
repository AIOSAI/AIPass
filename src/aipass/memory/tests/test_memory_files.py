# =================== AIPass ====================
# Name: test_memory_files.py
# Description: Tests for memory_files.py, the memory file safe I/O handler
# Version: 1.3.0
# Created: 2026-03-24
# Modified: 2026-10-10
# =============================================

"""Tests for apps/handlers/json/memory_files.py."""

# ---------------------------------------------------------------------------
# update_metadata — REMOVED 2026-08-25
# ---------------------------------------------------------------------------
# Its eight tests went with it. The function's only job was writing
# `document_metadata.status.<field>`, and the owner's ruling deleted the status
# block from the trinity standard: health is computed by the checker at run
# time, never stored. Its one production caller (line_counter.update_line_count)
# stamped a health date through it; nothing else in the fleet imported it.
# Keeping a generic writer for a block the standard forbids would leave the
# next agent a sanctioned-looking way to recreate the drift.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — read_memory_file() and write_memory_file(), tests/test_changed_entries.py
# seedgo: no-test-needed(covered_elsewhere) — violation_line(), read_memory_file_data(): tests/test_changed_entries.py
# seedgo: no-test-needed(covered_elsewhere) — write_memory_file_simple(), pinned in tests/test_handlers.py

import pytest

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
