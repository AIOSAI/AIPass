# =================== AIPass ====================
# Name: test_process.py
# Description: Tests for mbank/process.py — additional coverage
# Version: 1.1.0
# Created: 2026-05-12
# Modified: 2026-10-23
# =============================================

"""Tests for mbank/process.py — archive_plan, is_template_content, and orchestration."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that mbank/process.py parses and imports

import json
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch


from aipass.flow.apps.handlers.mbank.process import (
    archive_plan,
    get_closed_plans,
    is_template_content,
    process_closed_plans,
    verify_and_heal_orphaned_plans,
)

_PROC = "aipass.flow.apps.handlers.mbank.process"


def _move_answer(source: Path, destination: Path) -> OSError | None:
    """Move ``source`` with the test's own hands and keep what the platform answers."""
    try:
        shutil.move(str(source), str(destination))
    except OSError as exc:
        return exc
    return None


def _mkdir_answer(path: Path) -> OSError | None:
    """Make ``path`` a directory the way the heal does and keep the platform's answer."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return exc
    return None


class TestIsTemplateContent:
    """Detect untouched template content vs real user work."""

    def test_default_template_detected(self):
        """Content with 3+ default bracket placeholders is a template."""

        content = (
            "# Plan\n"
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
        )
        assert is_template_content(content) is True

    def test_master_template_detected(self):
        """Content with 3+ master bracket placeholders is a template."""

        content = (
            "# Master Plan\n[What this phase accomplishes]\n[What the agent will build]\n[Files/outputs expected]\n"
        )
        assert is_template_content(content) is True

    def test_proposal_template_detected(self):
        """Content with 3+ proposal bracket placeholders is a template."""

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

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Agent deployed\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_agent_completed_overrides(self):
        """Checked 'Agent completed' item signals real work."""

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Agent completed\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_seedgo_overrides(self):
        """Checked 'Seedgo checklist' item signals real work."""

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] Seedgo checklist\n"
        )
        assert is_template_content(content) is False

    def test_user_checked_all_goals_overrides(self):
        """Checked 'All goals achieved' item signals real work."""

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "[List any planning docs, specs, or examples to reference]\n"
            "- [x] All goals achieved\n"
        )
        assert is_template_content(content) is False

    def test_notes_section_with_real_content_overrides(self):
        """Real content in Notes section means the plan has been worked on."""

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

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[How will agents tackle this? What instructions will they need?]\n"
            "Real objective: build the thing.\n"
        )
        assert is_template_content(content) is False

    def test_empty_content_not_template(self):
        """Empty content is not a template."""

        assert is_template_content("") is False

    def test_mixed_placeholder_types_below_threshold(self):
        """Placeholders from different template types don't combine to reach threshold."""

        content = (
            "[What do you want to achieve? Specific end state.]\n"
            "[What this phase accomplishes]\n"
            "[Clear description of the idea, feature, improvement, or fix]\n"
        )
        assert is_template_content(content) is False


class TestArchivePlan:
    """Move plan file to processed_plans directory."""

    def test_successful_archive(self, tmp_path):
        """Archive moves file and returns True."""
        plan_file = tmp_path / "FPLAN-0100.md"
        plan_file.write_text("plan content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
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
            result = archive_plan(plan_file)

        assert result is True
        assert not plan_file.exists()
        md_files = list(processed_dir.glob("FPLAN-0200*.md"))
        assert len(md_files) == 2

    def test_archive_creates_destination_dir(self, tmp_path):
        """PROCESSED_PLANS_DIR is created if it does not exist."""
        plan_file = tmp_path / "FPLAN-0300.md"
        plan_file.write_text("content", encoding="utf-8")
        processed_dir = tmp_path / "deep" / "nested" / "processed"

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
            result = archive_plan(plan_file)

        assert result is True
        assert processed_dir.exists()
        assert (processed_dir / "FPLAN-0300.md").exists()

    def test_archive_returns_false_on_move_failure(self, tmp_path, mock_logger):
        """Return False when the move itself raises.

        Mutant: the except's `return False` -> `return True` reddens this.
        """
        plan_file = tmp_path / "FPLAN-0400.md"
        processed_dir = tmp_path / "processed"
        answer = _move_answer(tmp_path / "twin-FPLAN-0400.md", tmp_path / "twin-dest.md")
        assert isinstance(answer, OSError), "premise: this platform moved a file that does not exist"

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir):
            result = archive_plan(plan_file)

        assert result is False
        assert list(processed_dir.iterdir()) == []
        assert mock_logger.error.call_args.args[1] == plan_file

    def test_archive_returns_false_when_dest_not_verified(self, tmp_path):
        """Return False when destination file does not exist after move."""
        plan_file = tmp_path / "FPLAN-0500.md"
        plan_file.write_text("content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        class _Unverified:
            """A destination the move reaches but the check cannot see."""

            def __init__(self, real: Path) -> None:
                self.real = real

            def __str__(self) -> str:
                return str(self.real)

            def exists(self) -> bool:
                return False

        unverifiable_dir = MagicMock()
        unverifiable_dir.mkdir.side_effect = lambda **kw: processed_dir.mkdir(**kw)
        unverifiable_dir.__truediv__.side_effect = lambda name: _Unverified(processed_dir / name)

        with patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", unverifiable_dir):
            result = archive_plan(plan_file)

        assert result is False
        assert (processed_dir / "FPLAN-0500.md").read_text(encoding="utf-8") == "content"
        assert not plan_file.exists()


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
                "aipass.flow.apps.handlers.mbank.process.load_registry",
                side_effect=[Exception("corrupt"), {"plans": {}}],
            ),
        ):
            result = get_closed_plans()

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
                "aipass.flow.apps.handlers.mbank.process.load_registry",
                return_value=registry,
            ),
        ):
            result = get_closed_plans()

        assert len(result) == 1
        assert result[0]["registry_file"] == "special_registry.json"


