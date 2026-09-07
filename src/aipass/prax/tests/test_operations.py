# =================== AIPass ====================
# Name: test_operations.py
# Description: Unit tests for dashboard operations handler
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

"""Unit tests for aipass.prax.apps.handlers.dashboard.operations.

Because conftest.py patches sys.modules with autouse mocks before imports,
the module under test is imported INSIDE each test function via importlib
to ensure the mocked dependencies are in place.
"""

import importlib
import json
import sys
import types
from pathlib import Path

import pytest


MODULE_PATH = "aipass.prax.apps.handlers.dashboard.operations"


def _load_ops():
    """Import (or reimport) the operations module under active mocks."""
    sys.modules.pop(MODULE_PATH, None)
    import aipass.prax.apps.handlers.dashboard.operations as mod

    importlib.reload(mod)
    return mod


# =============================================
# get_dashboard_path
# =============================================


class TestGetDashboardPath:
    """Tests for get_dashboard_path -- pure path joining."""

    def test_returns_dashboard_path_from_path_input(self, tmp_path):
        """Result is branch_path / DASHBOARD.local.json."""
        ops = _load_ops()
        result = ops.get_dashboard_path(tmp_path)
        assert result == tmp_path / "DASHBOARD.local.json"

    def test_returns_path_type(self, tmp_path):
        """Return value is a pathlib.Path instance."""
        ops = _load_ops()
        result = ops.get_dashboard_path(tmp_path)
        assert isinstance(result, Path)

    def test_works_with_nested_branch_path(self, tmp_path):
        """Deeply nested branch paths still resolve correctly."""
        ops = _load_ops()
        nested = tmp_path / "src" / "aipass" / "flow"
        result = ops.get_dashboard_path(nested)
        assert result == nested / "DASHBOARD.local.json"


# =============================================
# load_dashboard
# =============================================


class TestLoadDashboard:
    """Tests for load_dashboard -- file I/O with fallback to template."""

    def _make_template(self):
        """Build a minimal dashboard template for test use."""
        return {
            "branch": "TEMPLATE",
            "last_updated": "",
            "sections": {
                "ai_mail": {"new": 0},
                "flow": {"active_plans": 0},
            },
        }

    def test_loads_existing_dashboard(self, tmp_path):
        """Existing dashboard file is loaded and returned as dict."""
        ops = _load_ops()
        branch_dir = tmp_path / "mybranch"
        branch_dir.mkdir()
        dashboard_data = {
            "branch": "MYBRANCH",
            "last_updated": "2026-01-01",
            "sections": {"flow": {"active_plans": 5}},
        }
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps(dashboard_data), encoding="utf-8")

        result = ops.load_dashboard(branch_dir, self._make_template())
        assert result["branch"] == "MYBRANCH"
        assert result["sections"]["flow"]["active_plans"] == 5

    def test_returns_template_when_file_missing(self, tmp_path):
        """Missing dashboard file triggers template fallback with branch name set."""
        ops = _load_ops()
        branch_dir = tmp_path / "nobranch"
        branch_dir.mkdir()
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        # Branch name should be set from directory name uppercased
        assert result["branch"] == "NOBRANCH"
        assert "sections" in result

    def test_returns_template_on_corrupted_json(self, tmp_path):
        """Corrupted JSON falls back to template."""
        ops = _load_ops()
        branch_dir = tmp_path / "broken"
        branch_dir.mkdir()
        (branch_dir / "DASHBOARD.local.json").write_text("{not valid json!!!", encoding="utf-8")
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        assert result["branch"] == "BROKEN"
        assert result["sections"] == template["sections"]

    def test_returns_template_on_empty_file(self, tmp_path):
        """Empty file is treated as missing and falls back to template."""
        ops = _load_ops()
        branch_dir = tmp_path / "empty"
        branch_dir.mkdir()
        (branch_dir / "DASHBOARD.local.json").write_text("", encoding="utf-8")
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        assert result["branch"] == "EMPTY"

    def test_load_dashboard_with_non_dict_json(self, tmp_path):
        """A file containing valid JSON that is not a dict returns the template."""
        ops = _load_ops()
        branch_dir = tmp_path / "arrayfile"
        branch_dir.mkdir()
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        # Non-dict JSON falls back to template
        assert result["branch"] == "ARRAYFILE"
        assert result["sections"] == template["sections"]

    def test_adds_sections_when_missing_from_existing_file(self, tmp_path):
        """Valid JSON dict missing the sections key gets sections from template."""
        ops = _load_ops()
        branch_dir = tmp_path / "nosections"
        branch_dir.mkdir()
        # Valid JSON but missing "sections" key
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps({"branch": "NOSECTIONS", "last_updated": "2026-01-01"}),
            encoding="utf-8",
        )
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        assert "sections" in result
        assert result["sections"] == template["sections"]


# =============================================
# save_dashboard
# =============================================


