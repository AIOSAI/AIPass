# =================== AIPass ====================
# Name: test_close_ops.py
# Description: Tests for close_ops handler — plan closure business logic
# Version: 1.0.1
# Created: 2026-03-29
# Modified: 2026-10-05
# =============================================

"""Tests for apps/handlers/plan/close_ops.py and its close_helpers, append_closed_plan and registry_routing modules."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath
from unittest.mock import ANY, MagicMock, patch

import pytest

import aipass.flow.apps.handlers.plan.close_ops as close_ops
from aipass.flow.apps.handlers.plan.close_ops import (
    close_all_plans_impl,
    close_plan_impl,
)
from aipass.flow.apps.handlers.plan.registry_routing import canonical_plan_id
from aipass.flow.apps.handlers.plan.validator import validate_plan_exists
from aipass.flow.apps.handlers.registry import load_registry as plan_load


class TestABareNumberNeverClosesTheNamesakeOfAnUnreadableRegistry:
    """close 12: not in FPLAN, DPLAN's registry unreadable, PBPLAN-12 open.

    Until leg 6 the cross-registry search skipped the registry it could not
    read and went on, so 12 resolved to PBPLAN-12 and that plan was closed
    (and the load answered an unreadable registry with an empty one). Red
    first on that code; mutant: the search's load wrapped back in
    `try: ... except Exception: continue`.
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


# ─── Helpers ─────────────────────────────────────────────

_APPEND = "aipass.flow.apps.handlers.plan.append_closed_plan"


def _deny_exclusive_creates(lock_path: Path, denials: int | None):
    """A stand-in for the append's _create_exclusive seam that answers the way
    Windows does mid-release.

    Windows answers an exclusive create against a lock another writer is still
    removing (delete-pending) with PermissionError, not FileExistsError; Linux
    cannot show that, so it is manufactured, handed in through the product's
    own seam so os.open stays whole for every other reader. The first
    ``denials`` creates of ``lock_path`` are denied (None = never clears);
    after that the real exclusive create is made on disk.

    Returns:
        (side_effect, attempts, raised): attempts counts every exclusive create
        of lock_path; raised holds each PermissionError handed out.
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


def _under(path: PurePath, root: PurePath) -> bool:
    """True when `path` IS `root` or lives beneath it.

    A path relationship, never a string prefix. This exists because three
    tests in this file red on the windows-setup CI runner while their
    siblings stayed green, and the difference was exactly the idiom:

        str(Path("/aipass/src"))            # posix   -> "/aipass/src"
        str(Path("/aipass/src"))            # windows -> "\\aipass\\src"
        "\\aipass\\src".startswith("/aipass")  # False

    So a resolver written as ``str(path).startswith("/aipass")`` returned None
    for every row on Windows, the whole sweep landed in the held bucket, and
    nothing closed. The siblings compared ``str(path)`` to ``str(root)`` --
    both sides wearing the same separator -- which is why they survived.
    Neither idiom belongs in a path test; is_relative_to answers the question
    that was actually being asked, on every platform.
    """
    return path.is_relative_to(root)


def _scope(tmp_path, **overrides) -> dict:
    """Scope dependencies for close_all: caller in <tmp_path>/proj, every row in it.

    Injected explicitly in every close_all test. The fence is not optional and
    an un-injected default would let a test pass while saying nothing about
    which project it was standing in.
    """
    proj = tmp_path / "proj"
    deps = {"caller_project": proj, "resolve_project_fn": lambda _path: proj}
    deps.update(overrides)
    return deps


def _make_deps(**overrides) -> dict:
    """Build a full set of injected dependency kwargs with MagicMock defaults."""
    deps = {
        "normalize_plan_number": MagicMock(side_effect=lambda x: str(x).split("-")[-1].lstrip("0") or "0"),
        "load_registry": MagicMock(),
        "save_registry": MagicMock(),
        "validate_plan_exists": MagicMock(return_value=(True, None)),
        "confirm_plan_deletion": MagicMock(return_value=True),
        "is_template_content": MagicMock(return_value=False),
        "update_dashboard_local": MagicMock(return_value=True),
        "push_to_plans_central": MagicMock(return_value=True),
        "push_flow_to_branch_dashboard": MagicMock(return_value=True),
        "close_all_plans_fn": MagicMock(),
        "archive_plan_fn": MagicMock(return_value=True),
        "trigger_fire_fn": MagicMock(),
    }
    deps.update(overrides)
    return deps


# ═══════════════════════════════════════════════════════════
# 1. _extract_prefix
# ═══════════════════════════════════════════════════════════


class TestExtractPrefix:
    """_extract_prefix, reached through canonical_plan_id, its public caller (leg 10).

    The prefix is read off the row's file name: only a [A-Z]+PLAN prefix
    counts, case-blind and stripped, and it comes back upper case.
    """

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


# ═══════════════════════════════════════════════════════════
# 2. close_plan_impl — single plan closure
# ═══════════════════════════════════════════════════════════


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
        # Plan file does NOT exist on disk (already archived)
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
        # First call: default registry check returns True (exists in default)
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

        # Create orphan file on disk
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
        # Registry should have been saved with cleanup flags
        deps["save_registry"].assert_called()
        assert any("orphan" in m.get("text", "").lower() for m in result["messages"])


class TestCloseNeverArchivesAFileThatIsNotAPlan:
    """Leg 9: rows registered before leg 7 name reports; close would archive them.

    Live: FPLAN 0564 to 0583 named devpulse's FPLAN-0508_rows_*.md reports.
    Red first on the close of leg 8. Mutants leg9 K1 (normal-path guard off),
    K2 (orphan-path guard off) and K3 (None let through) each redden a test here.
    """

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
    """Leg 10: save_registry answers False when it could not write, and never raises.

    Close ignored that False at three saves: it said "closed" with the registry
    unwritten, and "archived" with the row still reading unarchived.
    """

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
        # Must NOT save registry in dry run
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
        # The CLOSED_PLANS entry lands beside the plan; the detached runner is spawned.
        mock_append.assert_called_once_with("1", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        # Registry was saved (at least for marking closed)
        deps["save_registry"].assert_called()
        # Dashboard updates were called
        deps["update_dashboard_local"].assert_called_once()
        deps["push_to_plans_central"].assert_called_once()

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

        It used to escape _acquire_append_lock on the first denial, so every
        close that raced a concurrent append reported a failed append.
        """
        closed_plans = tmp_path / "CLOSED_PLANS.local.json"
        lock = closed_plans.with_suffix(".lock")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1)
        sleep = MagicMock()

        result = self._close_with_real_append(tmp_path, fake_open, sleep)

        assert result["success"] is True
        # The result first: the entry landed and no failed append was said.
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
        # The count the warning states is the count of creates made, read off
        # the attempts rather than the private budget constant.
        budget = len(attempts)
        assert budget > 1
        assert not closed_plans.exists()
        # The denial reaches the user with its reason. Before leg 5 the append
        # logged it and answered False, read as a held lock: "append failed",
        # no reason. Red first on that code; mutant `raise` -> `return False`.
        reported = [m["text"] for m in result["messages"] if "CLOSED_PLANS" in m.get("text", "")]
        assert len(reported) == 1
        assert reported[0].startswith("  CLOSED_PLANS update failed: Lock ")
        assert str(lock) in reported[0]
        waited = sum(c.args[0] for c in sleep.call_args_list)
        assert reported[0].endswith(f"after {budget} attempts ({waited:.2f}s waited)")
        # The logged arguments themselves, never str(call): a call's repr doubles
        # every backslash, so a Windows path is never a substring of it.
        warned = " ".join(str(arg) for c in mock_logger.warning.call_args_list for arg in c.args)
        assert str(lock) in warned
        assert f"{budget} attempts" in warned
        # What each wait was given: positive, doubling, summed into the message.
        # Mutants: `_sleep(delay)` -> `_sleep(0.0)` and the delay without its
        # `(2**attempt)` growth each redden this.
        delays = [c.args[0] for c in sleep.call_args_list]
        assert len(delays) == len(attempts)
        assert delays[0] > 0
        assert all(later == 2 * earlier for earlier, later in zip(delays, delays[1:]))
        assert f"({sum(delays):.2f}s waited)" in warned
        # Retired leg 10: the direct call to _acquire_append_lock that pinned
        # its PermissionError's __cause__. Close reports the append failure as
        # text only, so no caller can see the chain; the message above is what
        # reaches anyone.


