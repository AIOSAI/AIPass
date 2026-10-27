# =================== AIPass ====================
# Name: tests/test_orchestrator_exec.py
# Description: Tests for the orchestrator execute_rollover pipeline
# Version: 1.1.0
# Created: 2026-04-26
# Modified: 2026-10-26
# Category: memory/tests
# =============================================

"""Tests for apps/handlers/rollover/orchestrator.py."""

# Tests for orchestrator execute_rollover pipeline -- line coverage.
#
# Covers: from aipass.memory.apps.handlers.rollover.orchestrator import execute_rollover

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — what @trigger does with the rollover_complete event trigger.fire sends
# seedgo: no-test-needed(covered_elsewhere) — the stats update_central writes, in tests/test_central_writer.py
# seedgo: no-test-needed(covered_elsewhere) — the pool run process_memory_pool does, in tests/test_intake.py

import json
import subprocess
import sys
import types
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.rollover import orchestrator
from aipass.trigger.apps.modules import core as trigger_core

# The real lookup, held before any test replaces it at orchestrator's name.
_REAL_LOCAL_CHROMA_PATH = orchestrator.get_branch_local_chroma_path
_REAL_EXTRACTOR = orchestrator.extractor

# The post-rollover chain imports these by name at call time, through
# sys.modules; a dotted target patches whatever module sys.modules holds then.
_CENTRAL_UPDATE = "aipass.memory.apps.handlers.central_writer.update_central"
_POOL_PROCESS = "aipass.memory.apps.handlers.intake.pool_processor.process_memory_pool"


def _stub_the_bus(monkeypatch, recorder):
    """Stand the recorder's two fire doors on the real trigger core: the instance and the class.

    The fire imports ``trigger`` at call time, through sys.modules, where the
    conftest's autouse fixture stands a whole mock module (conftest line HELD
    with the large graphs). So the real core imported at the top is registered
    there for the test and its two doors are replaced: the published instance
    and the class form, which reaches the same bus.
    """
    monkeypatch.setitem(sys.modules, trigger_core.__name__, trigger_core)
    monkeypatch.setattr(trigger_core, "trigger", recorder.trigger)
    monkeypatch.setattr(trigger_core.Trigger, "fire", recorder.Trigger.fire)


# ---------------------------------------------------------------------------
# Helper: import orchestrator with mocked infrastructure
# ---------------------------------------------------------------------------


def _import_orchestrator(monkeypatch):
    """Patch orchestrator's handler dependencies at the edge; return it and the mocks."""
    mock_detector = MagicMock()
    mock_detector._read_registry = MagicMock(return_value=[])
    mock_detector.check_all_branches = MagicMock(return_value={"success": True, "triggers": []})

    mock_extractor = MagicMock()

    monkeypatch.setattr(orchestrator, "detector", mock_detector)
    monkeypatch.setattr(orchestrator, "extractor", mock_extractor)
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


