# =================== AIPass ====================
# Name: test_operations_template.py
# Description: Unit tests for the dashboard template lane
# Version: 1.1.0
# Created: 2026-10-08
# Modified: 2026-10-24
# =============================================

"""Tests for the template lane: apps/handlers/dashboard/template_differ.py and template_pusher.py."""

# Split out of test_operations.py (2026-10-08), whole classes: diff and push
# of the dashboard template, its version status, and the dashboard module's
# push-template, diff-template and template-status handlers. The modules under
# test are bound once at the top; the conftest fixture _dashboard_quiet doubles
# their logger and json service before every test (prax, leg 12).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — handle_command's routing, covered by tests/test_operations_display.py

import json
import types

import pytest

from aipass.prax.apps.handlers.dashboard import template_differ, template_pusher
from aipass.prax.tests.support_test_operations import _load_dashboard_module, _Screen

pytestmark = pytest.mark.usefixtures("_dashboard_quiet")


# =============================================
# diff_dashboard_template (template_differ.py)
# =============================================


def _load_differ() -> types.ModuleType:
    """The template_differ module, bound at the top; _dashboard_quiet doubles its edges."""
    return template_differ


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


def _load_pusher() -> types.ModuleType:
    """The template_pusher module, bound at the top; _dashboard_quiet doubles its edges."""
    return template_pusher


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

    def test_a_created_dashboard_carries_its_branch_name(self, tmp_path, monkeypatch):
        """The {{BRANCHNAME}} placeholder is replaced by the branch the dashboard is for.

        Green from its first run; its proof is its mutant (prax, leg 13): the
        replace returning the raw value survived every other test in this file.
        """
        mod = _load_pusher()
        self._setup_template_and_registry(tmp_path, mod, monkeypatch, ["flow"])

        mod.push_dashboard_template(dry_run=False)

        created = json.loads((tmp_path / "flow" / "DASHBOARD.local.json").read_text(encoding="utf-8"))
        assert created["branch"] == "FLOW"

    def test_an_empty_dashboard_is_skipped_not_overwritten(self, tmp_path, monkeypatch):
        """An empty file is unreadable, not missing: a template over it would wipe every service's sections."""
        mod = _load_pusher()
        self._setup_template_and_registry(tmp_path, mod, monkeypatch, ["flow"])
        (tmp_path / "flow" / "DASHBOARD.local.json").write_text("", encoding="utf-8")

        result = mod.push_dashboard_template(dry_run=False)

        assert result["branches_created"] == 0
        assert result["branches_skipped"] == 1
        assert (tmp_path / "flow" / "DASHBOARD.local.json").read_text(encoding="utf-8") == ""

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
# _handle_push_template (dashboard.py)
# =============================================


