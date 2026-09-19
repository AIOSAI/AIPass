# =================== AIPass ====================
# Name: test_process.py
# Description: Tests for mbank/process.py — additional coverage
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-09-18
# =============================================

"""Tests for mbank/process.py — archive_plan, is_template_content, and orchestration."""

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_PROC = "aipass.flow.apps.handlers.mbank.process"

# Captured before any test patches os.open: the stand-in below delegates here.
_REAL_OS_OPEN = os.open


def _deny_exclusive_creates(lock_path: Path, denials: int | None):
    """An os.open stand-in that answers the way Windows does mid-release.

    Windows answers an exclusive create against a lock another writer is still
    removing (delete-pending) with PermissionError, not FileExistsError; Linux
    cannot show that, so it is manufactured. The first ``denials`` exclusive
    creates of ``lock_path`` are denied (None = never clears); everything else
    reaches the real os.open.

    Returns:
        (side_effect, attempts, raised): attempts counts every exclusive create
        of lock_path; raised holds each PermissionError handed out.
    """
    attempts: list[int] = []
    raised: list[PermissionError] = []

    def fake_open(path, flags, *args, **kwargs):
        if flags & os.O_EXCL and str(path) == str(lock_path):
            attempts.append(len(attempts) + 1)
            if denials is None or len(attempts) <= denials:
                denial = PermissionError(13, "Access is denied")
                raised.append(denial)
                raise denial
        return _REAL_OS_OPEN(path, flags, *args, **kwargs)

    return fake_open, attempts, raised


# ===================================================================
# 1. is_template_content
# ===================================================================


class TestIsTemplateContent:
    """Detect untouched template content vs real user work."""

    def test_default_template_detected(self):
        """Content with 3+ default bracket placeholders is a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "# Plan\n"
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
        )
        assert is_template_content(content) is True

    def test_master_template_detected(self):
        """Content with 3+ master bracket placeholders is a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "# Master Plan\n[What this phase accomplishes]\n[What the agent will build]\n[Files/outputs expected]\n"
        )
        assert is_template_content(content) is True

    def test_proposal_template_detected(self):
        """Content with 3+ proposal bracket placeholders is a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "# Proposal\n"
            "[Clear description of the idea, feature, improvement, or fix]\n"
            "[Why is this valuable? What problem does it solve? What does it enable?]\n"
            "[How would I tackle this? High-level steps.]\n"
            "[Any other branches, services, or approvals needed?]\n"
        )
        assert is_template_content(content) is True

    def test_real_content_not_template(self):
        """Content without bracket placeholders is not a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "# Implement OAuth flow\n"
            "## Objective\n"
            "Add OAuth2 support for GitHub and Google providers.\n"
            "## Approach\n"
            "Use the authorization code grant flow.\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_execution_log_overrides(self):
        """Checked execution log items signal real work, even with placeholders."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Agent deployed\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_agent_completed_overrides(self):
        """Checked 'Agent completed' item signals real work."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Agent completed\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_seedgo_overrides(self):
        """Checked 'Seedgo checklist' item signals real work."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Seedgo checklist\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_all_goals_overrides(self):
        """Checked 'All goals achieved' item signals real work."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] All goals achieved\n"
        )
        assert is_template_content(content) is False

    def test_notes_section_with_real_content_overrides(self):
        """Real content in Notes section means the plan has been worked on."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "## Notes\n"
            "Discovered that the API rate limit is 100 req/min.\n"
        )
        assert is_template_content(content) is False

    def test_notes_section_with_only_placeholder_still_template(self):
        """Notes section containing only the template placeholder does not override."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "## Notes\n"
            "[Working notes, issues encountered, decisions made]\n"
        )
        assert is_template_content(content) is True

    def test_execution_log_with_many_lines_overrides(self):
        """More than 8 lines in Execution Log section signals real work."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        exec_lines = "\n".join(f"- Step {i}: did something" for i in range(10))
        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "## Execution Log\n"
            f"{exec_lines}\n"
        )
        assert is_template_content(content) is False

    def test_two_placeholders_not_enough(self):
        """Fewer than 3 bracket placeholders is not a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "Real objective: build the thing.\n"
        )
        assert is_template_content(content) is False

    def test_empty_content_not_template(self):
        """Empty content is not a template."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        assert is_template_content("") is False

    def test_mixed_placeholder_types_below_threshold(self):
        """Placeholders from different template types don't combine to reach threshold."""
        from aipass.flow.apps.handlers.mbank.process import is_template_content

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[What this phase accomplishes]\n"
            "[Clear description of the idea, feature, improvement, or fix]\n"
        )
        # Each type has only 1 placeholder, so none reach 3
        assert is_template_content(content) is False


