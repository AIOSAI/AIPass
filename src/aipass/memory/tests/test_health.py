# =================== AIPass ====================
# Name: test_health.py
# Description: Tests for the branch health module (entry-count + entry-size wrapper)
# Version: 1.0.0
# Created: 2026-08-16
# Modified: 2026-08-16
# =============================================

"""
Tests for apps/modules/health.py -- get_branch_health().

health.get_branch_health() wraps two existing read-only checks (rollover
entry-count via handlers/monitor/detector.py, character-cap entry-size via
handlers/json/lint_handler.py) into one public function for @daemon to
import from its modules/ layer.

Covers:
  - Unknown branch returns success=False with an error message
  - A known branch with no violations and no rollover due (default shape)
  - A known branch where entry-count DOES trigger rollover (True branch)
  - A known branch with planted entry-size violations
  - A memory_type whose .trinity file is missing is skipped gracefully
  - Case-insensitive branch resolution
  - Read-only: files are byte-identical before/after the call
  - The exact returned-dict shape
  - A pin against THIS branch's own real .trinity/local.json and
    .trinity/observations.json -- not just synthetic fixtures (per
    @daemon's own lesson: a synthetic fixture carried a field their real
    files did not, and the gap was the actual bug)
"""

import importlib
import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Infrastructure mocking.
#
# conftest.py's autouse _mock_infrastructure fixture replaces the whole
# "aipass.memory.apps.handlers.json" package with a bare MagicMock (only
# .json_handler set). That is enough for governance/lint tests, but health.py
# does `from aipass.memory.apps.handlers.json.lint_handler import run_lint`
# (an absolute dotted import) -- Python's import machinery needs the parent
# package to have a real __path__ to locate that submodule, and a MagicMock
# has none (dunder attributes are not auto-vivified), so it fails with
# "'...json' is not a package". detector.py/entry_limits.py also read
# config_loader.section()/.load(), and an unconfigured MagicMock there makes
# `cfg.get(...)` / int comparisons blow up.
#
# So: force the WHOLE chain (json package + json_handler + config_loader +
# entry_limits + lint_handler + detector + health) to import for real --
# real packages have real __path__, so plain dotted imports work -- and then
# monkeypatch only the two behaviors that matter: config_loader returns
# controlled dicts (deterministic, no coupling to live memory.config.json),
# and json_handler.log_operation is stubbed so tests never write real
# operational log files.
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_health_infrastructure(monkeypatch):
    """Force a real, fresh import of the health -> detector / lint_handler ->
    entry_limits / config_loader / json_handler chain, then patch
    config_loader to controlled dicts and json_handler.log_operation to a
    no-op (prax stays mocked by conftest's own autouse fixture)."""

    for name in (
        "aipass.memory.apps.handlers.json",
        "aipass.memory.apps.handlers.json.json_handler",
        "aipass.memory.apps.handlers.json.config_loader",
        "aipass.memory.apps.handlers.json.entry_limits",
        "aipass.memory.apps.handlers.json.lint_handler",
        "aipass.memory.apps.handlers.monitor",
        "aipass.memory.apps.handlers.monitor.detector",
        "aipass.memory.apps.modules.health",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)

    json_handler = importlib.import_module("aipass.memory.apps.handlers.json.json_handler")
    config_loader = importlib.import_module("aipass.memory.apps.handlers.json.config_loader")

    # Never let a test write a real entry into memory_json/*.json.
    monkeypatch.setattr(json_handler, "log_operation", MagicMock(return_value=True))

    # Default: a "config gap" for rollover (empty defaults/per_branch) so
    # check_single_file deterministically reports should_rollover=False,
    # and an empty entry_limits.entry_types so run_lint deterministically
    # reports zero violations -- independent of live memory.config.json.
    # Individual tests override via monkeypatch when they need a specific
    # scenario (rollover due / planted violation).
    monkeypatch.setattr(
        config_loader,
        "section",
        lambda name: {"defaults": {}, "per_branch": {}} if name == "rollover" else {},
    )
    monkeypatch.setattr(
        config_loader,
        "load",
        lambda: {"entry_limits": {"enabled": True, "enforce": False, "entry_types": {}, "per_branch": {}}},
    )


def _get_health():
    """Import and return the health module (fresh, per the fixture above)."""
    return importlib.import_module("aipass.memory.apps.modules.health")


def _get_detector():
    return importlib.import_module("aipass.memory.apps.handlers.monitor.detector")


def _get_lint_handler():
    return importlib.import_module("aipass.memory.apps.handlers.json.lint_handler")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _valid_local_json() -> dict[str, Any]:
    return {
        "document_metadata": {"document_type": "session_history", "schema_version": "3.0.0"},
        "sessions": [],
        "key_learnings": {},
    }


def _valid_observations_json() -> dict[str, Any]:
    return {
        "document_metadata": {"document_type": "collaboration_patterns", "schema_version": "3.0.0"},
        "observations": [],
    }


