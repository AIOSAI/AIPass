# =================== AIPass ====================
# Name: test_mbank_template.py
# Description: Tests for mbank/process.py and template handler functions
# Version: 1.1.0
# Created: 2026-09-20
# Modified: 2026-10-24
# =============================================

"""Tests for mbank/process.py and template handler functions."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the mbank/template handler files parse and import

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.flow.apps.handlers.mbank.process import (
    get_closed_plans,
    process_closed_plans,
    verify_and_heal_orphaned_plans,
)
from aipass.flow.apps.handlers.template import plan_type_loader as loader
from aipass.flow.apps.handlers.template.get_template import (
    TEMPLATES_DIR,
    get_template,
)
from aipass.flow.apps.handlers.template.plan_type_loader import discover_plan_types
from aipass.flow.apps.handlers.template.registry_ops import get_prefix_map


def _unlink_answer(path: Path) -> OSError | None:
    """Unlink ``path`` with the test's own hands and keep what the platform answers.

    Returns:
        The OSError the unlink raised, or None when the platform refused nothing.
    """
    try:
        path.unlink()
    except OSError as exc:
        return exc
    return None


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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            result = get_closed_plans()

        assert len(result) == 0

    def test_calls_verify_and_heal(self, tmp_path):
        """get_closed_plans calls verify_and_heal_orphaned_plans internally, BEFORE it
        reads the registries -- so a row the heal repairs is returned on this same call.

        Mutant: moving verify_and_heal_orphaned_plans() after the registry loop reddens this.
        """
        healed_file = tmp_path / "FPLAN-0007.md"
        healed_file.write_text("closed plan", encoding="utf-8")
        row = {"status": "closed", "file_path": str(tmp_path / "gone" / "FPLAN-0007.md")}
        reg_file = tmp_path / "fplan_registry.json"
        reg_file.write_text(json.dumps({"plans": {"7": row}}), encoding="utf-8")

        def heal() -> dict:
            """Stand-in heal: repoint the orphaned row at the file that exists."""
            reg_file.write_text(json.dumps({"plans": {"7": {**row, "file_path": str(healed_file)}}}), encoding="utf-8")
            return {"orphans_found": 1, "successfully_healed": 1, "failed_to_heal": 0, "orphans": []}

        mock_heal = MagicMock(side_effect=heal)

        with (
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            result = get_closed_plans()

        mock_heal.assert_called_once_with()
        assert [(p["number"], p["path"]) for p in result] == [("7", healed_file)]


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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
            patch("aipass.flow.apps.handlers.registry.load_registry.FLOW_JSON_DIR", tmp_path),
            patch("aipass.flow.apps.handlers.registry.save_registry.FLOW_JSON_DIR", tmp_path),
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
        ):
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
                "aipass.flow.apps.handlers.mbank.process.load_registry",
                return_value=registry,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.save_registry",
            ) as mock_save,
            patch("aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE", reg_file),
        ):
            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 1
        assert result["errors"] == 0
        mock_archive.assert_called_once_with(plan_file)
        mock_save.assert_called_once()
        # Verify registry was updated with processed=True
        assert registry["plans"]["42"]["processed"] is True

    def test_process_plan_archive_failure(self, tmp_path):
        """When archive_plan returns False, plan is counted as error.

        Mutant: cleanup_completed = archive_success -> = True reddens this.
        """
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
                "aipass.flow.apps.handlers.mbank.process.load_registry",
                return_value=registry,
            ),
            patch(
                "aipass.flow.apps.handlers.mbank.process.save_registry",
            ) as mock_save,
            patch(
                "aipass.flow.apps.handlers.mbank.process.REGISTRY_FILE",
                tmp_path / "fplan_registry.json",
            ),
        ):
            result = process_closed_plans()

        assert result["success"] is True
        assert result["processed"] == 0
        assert result["errors"] == 1
        assert result["results"][0]["status"] == "archive_failed"
        # The failed archive is still recorded (cleanup_completed=False), never marked processed.
        mock_save.assert_called_once_with(registry, registry_file="fplan_registry.json")
        assert registry["plans"]["55"]["cleanup_completed"] is False
        assert "processed" not in registry["plans"]["55"]

    def test_process_handles_exception(self, tmp_path):
        """Top-level exception produces success=False response."""
        with patch(
            "aipass.flow.apps.handlers.mbank.process.get_closed_plans",
            side_effect=RuntimeError("unexpected boom"),
        ):
            result = process_closed_plans()

        assert result["success"] is False
        assert "unexpected boom" in result["error"]


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

        result = get_template(template_path=custom, number=7, subject="Override", prefix="DPLAN")

        assert "DPLAN-0007" in result
        assert "Override" in result

    def test_custom_prefix_and_digits(self, tmp_path):
        """Verify custom prefix and digit count in plan_number."""
        tpl = tmp_path / "tpl.md"
        tpl.write_text("{plan_number}{tag}", encoding="utf-8")

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
            with pytest.raises(FileNotFoundError, match="not found"):
                get_template("nonexistent")

    def test_today_placeholder_filled(self, tmp_path):
        """The {today} placeholder is replaced with a date string."""
        tpl = tmp_path / "dated.md"
        tpl.write_text("Date: {today}{tag}", encoding="utf-8")

        result = get_template(template_path=tpl, number=1)

        # Should contain a date like 2026-04-03
        assert len(result) > len("Date: ")
        # The date portion should match YYYY-MM-DD format
        date_part = result.replace("Date: ", "")
        assert len(date_part) == 10
        assert date_part[4] == "-" and date_part[7] == "-"

    def test_literal_braces_in_prose_survive(self, tmp_path):
        """ERROR d3de39ba: SOP templates document code with braces.

        weekly_update.md carries a literal ``{createIfEmpty: true}`` MCP call,
        which str.format() read as a replacement field and raised KeyError on --
        making the whole template un-instantiable. Unknown braces must pass
        through verbatim instead of blowing up template loading.
        """
        tpl = tmp_path / "sop.md"
        tpl.write_text(
            'Run `tabs_context_mcp {createIfEmpty: true}` for {subject}.\nJSON: {"a": 1}\nSet: {}',
            encoding="utf-8",
        )

        result = get_template(template_path=tpl, number=1, subject="Weekly")

        # Known placeholder still substituted...
        assert "for Weekly." in result
        # ...while every non-placeholder brace form is preserved untouched.
        assert "{createIfEmpty: true}" in result
        assert 'JSON: {"a": 1}' in result
        assert "Set: {}" in result

    def test_unknown_placeholder_is_not_substituted(self, tmp_path):
        """A brace token that is not a known placeholder is left alone, not blanked."""
        tpl = tmp_path / "unknown.md"
        tpl.write_text("{plan_number} {not_a_placeholder}", encoding="utf-8")

        result = get_template(template_path=tpl, number=2)

        assert result == "FPLAN-0002 {not_a_placeholder}"

    # Retired leg 10: test_missing_placeholder_value_passes_through. get_template,
    # the one caller, supplies every name in PLACEHOLDER_NAMES, so a known name
    # without a value never reaches the substitution. VERA's createIfEmpty
    # report (a brace form that is no placeholder) stays pinned above through
    # get_template.

    def test_registered_weekly_update_template_stamps(self):
        """The shipped weekly_update SOP loads end-to-end from its real path.

        Guards the brace-in-prose class against the live file rather than a
        synthetic one, and pins VERA's v2.1 content (full clickable URLs,
        Bluesky posting from the caller's own branch dir).
        """
        tpl = TEMPLATES_DIR / "playbook_plans" / "weekly_update.md"
        assert tpl.is_file(), f"weekly_update template missing at {tpl}"

        result = get_template(template_path=tpl, number=31, subject="Update 14", prefix="PPLAN")

        assert "PPLAN-0031" in result
        assert "Update 14" in result
        # Literal MCP snippet survives the stamp
        assert "{createIfEmpty: true}" in result
        # v2.1 content landed — pin a full template sentence, not the bare
        # domain: a URL-substring membership check reads to CodeQL like
        # hostname sanitization (py/incomplete-url-substring-sanitization).
        assert "Website: https://aipass.ai, changelog link" in result
        assert "YOUR OWN branch dir" in result

    @pytest.mark.parametrize("tpl", sorted(TEMPLATES_DIR.glob("*/*.md")), ids=lambda p: f"{p.parent.name}/{p.name}")
    def test_a_fresh_plan_of_every_shipped_template_has_no_listen_section(self, tpl):
        result = get_template(template_path=tpl, number=1, subject="Fresh")

        assert "## Listen" not in result
        assert "Spoken summary: written only when the user asks for one" in result


# ===================================================================
# 8. template/plan_type_loader.py — discover_plan_types
# ===================================================================


class TestDiscoverPlanTypes:
    def test_discovers_plan_types_from_filesystem(self, tmp_path, monkeypatch):
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
            # Reset cache to force fresh scan
            monkeypatch.setattr(loader, "_plan_type_cache", None)

            result = discover_plan_types()

        assert "flow_plans" in result
        assert "dev_plans" in result
        assert result["flow_plans"]["prefix"] == "FPLAN"
        assert result["dev_plans"]["prefix"] == "DPLAN"
        assert "default" in result["flow_plans"]["available_templates"]
        assert "master" in result["flow_plans"]["available_templates"]
        assert result["flow_plans"]["registry_file"] == "fplan_registry.json"

    def test_skips_hidden_directories(self, tmp_path, monkeypatch):
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
            monkeypatch.setattr(loader, "_plan_type_cache", None)

            result = discover_plan_types()

        assert ".hidden" not in result
        assert "_internal" not in result

    def test_skips_dirs_without_md_files(self, tmp_path, monkeypatch):
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
            monkeypatch.setattr(loader, "_plan_type_cache", None)

            result = discover_plan_types()

        assert "empty_plans" not in result

    def test_skips_dirs_without_prefix_mapping(self, tmp_path, monkeypatch):
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
            monkeypatch.setattr(loader, "_plan_type_cache", None)

            result = discover_plan_types()

        assert "unknown_plans" not in result

    def test_returns_empty_when_no_templates_dir(self, tmp_path, monkeypatch):
        """Return empty dict when templates directory does not exist."""
        with patch(
            "aipass.flow.apps.handlers.template.plan_type_loader.PLAN_TYPES_DIR",
            tmp_path / "nonexistent",
        ):
            monkeypatch.setattr(loader, "_plan_type_cache", None)

            result = discover_plan_types()

        assert result == {}


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
            result = get_prefix_map()

        assert "flow_plans" in result
        assert result["flow_plans"] == "FPLAN"
        assert "dev_plans" in result
        assert result["dev_plans"] == "DPLAN"
        # Registry file should now exist
        assert reg_path.exists()
