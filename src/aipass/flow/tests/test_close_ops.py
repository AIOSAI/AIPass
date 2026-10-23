# =================== AIPass ====================
# Name: test_close_ops.py
# Description: Tests for close_ops handler — plan closure business logic
# Version: 1.2.0
# Created: 2026-03-29
# Modified: 2026-10-23
# =============================================

"""Tests for apps/handlers/plan/close_ops.py and its close_helpers, append_closed_plan and registry_routing modules."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import os
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

import pytest

from aipass.flow.apps.handlers.plan.close_ops import (
    close_all_plans_impl,
    close_plan_impl,
)
from aipass.flow.apps.handlers.plan.registry_routing import canonical_plan_id
from aipass.flow.apps.handlers.plan.validator import validate_plan_exists
from aipass.flow.apps.handlers.registry import load_registry as plan_load
from aipass.flow.apps.handlers.template.get_template import TEMPLATES_DIR, get_template
from aipass.flow.tests.support_close_ops import _make_deps


class TestABareNumberNeverClosesTheNamesakeOfAnUnreadableRegistry:
    """close 12: not in FPLAN, DPLAN's registry unreadable, PBPLAN-12 open.

    Skipping the unreadable registry would resolve 12 to PBPLAN-12 and close the wrong plan.
    """

    def test_the_close_refuses_and_writes_nothing(self, tmp_path, monkeypatch):
        flow_json = tmp_path / "flow_json"
        flow_json.mkdir()
        monkeypatch.setattr(plan_load, "FLOW_JSON_DIR", flow_json)
        monkeypatch.setattr(plan_load, "REGISTRY_FILE", flow_json / "fplan_registry.json")
        (flow_json / "fplan_registry.json").write_text(json.dumps({"plans": {}, "next_number": 1}), encoding="utf-8")
        (flow_json / "dplan_registry.json").write_text('{"plans": {"12": ', encoding="utf-8")
        theirs = tmp_path / "PBPLAN-0012_theirs_2026-10-04.md"
        theirs.write_text("# theirs\nReal notes.", encoding="utf-8")
        row = {"status": "open", "subject": "theirs", "location": str(tmp_path), "file_path": str(theirs)}
        pbplan = flow_json / "pbplan_registry.json"
        pbplan.write_text(json.dumps({"plans": {"12": row}, "next_number": 13}), encoding="utf-8")
        before = pbplan.read_text(encoding="utf-8")
        types = {"types": {"dev_plans": {"prefix": "DPLAN"}, "playbook_plans": {"prefix": "PBPLAN"}}}
        deps = _make_deps(load_registry=plan_load.load_registry, validate_plan_exists=validate_plan_exists)

        with (
            patch("aipass.flow.apps.handlers.plan.registry_routing._load_template_registry", return_value=types),
            patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess") as subprocess_stand_in,
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
        ):
            result = close_plan_impl(plan_num="12", **deps)

        assert subprocess_stand_in.mock_calls == []  # no post-close runner was started
        assert result["success"] is False
        [message] = result["messages"]
        assert message["type"] == "error"
        assert message["details"].startswith(f"Plan registry {flow_json / 'dplan_registry.json'} cannot be read: ")
        deps["save_registry"].assert_not_called()
        deps["archive_plan_fn"].assert_not_called()
        assert pbplan.read_text(encoding="utf-8") == before
        assert theirs.exists()


_APPEND = "aipass.flow.apps.handlers.plan.append_closed_plan"


def _deny_exclusive_creates(lock_path: Path, denials: int | None):
    """A stand-in for the append's _create_exclusive seam that answers the way
    Windows does mid-release.

    Windows delete-pending raises PermissionError, which Linux can never show. The first
    ``denials`` creates of ``lock_path`` are denied (None = forever), then the real create runs.
    """
    attempts: list[int] = []
    raised: list[PermissionError] = []

    def fake_create(path):
        if str(path) == str(lock_path):
            attempts.append(len(attempts) + 1)
            if denials is None or len(attempts) <= denials:
                denial = PermissionError(13, "Access is denied")
                raised.append(denial)
                raise denial
        return os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)

    return fake_create, attempts, raised


class TestExtractPrefix:
    """_extract_prefix, reached through canonical_plan_id, its public caller (leg 10)."""

    @pytest.mark.parametrize(
        ("file_name", "expected"),
        [
            ("FPLAN-0001", "FPLAN-1"),
            ("DPLAN-0004", "DPLAN-1"),
            ("fplan-0099", "FPLAN-1"),
            ("Dplan-0002", "DPLAN-1"),
            ("0001", None),
            ("42", None),
            ("", None),
            ("FOO-0001", None),
            ("  FPLAN-0001  ", "FPLAN-1"),
            ("XYZPLAN-0010", "XYZPLAN-1"),
        ],
    )
    def test_the_prefix_read_off_the_file_name(self, file_name, expected):
        assert canonical_plan_id("1", {"file_path": file_name}) == expected


class TestClosePlanImplNoNumber:
    """Plan number is required for single plan closure."""

    def test_no_plan_num_returns_error(self):
        result = close_plan_impl(plan_num=None, **_make_deps())
        assert result["success"] is False
        assert result["messages"][0]["text"] == "invalid_number"
        assert result["plan_key"] == ""

    def test_empty_string_plan_num_returns_error(self):
        result = close_plan_impl(plan_num="", **_make_deps())
        assert result["success"] is False
        assert result["messages"][0]["text"] == "invalid_number"


class TestClosePlanImplAllFlag:
    """When all_plans=True, delegates to close_all_plans_fn."""

    def test_all_plans_delegates(self):
        mock_close_all = MagicMock(return_value={"success": True, "messages": []})
        deps = _make_deps(close_all_plans_fn=mock_close_all)
        result = close_plan_impl(plan_num="1", all_plans=True, **deps)
        mock_close_all.assert_called_once_with(False, dry_run=False, exclude_types=None)
        assert result == {"success": True, "messages": []}


class TestClosePlanImplNotFound:
    """Plan not found in registry."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._find_unregistered_plan_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_plan_not_found_returns_error(self, _mock_find, _mock_resolve, _mock_unregistered):
        deps = _make_deps()
        deps["validate_plan_exists"].return_value = (False, "Plan 99 not found")
        deps["load_registry"].return_value = {"plans": {}}

        result = close_plan_impl(plan_num="99", **deps)
        assert result["success"] is False
        assert result["messages"][0]["text"] == "not_found"
        assert result["plan_key"] == "99"