def _make_branch(tmp_path: Path, name: str = "test_branch", with_observations: bool = True) -> dict[str, str]:
    """Create a temp branch dir with .trinity/local.json (+ observations.json)."""
    branch_dir = tmp_path / name
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True)
    (trinity / "local.json").write_text(json.dumps(_valid_local_json(), indent=2), encoding="utf-8")
    if with_observations:
        (trinity / "observations.json").write_text(json.dumps(_valid_observations_json(), indent=2), encoding="utf-8")
    return {"name": name, "path": str(branch_dir)}


# ===========================================================================
# 1. Unknown branch
# ===========================================================================


class TestUnknownBranch:
    def test_unknown_branch_returns_error(self, tmp_path: Path):
        health = _get_health()
        branch = _make_branch(tmp_path)

        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("nosuchbranch")

        assert result == {"success": False, "error": "Unknown branch: nosuchbranch"}

    def test_empty_registry_is_unknown(self, tmp_path: Path):
        health = _get_health()

        with patch.object(health, "_read_registry", return_value=[]):
            result = health.get_branch_health("anything")

        assert result["success"] is False
        assert "anything" in result["error"]


# ===========================================================================
# 2. Known branch -- no violations, no rollover due (default shape)
# ===========================================================================


class TestKnownBranchNoViolations:
    def test_success_shape_and_values(self, tmp_path: Path):
        health = _get_health()
        branch = _make_branch(tmp_path, name="clean_branch")

        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("clean_branch")

        assert result["success"] is True
        assert result["branch"] == "clean_branch"

        assert result["entry_count"]["local"]["should_rollover"] is False
        assert result["entry_count"]["local"]["current_lines"] > 0
        assert result["entry_count"]["observations"]["should_rollover"] is False
        assert result["entry_count"]["observations"]["current_lines"] > 0

        assert result["entry_size"] == {"violations": [], "total_violations": 0}

    def test_case_insensitive_resolution(self, tmp_path: Path):
        """branch_name is matched case-insensitively against the registry."""
        health = _get_health()
        branch = _make_branch(tmp_path, name="clean_branch")

        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("CLEAN_BRANCH")

        assert result["success"] is True
        # Canonical registry name is returned, not the caller's casing.
        assert result["branch"] == "clean_branch"


# ===========================================================================
# 3. Known branch -- entry-count DOES trigger rollover
# ===========================================================================


class TestKnownBranchRolloverDue:
    def test_should_rollover_true_carries_trigger_fields(self, tmp_path: Path, monkeypatch):
        health = _get_health()
        detector = _get_detector()

        branch_dir = tmp_path / "full_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [{"id": f"s{i}"} for i in range(50)],
        }
        (trinity / "local.json").write_text(json.dumps(data, indent=2), encoding="utf-8")
        (trinity / "observations.json").write_text(json.dumps(_valid_observations_json(), indent=2), encoding="utf-8")

        # health.py imports check_single_file/_get_memory_file_path directly
        # from detector, so patch config_loader on the detector module the
        # already-imported names came from (same object health.py is using).
        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"full_branch": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )

        branch = {"name": "full_branch", "path": str(branch_dir)}
        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("full_branch")

        assert result["success"] is True
        local = result["entry_count"]["local"]
        assert local["should_rollover"] is True
        assert local["current_lines"] > 0
        assert "sessions" in local["reason"]

        # observations.json was untouched by the override -- config gap, no trigger.
        assert result["entry_count"]["observations"]["should_rollover"] is False


# ===========================================================================
# 4. A memory_type file that does not exist is skipped gracefully
# ===========================================================================


class TestMissingMemoryFile:
    def test_missing_observations_is_none_not_an_error(self, tmp_path: Path):
        health = _get_health()
        branch = _make_branch(tmp_path, name="partial_branch", with_observations=False)

        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("partial_branch")

        assert result["success"] is True
        assert result["entry_count"]["observations"] is None
        assert result["entry_count"]["local"] is not None


# ===========================================================================
# 5. Entry-size violations carry through
# ===========================================================================


class TestEntrySizeViolations:
    def test_planted_violation_is_reported(self, tmp_path: Path):
        health = _get_health()
        lint_handler = _get_lint_handler()

        branch_dir = tmp_path / "loud_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        local_data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "key_learnings": {
                "ok_entry": "fine",
                "bad_entry": "x" * 15,
            },
        }
        (trinity / "local.json").write_text(json.dumps(local_data, indent=2), encoding="utf-8")

        limits = {
            "enabled": True,
            "enforce": False,
            "entry_types": {
                "key_learnings": {
                    "file": "local.json",
                    "container": "key_learnings",
                    "kind": "dict",
                    "field": "value",
                    "max_chars": 10,
                },
            },
        }

        branch = {"name": "loud_branch", "path": str(branch_dir)}
        with patch.object(health, "_read_registry", return_value=[branch]):
            with patch.object(lint_handler, "load_entry_limits", return_value=limits):
                result = health.get_branch_health("loud_branch")

        assert result["success"] is True
        assert result["entry_size"]["total_violations"] == 1
        v = result["entry_size"]["violations"][0]
        assert v["branch"] == "loud_branch"
        assert v["key"] == "bad_entry"
        assert v["over_by"] == 5


