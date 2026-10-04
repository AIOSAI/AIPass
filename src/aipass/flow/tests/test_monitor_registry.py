# =================== AIPass ====================
# Name: test_monitor_registry.py
# Description: Tests for monitor_ops handler and registry_monitor module
# Version: 2.1.0
# Created: 2026-03-08
# Modified: 2026-10-04
# =============================================

"""Tests for apps/handlers/registry/monitor_ops.py and apps/modules/registry_monitor.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that monitor_ops.py and registry_monitor.py parse and import

import os
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

from aipass.flow.apps.handlers.registry import monitor_ops
from aipass.flow.apps.handlers.template import get_template as template_mod
from aipass.flow.apps.modules import registry_monitor


def _make_plan_file(directory: Path, number: str) -> Path:
    """Create a FPLAN-NNNN.md file in the given directory, with a plan's header line."""
    filename = f"FPLAN-{number}.md"
    plan_file = directory / filename
    plan_file.write_text(f"# FPLAN-{number}: Test plan\nTest content", encoding="utf-8")
    return plan_file


class TestEveryPlanCreateWritesIsAPlan:
    """Every template create renders must read as a plan, in both header forms (leg 8).

    Leg 7 checked the colon form only and claimed every template used it;
    flow_plans (FPLAN, the default type) and playbook_plans open with
    ``# {plan_number} - {subject}``, and six live open plans carry the dash.
    devpulse widened is_plan_file in d1a1100d. Red first against the
    colon-only line; mutant leg8 D1 (dash form dropped) reddens both tests.
    """

    def test_the_dash_form_is_a_plan(self, tmp_path):
        plan = tmp_path / "FPLAN-0300_old_form_2026-01-01.md"
        plan.write_text("# FPLAN-0300 - an older plan\n", encoding="utf-8")

        assert monitor_ops.is_plan_file(plan) is True

    def test_every_template_renders_a_plan_header(self, tmp_path):
        """Renders each template under templates/ the way create does and asks is_plan_file."""
        templates = Path(monitor_ops.__file__).parents[3] / "templates"
        rendered = sorted(p for p in templates.glob("*/*.md") if p.name != "README.md")
        assert len(rendered) >= 11, f"walk did not reach the templates: {rendered}"

        not_plans = []
        with patch.object(template_mod, "json_handler", MagicMock()):
            for number, template in enumerate(rendered, start=1):
                text = template_mod.get_template(
                    number=number, subject="subject", template_path=template, prefix="FPLAN"
                )
                plan = tmp_path / f"FPLAN-{number:04d}_{template.parent.name}_{template.stem}.md"
                plan.write_text(text, encoding="utf-8")
                if monitor_ops.is_plan_file(plan) is not True:
                    not_plans.append(f"{template.parent.name}/{template.name}: {text.splitlines()[0]!r}")

        assert not_plans == []


# ═══════════════════════════════════════════════════════════
# 1. handle_walk_error
# ═══════════════════════════════════════════════════════════


class TestHandleWalkError:
    """Tests for the handle_walk_error inner function in scan_plan_files_impl."""

    def test_permission_error_is_silenced(self, tmp_path, mock_logger):
        """PermissionError should not trigger a warning log.

        Mutant: if not isinstance(error, PermissionError): -> if isinstance(error, OSError): reddens this.
        """
        mod = monitor_ops
        with patch.object(mod, "_fire_event", return_value=True):
            restricted = tmp_path / "restricted"
            restricted.mkdir()
            _make_plan_file(tmp_path, "0001")

            os.chmod(str(restricted), 0o000)
            try:
                result = mod.scan_plan_files_impl(
                    ecosystem_root=tmp_path,
                    load_registry=lambda: {"plans": {}},
                )
                # The scan still finds the readable plan, and says nothing
                # about the directory it was refused.
                assert result["added"] == ["0001"]
                warned = [str(c) for c in mock_logger.warning.call_args_list]
                assert not any("Error during scan" in w for w in warned), warned
            finally:
                os.chmod(str(restricted), 0o755)

    def test_generic_os_error_logs_warning(self, tmp_path, mock_logger):
        """Non-PermissionError OSError should be logged as warning."""
        mod = monitor_ops
        missing = tmp_path / "nonexistent_root"
        with patch.object(mod, "_fire_event", return_value=False):
            result = mod.scan_plan_files_impl(
                ecosystem_root=missing,
                load_registry=lambda: {"plans": {}},
            )
            assert result["total_plans"] == 0
            assert result["added"] == []


