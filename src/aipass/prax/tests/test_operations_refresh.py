# =================== AIPass ====================
# Name: test_operations_refresh.py
# Description: Unit tests for the dashboard refresh and section writes
# Version: 1.2.0
# Created: 2026-10-08
# Modified: 2026-11-08
# =============================================

"""Tests for the refresh and section writes: apps/handlers/dashboard/refresh.py and status.py."""

# The conftest fixture _dashboard_quiet doubles the modules' logger and json service before every test.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(through_the_command) — create_fresh_dashboard, covered by tests/test_operations.py

import json
import types
from pathlib import Path

import pytest

from aipass.prax.apps.handlers.dashboard import refresh, status
from aipass.prax.tests.support_test_operations import _load_dashboard_module

pytestmark = pytest.mark.usefixtures("_dashboard_quiet")


def _load_refresh() -> types.ModuleType:
    """The refresh module, bound at the top; _dashboard_quiet doubles its edges."""
    return refresh


class TestRefreshAllDashboards:
    """Tests for refresh_all_dashboards -- full refresh from centrals."""

    def test_returns_success_when_all_branches_updated(self, tmp_path, monkeypatch):
        """Status is 'success' when every branch refreshes without error."""
        mod = _load_refresh()
        branch1 = tmp_path / "branch1"
        branch1.mkdir()
        branch2 = tmp_path / "branch2"
        branch2.mkdir()

        monkeypatch.setattr(mod, "read_all_centrals", lambda: {})
        monkeypatch.setattr(mod, "_load_branch_paths", lambda: [branch1, branch2])
        monkeypatch.setattr(
            mod,
            "create_fresh_dashboard",
            lambda bp: {
                "branch": bp.name.upper(),
                "sections": {},
                "quick_status": {},
            },
        )

        result = mod.refresh_all_dashboards()
        assert result["status"] == "success"
        assert result["branches_updated"] == 2
        assert result["branches_failed"] == 0
        assert result["errors"] == []

    def test_returns_error_when_branch_paths_fail(self, monkeypatch):
        """Status is 'error' when loading branch paths raises."""
        mod = _load_refresh()
        monkeypatch.setattr(mod, "read_all_centrals", lambda: {})

        def _raise():
            """Simulate registry load failure."""
            raise RuntimeError("registry gone")

        monkeypatch.setattr(mod, "_load_branch_paths", _raise)

        result = mod.refresh_all_dashboards()
        assert result["status"] == "error"
        assert result["branches_updated"] == 0
        assert len(result["errors"]) == 1
        assert "registry gone" in result["errors"][0]

    def test_partial_status_on_mixed_success_failure(self, tmp_path, monkeypatch):
        """Status is 'partial' when some branches succeed and some fail."""
        mod = _load_refresh()
        good_branch = tmp_path / "good"
        good_branch.mkdir()
        bad_branch = tmp_path / "bad"
        bad_branch.mkdir()

        monkeypatch.setattr(mod, "read_all_centrals", lambda: {})
        monkeypatch.setattr(mod, "_load_branch_paths", lambda: [good_branch, bad_branch])

        def flaky_create(bp):
            """Succeed for 'good', raise for 'bad'."""
            if bp.name == "bad":
                raise RuntimeError("simulated failure")
            return {
                "branch": bp.name.upper(),
                "sections": {},
                "quick_status": {},
            }

        monkeypatch.setattr(mod, "create_fresh_dashboard", flaky_create)

        result = mod.refresh_all_dashboards()
        assert result["status"] == "partial"
        assert result["branches_updated"] == 1
        assert result["branches_failed"] == 1