class TestClosePlanImplAlreadyClosed:
    """Idempotency: plan already closed (no orphan file)."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_already_closed_no_orphan(self, _mock_find, _mock_resolve, tmp_path):
        plan_file = tmp_path / "FPLAN-0002_closed_2026-03-18.md"
        registry = {
            "plans": {
                "2": {
                    "status": "closed",
                    "closed": "2026-03-19",
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        result = close_plan_impl(plan_num="2", **deps)
        assert result["success"] is False
        assert any("already closed" in m.get("text", "") for m in result["messages"])
        assert result["plan_key"] == "2"


class TestClosePlanImplAlreadyClosedOrphan:
    """Already closed but orphan .md file still on disk -- auto-heal."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_already_closed_orphan_cleanup(self, _mock_find, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0002_closed_2026-03-18.md"
        plan_file.write_text("# FPLAN-0002: closed", encoding="utf-8")

        registry = {
            "plans": {
                "2": {
                    "status": "closed",
                    "closed": "2026-03-19",
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        result = close_plan_impl(plan_num="2", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "2"
        deps["save_registry"].assert_called()
        assert any("orphan" in m.get("text", "").lower() for m in result["messages"])


class TestCloseNeverArchivesAFileThatIsNotAPlan:
    """Leg 9: rows registered before leg 7 name reports; close would archive them."""

    REPORT = "FPLAN-0508 rows seedgo\nmeasured rows, not a plan\n"

    @staticmethod
    def _close(row: dict, deps: dict) -> dict:
        deps["load_registry"].return_value = {"plans": {"564": row}}
        with (
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
        ):
            return close_plan_impl(plan_num="564", spawn_background=False, **deps)

    def test_an_open_row_naming_a_report_is_refused_and_nothing_moves(self, tmp_path):
        report = tmp_path / "FPLAN-0516.md"
        report.write_text(self.REPORT, encoding="utf-8")
        row = {"status": "open", "subject": "FPLAN-0516", "file_path": str(report)}
        deps = _make_deps()

        result = self._close(row, deps)

        assert result["success"] is False
        assert result["messages"] == [
            {
                "type": "error_text",
                "text": f"Refused: {report} is not a plan (its first line is no plan header). "
                "Nothing was archived, moved or renamed.",
            }
        ]
        deps["archive_plan_fn"].assert_not_called()
        deps["save_registry"].assert_not_called()
        assert row["status"] == "open"
        assert report.read_text(encoding="utf-8") == self.REPORT

    def test_the_orphan_cleanup_of_a_closed_row_naming_a_report_is_refused(self, tmp_path):
        report = tmp_path / "FPLAN-0516.md"
        report.write_text(self.REPORT, encoding="utf-8")
        row = {"status": "closed", "closed": "2026-10-04", "file_path": str(report)}
        deps = _make_deps()

        result = self._close(row, deps)

        assert result["success"] is False
        assert str(report) in result["messages"][0]["text"]
        deps["archive_plan_fn"].assert_not_called()
        deps["save_registry"].assert_not_called()
        assert "processed" not in row
        assert report.read_text(encoding="utf-8") == self.REPORT

    def test_an_unreadable_file_is_refused_not_archived(self, tmp_path):
        """is_plan_file None (undecodable bytes): nobody can tell, so nothing moves."""
        unreadable = tmp_path / "FPLAN-0564.md"
        unreadable.write_bytes(b"\xff\xfe# FPLAN-0564: x\n")
        row = {"status": "open", "file_path": str(unreadable)}
        deps = _make_deps()

        result = self._close(row, deps)

        assert result["success"] is False
        assert result["messages"][0]["text"] == (
            f"Refused: {unreadable} cannot be read. Nothing was archived, moved or renamed."
        )
        deps["archive_plan_fn"].assert_not_called()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_close_all_archives_the_plan_and_refuses_the_report(self, _mock_jh, mock_bg, tmp_path):
        """close --all closes each row through close_plan_impl, so the refusal holds per row."""
        plan = tmp_path / "FPLAN-0001_real_2026-10-04.md"
        plan.write_text("# FPLAN-0001 - real\n", encoding="utf-8")
        report = tmp_path / "FPLAN-0516.md"
        report.write_text(self.REPORT, encoding="utf-8")
        rows = {
            "1": {"status": "open", "subject": "real", "location": str(tmp_path), "file_path": str(plan)},
            "564": {"status": "open", "subject": "junk", "location": str(tmp_path), "file_path": str(report)},
        }
        deps = _make_deps()
        deps["load_registry"].return_value = {"plans": rows}

        def close_one(plan_num, **kwargs):
            with (
                patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
                patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            ):
                return close_plan_impl(plan_num=plan_num.split("-")[-1], **kwargs, **deps)

        result = close_all_plans_impl(
            caller_project=tmp_path,
            resolve_project_fn=lambda _location: tmp_path,
            get_open_plans=MagicMock(return_value=[(key, row) for key, row in rows.items()]),
            close_plan_fn=close_one,
        )

        deps["archive_plan_fn"].assert_called_once_with(plan)
        assert rows["564"]["status"] == "open"
        assert report.read_text(encoding="utf-8") == self.REPORT
        assert (result["success_count"], result["failure_count"]) == (1, 1)
        mock_bg.assert_called_once_with()  # one runner for the one plan archived


class TestAFailedSaveIsSaidNotSwallowed:
    """Leg 10: save_registry answers False when it could not write, and never raises."""

    @staticmethod
    def _close(tmp_path, row: dict, deps: dict) -> dict:
        deps["load_registry"].return_value = {"plans": {"1": row}}
        with (
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            return close_plan_impl(plan_num="1", spawn_background=False, **deps)

    @staticmethod
    def _plan(tmp_path) -> Path:
        plan = tmp_path / "FPLAN-0001_real_2026-10-04.md"
        plan.write_text("# FPLAN-0001: real\nnotes\n", encoding="utf-8")
        return plan

    def test_an_unsaved_close_fails_and_archives_nothing(self, tmp_path):
        plan = self._plan(tmp_path)
        row = {"status": "open", "subject": "real", "location": str(tmp_path), "file_path": str(plan)}
        deps = _make_deps(save_registry=MagicMock(return_value=False))

        result = self._close(tmp_path, row, deps)

        assert result["success"] is False
        assert result["messages"][-1] == {
            "type": "error_text",
            "text": "  Failed to update registry: the registry was not saved; "
            "the plan is still open and nothing was archived",
        }
        deps["archive_plan_fn"].assert_not_called()

    def test_an_unsaved_archive_mark_is_said(self, tmp_path):
        """The close itself saved; the archive mark after it did not."""
        plan = self._plan(tmp_path)
        row = {"status": "open", "subject": "real", "location": str(tmp_path), "file_path": str(plan)}
        deps = _make_deps(save_registry=MagicMock(side_effect=[True, False]))

        result = self._close(tmp_path, row, deps)

        assert result["success"] is True
        deps["archive_plan_fn"].assert_called_once_with(plan)
        assert {
            "type": "warning",
            "text": "  Archived, but could not save the registry: the row reads unarchived",
        } in result["messages"]

    def test_an_unsaved_orphan_cleanup_is_said(self, tmp_path):
        plan = self._plan(tmp_path)
        row = {"status": "closed", "closed": "2026-10-04", "file_path": str(plan)}
        deps = _make_deps(save_registry=MagicMock(return_value=False))

        result = self._close(tmp_path, row, deps)

        deps["archive_plan_fn"].assert_called_once_with(plan)
        assert {
            "type": "warning",
            "text": "  Archived, but could not save the registry: the row reads unarchived",
        } in result["messages"]


class TestClosePlanImplDryRun:
    """Dry run previews without acting."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_dry_run_returns_preview(self, _mock_find, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": "/some/path",
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        result = close_plan_impl(plan_num="1", dry_run=True, **deps)
        assert result["success"] is True
        assert result["plan_key"] == "1"
        assert any("DRY RUN" in m.get("text", "") for m in result["messages"])
        assert any("No action taken" in m.get("text", "") for m in result["messages"])
        deps["save_registry"].assert_not_called()


class TestClosePlanImplSuccess:
    """Successful close -- full happy path with all deps mocked."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_successful_close(self, mock_subprocess, _mock_find, _mock_resolve, tmp_path):
        """Mutant: `if spawn_background:` -> `if False:` reddens this."""
        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test\nSome actual plan notes.", encoding="utf-8")

        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="1", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "1"
        assert result["cancelled"] is False
        mock_append.assert_called_once_with("1", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        deps["save_registry"].assert_called()
        deps["update_dashboard_local"].assert_called_once()
        deps["push_to_plans_central"].assert_called_once()

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_a_plan_rendered_without_a_listen_section_closes(
        self, mock_subprocess, _mock_find, _mock_resolve, tmp_path
    ):
        plan_file = tmp_path / "FPLAN-0001_fresh_2026-10-23.md"
        fresh = get_template(template_path=TEMPLATES_DIR / "flow_plans" / "default.md", number=1, subject="Fresh")
        plan_file.write_text(fresh, encoding="utf-8")
        assert "## Listen" not in plan_file.read_text(encoding="utf-8")
        deps = _make_deps()
        deps["load_registry"].return_value = {
            "plans": {
                "1": {"status": "open", "subject": "Fresh", "location": str(tmp_path), "file_path": str(plan_file)}
            }
        }

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="1", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("1", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()

    @pytest.mark.parametrize("answer, failed", [(None, False), (False, True)])
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_no_dashboard_is_not_logged_as_a_failure(
        self, mock_subprocess, _mock_find, _mock_resolve, answer, failed, tmp_path, mock_logger
    ):
        """None from either dashboard writer means there is no dashboard, not a failure; False warns.

        Mutants: `if dashboard_success is False:` -> `if not dashboard_success:`, and
        `if branch_dashboard_success is False:` -> `if not branch_dashboard_success:`,
        each redden the None case.
        """
        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test\nSome actual plan notes.", encoding="utf-8")
        registry = {
            "plans": {
                "1": {"status": "open", "subject": "Test plan", "location": str(tmp_path), "file_path": str(plan_file)}
            }
        }
        deps = _make_deps(
            update_dashboard_local=MagicMock(return_value=answer),
            push_flow_to_branch_dashboard=MagicMock(return_value=answer),
        )
        deps["load_registry"].return_value = registry

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans") as mock_append,
        ):
            result = close_plan_impl(plan_num="1", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("1", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        deps["push_flow_to_branch_dashboard"].assert_called_once_with(tmp_path)
        warned = [str(c.args[0]) for c in mock_logger.warning.call_args_list]
        assert any("Failed to update DASHBOARD.local.json" in w for w in warned) is failed
        assert any("Failed to push flow section to branch dashboard" in w for w in warned) is failed

    @staticmethod
    def _close_with_real_append(tmp_path, fake_open, sleep):
        """Close FPLAN-0001 in tmp_path with the REAL CLOSED_PLANS append, a
        stand-in for its exclusive create and ``sleep`` recording the backoff's waits; returns
        close_plan_impl's result.
        """
        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test\nSome actual plan notes.", encoding="utf-8")
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                    "relative_path": plan_file.name,
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess"),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(f"{_APPEND}._create_exclusive", side_effect=fake_open),
            patch(f"{_APPEND}._sleep", sleep),
        ):
            return close_plan_impl(plan_num="1", **deps)

    def test_closed_plans_append_waits_out_a_delete_pending_lock(self, tmp_path):
        """The CLOSED_PLANS append lock takes a Windows delete-pending denial as
        a held lock and retries it; the entry lands in CLOSED_PLANS.local.json.
        """
        closed_plans = tmp_path / "CLOSED_PLANS.local.json"
        lock = closed_plans.with_suffix(".lock")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1)
        sleep = MagicMock()

        result = self._close_with_real_append(tmp_path, fake_open, sleep)

        assert result["success"] is True
        assert not any("CLOSED_PLANS" in m.get("text", "") for m in result["messages"])
        assert closed_plans.exists()
        entries = json.loads(closed_plans.read_text(encoding="utf-8"))["closed_plans"]
        assert [e["plan_id"] for e in entries] == ["FPLAN-1"]
        assert len(attempts) == 2
        sleep.assert_called_once()
        assert sleep.call_args.args[0] > 0
        assert not lock.exists()

    def test_closed_plans_denial_that_never_clears_fails_at_the_budget(self, tmp_path, mock_logger):
        """A denial past the budget: exactly the budget of attempts, the close
        still succeeds (the append is non-critical) but reports the failed
        append with its reason.
        """

        closed_plans = tmp_path / "CLOSED_PLANS.local.json"
        lock = closed_plans.with_suffix(".lock")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=None)
        sleep = MagicMock()

        result = self._close_with_real_append(tmp_path, fake_open, sleep)

        assert result["success"] is True
        # Read off the attempts, not the private budget constant.
        budget = len(attempts)
        assert budget > 1
        assert not closed_plans.exists()
        # The denial reaches the user with its reason. Mutant `raise` -> `return False`.
        reported = [m["text"] for m in result["messages"] if "CLOSED_PLANS" in m.get("text", "")]
        assert len(reported) == 1
        assert reported[0].startswith("  CLOSED_PLANS update failed: Lock ")
        assert str(lock) in reported[0]
        waited = sum(c.args[0] for c in sleep.call_args_list)
        assert reported[0].endswith(f"after {budget} attempts ({waited:.2f}s waited)")
        # Never str(call): its repr doubles backslashes, hiding a Windows path.
        warned = " ".join(str(arg) for c in mock_logger.warning.call_args_list for arg in c.args)
        assert str(lock) in warned
        assert f"{budget} attempts" in warned
        # Positive, doubling, summed into the message.
        delays = [c.args[0] for c in sleep.call_args_list]
        assert len(delays) == len(attempts)
        assert delays[0] > 0
        assert all(later == 2 * earlier for earlier, later in zip(delays, delays[1:]))
        assert f"({sum(delays):.2f}s waited)" in warned


class TestTemplateDetectionNeverDeletes:
    """FPLAN-0370/0371 bug: is_template_content()==True must NOT fast-delete the
    file or the registry row; it closes and archives like any other plan."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_template_flagged_plan_is_archived_not_deleted(self, mock_subprocess, _mock_find, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        template_body = "# FPLAN-0001 - test\n[What do you want to achieve? Specific end state.]"
        plan_file.write_text(template_body, encoding="utf-8")

        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps(is_template_content=MagicMock(return_value=True))
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="1", **deps)

        assert result["success"] is True
        # archive_plan_fn is the only thing allowed to move or remove the file.
        assert plan_file.exists()
        deps["archive_plan_fn"].assert_called_once_with(plan_file)
        assert "1" in registry["plans"]
        assert registry["plans"]["1"]["status"] == "closed"
        deps["update_dashboard_local"].assert_called_once()
        mock_append.assert_called_once()
        mock_subprocess.Popen.assert_called_once()
        assert any("empty template" in m.get("text", "").lower() for m in result["messages"])


class TestSpawnBackgroundBehavior:
    """#662: spawn_background controls whether vectorization runs inline or in background."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_spawn_background_true_calls_background_runner(self, _mock_find, _mock_resolve, mock_runner, tmp_path):
        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test\nNotes here.", encoding="utf-8")
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)
        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="1", spawn_background=True, **deps)
        assert result["success"] is True
        mock_append.assert_called_once_with("1", ANY, tmp_path)
        mock_runner.assert_called_once()
        assert any("background" in m.get("text", "").lower() for m in result["messages"])

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_spawn_background_false_skips_background_runner(self, _mock_find, _mock_resolve, mock_runner, tmp_path):
        """Mutant: append_to_closed_plans(..., plan_file.parent) -> (..., plan_file) reddens this."""
        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test\nNotes here.", encoding="utf-8")
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)
        with (
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="1", spawn_background=False, **deps)
        assert result["success"] is True
        mock_append.assert_called_once_with("1", ANY, tmp_path)  # the append is not tied to the spawn
        mock_runner.assert_not_called()


class TestClosePlanImplConfirmCancelled:
    """User cancels when confirm=True."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_confirm_cancelled(self, _mock_find, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# FPLAN-0001: test", encoding="utf-8")

        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "subject": "Test plan",
                    "location": str(tmp_path),
                    "file_path": str(plan_file),
                }
            }
        }
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)
        deps["confirm_plan_deletion"].return_value = False  # User says no

        result = close_plan_impl(plan_num="1", confirm=True, **deps)
        assert result["success"] is False
        assert result["cancelled"] is True
        deps["save_registry"].assert_not_called()


class TestClosePlanImplValueError:
    """normalize_plan_number raises ValueError for invalid input."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    def test_value_error_returns_invalid_number(self, _mock_resolve):
        deps = _make_deps()
        deps["normalize_plan_number"].side_effect = ValueError("bad number")

        result = close_plan_impl(plan_num="abc", **deps)
        assert result["success"] is False
        assert result["messages"][0]["text"] == "invalid_number"