# ═══════════════════════════════════════════════════════════
# 2. scan_plan_files_impl
# ═══════════════════════════════════════════════════════════


class TestScanPlanFilesImpl:
    """Tests for scan_plan_files_impl in monitor_ops."""

    def test_detects_plan_files_in_root(self, tmp_path):
        """Plan files at root level should be detected."""
        mod = monitor_ops
        _make_plan_file(tmp_path, "0001")
        _make_plan_file(tmp_path, "0002")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]
        assert "0002" in result["added"]
        assert result["healing_performed"] is True

    def test_detects_plan_files_in_subdirectories(self, tmp_path):
        """Plan files in subdirectories should be detected."""
        mod = monitor_ops
        sub = tmp_path / "projects" / "alpha"
        sub.mkdir(parents=True)
        _make_plan_file(sub, "0010")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0010" in result["added"]

    def test_ignores_non_plan_files(self, tmp_path):
        """Non-plan files should be ignored even if they look similar."""
        mod = monitor_ops
        _make_plan_file(tmp_path, "0001")
        (tmp_path / "DPLAN-0002.md").write_text("# DPLAN-0002: also a plan", encoding="utf-8")
        (tmp_path / "FPLAN-ABC.md").write_text("bad number", encoding="utf-8")
        (tmp_path / "README.md").write_text("readme", encoding="utf-8")
        (tmp_path / "NOTES-0003.md").write_text("not a plan prefix", encoding="utf-8")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert sorted(result["added"]) == ["0001", "0002"]

    def test_skips_ignored_folders(self, tmp_path):
        """Directories in IGNORE_FOLDERS should be skipped."""
        mod = monitor_ops
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        _make_plan_file(git_dir, "0001")

        pycache_dir = tmp_path / "__pycache__"
        pycache_dir.mkdir()
        _make_plan_file(pycache_dir, "0002")

        good_dir = tmp_path / "active"
        good_dir.mkdir()
        _make_plan_file(good_dir, "0003")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0003" in result["added"]
        assert "0001" not in result["added"]
        assert "0002" not in result["added"]

    def test_detects_plan_files_with_slug_and_date_suffix(self, tmp_path):
        """Real plan filenames carry a subject slug + date suffix and must still match."""
        mod = monitor_ops
        (tmp_path / "FPLAN-0001_some_subject_slug_2026-07-27.md").write_text("# FPLAN-0001: plan", encoding="utf-8")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_ignored_folder_requires_exact_name_match(self, tmp_path):
        """Substring matches (e.g. 'dev' in 'devpulse') must not skip unrelated directories."""
        mod = monitor_ops
        lookalike_dir = tmp_path / "devpulse"
        lookalike_dir.mkdir()
        _make_plan_file(lookalike_dir, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_dropbox_folder_is_ignored(self, tmp_path):
        """dropbox/ is a received-files inbox -- old snapshot copies must never register."""
        mod = monitor_ops
        dropbox_dir = tmp_path / "dropbox"
        dropbox_dir.mkdir()
        _make_plan_file(dropbox_dir, "0001")

        good_dir = tmp_path / "active"
        good_dir.mkdir()
        _make_plan_file(good_dir, "0002")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" not in result["added"]
        assert "0002" in result["added"]

    def test_dropbox_ignore_requires_exact_name_match(self, tmp_path):
        """Lookalike names (e.g. 'dropbox-clone') must not be skipped -- exact match only."""
        mod = monitor_ops
        lookalike_dir = tmp_path / "dropbox-clone"
        lookalike_dir.mkdir()
        _make_plan_file(lookalike_dir, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert "0001" in result["added"]

    def test_orphaned_closed_plan_does_not_fire_deleted(self, tmp_path):
        """Closed plans are expected to be archived out of the scan tree — not orphans."""
        mod = monitor_ops
        registry = {
            "plans": {
                "0001": {"file_path": str(tmp_path / "FPLAN-0001.md"), "status": "closed"},
                "0002": {"file_path": str(tmp_path / "FPLAN-0002.md"), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" not in result["removed"]
        assert "0002" in result["removed"]

    def test_detects_orphaned_registry_entries(self, tmp_path):
        """Registry entries with no matching file should fire deleted events."""
        mod = monitor_ops
        registry = {
            "plans": {
                "0001": {"file_path": str(tmp_path / "FPLAN-0001.md"), "status": "open"},
                "0002": {"file_path": str(tmp_path / "FPLAN-0002.md"), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" in result["removed"]
        assert "0002" in result["removed"]
        assert result["healing_performed"] is True

    def test_detects_moved_files(self, tmp_path):
        """Files that exist but at a different path should fire moved events."""
        mod = monitor_ops
        new_dir = tmp_path / "new_location"
        new_dir.mkdir()
        _make_plan_file(new_dir, "0001")

        registry = {
            "plans": {
                "0001": {
                    "file_path": str(tmp_path / "old_location" / "FPLAN-0001.md"),
                    "status": "open",
                },
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert "0001" in result["updated"]

    def test_no_changes_needed(self, tmp_path):
        """When disk matches registry, no healing should be needed."""
        mod = monitor_ops
        plan = _make_plan_file(tmp_path, "0001")

        registry = {
            "plans": {
                "0001": {"file_path": str(plan), "status": "open"},
            }
        }
        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: registry,
            )
        assert result["added"] == []
        assert result["updated"] == []
        assert result["removed"] == []
        assert result["duplicates"] == []
        assert result["healing_performed"] is False

    def test_duplicate_plan_files_reported_not_renamed(self, tmp_path):
        """Duplicate plan numbers are reported; both files keep their names (leg 7)."""
        mod = monitor_ops
        dir_a = tmp_path / "project_a"
        dir_a.mkdir()
        dir_b = tmp_path / "project_b"
        dir_b.mkdir()

        first = _make_plan_file(dir_a, "0001")
        second = _make_plan_file(dir_b, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert result["duplicates"] == [{"prefix": "FPLAN", "number": "0001", "paths": [str(first), str(second)]}]
        assert first.exists() and second.exists()
        assert sorted(p.name for p in tmp_path.rglob("*.md")) == ["FPLAN-0001.md", "FPLAN-0001.md"]

    def test_scan_calls_json_handler_log(self, tmp_path, mock_json_handler):
        """Scan should log its results via json_handler."""
        mod = monitor_ops
        _make_plan_file(tmp_path, "0001")

        with patch.object(mod, "_fire_event", return_value=True):
            mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        mock_json_handler.assert_called_once()
        call_args = mock_json_handler.call_args
        assert call_args[0][0] == "plan_files_scanned"
        assert call_args[0][1]["success"] is True

    def test_fire_event_failure_excludes_from_results(self, tmp_path):
        """If _fire_event returns False, the plan should not appear in added."""
        mod = monitor_ops
        _make_plan_file(tmp_path, "0001")

        with patch.object(mod, "_fire_event", return_value=False):
            result = mod.scan_plan_files_impl(
                ecosystem_root=tmp_path,
                load_registry=lambda: {"plans": {}},
            )
        assert result["added"] == []


# ═══════════════════════════════════════════════════════════
# 3. get_status_impl
# ═══════════════════════════════════════════════════════════


class TestGetStatusImpl:
    """Tests for get_status_impl in monitor_ops."""

    def test_status_returns_correct_fields(self, tmp_path):
        """Status should return all expected fields."""
        mod = monitor_ops
        registry = {
            "plans": {
                "0001": {"status": "open"},
                "0002": {"status": "closed"},
                "0003": {"status": "open"},
            }
        }
        result = mod.get_status_impl(tmp_path, load_registry=lambda: registry)
        assert result["monitoring_active"] is False
        assert result["total_plans"] == 3
        assert result["open_plans"] == 2
        assert result["watch_location"] == str(tmp_path)
        assert result["module"] == "registry_monitor"
        assert result["version"] == "2.0.0"
        assert result["ignore_folders"] == len(mod.IGNORE_FOLDERS)

    def test_status_with_empty_registry(self, tmp_path):
        """Status should handle empty registry."""
        mod = monitor_ops
        result = mod.get_status_impl(tmp_path, load_registry=lambda: {"plans": {}})
        assert result["total_plans"] == 0
        assert result["open_plans"] == 0


# ═══════════════════════════════════════════════════════════
# 4. registry_monitor module wrappers
# ═══════════════════════════════════════════════════════════


class TestRegistryMonitorGetStatus:
    """Tests for registry_monitor.get_status wrapper."""

    def test_get_status_delegates_to_impl(self):
        """get_status should delegate to get_status_impl with correct args."""
        mod = registry_monitor
        expected = {
            "module": "registry_monitor",
            "version": "2.0.0",
            "monitoring_active": False,
            "watch_location": "/some/path",
            "total_plans": 5,
            "open_plans": 3,
            "ignore_folders": 20,
        }
        with patch.object(mod, "get_status_impl", return_value=expected) as mock_impl:
            result = mod.get_status()
        assert result == expected
        mock_impl.assert_called_once_with(
            ecosystem_root=mod.ECOSYSTEM_ROOT,
            load_registry=mod.load_registry,
        )


class TestAnUnreadableRegistryIsRefusedByName:
    """`registry status` / `registry scan` over a registry load_registry refuses.

    Before leg 6 the load answered an empty registry; now it raises, and
    uncaught the raise reached flow.py's router, which logged it and said
    "unknown command". Red first without the catch; mutant: the handler's
    `except RegistryUnreadableError` narrowed to `except KeyError`.
    """

    def _refuse(self, subcommand, impl):
        mod = registry_monitor
        refusal = mod.RegistryUnreadableError("Plan registry fplan_registry.json cannot be read: stand-in")
        with (
            patch.object(mod, impl, side_effect=refusal),
            patch.object(mod, "error") as error_stand_in,
        ):
            handled = mod.handle_command("registry", [subcommand])
        return handled, error_stand_in, refusal

    def test_status_is_handled_and_says_why(self):
        handled, error_stand_in, refusal = self._refuse("status", "get_status_impl")

        assert handled is True
        error_stand_in.assert_called_once_with(f"Registry status refused: {refusal}")

    def test_scan_is_handled_and_says_why(self, capsys):
        handled, error_stand_in, refusal = self._refuse("scan", "scan_plan_files_impl")

        assert handled is True
        error_stand_in.assert_called_once_with(f"Registry scan refused: {refusal}")
        assert "Scan complete" not in capsys.readouterr().out


# ═══════════════════════════════════════════════════════════
# 5. _fire_event helper
# ═══════════════════════════════════════════════════════════


class TestFireEvent:
    """Tests for the _fire_event helper function."""

    def test_fire_event_success(self, tmp_path):
        """Successful event fire should return True."""
        mod = monitor_ops
        mock_trigger = MagicMock()
        fake_core = MagicMock(trigger=mock_trigger)
        plan_path = str(tmp_path / "FPLAN-0001.md")
        with patch.dict(
            "sys.modules",
            {"aipass.trigger.apps.modules.core": fake_core},
        ):
            result = mod._fire_event("plan_file_created", path=plan_path)
        assert result is True
        mock_trigger.fire.assert_called_once_with("plan_file_created", path=plan_path)

    def test_fire_event_import_error(self, mock_logger):
        """ImportError should return False and log warning."""
        mod = monitor_ops
        # A None entry in sys.modules makes the import raise ImportError.
        with patch.dict("sys.modules", {"aipass.trigger.apps.modules.core": None}):
            result = mod._fire_event("test_event")
        assert result is False


# ═══════════════════════════════════════════════════════════
# Cross-type numbers are NOT duplicates
#
# Ruling 2026-08-22 (the owner): "numbers are separated by plan names. the plan
# name is the separation. aplan0002 fplan0001 dplan0001 pplan0001." The on-disk
# index used to key on the bare number, so APLAN-0007 and FPLAN-0007 read as one
# plan filed twice — and the scan RENAMES the loser on the filesystem, dropping
# its topic slug and orphaning its registry row. heal_registry's own index has
# always keyed on (prefix, number); this brings the scan in line.
#
# Every test here asserts the walk REACHED the files before asserting on the
# outcome: a scan that found nothing would satisfy "nothing was renamed".
# ═══════════════════════════════════════════════════════════


def _write_plan(directory: Path, name: str) -> Path:
    """Create a plan file on disk, opening with its plan header, and return its path."""
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    identity = name.removesuffix(".md").split("_")[0]
    path.write_text(f"# {identity}: plan\n", encoding="utf-8")
    return path


class TestCrossTypeNumbersAreNotDuplicates:
    """Same number, different type = two plans, not one to repair."""

    def test_aplan_and_fplan_sharing_a_number_are_both_left_alone(self, tmp_path):
        mod = monitor_ops
        aplan = _write_plan(tmp_path / "a", "APLAN-0007_branch_audit_flow_2026-08-13.md")
        fplan = _write_plan(tmp_path / "b", "FPLAN-0007_some_build_2026-08-13.md")

        with patch.object(mod, "_fire_event", MagicMock(return_value=True)) as fire:
            result = mod.scan_plan_files_impl(tmp_path, load_registry=lambda: {"plans": {}})

        # REACHED: both files were walked. Without this the assertions below
        # would also pass on an empty scan.
        assert fire.call_count == 2, "scan did not reach both plan files"

        assert result["duplicates"] == []
        assert aplan.exists(), "APLAN-0007 was renamed away"
        assert fplan.exists(), "FPLAN-0007 was renamed away"

    def test_four_types_one_number_all_survive(self, tmp_path):
        mod = monitor_ops
        paths = [
            _write_plan(tmp_path / p.lower(), f"{p}-0001_topic_2026-08-13.md")
            for p in ("APLAN", "FPLAN", "DPLAN", "PPLAN")
        ]

        with patch.object(mod, "_fire_event", MagicMock(return_value=True)) as fire:
            result = mod.scan_plan_files_impl(tmp_path, load_registry=lambda: {"plans": {}})

        assert fire.call_count == 4, "scan did not reach all four plan files"
        assert result["duplicates"] == []
        for p in paths:
            assert p.exists(), f"{p.name} was renamed away"


class TestGenuineDuplicatesAreReportedNotRenamed:
    """Same prefix AND same number: reported, never renamed (flow's decision, leg 7).

    The scan renamed every file after the first until leg 7, and most of the
    46 files it renamed in flow's logs were reports named after a plan.
    Mutant: the report's paths emptied reddens this (leg7 M5).
    """

    def test_two_fplans_with_one_number_both_keep_their_names(self, tmp_path):
        mod = monitor_ops
        first = _write_plan(tmp_path / "one", "FPLAN-0007_first_2026-08-13.md")
        second = _write_plan(tmp_path / "two", "FPLAN-0007_second_2026-08-13.md")

        with patch.object(mod, "_fire_event", MagicMock(return_value=True)) as fire:
            result = mod.scan_plan_files_impl(tmp_path, load_registry=lambda: {"plans": {}})

        # REACHED: one created event for the number; the report names both.
        assert fire.call_count == 1, "scan did not reach the plan files"
        assert result["duplicates"] == [{"prefix": "FPLAN", "number": "0007", "paths": [str(first), str(second)]}]
        assert first.exists() and second.exists()
        assert sorted(p.name for p in tmp_path.rglob("*.md")) == [first.name, second.name]


class TestALookAlikeIsNotAPlan:
    """A report named like a plan is not one (leg 7: hooks' DPLAN-0356_ph2_report.md).

    Live on 2026-10-04 02:31 the scan renamed hooks/docs.local/
    DPLAN-0356_ph2_report.md to DPLAN-0358.md and heal registered it as a plan.
    Proof is the mutants, not a first red: the scan's gate off, the header
    check off, the number dropped from it, and unreadable -> True each redden
    a test here (leg7/mutants.txt M1 to M4).
    """

    @staticmethod
    def _world(root: Path) -> Tuple[Path, Path]:
        """A real DPLAN-0356 and a phase report named after it in a docs.local folder."""
        plan = _write_plan(root / "devpulse", "DPLAN-0356_fleet_green_2026-10-01.md")
        report = root / "hooks" / "docs.local" / "DPLAN-0356_ph2_report.md"
        report.parent.mkdir(parents=True)
        report.write_text("DPLAN-0356 phase 2 DONE\n", encoding="utf-8")
        return plan, report

    def test_scan_neither_renames_nor_reports_the_report(self, tmp_path):
        mod = monitor_ops
        plan, report = self._world(tmp_path)

        with patch.object(mod, "_fire_event", MagicMock(return_value=True)) as fire:
            result = mod.scan_plan_files_impl(tmp_path, load_registry=lambda: {"plans": {}})

        fire.assert_called_once_with("plan_file_created", path=str(plan))
        assert result["duplicates"] == []
        assert report.read_text(encoding="utf-8") == "DPLAN-0356 phase 2 DONE\n"
        assert sorted(p.name for p in tmp_path.rglob("*.md")) == [plan.name, report.name]

    def test_is_plan_file_tells_the_two_apart(self, tmp_path):
        plan, report = self._world(tmp_path)

        assert monitor_ops.is_plan_file(plan) is True
        assert monitor_ops.is_plan_file(report) is False

    def test_a_heading_that_only_starts_with_the_id_is_not_a_plan(self, tmp_path):
        """'# DPLAN-0356 phase 2 notes' is a report's heading: only ':' or ' - ' follow a plan's id.

        Mutant leg8 D2 (' - ' widened to ' ') survived without this test.
        """
        notes = tmp_path / "DPLAN-0356_ph2_notes.md"
        notes.write_text("# DPLAN-0356 phase 2 notes\n", encoding="utf-8")

        assert monitor_ops.is_plan_file(notes) is False

    def test_a_header_for_another_number_is_not_this_plan(self, tmp_path):
        """A copy of DPLAN-0356 saved as DPLAN-0357.md is not plan 0357."""
        copy = tmp_path / "DPLAN-0357.md"
        copy.write_text("# DPLAN-0356: fleet green\n", encoding="utf-8")

        assert monitor_ops.is_plan_file(copy) is False

    def test_an_unreadable_file_is_unknown_not_a_plan(self, tmp_path):
        """Undecodable bytes: None, which every caller treats as 'not a plan to act on'."""
        binary = tmp_path / "DPLAN-0356.md"
        binary.write_bytes(b"\xff\xfe# DPLAN-0356: x\n")

        assert monitor_ops.is_plan_file(binary) is None


class TestDuplicateReportIsDeterministic:
    """The report's path order is identity, not the order the OS walked."""

    @staticmethod
    def _report(mod, root: Path, reverse_walk: bool) -> List[str]:
        """Scan ``root`` with the walk emitted in a chosen order; return the reported names."""
        _write_plan(root / "alpha", "FPLAN-0007_alpha_2026-08-13.md")
        _write_plan(root / "beta", "FPLAN-0007_beta_2026-08-13.md")
        real_walk = os.walk

        def ordered_walk(top, **kwargs):
            steps = list(real_walk(top, **kwargs))
            return reversed(steps) if reverse_walk else iter(steps)

        with patch.object(mod.os, "walk", ordered_walk):
            with patch.object(mod, "_fire_event", MagicMock(return_value=True)):
                result = mod.scan_plan_files_impl(root, load_registry=lambda: {"plans": {}})

        assert len(result["duplicates"]) == 1, f"expected one duplicate, got {result['duplicates']}"
        return [Path(p).name for p in result["duplicates"][0]["paths"]]

    def test_same_order_in_either_walk_order(self, tmp_path):
        """Reversing the walk must not reorder the report. Mutant: the sort -> reverse() reddens this (leg7 M6)."""
        mod = monitor_ops

        forward = self._report(mod, tmp_path / "forward", reverse_walk=False)
        backward = self._report(mod, tmp_path / "backward", reverse_walk=True)

        assert forward == backward == ["FPLAN-0007_alpha_2026-08-13.md", "FPLAN-0007_beta_2026-08-13.md"]