class TestSaveDashboard:
    """Tests for save_dashboard -- file write with timestamp update."""

    def test_creates_dashboard_file(self, tmp_path):
        """Dashboard file is created on disk."""
        ops = _load_ops()
        branch_dir = tmp_path / "savebranch"
        branch_dir.mkdir()
        data = {"branch": "SAVEBRANCH", "sections": {}}

        result = ops.save_dashboard(branch_dir, data)
        assert result is True
        assert (branch_dir / "DASHBOARD.local.json").exists()

    def test_writes_valid_json(self, tmp_path):
        """Written file contains valid, parseable JSON."""
        ops = _load_ops()
        branch_dir = tmp_path / "jsoncheck"
        branch_dir.mkdir()
        data = {"branch": "JSONCHECK", "sections": {"flow": {"active_plans": 3}}}

        ops.save_dashboard(branch_dir, data)
        content = (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        loaded = json.loads(content)
        assert loaded["branch"] == "JSONCHECK"
        assert loaded["sections"]["flow"]["active_plans"] == 3

    def test_sets_last_updated_timestamp(self, tmp_path):
        """Saved file contains a non-empty ISO-format last_updated timestamp."""
        ops = _load_ops()
        branch_dir = tmp_path / "timestamp"
        branch_dir.mkdir()
        data = {"branch": "TIMESTAMP", "sections": {}}

        ops.save_dashboard(branch_dir, data)
        content = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert "last_updated" in content
        # Should be a non-empty ISO-format string
        assert len(content["last_updated"]) > 0
        assert "T" in content["last_updated"]

    def test_returns_true_on_success(self, tmp_path):
        """Return value is True on successful save."""
        ops = _load_ops()
        branch_dir = tmp_path / "retval"
        branch_dir.mkdir()

        result = ops.save_dashboard(branch_dir, {"branch": "RV"})
        assert result is True


# =============================================
# write_section
# =============================================


class TestWriteSection:
    """Tests for write_section -- orchestration of load/update/save."""

    def test_creates_dashboard_if_none_exists(self, tmp_path):
        """A new dashboard file is created when none exists."""
        ops = _load_ops()
        branch_dir = tmp_path / "newbranch"
        branch_dir.mkdir()

        result = ops.write_section(branch_dir, "flow", {"active_plans": 2})
        assert result is True
        dashboard_path = branch_dir / "DASHBOARD.local.json"
        assert dashboard_path.exists()
        data = json.loads(dashboard_path.read_text(encoding="utf-8"))
        assert data["sections"]["flow"]["active_plans"] == 2

    def test_updates_existing_section(self, tmp_path):
        """An existing section is replaced with new data."""
        ops = _load_ops()
        branch_dir = tmp_path / "updatebranch"
        branch_dir.mkdir()
        # Pre-populate a dashboard
        existing = {
            "branch": "UPDATEBRANCH",
            "last_updated": "2026-01-01",
            "sections": {
                "flow": {"active_plans": 1, "last_updated": "2026-01-01"},
                "ai_mail": {"new": 5, "last_updated": "2026-01-01"},
            },
        }
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps(existing), encoding="utf-8")

        ops.write_section(branch_dir, "flow", {"active_plans": 7})
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert data["sections"]["flow"]["active_plans"] == 7

    def test_preserves_other_sections(self, tmp_path):
        """Sections not being updated remain untouched."""
        ops = _load_ops()
        branch_dir = tmp_path / "preserve"
        branch_dir.mkdir()
        existing = {
            "branch": "PRESERVE",
            "last_updated": "2026-01-01",
            "sections": {
                "ai_mail": {"new": 3, "opened": 1, "last_updated": "2026-01-01"},
            },
        }
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps(existing), encoding="utf-8")

        ops.write_section(branch_dir, "flow", {"active_plans": 4})
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        # ai_mail should still be present and unchanged
        assert data["sections"]["ai_mail"]["new"] == 3
        assert data["sections"]["ai_mail"]["opened"] == 1

    def test_adds_last_updated_to_section(self, tmp_path):
        """Section data gets an ISO last_updated timestamp added."""
        ops = _load_ops()
        branch_dir = tmp_path / "sectstamp"
        branch_dir.mkdir()

        ops.write_section(branch_dir, "flow", {"active_plans": 1})
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert "last_updated" in data["sections"]["flow"]
        assert "T" in data["sections"]["flow"]["last_updated"]

    def test_returns_false_on_error(self, tmp_path):
        """Non-writable path returns False instead of raising."""
        ops = _load_ops()
        # Use a file as parent so mkdir fails on all platforms
        blocker = tmp_path / "blocker"
        blocker.write_text("I am a file", encoding="utf-8")
        impossible_branch = blocker / "subdir" / "branch"

        result = ops.write_section(impossible_branch, "flow", {"active_plans": 1})
        assert result is False


# =============================================
# _calculate_quick_status_standalone
# =============================================


class TestCalculateQuickStatusStandalone:
    """Tests for _calculate_quick_status_standalone -- pure calculation."""

    def test_empty_sections_returns_defaults(self, tmp_path):
        """Empty sections produce zeroed counters and 'All clear' summary."""
        ops = _load_ops()
        result = ops._calculate_quick_status_standalone({}, tmp_path)
        assert result["new_mail"] == 0
        assert result["opened_mail"] == 0
        assert result["active_plans"] == 0
        assert result["action_required"] is False
        assert result["summary"] == "All clear"

    def test_new_mail_triggers_action_required(self, tmp_path):
        """New mail count > 0 sets action_required to True (sourced from inbox.json)."""
        ops = _load_ops()
        mail_dir = tmp_path / ".ai_mail.local"
        mail_dir.mkdir()
        inbox = {
            "messages": [
                {"id": "1", "status": "new"},
                {"id": "2", "status": "new"},
                {"id": "3", "status": "new"},
            ]
        }
        (mail_dir / "inbox.json").write_text(json.dumps(inbox))
        result = ops._calculate_quick_status_standalone({}, tmp_path)
        assert result["new_mail"] == 3
        assert result["action_required"] is True
        assert "3 new emails" in result["summary"]

    def test_active_plans_triggers_action_required(self, tmp_path):
        """Active plans > 0 sets action_required to True."""
        ops = _load_ops()
        sections = {"flow": {"active_plans": 2}}
        result = ops._calculate_quick_status_standalone(sections, tmp_path)
        assert result["active_plans"] == 2
        assert result["action_required"] is True
        assert "2 active plans" in result["summary"]

    def test_combined_summary_includes_all_parts(self, tmp_path):
        """Summary string includes all active counts."""
        ops = _load_ops()
        mail_dir = tmp_path / ".ai_mail.local"
        mail_dir.mkdir()
        inbox = {
            "messages": [
                {"id": "1", "status": "new"},
                {"id": "2", "status": "new"},
                {"id": "3", "status": "opened"},
            ]
        }
        (mail_dir / "inbox.json").write_text(json.dumps(inbox))
        sections = {"flow": {"active_plans": 3}}
        result = ops._calculate_quick_status_standalone(sections, tmp_path)
        assert result["action_required"] is True
        assert "2 new emails" in result["summary"]
        assert "1 opened" in result["summary"]
        assert "3 active plans" in result["summary"]

    def test_mail_counts_from_inbox_json(self, tmp_path):
        """Mail counts sourced from inbox.json status fields."""
        ops = _load_ops()
        mail_dir = tmp_path / ".ai_mail.local"
        mail_dir.mkdir()
        inbox = {
            "messages": [
                {"id": "1", "status": "new"},
                {"id": "2", "status": "new"},
                {"id": "3", "status": "new"},
                {"id": "4", "status": "new"},
                {"id": "5", "status": "new"},
                {"id": "6", "status": "new"},
                {"id": "7", "status": "new"},
            ]
        }
        (mail_dir / "inbox.json").write_text(json.dumps(inbox))
        result = ops._calculate_quick_status_standalone({}, tmp_path)
        assert result["new_mail"] == 7
        assert result["action_required"] is True


