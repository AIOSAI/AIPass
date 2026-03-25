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
from pathlib import Path


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
    """Tests for get_dashboard_path — pure path joining."""

    def test_returns_dashboard_path_from_path_input(self, tmp_path):
        ops = _load_ops()
        result = ops.get_dashboard_path(tmp_path)
        assert result == tmp_path / "DASHBOARD.local.json"

    def test_returns_path_type(self, tmp_path):
        ops = _load_ops()
        result = ops.get_dashboard_path(tmp_path)
        assert isinstance(result, Path)

    def test_works_with_nested_branch_path(self, tmp_path):
        ops = _load_ops()
        nested = tmp_path / "src" / "aipass" / "flow"
        result = ops.get_dashboard_path(nested)
        assert result == nested / "DASHBOARD.local.json"


# =============================================
# load_dashboard
# =============================================

class TestLoadDashboard:
    """Tests for load_dashboard — file I/O with fallback to template."""

    def _make_template(self):
        return {
            "branch": "TEMPLATE",
            "last_updated": "",
            "sections": {
                "ai_mail": {"new": 0},
                "flow": {"active_plans": 0},
            },
        }

    def test_loads_existing_dashboard(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "mybranch"
        branch_dir.mkdir()
        dashboard_data = {
            "branch": "MYBRANCH",
            "last_updated": "2026-01-01",
            "sections": {"flow": {"active_plans": 5}},
        }
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps(dashboard_data), encoding="utf-8"
        )

        result = ops.load_dashboard(branch_dir, self._make_template())
        assert result["branch"] == "MYBRANCH"
        assert result["sections"]["flow"]["active_plans"] == 5

    def test_returns_template_when_file_missing(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "nobranch"
        branch_dir.mkdir()
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        # Branch name should be set from directory name uppercased
        assert result["branch"] == "NOBRANCH"
        assert "sections" in result

    def test_returns_template_on_corrupted_json(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "broken"
        branch_dir.mkdir()
        (branch_dir / "DASHBOARD.local.json").write_text(
            "{not valid json!!!", encoding="utf-8"
        )
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        assert result["branch"] == "BROKEN"
        assert result["sections"] == template["sections"]

    def test_returns_template_on_empty_file(self, tmp_path):
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
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps([1, 2, 3]), encoding="utf-8"
        )
        template = self._make_template()

        result = ops.load_dashboard(branch_dir, template)
        # Non-dict JSON falls back to template
        assert result["branch"] == "ARRAYFILE"
        assert result["sections"] == template["sections"]

    def test_adds_sections_when_missing_from_existing_file(self, tmp_path):
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
    """Tests for save_dashboard — file write with timestamp update."""

    def test_creates_dashboard_file(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "savebranch"
        branch_dir.mkdir()
        data = {"branch": "SAVEBRANCH", "sections": {}}

        result = ops.save_dashboard(branch_dir, data)
        assert result is True
        assert (branch_dir / "DASHBOARD.local.json").exists()

    def test_writes_valid_json(self, tmp_path):
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
        ops = _load_ops()
        branch_dir = tmp_path / "timestamp"
        branch_dir.mkdir()
        data = {"branch": "TIMESTAMP", "sections": {}}

        ops.save_dashboard(branch_dir, data)
        content = json.loads(
            (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        )
        assert "last_updated" in content
        # Should be a non-empty ISO-format string
        assert len(content["last_updated"]) > 0
        assert "T" in content["last_updated"]

    def test_returns_true_on_success(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "retval"
        branch_dir.mkdir()

        result = ops.save_dashboard(branch_dir, {"branch": "RV"})
        assert result is True


# =============================================
# write_section
# =============================================

class TestWriteSection:
    """Tests for write_section — orchestration of load/update/save."""

    def test_creates_dashboard_if_none_exists(self, tmp_path):
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
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps(existing), encoding="utf-8"
        )

        ops.write_section(branch_dir, "flow", {"active_plans": 7})
        data = json.loads(
            (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        )
        assert data["sections"]["flow"]["active_plans"] == 7

    def test_preserves_other_sections(self, tmp_path):
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
        (branch_dir / "DASHBOARD.local.json").write_text(
            json.dumps(existing), encoding="utf-8"
        )

        ops.write_section(branch_dir, "flow", {"active_plans": 4})
        data = json.loads(
            (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        )
        # ai_mail should still be present and unchanged
        assert data["sections"]["ai_mail"]["new"] == 3
        assert data["sections"]["ai_mail"]["opened"] == 1

    def test_adds_last_updated_to_section(self, tmp_path):
        ops = _load_ops()
        branch_dir = tmp_path / "sectstamp"
        branch_dir.mkdir()

        ops.write_section(branch_dir, "flow", {"active_plans": 1})
        data = json.loads(
            (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        )
        assert "last_updated" in data["sections"]["flow"]
        assert "T" in data["sections"]["flow"]["last_updated"]

    def test_returns_false_on_error(self, tmp_path):
        ops = _load_ops()
        # Pass a path that does not exist and cannot be written to
        nonexistent = tmp_path / "no" / "such" / "deep" / "branch"

        result = ops.write_section(nonexistent, "flow", {"active_plans": 1})
        assert result is False


# =============================================
# _calculate_quick_status_standalone
# =============================================

class TestCalculateQuickStatusStandalone:
    """Tests for _calculate_quick_status_standalone — pure calculation."""

    def test_empty_sections_returns_defaults(self):
        ops = _load_ops()
        result = ops._calculate_quick_status_standalone({})
        assert result["new_mail"] == 0
        assert result["opened_mail"] == 0
        assert result["active_plans"] == 0
        assert result["commons_mentions"] == 0
        assert result["action_required"] is False
        assert result["summary"] == "All clear"

    def test_new_mail_triggers_action_required(self):
        ops = _load_ops()
        sections = {"ai_mail": {"new": 3, "opened": 0}}
        result = ops._calculate_quick_status_standalone(sections)
        assert result["new_mail"] == 3
        assert result["action_required"] is True
        assert "3 new emails" in result["summary"]

    def test_active_plans_triggers_action_required(self):
        ops = _load_ops()
        sections = {"flow": {"active_plans": 2}}
        result = ops._calculate_quick_status_standalone(sections)
        assert result["active_plans"] == 2
        assert result["action_required"] is True
        assert "2 active plans" in result["summary"]

    def test_commons_mentions_triggers_action_required(self):
        ops = _load_ops()
        sections = {"commons_activity": {"mentions": 5}}
        result = ops._calculate_quick_status_standalone(sections)
        assert result["commons_mentions"] == 5
        assert result["action_required"] is True
        assert "5 mentions" in result["summary"]

    def test_combined_summary_includes_all_parts(self):
        ops = _load_ops()
        sections = {
            "ai_mail": {"new": 2, "opened": 1},
            "flow": {"active_plans": 3},
            "commons_activity": {"mentions": 4},
        }
        result = ops._calculate_quick_status_standalone(sections)
        assert result["action_required"] is True
        assert "2 new emails" in result["summary"]
        assert "1 opened" in result["summary"]
        assert "3 active plans" in result["summary"]
        assert "4 mentions" in result["summary"]

    def test_unread_field_falls_back_from_new(self):
        """ai_mail may use 'unread' instead of 'new' — code checks both."""
        ops = _load_ops()
        sections = {"ai_mail": {"unread": 7}}
        result = ops._calculate_quick_status_standalone(sections)
        assert result["new_mail"] == 7
        assert result["action_required"] is True
