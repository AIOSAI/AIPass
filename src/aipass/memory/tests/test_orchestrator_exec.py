# =================== AIPass ====================
# Name: tests/test_orchestrator_exec.py
# Description: Tests for the orchestrator execute_rollover pipeline
# Version: 1.0.1
# Created: 2026-04-26
# Modified: 2026-09-27
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/rollover/orchestrator.py."""

# Tests for orchestrator execute_rollover pipeline -- line coverage.
#
# Covers: from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — what @trigger does with the rollover_complete event Trigger.fire sends
# seedgo: no-test-needed(covered_elsewhere) — the stats update_central writes, in tests/test_central_writer.py
# seedgo: no-test-needed(covered_elsewhere) — the pool run process_memory_pool does, in tests/test_intake.py

import sys
from unittest.mock import MagicMock

from aipass.memory.apps.handlers.rollover import orchestrator

# The post-rollover chain imports these by name at call time, through
# sys.modules; a dotted target patches whatever module sys.modules holds then.
_CENTRAL_UPDATE = "aipass.memory.apps.handlers.central_writer.update_central"
_POOL_PROCESS = "aipass.memory.apps.handlers.intake.pool_processor.process_memory_pool"


# ---------------------------------------------------------------------------
# Helper: import orchestrator with mocked infrastructure
# ---------------------------------------------------------------------------


def _import_orchestrator(monkeypatch):
    """Patch orchestrator's handler dependencies at the edge; return it and the mocks."""
    mock_detector = MagicMock()
    mock_detector._read_registry = MagicMock(return_value=[])
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})

    mock_extractor = MagicMock()
    mock_line_counter = MagicMock()

    monkeypatch.setattr(orchestrator, "detector", mock_detector)
    monkeypatch.setattr(orchestrator, "extractor", mock_extractor)
    monkeypatch.setattr(orchestrator, "line_counter", mock_line_counter)
    # The conftest stands mocks in for these two in sys.modules; a module
    # imported at the top of the file bound the real ones, so patch them here.
    monkeypatch.setattr(orchestrator, "logger", MagicMock())
    monkeypatch.setattr(orchestrator, "json_handler", MagicMock(log_operation=MagicMock(return_value=True)))
    # The post-rollover chain imports these at call time; unpatched, a test that
    # reaches success_count > 0 wrote the live .ai_central/MEMORY.central.json.
    monkeypatch.setattr(_CENTRAL_UPDATE, MagicMock(return_value={"success": True}))
    monkeypatch.setattr(_POOL_PROCESS, MagicMock(return_value={"files_processed": 0}))

    return orchestrator, {
        "detector": mock_detector,
        "extractor": mock_extractor,
        "line_counter": mock_line_counter,
    }


def _make_trigger(tmp_path, branch="TEST", memory_type="sessions"):
    """Build a mock trigger object with required attributes."""
    trigger = MagicMock()
    trigger.file_path = tmp_path / f"{branch}.local.json"
    trigger.branch = branch
    trigger.memory_type = memory_type
    trigger.__str__ = MagicMock(return_value=f"{branch}.local.json")
    return trigger


# ===========================================================================
# execute_rollover
# ===========================================================================


class TestExecuteRolloverCheckBranches:
    """Tests for the trigger-detection phase of execute_rollover."""

    def test_check_branches_fails(self, monkeypatch, tmp_path):
        """check_all_branches returns success=False."""
        orch, mocks = _import_orchestrator(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {
            "success": False,
            "error": "registry missing",
        }
        result = orch.execute_rollover()
        assert result["success"] is False
        assert "registry missing" in result["error"]

    def test_no_triggers(self, monkeypatch, tmp_path):
        """check_all_branches returns empty triggers list."""
        orch, mocks = _import_orchestrator(monkeypatch)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [],
        }
        result = orch.execute_rollover()
        assert result["success"] is True
        assert result["triggers_count"] == 0