# =============================================
# create_fresh_dashboard (operations.py)
# =============================================


class TestCreateFreshDashboard:
    """Tests for create_fresh_dashboard -- template or hardcoded fallback."""

    def test_fallback_hardcoded_when_no_template_file(self, tmp_path):
        """When template file does not exist, returns hardcoded dashboard."""
        ops = _load_ops()
        fake_prax = tmp_path / "prax"
        fake_prax.mkdir()
        original = ops._PRAX_ROOT
        ops._PRAX_ROOT = fake_prax

        try:
            branch_dir = tmp_path / "mybranch"
            branch_dir.mkdir()
            result = ops.create_fresh_dashboard(branch_dir)

            assert result["branch"] == "MYBRANCH"
            assert "last_updated" in result
            assert result["last_updated"] != ""
            assert "_warning" in result
            assert "sections" in result
            assert "ai_mail" in result["sections"]
            assert "flow" in result["sections"]
            assert "memory" in result["sections"]
            assert "commons_activity" not in result["sections"]
            assert result["quick_status"]["action_required"] is False
        finally:
            ops._PRAX_ROOT = original

    def test_loads_from_template_file(self, tmp_path):
        """When template file exists, uses it and replaces placeholders."""
        ops = _load_ops()
        fake_prax = tmp_path / "prax"
        templates_dir = fake_prax / "templates"
        templates_dir.mkdir(parents=True)

        template_data = {
            "_warning": "AUTO-GENERATED",
            "branch": "{{BRANCHNAME}}",
            "last_updated": "",
            "sections": {
                "ai_mail": {"managed_by": "ai_mail", "new": 0},
            },
            "quick_status": {"action_required": False},
        }
        (templates_dir / "DASHBOARD.template.json").write_text(json.dumps(template_data), encoding="utf-8")

        original = ops._PRAX_ROOT
        ops._PRAX_ROOT = fake_prax
        try:
            branch_dir = tmp_path / "flow"
            branch_dir.mkdir()
            result = ops.create_fresh_dashboard(branch_dir)

            assert result["branch"] == "FLOW"
            assert result["last_updated"] != ""
            assert result["sections"]["ai_mail"]["new"] == 0
        finally:
            ops._PRAX_ROOT = original

    def test_falls_back_on_corrupted_template(self, tmp_path):
        """If template JSON is invalid, falls back to hardcoded structure."""
        ops = _load_ops()
        fake_prax = tmp_path / "prax"
        templates_dir = fake_prax / "templates"
        templates_dir.mkdir(parents=True)
        (templates_dir / "DASHBOARD.template.json").write_text("{bad json!!", encoding="utf-8")

        original = ops._PRAX_ROOT
        ops._PRAX_ROOT = fake_prax
        try:
            branch_dir = tmp_path / "broken"
            branch_dir.mkdir()
            result = ops.create_fresh_dashboard(branch_dir)

            # Should still return a valid hardcoded dashboard
            assert result["branch"] == "BROKEN"
            assert "sections" in result
            assert "_warning" in result
        finally:
            ops._PRAX_ROOT = original


# =============================================
# update_section (operations.py -- legacy interface)
# =============================================


class TestUpdateSectionLegacy:
    """Tests for update_section -- legacy interface with template and status func."""

    def test_updates_section_and_calls_status_func(self, tmp_path):
        """Section is written and calculate_status_func is invoked with live data."""
        ops = _load_ops()
        branch_dir = tmp_path / "testbranch"
        branch_dir.mkdir()
        template = {
            "branch": "",
            "last_updated": "",
            "sections": {"ai_mail": {"new": 0}},
        }
        status_called_with: dict[str, object] = {}

        def mock_status(sections, branch_path=None):
            """Capture sections passed to status calculator."""
            status_called_with.update(sections)
            return {"action_required": True, "summary": "test"}

        result = ops.update_section(branch_dir, "ai_mail", {"new": 5}, template, mock_status)
        assert result is True
        # Verify status function was called with sections containing our data
        assert "ai_mail" in status_called_with
        assert status_called_with["ai_mail"]["new"] == 5  # type: ignore[union-attr]

        # Verify the file was written
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert data["sections"]["ai_mail"]["new"] == 5
        assert data["quick_status"]["action_required"] is True

    def test_creates_sections_dict_if_missing(self, tmp_path):
        """Dashboard without sections key gets one created during update."""
        ops = _load_ops()
        branch_dir = tmp_path / "nosections"
        branch_dir.mkdir()
        # Pre-populate dashboard without sections key
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps({"branch": "NOSECTIONS", "last_updated": ""}),
            encoding="utf-8",
        )
        template = {
            "branch": "",
            "last_updated": "",
            "sections": {},
        }

        result = ops.update_section(
            branch_dir,
            "flow",
            {"active_plans": 2},
            template,
            lambda s, bp=None: {"action_required": False},
        )
        assert result is True
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert data["sections"]["flow"]["active_plans"] == 2


# =============================================
# refresh_all_dashboards (refresh.py)
# =============================================

REFRESH_MODULE_PATH = "aipass.prax.apps.handlers.dashboard.refresh"


def _load_refresh() -> types.ModuleType:
    """Import (or reimport) the refresh module under active mocks."""
    sys.modules.pop(REFRESH_MODULE_PATH, None)
    sys.modules.pop("aipass.prax.apps.handlers.dashboard.operations", None)
    import aipass.prax.apps.handlers.dashboard.refresh as mod

    importlib.reload(mod)
    return mod


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


# =============================================
# refresh_single_dashboard (refresh.py)
# =============================================


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


# =============================================
# get_branch_paths (status.py)
# =============================================

STATUS_MODULE_PATH = "aipass.prax.apps.handlers.dashboard.status"


def _load_status() -> types.ModuleType:
    """Import (or reimport) the status module under active mocks."""
    sys.modules.pop(STATUS_MODULE_PATH, None)
    import aipass.prax.apps.handlers.dashboard.status as mod

    importlib.reload(mod)
    return mod


