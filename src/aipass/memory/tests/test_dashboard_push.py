# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_dashboard_push.py
# Date: 2026-04-03
# Version: 1.0.0
# Category: memory/tests
# =============================================

"""Tests for the dashboard_push handler.

Covers:
  - dashboard_push._read_central_stats (missing file, valid file)
  - dashboard_push._get_collections_count (missing DB, valid DB)
  - dashboard_push._get_rollover_config (missing config, valid config)
  - dashboard_push._get_max_lines_for_branch (override vs default)
  - dashboard_push._find_branches_near_rollover (v1 near threshold, v2 near session limit)
  - dashboard_push._get_template_version (missing file, valid file)
  - dashboard_push._get_last_rollover_info (with timestamp, empty string)
  - dashboard_push._get_all_branch_paths (with registry)
  - dashboard_push.build_memory_bank_section (integration via mocked helpers)
  - dashboard_push.push_memory_bank_dashboard (subprocess + build mock)

All tests use mocks/tmp_path -- no live filesystem or infrastructure access.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Import helper
# ---------------------------------------------------------------------------


def _import_dashboard_push(monkeypatch):
    """Import dashboard_push with mocked dependencies."""
    sys.modules.pop("aipass.memory.apps.handlers.dashboard_push", None)
    parent = sys.modules.get("aipass.memory.apps.handlers")
    if parent is not None and hasattr(parent, "dashboard_push"):
        delattr(parent, "dashboard_push")

    from aipass.memory.apps.handlers import dashboard_push

    return dashboard_push


# ===========================================================================
# Tests: _read_central_stats
# ===========================================================================


class TestReadCentralStats:
    """Test _read_central_stats helper."""

    def test_returns_defaults_when_file_missing(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "CENTRAL_FILE", tmp_path / "nonexistent.json")

        result = mod._read_central_stats()

        assert result == {"total_vectors": 0, "total_archives": 0, "last_rollover": ""}

    def test_reads_valid_central_file(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        central = tmp_path / "MEMORY.central.json"
        central.write_text(
            json.dumps(
                {"stats": {"total_vectors": 1500, "total_archives": 12, "last_rollover": "2026-03-15T10:30:00"}}
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "CENTRAL_FILE", central)

        result = mod._read_central_stats()

        assert result["total_vectors"] == 1500
        assert result["total_archives"] == 12
        assert result["last_rollover"] == "2026-03-15T10:30:00"

    def test_returns_defaults_on_corrupt_json(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        central = tmp_path / "MEMORY.central.json"
        central.write_text("not valid json{{{", encoding="utf-8")
        monkeypatch.setattr(mod, "CENTRAL_FILE", central)

        result = mod._read_central_stats()

        assert result == {"total_vectors": 0, "total_archives": 0, "last_rollover": ""}


# ===========================================================================
# Tests: _get_collections_count
# ===========================================================================


class TestGetCollectionsCount:
    """Test _get_collections_count helper."""

    def test_returns_zero_when_no_db(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "_MEMORY_ROOT", tmp_path)

        result = mod._get_collections_count()

        assert result == 0

    def test_reads_count_from_sqlite(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "_MEMORY_ROOT", tmp_path)

        import sqlite3

        chroma_dir = tmp_path / ".chroma"
        chroma_dir.mkdir()
        db_path = chroma_dir / "chroma.sqlite3"
        conn = sqlite3.connect(str(db_path))
        conn.execute("CREATE TABLE collections (id INTEGER PRIMARY KEY, name TEXT)")
        conn.execute("INSERT INTO collections VALUES (1, 'coll_a')")
        conn.execute("INSERT INTO collections VALUES (2, 'coll_b')")
        conn.execute("INSERT INTO collections VALUES (3, 'coll_c')")
        conn.commit()
        conn.close()

        result = mod._get_collections_count()

        assert result == 3


# ===========================================================================
# Tests: _get_rollover_config
# ===========================================================================


class TestGetRolloverConfig:
    """Test _get_rollover_config helper."""

    def test_returns_defaults_when_no_config(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "CONFIG_PATH", tmp_path / "missing_config.json")

        result = mod._get_rollover_config()

        assert result == {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}

    def test_loads_valid_config(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        config_file = tmp_path / "memory_bank.config.json"
        config_file.write_text(
            json.dumps(
                {
                    "rollover": {
                        "defaults": {"max_lines": 800, "buffer": 150},
                        "per_branch": {"NEXUS": {"max_lines": 1200}},
                    }
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "CONFIG_PATH", config_file)

        result = mod._get_rollover_config()

        assert result["defaults"]["max_lines"] == 800
        assert result["defaults"]["buffer"] == 150
        assert result["per_branch"]["NEXUS"]["max_lines"] == 1200

    def test_returns_defaults_on_corrupt_config(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        config_file = tmp_path / "broken.json"
        config_file.write_text("{invalid", encoding="utf-8")
        monkeypatch.setattr(mod, "CONFIG_PATH", config_file)

        result = mod._get_rollover_config()

        assert result == {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}


# ===========================================================================
# Tests: _get_max_lines_for_branch
# ===========================================================================


class TestGetMaxLinesForBranch:
    """Test _get_max_lines_for_branch helper."""

    def test_returns_default_when_no_override(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        config = {"defaults": {"max_lines": 600}, "per_branch": {}}

        result = mod._get_max_lines_for_branch("DEVPULSE", config)

        assert result == 600

    def test_returns_override_when_present(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        config = {"defaults": {"max_lines": 600}, "per_branch": {"NEXUS": {"max_lines": 1200}}}

        result = mod._get_max_lines_for_branch("NEXUS", config)

        assert result == 1200

    def test_falls_back_to_default_when_override_missing_max_lines(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        config = {"defaults": {"max_lines": 600}, "per_branch": {"DRONE": {"buffer": 200}}}

        result = mod._get_max_lines_for_branch("DRONE", config)

        assert result == 600


# ===========================================================================
# Tests: _find_branches_near_rollover
# ===========================================================================


class TestFindBranchesNearRollover:
    """Test _find_branches_near_rollover helper."""

    def test_returns_empty_when_no_registry(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", tmp_path / "no_registry.json")

        result = mod._find_branches_near_rollover()

        assert result == []

    def test_v1_file_near_threshold(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        # Build branch with a v1 memory file near rollover
        branch_dir = tmp_path / "src" / "aipass" / "test_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text(
            json.dumps({"document_metadata": {"schema_version": "1.0.0", "status": {"current_lines": 550}}}),
            encoding="utf-8",
        )

        # Registry pointing to branch
        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "TEST_BRANCH", "path": str(branch_dir)}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)

        # Config: max_lines=600, so 600-550=50 remaining (<100 threshold)
        monkeypatch.setattr(
            mod, "_get_rollover_config", lambda: {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}
        )
        monkeypatch.setattr(mod, "NEAR_ROLLOVER_THRESHOLD", 100)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._find_branches_near_rollover()

        assert len(result) == 1
        assert result[0]["branch"] == "TEST_BRANCH"
        assert result[0]["file_type"] == "local"
        assert result[0]["lines_remaining"] == 50
        assert result[0]["current_lines"] == 550

    def test_v1_file_not_near_threshold(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        branch_dir = tmp_path / "src" / "aipass" / "safe_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text(
            json.dumps({"document_metadata": {"schema_version": "1.0.0", "status": {"current_lines": 200}}}),
            encoding="utf-8",
        )

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "SAFE_BRANCH", "path": str(branch_dir)}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(
            mod, "_get_rollover_config", lambda: {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}
        )
        monkeypatch.setattr(mod, "NEAR_ROLLOVER_THRESHOLD", 100)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._find_branches_near_rollover()

        assert result == []

    def test_v2_file_near_session_limit(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        branch_dir = tmp_path / "src" / "aipass" / "v2_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text(
            json.dumps(
                {
                    "document_metadata": {
                        "schema_version": "2.0.0",
                        "limits": {"max_sessions": 20, "max_key_learnings": 25},
                    },
                    "sessions": [{"id": i} for i in range(19)],  # 19 of 20 sessions
                    "key_learnings": {"k1": "v1"},
                }
            ),
            encoding="utf-8",
        )

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "V2_BRANCH", "path": str(branch_dir)}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(
            mod, "_get_rollover_config", lambda: {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._find_branches_near_rollover()

        # sessions: 20-19=1 remaining (<3) -> reported
        # key_learnings: 25-1=24 remaining (>=3) -> not reported
        assert len(result) == 1
        assert result[0]["branch"] == "V2_BRANCH"
        assert result[0]["v2_field"] == "sessions"
        assert result[0]["lines_remaining"] == 1

    def test_v2_file_near_key_learnings_limit(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        branch_dir = tmp_path / "src" / "aipass" / "kl_branch"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "local.json").write_text(
            json.dumps(
                {
                    "document_metadata": {
                        "schema_version": "2.0.0",
                        "limits": {"max_sessions": 20, "max_key_learnings": 5},
                    },
                    "sessions": [{"id": 1}],
                    "key_learnings": {f"k{i}": f"v{i}" for i in range(4)},  # 4 of 5
                }
            ),
            encoding="utf-8",
        )

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "KL_BRANCH", "path": str(branch_dir)}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(
            mod, "_get_rollover_config", lambda: {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._find_branches_near_rollover()

        # key_learnings: 5-4=1 remaining (<3) -> reported
        assert len(result) == 1
        assert result[0]["v2_field"] == "key_learnings"
        assert result[0]["lines_remaining"] == 1

    def test_skips_nonexistent_branch_paths(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "GHOST", "path": str(tmp_path / "nonexistent")}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(
            mod, "_get_rollover_config", lambda: {"defaults": {"max_lines": 600, "buffer": 100}, "per_branch": {}}
        )
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._find_branches_near_rollover()

        assert result == []


# ===========================================================================
# Tests: _get_template_version
# ===========================================================================


class TestGetTemplateVersion:
    """Test _get_template_version helper."""

    def test_returns_unknown_when_file_missing(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "TEMPLATE_VERSION_FILE", tmp_path / "nope.json")

        result = mod._get_template_version()

        assert result == "unknown"

    def test_reads_valid_version(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        version_file = tmp_path / ".template_version.json"
        version_file.write_text(json.dumps({"version": "2.0.4"}), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_VERSION_FILE", version_file)

        result = mod._get_template_version()

        assert result == "2.0.4"

    def test_returns_unknown_when_version_key_absent(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        version_file = tmp_path / ".template_version.json"
        version_file.write_text(json.dumps({"name": "templates"}), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_VERSION_FILE", version_file)

        result = mod._get_template_version()

        assert result == "unknown"


# ===========================================================================
# Tests: _get_last_rollover_info
# ===========================================================================


class TestGetLastRolloverInfo:
    """Test _get_last_rollover_info helper."""

    def test_parses_iso_timestamp(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        stats = {"last_rollover": "2026-03-15T10:30:00"}

        result = mod._get_last_rollover_info(stats)

        assert result == {"date": "2026-03-15"}

    def test_returns_never_for_empty_string(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        stats = {"last_rollover": ""}

        result = mod._get_last_rollover_info(stats)

        assert result == {"date": "never"}

    def test_returns_never_when_key_missing(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        stats = {}

        result = mod._get_last_rollover_info(stats)

        assert result == {"date": "never"}

    def test_returns_raw_string_on_unparseable_timestamp(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)
        stats = {"last_rollover": "some-invalid-date"}

        result = mod._get_last_rollover_info(stats)

        assert result == {"date": "some-invalid-date"}


# ===========================================================================
# Tests: _get_all_branch_paths
# ===========================================================================


class TestGetAllBranchPaths:
    """Test _get_all_branch_paths helper."""

    def test_returns_empty_when_no_registry(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", tmp_path / "no_registry.json")

        result = mod._get_all_branch_paths()

        assert result == []

    def test_returns_existing_branch_paths(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        branch_a = tmp_path / "branch_a"
        branch_b = tmp_path / "branch_b"
        branch_a.mkdir()
        branch_b.mkdir()

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "branches": [
                        {"name": "A", "path": str(branch_a)},
                        {"name": "B", "path": str(branch_b)},
                        {"name": "C", "path": str(tmp_path / "nonexistent")},
                    ]
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._get_all_branch_paths()

        assert len(result) == 2
        assert branch_a in result
        assert branch_b in result

    def test_resolves_relative_paths(self, monkeypatch, tmp_path):
        mod = _import_dashboard_push(monkeypatch)

        branch_dir = tmp_path / "src" / "aipass" / "test_branch"
        branch_dir.mkdir(parents=True)

        registry = tmp_path / "AIPASS_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": "TEST", "path": "src/aipass/test_branch"}]}), encoding="utf-8"
        )
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod._get_all_branch_paths()

        assert len(result) == 1
        assert result[0] == branch_dir


# ===========================================================================
# Tests: build_memory_bank_section (public)
# ===========================================================================


class TestBuildMemoryBankSection:
    """Test build_memory_bank_section with mocked helpers."""

    def test_assembles_section_data(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)

        monkeypatch.setattr(
            mod,
            "_read_central_stats",
            lambda: {"total_vectors": 2500, "total_archives": 15, "last_rollover": "2026-03-20T12:00:00"},
        )
        monkeypatch.setattr(
            mod,
            "_find_branches_near_rollover",
            lambda: [{"branch": "NEXUS", "file_type": "local", "lines_remaining": 30}],
        )
        monkeypatch.setattr(mod, "_get_last_rollover_info", lambda s: {"date": "2026-03-20"})
        monkeypatch.setattr(mod, "_get_template_version", lambda: "2.0.4")
        monkeypatch.setattr(mod, "_get_collections_count", lambda: 8)

        result = mod.build_memory_bank_section()

        assert result["managed_by"] == "memory_bank"
        assert result["total_vectors"] == 2500
        assert result["collections_count"] == 8
        assert len(result["branches_near_rollover"]) == 1
        assert result["branches_near_rollover"][0]["branch"] == "NEXUS"
        assert result["last_rollover"] == {"date": "2026-03-20"}
        assert result["template_version"] == "2.0.4"


# ===========================================================================
# Tests: push_memory_bank_dashboard (public)
# ===========================================================================


class TestPushMemoryBankDashboard:
    """Test push_memory_bank_dashboard."""

    def test_returns_true_when_at_least_one_updated(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)

        mock_section = {"managed_by": "memory_bank", "total_vectors": 100}
        monkeypatch.setattr(mod, "build_memory_bank_section", lambda: mock_section)
        monkeypatch.setattr(mod, "_get_all_branch_paths", lambda: [Path("/tmp/a")])
        monkeypatch.setattr(mod, "_write_section_to_all_branches", lambda name, data, paths: 1)

        result = mod.push_memory_bank_dashboard()

        assert result is True

    def test_returns_false_when_no_dashboards_updated(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)

        monkeypatch.setattr(mod, "build_memory_bank_section", lambda: {"managed_by": "memory_bank"})
        monkeypatch.setattr(mod, "_get_all_branch_paths", lambda: [])
        monkeypatch.setattr(mod, "_write_section_to_all_branches", lambda name, data, paths: 0)

        result = mod.push_memory_bank_dashboard()

        assert result is False

    def test_logs_operation_on_success(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)

        monkeypatch.setattr(mod, "build_memory_bank_section", lambda: {"managed_by": "memory_bank"})
        monkeypatch.setattr(mod, "_get_all_branch_paths", lambda: [Path("/tmp/a")])
        monkeypatch.setattr(mod, "_write_section_to_all_branches", lambda name, data, paths: 3)

        mock_jh = MagicMock()
        monkeypatch.setattr(mod, "json_handler", mock_jh)

        mod.push_memory_bank_dashboard()

        mock_jh.log_operation.assert_called_once_with("dashboard_push", {"branches_updated": 3, "success": True})

    def test_returns_false_on_exception(self, monkeypatch):
        mod = _import_dashboard_push(monkeypatch)

        monkeypatch.setattr(mod, "build_memory_bank_section", MagicMock(side_effect=RuntimeError("boom")))

        result = mod.push_memory_bank_dashboard()

        assert result is False