class TestVerifyAndHealOrphanedPlansAdditional:
    """Additional edge cases for verify_and_heal_orphaned_plans."""

    def test_handles_rename_exception(self, tmp_path):
        """When the heal's move raises, report failed_to_heal.

        A file stands where the processed directory goes, so the heal's mkdir fails on disk.
        """
        plan_file = tmp_path / "FPLAN-0030.md"
        plan_file.write_text("orphan", encoding="utf-8")
        processed_dir = tmp_path / "processed"
        processed_dir.write_text("a file where the directory goes", encoding="utf-8")
        twin = tmp_path / "twin-processed"
        twin.write_text("", encoding="utf-8")
        answer = _mkdir_answer(twin)
        assert isinstance(answer, OSError), "premise: this platform made a directory over a file"

        registry = {
            "plans": {
                "30": {"status": "closed", "file_path": str(plan_file)},
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
        ):
            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 1
        assert result["failed_to_heal"] == 1
        assert result["orphans"][0]["status"] == "heal_failed"
        assert plan_file.read_text(encoding="utf-8") == "orphan"

    def test_skips_registries_that_fail_to_load(self):
        """When a registry fails to load during healing, skip it."""
        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["broken.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_registry",
                side_effect=Exception("corrupt file"),
            ),
        ):
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR", processed_dir),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json", "dplan_registry.json"],
            ),
        ):
            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 2
        assert result["successfully_healed"] == 2
        assert not plan_a.exists()
        assert not plan_b.exists()


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
                "aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE",
                tmp_path / "fplan_registry.json",
            ),
        ):
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
            patch("aipass.flow.apps.handlers.mbank.process.load_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_registry", mock_save),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            process_closed_plans()

        mock_save.assert_called_once()
        assert registry["plans"]["70"]["cleanup_completed"] is False
        assert "processed" not in registry["plans"]["70"]

    def test_logs_json_operation_after_processing(self, tmp_path, mock_json_handler):
        """json_handler.log_operation is called after processing plans.

        Mutant: save_flow_registry(registry, registry_file=reg_file) -> save_flow_registry(registry) reddens this.
        """
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
            patch("aipass.flow.apps.handlers.mbank.process.load_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_registry") as mock_save,
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            process_closed_plans()

        mock_save.assert_called_once_with(registry, registry_file="fplan_registry.json")
        assert registry["plans"]["80"]["processed"] is True
        processed = [c for c in mock_json_handler.call_args_list if c.args[0] == "closed_plans_processed"]
        assert [c.args[1] for c in processed] == [{"processed": 1, "errors": 0, "success": True}]

    def test_multiple_plans_mixed_results(self, tmp_path):
        """Process two plans: one succeeds, one fails.

        Mutant: `if archive_success:` (processed flag) -> `if True:` reddens this.
        """
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
            patch("aipass.flow.apps.handlers.mbank.process.load_registry", return_value=registry),
            patch("aipass.flow.apps.handlers.mbank.process.save_registry") as mock_save,
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", tmp_path / "fplan_registry.json"),
        ):
            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 1
        assert result["errors"] == 1
        statuses = [r["status"] for r in result["results"]]
        assert "archived" in statuses
        assert "archive_failed" in statuses
        # Both rows are written back (the failure records cleanup_completed=False); only the success is processed.
        assert mock_save.call_count == 2
        assert registry["plans"]["90"].get("processed") is True
        assert "processed" not in registry["plans"]["91"]