class TestGetBranchPaths:
    """Tests for get_branch_paths -- reads registry and returns branch paths."""

    def test_returns_paths_from_registry(self, tmp_path, monkeypatch):
        """All branch paths from registry are returned as Path objects."""
        mod = _load_status()
        registry_data = {
            "branches": [
                {"name": "flow", "path": str(tmp_path / "flow")},
                {"name": "ai_mail", "path": str(tmp_path / "ai_mail")},
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
                {"name": "flow", "path": "src/aipass/flow"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")

        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.get_branch_paths()
        assert len(result) == 1
        assert result[0] == tmp_path / "src" / "aipass" / "flow"


# =============================================
# resolve_branch_path (status.py)
# =============================================


class TestResolveBranchPath:
    """Tests for resolve_branch_path -- resolves @branch ref to filesystem path."""

    def test_resolves_existing_branch(self, tmp_path, monkeypatch):
        """Existing branch reference resolves to its directory path."""
        mod = _load_status()
        branch_dir = tmp_path / "flow"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {"name": "flow", "path": str(branch_dir)},
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
                {"name": "VERA", "path": str(branch_dir)},
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
                {"name": "ghost", "path": str(tmp_path / "ghost")},
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


# =============================================
# diff_dashboard_template (template_differ.py)
# =============================================

DIFFER_MODULE_PATH = "aipass.prax.apps.handlers.dashboard.template_differ"


def _load_differ() -> types.ModuleType:
    """Import (or reimport) the template_differ module under active mocks."""
    sys.modules.pop(DIFFER_MODULE_PATH, None)
    import aipass.prax.apps.handlers.dashboard.template_differ as mod

    importlib.reload(mod)
    return mod


class TestDiffDashboardTemplate:
    """Tests for diff_dashboard_template -- compares template vs dashboards."""

    def _make_template(self):
        """Build a full dashboard template dict for diff tests."""
        return {
            "_warning": "AUTO-GENERATED",
            "branch": "{{BRANCHNAME}}",
            "sections": {
                "ai_mail": {
                    "managed_by": "ai_mail",
                    "new": 0,
                    "last_updated": "",
                },
                "flow": {
                    "managed_by": "flow",
                    "active_plans": 0,
                    "last_updated": "",
                },
                "memory": {"managed_by": "memory", "last_updated": ""},
            },
            "quick_status": {
                "new_mail": 0,
                "opened_mail": 0,
                "active_plans": 0,
                "action_required": False,
                "summary": "",
            },
        }

    def test_returns_error_when_template_missing(self, tmp_path, monkeypatch):
        """Error dict returned when template file does not exist."""
        mod = _load_differ()
        monkeypatch.setattr(mod, "TEMPLATE_FILE", tmp_path / "nofile.json")

        result = mod.diff_dashboard_template()
        assert "error" in result
        assert "not found" in result["error"]

    def test_reports_up_to_date_branch(self, tmp_path, monkeypatch):
        """Branch matching template schema reports status 'up_to_date'."""
        mod = _load_differ()

        template = self._make_template()
        template_file = tmp_path / "template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", template_file)

        branch_dir = tmp_path / "flow"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {"name": "FLOW", "path": str(branch_dir), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        dashboard = {
            "_warning": "AUTO-GENERATED",
            "branch": "FLOW",
            "sections": {
                "ai_mail": {
                    "managed_by": "ai_mail",
                    "new": 0,
                    "last_updated": "2026-01-01",
                },
                "flow": {
                    "managed_by": "flow",
                    "active_plans": 0,
                    "last_updated": "2026-01-01",
                },
                "memory": {"managed_by": "memory", "last_updated": "2026-01-01"},
            },
            "quick_status": {
                "new_mail": 0,
                "opened_mail": 0,
                "active_plans": 0,
                "action_required": False,
                "summary": "",
            },
        }
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps(dashboard), encoding="utf-8")

        result = mod.diff_dashboard_template()
        assert result["summary"]["up_to_date"] == 1
        assert result["summary"]["needs_update"] == 0

    def test_reports_missing_dashboard(self, tmp_path, monkeypatch):
        """Branch without a DASHBOARD.local.json reports status 'missing'."""
        mod = _load_differ()

        template = self._make_template()
        template_file = tmp_path / "template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", template_file)

        branch_dir = tmp_path / "nobranch"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {
                    "name": "NOBRANCH",
                    "path": str(branch_dir),
                    "status": "active",
                },
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.diff_dashboard_template()
        assert result["summary"]["missing"] == 1

    def test_detects_deprecated_sections(self, tmp_path, monkeypatch):
        """Deprecated sections in dashboard are flagged for removal."""
        mod = _load_differ()

        template = self._make_template()
        template_file = tmp_path / "template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", template_file)

        branch_dir = tmp_path / "oldbranch"
        branch_dir.mkdir()
        registry_data = {
            "branches": [
                {
                    "name": "OLDBRANCH",
                    "path": str(branch_dir),
                    "status": "active",
                },
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        dashboard = {
            "_warning": "AUTO-GENERATED",
            "branch": "OLDBRANCH",
            "sections": {
                "ai_mail": {"new": 0, "last_updated": ""},
                "flow": {"active_plans": 0, "last_updated": ""},
                "memory": {"last_updated": ""},
                "commons_activity": {"last_updated": ""},
                "bulletin_board": {"posts": 0, "last_updated": ""},
            },
            "quick_status": {
                "new_mail": 0,
                "opened_mail": 0,
                "active_plans": 0,
                "commons_mentions": 0,
                "action_required": False,
                "summary": "",
            },
        }
        # commons_activity, bulletin_board, commons_mentions are deprecated — push should remove them
        (branch_dir / "DASHBOARD.local.json").write_text(json.dumps(dashboard), encoding="utf-8")

        result = mod.diff_dashboard_template()
        assert result["summary"]["needs_update"] == 1
        branch_diff = result["branches"][0]
        assert any("bulletin_board" in r for r in branch_diff["removals"])

    def test_filters_to_single_branch(self, tmp_path, monkeypatch):
        """When branch_name is given, only that branch is diffed."""
        mod = _load_differ()

        template = self._make_template()
        template_file = tmp_path / "template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", template_file)

        branch1 = tmp_path / "flow"
        branch1.mkdir()
        branch2 = tmp_path / "ai_mail"
        branch2.mkdir()
        registry_data = {
            "branches": [
                {"name": "FLOW", "path": str(branch1), "status": "active"},
                {"name": "AI_MAIL", "path": str(branch2), "status": "active"},
            ]
        }
        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps(registry_data), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        result = mod.diff_dashboard_template(branch_name="FLOW")
        assert len(result["branches"]) == 1
        assert result["branches"][0]["branch"] == "FLOW"


# =============================================
# push_dashboard_template (template_pusher.py)
# =============================================

PUSHER_MODULE_PATH = "aipass.prax.apps.handlers.dashboard.template_pusher"


def _load_pusher() -> types.ModuleType:
    """Import (or reimport) the template_pusher module under active mocks."""
    sys.modules.pop(PUSHER_MODULE_PATH, None)
    import aipass.prax.apps.handlers.dashboard.template_pusher as mod

    importlib.reload(mod)
    return mod


class TestPushDashboardTemplate:
    """Tests for push_dashboard_template -- pushes template to all branches."""

    def _setup_template_and_registry(self, tmp_path, mod, monkeypatch, branches):
        """Create template file, registry, and branch dirs for push tests."""
        template = {
            "_warning": "AUTO-GENERATED",
            "branch": "{{BRANCHNAME}}",
            "sections": {
                "ai_mail": {
                    "managed_by": "ai_mail",
                    "new": 0,
                    "opened": 0,
                    "total": 0,
                    "last_updated": "",
                },
                "flow": {
                    "managed_by": "flow",
                    "active_plans": 0,
                    "recently_closed": [],
                    "last_updated": "",
                },
                "memory": {
                    "managed_by": "memory",
                    "vectors_stored": 0,
                    "notes": {},
                    "last_updated": "",
                },
            },
            "quick_status": {},
        }
        template_file = tmp_path / "template.json"
        template_file.write_text(json.dumps(template), encoding="utf-8")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", template_file)

        version_file = tmp_path / ".dashboard_version.json"
        monkeypatch.setattr(mod, "VERSION_FILE", version_file)

        branch_entries = []
        for name in branches:
            d = tmp_path / name
            d.mkdir(exist_ok=True)
            branch_entries.append({"name": name.upper(), "path": str(d), "status": "active"})

        registry_file = tmp_path / "AIPASS_REGISTRY.json"
        registry_file.write_text(json.dumps({"branches": branch_entries}), encoding="utf-8")
        monkeypatch.setattr(mod, "AIPASS_REGISTRY", registry_file)
        monkeypatch.setattr(mod, "_find_repo_root", lambda: tmp_path)

        return template

    def test_creates_dashboards_for_branches_without_one(self, tmp_path, monkeypatch):
        """Branches with no dashboard get one created from template."""
        mod = _load_pusher()
        self._setup_template_and_registry(tmp_path, mod, monkeypatch, ["flow", "ai_mail"])

        result = mod.push_dashboard_template(dry_run=False)
        assert result["success"] is True
        assert result["branches_created"] == 2
        assert (tmp_path / "flow" / "DASHBOARD.local.json").exists()
        assert (tmp_path / "ai_mail" / "DASHBOARD.local.json").exists()

    def test_dry_run_does_not_write_files(self, tmp_path, monkeypatch):
        """Dry run reports changes but does not create files on disk."""
        mod = _load_pusher()
        self._setup_template_and_registry(tmp_path, mod, monkeypatch, ["flow"])

        result = mod.push_dashboard_template(dry_run=True)
        assert result["dry_run"] is True
        assert result["branches_created"] == 1
        # File should NOT be created in dry run
        assert not (tmp_path / "flow" / "DASHBOARD.local.json").exists()

    def test_updates_existing_dashboard_with_structural_changes(self, tmp_path, monkeypatch):
        """Deprecated sections are removed and warning header is updated."""
        mod = _load_pusher()
        self._setup_template_and_registry(tmp_path, mod, monkeypatch, ["flow"])

        existing = {
            "_warning": "OLD WARNING",
            "branch": "FLOW",
            "sections": {
                "ai_mail": {
                    "managed_by": "ai_mail",
                    "new": 3,
                    "last_updated": "2026-01-01",
                },
                "flow": {
                    "managed_by": "flow",
                    "active_plans": 2,
                    "last_updated": "2026-01-01",
                },
                "memory": {"managed_by": "memory", "last_updated": "2026-01-01"},
                "commons_activity": {
                    "managed_by": "the_commons",
                    "last_updated": "2026-01-01",
                },
                "bulletin_board": {"posts": 5},
            },
            "quick_status": {"pending_bulletins": 3},
        }
        (tmp_path / "flow" / "DASHBOARD.local.json").write_text(json.dumps(existing), encoding="utf-8")

        result = mod.push_dashboard_template(dry_run=False)
        assert result["branches_updated"] == 1
        assert result["branches_created"] == 0

        data = json.loads((tmp_path / "flow" / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert "bulletin_board" not in data["sections"]
        assert "commons_activity" not in data["sections"]
        assert "pending_bulletins" not in data.get("quick_status", {})
        assert "commons_mentions" not in data.get("quick_status", {})
        assert data["_warning"] == "AUTO-GENERATED"
        assert data["sections"]["ai_mail"]["new"] == 3

    def test_returns_error_when_template_missing(self, tmp_path, monkeypatch):
        """Missing template file returns success=False with error message."""
        mod = _load_pusher()
        monkeypatch.setattr(mod, "TEMPLATE_FILE", tmp_path / "no_template.json")

        result = mod.push_dashboard_template()
        assert result["success"] is False
        assert len(result["errors"]) > 0


# =============================================
# get_template_status (template_pusher.py)
# =============================================


class TestGetTemplateStatus:
    """Tests for get_template_status -- version file and template existence."""

    def test_returns_status_when_version_file_exists(self, tmp_path, monkeypatch):
        """Version data is populated from existing .dashboard_version.json."""
        mod = _load_pusher()
        version_data = {
            "version": "3.0.0",
            "last_updated": "2026-03-01",
            "updated_by": "prax",
            "changes": ["added commons"],
            "last_push": "2026-03-02 10:00:00",
            "last_push_branches": ["FLOW", "AI_MAIL"],
        }
        version_file = tmp_path / ".dashboard_version.json"
        version_file.write_text(json.dumps(version_data), encoding="utf-8")
        monkeypatch.setattr(mod, "VERSION_FILE", version_file)
        monkeypatch.setattr(mod, "TEMPLATE_FILE", tmp_path / "exists.json")
        (tmp_path / "exists.json").write_text("{}", encoding="utf-8")

        result = mod.get_template_status()
        assert result["version"] == "3.0.0"
        assert result["last_push"] == "2026-03-02 10:00:00"
        assert result["last_push_branches"] == ["FLOW", "AI_MAIL"]
        assert result["template_exists"] is True

    def test_returns_defaults_when_no_version_file(self, tmp_path, monkeypatch):
        """Missing version file returns None defaults and template_exists=False."""
        mod = _load_pusher()
        monkeypatch.setattr(mod, "VERSION_FILE", tmp_path / "nonexistent_version.json")
        monkeypatch.setattr(mod, "TEMPLATE_FILE", tmp_path / "also_nonexistent.json")

        result = mod.get_template_status()
        assert result["version"] is None
        assert result["last_push"] is None
        assert result["last_push_branches"] == []
        assert result["template_exists"] is False


# =============================================
# update_section (dashboard.py module wrapper)
# =============================================

DASHBOARD_MODULE_PATH = "aipass.prax.apps.modules.dashboard"


def _load_dashboard_module() -> types.ModuleType:
    """Import (or reimport) the dashboard module under active mocks."""
    for mod_key in list(sys.modules.keys()):
        if mod_key.startswith("aipass.prax.apps.handlers.dashboard"):
            sys.modules.pop(mod_key, None)
    sys.modules.pop(DASHBOARD_MODULE_PATH, None)
    import aipass.prax.apps.modules.dashboard as mod

    importlib.reload(mod)
    return mod


class TestDashboardModuleUpdateSection:
    """Tests for dashboard.py module-level update_section wrapper."""

    def test_delegates_to_handler_update_section(self, tmp_path):
        """Module wrapper calls handler and writes section to disk."""
        mod = _load_dashboard_module()
        branch_dir = tmp_path / "wrapper_branch"
        branch_dir.mkdir()

        result = mod.update_section(branch_dir, "flow", {"active_plans": 3})
        assert result is True
        data = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert data["sections"]["flow"]["active_plans"] == 3

    def test_returns_false_on_handler_error(self, tmp_path):
        """Non-writable path causes wrapper to return False."""
        mod = _load_dashboard_module()
        bad_path = tmp_path / "no" / "such" / "deep" / "branch"

        result = mod.update_section(bad_path, "flow", {"active_plans": 1})
        assert result is False


# =============================================
# print_status (dashboard.py)
# =============================================


class TestPrintStatus:
    """Tests for print_status -- CLI status display."""

    def test_prints_branch_dashboard_status(self, tmp_path, monkeypatch):
        """Status output runs without error for mixed dashboard states."""
        mod = _load_dashboard_module()

        branch1 = tmp_path / "flow"
        branch1.mkdir()
        (branch1 / "DASHBOARD.local.json").write_text("{}", encoding="utf-8")
        branch2 = tmp_path / "ai_mail"
        branch2.mkdir()

        monkeypatch.setattr(mod, "get_branch_paths", lambda: [branch1, branch2])

        # Should not raise
        mod.print_status()

    def test_handles_error_loading_branches(self, monkeypatch):
        """Exception from get_branch_paths is caught and logged."""
        mod = _load_dashboard_module()

        def raise_error():
            """Simulate registry load failure."""
            raise RuntimeError("registry not found")

        monkeypatch.setattr(mod, "get_branch_paths", raise_error)
        # Should not raise, just log/print error
        mod.print_status()


# =============================================
# print_template (dashboard.py)
# =============================================


class TestPrintTemplate:
    """Tests for print_template -- CLI template display."""

    def test_prints_template_without_error(self):
        """Template JSON is printed to console without raising."""
        mod = _load_dashboard_module()
        # Should not raise
        mod.print_template()


# =============================================
# print_introspection (dashboard.py)
# =============================================


class TestDashboardPrintIntrospection:
    """Tests for print_introspection -- CLI module info display."""

    def test_prints_introspection_without_error(self):
        """Introspection output runs without raising."""
        mod = _load_dashboard_module()
        mod.print_introspection()

    def test_introspection_lists_template_sections(self):
        """Introspection lists all template section names."""
        mod = _load_dashboard_module()
        mod.print_introspection()
        # console.print should have been called multiple times
        assert mod.console.print.call_count > 3


# =============================================
# print_help (dashboard.py)
# =============================================


class TestDashboardPrintHelp:
    """Tests for print_help -- CLI help output."""

    def test_prints_help_without_error(self):
        """Help output runs without raising."""
        mod = _load_dashboard_module()
        mod.print_help()

    def test_help_lists_commands(self):
        """Help output includes subcommand names."""
        mod = _load_dashboard_module()
        mod.print_help()
        assert mod.console.print.call_count > 5


# =============================================
# handle_command (dashboard.py)
# =============================================


class TestDashboardHandleCommand:
    """Tests for handle_command -- command routing."""

    def test_returns_false_for_non_dashboard_command(self):
        """handle_command returns False for commands other than 'dashboard'."""
        mod = _load_dashboard_module()
        assert mod.handle_command("monitor", []) is False

    def test_no_args_calls_print_introspection(self):
        """Bare 'dashboard' with no args shows introspection."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_introspection") as mock_intro:
            result = mod.handle_command("dashboard", [])
            assert result is True
            mock_intro.assert_called_once()

    def test_help_flag_calls_print_help(self):
        """--help flag shows help and returns True."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        for flag in ("--help", "-h", "help"):
            with _patch.object(mod, "print_help") as mock_help:
                result = mod.handle_command("dashboard", [flag])
                assert result is True
                mock_help.assert_called_once()

    def test_status_subcommand(self):
        """'status' subcommand dispatches to print_status."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_status") as mock_status:
            result = mod.handle_command("dashboard", ["status"])
            assert result is True
            mock_status.assert_called_once()

    def test_template_subcommand(self):
        """'template' subcommand dispatches to print_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_template") as mock_tmpl:
            result = mod.handle_command("dashboard", ["template"])
            assert result is True
            mock_tmpl.assert_called_once()

    def test_refresh_subcommand(self):
        """'refresh' subcommand dispatches to _handle_refresh."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_refresh") as mock_refresh:
            result = mod.handle_command("dashboard", ["refresh"])
            assert result is True
            mock_refresh.assert_called_once_with([])

    def test_refresh_subcommand_passes_args(self):
        """'refresh' subcommand forwards trailing args."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_refresh") as mock_refresh:
            mod.handle_command("dashboard", ["refresh", "--all"])
            mock_refresh.assert_called_once_with(["--all"])

    def test_push_template_subcommand(self):
        """'push-template' subcommand dispatches to _handle_push_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_push_template") as mock_push:
            result = mod.handle_command("dashboard", ["push-template"])
            assert result is True
            mock_push.assert_called_once_with([])

    def test_diff_template_subcommand(self):
        """'diff-template' subcommand dispatches to _handle_diff_template."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_diff_template") as mock_diff:
            result = mod.handle_command("dashboard", ["diff-template"])
            assert result is True
            mock_diff.assert_called_once_with([])

    def test_template_status_subcommand(self):
        """'template-status' subcommand dispatches to _handle_template_status."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "_handle_template_status") as mock_ts:
            result = mod.handle_command("dashboard", ["template-status"])
            assert result is True
            mock_ts.assert_called_once()

    def test_unknown_subcommand_shows_help(self):
        """Unknown subcommand shows help and returns True."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        with _patch.object(mod, "print_help") as mock_help:
            result = mod.handle_command("dashboard", ["bogus"])
            assert result is True
            mock_help.assert_called_once()


# =============================================
# _handle_refresh (dashboard.py)
# =============================================


class TestHandleRefresh:
    """Tests for _handle_refresh -- refresh command handler."""

    def test_refresh_all(self, monkeypatch):
        """--all flag refreshes all branches."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {"status": "success", "branches_updated": 3},
        )
        mod._handle_refresh(["--all"])

    def test_refresh_all_partial(self, monkeypatch):
        """Partial success path for --all refresh."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {
                "status": "partial",
                "branches_updated": 2,
                "branches_failed": 1,
                "errors": ["branch X failed"],
            },
        )
        mod._handle_refresh(["--all"])

    def test_refresh_all_failure(self, monkeypatch):
        """Full failure path for --all refresh."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "refresh_all_dashboards",
            lambda: {
                "status": "error",
                "branches_updated": 0,
                "branches_failed": 3,
                "errors": ["total failure"],
            },
        )
        mod._handle_refresh(["--all"])

    def test_refresh_specific_branch_success(self, tmp_path, monkeypatch):
        """@branch arg refreshes specific branch on success."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(mod, "_resolve_branch_path", lambda ref: tmp_path / "flow")
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "success", "branch": "FLOW"},
        )
        mod._handle_refresh(["@flow"])

    def test_refresh_specific_branch_failure(self, tmp_path, monkeypatch):
        """@branch arg shows error on refresh failure."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(mod, "_resolve_branch_path", lambda ref: tmp_path / "flow")
        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "error", "error": "disk full"},
        )
        mod._handle_refresh(["@flow"])

    def test_refresh_specific_branch_not_found(self, monkeypatch):
        """@branch arg handles branch not found in registry."""
        mod = _load_dashboard_module()

        def _raise(ref):
            """Simulate branch not found."""
            raise FileNotFoundError("not found in registry")

        monkeypatch.setattr(mod, "_resolve_branch_path", _raise)
        mod._handle_refresh(["@ghost"])

    def test_refresh_cwd_success(self, tmp_path, monkeypatch):
        """No args refreshes current branch from CWD."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "success", "branch": "PRAX"},
        )
        with _patch("pathlib.Path.cwd", return_value=tmp_path):
            mod._handle_refresh([])

    def test_refresh_cwd_failure(self, tmp_path, monkeypatch):
        """No args shows error on CWD refresh failure."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(
            mod,
            "refresh_single_dashboard",
            lambda bp: {"status": "error", "error": "no dashboard"},
        )
        with _patch("pathlib.Path.cwd", return_value=tmp_path):
            mod._handle_refresh([])


# =============================================
# _handle_push_template (dashboard.py)
# =============================================


class TestHandlePushTemplate:
    """Tests for _handle_push_template -- push template handler."""

    def test_push_template_with_changes(self, monkeypatch):
        """Push template shows changes when branches need updating."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "push_dashboard_template",
            lambda dry_run=False: {
                "branches_scanned": 5,
                "branches_updated": 2,
                "branches_created": 1,
                "branches_skipped": 2,
                "changes": [
                    {
                        "branch": "FLOW",
                        "actions": ["removed bulletin_board"],
                    }
                ],
                "errors": [],
            },
        )
        mod._handle_push_template([])

    def test_push_template_dry_run(self, monkeypatch):
        """Dry run flag is forwarded to push_dashboard_template."""
        mod = _load_dashboard_module()
        captured: dict[str, object] = {}

        def _mock_push(dry_run=False):
            """Capture dry_run flag."""
            captured["dry_run"] = dry_run
            return {
                "branches_scanned": 3,
                "branches_updated": 0,
                "branches_created": 0,
                "branches_skipped": 3,
                "changes": [],
                "errors": [],
            }

        monkeypatch.setattr(mod, "push_dashboard_template", _mock_push)
        mod._handle_push_template(["--dry-run"])
        assert captured["dry_run"] is True

    def test_push_template_with_errors(self, monkeypatch):
        """Push template shows errors when some branches fail."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "push_dashboard_template",
            lambda dry_run=False: {
                "branches_scanned": 3,
                "branches_updated": 1,
                "branches_created": 0,
                "branches_skipped": 1,
                "changes": [],
                "errors": ["branch X: permission denied"],
            },
        )
        mod._handle_push_template([])

    def test_push_template_all_up_to_date(self, monkeypatch):
        """Push template shows 'all up to date' message."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "push_dashboard_template",
            lambda dry_run=False: {
                "branches_scanned": 3,
                "branches_updated": 0,
                "branches_created": 0,
                "branches_skipped": 3,
                "changes": [],
                "errors": [],
            },
        )
        mod._handle_push_template([])