class TestExecuteRolloverBackup:
    """Tests for the backup phase."""

    def test_backup_fails(self, monkeypatch, tmp_path):
        """Backup failure skips trigger and adds to failed list."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": False,
            "error": "disk full",
        }

        result = orch.execute_rollover()
        assert result["success"] is False
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "backup"


class TestExecuteRolloverExtraction:
    """Tests for the extraction phase."""

    def test_extract_fails_and_restores(self, monkeypatch, tmp_path):
        """Extraction failure triggers restore_from_backup."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "backup created",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": False,
            "error": "parse error",
        }
        mocks["extractor"].restore_from_backup.return_value = {"success": True}

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "extraction"
        mocks["extractor"].restore_from_backup.assert_called_once()

    def test_no_branch_in_result(self, monkeypatch, tmp_path):
        """Extraction succeeds but returns no branch field and trigger has empty branch."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path, branch="")
        # Also clear the trigger.branch so the fallback is empty
        trigger.branch = ""
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "data"}],
            "branch": "",
            "type": "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["error"] == "No branch in result"


class TestExecuteRolloverExtractionSkipped:
    """Tests for skipped extraction (race condition / no excess entries)."""

    def test_skipped_extraction_skips_trigger(self, monkeypatch, tmp_path):
        """Extraction returns skipped=True — trigger is skipped, not failed."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "skipped": True,
            "message": "No entries exceed v2 limits",
            "entries": [],
            "count": 0,
        }

        result = orch.execute_rollover()
        assert result["success_count"] == 0
        assert len(result["failed"]) == 0

    def test_skipped_extraction_no_embedding_attempted(self, monkeypatch, tmp_path):
        """Skipped extraction does not call encode_batch_subprocess."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "skipped": True,
            "message": "File under limit",
            "entries": [],
            "count": 0,
        }

        embed_called = {"called": False}
        original_encode = orch.encode_batch_subprocess

        def tracking_encode(texts):
            """Wrap encode to track whether it was called."""
            embed_called["called"] = True
            return original_encode(texts)

        monkeypatch.setattr(orch, "encode_batch_subprocess", tracking_encode)

        orch.execute_rollover()
        assert embed_called["called"] is False


class TestExecuteRolloverEmbedding:
    """Tests for the embedding phase."""

    def _setup_to_embedding(self, monkeypatch, tmp_path, mocks, trigger=None):
        """Set up mocks so execution reaches the embedding step."""
        if trigger is None:
            trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "memory item"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }
        mocks["extractor"].restore_from_backup.return_value = {"success": True}
        return trigger

    def test_embed_fails_and_restores(self, monkeypatch, tmp_path):
        """Embedding failure triggers restore."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_embedding(monkeypatch, tmp_path, mocks)

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": False, "error": "model load fail"},
        )

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "embedding"
        mocks["extractor"].restore_from_backup.assert_called_once()

    def test_no_embeddings_returned_restores_backup(self, monkeypatch, tmp_path):
        """Embed succeeds but returns empty embeddings — must restore from backup."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_embedding(monkeypatch, tmp_path, mocks)

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": []},
        )

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "embedding"
        assert "No embeddings" in result["failed"][0]["error"]
        mocks["extractor"].restore_from_backup.assert_called_once()

    def test_no_embeddings_restore_fails(self, monkeypatch, tmp_path):
        """Empty embeddings + restore failure — CRITICAL data loss path."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_embedding(monkeypatch, tmp_path, mocks)
        mocks["extractor"].restore_from_backup.return_value = {
            "success": False,
            "error": "backup file missing",
        }

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": []},
        )

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "embedding"
        mocks["extractor"].restore_from_backup.assert_called_once()