# ===================================================================
# 2. archive_plan
# ===================================================================


class TestArchivePlan:
    """Move plan file to processed_plans directory."""

    def test_successful_archive(self, tmp_path):
        """Archive moves file and returns True."""
        plan_file = tmp_path / "FPLAN-0100.md"
        plan_file.write_text("plan content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
            from aipass.flow.apps.handlers.mbank.process import archive_plan

            result = archive_plan(plan_file)

        assert result is True
        assert not plan_file.exists()
        assert (processed_dir / "FPLAN-0100.md").exists()

    def test_archive_handles_duplicate_name(self, tmp_path):
        """When destination already exists, append timestamp to avoid collision."""
        plan_file = tmp_path / "FPLAN-0200.md"
        plan_file.write_text("new content", encoding="utf-8")
        processed_dir = tmp_path / "processed"
        processed_dir.mkdir()
        (processed_dir / "FPLAN-0200.md").write_text("already there", encoding="utf-8")

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
            from aipass.flow.apps.handlers.mbank.process import archive_plan

            result = archive_plan(plan_file)

        assert result is True
        assert not plan_file.exists()
        # Original collision file still present, plus the timestamped one
        md_files = list(processed_dir.glob("FPLAN-0200*.md"))
        assert len(md_files) == 2

    def test_archive_creates_destination_dir(self, tmp_path):
        """PROCESSED_PLANS_DIR is created if it does not exist."""
        plan_file = tmp_path / "FPLAN-0300.md"
        plan_file.write_text("content", encoding="utf-8")
        processed_dir = tmp_path / "deep" / "nested" / "processed"

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
            from aipass.flow.apps.handlers.mbank.process import archive_plan

            result = archive_plan(plan_file)

        assert result is True
        assert processed_dir.exists()
        assert (processed_dir / "FPLAN-0300.md").exists()

    def test_archive_returns_false_on_move_failure(self, tmp_path):
        """Return False when shutil.move raises an exception."""
        plan_file = tmp_path / "FPLAN-0400.md"
        plan_file.write_text("content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        with (
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch("aipass.flow.apps.handlers.mbank.process.shutil.move", side_effect=OSError("disk full")),
        ):
            from aipass.flow.apps.handlers.mbank.process import archive_plan

            result = archive_plan(plan_file)

        assert result is False

    def test_archive_returns_false_when_dest_not_verified(self, tmp_path):
        """Return False when destination file does not exist after move."""
        plan_file = tmp_path / "FPLAN-0500.md"
        plan_file.write_text("content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        def fake_move(src: str, _: str) -> None:
            """Simulate a move that deletes source but never creates destination."""
            import os

            os.remove(src)

        with (
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch("aipass.flow.apps.handlers.mbank.process.shutil.move", side_effect=fake_move),
        ):
            from aipass.flow.apps.handlers.mbank.process import archive_plan

            result = archive_plan(plan_file)

        assert result is False


# ===================================================================
# 3. load_flow_registry (additional coverage)
# ===================================================================


class TestLoadFlowRegistryAdditional:
    """Additional edge cases for load_flow_registry."""

    def test_loads_with_explicit_registry_file_arg(self, tmp_path):
        """Loading with an explicit registry_file name uses FLOW_JSON_DIR / name."""
        data = {"plans": {"1": {"status": "open"}}, "next_number": 2}
        (tmp_path / "custom_reg.json").write_text(json.dumps(data), encoding="utf-8")

        with patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path):
            from aipass.flow.apps.handlers.mbank.process import load_flow_registry

            result = load_flow_registry(registry_file="custom_reg.json")

        assert result["next_number"] == 2


# ===================================================================
# 4. save_flow_registry (additional coverage)
# ===================================================================


class TestSaveFlowRegistryAdditional:
    """Additional edge cases for save_flow_registry."""

    def test_preserves_existing_data(self, tmp_path):
        """All existing registry keys are preserved after save."""
        data = {"next_number": 10, "plans": {"1": {"subject": "keep me", "status": "open"}}}
        reg_file = tmp_path / "fplan_registry.json"

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
        ):
            from aipass.flow.apps.handlers.mbank.process import save_flow_registry

            save_flow_registry(data)

        saved = json.loads(reg_file.read_text(encoding="utf-8"))
        assert saved["plans"]["1"]["subject"] == "keep me"
        assert saved["next_number"] == 10

    def test_delete_pending_denial_is_retried_and_processed_flag_lands(self, tmp_path):
        """A Windows delete-pending denial on the registry lock is a held lock:
        retried on the same budget, and the "processed" update reaches disk.

        It used to give up on the first denial, so the plan was archived but
        the registry never learned it was processed.
        """
        from aipass.flow.apps.handlers.mbank.process import save_flow_registry

        reg_file = tmp_path / "fplan_registry.json"
        lock = reg_file.with_suffix(".lock")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=1)
        data = {"next_number": 2, "plans": {"1": {"status": "closed", "processed": True}}}

        with (
            patch(f"{_PROC}.FLOW_JSON_DIR", tmp_path),
            patch(f"{_PROC}.os.open", side_effect=fake_open),
            patch(f"{_PROC}.time.sleep"),
        ):
            save_flow_registry(data, registry_file=reg_file.name)

        assert len(attempts) == 2
        saved = json.loads(reg_file.read_text(encoding="utf-8"))
        assert saved["plans"]["1"]["processed"] is True
        assert not lock.exists()

    def test_denial_that_never_clears_fails_at_the_budget_with_the_denial(self, tmp_path):
        """A denial past the budget raises out of save_flow_registry with the
        denial in the message after exactly the budget; the helper's own raise
        is a PermissionError chained to the last denial.
        """
        import aipass.flow.apps.handlers.mbank.process as proc

        reg_file = tmp_path / "fplan_registry.json"
        before = {"next_number": 2, "plans": {"1": {"status": "closed"}}}
        reg_file.write_text(json.dumps(before), encoding="utf-8")
        lock = reg_file.with_suffix(".lock")
        fake_open, attempts, _raised = _deny_exclusive_creates(lock, denials=None)

        with (
            patch(f"{_PROC}.FLOW_JSON_DIR", tmp_path),
            patch(f"{_PROC}.os.open", side_effect=fake_open),
            patch(f"{_PROC}.time.sleep"),
            pytest.raises(Exception) as excinfo,
        ):
            proc.save_flow_registry({"next_number": 2, "plans": {}}, registry_file=reg_file.name)

        assert len(attempts) == proc._LOCK_RETRIES
        assert str(lock) in str(excinfo.value)
        assert f"{proc._LOCK_RETRIES} attempts" in str(excinfo.value)
        assert json.loads(reg_file.read_text(encoding="utf-8")) == before

        fake_open, attempts, raised = _deny_exclusive_creates(lock, denials=None)
        with (
            patch(f"{_PROC}.os.open", side_effect=fake_open),
            patch(f"{_PROC}.time.sleep"),
            pytest.raises(PermissionError) as helper_exc,
        ):
            proc._acquire_lock(lock)

        assert helper_exc.value.__cause__ is raised[-1]
        assert len(attempts) == proc._LOCK_RETRIES