# =============================================
# _handle_diff_template (dashboard.py)
# =============================================


class TestHandleDiffTemplate:
    """Tests for _handle_diff_template -- diff template handler."""

    def test_diff_template_error(self, monkeypatch):
        """Diff template shows error when result has error key."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "diff_dashboard_template",
            lambda branch_name=None: {"error": "template not found"},
        )
        mod._handle_diff_template([])

    def test_diff_template_with_branch_flag(self, monkeypatch):
        """--branch flag filters diff to single branch."""
        mod = _load_dashboard_module()
        captured: dict[str, object] = {}

        def _mock_diff(branch_name=None):
            """Capture branch_name arg."""
            captured["branch_name"] = branch_name
            return {
                "summary": {
                    "needs_update": 0,
                    "up_to_date": 1,
                    "missing": 0,
                },
                "branches": [],
            }

        monkeypatch.setattr(mod, "diff_dashboard_template", _mock_diff)
        mod._handle_diff_template(["--branch", "FLOW"])
        assert captured["branch_name"] == "FLOW"

    def test_diff_template_branch_flag_missing_name(self):
        """--branch without name prints error."""
        mod = _load_dashboard_module()
        mod._handle_diff_template(["--branch"])
        mod.error.assert_called()

    def test_diff_template_with_changes(self, monkeypatch):
        """Diff template shows additions, removals, and modifications."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "diff_dashboard_template",
            lambda branch_name=None: {
                "summary": {
                    "needs_update": 1,
                    "up_to_date": 1,
                    "missing": 1,
                    "invalid_json": 1,
                },
                "branches": [
                    {
                        "branch": "FLOW",
                        "status": "needs_update",
                        "additions": ["+ memory"],
                        "removals": ["- bulletin_board"],
                        "modifications": ["~ ai_mail.new default changed"],
                    },
                    {"branch": "MISSING", "status": "missing"},
                    {"branch": "GOOD", "status": "up_to_date"},
                ],
            },
        )
        mod._handle_diff_template([])


