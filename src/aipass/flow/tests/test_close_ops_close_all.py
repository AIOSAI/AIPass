# =================== AIPass ====================
# Name: test_close_ops_close_all.py
# Description: Tests for close_all_plans_impl, split from test_close_ops.py (oversize, leg 12)
# Version: 1.0.0
# Created: 2026-10-06
# Modified: 2026-10-06
# =============================================

"""Tests for close_all_plans_impl in apps/handlers/plan/close_ops.py and the typed IDs it hands on."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

from unittest.mock import MagicMock, patch

from aipass.flow.apps.handlers.plan.close_ops import close_all_plans_impl
from aipass.flow.apps.handlers.plan.registry_routing import canonical_plan_id
from aipass.flow.tests.support_close_ops import _closed_ids, _held_ids, _scope


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
# 8. Plan identity: the bulk path must address a TYPE, not a bare number
#
# Every per-type registry numbers from 0001, so a bare registry key is
# ambiguous across types. close_all used to hand that bare key to
# close_plan_fn, which re-resolved it and defaulted to fplan_registry.json --
# measured on live data as 61 of 72 open plans routed to the wrong registry.
# These tests pin the IDENTITY passed downstream, which is the thing the
# original close_all tests never looked at (they only counted calls).
# ═══════════════════════════════════════════════════════════


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
