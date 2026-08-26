# =================== AIPass ====================
# Name: test_detector.py
# Description: Tests for rollover trigger detection handler
# Version: 1.1.0
# Created: 2026-03-24
# Modified: 2026-06-14
# =============================================

"""Tests for the rollover trigger detection module (apps/handlers/monitor/detector).

Uses tmp_path for all file operations. Creates real temp files with JSON content
rather than mocking open(). The detector module is imported inside each test
to ensure the autouse conftest fixture for json_handler is already applied.
"""

import json
import logging
import sys

import pytest
from pathlib import Path
from unittest.mock import MagicMock

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Autouse fixture -- mock heavy infrastructure before detector is imported
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_detector_infrastructure(monkeypatch):
    """Mock prax logger and json_handler so detector.py can be imported."""

    # -- prax logger --------------------------------------------------------
    mock_logger_mod = MagicMock()
    mock_logger_mod.get_system_logger = MagicMock(return_value=MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules", MagicMock())
    monkeypatch.setitem(sys.modules, "aipass.prax.apps.modules.logger", mock_logger_mod)

    # -- memory json handler ------------------------------------------------
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- config_loader (must return real dicts, not MagicMocks) -------------
    mock_config_loader = MagicMock()
    mock_config_loader.load.return_value = {
        "rollover": {"defaults": {}, "per_branch": {}},
    }
    mock_config_loader.section.side_effect = lambda name: mock_config_loader.load.return_value.get(name, {})

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    json_pkg.config_loader = mock_config_loader
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json", json_pkg)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.json_handler", mock_json_handler)
    monkeypatch.setitem(sys.modules, "aipass.memory.apps.handlers.json.config_loader", mock_config_loader)

    # Force fresh import every test — must also clean the parent package's
    # cached attribute, otherwise Python reuses a stale detector module
    # that holds an unconfigured config_loader reference.
    monkeypatch.delitem(sys.modules, "aipass.memory.apps.handlers.monitor.detector", raising=False)
    parent = sys.modules.get("aipass.memory.apps.handlers.monitor")
    if parent is not None and hasattr(parent, "detector"):
        monkeypatch.delattr(parent, "detector", raising=False)


# ===========================================================================
# _get_memory_file_path
# ===========================================================================