class TestHandlePushTemplate:
    """Tests for _handle_push_template -- push template handler."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_push_template_with_changes(self, monkeypatch):
        """Push prints the four counters and every action of every changed branch."""
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

        mod.handle_command("dashboard", ["push-template"])

        printed = self._screen.read().printed
        assert "Dashboard Template PUSH Results" in printed
        assert "  Branches scanned:  5" in printed
        assert "  Branches updated:  2" in printed
        assert "  Branches created:  1" in printed
        assert "  Branches skipped:  2" in printed
        assert "Changes (1 branches):" in printed
        assert printed[printed.index("  FLOW:") - 1] == ""
        assert "    - removed bulletin_board" in printed
        assert "All branches are up to date with template." not in printed
        assert self._screen.read().errors == []

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
        mod.handle_command("dashboard", ["push-template", "--dry-run"])
        assert captured["dry_run"] is True

    def test_push_template_with_errors(self, monkeypatch):
        """A failing branch is counted and named through error(), and suppresses 'up to date'."""
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

        mod.handle_command("dashboard", ["push-template"])

        printed = self._screen.read().printed
        assert "  Branches scanned:  3" in printed
        assert "  Branches updated:  1" in printed
        assert "All branches are up to date with template." not in printed
        assert self._screen.read().errors == [
            "Errors (1)",
            "! branch X: permission denied",
        ]

    def test_push_template_all_up_to_date(self, monkeypatch):
        """No changes and no errors prints the up-to-date line and nothing failed."""
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

        mod.handle_command("dashboard", ["push-template"])

        printed = self._screen.read().printed
        assert "  Branches scanned:  3" in printed
        assert "  Branches skipped:  3" in printed
        assert "All branches are up to date with template." in printed
        assert not any("Changes (" in line for line in printed)
        assert self._screen.read().errors == []


# =============================================
# _handle_diff_template (dashboard.py)
# =============================================


class TestHandleDiffTemplate:
    """Tests for _handle_diff_template -- diff template handler."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    def test_diff_template_error(self, monkeypatch):
        """An 'error' key is surfaced verbatim through error() and stops before the summary."""
        mod = _load_dashboard_module()
        monkeypatch.setattr(
            mod,
            "diff_dashboard_template",
            lambda branch_name=None: {"error": "template not found"},
        )

        mod.handle_command("dashboard", ["diff-template"])

        self._screen.assert_one_error("template not found")
        assert self._screen.read().printed == []

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
        mod.handle_command("dashboard", ["diff-template", "--branch", "FLOW"])
        assert captured["branch_name"] == "FLOW"

    def test_diff_template_branch_flag_missing_name(self):
        """--branch without name prints error."""
        mod = _load_dashboard_module()
        mod.handle_command("dashboard", ["diff-template", "--branch"])
        self._screen.assert_one_error("--branch requires a branch name")

    def test_diff_template_with_changes(self, monkeypatch):
        """Summary counters, per-branch additions/removals/modifications; up-to-date branches are skipped."""
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

        mod.handle_command("dashboard", ["diff-template"])

        printed = self._screen.read().printed
        assert "  Needs update: 1" in printed
        assert "  Up to date:   1" in printed
        assert "  Missing:      1" in printed
        assert printed[printed.index("  FLOW (needs_update)") - 1] == ""
        assert "    + + memory" in printed
        assert "    ~ ~ ai_mail.new default changed" in printed
        assert printed[printed.index("  MISSING (missing)") - 1] == ""
        assert not any("GOOD" in line for line in printed), "up_to_date branches are skipped"
        self._screen.assert_one_error("Invalid JSON: 1")
        self._screen.assert_one_warning("  - - bulletin_board")


# =============================================
# _handle_template_status (dashboard.py)
# =============================================


class TestHandleTemplateStatus:
    """Tests for _handle_template_status -- template status display."""

    _screen: _Screen

    @pytest.fixture(autouse=True)
    def _keep_screen(self, screen):
        self._screen = screen

    @pytest.mark.parametrize(
        ("pushed", "expected_line"),
        [
            (["FLOW", "AI_MAIL"], "Branches pushed: 2 (FLOW, AI_MAIL)"),
            (["A", "B", "C", "D", "E", "F", "G"], "Branches pushed: 7 (A, B, C, D, E...)"),
        ],
    )
    def test_template_status_basic(self, monkeypatch, pushed, expected_line):
        """Template status prints the version and the pushed branches, truncated past five."""
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
                "last_push_branches": pushed,
                "changes": [],
            },
        )

        mod.handle_command("dashboard", ["template-status"])

        printed = self._screen.read().printed
        assert any("Schema version:  3.0.0" in line for line in printed)
        assert any(expected_line in line for line in printed), f"missing: {expected_line}"

    def test_template_status_missing(self, monkeypatch):
        """A missing template file is warned about, and the unknown fields print as None."""
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

        mod.handle_command("dashboard", ["template-status"])

        printed = self._screen.read().printed
        assert "  Templates dir:   /path/to/templates" in printed
        assert "  Template file:   found" not in printed
        assert "  Schema version:  None" in printed
        assert "  Last push:       never" in printed
        self._screen.assert_one_warning("Template file: MISSING")

    def test_template_status_no_push(self, monkeypatch):
        """A never-pushed template prints 'never' and omits the branches-pushed line entirely."""
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

        mod.handle_command("dashboard", ["template-status"])

        printed = self._screen.read().printed
        assert "  Template file:   found" in printed
        assert "  Schema version:  1.0.0" in printed
        assert "  Last updated:    2026-01-01" in printed
        assert "  Updated by:      dev" in printed
        assert "  Last push:       never" in printed
        assert not any("Branches pushed" in line for line in printed)
        assert self._screen.read().warnings == []