# ===================================================================
# 5. get_closed_plans (additional coverage)
# ===================================================================


class TestGetClosedPlansAdditional:
    """Additional edge cases for get_closed_plans."""

    def test_handles_registry_load_failure_gracefully(self):
        """When a registry fails to load, skip it and continue."""
        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["bad_registry.json", "good_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []},
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_flow_registry",
                side_effect=[Exception("corrupt"), {"plans": {}}],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            result = get_closed_plans()

        # Should not raise, returns empty because the good registry has no closed plans
        assert result == []

    def test_includes_registry_file_in_result(self, tmp_path):
        """Each result entry includes the registry_file it came from."""
        plan_file = tmp_path / "FPLAN-0077.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "77": {
                    "status": "closed",
                    "file_path": str(plan_file),
                },
            }
        }

        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["special_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []},
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_flow_registry",
                return_value=registry,
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            result = get_closed_plans()

        assert len(result) == 1
        assert result[0]["registry_file"] == "special_registry.json"


# ===================================================================
# 6. cleanup_temp_files (additional coverage)
# ===================================================================


class TestCleanupTempFilesAdditional:
    """Additional edge cases for cleanup_temp_files."""

    def test_scan_error_returns_error_key(self, tmp_path):
        """When scanning the directory raises, return scan_error key."""
        with patch("aipass.flow.apps.handlers.mbank.process.MEMORY_PATH", tmp_path):
            # Make .exists() return True but .glob() raise
            with patch.object(Path, "glob", side_effect=PermissionError("no access")):
                from aipass.flow.apps.handlers.mbank.process import cleanup_temp_files

                result = cleanup_temp_files()

        assert "scan_error" in result
        assert result["files_found"] == 0


# ===================================================================
# 7. verify_and_heal_orphaned_plans (additional coverage)
# ===================================================================


class TestVerifyAndHealOrphanedPlansAdditional:
    """Additional edge cases for verify_and_heal_orphaned_plans."""

    def test_handles_rename_exception(self, tmp_path):
        """When rename raises, report failed_to_heal."""
        plan_file = tmp_path / "FPLAN-0030.md"
        plan_file.write_text("orphan", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        registry = {
            "plans": {
                "30": {"status": "closed", "file_path": str(plan_file)},
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
            patch.object(Path, "rename", side_effect=OSError("cross-device")),
        ):
            from aipass.flow.apps.handlers.mbank.process import verify_and_heal_orphaned_plans

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 1
        assert result["failed_to_heal"] == 1
        assert result["orphans"][0]["status"] == "heal_failed"

    def test_skips_registries_that_fail_to_load(self):
        """When a registry fails to load during healing, skip it."""
        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["broken.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_flow_registry",
                side_effect=Exception("corrupt file"),
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import verify_and_heal_orphaned_plans

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 0
        assert result["successfully_healed"] == 0

    def test_multiple_registries_healed(self, tmp_path):
        """Orphans from multiple registries are all healed."""
        plan_a = tmp_path / "FPLAN-0040.md"
        plan_a.write_text("orphan a", encoding="utf-8")
        plan_b = tmp_path / "DPLAN-0050.md"
        plan_b.write_text("orphan b", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        reg_a = {
            "plans": {"40": {"status": "closed", "file_path": str(plan_a)}},
        }
        reg_b = {
            "plans": {"50": {"status": "closed", "file_path": str(plan_b)}},
        }

        reg_file_a = tmp_path / "fplan_registry.json"
        reg_file_a.write_text(json.dumps(reg_a), encoding="utf-8")
        reg_file_b = tmp_path / "dplan_registry.json"
        reg_file_b.write_text(json.dumps(reg_b), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json", "dplan_registry.json"],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import verify_and_heal_orphaned_plans

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 2
        assert result["successfully_healed"] == 2
        assert not plan_a.exists()
        assert not plan_b.exists()


# ===================================================================
# 8. process_closed_plans (additional coverage)
# ===================================================================


class TestProcessClosedPlansAdditional:
    """Additional edge cases for process_closed_plans."""

    def test_per_plan_exception_counted_as_error(self, tmp_path):
        """When processing a single plan raises, it is counted as an error."""
        plan_file = tmp_path / "FPLAN-0060.md"
        plan_file.write_text("content", encoding="utf-8")

        closed_plans = [
            {
                "number": "60",
                "path": plan_file,
                "info": {"status": "closed"},
                "registry_file": "fplan_registry.json",
            }
        ]

        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process.get_closed_plans",
                return_value=closed_plans,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.archive_plan",
                side_effect=RuntimeError("boom"),
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": []},
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE",
                tmp_path / "fplan_registry.json",
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is True
        assert result["errors"] == 1
        assert result["results"][0]["status"] == "error"

    def test_registry_updated_even_on_archive_failure(self, tmp_path):
        """Registry is updated with cleanup_completed=False when archive fails."""
        plan_file = tmp_path / "FPLAN-0070.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "70": {"status": "closed", "file_path": str(plan_file)},
            },
            "last_updated": "2026-01-01",
        }

        closed_plans = [
            {
                "number": "70",
                "path": plan_file,
                "info": registry["plans"]["70"],
                "registry_file": "fplan_registry.json",
            }
        ]

        mock_save = MagicMock()

        with (
            patch("aipass.flow.apps.handlers.mbank.process.get_closed_plans", return_value=closed_plans),
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=False),
            patch("aipass.flow.apps.handlers.mbank.process.load_flow_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_flow_registry", mock_save),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": []},
            ),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            process_closed_plans()

        # Registry save was called with cleanup_completed=False
        mock_save.assert_called_once()
        assert registry["plans"]["70"]["cleanup_completed"] is False
        # processed should NOT be set when archive fails
        assert "processed" not in registry["plans"]["70"]

    def test_logs_json_operation_after_processing(self, tmp_path, mock_json_handler):
        """json_handler.log_operation is called after processing plans."""
        plan_file = tmp_path / "FPLAN-0080.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "80": {"status": "closed", "file_path": str(plan_file)},
            },
            "last_updated": "2026-01-01",
        }

        closed_plans = [
            {
                "number": "80",
                "path": plan_file,
                "info": registry["plans"]["80"],
                "registry_file": "fplan_registry.json",
            }
        ]

        with (
            patch("aipass.flow.apps.handlers.mbank.process.get_closed_plans", return_value=closed_plans),
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", return_value=True),
            patch("aipass.flow.apps.handlers.mbank.process.load_flow_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_flow_registry"),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": []},
            ),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            process_closed_plans()

        mock_json_handler.assert_called_once_with(
            "closed_plans_processed",
            {
                "processed": 1,
                "errors": 0,
                "cleanup_deleted": 0,
                "success": True,
            },
        )

    def test_multiple_plans_mixed_results(self, tmp_path):
        """Process two plans: one succeeds, one fails."""
        plan_ok = tmp_path / "FPLAN-0090.md"
        plan_ok.write_text("ok", encoding="utf-8")
        plan_bad = tmp_path / "FPLAN-0091.md"
        plan_bad.write_text("bad", encoding="utf-8")

        registry = {
            "plans": {
                "90": {"status": "closed", "file_path": str(plan_ok)},
                "91": {"status": "closed", "file_path": str(plan_bad)},
            },
            "last_updated": "2026-01-01",
        }

        closed_plans = [
            {
                "number": "90",
                "path": plan_ok,
                "info": registry["plans"]["90"],
                "registry_file": "fplan_registry.json",
            },
            {
                "number": "91",
                "path": plan_bad,
                "info": registry["plans"]["91"],
                "registry_file": "fplan_registry.json",
            },
        ]

        archive_results = [True, False]

        with (
            patch("aipass.flow.apps.handlers.mbank.process.get_closed_plans", return_value=closed_plans),
            patch("aipass.flow.apps.handlers.mbank.process.archive_plan", side_effect=archive_results),
            patch("aipass.flow.apps.handlers.mbank.process.load_flow_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_flow_registry"),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={"files_found": 0, "files_deleted": 0, "failed_deletes": 0, "details": []},
            ),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 1
        assert result["errors"] == 1
        statuses = [r["status"] for r in result["results"]]
        assert "archived" in statuses
        assert "archive_failed" in statuses
