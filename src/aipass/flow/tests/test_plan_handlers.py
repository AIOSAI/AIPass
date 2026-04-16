"""Tests for plan handler functions in aipass.flow.apps.handlers.plan.*

Covers: slugify_subject, create_plan_impl, create_plan_file,
        build_plan_registry_entry, calculate_relative_location,
        resolve_plan_location, auto_close_orphaned_plans, get_closed_plans,
        update_data_metrics (json_handler).
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Module imports
# ---------------------------------------------------------------------------
from aipass.flow.apps.handlers.plan.create_ops import slugify_subject, create_plan_impl
from aipass.flow.apps.handlers.plan.create_file import create_plan_file
from aipass.flow.apps.handlers.plan.build_registry_entry import build_plan_registry_entry
from aipass.flow.apps.handlers.plan.calculate_relative_path import calculate_relative_location
from aipass.flow.apps.handlers.plan.resolve_location import resolve_plan_location
from aipass.flow.apps.handlers.plan.auto_cleanup import auto_close_orphaned_plans
from aipass.flow.apps.handlers.plan.get_closed_plans import get_closed_plans
from aipass.flow.apps.handlers.json.json_handler import update_data_metrics


# =========================================================================
# slugify_subject
# =========================================================================


class TestSlugifySubject:
    """Tests for slugify_subject()."""

    def test_basic_lowercase_and_underscores(self):
        result = slugify_subject("Hello World")
        assert result == "hello_world"

    def test_strips_special_characters(self):
        result = slugify_subject("Fix: bugs & issues!")
        assert result == "fix_bugs_issues"

    def test_collapses_multiple_spaces_and_dashes(self):
        result = slugify_subject("too   many---dashes")
        assert result == "too_many_dashes"

    def test_respects_max_length_default(self):
        long_subject = "a" * 60
        result = slugify_subject(long_subject)
        assert len(result) <= 40

    def test_respects_custom_max_length(self):
        result = slugify_subject("a" * 60, max_length=10)
        assert len(result) == 10

    def test_strips_leading_trailing_underscores(self):
        result = slugify_subject("  -hello-  ")
        assert result == "hello"

    def test_empty_string(self):
        result = slugify_subject("")
        assert result == ""

    def test_only_special_characters(self):
        result = slugify_subject("!@#$%^&*()")
        assert result == ""

    def test_preserves_digits(self):
        result = slugify_subject("Plan 42 rollout")
        assert result == "plan_42_rollout"


# =========================================================================
# create_plan_file
# =========================================================================


class TestCreatePlanFile:
    """Tests for create_plan_file()."""

    def test_creates_file_successfully(self, tmp_path: Path):
        plan_file = tmp_path / "FPLAN-0001_test_2026-01-01.md"
        content = "# FPLAN-0001\n\nTest content"
        success, error = create_plan_file(plan_file, content)

        assert success is True
        assert error == ""
        assert plan_file.exists()
        assert plan_file.read_text(encoding="utf-8") == content

    def test_fails_when_file_already_exists(self, tmp_path: Path):
        plan_file = tmp_path / "FPLAN-0001_test.md"
        plan_file.write_text("existing", encoding="utf-8")

        success, error = create_plan_file(plan_file, "new content")

        assert success is False
        assert "already exists" in error
        assert plan_file.read_text(encoding="utf-8") == "existing"

    def test_fails_on_unwritable_directory(self, tmp_path: Path):
        bad_path = tmp_path / "nonexistent_dir" / "FPLAN-0001.md"
        success, error = create_plan_file(bad_path, "content")

        assert success is False
        assert "Failed to create" in error

    def test_error_message_includes_parent_name(self, tmp_path: Path):
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("x", encoding="utf-8")

        _, error = create_plan_file(plan_file, "y")
        assert tmp_path.name in error


# =========================================================================
# build_plan_registry_entry
# =========================================================================


class TestBuildPlanRegistryEntry:
    """Tests for build_plan_registry_entry()."""

    def test_returns_correct_structure(self, tmp_path: Path):
        plan_file = tmp_path / "FPLAN-0005.md"
        entry = build_plan_registry_entry(
            plan_num=5,
            target_dir=tmp_path,
            relative_location="flow",
            subject="Deploy widget",
            plan_file=plan_file,
            template_type="default",
        )

        assert entry["location"] == str(tmp_path)
        assert entry["relative_path"] == "flow"
        assert entry["subject"] == "Deploy widget"
        assert entry["status"] == "open"
        assert entry["file_path"] == str(plan_file)
        assert entry["template_type"] == "default"

    def test_created_timestamp_is_iso_utc(self, tmp_path: Path):
        before = datetime.now(timezone.utc)
        entry = build_plan_registry_entry(
            plan_num=1,
            target_dir=tmp_path,
            relative_location="root",
            subject="test",
            plan_file=tmp_path / "FPLAN-0001.md",
            template_type="default",
        )
        after = datetime.now(timezone.utc)

        created = datetime.fromisoformat(entry["created"])
        assert before <= created <= after

    def test_all_required_keys_present(self, tmp_path: Path):
        entry = build_plan_registry_entry(
            plan_num=1,
            target_dir=tmp_path,
            relative_location="root",
            subject="anything",
            plan_file=tmp_path / "p.md",
            template_type="master",
        )
        required_keys = {"location", "relative_path", "created", "subject", "status", "file_path", "template_type"}
        assert required_keys == set(entry.keys())


# =========================================================================
# calculate_relative_location
# =========================================================================


class TestCalculateRelativeLocation:
    """Tests for calculate_relative_location()."""

    def test_subdirectory_returns_relative(self, tmp_path: Path):
        root = tmp_path / "repo"
        target = root / "src" / "flow"
        root.mkdir()
        target.mkdir(parents=True)

        result = calculate_relative_location(target, root)
        assert result == "src/flow"

    def test_same_directory_returns_root(self, tmp_path: Path):
        result = calculate_relative_location(tmp_path, tmp_path)
        assert result == "root"

    def test_outside_ecosystem_returns_absolute(self, tmp_path: Path):
        root = tmp_path / "repo"
        outside = tmp_path / "other"
        root.mkdir()
        outside.mkdir()

        result = calculate_relative_location(outside, root)
        assert result == str(outside)

    def test_deeply_nested_path(self, tmp_path: Path):
        root = tmp_path
        target = tmp_path / "a" / "b" / "c" / "d"
        target.mkdir(parents=True)

        result = calculate_relative_location(target, root)
        assert result == "a/b/c/d"


# =========================================================================
# resolve_plan_location
# =========================================================================


class TestResolvePlanLocation:
    """Tests for resolve_plan_location()."""

    def test_none_location_uses_caller_cwd(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.plan.resolve_location._get_caller_cwd",
            return_value=tmp_path,
        ):
            success, resolved, error = resolve_plan_location(None, tmp_path)

        assert success is True
        assert resolved == tmp_path
        assert error == ""

    def test_absolute_path_resolves_directly(self, tmp_path: Path):
        target = tmp_path / "plans"
        target.mkdir()

        with patch(
            "aipass.flow.apps.handlers.plan.resolve_location._get_caller_cwd",
            return_value=tmp_path,
        ):
            success, resolved, error = resolve_plan_location(str(target), tmp_path)

        assert success is True
        assert resolved == target.resolve()
        assert error == ""

    def test_relative_path_resolves_against_caller_cwd(self, tmp_path: Path):
        subdir = tmp_path / "subdir"
        subdir.mkdir()

        with patch(
            "aipass.flow.apps.handlers.plan.resolve_location._get_caller_cwd",
            return_value=tmp_path,
        ):
            success, resolved, error = resolve_plan_location("subdir", tmp_path)

        assert success is True
        assert resolved == subdir.resolve()

    def test_nonexistent_directory_returns_failure(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.plan.resolve_location._get_caller_cwd",
            return_value=tmp_path,
        ):
            success, _, error = resolve_plan_location("/no/such/place", tmp_path)

        assert success is False
        assert "does not exist" in error

    def test_dot_resolves_to_caller_cwd(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.plan.resolve_location._get_caller_cwd",
            return_value=tmp_path,
        ):
            success, resolved, error = resolve_plan_location(".", tmp_path)

        assert success is True
        assert resolved == tmp_path.resolve()


# =========================================================================
# auto_close_orphaned_plans
# =========================================================================


class TestAutoCloseOrphanedPlans:
    """Tests for auto_close_orphaned_plans()."""

    def test_closes_plans_with_missing_files(self, tmp_path: Path):
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "file_path": str(tmp_path / "does_not_exist.md"),
                },
            }
        }
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 1
        assert updated["plans"]["1"]["status"] == "closed"
        assert updated["plans"]["1"]["closed_reason"] == "auto_closed_missing_file"
        assert "closed" in updated["plans"]["1"]

    def test_leaves_existing_open_plans_alone(self, tmp_path: Path):
        plan_file = tmp_path / "FPLAN-0001.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "file_path": str(plan_file),
                },
            }
        }
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 0
        assert updated["plans"]["1"]["status"] == "open"

    def test_ignores_already_closed_plans(self, tmp_path: Path):
        registry = {
            "plans": {
                "1": {
                    "status": "closed",
                    "file_path": str(tmp_path / "gone.md"),
                },
            }
        }
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 0
        assert updated["plans"]["1"]["status"] == "closed"

    def test_handles_empty_registry(self):
        registry = {"plans": {}}
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 0
        assert updated["plans"] == {}

    def test_handles_missing_plans_key(self):
        registry = {}
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 0

    def test_multiple_orphaned_plans(self, tmp_path: Path):
        registry = {
            "plans": {
                "1": {"status": "open", "file_path": str(tmp_path / "a.md")},
                "2": {"status": "open", "file_path": str(tmp_path / "b.md")},
                "3": {"status": "open", "file_path": str(tmp_path / "c.md")},
            }
        }
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 3
        for num in ("1", "2", "3"):
            assert updated["plans"][num]["status"] == "closed"

    def test_mixed_existing_and_orphaned(self, tmp_path: Path):
        existing = tmp_path / "exists.md"
        existing.write_text("hi", encoding="utf-8")

        registry = {
            "plans": {
                "1": {"status": "open", "file_path": str(existing)},
                "2": {"status": "open", "file_path": str(tmp_path / "gone.md")},
                "3": {"status": "closed", "file_path": str(tmp_path / "also_gone.md")},
            }
        }
        updated, count = auto_close_orphaned_plans(registry)

        assert count == 1
        assert updated["plans"]["1"]["status"] == "open"
        assert updated["plans"]["2"]["status"] == "closed"
        assert updated["plans"]["3"]["status"] == "closed"

    def test_closed_timestamp_is_valid_iso(self, tmp_path: Path):
        registry = {
            "plans": {
                "1": {
                    "status": "open",
                    "file_path": str(tmp_path / "nope.md"),
                },
            }
        }
        before = datetime.now(timezone.utc)
        updated, _ = auto_close_orphaned_plans(registry)
        after = datetime.now(timezone.utc)

        ts = datetime.fromisoformat(updated["plans"]["1"]["closed"])
        assert before <= ts <= after


# =========================================================================
# get_closed_plans
# =========================================================================


class TestGetClosedPlans:
    """Tests for get_closed_plans()."""

    _SINGLE_REG = ["fplan_registry.json"]
    _DISCOVERY_PATH = "aipass.flow.apps.handlers.plan.get_closed_plans._get_all_registry_files"
    _LOAD_PATH = "aipass.flow.apps.handlers.plan.get_closed_plans.load_registry"

    def test_returns_only_closed_plans(self, mock_registry):
        _, registry = mock_registry
        with patch(self._DISCOVERY_PATH, return_value=self._SINGLE_REG), patch(self._LOAD_PATH, return_value=registry):
            result = get_closed_plans()

        assert len(result) == 1
        plan_num, plan_info = result[0]
        assert plan_num == "2"
        assert plan_info["status"] == "closed"

    def test_returns_empty_when_no_closed(self):
        registry = {
            "plans": {
                "1": {"status": "open", "subject": "active"},
            }
        }
        with patch(self._DISCOVERY_PATH, return_value=self._SINGLE_REG), patch(self._LOAD_PATH, return_value=registry):
            result = get_closed_plans()

        assert result == []

    def test_returns_empty_on_empty_registry(self):
        with (
            patch(self._DISCOVERY_PATH, return_value=self._SINGLE_REG),
            patch(self._LOAD_PATH, return_value={"plans": {}}),
        ):
            result = get_closed_plans()

        assert result == []

    def test_returns_multiple_closed_plans(self):
        registry = {
            "plans": {
                "1": {"status": "closed", "subject": "done A"},
                "2": {"status": "closed", "subject": "done B"},
                "3": {"status": "open", "subject": "still going"},
            }
        }
        with patch(self._DISCOVERY_PATH, return_value=self._SINGLE_REG), patch(self._LOAD_PATH, return_value=registry):
            result = get_closed_plans()

        assert len(result) == 2
        subjects = {info["subject"] for _, info in result}
        assert subjects == {"done A", "done B"}

    def test_result_tuples_contain_plan_num_and_info(self, mock_registry):
        _, registry = mock_registry
        with patch(self._DISCOVERY_PATH, return_value=self._SINGLE_REG), patch(self._LOAD_PATH, return_value=registry):
            result = get_closed_plans()

        for plan_num, plan_info in result:
            assert isinstance(plan_num, str)
            assert isinstance(plan_info, dict)
            assert "subject" in plan_info


# =========================================================================
# update_data_metrics (json_handler)
# =========================================================================


class TestUpdateDataMetrics:
    """Tests for update_data_metrics() in json_handler."""

    def test_updates_single_metric(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.json.json_handler.FLOW_JSON_DIR",
            tmp_path,
        ):
            # Seed the data file with the minimum required structure
            data_file = tmp_path / "testmod_data.json"
            data_file.write_text(
                json.dumps({"created": "2026-01-01", "last_updated": "2026-01-01"}),
                encoding="utf-8",
            )

            result = update_data_metrics("testmod", total_plans=42)

        assert result is True
        saved = json.loads(data_file.read_text(encoding="utf-8"))
        assert saved["total_plans"] == 42

    def test_updates_multiple_metrics(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.json.json_handler.FLOW_JSON_DIR",
            tmp_path,
        ):
            data_file = tmp_path / "testmod_data.json"
            data_file.write_text(
                json.dumps({"created": "2026-01-01", "last_updated": "2026-01-01"}),
                encoding="utf-8",
            )

            result = update_data_metrics("testmod", open=5, closed=3, total=8)

        assert result is True
        saved = json.loads(data_file.read_text(encoding="utf-8"))
        assert saved["open"] == 5
        assert saved["closed"] == 3
        assert saved["total"] == 8

    def test_returns_false_when_data_load_fails(self, tmp_path: Path):
        with (
            patch(
                "aipass.flow.apps.handlers.json.json_handler.FLOW_JSON_DIR",
                tmp_path / "nonexistent",
            ),
            patch(
                "aipass.flow.apps.handlers.json.json_handler.load_json",
                return_value=None,
            ),
        ):
            result = update_data_metrics("broken_mod", x=1)

        assert result is False

    def test_overwrites_existing_metric(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.json.json_handler.FLOW_JSON_DIR",
            tmp_path,
        ):
            data_file = tmp_path / "testmod_data.json"
            data_file.write_text(
                json.dumps(
                    {
                        "created": "2026-01-01",
                        "last_updated": "2026-01-01",
                        "counter": 10,
                    }
                ),
                encoding="utf-8",
            )

            update_data_metrics("testmod", counter=20)

        saved = json.loads(data_file.read_text(encoding="utf-8"))
        assert saved["counter"] == 20

    def test_updates_last_updated_field(self, tmp_path: Path):
        with patch(
            "aipass.flow.apps.handlers.json.json_handler.FLOW_JSON_DIR",
            tmp_path,
        ):
            data_file = tmp_path / "testmod_data.json"
            data_file.write_text(
                json.dumps({"created": "2026-01-01", "last_updated": "2020-01-01"}),
                encoding="utf-8",
            )

            update_data_metrics("testmod", score=99)

        saved = json.loads(data_file.read_text(encoding="utf-8"))
        assert saved["last_updated"] != "2020-01-01"


# =========================================================================
# create_plan_impl
# =========================================================================


class TestCreatePlanImpl:
    """Tests for create_plan_impl()."""

    def _make_deps(self, **overrides) -> dict:
        """Build a complete set of MagicMock dependencies for create_plan_impl."""
        registry = {"next_number": 1, "plans": {}}
        deps = {
            "load_registry": MagicMock(return_value=registry),
            "save_registry": MagicMock(return_value=True),
            "auto_close_orphaned_plans": MagicMock(return_value=(registry, 0)),
            "resolve_plan_location": MagicMock(
                return_value=(True, Path("/tmp/plans"), ""),
            ),
            "calculate_relative_location": MagicMock(return_value="plans"),
            "get_template": MagicMock(return_value="# Plan content"),
            "create_plan_file": MagicMock(return_value=(True, "")),
            "build_plan_registry_entry": MagicMock(return_value={"status": "open"}),
            "display_plan_created": MagicMock(return_value="Plan created"),
            "update_dashboard_local": MagicMock(return_value=True),
            "push_to_plans_central": MagicMock(return_value=True),
            "push_flow_to_branch_dashboard": MagicMock(return_value=True),
        }
        deps.update(overrides)
        return deps

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_successful_creation(self, mock_log, mock_jh):
        deps = self._make_deps()
        success, plan_num, loc, tmpl, err, msgs = create_plan_impl(
            location="/tmp/plans",
            subject="Widget feature",
            template_type="default",
            **deps,
        )

        assert success is True
        assert plan_num == 1
        assert loc == "plans"
        assert err == ""
        deps["create_plan_file"].assert_called_once()
        deps["save_registry"].assert_called()

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_missing_dependency_returns_failure(self, mock_log, mock_jh):
        deps = self._make_deps()
        deps["get_template"] = None  # Missing dep

        success, plan_num, loc, tmpl, err, msgs = create_plan_impl(subject="anything", **deps)

        assert success is False
        assert "Missing required dependency" in err
        assert "get_template" in err

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_location_resolution_failure(self, mock_log, mock_jh):
        deps = self._make_deps(
            resolve_plan_location=MagicMock(
                return_value=(False, Path("/tmp"), "Dir not found"),
            ),
        )

        success, _, _, _, err, _ = create_plan_impl(location="/bad/path", subject="test", **deps)

        assert success is False
        assert err == "Dir not found"

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_file_creation_failure(self, mock_log, mock_jh):
        deps = self._make_deps(
            create_plan_file=MagicMock(return_value=(False, "File exists")),
        )

        success, _, _, _, err, _ = create_plan_impl(subject="test", **deps)

        assert success is False
        assert err == "File exists"

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_auto_cleanup_runs_and_saves(self, mock_log, mock_jh):
        registry = {"next_number": 5, "plans": {}}
        cleaned_registry = {"next_number": 5, "plans": {}}
        deps = self._make_deps(
            load_registry=MagicMock(return_value=registry),
            auto_close_orphaned_plans=MagicMock(
                return_value=(cleaned_registry, 2),
            ),
        )

        success, plan_num, _, _, _, msgs = create_plan_impl(subject="test", **deps)

        assert success is True
        assert plan_num == 5
        # Auto-cleanup save + registry save after plan creation = 2 calls
        assert deps["save_registry"].call_count >= 2
        dim_msgs = [m for m in msgs if m.get("type") == "dim" and "AUTO-CLEANUP" in m.get("text", "")]
        assert len(dim_msgs) == 1
        assert "2" in dim_msgs[0]["text"]

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_plan_type_config_used(self, mock_log, mock_jh):
        """Plan type config controls prefix, digits, slug length."""
        deps = self._make_deps()
        config = {
            "prefix": "DPLAN",
            "digits": 3,
            "slug_max_length": 20,
        }

        success, plan_num, _, _, _, msgs = create_plan_impl(
            subject="Testing custom config",
            plan_type_config=config,
            **deps,
        )

        assert success is True
        # Verify the file path used DPLAN prefix with 3-digit formatting
        call_args = deps["create_plan_file"].call_args
        plan_file_path: Path = call_args[0][0]
        assert plan_file_path.name.startswith("DPLAN-001")

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_template_exception_returns_failure(self, mock_log, mock_jh):
        deps = self._make_deps(
            get_template=MagicMock(side_effect=ValueError("bad template")),
        )

        success, _, _, _, err, _ = create_plan_impl(subject="test", **deps)

        assert success is False
        assert "Failed to load template" in err

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_dashboard_failure_does_not_block_success(self, mock_log, mock_jh):
        deps = self._make_deps(
            update_dashboard_local=MagicMock(return_value=False),
            push_to_plans_central=MagicMock(return_value=False),
            push_flow_to_branch_dashboard=MagicMock(return_value=False),
        )

        success, _, _, _, err, msgs = create_plan_impl(subject="test", **deps)

        assert success is True
        assert err == ""

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_empty_subject_produces_filename_without_slug(self, mock_log, mock_jh):
        deps = self._make_deps()

        success, _, _, _, _, _ = create_plan_impl(subject="", **deps)

        assert success is True
        call_args = deps["create_plan_file"].call_args
        plan_file_path: Path = call_args[0][0]
        # With empty subject, filename should be PREFIX-NNNN_date.md (no slug segment)
        name = plan_file_path.name
        assert name.startswith("FPLAN-0001_")
        # Should not have double underscores from empty slug
        assert "__" not in name

    @patch("aipass.flow.apps.handlers.plan.create_ops.json_handler")
    @patch("aipass.flow.apps.handlers.plan.create_ops.logger")
    def test_registry_save_failure_warns_but_returns_success(self, mock_log, mock_jh):
        """Plan is created even if registry save fails (file already on disk)."""
        save_mock = MagicMock(side_effect=[True, False])  # First for auto-close, second for plan
        deps = self._make_deps(
            auto_close_orphaned_plans=MagicMock(
                return_value=({"next_number": 1, "plans": {}}, 1),
            ),
            save_registry=save_mock,
        )

        success, _, _, _, _, msgs = create_plan_impl(subject="test", **deps)

        assert success is True
        warning_msgs = [m for m in msgs if m.get("type") == "warning"]
        assert len(warning_msgs) >= 1
