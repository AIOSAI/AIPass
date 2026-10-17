# =================== AIPass ====================
# Name: test_close_ops_self_heal.py
# Description: Tests for close's self-heal of an unregistered plan, split from test_close_ops.py (oversize, leg 12)
# Version: 1.1.0
# Created: 2026-10-06
# Modified: 2026-10-17
# =============================================

"""Tests for close_plan_impl's self-heal in apps/handlers/plan/close_ops.py and close_helpers.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import json
from pathlib import Path
from unittest.mock import ANY, MagicMock, patch

from aipass.flow.apps.handlers.plan.close_ops import close_plan_impl
from aipass.flow.tests.support_close_ops import _make_deps


class TestFindUnregisteredPlanFile:
    """_find_unregistered_plan_file, reached through close.

    Every skipped copy carries a real plan header, so only the skip can keep it out.
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
        """A report named like the plan must not be registered and archived as the plan.

        Mutant: the is_plan_file gate off reddens this."""
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


class TestSelfHealNoCollision:
    """_self_heal_unregistered_plan, reached through close.

    The bump on a same-number collision is pinned in test_heal_registry TestNumberCollision.
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

        result, saved, _loads = self._close_unregistered("DPLAN-0176", plan_file, next_number=176)

        assert result["success"] is True
        registry_file, registered = saved[0]  # the self-heal's save, before the close's
        assert registry_file == "dplan_registry.json"
        assert registered["plans"]["0176"]["self_healed"] is True
        assert registered["plans"]["0176"]["status"] == "open"
        assert registered["plans"]["0176"]["file_path"] == str(plan_file)
        # The counter moves past the row it was standing on.
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
