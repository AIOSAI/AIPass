# =================== AIPass ====================
# Name: test_detector.py
# Description: Tests for rollover trigger detection handler
# Version: 1.3.1
# Created: 2026-03-24
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/monitor/detector.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — resident tier, read_scope() externals: tests/test_residency_scope.py
# seedgo: no-test-needed(covered_elsewhere) — _find_repo_root() -> find_repo_root, pinned in tests/test_repo_root.py
# seedgo: no-test-needed(covered_elsewhere) — detector/extractor boundary sweep: tests/test_trinity_standard.py
# seedgo: no-test-needed(external) — get_system_logger from @prax; the autouse fixture replaces logger

import json
import logging

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from aipass.memory.apps.handlers import write_fence
from aipass.memory.apps.handlers.monitor import detector, registry_scope

logger = logging.getLogger(__name__)

# A caller-side registry offering one branch, by name, at a relative path inside its project.
_ONE_BRANCH = '{"branches":[{"name":"%s","path":"src/b"}]}'


@pytest.fixture(autouse=True)
def _mock_detector_infrastructure(monkeypatch):
    """Mock prax logger and json_handler so detector.py can be imported."""

    monkeypatch.setattr(detector, "logger", MagicMock())

    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # Real dicts, not MagicMocks: the detector indexes into them.
    mock_config_loader = MagicMock()
    mock_config_loader.load.return_value = {
        "rollover": {"defaults": {}, "per_branch": {}},
    }
    mock_config_loader.section.side_effect = lambda name: mock_config_loader.load.return_value.get(name, {})

    monkeypatch.setattr(detector, "json_handler", mock_json_handler)
    monkeypatch.setattr(detector, "config_loader", mock_config_loader)


