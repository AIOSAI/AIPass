"""Tests for close_ops handler — plan closure business logic."""

from unittest.mock import MagicMock, patch


# ─── Helpers ─────────────────────────────────────────────


def _import_extract_prefix():
    from aipass.flow.apps.handlers.plan.close_ops import _extract_prefix

    return _extract_prefix


def _import_close_plan_impl():
    from aipass.flow.apps.handlers.plan.close_ops import close_plan_impl

    return close_plan_impl


def _import_close_all_plans_impl():
    from aipass.flow.apps.handlers.plan.close_ops import close_all_plans_impl

    return close_all_plans_impl


def _import_find_unregistered():
    from aipass.flow.apps.handlers.plan.close_ops import _find_unregistered_plan_file

    return _find_unregistered_plan_file


def _import_self_heal():
    from aipass.flow.apps.handlers.plan.close_ops import _self_heal_unregistered_plan

    return _self_heal_unregistered_plan


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
    }
    deps.update(overrides)
    return deps


# ═══════════════════════════════════════════════════════════
# 1. _extract_prefix
# ═══════════════════════════════════════════════════════════


class TestExtractPrefix:
    def test_fplan_prefix(self):
        fn = _import_extract_prefix()
        assert fn("FPLAN-0001") == "FPLAN"

    def test_dplan_prefix(self):
        fn = _import_extract_prefix()
        assert fn("DPLAN-0004") == "DPLAN"

    def test_lowercase_normalised_to_upper(self):
        fn = _import_extract_prefix()
        assert fn("fplan-0099") == "FPLAN"

    def test_mixed_case(self):
        fn = _import_extract_prefix()
        assert fn("Dplan-0002") == "DPLAN"

    def test_bare_number_returns_none(self):
        fn = _import_extract_prefix()
        assert fn("0001") is None

    def test_bare_number_no_dash_returns_none(self):
        fn = _import_extract_prefix()
        assert fn("42") is None

    def test_empty_string_returns_none(self):
        fn = _import_extract_prefix()
        assert fn("") is None

    def test_prefix_without_plan_suffix_returns_none(self):
        """Only strings with PLAN in the prefix match."""
        fn = _import_extract_prefix()
        assert fn("FOO-0001") is None

    def test_whitespace_stripped(self):
        fn = _import_extract_prefix()
        assert fn("  FPLAN-0001  ") == "FPLAN"

    def test_custom_plan_type_prefix(self):
        fn = _import_extract_prefix()
        assert fn("XYZPLAN-0010") == "XYZPLAN"


# ═══════════════════════════════════════════════════════════
# 2. close_plan_impl — single plan closure
# ═══════════════════════════════════════════════════════════


class TestClosePlanImplNoNumber:
    """Plan number is required for single plan closure."""

    def test_no_plan_num_returns_error(self):
        close_plan_impl = _import_close_plan_impl()
        result = close_plan_impl(plan_num=None, **_make_deps())
        assert result["success"] is False
        assert result["messages"][0]["text"] == "invalid_number"
        assert result["plan_key"] == ""

    def test_empty_string_plan_num_returns_error(self):
        close_plan_impl = _import_close_plan_impl()
        result = close_plan_impl(plan_num="", **_make_deps())
        assert result["success"] is False
        assert result["messages"][0]["text"] == "invalid_number"


class TestClosePlanImplAllFlag:
    """When all_plans=True, delegates to close_all_plans_fn."""

    def test_all_plans_delegates(self):
        close_plan_impl = _import_close_plan_impl()
        mock_close_all = MagicMock(return_value={"success": True, "messages": []})
        deps = _make_deps(close_all_plans_fn=mock_close_all)
        result = close_plan_impl(plan_num="1", all_plans=True, **deps)
        mock_close_all.assert_called_once_with(False, dry_run=False)
        assert result == {"success": True, "messages": []}


class TestClosePlanImplNotFound:
    """Plan not found in registry."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._find_unregistered_plan_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_plan_not_found_returns_error(self, _mock_find, _mock_resolve, _mock_unregistered):
        close_plan_impl = _import_close_plan_impl()
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
        close_plan_impl = _import_close_plan_impl()
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
    @patch("aipass.flow.apps.handlers.plan.close_ops.archive_plan", create=True)
    def test_already_closed_orphan_cleanup(self, mock_archive, _mock_find, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        # Create orphan file on disk
        plan_file = tmp_path / "FPLAN-0002_closed_2026-03-18.md"
        plan_file.write_text("# Plan content", encoding="utf-8")

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

        # Patch archive_plan inside the function (lazy import)
        with patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True):
            result = close_plan_impl(plan_num="2", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "2"
        # Registry should have been saved with cleanup flags
        deps["save_registry"].assert_called()
        assert any("orphan" in m.get("text", "").lower() for m in result["messages"])


class TestClosePlanImplDryRun:
    """Dry run previews without acting."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_dry_run_returns_preview(self, _mock_find, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

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
    @patch("aipass.flow.apps.handlers.plan.close_ops.subprocess")
    def test_successful_close(self, mock_subprocess, _mock_find, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# Real content\nSome actual plan notes.", encoding="utf-8")

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
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num="1", **deps)

        assert result["success"] is True
        assert result["plan_key"] == "1"
        assert result["cancelled"] is False
        # Registry was saved (at least for marking closed)
        deps["save_registry"].assert_called()
        # Dashboard updates were called
        deps["update_dashboard_local"].assert_called_once()
        deps["push_to_plans_central"].assert_called_once()


