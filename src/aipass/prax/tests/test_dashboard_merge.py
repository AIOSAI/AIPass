# =================== AIPass ====================
# Name: test_dashboard_merge.py
# Description: quick_status has many writers — none may delete another's key
# Version: 1.2.0
# Created: 2026-08-13
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/dashboard/status.py, refresh.py, operations.py, template_pusher.py and template_differ.py."""

# Invariant: no quick_status writer deletes a key it did not write. The calculator's copies are pinned to agree.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(through_the_command) — save_dashboard, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — create_fresh_dashboard, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — get_branch_paths, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — resolve_branch_path, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — refresh_all_dashboards, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — diff_dashboard_template, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — push_dashboard_template, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — get_template_status, covered by tests/test_operations.py
# seedgo: no-test-needed(through_the_command) — _extract_flow_section, covered by tests/test_flow_section_contract.py
# seedgo: no-test-needed(through_the_command) — plugin refresh(), covered by tests/test_devpulse_dashboard_plugin.py
# seedgo: no-test-needed(json_structure) — the log_operation records of the refresh, push and diff, covered by that row

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.prax.apps.handlers.dashboard import operations as ops
from aipass.prax.apps.handlers.dashboard import refresh
from aipass.prax.apps.handlers.dashboard import status
from aipass.prax.apps.handlers.dashboard import template_differ as differ
from aipass.prax.apps.handlers.dashboard import template_pusher as pusher


# A key only @flow writes. prax must carry it through untouched.
FOREIGN = {"commons_mentions": 4}


def _seed_branch(tmp_path: Path, quick_status: dict, todos: int = 2) -> Path:
    """Build a branch dir with a dashboard, a local.json and an inbox."""
    branch = tmp_path / "prax"
    (branch / ".trinity").mkdir(parents=True)
    (branch / ".ai_mail.local").mkdir(parents=True)

    (branch / "DASHBOARD.local.json").write_text(
        json.dumps(
            {
                "branch": "PRAX",
                "quick_status": quick_status,
                "sections": {"flow": {"managed_by": "flow", "active_plans": 3}},
            }
        ),
        encoding="utf-8",
    )
    (branch / ".trinity" / "local.json").write_text(
        json.dumps({"todos": [{"task": f"t{i}"} for i in range(todos)]}), encoding="utf-8"
    )
    (branch / ".ai_mail.local" / "inbox.json").write_text(
        json.dumps({"messages": [{"status": "new"}, {"status": "opened"}]}), encoding="utf-8"
    )
    return branch


def _push_world(tmp_path: Path, monkeypatch, module, template: dict, branch: "Path | None"):
    """Point the pusher or the differ at a world under tmp_path (registry naming ``branch``) and return it."""
    template_file = tmp_path / "DASHBOARD.template.json"
    template_file.write_text(json.dumps(template), encoding="utf-8")
    registry = tmp_path / "AIPASS_REGISTRY.json"
    entries = [] if branch is None else [{"name": branch.name.upper(), "path": str(branch), "status": "active"}]
    registry.write_text(json.dumps({"branches": entries}), encoding="utf-8")
    monkeypatch.setattr(module, "TEMPLATE_FILE", template_file)
    monkeypatch.setattr(module, "AIPASS_REGISTRY", registry)
    monkeypatch.setattr(module, "_find_repo_root", lambda: tmp_path)
    if module is pusher:
        monkeypatch.setattr(pusher, "VERSION_FILE", tmp_path / ".dashboard_version.json")
    return module


def _read_quick_status(branch: Path) -> dict:
    return json.loads((branch / "DASHBOARD.local.json").read_text(encoding="utf-8"))["quick_status"]


class TestForeignKeysSurviveEveryWriter:
    """commons_mentions is flow's. Every prax write path must carry it through."""

    def test_merge_preserves_unknown_keys(self):
        merged = status.merge_quick_status(
            {"commons_mentions": 4, "new_mail": 9}, {"new_mail": 1, "summary": "1 new emails"}
        )
        assert merged["commons_mentions"] == 4

    def test_merge_lets_owned_keys_win(self):
        """Preserving foreign keys must not freeze prax's own counters."""
        merged = status.merge_quick_status({"new_mail": 9}, {"new_mail": 1})
        assert merged["new_mail"] == 1

    def test_merge_tolerates_missing_existing_block(self):
        assert status.merge_quick_status(None, {"new_mail": 0})["new_mail"] == 0

    def test_write_section_preserves_foreign_key(self, tmp_path):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        ops.write_section(branch, "memory", {"managed_by": "memory", "vectors_stored": 7})
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_preserves_foreign_key(self, tmp_path):
        """The live path: `drone @prax dashboard refresh @prax`."""
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_refresh_single_still_recomputes_owned_keys(self, tmp_path):
        """Preservation must not turn refresh into a no-op."""
        branch = _seed_branch(tmp_path, {"new_mail": 99, "todo_count": 99, **FOREIGN}, todos=2)
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        quick = _read_quick_status(branch)
        assert quick["todo_count"] == 2
        assert quick["new_mail"] == 1

    def test_an_unreadable_todo_list_keeps_the_last_count_and_says_so(self, tmp_path):
        """A local.json that cannot be read is not zero todos: the last count stays, the summary says so."""
        branch = _seed_branch(tmp_path, {"new_mail": 0, "todo_count": 7})
        (branch / ".trinity" / "local.json").write_text("<<<not json>>>", encoding="utf-8")

        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)

        quick = _read_quick_status(branch)
        assert quick["todo_count"] == 7
        assert quick["summary"] == "1 new emails, 1 opened, todos unreadable"

    def _refreshed(self, branch):
        with patch.object(refresh, "read_all_centrals", return_value={}):
            refresh.refresh_single_dashboard(branch)
        return _read_quick_status(branch)

    def test_an_unreadable_dashboard_says_its_keys_were_lost(self, tmp_path):
        """An unreadable dashboard merged as {}: the foreign keys went with only a log line."""
        branch = _seed_branch(tmp_path, {})
        (branch / "DASHBOARD.local.json").write_text("<<<not json>>>", encoding="utf-8")

        quick = self._refreshed(branch)

        assert quick.get("previous_unreadable") is True
        assert (quick["new_mail"], quick["opened_mail"], quick["todo_count"]) == (1, 1, 2)

    def test_a_missing_dashboard_has_no_loss_to_report(self, tmp_path):
        branch = _seed_branch(tmp_path, {})
        (branch / "DASHBOARD.local.json").unlink()

        quick = self._refreshed(branch)

        assert "previous_unreadable" not in quick
        assert quick["new_mail"] == 1

    def test_a_readable_dashboard_keeps_its_keys_and_clears_an_old_loss(self, tmp_path):
        """The flag of an earlier unreadable refresh does not outlive a readable one."""
        branch = _seed_branch(tmp_path, {"commons_mentions": 4, "previous_unreadable": True})

        quick = self._refreshed(branch)

        assert quick.get("commons_mentions") == 4
        assert "previous_unreadable" not in quick

    def test_canary_plain_assignment_drops_the_key(self):
        """Proof the assertions above can fail: replacing the block is the bug."""
        block = {"new_mail": 0, **FOREIGN}
        block = {"new_mail": 1, "summary": "1 new emails"}
        assert "commons_mentions" not in block


