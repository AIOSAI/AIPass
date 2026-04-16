"""Tests for mbank/process.py and template handler functions."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ===================================================================
# 1. mbank/process.py — load_flow_registry
# ===================================================================


class TestLoadFlowRegistry:
    def test_loads_valid_registry(self, tmp_path):
        """Load a valid JSON registry file and return its contents."""
        registry_data = {
            "next_number": 3,
            "plans": {"1": {"subject": "a", "status": "open"}},
            "last_updated": "2026-03-01",
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry_data), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
        ):
            from aipass.flow.apps.handlers.mbank.process import load_flow_registry

            result = load_flow_registry()

        assert result["next_number"] == 3
        assert "1" in result["plans"]
        assert result["plans"]["1"]["subject"] == "a"

    def test_loads_named_registry_file(self, tmp_path):
        """When registry_file is given, load from FLOW_JSON_DIR / registry_file."""
        data = {"plans": {}, "next_number": 1}
        (tmp_path / "dplan_registry.json").write_text(json.dumps(data), encoding="utf-8")

        with patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path):
            from aipass.flow.apps.handlers.mbank.process import load_flow_registry

            result = load_flow_registry(registry_file="dplan_registry.json")

        assert result["next_number"] == 1

    def test_raises_when_file_missing(self, tmp_path):
        """Raise Exception when registry file does not exist."""
        missing = tmp_path / "nonexistent.json"

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", missing),
        ):
            from aipass.flow.apps.handlers.mbank.process import load_flow_registry

            with pytest.raises(Exception, match="Flow registry not found"):
                load_flow_registry()

    def test_raises_on_invalid_json(self, tmp_path):
        """Raise Exception when registry contains invalid JSON."""
        bad_file = tmp_path / "fplan_registry.json"
        bad_file.write_text("{not valid json", encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", bad_file),
        ):
            from aipass.flow.apps.handlers.mbank.process import load_flow_registry

            with pytest.raises(Exception, match="Failed to load flow registry"):
                load_flow_registry()


# ===================================================================
# 2. mbank/process.py — save_flow_registry
# ===================================================================


class TestSaveFlowRegistry:
    def test_saves_registry_with_last_updated(self, tmp_path):
        """Save registry and verify last_updated is set."""
        reg_file = tmp_path / "fplan_registry.json"
        data = {"next_number": 5, "plans": {}}

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
        ):
            from aipass.flow.apps.handlers.mbank.process import save_flow_registry

            save_flow_registry(data)

        saved = json.loads(reg_file.read_text(encoding="utf-8"))
        assert saved["next_number"] == 5
        assert "last_updated" in saved
        # last_updated should be an ISO timestamp string
        assert "T" in saved["last_updated"]

    def test_saves_to_named_file(self, tmp_path):
        """When registry_file arg is given, save to that filename inside FLOW_JSON_DIR."""
        data = {"next_number": 1, "plans": {"1": {"status": "open"}}}

        with patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path):
            from aipass.flow.apps.handlers.mbank.process import save_flow_registry

            save_flow_registry(data, registry_file="dplan_registry.json")

        saved = json.loads((tmp_path / "dplan_registry.json").read_text(encoding="utf-8"))
        assert saved["plans"]["1"]["status"] == "open"

    def test_raises_on_write_failure(self, tmp_path):
        """Raise Exception when the target path is not writable."""
        bad_path = tmp_path / "no_such_dir" / "sub" / "fplan_registry.json"

        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR",
                tmp_path / "no_such_dir" / "sub",
            ),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", bad_path),
        ):
            from aipass.flow.apps.handlers.mbank.process import save_flow_registry

            with pytest.raises(Exception, match="Failed to save flow registry"):
                save_flow_registry({"plans": {}})


# ===================================================================
# 3. mbank/process.py — get_closed_plans
# ===================================================================


class TestGetClosedPlans:
    def test_returns_closed_unprocessed_plans(self, tmp_path):
        """Return only closed, unprocessed plans whose files exist."""
        plan_file = tmp_path / "FPLAN-0002.md"
        plan_file.write_text("closed plan content", encoding="utf-8")

        registry = {
            "plans": {
                "1": {"status": "open", "file_path": str(tmp_path / "FPLAN-0001.md")},
                "2": {
                    "status": "closed",
                    "file_path": str(plan_file),
                },
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []},
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            result = get_closed_plans()

        assert len(result) == 1
        assert result[0]["number"] == "2"
        assert result[0]["path"] == plan_file

    def test_skips_already_processed(self, tmp_path):
        """Plans with processed=True are excluded."""
        plan_file = tmp_path / "FPLAN-0005.md"
        plan_file.write_text("done", encoding="utf-8")

        registry = {
            "plans": {
                "5": {
                    "status": "closed",
                    "processed": True,
                    "file_path": str(plan_file),
                },
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []},
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            result = get_closed_plans()

        assert len(result) == 0

    def test_skips_missing_files(self, tmp_path):
        """Closed plans whose file does not exist on disk are excluded."""
        registry = {
            "plans": {
                "9": {
                    "status": "closed",
                    "file_path": str(tmp_path / "FPLAN-0009-ghost.md"),
                },
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []},
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            result = get_closed_plans()

        assert len(result) == 0

    def test_calls_verify_and_heal(self, tmp_path):
        """get_closed_plans calls verify_and_heal_orphaned_plans internally."""
        registry = {"plans": {}}
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        mock_heal = MagicMock(
            return_value={"orphans_found": 0, "successfully_healed": 0, "failed_to_heal": 0, "orphans": []}
        )

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.verify_and_heal_orphaned_plans",
                mock_heal,
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import get_closed_plans

            get_closed_plans()

        mock_heal.assert_called_once()


# ===================================================================
# 4. mbank/process.py — cleanup_temp_files
# ===================================================================


class TestCleanupTempFiles:
    def test_deletes_temp_files(self, tmp_path):
        """Delete -TEMP- files from MEMORY_PATH and report counts."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "some-TEMP-20260301.md").write_text("t", encoding="utf-8")
        (memory_dir / "other-TEMP-20260302.md").write_text("t", encoding="utf-8")
        (memory_dir / "real-plan-20260303.md").write_text("keep", encoding="utf-8")

        with patch("aipass.flow.apps.handlers.mbank.process.MEMORY_PATH", memory_dir):
            from aipass.flow.apps.handlers.mbank.process import cleanup_temp_files

            result = cleanup_temp_files()

        assert result["files_found"] == 2
        assert result["files_deleted"] == 2
        assert result["failed_deletes"] == 0
        # Real plan file survives
        assert (memory_dir / "real-plan-20260303.md").exists()

    def test_no_temp_files_found(self, tmp_path):
        """Return zeros when no -TEMP- files exist."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        (memory_dir / "normal-plan.md").write_text("ok", encoding="utf-8")

        with patch("aipass.flow.apps.handlers.mbank.process.MEMORY_PATH", memory_dir):
            from aipass.flow.apps.handlers.mbank.process import cleanup_temp_files

            result = cleanup_temp_files()

        assert result["files_found"] == 0
        assert result["files_deleted"] == 0

    def test_handles_missing_memory_path(self, tmp_path):
        """Return zeros when MEMORY_PATH does not exist."""
        nonexistent = tmp_path / "no_such_dir"

        with patch("aipass.flow.apps.handlers.mbank.process.MEMORY_PATH", nonexistent):
            from aipass.flow.apps.handlers.mbank.process import cleanup_temp_files

            result = cleanup_temp_files()

        assert result["files_found"] == 0
        assert result["files_deleted"] == 0

    def test_reports_failed_deletes(self, tmp_path):
        """Report failed_deletes when unlink raises."""
        memory_dir = tmp_path / "memory"
        memory_dir.mkdir()
        temp_file = memory_dir / "broken-TEMP-20260301.md"
        temp_file.write_text("t", encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.MEMORY_PATH", memory_dir),
            patch.object(Path, "unlink", side_effect=PermissionError("denied")),
        ):
            from aipass.flow.apps.handlers.mbank.process import cleanup_temp_files

            result = cleanup_temp_files()

        assert result["files_found"] == 1
        assert result["failed_deletes"] == 1
        assert result["details"][0]["status"] == "delete_failed"


# ===================================================================
# 5. mbank/process.py — verify_and_heal_orphaned_plans
# ===================================================================


class TestVerifyAndHealOrphanedPlans:
    def test_heals_orphaned_closed_plan(self, tmp_path):
        """Move a closed plan file to processed_plans and report as healed."""
        plan_file = tmp_path / "FPLAN-0010.md"
        plan_file.write_text("orphan content", encoding="utf-8")
        processed_dir = tmp_path / "processed"

        registry = {
            "plans": {
                "10": {
                    "status": "closed",
                    "file_path": str(plan_file),
                },
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import (
                verify_and_heal_orphaned_plans,
            )

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 1
        assert result["successfully_healed"] == 1
        assert result["failed_to_heal"] == 0
        # Original file should be gone, destination should exist
        assert not plan_file.exists()
        assert (processed_dir / "FPLAN-0010.md").exists()

    def test_no_orphans_when_all_open(self, tmp_path):
        """Open plans are never considered orphans."""
        registry = {
            "plans": {
                "1": {"status": "open", "file_path": str(tmp_path / "FPLAN-0001.md")},
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                tmp_path / "processed",
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import (
                verify_and_heal_orphaned_plans,
            )

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 0

    def test_skips_closed_plan_with_missing_file(self, tmp_path):
        """Closed plan whose file is already gone is not an orphan."""
        registry = {
            "plans": {
                "7": {
                    "status": "closed",
                    "file_path": str(tmp_path / "FPLAN-0007-gone.md"),
                },
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                tmp_path / "processed",
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import (
                verify_and_heal_orphaned_plans,
            )

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 0

    def test_handles_duplicate_destination(self, tmp_path):
        """When destination already exists, append timestamp to avoid collision."""
        plan_file = tmp_path / "FPLAN-0020.md"
        plan_file.write_text("orphan", encoding="utf-8")
        processed_dir = tmp_path / "processed"
        processed_dir.mkdir()
        # Pre-create a collision at the destination
        (processed_dir / "FPLAN-0020.md").write_text("already there", encoding="utf-8")

        registry = {
            "plans": {
                "20": {"status": "closed", "file_path": str(plan_file)},
            }
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        with (
            patch("aipass.flow.apps.handlers.mbank.process.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
            patch(
                "aipass.flow.apps.handlers.mbank.process.PROCESSED_PLANS_DIR",
                processed_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process._get_all_registry_files",
                return_value=["fplan_registry.json"],
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import (
                verify_and_heal_orphaned_plans,
            )

            result = verify_and_heal_orphaned_plans()

        assert result["orphans_found"] == 1
        assert result["successfully_healed"] == 1
        assert not plan_file.exists()
        # Original collision file still present, plus the timestamped one
        assert (processed_dir / "FPLAN-0020.md").exists()
        # At least two files in processed dir now
        md_files = list(processed_dir.glob("FPLAN-0020*.md"))
        assert len(md_files) == 2


# ===================================================================
# 6. mbank/process.py — process_closed_plans
# ===================================================================


class TestProcessClosedPlans:
    def test_process_no_closed_plans(self, tmp_path):
        """When no closed plans exist, return success with zero processed."""
        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process.get_closed_plans",
                return_value=[],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={
                    "files_found": 0,
                    "files_deleted": 0,
                    "failed_deletes": 0,
                    "details": [],
                },
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 0
        assert result["errors"] == 0

    def test_process_single_plan_success(self, tmp_path):
        """Archive one closed plan, update registry, report processed=1."""
        plan_file = tmp_path / "FPLAN-0042.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "42": {
                    "status": "closed",
                    "file_path": str(plan_file),
                },
            },
            "last_updated": "2026-01-01",
        }
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps(registry), encoding="utf-8")

        closed_plans = [
            {
                "number": "42",
                "path": plan_file,
                "info": registry["plans"]["42"],
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
                return_value=True,
            ) as mock_archive,
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_flow_registry",
                return_value=registry,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.save_flow_registry",
            ) as mock_save,
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={
                    "files_found": 0,
                    "files_deleted": 0,
                    "failed_deletes": 0,
                    "details": [],
                },
            ),
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 1
        assert result["errors"] == 0
        mock_archive.assert_called_once_with(plan_file)
        mock_save.assert_called_once()
        # Verify registry was updated with processed=True
        assert registry["plans"]["42"]["processed"] is True

    def test_process_plan_archive_failure(self, tmp_path):
        """When archive_plan returns False, plan is counted as error."""
        plan_file = tmp_path / "FPLAN-0055.md"
        plan_file.write_text("content", encoding="utf-8")

        registry = {
            "plans": {
                "55": {
                    "status": "closed",
                    "file_path": str(plan_file),
                },
            },
            "last_updated": "2026-01-01",
        }

        closed_plans = [
            {
                "number": "55",
                "path": plan_file,
                "info": registry["plans"]["55"],
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
                return_value=False,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.load_flow_registry",
                return_value=registry,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.save_flow_registry",
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                return_value={
                    "files_found": 0,
                    "files_deleted": 0,
                    "failed_deletes": 0,
                    "details": [],
                },
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE",
                tmp_path / "fplan_registry.json",
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 0
        assert result["errors"] == 1
        assert result["results"][0]["status"] == "archive_failed"

    def test_process_handles_exception(self, tmp_path):
        """Top-level exception produces success=False response."""
        with patch(
            "aipass.flow.apps.handlers.mbank.process.get_closed_plans",
            side_effect=RuntimeError("unexpected boom"),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        assert result["success"] is False
        assert "unexpected boom" in result["error"]

    def test_process_calls_cleanup(self, tmp_path):
        """cleanup_temp_files is called after processing closed plans."""
        mock_cleanup = MagicMock(
            return_value={
                "files_found": 1,
                "files_deleted": 1,
                "failed_deletes": 0,
                "details": [],
            }
        )

        with (
            patch(
                "aipass.flow.apps.handlers.mbank.process.get_closed_plans",
                return_value=[],
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.cleanup_temp_files",
                mock_cleanup,
            ),
        ):
            from aipass.flow.apps.handlers.mbank.process import process_closed_plans

            result = process_closed_plans()

        mock_cleanup.assert_called_once()
        assert result["cleanup"]["files_deleted"] == 1


# ===================================================================
# 7. template/get_template.py — get_template
# ===================================================================


class TestGetTemplate:
    def test_loads_template_by_name(self, tmp_path):
        """Load a template by name from the templates directory."""
        templates_dir = tmp_path / "templates"
        templates_dir.mkdir()
        (templates_dir / "default.md").write_text(
            "# Plan {plan_number}\nSubject: {subject}\nDate: {today}\nLocation: {location}\nTag: {tag}",
            encoding="utf-8",
        )

        with patch(
            "aipass.flow.apps.handlers.template.get_template.TEMPLATES_DIR",
            templates_dir,
        ):
            from aipass.flow.apps.handlers.template.get_template import get_template

            result = get_template("default", number=1, location="flow", subject="Test")

        assert "FPLAN-0001" in result
        assert "Test" in result
        assert "flow" in result

    def test_uses_template_path_override(self, tmp_path):
        """When template_path is given, load from that file directly."""
        custom = tmp_path / "custom.md"
        custom.write_text(
            "Custom: {plan_number} - {subject} ({today}){tag}",
            encoding="utf-8",
        )

        from aipass.flow.apps.handlers.template.get_template import get_template

        result = get_template(template_path=custom, number=7, subject="Override", prefix="DPLAN")

        assert "DPLAN-0007" in result
        assert "Override" in result

    def test_custom_prefix_and_digits(self, tmp_path):
        """Verify custom prefix and digit count in plan_number."""
        tpl = tmp_path / "tpl.md"
        tpl.write_text("{plan_number}{tag}", encoding="utf-8")

        from aipass.flow.apps.handlers.template.get_template import get_template

        result = get_template(template_path=tpl, number=3, prefix="XPLAN", digits=6)

        assert result == "XPLAN-000003"

    def test_raises_file_not_found(self, tmp_path):
        """FileNotFoundError when template does not exist."""
        empty_dir = tmp_path / "templates"
        empty_dir.mkdir()

        with patch(
            "aipass.flow.apps.handlers.template.get_template.TEMPLATES_DIR",
            empty_dir,
        ):
            from aipass.flow.apps.handlers.template.get_template import get_template

            with pytest.raises(FileNotFoundError, match="not found"):
                get_template("nonexistent")

    def test_today_placeholder_filled(self, tmp_path):
        """The {today} placeholder is replaced with a date string."""
        tpl = tmp_path / "dated.md"
        tpl.write_text("Date: {today}{tag}", encoding="utf-8")

        from aipass.flow.apps.handlers.template.get_template import get_template

        result = get_template(template_path=tpl, number=1)

        # Should contain a date like 2026-04-03
        assert len(result) > len("Date: ")
        # The date portion should match YYYY-MM-DD format
        date_part = result.replace("Date: ", "")
        assert len(date_part) == 10
        assert date_part[4] == "-" and date_part[7] == "-"


# ===================================================================
# 8. template/plan_type_loader.py — discover_plan_types
# ===================================================================


class TestDiscoverPlanTypes:
    def test_discovers_plan_types_from_filesystem(self, tmp_path):
        """Discover plan types from subdirectories with .md files."""
        templates_dir = tmp_path / "templates"
        flow_dir = templates_dir / "flow_plans"
        flow_dir.mkdir(parents=True)
        (flow_dir / "default.md").write_text("template", encoding="utf-8")
        (flow_dir / "master.md").write_text("master tpl", encoding="utf-8")

        dev_dir = templates_dir / "dev_plans"
        dev_dir.mkdir()
        (dev_dir / "default.md").write_text("dev template", encoding="utf-8")

        prefix_map = {"flow_plans": "FPLAN", "dev_plans": "DPLAN"}

        with (
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
                templates_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader._get_prefix_map",
                return_value=prefix_map,
            ),
        ):
            from aipass.flow.apps.handlers.template.plan_type_loader import (
                discover_plan_types,
            )

            # Reset cache to force fresh scan
            import aipass.flow.apps.handlers.template.plan_type_loader as loader

            loader._plan_type_cache = None

            result = discover_plan_types()

        assert "flow_plans" in result
        assert "dev_plans" in result
        assert result["flow_plans"]["prefix"] == "FPLAN"
        assert result["dev_plans"]["prefix"] == "DPLAN"
        assert "default" in result["flow_plans"]["available_templates"]
        assert "master" in result["flow_plans"]["available_templates"]
        assert result["flow_plans"]["registry_file"] == "fplan_registry.json"

    def test_skips_hidden_directories(self, tmp_path):
        """Directories starting with . or _ are skipped."""
        templates_dir = tmp_path / "templates"
        hidden = templates_dir / ".hidden"
        hidden.mkdir(parents=True)
        (hidden / "default.md").write_text("nope", encoding="utf-8")

        underscore = templates_dir / "_internal"
        underscore.mkdir()
        (underscore / "default.md").write_text("nope", encoding="utf-8")

        with (
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
                templates_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader._get_prefix_map",
                return_value={},
            ),
        ):
            from aipass.flow.apps.handlers.template.plan_type_loader import (
                discover_plan_types,
            )

            import aipass.flow.apps.handlers.template.plan_type_loader as loader

            loader._plan_type_cache = None

            result = discover_plan_types()

        assert ".hidden" not in result
        assert "_internal" not in result

    def test_skips_dirs_without_md_files(self, tmp_path):
        """Directories with no .md files are skipped."""
        templates_dir = tmp_path / "templates"
        empty_type = templates_dir / "empty_plans"
        empty_type.mkdir(parents=True)
        (empty_type / "readme.txt").write_text("not a template", encoding="utf-8")

        with (
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
                templates_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader._get_prefix_map",
                return_value={"empty_plans": "EPLAN"},
            ),
        ):
            from aipass.flow.apps.handlers.template.plan_type_loader import (
                discover_plan_types,
            )

            import aipass.flow.apps.handlers.template.plan_type_loader as loader

            loader._plan_type_cache = None

            result = discover_plan_types()

        assert "empty_plans" not in result

    def test_skips_dirs_without_prefix_mapping(self, tmp_path):
        """Directories not in PREFIX_MAP are skipped with a warning."""
        templates_dir = tmp_path / "templates"
        unknown = templates_dir / "unknown_plans"
        unknown.mkdir(parents=True)
        (unknown / "default.md").write_text("tpl", encoding="utf-8")

        with (
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
                templates_dir,
            ),
            patch(
                "aipass.flow.apps.handlers.template.plan_type_loader._get_prefix_map",
                return_value={},
            ),
        ):
            from aipass.flow.apps.handlers.template.plan_type_loader import (
                discover_plan_types,
            )

            import aipass.flow.apps.handlers.template.plan_type_loader as loader

            loader._plan_type_cache = None

            result = discover_plan_types()

        assert "unknown_plans" not in result

    def test_returns_empty_when_no_templates_dir(self, tmp_path):
        """Return empty dict when templates directory does not exist."""
        with patch(
            "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
            tmp_path / "nonexistent",
        ):
            from aipass.flow.apps.handlers.template.plan_type_loader import (
                discover_plan_types,
            )

            import aipass.flow.apps.handlers.template.plan_type_loader as loader

            loader._plan_type_cache = None

            result = discover_plan_types()

        assert result == {}


# ===================================================================
# 9. template/registry_ops.py — prefix_exists
# ===================================================================


class TestPrefixExists:
    def test_existing_prefix_returns_true(self, tmp_path):
        """prefix_exists returns True for a registered prefix."""
        registry = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
            },
            "metadata": {"version": "1.0.0", "last_updated": "2026-03-18", "type_count": 1},
        }
        reg_path = tmp_path / "template_registry.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")

        # Also create the templates dir so auto-heal does not prune
        templates_dir = tmp_path / "templates" / "flow_plans"
        templates_dir.mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import prefix_exists

            assert prefix_exists("FPLAN") is True

    def test_case_insensitive_match(self, tmp_path):
        """prefix_exists is case-insensitive."""
        registry = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
            },
            "metadata": {"version": "1.0.0", "last_updated": "2026-03-18", "type_count": 1},
        }
        reg_path = tmp_path / "template_registry.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")

        templates_dir = tmp_path / "templates" / "flow_plans"
        templates_dir.mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import prefix_exists

            assert prefix_exists("fplan") is True

    def test_nonexistent_prefix_returns_false(self, tmp_path):
        """prefix_exists returns False for an unregistered prefix."""
        registry = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
            },
            "metadata": {"version": "1.0.0", "last_updated": "2026-03-18", "type_count": 1},
        }
        reg_path = tmp_path / "template_registry.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")

        templates_dir = tmp_path / "templates" / "flow_plans"
        templates_dir.mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import prefix_exists

            assert prefix_exists("ZPLAN") is False


# ===================================================================
# 10. template/registry_ops.py — get_prefix_map
# ===================================================================


class TestGetPrefixMap:
    def test_returns_correct_mapping(self, tmp_path):
        """get_prefix_map returns {dir_name: prefix} for all registered types."""
        registry = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
                "dev_plans": {"prefix": "DPLAN", "shorthand": "dplan"},
            },
            "metadata": {"version": "1.0.0", "last_updated": "2026-03-18", "type_count": 2},
        }
        reg_path = tmp_path / "template_registry.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")

        # Create template directories so auto-heal does not prune
        for name in ("flow_plans", "dev_plans"):
            (tmp_path / "templates" / name).mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

            result = get_prefix_map()

        assert result == {"flow_plans": "FPLAN", "dev_plans": "DPLAN"}

    def test_skips_entries_without_prefix_key(self, tmp_path):
        """Entries missing the 'prefix' key are excluded from the map."""
        registry = {
            "types": {
                "flow_plans": {"prefix": "FPLAN", "shorthand": "fplan"},
                "broken_type": {"shorthand": "broken"},
            },
            "metadata": {"version": "1.0.0", "last_updated": "2026-03-18", "type_count": 2},
        }
        reg_path = tmp_path / "template_registry.json"
        reg_path.write_text(json.dumps(registry), encoding="utf-8")

        for name in ("flow_plans", "broken_type"):
            (tmp_path / "templates" / name).mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

            result = get_prefix_map()

        assert "broken_type" not in result
        assert result == {"flow_plans": "FPLAN"}

    def test_auto_creates_registry_when_missing(self, tmp_path):
        """When registry file does not exist, get_prefix_map returns defaults."""
        reg_path = tmp_path / "flow_json" / "template_registry.json"

        # Create protected template directories so auto-heal does not prune
        for name in ("flow_plans", "dev_plans"):
            (tmp_path / "templates" / name).mkdir(parents=True)

        with (
            patch(
                "aipass.flow.apps.handlers.template.registry_ops.REGISTRY_PATH",
                reg_path,
            ),
            patch("aipass.flow.apps.handlers.template.registry_ops.FLOW_ROOT", tmp_path),
        ):
            from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map

            result = get_prefix_map()

        assert "flow_plans" in result
        assert result["flow_plans"] == "FPLAN"
        assert "dev_plans" in result
        assert result["dev_plans"] == "DPLAN"
        # Registry file should now exist
        assert reg_path.exists()