class TestRefreshSingleDashboard:
    """Tests for refresh_single_dashboard -- refreshes one branch."""

    def test_returns_success_for_valid_branch(self, tmp_path, monkeypatch):
        """Successful refresh returns status 'success' with branch name."""
        mod = _load_refresh()
        branch_dir = tmp_path / "flow"
        branch_dir.mkdir()

        monkeypatch.setattr(mod, "read_all_centrals", lambda: {})
        monkeypatch.setattr(
            mod,
            "create_fresh_dashboard",
            lambda bp: {
                "branch": bp.name.upper(),
                "sections": {},
                "quick_status": {},
            },
        )

        result = mod.refresh_single_dashboard(branch_dir)
        assert result["status"] == "success"
        assert result["branch"] == "FLOW"

    def test_returns_error_on_exception(self, tmp_path, monkeypatch):
        """Exception during refresh returns status 'error' with message."""
        mod = _load_refresh()
        branch_dir = tmp_path / "failing"
        branch_dir.mkdir()

        monkeypatch.setattr(mod, "read_all_centrals", lambda: {})

        def _raise(bp):
            """Always raise to simulate failure."""
            raise RuntimeError("boom")

        monkeypatch.setattr(mod, "create_fresh_dashboard", _raise)

        result = mod.refresh_single_dashboard(branch_dir)
        assert result["status"] == "error"
        assert result["branch"] == "FAILING"
        assert "boom" in result["error"]

    def test_a_branch_with_no_mail_central_row_gets_its_own_inbox_count(self, tmp_path, monkeypatch):
        """The mail count is the branch's own inbox, so a branch the central never lists is not stamped 0.

        An external project's branch has no row in AIPass's AI_MAIL.central.json
        (18 core rows, measured 2026-09-11), and its project has no mail central
        at all. The central here lists only FLOW.
        """
        mod = _load_refresh()
        verify = tmp_path / "verify"
        (verify / ".ai_mail.local").mkdir(parents=True)
        # "c" carries no status and no read flag: the reader counts that as new.
        messages = [{"id": "a", "status": "new"}, {"id": "b", "status": "new"}, {"id": "c"}]
        inbox = {"messages": [*messages, {"id": "d", "status": "opened"}]}
        (verify / ".ai_mail.local" / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")

        monkeypatch.setattr(mod, "read_all_centrals", lambda: {"ai_mail": {"branch_stats": {"FLOW": {"unread": 9}}}})
        monkeypatch.setattr(
            mod, "create_fresh_dashboard", lambda bp: {"branch": bp.name.upper(), "sections": {}, "quick_status": {}}
        )
        saved: dict = {}
        monkeypatch.setattr(mod, "save_dashboard", lambda bp, data: saved.update(data))

        assert mod.refresh_single_dashboard(verify)["status"] == "success"
        assert saved["quick_status"]["new_mail"] == 3
        assert saved["quick_status"]["opened_mail"] == 1
        assert saved["quick_status"]["summary"] == "3 new emails, 1 opened"


def _load_status() -> types.ModuleType:
    """The status module, bound at the top; _dashboard_quiet doubles its edges."""
    return status


class TestGetBranchPaths:
    """Tests for get_branch_paths -- reads registry and returns branch paths."""

    def test_returns_paths_from_registry(self, tmp_path, monkeypatch):
        """All branch paths from registry are returned as Path objects."""
        mod = _load_status()
        registry_data = {
            "branches": [
                {"name": "flow", "path": str(tmp_path / "flow"), "status": "active"},
                {"name": "ai_mail", "path": str(tmp_path / "ai_mail"), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.get_branch_paths()
        assert len(result) == 2
        assert all(isinstance(p, Path) for p in result)

    def test_raises_when_registry_missing(self, tmp_path, monkeypatch):
        """FileNotFoundError raised when AIPASS_REGISTRY.json does not exist."""
        mod = _load_status()
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", tmp_path / "nonexistent_registry.json")

        with pytest.raises(FileNotFoundError):
            mod.get_branch_paths()

    def test_handles_relative_paths(self, tmp_path, monkeypatch):
        """Relative paths in registry are resolved against repo root."""
        mod = _load_status()
        registry_data = {
            "branches": [
                {"name": "flow", "path": "src/aipass/flow", "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.get_branch_paths()
        assert len(result) == 1
        assert result[0] == tmp_path / "src" / "aipass" / "flow"


class TestResolveBranchPath:
    """Tests for resolve_branch_path -- resolves @branch ref to filesystem path."""

    @staticmethod
    def _core(root: Path, rows: list, monkeypatch, mod) -> Path:
        """Point the module at an AIPASS_REGISTRY.json under ``root`` holding ``rows``."""
        root.mkdir(parents=True, exist_ok=True)
        registry = root / "AIPASS_REGISTRY.json"
        registry.write_text(json.dumps({"branches": [dict(r, status="active") for r in rows]}), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: root)
        return root

    def test_the_first_row_wins_a_collision_and_the_log_names_both_rows(self, tmp_path, monkeypatch):
        """A name in core and at a declared root resolves to core, and the warning names both."""
        from unittest.mock import MagicMock

        mod = _load_status()
        core = self._core(tmp_path / "aipass", [{"name": "FLOW", "path": "src/flow"}], monkeypatch, mod)
        (core / "src" / "flow").mkdir(parents=True)
        studio = tmp_path / "studio"
        (studio / "flow" / ".trinity").mkdir(parents=True)
        (studio / "flow" / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
        rows = {"branches": [{"name": "flow", "path": "flow", "status": "active"}]}
        (studio / "STUDIO_REGISTRY.json").write_text(json.dumps(rows), encoding="utf-8")
        roots = {"roots": [{"path": str(studio), "status": "active"}]}
        (core / "AIPASS_ROOTS.json").write_text(json.dumps(roots), encoding="utf-8")
        log = MagicMock()
        monkeypatch.setattr(mod, "logger", log)

        assert mod.resolve_branch_path("@flow") == core / "src" / "flow"
        template, *values = log.warning.call_args.args
        rendered = template % tuple(values)
        assert "STUDIO_REGISTRY.json" in rendered
        assert str(core / "src" / "flow") in rendered
        assert str(studio / "flow") in rendered

    def test_resolves_existing_branch(self, tmp_path, monkeypatch):
        """Existing branch reference resolves to its directory path."""
        mod = _load_status()
        branch_dir = tmp_path / "flow"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {"name": "flow", "path": str(branch_dir), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.resolve_branch_path("@flow")
        assert result == branch_dir

    def test_strips_at_sign_and_is_case_insensitive(self, tmp_path, monkeypatch):
        """Leading @ is stripped and comparison is case-insensitive."""
        mod = _load_status()
        branch_dir = tmp_path / "vera"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {"name": "VERA", "path": str(branch_dir), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.resolve_branch_path("@vera")
        assert result == branch_dir

    def test_raises_when_branch_not_in_registry(self, tmp_path, monkeypatch):
        """FileNotFoundError raised when branch name is not in registry."""
        mod = _load_status()
        registry_data: dict[str, list[object]] = {"branches": []}
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        with pytest.raises(FileNotFoundError, match="not found in registry"):
            mod.resolve_branch_path("@nonexistent")

    def test_raises_when_path_does_not_exist(self, tmp_path, monkeypatch):
        """FileNotFoundError raised when branch directory does not exist."""
        mod = _load_status()
        registry_data = {
            "branches": [
                {"name": "ghost", "path": str(tmp_path / "ghost"), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        with pytest.raises(FileNotFoundError, match="does not exist"):
            mod.resolve_branch_path("@ghost")

    def test_raises_when_registry_missing(self, tmp_path, monkeypatch):
        """FileNotFoundError raised when AIPASS_REGISTRY.json is missing."""
        mod = _load_status()
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", tmp_path / "nonexistent_registry.json")

        with pytest.raises(FileNotFoundError, match="AIPASS_REGISTRY"):
            mod.resolve_branch_path("@flow")


class TestTheCensusReadsMemorysDoor:
    """A citizen at a declared root (@grow) is in every dashboard census; an undeclared sibling is not."""

    def test_get_branch_paths_lists_the_declared_external_and_not_the_stray(self, fleet, monkeypatch):
        monkeypatch.setattr(status, "AIPASS_REGISTRY", fleet.registry)
        paths = status.get_branch_paths()
        assert fleet.grow in paths
        assert fleet.flow in paths
        assert fleet.rogue not in paths

    def test_resolve_branch_path_finds_an_external_by_name(self, fleet, monkeypatch):
        monkeypatch.setattr(status, "AIPASS_REGISTRY", fleet.registry)
        assert status.resolve_branch_path("@grow") == fleet.grow
        with pytest.raises(FileNotFoundError, match="not found in registry"):
            status.resolve_branch_path("@rogue")

    def test_refresh_all_writes_the_externals_dashboard(self, fleet, monkeypatch):
        monkeypatch.setattr(refresh, "AIPASS_REGISTRY", fleet.registry)
        monkeypatch.setattr(refresh, "read_all_centrals", lambda: {})
        result = refresh.refresh_all_dashboards()
        assert result["status"] == "success"
        assert result["branches_updated"] == 2
        assert (fleet.grow / "DASHBOARD.local.json").is_file()
        assert not (fleet.rogue / "DASHBOARD.local.json").exists()


DASHBOARD_MODULE_PATH = "aipass.prax.apps.modules.dashboard"


class TestResolveBranchPathWrapper:
    """Tests for _resolve_branch_path -- dashboard module wrapper."""

    def test_delegates_to_handler(self, monkeypatch, tmp_path):
        """The handler's answer is the branch refresh @branch refreshes (prax, leg 6: through the command)."""
        mod = _load_dashboard_module()
        fake_path = tmp_path / "flow"
        refreshed: list = []

        monkeypatch.setattr(
            mod,
            "resolve_branch_path",
            lambda ref: fake_path,
        )
        monkeypatch.setattr(
            mod, "refresh_single_dashboard", lambda bp: refreshed.append(bp) or {"status": "success", "branch": "FLOW"}
        )

        mod.handle_command("dashboard", ["refresh", "@flow"])

        assert refreshed == [fake_path]