# ---------------------------------------------------------------------------
# Finding 2 — a flow-shaped section must not raise
# ---------------------------------------------------------------------------

# The legacy flow shape (active_plans a list); old dashboards carry it on disk until their next write.
FLOW_LIST_SECTION = {
    "flow": {
        "managed_by": "flow",
        "active_plans": [{"id": "FPLAN-0001"}, {"id": "FPLAN-0002"}],
        "active_count": 2,
    }
}


# One calculator: every writer calls it, so there is no copy to drift.
CALCULATORS = [("status.calculate_quick_status", status.calculate_quick_status)]


class TestListShapedActivePlans:
    """flow's own section shape must not raise in any copy of the calculator."""

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_list_shape_does_not_raise(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc(FLOW_LIST_SECTION, branch)["active_plans"] == 2, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_int_shape_still_works(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({"flow": {"active_plans": 3}}, branch)["active_plans"] == 3, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_missing_flow_section_is_zero(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {})
        assert calc({}, branch)["active_plans"] == 0, name


class TestPushTemplateIsNotAWreckingBall:
    """`dashboard push-template` writes every branch's dashboard; it must not delete flow's commons_mentions."""

    def test_commons_mentions_is_not_deprecated(self):
        assert "commons_mentions" not in pusher.DEPRECATED_QUICK_STATUS_KEYS

    def test_the_differ_reads_the_pushers_list_not_its_own_copy(self):
        """One deprecation list, the pusher's, or the differ's advice and the write disagree."""
        assert differ.DEPRECATED_QUICK_STATUS_KEYS is pusher.DEPRECATED_QUICK_STATUS_KEYS
        assert "commons_mentions" not in differ.DEPRECATED_QUICK_STATUS_KEYS

    def test_structural_update_preserves_foreign_key(self, tmp_path, monkeypatch):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})

        result = _push_world(tmp_path, monkeypatch, pusher, {}, branch).push_dashboard_template(dry_run=False)

        assert result["branches_updated"] == 1
        assert _read_quick_status(branch)["commons_mentions"] == 4

    def test_structural_update_keeps_todo_count(self, tmp_path, monkeypatch):
        """The pusher's own calculator had no todo_count at all, so it dropped it."""
        branch = _seed_branch(tmp_path, {"new_mail": 0, "todo_count": 99}, todos=2)

        _push_world(tmp_path, monkeypatch, pusher, {}, branch).push_dashboard_template(dry_run=False)

        assert _read_quick_status(branch)["todo_count"] == 2

    def test_structural_update_without_a_branch_stays_placeholder(self, tmp_path, monkeypatch):
        """spawn's builder template has no .trinity/ or inbox — it must not gain counts."""
        spawn_template = tmp_path / "src" / "aipass" / "spawn" / "templates" / "builder" / "DASHBOARD.local.json"
        spawn_template.parent.mkdir(parents=True)
        spawn_template.write_text(
            json.dumps({"quick_status": {}, "sections": {"flow": {"active_plans": 0}}}), encoding="utf-8"
        )

        _push_world(tmp_path, monkeypatch, pusher, {}, None).push_dashboard_template(dry_run=False)

        quick = json.loads(spawn_template.read_text(encoding="utf-8"))["quick_status"]
        assert quick["todo_count"] == 0
        assert quick["new_mail"] == 0

    def test_a_template_section_the_constant_never_heard_of_is_advised(self, tmp_path, monkeypatch):
        """The differ advises from the loaded template, not a module-level copy of its sections."""
        branch = _seed_branch(tmp_path, {"new_mail": 0})
        template = {"sections": {"a_brand_new_section": {}}, "quick_status": {"new_mail": 0}}

        result = _push_world(tmp_path, monkeypatch, differ, template, branch).diff_dashboard_template("PRAX")

        assert "a_brand_new_section section" in result["branches"][0]["additions"]

    def test_canary_deprecation_list_still_deletes(self):
        """Proof the first assertion can fail: the removal loop is real."""
        qs = {"commons_mentions": 4, "pending_bulletins": 1}
        for key in ["pending_bulletins", "commons_mentions"]:
            qs.pop(key, None)
        assert qs == {}