# =============================================
# _handle_template_status (dashboard.py)
# =============================================


class TestHandleTemplateStatus:
    """Tests for _handle_template_status -- template status display."""

    def test_template_status_basic(self, monkeypatch):
        """Template status displays version info."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "get_template_status",
            lambda: {
                "templates_dir": "/path/to/templates",
                "template_exists": True,
                "version": "3.0.0",
                "last_updated": "2026-03-01",
                "updated_by": "prax",
                "last_push": "2026-03-02",
                "last_push_branches": ["FLOW", "AI_MAIL"],
                "changes": [],
            },
        )
        mod._handle_template_status()

    def test_template_status_with_many_branches(self, monkeypatch):
        """Template status truncates branch list at 5 with ellipsis."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "get_template_status",
            lambda: {
                "templates_dir": "/path/to/templates",
                "template_exists": True,
                "version": "3.0.0",
                "last_updated": "2026-03-01",
                "updated_by": "prax",
                "last_push": "2026-03-02",
                "last_push_branches": [
                    "A",
                    "B",
                    "C",
                    "D",
                    "E",
                    "F",
                    "G",
                ],
                "changes": ["added commons"],
            },
        )
        mod._handle_template_status()

    def test_template_status_missing(self, monkeypatch):
        """Template status handles missing template."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "get_template_status",
            lambda: {
                "templates_dir": "/path/to/templates",
                "template_exists": False,
                "version": None,
                "last_updated": None,
                "updated_by": None,
                "last_push": None,
                "last_push_branches": [],
                "changes": [],
            },
        )
        mod._handle_template_status()

    def test_template_status_no_push(self, monkeypatch):
        """Template status handles never-pushed template."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "get_template_status",
            lambda: {
                "templates_dir": "/path/to/templates",
                "template_exists": True,
                "version": "1.0.0",
                "last_updated": "2026-01-01",
                "updated_by": "dev",
                "last_push": None,
                "last_push_branches": [],
                "changes": [],
            },
        )
        mod._handle_template_status()


