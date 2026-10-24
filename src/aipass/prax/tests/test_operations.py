# =================== AIPass ====================
# Name: test_operations.py
# Description: Unit tests for dashboard operations handler
# Version: 1.5.0
# Created: 2026-03-24
# Modified: 2026-10-24
# =============================================

"""Tests for the dashboard file and its budget: apps/handlers/dashboard/operations.py."""

# Unit tests for aipass.prax.apps.handlers.dashboard.operations.
#
# The modules under test are bound once at the top; the conftest fixture
# _dashboard_quiet doubles their logger and json service before every test
# (prax, leg 12). Split 2026-10-08: refresh and section writes, the template
# lane and the display and command handlers live in test_operations_refresh.py,
# test_operations_template.py and test_operations_display.py.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(json_structure) — write_section's log_operation("section_updated") record, covered by that row
# seedgo: no-test-needed(through_the_command) — merge_quick_status, covered by tests/test_dashboard_merge.py

import json
from pathlib import Path

import pytest

from aipass.prax.apps.handlers.dashboard.status import calculate_quick_status
from aipass.prax.tests.support_test_operations import _load_ops

pytestmark = pytest.mark.usefixtures("_dashboard_quiet")


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
        """Return value is a pathlib.Path naming DASHBOARD.local.json under the branch."""
        ops = _load_ops()
        result = ops.get_dashboard_path(tmp_path)
        assert isinstance(result, Path)
        assert result.name == "DASHBOARD.local.json"
        assert result.parent == tmp_path

    def test_works_with_nested_branch_path(self, tmp_path):
        """Deeply nested branch paths still resolve correctly."""
        ops = _load_ops()
        nested = tmp_path / "src" / "aipass" / "flow"
        result = ops.get_dashboard_path(nested)
        assert result == nested / "DASHBOARD.local.json"


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


class TestDashboardCharBudget:
    """Over the budget the save warns — it never refuses and never trims.

    DPLAN-0347: the dashboard is read on every greeting, so its size is a cost
    every branch pays. A refused save would leave a stale dashboard, and stale is
    the failure already on the board: zero new mail reported with three waiting.
    """

    def _oversized(self, chars: int) -> dict:
        """A dashboard whose rendered JSON is comfortably past the budget."""
        return {"branch": "BIG", "sections": {"flow": {"subject": "x" * chars}}}

    def test_a_dashboard_over_the_budget_warns_with_the_measured_number(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        ops = _load_ops()
        branch_dir = tmp_path / "big"
        branch_dir.mkdir()
        log = MagicMock()
        monkeypatch.setattr(ops, "logger", log)

        assert ops.save_dashboard(branch_dir, self._oversized(ops.DASHBOARD_CHAR_BUDGET)) is True

        template, *values = log.warning.call_args.args
        rendered = template % tuple(values)
        written = (branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8")
        assert "big" in rendered
        assert str(len(written)) in rendered, "the warning must carry the measured size"
        assert str(ops.DASHBOARD_CHAR_BUDGET) in rendered

    def test_the_oversized_dashboard_is_still_written_whole(self, tmp_path, monkeypatch):
        """Never refuse, never trim: a warned dashboard is a complete dashboard."""
        from unittest.mock import MagicMock

        ops = _load_ops()
        branch_dir = tmp_path / "whole"
        branch_dir.mkdir()
        monkeypatch.setattr(ops, "logger", MagicMock())
        data = self._oversized(ops.DASHBOARD_CHAR_BUDGET)

        ops.save_dashboard(branch_dir, data)

        loaded = json.loads((branch_dir / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert loaded["sections"]["flow"]["subject"] == data["sections"]["flow"]["subject"]

    def test_a_dashboard_under_the_budget_is_silent(self, tmp_path, monkeypatch):
        from unittest.mock import MagicMock

        ops = _load_ops()
        branch_dir = tmp_path / "small"
        branch_dir.mkdir()
        log = MagicMock()
        monkeypatch.setattr(ops, "logger", log)

        ops.save_dashboard(branch_dir, {"branch": "SMALL", "sections": {}})

        assert log.warning.call_count == 0


class TestCapSubject:
    """One cut, one number, shared by every writer that publishes a subject."""

    def test_an_essay_is_cut_to_the_cap_including_the_marker(self):
        ops = _load_ops()
        capped = ops.cap_subject("FPLAN-0593 " + "startup floor fleet-wide " * 20)

        assert len(capped) <= ops.SUBJECT_CAP
        assert capped.endswith(ops.TRUNCATION_MARKER)

    def test_a_subject_at_the_cap_is_untouched(self):
        """The boundary belongs to the subject, not to the marker."""
        ops = _load_ops()
        exact = "x" * ops.SUBJECT_CAP

        assert ops.cap_subject(exact) == exact

    def test_only_the_first_line_survives(self):
        ops = _load_ops()

        assert ops.cap_subject("feat(x): short\n\nWHY: the essay lives here\n") == "feat(x): short"

    def test_empty_and_blank_subjects_stay_empty(self):
        ops = _load_ops()

        assert ops.cap_subject("") == ""
        assert ops.cap_subject("   \n") == ""


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
# calculate_quick_status (the one write_section uses)
# =============================================


class TestCalculateQuickStatus:
    """Tests for status.calculate_quick_status -- pure calculation."""

    def test_empty_sections_returns_defaults(self, tmp_path):
        """Empty sections produce zeroed counters and 'All clear' summary."""
        result = calculate_quick_status({}, tmp_path)
        assert result["new_mail"] == 0
        assert result["opened_mail"] == 0
        assert result["active_plans"] == 0
        assert result["action_required"] is False
        assert result["summary"] == "All clear"

    def test_new_mail_triggers_action_required(self, tmp_path):
        """New mail count > 0 sets action_required to True (sourced from inbox.json)."""
        mail_dir = tmp_path / ".ai_mail.local"
        mail_dir.mkdir()
        inbox = {
            "messages": [
                {"id": "1", "status": "new"},
                {"id": "2", "status": "new"},
                {"id": "3", "status": "new"},
            ]
        }
        (mail_dir / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")
        result = calculate_quick_status({}, tmp_path)
        assert result["new_mail"] == 3
        assert result["action_required"] is True
        assert "3 new emails" in result["summary"]

    def test_active_plans_triggers_action_required(self, tmp_path):
        """Active plans > 0 sets action_required to True."""
        sections = {"flow": {"active_plans": 2}}
        result = calculate_quick_status(sections, tmp_path)
        assert result["active_plans"] == 2
        assert result["action_required"] is True
        assert "2 active plans" in result["summary"]

    def test_combined_summary_includes_all_parts(self, tmp_path):
        """Summary string includes all active counts."""
        mail_dir = tmp_path / ".ai_mail.local"
        mail_dir.mkdir()
        inbox = {
            "messages": [
                {"id": "1", "status": "new"},
                {"id": "2", "status": "new"},
                {"id": "3", "status": "opened"},
            ]
        }
        (mail_dir / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")
        sections = {"flow": {"active_plans": 3}}
        result = calculate_quick_status(sections, tmp_path)
        assert result["action_required"] is True
        assert "2 new emails" in result["summary"]
        assert "1 opened" in result["summary"]
        assert "3 active plans" in result["summary"]

    def test_mail_counts_from_inbox_json(self, tmp_path):
        """Mail counts sourced from inbox.json status fields."""
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
        (mail_dir / "inbox.json").write_text(json.dumps(inbox), encoding="utf-8")
        result = calculate_quick_status({}, tmp_path)
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
            assert "ai_mail" not in result["sections"]
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