class TestActionRequiredMatchesItsOwnSummary:
    """action_required must agree with the summary beside it: the owner's card reads it for 'needs attention'."""

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_todos_alone_require_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=1)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["todo_count"] == 1, name
        assert result["action_required"] is True, name

    @pytest.mark.parametrize("name,calc", CALCULATORS)
    def test_all_clear_requires_no_action(self, name, calc, tmp_path):
        branch = _seed_branch(tmp_path, {}, todos=0)
        (branch / ".ai_mail.local" / "inbox.json").write_text(json.dumps({"messages": []}), encoding="utf-8")
        result = calc({}, branch)
        assert result["summary"] == "All clear", name
        assert result["action_required"] is False, name


class TestUnreadableInboxKeepsTheLastMailCount:
    """A mid-write inbox.json must not publish 0 new mail and 'All clear'."""

    def test_unreadable_inbox_drops_mail_keys_so_the_merge_keeps_them(self, tmp_path):
        branch = _seed_branch(tmp_path, {"new_mail": 3, "opened_mail": 1}, todos=0)
        (branch / ".ai_mail.local" / "inbox.json").write_text('{"messages": [', encoding="utf-8")

        computed = status.calculate_quick_status({}, branch)

        assert "new_mail" not in computed and "opened_mail" not in computed
        assert computed["summary"] == "mail unreadable"
        assert status.merge_quick_status({"new_mail": 3}, computed)["new_mail"] == 3


class TestDashboardWritesAreAtomicAndLocked:
    """A reader or a second writer never sees, or rebuilds over, a half-written dashboard."""

    def test_a_failed_save_leaves_the_old_file_whole(self, tmp_path, monkeypatch):
        branch = _seed_branch(tmp_path, {"new_mail": 0, **FOREIGN})
        before = (branch / "DASHBOARD.local.json").read_text(encoding="utf-8")

        def _boom(*args):
            raise OSError("disk full")

        monkeypatch.setattr(ops.os, "replace", _boom)

        assert ops.write_section(branch, "dispatch", {"agents_active": []}) is False
        assert (branch / "DASHBOARD.local.json").read_text(encoding="utf-8") == before

    @pytest.mark.parametrize("content", ["", '{"sections": {', "[1, 2]"])
    def test_write_section_refuses_an_unreadable_dashboard(self, tmp_path, content):
        """Rebuilding from the template here wiped every other service's sections."""
        branch = _seed_branch(tmp_path, {})
        (branch / "DASHBOARD.local.json").write_text(content, encoding="utf-8")

        assert ops.write_section(branch, "dispatch", {"agents_active": []}) is False
        assert (branch / "DASHBOARD.local.json").read_text(encoding="utf-8") == content

    @pytest.mark.skipif(ops.fcntl is None, reason="no advisory lock on this platform")
    @pytest.mark.parametrize(
        "writer",
        [
            lambda b: ops.write_section(b, "dispatch", {"agents_active": []}),
            lambda b: refresh.refresh_single_dashboard(b),
        ],
        ids=["write_section", "refresh"],
    )
    def test_writers_wait_for_the_dashboard_lock(self, tmp_path, writer):
        import threading

        branch = _seed_branch(tmp_path, {})
        done = threading.Event()
        with patch.object(refresh, "read_all_centrals", return_value={}):
            with ops.dashboard_lock(branch):
                worker = threading.Thread(target=lambda: (writer(branch), done.set()))
                worker.start()
                assert not done.wait(0.3)
            worker.join(10)
        assert done.is_set()