# =============================================
# _resolve_branch_path (dashboard.py wrapper)
# =============================================


class TestResolveBranchPathWrapper:
    """Tests for _resolve_branch_path -- dashboard module wrapper."""

    def test_delegates_to_handler(self, monkeypatch):
        """Wrapper delegates to resolve_branch_path handler."""
        mod = _load_dashboard_module()
        from pathlib import Path

        monkeypatch.setattr(
            mod,
            "resolve_branch_path",
            lambda ref: Path("/fake/flow"),
        )
        result = mod._resolve_branch_path("@flow")
        assert result == Path("/fake/flow")


# =============================================
# main (dashboard.py)
# =============================================


class TestDashboardMain:
    """Tests for main -- CLI entry point."""

    def test_main_no_args(self, monkeypatch):
        """No args shows introspection."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(sys, "argv", ["dashboard"])
        with _patch.object(mod, "print_introspection") as mock_intro:
            mod.main()
        mock_intro.assert_called_once()

    def test_main_help_flag(self, monkeypatch):
        """--help flag shows help."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(sys, "argv", ["dashboard", "--help"])
        with _patch.object(mod, "print_help") as mock_help:
            mod.main()
        mock_help.assert_called_once()

    def test_main_h_flag(self, monkeypatch):
        """-h flag shows help."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(sys, "argv", ["dashboard", "-h"])
        with _patch.object(mod, "print_help") as mock_help:
            mod.main()
        mock_help.assert_called_once()

    def test_main_valid_command(self, monkeypatch):
        """Valid command delegates to handle_command."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(sys, "argv", ["dashboard", "dashboard", "status"])
        with _patch.object(mod, "handle_command", return_value=True) as mock_hc:
            mod.main()
        mock_hc.assert_called_once_with("dashboard", ["status"])

    def test_main_unknown_command(self, monkeypatch):
        """Unknown command shows error and help."""
        mod = _load_dashboard_module()
        from unittest.mock import patch as _patch

        monkeypatch.setattr(sys, "argv", ["dashboard", "bogus"])
        with (
            _patch.object(mod, "handle_command", return_value=False),
            _patch.object(mod, "print_help") as mock_help,
        ):
            mod.main()
        mock_help.assert_called_once()
        mod.error.assert_called()