class TestExecuteRolloverExtraction:
    """Tests for the extraction phase."""

    def test_extract_fails(self, monkeypatch, tmp_path):
        """Extraction failure fails the trigger; nothing is trimmed."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": False,
            "error": "parse error",
        }

        result = orch.execute_rollover()
        assert len(result["failed"]) == 1
        assert result["failed"][0]["stage"] == "extraction"
        mocks["extractor"].commit_trimmed.assert_not_called()

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
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "data"}],
            "branch": "",
            "type": "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
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
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "memory item"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
        }
        return trigger

    def test_embed_fails(self, monkeypatch, tmp_path):
        """Embedding failure fails the trigger; nothing is trimmed."""
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
        mocks["extractor"].commit_trimmed.assert_not_called()

    def test_no_embeddings_returned_fails(self, monkeypatch, tmp_path):
        """Embed succeeds but returns empty embeddings — the trigger fails, nothing is trimmed."""
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
        mocks["extractor"].commit_trimmed.assert_not_called()


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
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "item", "_metadata": {"source": "test"}, "timestamp": "2026-01-01"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
        }

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
        mocks["extractor"].commit_trimmed.return_value = {"success": True, "new_lines": 50}

        result = orch.execute_rollover()
        assert result["success_count"] == 1
        assert call_count["n"] == 2  # both local and global called

    def test_global_storage_fails(self, monkeypatch, tmp_path):
        """Global storage failure fails the trigger; the file is never trimmed -- CRITICAL path."""
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
        mocks["extractor"].commit_trimmed.assert_not_called()


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
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "mem", "_metadata": {"src": "t"}, "timestamp": "2026-01-01"}],
            "branch": trigger.branch or "TEST",
            "type": trigger.memory_type or "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
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
        mocks["extractor"].commit_trimmed.return_value = {"success": True, "new_lines": 50}
        return trigger

    def test_full_success_pipeline(self, monkeypatch, tmp_path):
        """Complete success: extract, embed, store global, trim."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        # Mock post-rollover imports so they don't error
        mock_trigger_core = MagicMock()
        _stub_the_bus(monkeypatch, mock_trigger_core)
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
        mocks["extractor"].commit_trimmed.assert_called_once()

    def test_a_registry_that_turns_unreadable_after_the_check_never_strands_the_entries(self, monkeypatch, tmp_path):
        """The file is already trimmed when the local store's path is looked up; the global store still takes it.

        Leg 3b of DPLAN-0354: the registry read raises RegistryUnreadable since
        leg 3, and at this step that raise left the file trimmed with its
        entries in neither store. The local store is the second store.
        """
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)
        monkeypatch.setattr(orch, "get_branch_local_chroma_path", _REAL_LOCAL_CHROMA_PATH)
        registry = tmp_path / "AIPASS_REGISTRY.json"
        mocks["detector"]._read_registry.side_effect = detector.RegistryUnreadable(f"Unreadable registry {registry}: x")
        stored = []
        monkeypatch.setattr(orch, "store_vectors_subprocess", lambda **kw: stored.append(kw) or {"success": True})

        result = orch.execute_rollover()

        assert result["success_count"] == 1
        assert [call.get("db_path") for call in stored] == [None]
        assert any(str(registry) in c.args[0] for c in orch.logger.error.call_args_list)

    def test_post_rollover_trigger_fires(self, monkeypatch, tmp_path):
        """After success, the event goes through the published door, the instance ``trigger``."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        mock_trigger_bus = MagicMock()
        mock_trigger_mod.trigger = mock_trigger_bus
        _stub_the_bus(monkeypatch, mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        orch.execute_rollover()
        # Mutant: success_count dropped from the rollover_complete payload — killed.
        mock_trigger_bus.fire.assert_called_once_with(
            "rollover_complete", triggers_count=1, success_count=1, failed_count=0
        )
        mock_trigger_mod.Trigger.fire.assert_not_called()

    def test_post_rollover_central_update(self, monkeypatch, tmp_path):
        """After success, central_writer.update_central is called."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        _stub_the_bus(monkeypatch, mock_trigger_mod)
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
        _stub_the_bus(monkeypatch, mock_trigger_mod)
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
        """trigger.fire raises but does not crash the pipeline."""
        orch, mocks = _import_orchestrator(monkeypatch)
        self._setup_full_success(monkeypatch, tmp_path, orch, mocks)

        mock_trigger_mod = MagicMock()
        mock_trigger_mod.trigger.fire.side_effect = ImportError("trigger missing")
        _stub_the_bus(monkeypatch, mock_trigger_mod)
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
        _stub_the_bus(monkeypatch, mock_trigger_mod)
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
        """Two triggers: one succeeds, one fails at extraction."""
        orch, mocks = _import_orchestrator(monkeypatch)

        trigger_ok = _make_trigger(tmp_path, branch="GOOD")
        trigger_bad = _make_trigger(tmp_path, branch="BAD")

        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger_ok, trigger_bad],
        }

        def fake_extract(fp):
            """Fail for BAD branch, succeed for others."""
            if "BAD" in str(fp):
                return {"success": False, "error": "parse error"}
            return {
                "success": True,
                "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
                "branch": "GOOD",
                "type": "sessions",
                "old_lines": 80,
                "trimmed": {"sessions": []},
            }

        mocks["extractor"].extract_with_metadata.side_effect = fake_extract

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
        mocks["extractor"].commit_trimmed.return_value = {"success": True, "new_lines": 50}

        # Mock post-rollover chain (success_count > 0 triggers it)
        mock_trigger_mod = MagicMock()
        _stub_the_bus(monkeypatch, mock_trigger_mod)
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

    def test_a_refused_trim_after_storage_fails_the_trigger(self, monkeypatch, tmp_path):
        """Vectors stored, file whole: the trigger fails at the commit stage and the next run retries it."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
            "branch": "TEST",
            "type": "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
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
        mocks["extractor"].commit_trimmed.return_value = {"success": False, "error": "permission denied"}

        # Mock post-rollover chain
        mock_trigger_mod = MagicMock()
        _stub_the_bus(monkeypatch, mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is False
        assert result["success_count"] == 0
        assert result["failed"][0]["stage"] == "commit"

    def test_local_storage_with_path(self, monkeypatch, tmp_path):
        """Local chroma path exists and local storage succeeds."""
        orch, mocks = _import_orchestrator(monkeypatch)
        trigger = _make_trigger(tmp_path)
        mocks["detector"].check_all_branches.return_value = {
            "success": True,
            "triggers": [trigger],
        }
        mocks["extractor"].extract_with_metadata.return_value = {
            "success": True,
            "entries": [{"text": "m", "_metadata": {}, "timestamp": "2026-01-01"}],
            "branch": "TEST",
            "type": "sessions",
            "old_lines": 100,
            "trimmed": {"sessions": []},
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
        mocks["extractor"].commit_trimmed.return_value = {"success": True, "new_lines": 50}

        # Mock post-rollover chain
        mock_trigger_mod = MagicMock()
        _stub_the_bus(monkeypatch, mock_trigger_mod)
        mock_central = MagicMock()
        mock_central.update_central = MagicMock(return_value={"success": True})
        monkeypatch.setattr(_CENTRAL_UPDATE, mock_central.update_central)
        mock_pool = MagicMock()
        mock_pool.process_memory_pool = MagicMock(return_value={"files_processed": 0})
        monkeypatch.setattr(_POOL_PROCESS, mock_pool.process_memory_pool)

        result = orch.execute_rollover()
        assert result["success"] is True
        assert result["results"][0]["local_stored"] is True


class TestTheEmbedRefusalNamesItsCause:
    """A rollover's embed refusal carries the embedder's reason, not a bare word (leg 9)."""

    def test_an_embedder_refusal_names_its_cause(self):
        """The embedder's real refusal: exit 1, its reason as JSON on stdout, stderr empty."""
        refused = MagicMock()
        refused.returncode = 1
        refused.stdout = json.dumps({"success": False, "error": "inhomogeneous shape"})
        refused.stderr = ""

        with patch.object(subprocess, "run", return_value=refused):
            result = orchestrator.encode_batch_subprocess(["a long entry", "short"])

        assert result == {"success": False, "error": "Embedding failed (exit 1): inhomogeneous shape"}