class TestGetMemoryFilePath:
    """Tests for _get_memory_file_path(branch, memory_type)."""

    def test_returns_path_when_file_exists(self, tmp_path: Path):
        """Existing .trinity file should resolve to a valid Path."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        obs_file = trinity_dir / "observations.json"
        obs_file.write_text("{}", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        branch = {"path": str(tmp_path)}
        result = detector._get_memory_file_path(branch, "observations")

        assert result is not None
        assert result == obs_file

    def test_returns_none_when_file_missing(self, tmp_path: Path):
        """Missing memory file should return None."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        # No observations.json created

        from aipass.memory.apps.handlers.monitor import detector

        branch = {"path": str(tmp_path)}
        result = detector._get_memory_file_path(branch, "observations")

        assert result is None

    def test_returns_none_when_branch_path_missing(self, tmp_path: Path):
        """Nonexistent branch path should return None."""
        from aipass.memory.apps.handlers.monitor import detector

        nonexistent = tmp_path / "does_not_exist"
        branch = {"path": str(nonexistent)}
        result = detector._get_memory_file_path(branch, "local")

        assert result is None

    def test_returns_none_when_path_key_empty(self, tmp_path: Path):
        """Empty path key in branch dict should return None."""
        from aipass.memory.apps.handlers.monitor import detector

        branch: dict[str, str] = {"path": ""}
        result = detector._get_memory_file_path(branch, "local")

        assert result is None

    def test_local_memory_type(self, tmp_path: Path):
        """Local memory type should resolve to local.json in .trinity dir."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        local_file = trinity_dir / "local.json"
        local_file.write_text("{}", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        branch = {"path": str(tmp_path)}
        result = detector._get_memory_file_path(branch, "local")

        assert result is not None
        assert result.name == "local.json"


# ===========================================================================
# check_single_file
# ===========================================================================


class TestCheckSingleFile:
    """Tests for check_single_file(file_path)."""

    def test_file_under_threshold_no_rollover(self, tmp_path: Path, monkeypatch):
        """A small file with entries under v2 limits should not trigger rollover."""
        mem_file = tmp_path / "SEEDGO.observations.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "observations": [],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"seedgo": {"observations": {"observations": {"count": 10}}}}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False

    def test_file_over_threshold_triggers_rollover(self, tmp_path: Path, monkeypatch):
        """A file exceeding v2 entry-count limits should trigger rollover."""
        mem_file = tmp_path / "SEEDGO.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [{"id": f"s{i}", "notes": "padding"} for i in range(50)],
        }
        content = json.dumps(data, indent=2)
        mem_file.write_text(content, encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"seedgo": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "trigger" in result

    def test_missing_file_returns_error(self, tmp_path: Path):
        """check_single_file on a nonexistent path returns success=False."""
        missing = tmp_path / "ghost.json"

        from aipass.memory.apps.handlers.monitor import detector

        result = detector.check_single_file(missing)

        assert result["success"] is False
        assert "error" in result

    def test_v2_schema_entry_count_trigger(self, tmp_path: Path, monkeypatch):
        """v2 schema triggers on entry counts from config per_branch."""
        mem_file = tmp_path / "DRONE.local.json"
        data = {
            "document_metadata": {"schema_version": "2.0.0"},
            "sessions": [{"id": "s1"}, {"id": "s2"}, {"id": "s3"}, {"id": "s4"}],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"drone": {"local": {"sessions": {"count": 3}}}}, "defaults": {}},
        )
        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True

    def test_v2_schema_under_limit_no_trigger(self, tmp_path: Path, monkeypatch):
        """v2 schema with entries under the limit should not trigger."""
        mem_file = tmp_path / "FLOW.local.json"
        data = {
            "document_metadata": {"schema_version": "2.0.0"},
            "sessions": [{"id": "s1"}, {"id": "s2"}],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"flow": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )
        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False

    def test_v2_list_key_learnings_triggers_rollover(self, tmp_path: Path, monkeypatch):
        """List-shaped key_learnings ABOVE count triggers v2 rollover.

        Above, not "at/over": keep-3 means the file may hold 3. Firing at the
        limit while the extractor drains `len - limit` (nothing) is the
        NOTHING DRAINED skip loop — see test_trinity_standard.py::TestKeepNKeepsN.
        """
        mem_file = tmp_path / "DEVPULSE.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "key_learnings": [
                {"number": 4, "date": "2026-06-14", "key": "d", "value": "vd"},
                {"number": 3, "date": "2026-06-13", "key": "c", "value": "vc"},
                {"number": 2, "date": "2026-06-12", "key": "b", "value": "vb"},
                {"number": 1, "date": "2026-06-11", "key": "a", "value": "va"},
            ],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"devpulse": {"local": {"key_learnings": {"count": 3}}}}, "defaults": {}},
        )
        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "4/3 key_learnings" in result["trigger"].v2_reason

    def test_v2_list_key_learnings_under_limit_no_trigger(self, tmp_path: Path, monkeypatch):
        """List-shaped key_learnings under count does not trigger."""
        mem_file = tmp_path / "DRONE.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "key_learnings": [
                {"number": 2, "date": "2026-06-13", "key": "b", "value": "vb"},
                {"number": 1, "date": "2026-06-12", "key": "a", "value": "va"},
            ],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {
                "per_branch": {"drone": {"local": {"key_learnings": {"count": 10}}}},
                "defaults": {},
            },
        )
        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False

    def test_parse_failure_returns_no_rollover(self, tmp_path: Path, monkeypatch):
        """JSON parse failure should return should_rollover=False, not 600-line fallback."""
        mem_file = tmp_path / "BROKEN.local.json"
        mem_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"broken": {"local": {"sessions": {"count": 5}}}}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False
        assert "parse failure" in result.get("v2_reason", "")

    def test_defaults_fallback_when_branch_missing_from_per_branch(self, tmp_path: Path, monkeypatch):
        """Branch not in per_branch should fall back to defaults and still trigger on entry count."""
        mem_file = tmp_path / "NEWBRANCH.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [{"id": f"s{i}"} for i in range(15)],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # per_branch has NO entry for "newbranch", but defaults has local limits
        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {
                "per_branch": {},
                "defaults": {"local": {"sessions": {"count": 10}}},
            },
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "15/10 sessions" in result["trigger"].v2_reason

    def test_no_limits_in_per_branch_or_defaults_skips_rollover(self, tmp_path: Path, monkeypatch):
        """Branch missing from BOTH per_branch AND defaults should not roll and log config gap."""
        mem_file = tmp_path / "ORPHAN.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [{"id": f"s{i}"} for i in range(100)],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # Neither per_branch nor defaults have anything for "orphan"/"local"
        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False
        assert "config gap" in result.get("v2_reason", "")


class TestSessionAutoCompactBudget:
    """auto-compact snapshots get their own cap and don't inflate the regular session count."""

    def test_auto_compact_cap_triggers_independently_of_session_count(self, tmp_path: Path, monkeypatch):
        """4 auto-compact entries over cap=3 trigger even with regular sessions well under count."""
        mem_file = tmp_path / "MEMORY.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [
                {"id": "regular-1", "status": "completed"},
                {"id": "auto-0", "status": "auto-compact"},
                {"id": "auto-1", "status": "auto-compact"},
                {"id": "auto-2", "status": "auto-compact"},
                {"id": "auto-3", "status": "auto-compact"},
            ],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {
                "per_branch": {"memory": {"local": {"sessions": {"count": 15, "auto_compact_cap": 3}}}},
                "defaults": {},
            },
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert result["trigger"].v2_reason == "4/3 auto-compact snapshots"

    def test_auto_compact_entries_excluded_from_regular_session_count(self, tmp_path: Path, monkeypatch):
        """Auto-compact entries must not count toward the regular sessions/count trigger."""
        mem_file = tmp_path / "MEMORY.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": (
                [{"id": f"regular-{i}", "status": "completed"} for i in range(2)]
                + [{"id": f"auto-{i}", "status": "auto-compact"} for i in range(5)]
            ),
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {
                "per_branch": {"memory": {"local": {"sessions": {"count": 10, "auto_compact_cap": 20}}}},
                "defaults": {},
            },
        )

        result = detector.check_single_file(mem_file)

        # 2 regular sessions (well under count=10), 5 auto-compact (well under cap=20)
        assert result["success"] is True
        assert result["should_rollover"] is False

    def test_regular_session_count_still_triggers_without_auto_compact_cap(self, tmp_path: Path, monkeypatch):
        """Branches without auto_compact_cap configured keep triggering on raw session count."""
        mem_file = tmp_path / "MEMORY.local.json"
        data = {
            "document_metadata": {"schema_version": "3.0.0"},
            "sessions": [{"id": f"s{i}", "status": "completed"} for i in range(12)],
        }
        mem_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"memory": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "12/10 sessions" in result["trigger"].v2_reason