def _stats_over(tmp_path: Path, monkeypatch, branch_path: str) -> dict:
    """get_rollover_stats over a tmp fleet of one branch, named "b", at *branch_path*."""
    registry = {"branches": [{"name": "b", "path": branch_path, "status": "active"}]}
    (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
    monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
    monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
    return detector.get_rollover_stats()


class TestGetMemoryFilePath:
    """Which .trinity files the stats walk finds for a branch (it never recreates one)."""

    def test_returns_path_when_file_exists(self, tmp_path: Path, monkeypatch):
        """An existing .trinity/observations.json is the one file checked."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / "observations.json").write_text("{}", encoding="utf-8")

        stats = _stats_over(tmp_path, monkeypatch, str(tmp_path))

        assert stats["files_checked"] == 1
        assert list(stats["branches"]["b"]) == ["observations"]

    def test_returns_none_when_file_missing(self, tmp_path: Path, monkeypatch):
        """An empty .trinity dir yields no file to check, and none is made."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()

        stats = _stats_over(tmp_path, monkeypatch, str(tmp_path))

        assert (stats["files_checked"], stats["branches"]) == (0, {})
        assert list(trinity_dir.iterdir()) == []

    def test_returns_none_when_branch_path_missing(self, tmp_path: Path, monkeypatch):
        """A registry row pointing at a missing directory is skipped, not created."""
        nonexistent = tmp_path / "does_not_exist"

        stats = _stats_over(tmp_path, monkeypatch, str(nonexistent))

        assert (stats["total_branches"], stats["files_checked"]) == (1, 0)
        assert not nonexistent.exists()

    def test_returns_none_when_path_key_empty(self, tmp_path: Path, monkeypatch):
        """An empty registry path resolves to the root, which holds no .trinity: nothing checked."""
        stats = _stats_over(tmp_path, monkeypatch, "")

        assert (stats["total_branches"], stats["files_checked"], stats["branches"]) == (1, 0, {})

    def test_local_memory_type(self, tmp_path: Path, monkeypatch):
        """A .trinity/local.json alone is checked under the "local" type."""
        trinity_dir = tmp_path / ".trinity"
        trinity_dir.mkdir()
        (trinity_dir / "local.json").write_text("{}", encoding="utf-8")

        stats = _stats_over(tmp_path, monkeypatch, str(tmp_path))

        assert list(stats["branches"]["b"]) == ["local"]


class TestGetRolloverStats:
    """get_rollover_stats() counts a tmp fleet's files: checked, ready, undrainable."""

    def test_counts_one_branch_with_a_ready_file_and_an_undrainable_one(self, tmp_path: Path, monkeypatch):
        """local is over its sessions count and holds a dict of learnings; observations is under."""
        trinity = tmp_path / "writer" / ".trinity"
        trinity.mkdir(parents=True)
        local = {
            "document_metadata": {"schema_version": "2.0.0"},
            "sessions": [{"number": n, "status": "completed"} for n in range(4, 0, -1)],
            "key_learnings": {f"KL-{n:03d}": "x" for n in range(1, 5)},
        }
        (trinity / "local.json").write_text(json.dumps(local), encoding="utf-8")
        (trinity / "observations.json").write_text(json.dumps({"observations": []}), encoding="utf-8")
        limits = {
            "local": {"sessions": {"count": 3}, "key_learnings": {"count": 3}},
            "observations": {"observations": {"count": 3}},
        }
        monkeypatch.setattr(detector.config_loader, "section", lambda name: {"per_branch": {}, "defaults": limits})

        stats = _stats_over(tmp_path, monkeypatch, str(tmp_path / "writer"))

        assert (stats["success"], stats["total_branches"], stats["files_checked"]) == (True, 1, 2)
        assert (stats["files_ready"], stats["files_undrainable"]) == (1, 1)
        assert stats["branches"]["b"]["local"]["ready"] is True
        assert stats["branches"]["b"]["local"]["v2_reason"] == "4/3 sessions"
        assert stats["branches"]["b"]["local"]["undrainable"] == [
            "4/3 key_learnings held as a dict, not a list (schema 2.0.0)"
        ]
        assert stats["branches"]["b"]["observations"] == {"current": 1, "ready": False, "schema_version": "3.0.0"}


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

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"flow": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )
        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is False

    def test_v2_list_key_learnings_triggers_rollover(self, tmp_path: Path, monkeypatch):
        """List-shaped key_learnings ABOVE count triggers v2 rollover; at the limit is the NOTHING DRAINED loop."""
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

    @staticmethod
    def _dict_learnings(tmp_path: Path, entries: int) -> Path:
        """A schema 2.0.0 local.json whose key_learnings is a dict, the shape VERA and WRITER still carry."""
        trinity = tmp_path / "vera" / ".trinity"
        trinity.mkdir(parents=True)
        mem_file = trinity / "local.json"
        data = {
            "document_metadata": {"schema_version": "2.0.0"},
            "key_learnings": {f"KL-{n:03d}": f"learning {n}" for n in range(1, entries + 1)},
        }
        mem_file.write_text(json.dumps(data), encoding="utf-8")
        return mem_file

    def test_a_dict_over_its_count_is_undrainable_not_a_trigger(self, tmp_path: Path, monkeypatch):
        """A dict has no order and no numbers, and the extractor drains lists only: never a trigger."""
        mem_file = self._dict_learnings(tmp_path, 4)

        limits = {"per_branch": {}, "defaults": {"local": {"key_learnings": {"count": 3}}}}
        monkeypatch.setattr(detector.config_loader, "section", lambda name: limits)

        assert detector.check_single_file(mem_file)["should_rollover"] is False
        assert detector.undrainable_containers(mem_file) == [
            "4/3 key_learnings held as a dict, not a list (schema 2.0.0)"
        ]

    def test_a_dict_at_its_count_is_not_undrainable(self, tmp_path: Path, monkeypatch):
        """Keep-N keeps N, in either shape: at the count there is nothing to drain."""
        mem_file = self._dict_learnings(tmp_path, 3)

        limits = {"per_branch": {}, "defaults": {"local": {"key_learnings": {"count": 3}}}}
        monkeypatch.setattr(detector.config_loader, "section", lambda name: limits)

        assert detector.undrainable_containers(mem_file) == []

    def test_the_fleet_walk_names_a_dict_apart_from_the_triggers_and_warns(self, tmp_path: Path, monkeypatch):
        """One file, both kinds: the sessions list rolls, the dict is named - and never silently."""
        trinity = tmp_path / "writer" / ".trinity"
        trinity.mkdir(parents=True)
        sessions = [
            {"number": n, "date": "2026-09-01", "summary": f"s{n}", "status": "completed"} for n in range(4, 0, -1)
        ]
        local = {
            "document_metadata": {"schema_version": "2.0.0"},
            "sessions": sessions,
            "key_learnings": {f"KL-{n:03d}": "x" for n in range(1, 5)},
        }
        (trinity / "local.json").write_text(json.dumps(local), encoding="utf-8")
        (trinity / "observations.json").write_text(json.dumps({"observations": []}), encoding="utf-8")
        registry = {"branches": [{"name": "WRITER", "path": str(tmp_path / "writer"), "status": "active"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        limits = {
            "local": {"sessions": {"count": 3}, "key_learnings": {"count": 3}},
            "observations": {"observations": {"count": 3}},
        }
        monkeypatch.setattr(detector.config_loader, "section", lambda name: {"per_branch": {}, "defaults": limits})
        said = []
        monkeypatch.setattr(detector.logger, "warning", lambda msg, *a, **k: said.append(str(msg)))

        result = detector.check_all_branches()

        assert [t.v2_reason for t in result["triggers"]] == ["4/3 sessions"]
        assert [str(u) for u in result["undrainable"]] == [
            "WRITER.local (4/3 key_learnings held as a dict, not a list (schema 2.0.0))"
        ]
        assert any("UNDRAINABLE WRITER.local" in line for line in said), said

    def test_parse_failure_returns_no_rollover(self, tmp_path: Path, monkeypatch):
        """JSON parse failure should return should_rollover=False, not 600-line fallback."""
        mem_file = tmp_path / "BROKEN.local.json"
        mem_file.write_text("NOT VALID JSON {{{", encoding="utf-8")

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

        monkeypatch.setattr(
            detector.config_loader,
            "section",
            lambda name: {"per_branch": {"memory": {"local": {"sessions": {"count": 10}}}}, "defaults": {}},
        )

        result = detector.check_single_file(mem_file)

        assert result["success"] is True
        assert result["should_rollover"] is True
        assert "12/10 sessions" in result["trigger"].v2_reason


class TestReadRegistry:
    """The registry read, through read_scope(): a tmp root declares no external roots, so it is the write scope."""

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

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector.read_scope()

        assert len(result) == 2
        assert result[0]["name"] == "memory"
        assert Path(result[0]["path"]).is_absolute()

    def test_missing_registry_returns_empty(self, tmp_path: Path, monkeypatch):
        """Missing registry file should return empty list."""

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector.read_scope()

        assert result == []

    def test_an_unreadable_core_registry_is_not_an_empty_fleet(self, tmp_path: Path, monkeypatch):
        """An unreadable core registry is a failure the walk reports, never "No branches in registry"."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text("NOT JSON {{{", encoding="utf-8")

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        with pytest.raises(detector.RegistryUnreadable, match="AIPASS_REGISTRY"):
            detector.read_scope()
        walk = detector.check_all_branches()
        assert walk["success"] is False
        assert str(registry_file) in walk["error"]
        assert detector.get_rollover_stats()["success"] is False

    def test_an_unreadable_resident_registry_costs_only_its_own_rows(self, tmp_path: Path, monkeypatch):
        """A broken resident registry is skipped at error level; the core fleet is still walked."""
        core = {"branches": [{"name": "memory", "path": "src/aipass/memory"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(core), encoding="utf-8")
        broken = tmp_path / "projects" / "p" / "P_REGISTRY.json"
        broken.parent.mkdir(parents=True)
        broken.write_text("NOT JSON {{{", encoding="utf-8")

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        monkeypatch.setattr(registry_scope, "resident_registry_paths", lambda root: [broken])
        monkeypatch.setattr(registry_scope, "accepted_resident_paths", lambda root: set())
        log = MagicMock()
        monkeypatch.setattr(detector, "logger", log)

        assert [b["name"] for b in detector.read_scope()] == ["memory"]
        assert any(str(broken) in c.args[0] for c in log.error.call_args_list)

    def test_registry_resolves_relative_paths(self, tmp_path: Path, monkeypatch):
        """Relative paths in registry should be resolved to absolute."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {
            "branches": [
                {"name": "cli", "path": "src/aipass/cli"},
            ]
        }
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector.read_scope()

        resolved_path = Path(result[0]["path"])
        assert resolved_path.is_absolute()
        assert str(resolved_path) == str(tmp_path / "src/aipass/cli")

    def test_empty_branches_list(self, tmp_path: Path, monkeypatch):
        """Registry with empty branches list should return empty list."""
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_data = {"branches": []}
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector.read_scope()

        assert result == []


class TestAMissingTrinityFileIsSkipped:
    """The fleet walk reads; a missing .trinity file is spawn's to scaffold, never the detector's to write."""

    def test_check_all_branches_writes_nothing_for_a_missing_file(self, tmp_path: Path, monkeypatch):
        branch_dir = tmp_path / "mybranch"
        branch_dir.mkdir()
        registry = {"branches": [{"name": "mybranch", "path": str(branch_dir), "status": "active"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        result = detector.check_all_branches()

        assert result["triggers"] == []
        assert not (branch_dir / ".trinity").exists()


_ROLLOVER_WITH_TODOS = {
    "defaults": {
        "local": {"sessions": {"count": 15}, "key_learnings": {"count": 15}, "todos": {"count": 10}},
        "observations": {"observations": {"count": 15}},
    },
    "per_branch": {},
}


def _todo_pad(tmp_path: Path, count: int, name: str = "mybranch") -> Path:
    """A branch whose local memory file holds *count* todos and nothing a vector family counts."""
    trinity = tmp_path / name / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    local = trinity / "local.json"
    todos = [
        {"number": n, "task": f"task {n}", "date": "2026-09-01", "priority": "normal"} for n in range(1, count + 1)
    ]
    document = {"document_metadata": {"schema_version": "3.0.0"}, "sessions": [], "key_learnings": [], "todos": todos}
    local.write_text(json.dumps(document), encoding="utf-8")
    return local


class TestTodosAreCountOnly:
    """check_todos counts ONE pad; _should_rollover and check_all_branches never see todos."""

    def test_check_todos_reports_a_pad_over_its_count(self, tmp_path: Path, monkeypatch):

        counter = MagicMock(return_value=10)
        monkeypatch.setattr(detector.config_loader, "get_todos_count", counter)
        result = detector.check_todos(_todo_pad(tmp_path, 12))

        assert result == {"success": True, "branch": "mybranch", "pad": 12, "count": 10, "over": True, "excess": 2}
        counter.assert_called_once_with("mybranch")

    def test_a_pad_at_its_count_is_not_over(self, tmp_path: Path, monkeypatch):

        monkeypatch.setattr(detector.config_loader, "get_todos_count", MagicMock(return_value=10))
        result = detector.check_todos(_todo_pad(tmp_path, 10), "Named")

        assert (result["branch"], result["over"], result["excess"]) == ("Named", False, 0)

    def test_no_usable_count_is_never_over(self, tmp_path: Path, monkeypatch):

        monkeypatch.setattr(detector.config_loader, "get_todos_count", MagicMock(return_value=None))
        result = detector.check_todos(_todo_pad(tmp_path, 40))

        assert result["success"] is True
        assert (result["count"], result["over"]) == (None, False)

    def test_todos_that_are_not_a_list_are_refused(self, tmp_path: Path):

        local = _todo_pad(tmp_path, 0)
        local.write_text(json.dumps({"todos": {"1": "not a pad"}}), encoding="utf-8")

        assert detector.check_todos(local)["success"] is False

    def test_should_rollover_never_triggers_on_todos(self, tmp_path: Path, monkeypatch):

        monkeypatch.setattr(detector.config_loader, "section", lambda name: _ROLLOVER_WITH_TODOS)
        result = detector.check_single_file(_todo_pad(tmp_path, 12))

        assert result["should_rollover"] is False
        assert "todo" not in result["v2_reason"]

    def test_check_all_branches_leaves_an_over_count_pad_alone(self, tmp_path: Path, monkeypatch):
        """The detached fleet walk rolls whatever this reports - a pad over its count must not be in it."""

        local = _todo_pad(tmp_path, 12)
        observations = {"document_metadata": {"schema_version": "3.0.0"}, "observations": []}
        (local.parent / "observations.json").write_text(json.dumps(observations), encoding="utf-8")
        before = local.read_bytes()
        registry = {"branches": [{"name": "mybranch", "path": str(tmp_path / "mybranch"), "status": "active"}]}
        (tmp_path / "AIPASS_REGISTRY.json").write_text(json.dumps(registry), encoding="utf-8")
        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        monkeypatch.setattr(detector.config_loader, "section", lambda name: _ROLLOVER_WITH_TODOS)
        counter = MagicMock(return_value=10)
        monkeypatch.setattr(detector.config_loader, "get_todos_count", counter)

        result = detector.check_all_branches()

        assert result["success"] is True
        assert result["triggers"] == []
        assert local.read_bytes() == before
        counter.assert_not_called()


class TestKnownRegistries:
    """``known_registries.json`` is retired: a caller's cwd is never remembered.

    The caller walk is scoped to THIS call, and anything outside the root is dropped
    through the write fence's own predicate before a writing lane sees it.
    """

    def test_the_persistence_api_is_gone(self):
        """No file to read, no function to write it — the door, not just the habit."""

        for name in ("persist_registry", "load_known_registries", "_KNOWN_REGISTRIES_PATH"):
            assert not hasattr(detector, name), f"detector.{name} is back — a caller's cwd would outlive the call"

    def test_a_caller_registry_is_forgotten_the_moment_the_caller_leaves(self, tmp_path: Path, monkeypatch):
        """Behavioural: a second walk from a neutral directory sees nothing the first one found."""

        home = tmp_path / "aipass_home"
        home.mkdir()
        monkeypatch.setattr(detector, "_REPO_ROOT", home)
        visited = tmp_path / "visited"
        visited.mkdir()
        (visited / "VISITED_REGISTRY.json").write_text(_ONE_BRANCH % "v", encoding="utf-8")
        neutral = tmp_path / "neutral"
        neutral.mkdir()
        monkeypatch.setattr(write_fence, "ROOT", tmp_path)

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(visited))
        assert [branch["name"] for branch in detector.read_scope()] == ["v"]

        monkeypatch.setenv("AIPASS_CALLER_CWD", str(neutral))
        assert detector.read_scope() == []

    @staticmethod
    def _home_with_memory(tmp_path: Path, monkeypatch) -> Path:
        """A fake AIPass root holding one core branch, with detector AND fence standing on it."""

        home = tmp_path / "aipass"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "memory", "path": "src/memory"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(detector, "_REPO_ROOT", home)
        monkeypatch.setattr(write_fence, "ROOT", home)
        return home

    def test_a_caller_registry_outside_the_root_never_enters_the_write_scope(self, tmp_path: Path, monkeypatch):
        """Standing in another repo adds nothing to rollover, logged once at INFO (expected, not a fault)."""

        self._home_with_memory(tmp_path, monkeypatch)
        log = MagicMock()
        monkeypatch.setattr(detector, "logger", log)
        foreign = tmp_path / "vera_like"
        (foreign / "src" / "vera").mkdir(parents=True)
        (foreign / "VERA-LIKE_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "vera", "path": "src/vera"}]}), encoding="utf-8"
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(foreign / "src" / "vera"))

        first = [branch["name"] for branch in detector.read_scope()]
        names = [branch["name"] for branch in detector.read_scope()]

        assert first == names == ["memory"]
        said = [str(call) for call in log.info.call_args_list if "VERA-LIKE_REGISTRY.json" in str(call)]
        assert len(said) == 2, f"one INFO line per walk, two walks ran: {said}"
        assert not [str(call) for call in log.warning.call_args_list if "VERA-LIKE" in str(call)]

    def test_a_caller_registry_inside_the_root_is_still_read(self, tmp_path: Path, monkeypatch):
        """Positive control: the fence narrows the walk to this root, it does not delete it."""

        home = self._home_with_memory(tmp_path, monkeypatch)
        guest = home / "projects" / "guest"
        (guest / "src" / "guest").mkdir(parents=True)
        (guest / "GUEST_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "guest", "path": "src/guest"}]}), encoding="utf-8"
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(guest))

        names = [branch["name"] for branch in detector.read_scope()]

        assert names == ["memory", "guest"]

    def test_an_inside_registry_naming_a_branch_outside_the_root_does_not_offer_it(self, tmp_path: Path, monkeypatch):
        """A registry is data; an absolute path in it can point anywhere."""

        home = self._home_with_memory(tmp_path, monkeypatch)
        guest = home / "projects" / "guest"
        guest.mkdir(parents=True)
        elsewhere = tmp_path / "elsewhere" / "b"
        elsewhere.mkdir(parents=True)
        (guest / "GUEST_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "b", "path": str(elsewhere)}]}), encoding="utf-8"
        )
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(guest))

        names = [branch["name"] for branch in detector.read_scope()]

        assert names == ["memory"]


class TestTheCallerCwdWalkReadsNamesNotSpellings:
    """The caller-cwd ``*_REGISTRY.json`` walk matches exact-case names on a case-folding filesystem.

    The bait is real (``.spawn/.template_registry.json`` sits in every branch), and the
    ``break`` means a nearer folded match hides the real registry. The condition is
    injected (conftest ``case_insensitive_filesystem``), not skipped off-platform.
    """

    @pytest.fixture
    def caller_tree(self, tmp_path, monkeypatch):
        """A caller standing in someone else's repo, with the bait beside the real file."""

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path / "aipass_home")
        monkeypatch.setattr(write_fence, "ROOT", tmp_path)
        (tmp_path / "aipass_home").mkdir()

        foreign = tmp_path / "foreign_project"
        foreign.mkdir()
        (foreign / "FOREIGN_REGISTRY.json").write_text(_ONE_BRANCH % "real", encoding="utf-8")
        (foreign / "flow_json_registry.json").write_text(_ONE_BRANCH % "bait", encoding="utf-8")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(foreign))
        return foreign

    def test_the_injected_world_really_widens(self, caller_tree, case_insensitive_filesystem):
        """Positive control — a blinded fixture reports green exactly like a cure."""
        matched = sorted(path.name for path in caller_tree.glob("*_REGISTRY.json"))

        assert matched == ["FOREIGN_REGISTRY.json", "flow_json_registry.json"]

    def test_a_lowercase_counter_file_is_never_read_as_a_registry(self, caller_tree, case_insensitive_filesystem):

        found = [branch["name"] for branch in detector.read_scope()]

        assert found == ["real"]

    def test_bait_nearer_than_the_real_registry_does_not_end_the_walk(
        self, tmp_path, monkeypatch, case_insensitive_filesystem
    ):
        """Bait nearer than the real registry must not end the walk before the real one is found."""

        monkeypatch.setattr(detector, "_REPO_ROOT", tmp_path / "aipass_home")
        monkeypatch.setattr(write_fence, "ROOT", tmp_path)
        (tmp_path / "aipass_home").mkdir()

        foreign = tmp_path / "foreign_project"
        inner = foreign / "subdir"
        inner.mkdir(parents=True)
        (foreign / "FOREIGN_REGISTRY.json").write_text(_ONE_BRANCH % "real", encoding="utf-8")
        (inner / "flow_json_registry.json").write_text(_ONE_BRANCH % "bait", encoding="utf-8")
        monkeypatch.setenv("AIPASS_CALLER_CWD", str(inner))

        found = [branch["name"] for branch in detector.read_scope()]

        assert found == ["real"]