# ===========================================================================
# 6. Read-only -- files unchanged after the call
# ===========================================================================


class TestReadOnly:
    def test_files_unchanged_after_call(self, tmp_path: Path):
        health = _get_health()
        branch = _make_branch(tmp_path, name="untouched_branch")

        local_path = Path(branch["path"]) / ".trinity" / "local.json"
        obs_path = Path(branch["path"]) / ".trinity" / "observations.json"
        local_before = local_path.read_text(encoding="utf-8")
        obs_before = obs_path.read_text(encoding="utf-8")

        with patch.object(health, "_read_registry", return_value=[branch]):
            health.get_branch_health("untouched_branch")

        assert local_path.read_text(encoding="utf-8") == local_before, "local.json was modified!"
        assert obs_path.read_text(encoding="utf-8") == obs_before, "observations.json was modified!"


# ===========================================================================
# 7. Public surface
# ===========================================================================


class TestPublicSurface:
    def test_get_branch_health_is_exported(self):
        health = _get_health()
        assert "get_branch_health" in health.__all__

    def test_unknown_branch_return_shape(self, tmp_path: Path):
        health = _get_health()
        with patch.object(health, "_read_registry", return_value=[]):
            result = health.get_branch_health("ghost")
        assert set(result.keys()) == {"success", "error"}

    def test_success_return_shape(self, tmp_path: Path):
        health = _get_health()
        branch = _make_branch(tmp_path, name="shape_branch")

        with patch.object(health, "_read_registry", return_value=[branch]):
            result = health.get_branch_health("shape_branch")

        assert set(result.keys()) == {"success", "branch", "entry_count", "entry_size"}
        assert set(result["entry_count"].keys()) == {"local", "observations"}
        assert set(result["entry_size"].keys()) == {"violations", "total_violations"}
        for memory_type in ("local", "observations"):
            assert set(result["entry_count"][memory_type].keys()) == {"should_rollover", "current_lines", "reason"}


# ===========================================================================
# 8. REAL .trinity FILES (production truth, not fixtures)
# ===========================================================================


class TestRealTrinityFiles:
    """Pin against @memory's OWN live .trinity files, not just synthetic
    fixtures.

    Per @daemon's own hard-won lesson this week (recorded in their mail): a
    synthetic fixture carried a field their real files did not, and the gap
    between "the fixture models reality" and reality was the actual bug. A
    synthetic tmp_path branch cannot fail the way real production data can,
    so this reads the real files on disk.

    config_loader stays mocked (same controlled dicts as every other test in
    this file, config-gap / empty entry_types) so the assertions do not
    depend on live rollover thresholds drifting over time -- what is real
    here is the FILE: real path resolution via the real registry shape,
    real JSON parsing, real line counting.
    """

    BRANCH_ROOT = Path(__file__).resolve().parents[1]

    def test_real_branch_health_reads_real_files_without_mutating_them(self):
        local_file = self.BRANCH_ROOT / ".trinity" / "local.json"
        obs_file = self.BRANCH_ROOT / ".trinity" / "observations.json"
        if not local_file.exists() or not obs_file.exists():
            pytest.skip("no live .trinity files in this checkout")

        health = _get_health()

        local_before = local_file.read_text(encoding="utf-8")
        obs_before = obs_file.read_text(encoding="utf-8")

        with patch.object(health, "_read_registry", return_value=[{"name": "memory", "path": str(self.BRANCH_ROOT)}]):
            result = health.get_branch_health("memory")

        # Read-only: real files must be byte-identical after the call.
        assert local_file.read_text(encoding="utf-8") == local_before, "get_branch_health modified local.json!"
        assert obs_file.read_text(encoding="utf-8") == obs_before, "get_branch_health modified observations.json!"

        assert result["success"] is True
        assert result["branch"] == "memory"

        assert result["entry_count"]["local"] is not None
        assert isinstance(result["entry_count"]["local"]["current_lines"], int)
        assert result["entry_count"]["local"]["current_lines"] > 0
        assert isinstance(result["entry_count"]["local"]["should_rollover"], bool)

        assert result["entry_count"]["observations"] is not None
        assert isinstance(result["entry_count"]["observations"]["current_lines"], int)
        assert result["entry_count"]["observations"]["current_lines"] > 0

        assert isinstance(result["entry_size"]["violations"], list)
        assert isinstance(result["entry_size"]["total_violations"], int)