# ===========================================================================
# _read_registry
# ===========================================================================


class TestReadRegistry:
    """Tests for _read_registry()."""

    def test_valid_registry_returns_branches(self, tmp_path: Path, monkeypatch):
        """Valid registry JSON should return all branches with absolute paths."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "memory", "path": "src/aipass/memory"},
                {"name": "drone", "path": "src/aipass/drone"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        # Point _REPO_ROOT at our tmp_path
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector._read_registry()

        assert len(result) == 2
        assert result[0]["name"] == "memory"
        # Paths should be resolved to absolute
        assert Path(result[0]["path"]).is_absolute()

    def test_missing_registry_returns_empty(self, tmp_path: Path, monkeypatch):
        """Missing registry file should return empty list."""
        from aipass.memory.apps.handlers.monitor import detector

        # Point _REPO_ROOT at a directory with no registry file
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector._read_registry()

        assert result == []

    def test_invalid_json_returns_empty(self, tmp_path: Path, monkeypatch):
        """Malformed registry JSON should return empty list."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("NOT JSON {{{", encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector._read_registry()

        assert result == []

    def test_registry_resolves_relative_paths(self, tmp_path: Path, monkeypatch):
        """Relative paths in registry should be resolved to absolute."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "cli", "path": "src/aipass/cli"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector._read_registry()

        resolved_path = Path(result[0]["path"])
        assert resolved_path.is_absolute()
        assert str(resolved_path) == str(tmp_path / "src/aipass/cli")

    def test_empty_branches_list(self, tmp_path: Path, monkeypatch):
        """Registry with empty branches list should return empty list."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {"branches": []}
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector._read_registry()

        assert result == []


# ===========================================================================
# Self-healing recreation (_recreate_trinity_file)
# ===========================================================================


class TestRecreateTrinityFile:
    """Tests for _recreate_trinity_file — P4 self-healing."""

    def test_recreates_missing_local_file(self, tmp_path: Path, monkeypatch):
        """Missing local.json should be recreated from template with _usage and no limits."""
        from aipass.memory.apps.handlers.monitor import detector

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        template = {
            "document_metadata": {
                "document_type": "session_history",
                "document_name": "{{BRANCHNAME}}.LOCAL",
                "_usage": "Automated file.",
                "status": {"health": "healthy"},
            },
            "sessions": [],
            "key_learnings": [],
        }
        (templates_dir / "LOCAL.template.json").write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(detector, "_TEMPLATES_DIR", templates_dir)
        monkeypatch.setattr(
            detector,
            "_TEMPLATE_MAP",
            {"local": templates_dir / "LOCAL.template.json"},
        )

        branch_dir = tmp_path / "testbranch"
        branch_dir.mkdir()

        result = detector._recreate_trinity_file(branch_dir, "testbranch", "local")

        assert result is not None
        assert result.exists()
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["document_metadata"]["document_name"] == "TESTBRANCH.LOCAL"
        assert "_usage" in data["document_metadata"]
        assert "limits" not in data["document_metadata"]

    def test_recreates_missing_observations_file(self, tmp_path: Path, monkeypatch):
        """Missing observations.json should be recreated from template."""
        from aipass.memory.apps.handlers.monitor import detector

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        template = {
            "document_metadata": {
                "document_type": "collaboration_patterns",
                "document_name": "{{BRANCHNAME}}.OBSERVATIONS",
                "_usage": "Automated file.",
            },
            "observations": [],
        }
        (templates_dir / "OBSERVATIONS.template.json").write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(detector, "_TEMPLATES_DIR", templates_dir)
        monkeypatch.setattr(
            detector,
            "_TEMPLATE_MAP",
            {"observations": templates_dir / "OBSERVATIONS.template.json"},
        )

        branch_dir = tmp_path / "api"
        branch_dir.mkdir()

        result = detector._recreate_trinity_file(branch_dir, "api", "observations")

        assert result is not None
        data = json.loads(result.read_text(encoding="utf-8"))
        assert data["document_metadata"]["document_name"] == "API.OBSERVATIONS"
        assert "limits" not in data["document_metadata"]

    def test_check_all_branches_recreates_missing(self, tmp_path: Path, monkeypatch):
        """check_all_branches should auto-recreate missing .trinity files."""
        from aipass.memory.apps.handlers.monitor import detector

        branch_dir = tmp_path / "mybranch"
        trinity_dir = branch_dir / ".trinity"
        trinity_dir.mkdir(parents=True)
        # Only create observations, NOT local — local should be recreated
        obs_data = {
            "document_metadata": {"schema_version": "1.0.0", "limits": {"max_lines": 600}},
            "observations": [],
        }
        (trinity_dir / "observations.json").write_text(json.dumps(obs_data, indent=2), encoding="utf-8")

        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        local_template = {
            "document_metadata": {
                "document_type": "session_history",
                "document_name": "{{BRANCHNAME}}.LOCAL",
                "_usage": "Automated file.",
                "status": {"health": "healthy"},
            },
            "sessions": [],
        }
        (templates_dir / "LOCAL.template.json").write_text(json.dumps(local_template), encoding="utf-8")
        monkeypatch.setattr(detector, "_TEMPLATES_DIR", templates_dir)
        monkeypatch.setattr(
            detector,
            "_TEMPLATE_MAP",
            {
                "local": templates_dir / "LOCAL.template.json",
                "observations": templates_dir / "OBSERVATIONS.template.json",
            },
        )

        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "mybranch", "path": str(branch_dir), "status": "active"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        detector.check_all_branches()

        recreated = trinity_dir / "local.json"
        assert recreated.exists()
        data = json.loads(recreated.read_text(encoding="utf-8"))
        assert data["document_metadata"]["document_name"] == "MYBRANCH.LOCAL"
        assert "limits" not in data["document_metadata"]


# ===========================================================================
# Known registries (persist / load / discovery)
# ===========================================================================


class TestKnownRegistries:
    """Tests for load_known_registries() and persist_registry()."""

    def test_load_returns_empty_when_file_missing(self, tmp_path: Path, monkeypatch):
        """No known_registries.json → empty list."""
        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", tmp_path / "nope.json")

        result = detector.load_known_registries()

        assert result == []

    def test_persist_creates_file_and_stores_path(self, tmp_path: Path, monkeypatch):
        """persist_registry should create the file and store the absolute path."""
        from aipass.memory.apps.handlers.monitor import detector

        kr_path = tmp_path / "known_registries.json"
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)

        ext_reg = tmp_path / "EXT_REGISTRY.json"
        ext_reg.write_text('{"branches":[]}', encoding="utf-8")

        detector.persist_registry(ext_reg)

        assert kr_path.exists()
        data = json.loads(kr_path.read_text(encoding="utf-8"))
        assert str(ext_reg.resolve()) in data["registries"]

    def test_persist_deduplicates(self, tmp_path: Path, monkeypatch):
        """Persisting the same registry twice should not create duplicates."""
        from aipass.memory.apps.handlers.monitor import detector

        kr_path = tmp_path / "known_registries.json"
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)

        ext_reg = tmp_path / "EXT_REGISTRY.json"
        ext_reg.write_text('{"branches":[]}', encoding="utf-8")

        detector.persist_registry(ext_reg)
        detector.persist_registry(ext_reg)

        data = json.loads(kr_path.read_text(encoding="utf-8"))
        assert len(data["registries"]) == 1

    def test_load_filters_nonexistent_paths(self, tmp_path: Path, monkeypatch):
        """load_known_registries filters out paths that no longer exist."""
        from aipass.memory.apps.handlers.monitor import detector

        kr_path = tmp_path / "known_registries.json"
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)

        existing = tmp_path / "REAL_REGISTRY.json"
        existing.write_text('{"branches":[]}', encoding="utf-8")

        kr_path.write_text(
            json.dumps(
                {
                    "registries": [str(existing), "/nonexistent/GHOST_REGISTRY.json"],
                }
            ),
            encoding="utf-8",
        )

        result = detector.load_known_registries()

        assert len(result) == 1
        assert result[0] == existing

    def test_load_handles_malformed_json(self, tmp_path: Path, monkeypatch):
        """Malformed known_registries.json → empty list, not crash."""
        from aipass.memory.apps.handlers.monitor import detector

        kr_path = tmp_path / "known_registries.json"
        kr_path.write_text("NOT JSON", encoding="utf-8")
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)

        result = detector.load_known_registries()

        assert result == []

    def test_find_caller_registries_includes_known(self, tmp_path: Path, monkeypatch):
        """_find_caller_registries should include registries from known_registries.json."""
        from aipass.memory.apps.handlers.monitor import detector

        kr_path = tmp_path / "known_registries.json"
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)

        ext_project = tmp_path / "ext_project"
        ext_project.mkdir()
        ext_reg = ext_project / "MYPROJECT_REGISTRY.json"
        ext_reg.write_text('{"branches":[]}', encoding="utf-8")

        kr_path.write_text(
            json.dumps(
                {
                    "registries": [str(ext_reg)],
                }
            ),
            encoding="utf-8",
        )

        aipass_reg = tmp_path / "AIPASS_REGISTRY.json"
        aipass_reg.write_text('{"branches":[]}', encoding="utf-8")
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(tmp_path))

        result = detector._find_caller_registries()

        resolved_paths = [r.resolve() for r in result]
        assert ext_reg.resolve() in resolved_paths

    def test_read_registry_discovers_external_branches_via_known(self, tmp_path: Path, monkeypatch):
        """_read_registry should find external branches via known_registries.json
        even when cwd is AIPass root (the core bug from #664)."""
        from aipass.memory.apps.handlers.monitor import detector

        core_dir = tmp_path / "aipass"
        core_dir.mkdir()
        core_reg = core_dir / "AIPASS_REGISTRY.json"
        core_reg.write_text(
            json.dumps(
                {
                    "branches": [{"name": "memory", "path": "src/memory"}],
                }
            ),
            encoding="utf-8",
        )

        ext_project = tmp_path / "myproject"
        ext_project.mkdir()
        ext_branch = ext_project / "src" / "mybranch"
        ext_branch.mkdir(parents=True)
        ext_reg = ext_project / "MYPROJECT_REGISTRY.json"
        ext_reg.write_text(
            json.dumps(
                {
                    "branches": [{"name": "mybranch", "path": "src/mybranch"}],
                }
            ),
            encoding="utf-8",
        )

        kr_path = tmp_path / "known_registries.json"
        kr_path.write_text(
            json.dumps(
                {
                    "registries": [str(ext_reg)],
                }
            ),
            encoding="utf-8",
        )

        monkeypatch.setattr(detector, "_REPO_ROOT", core_dir)
        monkeypatch.setattr(detector, "_KNOWN_REGISTRIES_PATH", kr_path)
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(core_dir))

        branches = detector._read_registry()

        names = [b["name"] for b in branches]
        assert "memory" in names
        assert "mybranch" in names