class TestExecuteRolloverStorage:
    """Tests for the storage phases (local + global)."""

    def _setup_to_storage(self, monkeypatch, tmp_path, orch, mocks, trigger=None):
        """Set up mocks so execution reaches the storage step."""
        if trigger is None:
            trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "item", "_metadata": {"source": "test"}, "timestamp": "2026-01-01"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }
        mocks["extractor"].restore_from_backup.return_value = {"success": True}

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": [[0.1, 0.2]]},
        )
        # Default: local chroma path not found (None)
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: None)
        return trigger

    def test_local_storage_fails_continues(self, monkeypatch, tmp_path):
        """Local chroma failure still proceeds to global storage."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_storage(monkeypatch, tmp_path, orch, mocks)

        # Enable local path so local storage is attempted
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: tmp_path / ".chroma")

        call_count = {"n": 0}

        def fake_store(**kw):
            """Simulate local failure, global success."""
            call_count["n"] += 1
            if kw.get("db_path"):
                # Local storage fails
                return {"success": False, "error": "local disk error"}
            # Global storage succeeds
            return {"success": True, "collection": "col", "total_vectors": 1}

        monkeypatch.setattr(orch, "store_vectors_subprocess", fake_store)
        mocks["line_counter"].update_line_count.return_value = {"success": True}

        result = orch.execute_rollover()
        assert result["success_count"] == 1
        assert call_count["n"] == 2  # both local and global called

    def test_global_storage_fails_and_restores(self, monkeypatch, tmp_path):
        """Global storage failure triggers restore -- CRITICAL path."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_storage(monkeypatch, tmp_path, orch, mocks)

        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": False, "error": "chroma crash"},
        )

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "global_storage"
        mocks["extractor"].restore_from_backup.assert_called_once()

    def test_global_storage_fails_restore_fails(self, monkeypatch, tmp_path):
        """Global storage fails AND restore fails -- CRITICAL logging path."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_to_storage(monkeypatch, tmp_path, orch, mocks)

        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": False, "error": "chroma crash"},
        )
        mocks["extractor"].restore_from_backup.return_value = {
            "success": False,
            "error": "backup file missing",
        }

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "global_storage"


class TestExecuteRolloverFullPipeline:
    """Tests for the full success pipeline and post-rollover chain."""

    def _setup_full_success(self, monkeypatch, tmp_path, orch, mocks, trigger=None):
        """Set up mocks for a complete successful rollover."""
        if trigger is None:
            trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "mem", "_metadata": {"src": "t"}, "timestamp": "2026-01-01"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": [[0.1]]},
        )
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: None)
        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": True, "collection": "mem_TEST", "total_vectors": 5},
        )
        mocks["line_counter"].update_line_count.return_value = {"success": True}
        return trigger

    def test_full_success_pipeline(self, monkeypatch, tmp_path):
        """Complete success: backup, extract, embed, store global, line update."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        # Mock post-rollover imports so they don't error
        mock_trigger_core = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_core)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is True
        assert result["success_count"] == 1
        assert result["triggers_count"] == 1
        assert len(result["results"]) == 1
        assert result["results"][0]["memories_count"] == 1

    def test_post_rollover_trigger_fires(self, monkeypatch, tmp_path):
        """After success, Trigger.fire is called."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        mock_trigger_cls = MagicMock()
        mock_trigger_mod.Trigger = mock_trigger_cls
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        orch.execute_rollover()
        # Mutant: success_count dropped from the rollover_complete payload — killed.
        mock_trigger_cls.fire.assert_called_once_with(
            "rollover_complete", triggers_count=1, success_count=1, failed_count=0
        )

    def test_post_rollover_central_update(self, monkeypatch, tmp_path):
        """After success, central_writer.update_central is called."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        orch.execute_rollover()
        # Mutant: the "Central stats updated" log line reworded — killed.
        mock_central.update_central.assert_called_once_with()
        orch.logger.info.assert_any_call("[rollover] Central stats updated")

    def test_post_rollover_pool_processing(self, monkeypatch, tmp_path):
        """After success, pool_processor is called."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 2})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        orch.execute_rollover()
        # Mutant: the pool's files_processed count dropped from its log line — killed.
        mock_pool.process_memory_pool.assert_called_once_with()
        orch.logger.info.assert_any_call("[rollover] Memory pool: 2 files processed")

    def test_post_rollover_trigger_exception(self, monkeypatch, tmp_path):
        """Trigger.fire raises but does not crash the pipeline."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        mock_trigger_mod.Trigger.fire.side_effect = ImportError("trigger missing")
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        # Pipeline still succeeds despite trigger error
        assert result["success"] is True

    def test_post_rollover_central_returns_none(self, monkeypatch, tmp_path):
        """central_writer.update_central returns None (warning path)."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value=None)
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is True


class TestExecuteRolloverMultiple:
    """Tests with multiple triggers."""

    def test_multiple_triggers_mixed_results(self, monkeypatch, tmp_path):
        """Two triggers: one succeeds, one fails at backup."""
        orch, mocks = _import_orchestrator(monkeypatch)

        trigger_ok = _make_trigger(tmp_path, branch="GOOD")
        trigger_bad = _make_trigger(tmp_path, branch="BAD")

        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger_ok, trigger_bad],
        }

        def fake_backup(fp):
            """Fail for BAD branch, succeed for others."""
            if "BAD" in str(fp):
                return {"success": False, "error": "disk full"}
            return {"success": True, "message": "ok"}

        mocks["extractor"].create_rollover_backup.side_effect = fake_backup
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
            "branch": "GOOD",
            "type": "sessions",
            "old_lines": 80,
            "new_lines": 40,
        }

        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": [[0.1]]},
        )
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: None)
        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": True, "collection": "c", "total_vectors": 1},
        )
        mocks["line_counter"].update_line_count.return_value = {"success": True}

        # Mock post-rollover chain (success_count > 0 triggers it)
        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is True
        assert result["success_count"] == 1
        assert result["triggers_count"] == 2
        assert len(result["failed"]) == 1

    def test_line_count_update_fails(self, monkeypatch, tmp_path):
        """Line count update failure after successful storage is non-fatal."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
            "branch": "TEST",
            "type": "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }
        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": [[0.1]]},
        )
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: None)
        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": True, "collection": "c", "total_vectors": 1},
        )
        mocks["line_counter"].update_line_count.return_value = {
            "success": False,
            "error": "permission denied",
        }

        # Mock post-rollover chain
        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        # Still succeeds -- line count is non-fatal
        assert result["success"] is True
        assert result["success_count"] == 1

    def test_local_storage_with_path(self, monkeypatch, tmp_path):
        """Local chroma path exists and local storage succeeds."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].create_rollover_backup.return_value = {
            "success": True,
            "message": "ok",
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
            "branch": "TEST",
            "type": "sessions",
            "old_lines": 100,
            "new_lines": 50,
        }
        monkeypatch.setattr(
            orch,
            "encode_batch_subprocess",
            lambda texts: {"success": True, "embeddings": [[0.1]]},
        )
        # Return a real path for local chroma
        local_chroma = tmp_path / ".chroma"
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", lambda b: local_chroma)
        monkeypatch.setattr(
            orch,
            "store_vectors_subprocess",
            lambda **kw: {"success": True, "collection": "c", "total_vectors": 1},
        )
        mocks["line_counter"].update_line_count.return_value = {"success": True}

        # Mock post-rollover chain
        mock_trigger_mod = MagicMock()
        monkeypatch.setitem(sys.modules, "aipass.trigger.apps.modules.core", mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is True
        assert result["results"][0]["local_stored"] is True


# ===========================================================================
# sync_line_counts
# ===========================================================================


class TestSyncLineCounts:
    """Tests for sync_line_counts."""

    def test_sync_success(self, monkeypatch):
        """line_counter returns success."""
        orch, mocks = _import_orchestrator(monkeypatch)
        mocks["line_counter"].update_all_memory_files.return_value = {
            "success": True,
            "updated": 5,
            "failed": 0,
        }
        result = orch.sync_line_counts()
        assert result["success"] is True
        assert result["updated"] == 5

    def test_sync_failure(self, monkeypatch):
        """line_counter returns failure."""
        orch, mocks = _import_orchestrator(monkeypatch)
        mocks["line_counter"].update_all_memory_files.return_value = {
            "success": False,
            "updated": 0,
            "failed": 3,
        }
        result = orch.sync_line_counts()
        assert result["success"] is False