class TestClosePlanImplConfirmCancelled:
    """User cancels when confirm=True."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value=None)
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_plan_across_registries", return_value=None)
    def test_confirm_cancelled(self, _mock_find, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0001_test_2026-03-20.md"
        plan_file.write_text("# Real content", encoding="utf-8")

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
        close_plan_impl = _import_close_plan_impl()
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

    def test_no_open_plans(self):
        close_all = _import_close_all_plans_impl()
        mock_get = MagicMock(return_value=[])
        mock_close = MagicMock()

        result = close_all(get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is False
        assert result["total"] == 0
        assert any("No open plans" in m.get("text", "") for m in result["messages"])
        mock_close.assert_not_called()


class TestCloseAllDryRun:
    """Dry run previews plans without closing."""

    def test_dry_run_lists_plans(self):
        close_all = _import_close_all_plans_impl()
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
            ("2", {"subject": "Plan B", "location": "/b", "file_path": "/b/DPLAN-0002_b.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock()

        result = close_all(dry_run=True, get_open_plans=mock_get, close_plan_fn=mock_close)
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
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler")
    def test_close_all_success(self, _mock_jh, mock_bg):
        close_all = _import_close_all_plans_impl()
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
            ("3", {"subject": "Plan C", "location": "/c", "file_path": "/c/FPLAN-0003_c.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock(return_value={"success": True, "messages": [{"type": "success", "text": "ok"}]})

        result = close_all(get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True
        assert result["success_count"] == 2
        assert result["failure_count"] == 0
        assert result["total"] == 2
        assert mock_close.call_count == 2
        # Each call should have spawn_background=False
        for call in mock_close.call_args_list:
            assert call.kwargs.get("spawn_background") is False or call[1].get("spawn_background") is False
        # Background runner spawned once
        mock_bg.assert_called_once()


class TestCloseAllPartialFailure:
    """Some plans fail to close."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler")
    def test_partial_failure(self, _mock_jh, mock_bg):
        close_all = _import_close_all_plans_impl()
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

        result = close_all(get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True  # At least one succeeded
        assert result["success_count"] == 1
        assert result["failure_count"] == 1


class TestCloseAllBoolFallback:
    """close_plan_fn returns a plain bool (backward compat)."""

    @patch("aipass.flow.apps.handlers.plan.close_ops._spawn_background_runner")
    @patch("aipass.flow.apps.handlers.plan.close_ops.json_handler")
    def test_bool_return_handled(self, _mock_jh, mock_bg):
        close_all = _import_close_all_plans_impl()
        open_plans = [
            ("1", {"subject": "Plan A", "location": "/a", "file_path": "/a/FPLAN-0001_a.md"}),
        ]
        mock_get = MagicMock(return_value=open_plans)
        mock_close = MagicMock(return_value=True)  # bool, not dict

        result = close_all(get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is True
        assert result["success_count"] == 1


class TestCloseAllException:
    """get_open_plans raises an exception."""

    def test_exception_returns_error(self):
        close_all = _import_close_all_plans_impl()
        mock_get = MagicMock(side_effect=RuntimeError("db connection failed"))
        mock_close = MagicMock()

        result = close_all(get_open_plans=mock_get, close_plan_fn=mock_close)
        assert result["success"] is False
        assert result["total"] == 0
        assert any("Error" in m.get("text", "") for m in result["messages"])


# ═══════════════════════════════════════════════════════════
# 4. _find_unregistered_plan_file
# ═══════════════════════════════════════════════════════════


class TestFindUnregisteredPlanFile:
    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_finds_matching_file(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        branch_dir = tmp_path / "somebranch"
        branch_dir.mkdir()
        plan_file = branch_dir / "DPLAN-0176_design_topic_2026-05-10.md"
        plan_file.write_text("# Plan", encoding="utf-8")

        result = find_fn("DPLAN", "0176")
        assert result is not None
        assert result.name == "DPLAN-0176_design_topic_2026-05-10.md"

    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_skips_backup_directory(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        backup_dir = tmp_path / ".backup" / "processed_plans"
        backup_dir.mkdir(parents=True)
        (backup_dir / "FPLAN-0099_old_2026-01-01.md").write_text("# Old", encoding="utf-8")

        result = find_fn("FPLAN", "0099")
        assert result is None

    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_skips_archive_directory(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        archive_dir = tmp_path / "branch" / ".archive"
        archive_dir.mkdir(parents=True)
        (archive_dir / "FPLAN-0050_archived_2026-02-01.md").write_text("# Archived", encoding="utf-8")

        result = find_fn("FPLAN", "0050")
        assert result is None

    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_skips_processed_plans_directory(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        proc_dir = tmp_path / "processed_plans"
        proc_dir.mkdir()
        (proc_dir / "FPLAN-0077_done_2026-03-01.md").write_text("# Done", encoding="utf-8")

        result = find_fn("FPLAN", "0077")
        assert result is None

    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_returns_none_when_no_match(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        branch_dir = tmp_path / "branch"
        branch_dir.mkdir()
        (branch_dir / "FPLAN-0001_other_2026-01-01.md").write_text("# Other", encoding="utf-8")

        result = find_fn("FPLAN", "9999")
        assert result is None

    @patch("aipass.flow.apps.handlers.plan.close_helpers.FLOW_ROOT")
    def test_skips_git_directory(self, mock_flow_root, tmp_path):
        find_fn = _import_find_unregistered()
        mock_flow_root.parent = tmp_path
        git_dir = tmp_path / ".git" / "refs"
        git_dir.mkdir(parents=True)
        (git_dir / "FPLAN-0010_gitfile_2026-01-01.md").write_text("# Git", encoding="utf-8")

        result = find_fn("FPLAN", "0010")
        assert result is None


# ═══════════════════════════════════════════════════════════
# 5. _self_heal_unregistered_plan
# ═══════════════════════════════════════════════════════════


class TestSelfHealNoCollision:
    def test_registers_with_original_key(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "DPLAN-0176_design_topic_2026-05-10.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {"plans": {}, "next_number": 175}
        save_fn = MagicMock()
        load_fn = MagicMock()
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={"types": {}},
        ):
            actual_key, updated_reg = heal_fn(
                "DPLAN", "0176", plan_file, registry, "dplan_registry.json", save_fn, load_fn, messages
            )

        assert actual_key == "0176"
        assert "0176" in updated_reg["plans"]
        assert updated_reg["plans"]["0176"]["self_healed"] is True
        assert updated_reg["plans"]["0176"]["status"] == "open"
        assert updated_reg["next_number"] == 175
        save_fn.assert_called_once_with(registry, registry_file="dplan_registry.json")

    def test_extracts_subject_from_filename(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "FPLAN-0042_my_great_feature_2026-04-01.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {"plans": {}, "next_number": 40}
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={"types": {}},
        ):
            actual_key, updated_reg = heal_fn(
                "FPLAN", "0042", plan_file, registry, "fplan_registry.json", MagicMock(), MagicMock(), messages
            )

        assert updated_reg["plans"][actual_key]["subject"] == "my great feature"

    def test_emits_self_heal_warning_message(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "FPLAN-0001_test_2026-01-01.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {"plans": {}, "next_number": 1}
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={"types": {}},
        ):
            heal_fn("FPLAN", "0001", plan_file, registry, "fplan_registry.json", MagicMock(), MagicMock(), messages)

        assert any("self-heal" in m.get("text", "").lower() for m in messages)
        assert any("Registered" in m.get("text", "") for m in messages)


class TestSelfHealSamePrefixCollision:
    def test_bumps_to_next_number(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "FPLAN-0005_colliding_2026-03-01.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {
            "plans": {"0005": {"status": "closed", "subject": "existing"}},
            "next_number": 10,
        }
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={"types": {}},
        ):
            actual_key, updated_reg = heal_fn(
                "FPLAN", "0005", plan_file, registry, "fplan_registry.json", MagicMock(), MagicMock(), messages
            )

        assert actual_key == "0010"
        assert "0010" in updated_reg["plans"]
        assert "0005" in updated_reg["plans"]
        assert updated_reg["next_number"] == 11
        assert any("Bumping" in m.get("text", "") for m in messages)


class TestSelfHealCrossPrefixCollision:
    def test_notes_cross_prefix_collision(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "DPLAN-0013_design_2026-03-01.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {"plans": {}, "next_number": 13}
        save_fn = MagicMock()
        other_registry = {"plans": {"0013": {"status": "closed", "subject": "fplan thing"}}}
        load_fn = MagicMock(return_value=other_registry)
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={
                "types": {
                    "flow_plans": {"prefix": "FPLAN"},
                    "dev_plans": {"prefix": "DPLAN"},
                }
            },
        ):
            actual_key, updated_reg = heal_fn(
                "DPLAN", "0013", plan_file, registry, "dplan_registry.json", save_fn, load_fn, messages
            )

        assert actual_key == "0013"
        assert any("FPLAN-0013 also exists" in m.get("text", "") for m in messages)

    def test_skips_own_prefix_in_cross_check(self, tmp_path):
        heal_fn = _import_self_heal()
        plan_file = tmp_path / "FPLAN-0020_test_2026-03-01.md"
        plan_file.write_text("# Plan", encoding="utf-8")
        registry = {"plans": {}, "next_number": 20}
        load_fn = MagicMock()
        messages = []

        with patch(
            "aipass.flow.apps.handlers.plan.close_helpers._load_template_registry",
            return_value={
                "types": {
                    "flow_plans": {"prefix": "FPLAN"},
                }
            },
        ):
            heal_fn("FPLAN", "0020", plan_file, registry, "fplan_registry.json", MagicMock(), load_fn, messages)

        load_fn.assert_not_called()


# ═══════════════════════════════════════════════════════════
# 6. close_plan_impl — self-heal integration path
# ═══════════════════════════════════════════════════════════


class TestClosePlanImplSelfHeal:
    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="dplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_ops.subprocess")
    def test_triggers_self_heal_when_not_in_registry(self, mock_subprocess, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "DPLAN-0176_design_topic_2026-05-10.md"
        plan_file.write_text("# Real content\nDesign notes here.", encoding="utf-8")

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
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num="DPLAN-0176", **deps)

        mock_heal.assert_called_once()
        assert result["success"] is True

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_ops._find_unregistered_plan_file", return_value=None)
    def test_returns_not_found_when_no_file_on_disk(self, _mock_find, _mock_resolve):
        close_plan_impl = _import_close_plan_impl()
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
    @patch("aipass.flow.apps.handlers.plan.close_ops.subprocess")
    def test_verify_all_pass(self, mock_subprocess, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0042_test_2026-03-01.md"
        plan_file.write_text("# Real content here.", encoding="utf-8")
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
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            plan_file.unlink()
            result = close_plan_impl(plan_num="FPLAN-0042", **deps)

        assert result["success"] is True
        verify_msgs = [
            m
            for m in result["messages"]
            if "[VERIFY]" in m.get("text", "") or "[OK]" in m.get("text", "") or "[FAIL]" in m.get("text", "")
        ]
        assert len(verify_msgs) >= 1
        ok_msgs = [m for m in result["messages"] if "[OK]" in m.get("text", "")]
        assert len(ok_msgs) >= 2

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_ops.subprocess")
    def test_verify_fails_when_file_not_in_processed(self, mock_subprocess, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0055_missing_2026-03-01.md"
        plan_file.write_text("# Content", encoding="utf-8")
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
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num="FPLAN-0055", **deps)

        assert result["success"] is True
        fail_msgs = [m for m in result["messages"] if "[FAIL]" in m.get("text", "")]
        assert len(fail_msgs) >= 1
        assert any("NOT found in processed_plans" in m.get("text", "") for m in fail_msgs)

    @patch("aipass.flow.apps.handlers.plan.close_ops._resolve_registry_file", return_value="fplan_registry.json")
    @patch("aipass.flow.apps.handlers.plan.close_ops.subprocess")
    def test_verify_fails_when_source_still_exists(self, mock_subprocess, _mock_resolve, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0060_leftover_2026-03-01.md"
        plan_file.write_text("# Content", encoding="utf-8")
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
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num="FPLAN-0060", **deps)

        assert result["success"] is True
        fail_msgs = [m for m in result["messages"] if "[FAIL]" in m.get("text", "")]
        assert any("Source file still exists" in m.get("text", "") for m in fail_msgs)

    def test_verify_skipped_for_non_self_healed_plans(self, tmp_path):
        close_plan_impl = _import_close_plan_impl()

        plan_file = tmp_path / "FPLAN-0070_normal_2026-03-01.md"
        plan_file.write_text("# Normal plan content", encoding="utf-8")

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
            patch("aipass.flow.apps.handlers.plan.close_ops.subprocess"),
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch("aipass.flow.apps.handlers.plan.close_ops.json_handler"),
            patch("aipass.flow.apps.handlers.plan.append_closed_plan.append_to_closed_plans", create=True),
        ):
            result = close_plan_impl(plan_num="70", **deps)

        assert result["success"] is True
        verify_msgs = [m for m in result["messages"] if "[VERIFY]" in m.get("text", "")]
        assert len(verify_msgs) == 0