class TestAnEditDuringStorageSurvivesTheTrim:
    """The 2026-10-26 12:16 loss: a todo added while the rollover stored vectors was gone after the trim."""

    def test_a_todo_added_between_extract_and_trim_survives_and_only_the_archived_session_leaves(
        self, monkeypatch, tmp_path
    ):
        ext = _REAL_EXTRACTOR
        assert isinstance(ext.write_memory_file_simple, types.FunctionType), "extractor bound to a mocked writer"
        rollover_cfg = {"defaults": {"local": {"sessions": {"count": 10}}}, "per_branch": {}}
        monkeypatch.setattr(ext, "config_loader", SimpleNamespace(section=lambda name: rollover_cfg))

        local = tmp_path / "standin" / ".trinity" / "local.json"
        local.parent.mkdir(parents=True)
        pad = [381, 379, 374, 369, 363, 361, 360, 359, 355]
        local.write_text(
            json.dumps(
                {
                    "document_metadata": {"document_type": "session_history", "schema_version": "3.0.0"},
                    "todos_meta": "pad of 10 - next #385",
                    "todos": [{"number": n, "date": "2026-10-01", "task": f"task {n}"} for n in pad],
                    "sessions": [
                        {"number": n, "date": "2026-10-01", "summary": f"session {n}", "status": "completed"}
                        for n in range(734, 723, -1)
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        def the_edit_lands_while_storing(**kwargs):
            data = json.loads(local.read_text(encoding="utf-8"))
            data["todos"].insert(0, {"number": 385, "date": "2026-10-26", "task": "task 385"})
            data["todos_meta"] = "pad of 10 - next #386"
            local.write_text(json.dumps(data, indent=2), encoding="utf-8")
            return {"success": True, "collection": "c", "total_vectors": 1}

        trigger = MagicMock(file_path=local, branch="STANDIN", memory_type="local")
        monkeypatch.setattr(
            orchestrator, "detector", MagicMock(check_all_branches=lambda: {"success": True, "triggers": [trigger]})
        )
        monkeypatch.setattr(
            orchestrator, "encode_batch_subprocess", lambda texts: {"success": True, "embeddings": [[0.1]]}
        )
        no_local_store = MagicMock(return_value=None)
        monkeypatch.setattr(orchestrator, "get_branch_local_chroma_path", no_local_store)
        monkeypatch.setattr(orchestrator, "store_vectors_subprocess", the_edit_lands_while_storing)
        monkeypatch.setattr(_CENTRAL_UPDATE, MagicMock(return_value={"success": True}))
        monkeypatch.setattr(_POOL_PROCESS, MagicMock(return_value={"files_processed": 0}))
        _stub_the_bus(monkeypatch, MagicMock())

        result = orchestrator.execute_rollover()

        after = json.loads(local.read_text(encoding="utf-8"))
        assert result["success_count"] == 1, result
        assert [t["number"] for t in after["todos"]] == [385, *pad]
        assert after["todos_meta"] == "pad of 10 - next #386"
        assert [s["number"] for s in after["sessions"]] == list(range(734, 724, -1))
        no_local_store.assert_called_once_with("STANDIN")
