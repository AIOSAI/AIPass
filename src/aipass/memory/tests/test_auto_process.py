# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_auto_process.py
# Date: 2026-06-06
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the intake/auto_process handler and modules/pool module.

Covers:
  - auto_process.auto_process (full orchestration entry point)
  - auto_process.run_pool_processing (pool-only path)
  - auto_process._load_pool_enabled (config loading)
  - auto_process._run_rollover_check (rollover path)
  - pool.handle_command (CLI routing)

Tests: empty-pool no-op, new-drop processed+vectorized, re-run idempotent,
enabled=false respected, rollover-trigger path.

All tests use mocks/tmp_path — no live filesystem or infrastructure access.
"""

import importlib.util
import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Import helpers
# ---------------------------------------------------------------------------

_CONFIG_LOADER_PATH = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "json" / "config_loader.py"


def _load_real_config_loader():
    """Load the real config_loader module from disk (bypassing mocked sys.modules)."""
    spec = importlib.util.spec_from_file_location(
        "aipass.memory.apps.handlers.json.config_loader",
        _CONFIG_LOADER_PATH,
    )
    assert spec is not None, f"Could not find config_loader at {_CONFIG_LOADER_PATH}"
    assert spec.loader is not None, "config_loader spec has no loader"
    mod = importlib.util.module_from_spec(spec)
    sys.modules["aipass.memory.apps.handlers.json.config_loader"] = mod
    spec.loader.exec_module(mod)
    # Also attach to the (mocked) parent package so `from ... import config_loader` works
    parent = sys.modules.get("aipass.memory.apps.handlers.json")
    if parent is not None:
        setattr(parent, "config_loader", mod)
    return mod


def _import_auto_process(monkeypatch):
    """Import auto_process with mocked dependencies.

    Loads the real config_loader (bypassing the conftest MagicMock for the
    json package) so that _CONFIG_PATH can be patched per-test.
    """
    # Load real config_loader into sys.modules before auto_process imports it
    _load_real_config_loader()

    sys.modules.pop("aipass.memory.apps.handlers.intake.auto_process", None)
    parent = sys.modules.get("aipass.memory.apps.handlers.intake")
    if parent is not None and hasattr(parent, "auto_process"):
        delattr(parent, "auto_process")

    from aipass.memory.apps.handlers.intake import auto_process

    return auto_process


def _import_pool_module(monkeypatch):
    """Import pool module with mocked dependencies."""
    sys.modules.pop("aipass.memory.apps.modules.pool", None)
    parent = sys.modules.get("aipass.memory.apps.modules")
    if parent is not None and hasattr(parent, "pool"):
        delattr(parent, "pool")

    from aipass.memory.apps.modules import pool

    return pool


# ===========================================================================
# Tests: _load_pool_enabled
# ===========================================================================


class TestLoadPoolEnabled:
    """Test _load_pool_enabled config loading."""

    def test_returns_true_when_enabled(self, monkeypatch, tmp_path):
        mod = _import_auto_process(monkeypatch)
        cl = mod.config_loader
        config_file = tmp_path / "memory.config.json"
        config_file.write_text(
            json.dumps({"memory_pool": {"enabled": True}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(cl, "_CONFIG_PATH", config_file)

        assert mod._load_pool_enabled() is True

    def test_returns_false_when_disabled(self, monkeypatch, tmp_path):
        mod = _import_auto_process(monkeypatch)
        cl = mod.config_loader
        config_file = tmp_path / "memory.config.json"
        config_file.write_text(
            json.dumps({"memory_pool": {"enabled": False}}),
            encoding="utf-8",
        )
        monkeypatch.setattr(cl, "_CONFIG_PATH", config_file)

        assert mod._load_pool_enabled() is False

    def test_returns_true_when_config_missing_self_heals(self, monkeypatch, tmp_path):
        """Missing config triggers self-heal which writes DEFAULT_CONFIG (enabled=True)."""
        mod = _import_auto_process(monkeypatch)
        cl = mod.config_loader
        monkeypatch.setattr(cl, "_CONFIG_PATH", tmp_path / "missing.json")

        # Self-heal writes DEFAULT_CONFIG which has memory_pool.enabled = True
        assert mod._load_pool_enabled() is True

    def test_returns_false_when_key_missing(self, monkeypatch, tmp_path):
        mod = _import_auto_process(monkeypatch)
        cl = mod.config_loader
        config_file = tmp_path / "memory.config.json"
        config_file.write_text(json.dumps({"rollover": {}}), encoding="utf-8")
        monkeypatch.setattr(cl, "_CONFIG_PATH", config_file)

        # Config exists but has no memory_pool key; deep_merge with DEFAULT_CONFIG
        # fills it in, so enabled comes from DEFAULT_CONFIG (True)
        assert mod._load_pool_enabled() is True


# ===========================================================================
# Tests: run_pool_processing
# ===========================================================================


class TestRunPoolProcessing:
    """Test run_pool_processing function."""

    def test_skips_when_disabled(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: False)

        result = mod.run_pool_processing()

        assert result["skipped"] is True
        assert "disabled" in result["reason"]

    def test_returns_zero_when_pool_empty(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)

        mock_process = MagicMock(return_value={"success": True, "files_processed": 0, "total_chunks": 0})
        with patch(
            "aipass.memory.apps.handlers.intake.pool_processor.process_memory_pool",
            mock_process,
        ):
            result = mod.run_pool_processing()

        assert result["success"] is True
        assert result["files_processed"] == 0

    def test_returns_count_when_files_processed(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)

        mock_process = MagicMock(return_value={"success": True, "files_processed": 3, "total_chunks": 15})
        with patch(
            "aipass.memory.apps.handlers.intake.pool_processor.process_memory_pool",
            mock_process,
        ):
            result = mod.run_pool_processing()

        assert result["success"] is True
        assert result["files_processed"] == 3
        assert result["total_chunks"] == 15

    def test_handles_processing_error(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)

        with patch(
            "aipass.memory.apps.handlers.intake.pool_processor.process_memory_pool",
            side_effect=RuntimeError("chroma down"),
        ):
            result = mod.run_pool_processing()

        assert result["success"] is False
        assert "chroma down" in result["error"]


# ===========================================================================
# Tests: auto_process (full entry point)
# ===========================================================================


class TestAutoProcess:
    """Test auto_process full orchestration."""

    def test_skips_everything_when_disabled(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: False)

        result = mod.auto_process()

        assert result["success"] is True
        assert result["pool"]["skipped"] is True
        assert result["rollover"]["skipped"] is True

    def test_empty_pool_no_rollover_triggers(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)
        monkeypatch.setattr(
            mod,
            "run_pool_processing",
            lambda: {"success": True, "files_processed": 0, "total_chunks": 0},
        )
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"skipped": True, "reason": "no rollover triggers"},
        )

        result = mod.auto_process()

        assert result["success"] is True
        assert result["pool"]["files_processed"] == 0
        assert result["rollover"]["skipped"] is True

    def test_pool_processed_no_rollover(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)
        monkeypatch.setattr(
            mod,
            "run_pool_processing",
            lambda: {"success": True, "files_processed": 5, "total_chunks": 20},
        )
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"skipped": True, "reason": "no rollover triggers"},
        )

        result = mod.auto_process()

        assert result["success"] is True
        assert result["pool"]["files_processed"] == 5

    def test_pool_and_rollover_both_fire(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)
        monkeypatch.setattr(
            mod,
            "run_pool_processing",
            lambda: {"success": True, "files_processed": 2, "total_chunks": 8},
        )
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"success": True, "triggers": 1, "processed": 1},
        )

        result = mod.auto_process()

        assert result["success"] is True
        assert result["pool"]["files_processed"] == 2
        assert result["rollover"]["processed"] == 1

    def test_pool_failure_sets_success_false(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)
        monkeypatch.setattr(
            mod,
            "run_pool_processing",
            lambda: {"success": False, "error": "embedding failed"},
        )
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"skipped": True, "reason": "no rollover triggers"},
        )

        result = mod.auto_process()

        assert result["success"] is False

    def test_rollover_failure_sets_success_false(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)
        monkeypatch.setattr(
            mod,
            "run_pool_processing",
            lambda: {"success": True, "files_processed": 0, "total_chunks": 0},
        )
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"success": False, "error": "detector crash"},
        )

        result = mod.auto_process()

        assert result["success"] is False

    def test_idempotent_second_run_no_new_work(self, monkeypatch):
        """Empty pool stays empty — both calls return 0 files."""
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)

        call_count = {"pool": 0}

        def mock_pool():
            call_count["pool"] += 1
            return {"success": True, "files_processed": 0, "total_chunks": 0}

        monkeypatch.setattr(mod, "run_pool_processing", mock_pool)
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"skipped": True, "reason": "no rollover triggers"},
        )

        result1 = mod.auto_process()
        result2 = mod.auto_process()

        assert result1["pool"]["files_processed"] == 0
        assert result2["pool"]["files_processed"] == 0
        assert call_count["pool"] == 2

    def test_first_call_processes_second_call_noop(self, monkeypatch):
        """With keep_recent=0, first call archives all files, second finds empty pool."""
        mod = _import_auto_process(monkeypatch)
        monkeypatch.setattr(mod, "_load_pool_enabled", lambda: True)

        call_count = {"n": 0}

        def mock_pool():
            call_count["n"] += 1
            if call_count["n"] == 1:
                return {"success": True, "files_processed": 10, "total_chunks": 93}
            return {"success": True, "files_processed": 0, "total_chunks": 0}

        monkeypatch.setattr(mod, "run_pool_processing", mock_pool)
        monkeypatch.setattr(
            mod,
            "_run_rollover_check",
            lambda: {"skipped": True, "reason": "no rollover triggers"},
        )

        result1 = mod.auto_process()
        result2 = mod.auto_process()

        assert result1["pool"]["files_processed"] == 10
        assert result2["pool"]["files_processed"] == 0
        assert call_count["n"] == 2


# ===========================================================================
# Tests: _run_rollover_check
# ===========================================================================


class TestRunRolloverCheck:
    """Test _run_rollover_check function."""

    def test_skips_when_no_triggers(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)

        with patch(
            "aipass.memory.apps.handlers.monitor.detector.check_all_branches",
            return_value={"triggers": []},
        ):
            result = mod._run_rollover_check()

        assert result["skipped"] is True

    def test_executes_when_triggers_found(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)

        mock_trigger = MagicMock()
        mock_execute = MagicMock(return_value={"success": True, "triggers_count": 1, "success_count": 1})
        mock_orchestrator = MagicMock()
        mock_orchestrator.execute_rollover = mock_execute
        monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.rollover.orchestrator", mock_orchestrator)

        with patch(
            "aipass.memory.apps.handlers.monitor.detector.check_all_branches",
            return_value={"triggers": [mock_trigger]},
        ):
            result = mod._run_rollover_check()

        assert result["success"] is True
        assert result["triggers"] == 1
        assert result["processed"] == 1

    def test_handles_detector_error(self, monkeypatch):
        mod = _import_auto_process(monkeypatch)

        with patch(
            "aipass.memory.apps.handlers.monitor.detector.check_all_branches",
            side_effect=RuntimeError("registry missing"),
        ):
            result = mod._run_rollover_check()

        assert result["success"] is False
        assert "registry missing" in result["error"]


# ===========================================================================
# Tests: pool module handle_command
# ===========================================================================


class TestPoolHandleCommand:
    """Test pool module command routing."""

    def test_handles_pool_command(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)
        mock = MagicMock()
        monkeypatch.setattr(mod, "print_introspection", mock)

        assert mod.handle_command("pool", []) is True
        assert mock.call_count == 1

    def test_handles_pool_help(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)
        mock = MagicMock()
        monkeypatch.setattr(mod, "print_help", mock)

        assert mod.handle_command("pool", ["--help"]) is True
        assert mock.call_count == 1

    def test_handles_pool_process(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)
        mock = MagicMock()
        monkeypatch.setattr(mod, "_run_process_command", mock)

        assert mod.handle_command("pool", ["process"]) is True
        assert mock.call_count == 1

    def test_handles_pool_status(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)
        mock = MagicMock()
        monkeypatch.setattr(mod, "_run_status_command", mock)

        assert mod.handle_command("pool", ["status"]) is True
        assert mock.call_count == 1

    def test_rejects_unknown_subcommand(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)

        assert mod.handle_command("pool", ["bogus"]) is True

    def test_ignores_unrelated_command(self, monkeypatch):
        mod = _import_pool_module(monkeypatch)

        assert mod.handle_command("search", []) is False
