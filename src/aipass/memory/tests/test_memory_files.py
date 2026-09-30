# =================== AIPass ====================
# Name: test_memory_files.py
# Description: Tests for memory_files.py, the memory file safe I/O handler
# Version: 1.2.2
# Created: 2026-03-24
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/json/memory_files.py."""

# Tests for memory_files.py -- Memory File Safe I/O Handler.
#
# Covers read_memory_file, write_memory_file, read_memory_file_data,
# write_memory_file_simple, and update_metadata.
#
# The module under test imports ``json_handler`` and ``get_system_logger``
# at module level.  The conftest autouse fixture mocks those via
# ``sys.modules``, but the conftest also replaces the entire
# ``aipass.memory.apps.handlers.json`` package with a MagicMock -- which
# prevents Python from resolving child modules like ``memory_files``.
#
# The fix: each test pops the cached ``memory_files`` module from
# ``sys.modules`` and re-imports, after ensuring the parent package mock
# is in place AND the real ``memory_files`` module is registered.
#
# ---------------------------------------------------------------------------
# Per-test fixture: force-reimport memory_files with fresh mocks
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
