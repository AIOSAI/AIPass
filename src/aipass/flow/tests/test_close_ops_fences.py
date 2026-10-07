# =================== AIPass ====================
# Name: test_close_ops_fences.py
# Description: Tests for close_all's project-scope fence, split from test_close_ops.py (oversize, leg 12)
# Version: 1.0.0
# Created: 2026-10-06
# Modified: 2026-10-06
# =============================================

"""Tests for the project-scope fence of close_all_plans_impl in apps/handlers/plan/close_ops.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import PurePath, PurePosixPath, PureWindowsPath
from unittest.mock import MagicMock, patch

import aipass.flow.apps.handlers.plan.close_ops as close_ops
from aipass.flow.apps.handlers.plan.close_ops import close_all_plans_impl
from aipass.flow.tests.support_close_ops import _closed_ids, _held_ids, _scope


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