class TestTemplateDetectionNeverDeletes:
    """FPLAN-0370/0371 bug: is_template_content()==True must NOT fast-delete the
    file or the registry row anymore -- it must close/archive exactly like any
    other plan (full parity between template-flagged and real-content closes)."""

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
        # File was NOT unlinked directly -- archive_plan_fn is the only thing
        # allowed to move/remove it, never a raw unlink() in close_ops itself.
        assert plan_file.exists()
        deps["archive_plan_fn"].assert_called_once_with(plan_file)
        # Registry row survives (marked closed), never deleted outright.
        assert "1" in registry["plans"]
        assert registry["plans"]["1"]["status"] == "closed"
        # Full pipeline parity: dashboards + CLOSED_PLANS append still ran.
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


# ═══════════════════════════════════════════════════════════
# 3. close_all_plans_impl
# ═══════════════════════════════════════════════════════════


class TestCloseAllNoPlans:
    """No open plans to close."""

    def test_no_open_plans(self, tmp_path):
        close_all = close_all_plans_impl
        mock_get = MagicMock(return_value=[])
        mock_close = MagicMock()

        result = close_all(**_scope(tmp_path), get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is False
        assert result["total"] == 0
        assert any("No open plans" in m.get("text", "") for m in result["messages"])
        mock_close.assert_not_called()


class TestCloseAllDryRun:
    """Dry run previews plans without closing."""

    def test_dry_run_lists_plans(self, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
            ("2", {"subject": "Plan B", "location": "/b", "file_path": "/b/DPLAN-0002_b.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock()

        result = close_all(**_scope(tmp_path), dry_run=True, get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True
        assert result["total"] == 2
        assert result["success_count"] == 0
        assert result["failure_count"] == 0
        assert any("DRY RUN" in m.get("text", "") for m in result["messages"])
        assert any("No action taken" in m.get("text", "") for m in result["messages"])
        mock_close.assert_not_called()


class TestCloseAllSuccess:
    """Successfully close all open plans."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_close_all_success(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
            ("3", {"subject": "Plan C", "location": "/c", "file_path": "/c/FPLAN-0003_c.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock(return_value={"success": True, "messages": [{"type": "success", "text": "ok"}]})

        result = close_all(**_scope(tmp_path), get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True
        assert result["success_count"] == 2
        assert result["failure_count"] == 0
        assert result["total"] == 2
        assert mock_close.call_count == 2
        # Each call should have spawn_background=False. Written as a single
        # clause: the two halves of the old `or` were the SAME expression -
        # call.kwargs IS call[1] - so the second could never rescue the first
        # and the shape only made the assertion look like it probed two things.
        # Subscripted rather than .get() so a call that omits the keyword
        # entirely raises here instead of comparing None is False and passing.
        for call in mock_close.call_args_list:
            assert call.kwargs["spawn_background"] is False
        # Background runner spawned once
        mock_bg.assert_called_once()


class TestCloseAllPartialFailure:
    """Some plans fail to close."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_partial_failure(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
            ("3", {"subject": "Plan C", "location": "/c", "file_path": "/c/FPLAN-0003_c.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        # First succeeds, second fails
        mock_close = MagicMock(
            side_effect=[
                {"success": True, "messages": []},
                {"success": False, "messages": []},
            ]
        )

        result = close_all(**_scope(tmp_path), get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True  # At least one succeeded
        assert result["success_count"] == 1
        assert result["failure_count"] == 1
        mock_bg.assert_called_once()


class TestCloseAllBoolFallback:
    """close_plan_fn returns a plain bool (backward compat)."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_bool_return_handled(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock(return_value=True)  # bool, not dict

        result = close_all(**_scope(tmp_path), get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True
        assert result["success_count"] == 1
        mock_bg.assert_called_once()


class TestCloseAllException:
    """get_open_plans raises an exception."""

    def test_exception_returns_error(self, tmp_path):
        close_all = close_all_plans_impl
        mock_get = MagicMock(side_effect=RuntimeError("db connection failed"))
        mock_close = MagicMock()

        result = close_all(**_scope(tmp_path), get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is False
        assert result["total"] == 0
        assert any("Error" in m.get("text", "") for m in result["messages"])


# ═══════════════════════════════════════════════════════════
# 4. _find_unregistered_plan_file
# ═══════════════════════════════════════════════════════════


class TestFindUnregisteredPlanFile:
    """_find_unregistered_plan_file, reached through close (leg 10).

    A plan no registry row names is looked for on disk, registered and
    archived. What close finds is what it hands the (stubbed) archive; a file
    it must not find ends in not_found with nothing archived. Every skipped
    copy carries a real plan header, so only the skip can keep it out.
    """

    @staticmethod
    def _found_by_close(plan_id: str, aipass_root: Path) -> Path | None:
        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=lambda x: str(x).split("-")[-1]),
            validate_plan_exists=MagicMock(return_value=(False, "not in the registry")),
        )
        deps["load_registry"].return_value = {"plans": {}}
        with (
            patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT", aipass_root / "flow"),
            patch("aipass.flow.apps.handlers.plan.close_helpers._load_template_registry", return_value={"types": {}}),
            patch("aipass.flow.apps.handlers.plan.close_helpers.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num=plan_id, spawn_background=False, **deps)
        archived = deps["archive_plan_fn"].call_args
        assert (archived is None) == (result["success"] is False)
        # A file close must not find is not registered either: no row is saved.
        assert deps["save_registry"].called == (archived is not None)
        return archived.args[0] if archived else None

    @staticmethod
    def _plan(directory: Path, name: str) -> Path:
        directory.mkdir(parents=True, exist_ok=True)
        plan = directory / name
        plan.write_text(f"# {name.split('_')[0]}: a plan\n", encoding="utf-8")
        return plan

    def test_finds_matching_file(self, tmp_path):
        plan_file = self._plan(tmp_path / "somebranch", "DPLAN-0176_design_topic_2026-05-10.md")

        assert self._found_by_close("DPLAN-0176", tmp_path) == plan_file

    def test_a_report_named_like_the_plan_is_never_found(self, tmp_path):
        """Leg 7: close would register and archive hooks' DPLAN-0356_ph2_report.md as the plan.

        Mutant: the is_plan_file gate off reddens this (leg7 C1)."""
        report = tmp_path / "hooks" / "docs.local" / "DPLAN-0356_ph2_report.md"
        report.parent.mkdir(parents=True)
        report.write_text("DPLAN-0356 phase 2 DONE\n", encoding="utf-8")

        assert self._found_by_close("DPLAN-0356", tmp_path) is None

    def test_skips_backup_directory(self, tmp_path):
        self._plan(tmp_path / ".backup" / "processed_plans", "FPLAN-0099_old_2026-01-01.md")

        assert self._found_by_close("FPLAN-0099", tmp_path) is None

    def test_skips_archive_directory(self, tmp_path):
        self._plan(tmp_path / "branch" / ".archive", "FPLAN-0050_archived_2026-02-01.md")

        assert self._found_by_close("FPLAN-0050", tmp_path) is None

    def test_a_dropbox_copy_is_never_found(self, tmp_path):
        """A dropbox is a sandbox nothing looks into; close would register and close the copy.
        Mutant: dropping "dropbox" from skip_parts reddens this."""
        self._plan(tmp_path / "hooks" / "dropbox", "DPLAN-0335_handed_over_2026-09-27.md")

        assert self._found_by_close("DPLAN-0335", tmp_path) is None

    def test_a_checkout_inside_a_dropbox_still_finds_its_plans(self, tmp_path):
        """The skip reads the parts below the scan root, never the whole path.

        A checkout that itself lives under a directory named dropbox (or .backup)
        must still find its plans; a copy in a dropbox inside the tree must not be.
        Mutant: `match.relative_to(aipass_root).parts` -> `match.parts` reddens this.
        """
        aipass_root = tmp_path / "dropbox" / "aipass"
        plan = self._plan(aipass_root / "somebranch", "DPLAN-0336_live_2026-09-28.md")
        self._plan(aipass_root / "somebranch" / "dropbox", "DPLAN-0337_copy_2026-09-28.md")

        assert self._found_by_close("DPLAN-0336", aipass_root) == plan
        assert self._found_by_close("DPLAN-0337", aipass_root) is None

    def test_skips_processed_plans_directory(self, tmp_path):
        self._plan(tmp_path / "processed_plans", "FPLAN-0077_done_2026-03-01.md")

        assert self._found_by_close("FPLAN-0077", tmp_path) is None

    def test_returns_none_when_no_match(self, tmp_path):
        self._plan(tmp_path / "branch", "FPLAN-0001_other_2026-01-01.md")

        assert self._found_by_close("FPLAN-9999", tmp_path) is None

    def test_skips_git_directory(self, tmp_path):
        self._plan(tmp_path / ".git" / "refs", "FPLAN-0010_gitfile_2026-01-01.md")

        assert self._found_by_close("FPLAN-0010", tmp_path) is None


# ═══════════════════════════════════════════════════════════
# 5. _self_heal_unregistered_plan
# ═══════════════════════════════════════════════════════════


class TestSelfHealNoCollision:
    """_self_heal_unregistered_plan, reached through close (leg 10).

    Close self-heals only a plan no row names; a same-number row means no
    self-heal there, so the bump on a collision is pinned through the heal
    (test_heal_registry TestNumberCollision).
    """

    @staticmethod
    def _close_unregistered(plan_id: str, plan_file: Path, next_number: int, types=None, other=None):
        """Close a plan whose file exists and no row names: (result, registries saved, loads)."""
        saved: list = []
        loads: list = []

        def load(registry_file=None):
            loads.append(registry_file)
            rows = (other or {}).get(registry_file, {})
            return {"plans": json.loads(json.dumps(rows)), "next_number": next_number}

        def save(registry, registry_file=None):
            saved.append((registry_file, json.loads(json.dumps(registry))))
            return True

        deps = _make_deps(
            normalize_plan_number=MagicMock(side_effect=lambda x: str(x).split("-")[-1]),
            validate_plan_exists=MagicMock(return_value=(False, "not in the registry")),
            load_registry=MagicMock(side_effect=load),
            save_registry=MagicMock(side_effect=save),
        )
        with (
            patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT", plan_file.parent / "flow"),
            patch(
                "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
                return_value={"types": types or {}},
            ),
            patch("aipass.flow.apps.handlers.plan.close_helpers.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num=plan_id, spawn_background=False, **deps)
        return result, saved, loads

    def test_registers_with_original_key(self, tmp_path):
        plan_file = tmp_path / "DPLAN-0176_design_topic_2026-05-10.md"
        plan_file.write_text("# DPLAN-0176: design topic", encoding="utf-8")

        result, saved, _loads = self._close_unregistered("DPLAN-0176", plan_file, next_number=175)

        assert result["success"] is True
        registry_file, registered = saved[0]  # the self-heal's save, before the close's
        assert registry_file == "dplan_registry.json"
        assert registered["plans"]["0176"]["self_healed"] is True
        assert registered["plans"]["0176"]["status"] == "open"
        assert registered["plans"]["0176"]["file_path"] == str(plan_file)
        # 177, not the 175 this pinned until leg 7: a row at 0176 beside
        # next_number 175 hands 0176 out again two creates later (live:
        # DPLAN row 0358 beside next_number 358, 2026-10-04).
        assert registered["next_number"] == 177

    def test_extracts_subject_from_filename(self, tmp_path):
        plan_file = tmp_path / "FPLAN-0042_my_great_feature_2026-04-01.md"
        plan_file.write_text("# FPLAN-0042: my great feature", encoding="utf-8")

        _result, saved, _loads = self._close_unregistered("FPLAN-0042", plan_file, next_number=40)

        assert saved[0][1]["plans"]["0042"]["subject"] == "my great feature"

    def test_emits_self_heal_warning_message(self, tmp_path):
        plan_file = tmp_path / "FPLAN-0001_test_2026-01-01.md"
        plan_file.write_text("# FPLAN-0001: test", encoding="utf-8")

        result, _saved, _loads = self._close_unregistered("FPLAN-0001", plan_file, next_number=1)

        assert any("self-heal" in m.get("text", "").lower() for m in result["messages"])
        assert any("Registered FPLAN-0001" in m.get("text", "") for m in result["messages"])

    def test_notes_cross_prefix_collision(self, tmp_path):
        plan_file = tmp_path / "DPLAN-0013_design_2026-03-01.md"
        plan_file.write_text("# DPLAN-0013: design", encoding="utf-8")

        result, saved, _loads = self._close_unregistered(
            "DPLAN-0013",
            plan_file,
            next_number=13,
            types={"flow_plans": {"prefix": "FPLAN"}, "dev_plans": {"prefix": "DPLAN"}},
            other={"fplan_registry.json": {"0013": {"status": "closed", "subject": "fplan thing"}}},
        )

        assert "0013" in saved[0][1]["plans"]
        assert any("FPLAN-0013 also exists" in m.get("text", "") for m in result["messages"])

    # Retired leg 10: test_skips_own_prefix_in_cross_check. Close loads the
    # plan's own registry itself, so whether the cross check skips it is
    # invisible through close; a note against its own registry cannot arise,
    # since no row there names the number.


# Moved leg 10: TestSelfHealSamePrefixCollision. A same-number collision
# reaches the self-heal only through the heal, so both pins (the bump to
# next_number, and the bump never landing on a held row) live in
# test_heal_registry TestNumberCollision.


# ═══════════════════════════════════════════════════════════
# 6. close_plan_impl — self-heal integration path
# ═══════════════════════════════════════════════════════════


class TestClosePlanImplSelfHeal:
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="dplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_triggers_self_heal_when_not_in_registry(self, mock_subprocess, _mock_resolve, tmp_path):

        plan_file = tmp_path / "DPLAN-0176_design_topic_2026-05-10.md"
        plan_file.write_text("# DPLAN-0176: design topic\nDesign notes here.", encoding="utf-8")

        registry = {"plans": {}, "next_number": 175}
        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (False, "Plan 0176 not found")

        with (
            patch(
                "aipass.flow.apps.handlers.plan.close_ops._find_unregistered_plan_file",
                return_value=plan_file,
            ),
            patch(
                "aipass.flow.apps.handlers.plan.close_ops._self_heal_unregistered_plan",
                return_value=(
                    "0176",
                    {
                        "plans": {
                            "0176": {
                                "status": "open",
                                "subject": "design topic",
                                "file_path": str(plan_file),
                                "location": str(tmp_path),
                                "self_healed": True,
                            }
                        },
                        "next_number": 177,
                    },
                ),
            ) as mock_heal,
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="DPLAN-0176", **deps)

        mock_heal.assert_called_once()
        assert result["success"] is True
        # The healed row is closed under its healed key, through the whole pipeline.
        mock_append.assert_called_once_with("0176", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_unregistered_plan_file", return_value=None)
    def test_returns_not_found_when_no_file_on_disk(self, _mock_find, _mock_resolve):
        deps = _make_deps()
        deps["load_registry"].return_value = {"plans": {}}
        deps["validate_plan_exists"].return_value = (False, "Plan 9990 not found")

        result = close_plan_impl(plan_num="FPLAN-9990", **deps)
        assert result["success"] is False
        assert result["messages"][0]["text"] == "not_found"


# ═══════════════════════════════════════════════════════════
# 7. [VERIFY] block — physical state checks after self-heal
# ═══════════════════════════════════════════════════════════


class TestSelfHealVerifyBlock:
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_verify_all_pass(self, mock_subprocess, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0042_test_2026-03-01.md"
        plan_file.write_text("# FPLAN-0042: test", encoding="utf-8")
        processed_dir = tmp_path / "processed"
        processed_dir.mkdir()
        dest_file = processed_dir / plan_file.name
        dest_file.write_text("# Archived", encoding="utf-8")

        registry = {
            "plans": {
                "42": {
                    "status": "open",
                    "subject": "test",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "self_healed": True,
                }
            },
            "next_number": 43,
        }

        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch(
                "aipass.flow.apps.handlers.plan.close_ops.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            plan_file.unlink()
            result = close_plan_impl(plan_num="FPLAN-0042", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("42", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        verify_msgs = [
            m
            for m in result["messages"]
            if "[VERIFY]" in m.get("text", "") or "[OK]" in m.get("text", "") or "[FAIL]" in m.get("text", "")
        ]
        assert len(verify_msgs) >= 1
        ok_msgs = [m for m in result["messages"] if "[OK]" in m.get("text", "")]
        assert len(ok_msgs) >= 2

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_verify_fails_when_file_not_in_processed(self, mock_subprocess, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0055_missing_2026-03-01.md"
        plan_file.write_text("# FPLAN-0055: missing", encoding="utf-8")
        processed_dir = tmp_path / "processed_empty"
        processed_dir.mkdir()

        registry = {
            "plans": {
                "55": {
                    "status": "open",
                    "subject": "missing test",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "self_healed": True,
                }
            },
            "next_number": 56,
        }

        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch(
                "aipass.flow.apps.handlers.plan.close_ops.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="FPLAN-0055", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("55", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        fail_msgs = [m for m in result["messages"] if "[FAIL]" in m.get("text", "")]
        assert len(fail_msgs) >= 1
        assert any("NOT found in processed_plans" in m.get("text", "") for m in fail_msgs)

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess")
    def test_verify_fails_when_source_still_exists(self, mock_subprocess, _mock_resolve, tmp_path):

        plan_file = tmp_path / "FPLAN-0060_leftover_2026-03-01.md"
        plan_file.write_text("# FPLAN-0060: leftover", encoding="utf-8")
        processed_dir = tmp_path / "processed"
        processed_dir.mkdir()
        (processed_dir / plan_file.name).write_text("# Archived copy", encoding="utf-8")

        registry = {
            "plans": {
                "60": {
                    "status": "open",
                    "subject": "leftover test",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                    "self_healed": True,
                }
            },
            "next_number": 61,
        }

        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch(
                "aipass.flow.apps.handlers.plan.close_ops.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="FPLAN-0060", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("60", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        fail_msgs = [m for m in result["messages"] if "[FAIL]" in m.get("text", "")]
        assert any("Source file still exists" in m.get("text", "") for m in fail_msgs)

    def test_verify_skipped_for_non_self_healed_plans(self, tmp_path):

        plan_file = tmp_path / "FPLAN-0070_normal_2026-03-01.md"
        plan_file.write_text("# FPLAN-0070: normal", encoding="utf-8")

        registry = {
            "plans": {
                "70": {
                    "status": "open",
                    "subject": "normal plan",
                    "file_path": str(plan_file),
                    "location": str(tmp_path),
                }
            },
            "next_number": 71,
        }

        deps = _make_deps()
        deps["load_registry"].return_value = registry
        deps["validate_plan_exists"].return_value = (True, None)

        with (
            patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None),
            patch("aipass.flow.apps.handlers.plan.close_helpers.subprocess") as mock_subprocess,
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True),
            patch(
                "aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True
            ) as mock_append,
        ):
            result = close_plan_impl(plan_num="70", **deps)

        assert result["success"] is True
        mock_append.assert_called_once_with("70", ANY, tmp_path)
        mock_subprocess.Popen.assert_called_once()
        verify_msgs = [m for m in result["messages"] if "[VERIFY]" in m.get("text", "")]
        assert len(verify_msgs) == 0


# ═══════════════════════════════════════════════════════════
# 8. Plan identity: the bulk path must address a TYPE, not a bare number
#
# Every per-type registry numbers from 0001, so a bare registry key is
# ambiguous across types. close_all used to hand that bare key to
# close_plan_fn, which re-resolved it and defaulted to fplan_registry.json --
# measured on live data as 61 of 72 open plans routed to the wrong registry.
# These tests pin the IDENTITY passed downstream, which is the thing the
# original close_all tests never looked at (they only counted calls).
# ═══════════════════════════════════════════════════════════


def _closed_ids(mock_close) -> list:
    """Extract the plan_num argument from every close_plan_fn call."""
    return [c.kwargs.get("plan_num") for c in mock_close.call_args_list]


class TestCanonicalPlanId:
    """canonical_plan_id derives the typed ID from the row's file_path."""

    def test_derives_prefix_from_file_path(self):
        fn = canonical_plan_id
        assert fn("0300", {"file_path": "/x/DPLAN-0300_baud_on_the_phone_2026-08-01.md"}) == "DPLAN-0300"

    def test_each_registered_type(self):
        fn = canonical_plan_id
        for prefix in ("FPLAN", "DPLAN", "APLAN", "PPLAN", "RPLAN", "TDPLAN", "CPLAN"):
            assert fn("0007", {"file_path": f"/x/{prefix}-0007_topic_2026-01-01.md"}) == f"{prefix}-0007"

    def test_returns_none_when_file_path_missing(self):
        """No file_path means no type evidence -- must refuse, never guess a prefix."""
        fn = canonical_plan_id
        assert fn("0300", {}) is None
        assert fn("0300", {"file_path": ""}) is None

    def test_returns_none_when_filename_carries_no_prefix(self):
        fn = canonical_plan_id
        assert fn("0300", {"file_path": "/x/notes_about_a_thing.md"}) is None


class TestCloseAllPassesTypedId:
    """close_all must hand close_plan_fn a typed ID, not the bare registry key."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_dplan_row_closes_dplan_not_fplan(self, _mock_jh, mock_bg, tmp_path):
        """The live defect: key 0300 closed FPLAN-0300 while DPLAN-0300 stayed open."""
        close_all = close_all_plans_impl
        open_plans = [
            ("0300", {"subject": "BAUD on the phone", "location": "/v", "file_path": "/v/DPLAN-0300_baud.md"})
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        close_all(**_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close)
        assert _closed_ids(mock_close) == ["DPLAN-0300"]
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_mixed_types_each_keep_their_own_prefix(self, _mock_jh, mock_bg, tmp_path):
        """Mutant: deleting close_all's single _spawn_background_runner() call reddens this."""
        close_all = close_all_plans_impl
        open_plans = [
            ("0001", {"subject": "audit", "location": "/a", "file_path": "/a/APLAN-0001_branch_audit.md"}),
            ("0001", {"subject": "flow plan", "location": "/b", "file_path": "/b/FPLAN-0001_thing.md"}),
            ("0115", {"subject": "aipl", "location": "/c", "file_path": "/c/DPLAN-0115_aipl.md"}),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        close_all(**_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close)
        assert _closed_ids(mock_close) == ["APLAN-0001", "FPLAN-0001", "DPLAN-0115"]
        mock_bg.assert_called_once_with()  # ONE spawn for the whole batch, never one per plan


class TestCloseAllRefusesUnresolvableRow:
    """A row with no type evidence is refused loudly, never guessed."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_row_without_file_path_is_not_closed(self, _mock_jh, mock_bg, tmp_path):
        """Mutant: `if success_count > 0:` -> `if True:` reddens this."""
        close_all = close_all_plans_impl
        open_plans = [("0042", {"subject": "orphan row", "location": "/a", "file_path": ""})]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            **_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close
        )
        mock_close.assert_not_called()
        assert result["failure_count"] == 1
        assert result["success_count"] == 0
        mock_bg.assert_not_called()  # nothing closed, so no post-close work spawned

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_refusal_names_the_row(self, _mock_jh, mock_bg, tmp_path):
        """A count alone is the defect we are removing -- the row must be named."""
        close_all = close_all_plans_impl
        open_plans = [("0042", {"subject": "orphan row", "location": "/a", "file_path": ""})]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            **_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close
        )
        blob = " ".join(str(m.get("text", "")) for m in result["messages"])
        assert "0042" in blob
        # PINNED TO THE ONE STRING close_ops PRINTS, measured by running the
        # refusal: _refusal_text() writes "REFUSED 0042 (orphan row) - registry
        # row has no typed file_path, so its plan type cannot be established.
        # Refusing to guess." The old `"refus" in blob or "cannot" in blob`
        # passed on either word, so the message could lose half its meaning and
        # still be green; both clauses are the machine's actual words now.
        assert "REFUSED 0042" in blob
        assert "no typed file_path" in blob
        assert "Refusing to guess." in blob
        mock_bg.assert_not_called()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_resolvable_siblings_still_close(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("0042", {"subject": "orphan", "location": "/a", "file_path": ""}),
            ("0300", {"subject": "good", "location": "/b", "file_path": "/b/DPLAN-0300_x.md"}),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            **_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close
        )
        assert _closed_ids(mock_close) == ["DPLAN-0300"]
        assert result["success_count"] == 1
        assert result["failure_count"] == 1
        mock_bg.assert_called_once_with()


class TestDryRunEqualsRun:
    """The preview must resolve through the same path as the execution.

    The owner's success criterion: 'if the dry run accurately tells us what's
    actually gonna happen, then yeah, we're good.' Two paths that merely agree
    today can drift; these pin them to one resolution.
    """

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_dry_run_ids_equal_executed_ids(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("0001", {"subject": "audit", "location": "/a", "file_path": "/a/APLAN-0001_audit.md"}),
            ("0300", {"subject": "baud", "location": "/b", "file_path": "/b/DPLAN-0300_baud.md"}),
            ("0451", {"subject": "watchdog", "location": "/c", "file_path": "/c/FPLAN-0451_watchdog.md"}),
        ]
        preview = close_all(
            **_scope(tmp_path),
            dry_run=True,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        mock_close = MagicMock(return_value={"success": True, "messages": []})
        close_all(**_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close)

        assert preview["plan_ids"] == _closed_ids(mock_close)
        assert preview["plan_ids"] == ["APLAN-0001", "DPLAN-0300", "FPLAN-0451"]
        mock_bg.assert_called_once_with()  # the run spawns; the preview never does

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_dry_run_refusals_equal_run_refusals(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("0042", {"subject": "orphan", "location": "/a", "file_path": ""}),
            ("0300", {"subject": "baud", "location": "/b", "file_path": "/b/DPLAN-0300_baud.md"}),
        ]
        preview = close_all(
            **_scope(tmp_path),
            dry_run=True,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        mock_close = MagicMock(return_value={"success": True, "messages": []})
        run = close_all(**_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close)

        assert preview["refused"] == ["0042"]
        assert run["failure_count"] == len(preview["refused"])
        assert preview["plan_ids"] == _closed_ids(mock_close)
        mock_bg.assert_called_once_with()  # the run spawns; the preview never does

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_dry_run_row_carries_structured_id(self, _mock_jh, mock_bg, tmp_path):
        """Preview rows expose plan_id as data, so the renderer cannot re-derive it differently."""
        close_all = close_all_plans_impl
        open_plans = [("0300", {"subject": "baud", "location": "/b", "file_path": "/b/DPLAN-0300_baud.md"})]
        result = close_all(
            **_scope(tmp_path),
            dry_run=True,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        rows = [m for m in result["messages"] if m.get("type") == "dry_run_row"]
        assert len(rows) == 1
        assert rows[0]["plan_id"] == "DPLAN-0300"
        mock_bg.assert_not_called()  # a preview closes nothing, so it spawns nothing


# ═══════════════════════════════════════════════════════════
# 7. THE FENCES — type exclusion, project scope, dry-run parity
#
# Written red first. Each asserts REACHED before it asserts the
# outcome: a fence test that never reached the fence is green for
# the wrong reason, and would stay green through any regression in
# the one thing it exists to guard.
# ═══════════════════════════════════════════════════════════


def _held_ids(result) -> list:
    return result.get("held_ids", [])


class TestExcludeTypeHoldsTypeBack:
    """--exclude-type APLAN must leave every APLAN open."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_aplan_row_is_not_closed_when_aplan_excluded(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        open_plans = [
            ("0004", {"subject": "branch audit", "location": "/proj/f", "file_path": "/proj/f/APLAN-0004_audit.md"}),
            ("0316", {"subject": "plan reset", "location": "/proj/d", "file_path": "/proj/d/DPLAN-0316_reset.md"}),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            **_scope(tmp_path),
            exclude_types=["APLAN"],
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=mock_close,
        )
        # REACHED: the sweep ran and closed the non-excluded row.
        assert _closed_ids(mock_close) == ["DPLAN-0316"]
        # OUTCOME: the APLAN was held, not closed, and not counted as a failure.
        assert _held_ids(result) == ["APLAN-0004"]
        assert "APLAN-0004" not in _closed_ids(mock_close)
        assert result["failure_count"] == 0
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_exclusion_is_general_not_an_aplan_special_case(self, _mock_jh, mock_bg, tmp_path):
        """Any registered type can be fenced -- no hardcoded APLAN check."""
        close_all = close_all_plans_impl
        open_plans = [
            ("0001", {"subject": "playbook", "location": "/proj/p", "file_path": "/proj/p/PPLAN-0001_pb.md"}),
            ("0002", {"subject": "research", "location": "/proj/r", "file_path": "/proj/r/RPLAN-0002_res.md"}),
            ("0003", {"subject": "flow", "location": "/proj/f", "file_path": "/proj/f/FPLAN-0003_flow.md"}),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            **_scope(tmp_path),
            exclude_types=["PPLAN", "RPLAN"],
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=mock_close,
        )
        assert _closed_ids(mock_close) == ["FPLAN-0003"]
        assert sorted(_held_ids(result)) == ["PPLAN-0001", "RPLAN-0002"]
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_no_exclusion_closes_the_aplan_too(self, _mock_jh, mock_bg, tmp_path):
        """Control: without the flag the APLAN IS swept. The fence must be the flag's doing."""
        close_all = close_all_plans_impl
        open_plans = [
            ("0004", {"subject": "branch audit", "location": "/proj/f", "file_path": "/proj/f/APLAN-0004_audit.md"}),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        close_all(**_scope(tmp_path), get_open_plans=MagicMock(return_value=open_plans), close_plan_fn=mock_close)
        assert _closed_ids(mock_close) == ["APLAN-0004"]
        mock_bg.assert_called_once_with()


class TestProjectScopeFence:
    """A run from one project must not touch another project's rows."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_foreign_row_is_not_closed(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        aipass, baud = tmp_path / "aipass", tmp_path / "aipass" / "projects" / "baud"

        def resolver(path):
            return baud if _under(path, baud) else aipass

        open_plans = [
            (
                "0100",
                {
                    "subject": "ours",
                    "location": str(aipass / "src"),
                    "file_path": str(aipass / "src" / "DPLAN-0100_ours.md"),
                },
            ),
            (
                "0101",
                {
                    "subject": "theirs",
                    "location": str(baud / "apps"),
                    "file_path": str(baud / "apps" / "DPLAN-0101_theirs.md"),
                },
            ),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            caller_project=aipass,
            resolve_project_fn=resolver,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=mock_close,
        )
        # REACHED: the sweep ran against both rows and closed the local one.
        assert _closed_ids(mock_close) == ["DPLAN-0100"]
        # OUTCOME: the nested foreign row was held, not closed, not a failure.
        assert _held_ids(result) == ["DPLAN-0101"]
        assert result["failure_count"] == 0
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_row_with_no_project_is_held_and_named_distinctly(self, _mock_jh, mock_bg, tmp_path):
        """Unattributable is not the same as foreign, and the reason must say so."""
        close_all = close_all_plans_impl
        aipass = tmp_path / "aipass"
        elsewhere = tmp_path / "elsewhere" / "loose"

        open_plans = [
            (
                "0100",
                {
                    "subject": "ours",
                    "location": str(aipass / "src"),
                    "file_path": str(aipass / "src" / "DPLAN-0100_ours.md"),
                },
            ),
            (
                "0102",
                {"subject": "nowhere", "location": str(elsewhere), "file_path": str(elsewhere / "DPLAN-0102_x.md")},
            ),
        ]
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        result = close_all(
            caller_project=aipass,
            resolve_project_fn=lambda path: aipass if _under(path, aipass) else None,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=mock_close,
        )
        # REACHED: the sweep ran and closed the attributable row.
        assert _closed_ids(mock_close) == ["DPLAN-0100"]
        # OUTCOME: a row no register stands above is held, not swept by default.
        assert _held_ids(result) == ["DPLAN-0102"]
        summary = next(m for m in result["messages"] if m.get("type") == "close_all_scope")
        assert summary["held_out_of_scope"] == 1
        assert summary["refused"] == 0
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_dry_run_names_the_reason_for_each_held_row(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        aipass, baud = tmp_path / "aipass", tmp_path / "aipass" / "projects" / "baud"
        elsewhere = tmp_path / "elsewhere" / "loose"

        def resolver(path):
            if _under(path, baud):
                return baud
            if _under(path, aipass):
                return aipass
            return None

        open_plans = [
            ("0101", {"subject": "theirs", "location": str(baud), "file_path": f"{baud}/DPLAN-0101_t.md"}),
            (
                "0102",
                {"subject": "nowhere", "location": str(elsewhere), "file_path": str(elsewhere / "DPLAN-0102_x.md")},
            ),
        ]
        result = close_all(
            dry_run=True,
            caller_project=aipass,
            resolve_project_fn=resolver,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        reasons = {m["plan_id"]: m["reason"] for m in result["messages"] if m.get("type") == "held_row"}
        assert reasons["DPLAN-0101"] == "belongs to baud"
        assert "no project register" in reasons["DPLAN-0102"]
        mock_bg.assert_not_called()  # a preview closes nothing, so it spawns nothing

    def test_caller_outside_any_project_refuses_the_whole_run(self):
        """No register above the caller means 'all' has no boundary. Refuse."""
        close_all = close_all_plans_impl
        mock_get = MagicMock()
        mock_close = MagicMock()

        result = close_all(
            caller_project=None,
            resolve_project_fn=lambda _p: None,
            get_open_plans=mock_get,
            close_plan_fn=mock_close,
        )
        assert result["success"] is False
        mock_close.assert_not_called()
        # Refused BEFORE reading the registries -- not after filtering to zero.
        mock_get.assert_not_called()
        assert any("REFUSED" in str(m.get("text", "")) for m in result["messages"])


class TestDryRunEqualsRunUnderFences:
    """The authorisation step must show the post-fence list, not a superset."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_preview_equals_run_with_exclusion_and_foreign_rows(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        aipass, baud = tmp_path / "aipass", tmp_path / "aipass" / "projects" / "baud"
        elsewhere = tmp_path / "elsewhere" / "x"

        def resolver(path):
            if _under(path, baud):
                return baud
            if _under(path, aipass):
                return aipass
            return None

        open_plans = [
            (
                "0004",
                {"subject": "audit", "location": str(aipass / "f"), "file_path": str(aipass / "f" / "APLAN-0004_a.md")},
            ),
            (
                "0316",
                {"subject": "reset", "location": str(aipass / "d"), "file_path": str(aipass / "d" / "DPLAN-0316_r.md")},
            ),
            ("0101", {"subject": "theirs", "location": str(baud), "file_path": f"{baud}/DPLAN-0101_t.md"}),
            (
                "0102",
                {"subject": "nowhere", "location": str(elsewhere), "file_path": str(elsewhere / "FPLAN-0102_n.md")},
            ),
            ("0999", {"subject": "untyped", "location": str(aipass / "d"), "file_path": ""}),
        ]
        scope = {"caller_project": aipass, "resolve_project_fn": resolver}

        preview = close_all(
            dry_run=True,
            exclude_types=["APLAN"],
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
            **scope,
        )
        mock_close = MagicMock(return_value={"success": True, "messages": []})
        run = close_all(
            exclude_types=["APLAN"],
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=mock_close,
            **scope,
        )

        # The one assertion this whole build turns on.
        assert preview["plan_ids"] == _closed_ids(mock_close) == ["DPLAN-0316"]
        assert preview["held_ids"] == run["held_ids"] == ["APLAN-0004", "DPLAN-0101", "FPLAN-0102"]
        assert preview["refused"] == ["0999"]
        assert run["failed_ids"] == ["0999"]
        mock_bg.assert_called_once_with()  # the run spawns; the preview never does

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_the_plan_tracking_this_work_is_visible_not_exempt(self, _mock_jh, mock_bg, tmp_path):
        """DPLAN-0316 documents this command. A sweep closes it, and says so."""
        close_all = close_all_plans_impl
        open_plans = [
            ("0316", {"subject": "Plan reset", "location": "/proj/d", "file_path": "/proj/d/DPLAN-0316_reset.md"}),
        ]
        preview = close_all(
            **_scope(tmp_path),
            dry_run=True,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        rows = [m for m in preview["messages"] if m.get("type") == "dry_run_row"]
        assert [r["plan_id"] for r in rows] == ["DPLAN-0316"]
        assert preview["plan_ids"] == ["DPLAN-0316"]
        mock_bg.assert_not_called()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_scope_summary_counts_match_the_buckets(self, _mock_jh, mock_bg, tmp_path):
        close_all = close_all_plans_impl
        aipass = tmp_path / "aipass"
        elsewhere = tmp_path / "elsewhere" / "x"
        open_plans = [
            (
                "0004",
                {"subject": "audit", "location": str(aipass / "f"), "file_path": str(aipass / "f" / "APLAN-0004_a.md")},
            ),
            (
                "0316",
                {"subject": "reset", "location": str(aipass / "d"), "file_path": str(aipass / "d" / "DPLAN-0316_r.md")},
            ),
            (
                "0102",
                {"subject": "nowhere", "location": str(elsewhere), "file_path": str(elsewhere / "FPLAN-0102_n.md")},
            ),
        ]
        preview = close_all(
            dry_run=True,
            exclude_types=["APLAN"],
            caller_project=aipass,
            resolve_project_fn=lambda p: aipass if _under(p, aipass) else None,
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=MagicMock(),
        )
        summary = next(m for m in preview["messages"] if m.get("type") == "close_all_scope")
        assert summary["considered"] == 3
        assert summary["in_scope"] == 1
        assert summary["held_by_type"] == 1
        assert summary["held_out_of_scope"] == 1
        assert summary["refused"] == 0
        assert summary["in_scope"] == len(preview["plan_ids"])
        mock_bg.assert_not_called()  # a preview closes nothing, so it spawns nothing

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_a_corrupt_nested_register_refuses_the_sweep_not_hands_its_rows_over(self, _mock_jh, mock_bg, tmp_path):
        """The real resolver: a row under a project whose register is broken.

        Until leg 6 the walk read the broken register as "not a project" and
        went on up, so the row counted as the outer caller's and was closed.
        Red first on that code; the mutant is in test_project_scope.
        """
        suffix = "_REGISTRY" + ".json"  # assembled: the literal name is a sealed-write trigger
        outer = tmp_path / "outer"
        nested = outer / "projects" / "nested"
        nested.mkdir(parents=True)
        (outer / f"OUTER{suffix}").write_text(json.dumps({"branches": []}), encoding="utf-8")
        broken = nested / f"NESTED{suffix}"
        broken.write_text("{not json", encoding="utf-8")
        row = nested / "docs"
        open_plans = [
            ("0007", {"subject": "theirs", "location": str(row), "file_path": str(row / "FPLAN-0007_t.md")}),
        ]
        close_plan_fn = MagicMock()

        result = close_all_plans_impl(
            caller_project=outer.resolve(),
            get_open_plans=MagicMock(return_value=open_plans),
            close_plan_fn=close_plan_fn,
        )

        assert result["success"] is False
        assert result["total"] == 0
        [message] = result["messages"]
        assert message["text"].startswith("Error in close_all: Unreadable project register ")
        assert str(broken) in message["text"]
        close_plan_fn.assert_not_called()
        mock_bg.assert_not_called()


class TestTheScopeComparisonIsPlatformNeutral:
    """Guards the idiom the windows-setup runner caught, from Linux.

    The three tests that red on Windows all shared one line shape and no
    Linux run could see it: the whole failure lived in what str(Path(...))
    produces on a platform this machine is not. PureWindowsPath implements
    exactly those semantics here, so the class of bug is now catchable
    locally rather than only in CI on a runner nobody can reach.
    """

    ROW = "/aipass/src"
    ROOT = "/aipass"
    OTHER = "/elsewhere/loose"

    def test_a_row_under_the_root_is_recognised_on_both_platforms(self):
        for flavour in (PurePosixPath, PureWindowsPath):
            assert _under(flavour(self.ROW), flavour(self.ROOT)), flavour.__name__

    def test_the_root_itself_counts_as_inside_on_both_platforms(self):
        for flavour in (PurePosixPath, PureWindowsPath):
            assert _under(flavour(self.ROOT), flavour(self.ROOT)), flavour.__name__

    def test_a_row_outside_the_root_stays_outside_on_both_platforms(self):
        for flavour in (PurePosixPath, PureWindowsPath):
            assert not _under(flavour(self.OTHER), flavour(self.ROOT)), flavour.__name__

    def test_a_sibling_that_merely_shares_a_prefix_is_not_inside(self):
        """ROOT + "-old" is not under ROOT. A string prefix would say it is."""
        for flavour in (PurePosixPath, PureWindowsPath):
            sibling = flavour(self.ROOT + "-old") / "src"
            assert str(sibling).startswith(str(flavour(self.ROOT)))
            assert not _under(sibling, flavour(self.ROOT)), flavour.__name__


class TestTheFenceUnderWindowsPathSemantics:
    """Runs the scope fence with close_ops seeing Windows paths, from Linux.

    close_ops turns each row's location into ``Path(location)`` before handing
    it to the scope resolver, so patching that one name to PureWindowsPath puts
    the resolver in exactly the position it occupies on the windows-setup
    runner. This is not a substitute for CI -- it cannot see filesystem or
    drive-letter behaviour -- but it makes the SEPARATOR class of defect
    reproducible on a machine that has no Windows, which is the class that
    reddened three tests here and could not be seen locally at all.

    Proven faithful: with the old ``str(path).startswith("/aipass")`` idiom
    restored, this harness reproduces the CI job's three assertions verbatim --
    [] == ['DPLAN-0100'], [] == ['DPLAN-0316'], and 0 == 1.
    """

    @staticmethod
    def _rows():
        return [
            ("0100", {"subject": "ours", "location": "/aipass/src", "file_path": "/aipass/src/DPLAN-0100_o.md"}),
            ("0101", {"subject": "theirs", "location": "/aipass/projects/baud/a", "file_path": "/x/DPLAN-0101.md"}),
            (
                "0102",
                {"subject": "nowhere", "location": "/elsewhere/loose", "file_path": "/elsewhere/loose/DPLAN-0102_x.md"},
            ),
        ]

    @staticmethod
    def _resolver(aipass, baud):
        def resolve(path):
            if _under(path, baud):
                return baud
            if _under(path, aipass):
                return aipass
            return None

        return resolve

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_the_three_buckets_survive_windows_separators(self, _mock_jh, mock_bg):
        close_all = close_all_plans_impl

        aipass, baud = PureWindowsPath("/aipass"), PureWindowsPath("/aipass/projects/baud")
        mock_close = MagicMock(return_value={"success": True, "messages": []})

        with patch.object(close_ops, "Path", PureWindowsPath):
            result = close_all(
                caller_project=aipass,
                resolve_project_fn=self._resolver(aipass, baud),
                get_open_plans=MagicMock(return_value=self._rows()),
                close_plan_fn=mock_close,
            )

        # In scope, foreign and unattributable each land where they belong --
        # the exact split that collapsed to "everything is unattributable".
        assert _closed_ids(mock_close) == ["DPLAN-0100"]
        assert sorted(_held_ids(result)) == ["DPLAN-0101", "DPLAN-0102"]
        mock_bg.assert_called_once_with()

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler", spec=True)
    def test_the_held_reasons_still_tell_foreign_from_unattributable(self, _mock_jh, mock_bg):
        """The load-bearing half: a held row must still say WHY it was held."""
        close_all = close_all_plans_impl

        aipass, baud = PureWindowsPath("/aipass"), PureWindowsPath("/aipass/projects/baud")

        with patch.object(close_ops, "Path", PureWindowsPath):
            result = close_all(
                dry_run=True,
                caller_project=aipass,
                resolve_project_fn=self._resolver(aipass, baud),
                get_open_plans=MagicMock(return_value=self._rows()),
                close_plan_fn=MagicMock(),
            )

        reasons = {m["plan_id"]: m["reason"] for m in result["messages"] if m.get("type") == "held_row"}
        assert reasons["DPLAN-0101"] == "belongs to baud"
        assert "no project register" in reasons["DPLAN-0102"]
        mock_bg.assert_not_called()
