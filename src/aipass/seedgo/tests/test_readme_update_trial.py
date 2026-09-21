# =================== META ====================
# Name: test_readme_update_trial.py
# Description: Template v1 trial — readme_update module, readme_generator and readme_ops
# Version: 2.1.0
# Created: 2026-09-20
# Modified: 2026-09-20
# =============================================

"""Tests for apps/modules/readme_update.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/readme/ parses and imports
# seedgo: no-test-needed(documentation) — that the public generator functions carry docstrings
# seedgo: no-test-needed(constant) — SECTION_NAMES' display strings and MARKER_PREFIX's text
# seedgo: no-test-needed(stdlib) — importlib's ability to load a module from a path
# seedgo: no-test-needed(generated) — the tree glyphs; the shape is CPython's os.scandir order

import json
import os
import sys
from pathlib import Path

import pytest

from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.readme import readme_generator, readme_ops
from aipass.seedgo.apps.modules import readme_update


# A read-only file is the only route a command has to a write failure, and it is
# not one everywhere: Windows ignores the bit and root writes through it.
_WRITE_BIT_HOLDS = sys.platform != "win32" and getattr(os, "geteuid", lambda: 1)() != 0


def _set_writable(path: Path, writable: bool) -> None:
    if sys.platform != "win32":
        os.chmod(path, 0o644 if writable else 0o444)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def branch(tmp_path):
    """A branch tree with one auto-marked README, the shape the product expects."""
    (tmp_path / "apps").mkdir()
    (tmp_path / "apps" / "main.py").write_text("# entry point\n", encoding="utf-8")
    (tmp_path / "README.md").write_text(
        "# Title\nprose above\n<!-- AUTO:TREE -->\nstale\n<!-- /AUTO:TREE -->\nprose below\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def registered(branch, tmp_path, monkeypatch):
    """The branch above, reachable as @made_up through a registry this test built."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps({"branches": [{"name": "MADE_UP", "path": str(branch)}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry_scan, "find_registry", lambda: registry)
    return branch


# ---------------------------------------------------------------------------
# handle_command — the routing a user actually types
# ---------------------------------------------------------------------------


class TestHandleCommand:
    def test_a_command_that_is_not_ours_is_declined(self):
        assert readme_update.handle_command("wrong_command", []) is False

    def test_both_spellings_reach_this_modules_introspection(self, capsys):
        for spelling in ("readme", "readme_update"):
            assert readme_update.handle_command(spelling, []) is True
        assert capsys.readouterr().out.count("readme_update Module") == 2

    def test_no_args_names_the_module_and_its_handlers(self, capsys):
        readme_update.handle_command("readme", [])
        printed = capsys.readouterr().out
        assert "readme_update Module" in printed
        assert "handlers/readme/" in printed

    def test_a_help_flag_behind_a_subcommand_explains_instead_of_updating(self, capsys, monkeypatch):
        """`readme update -h` must describe the update, never perform it."""
        ran = []
        monkeypatch.setattr(readme_update, "_handle_update", lambda args: ran.append(args))

        assert readme_update.handle_command("readme", ["update", "-h"]) is True

        printed = capsys.readouterr().out
        assert ran == []
        assert "README Auto-Update" in printed
        assert "readme update @branch" in printed

    def test_an_unknown_subcommand_is_named_back_on_stderr_with_the_valid_list(self, capsys):
        readme_update.handle_command("readme", ["bogus_subcommand"])

        out, err = capsys.readouterr()
        assert "Unknown subcommand: 'bogus_subcommand'" in err
        assert "Valid subcommands:" in out

    def test_update_forwards_the_args_that_followed_it(self, monkeypatch):
        ran = []
        monkeypatch.setattr(readme_update, "_handle_update", lambda args: ran.append(args))

        readme_update.handle_command("readme", ["update", "@flow", "--extra"])

        assert ran == [["@flow", "--extra"]]

    def test_check_never_reaches_the_writing_path(self, monkeypatch):
        checked, updated = [], []
        monkeypatch.setattr(readme_update, "_handle_check", lambda args: checked.append(args))
        monkeypatch.setattr(readme_update, "_handle_update", lambda args: updated.append(args))

        readme_update.handle_command("readme", ["check", "@flow"])

        assert checked == [["@flow"]] and updated == []


# ---------------------------------------------------------------------------
# readme update / readme check — a whole run, through the command
# ---------------------------------------------------------------------------


class TestUpdateRun:
    def test_a_named_branch_is_updated_and_its_readme_rewritten(self, capsys, registered):
        readme_update.handle_command("readme", ["update", "@made_up"])

        printed = capsys.readouterr().out
        assert "README Update: MADE_UP" in printed
        assert "Updated" in printed and "TREE" in printed
        assert "main.py" in (registered / "README.md").read_text(encoding="utf-8")

    @pytest.mark.skipif(not _WRITE_BIT_HOLDS, reason="the write cannot be made to fail on this platform")
    def test_a_write_failure_is_reported_on_stderr_and_no_section_is_claimed(self, capsys, registered):
        """A run that errored must not also claim the sections it had already rendered."""
        readme = registered / "README.md"
        _set_writable(readme, False)
        try:
            readme_update.handle_command("readme", ["update", "@made_up"])
        finally:
            _set_writable(readme, True)

        out, err = capsys.readouterr()
        assert "Failed to write README.md" in err
        assert "Updated" not in out and "Skipped" not in out

    def test_check_says_would_update_where_update_says_updated(self, capsys, registered):
        readme_update.handle_command("readme", ["check", "@made_up"])
        checked = capsys.readouterr().out

        readme_update.handle_command("readme", ["update", "@made_up"])
        updated = capsys.readouterr().out

        assert "Would update" in checked and "content differs" in checked
        assert "Updated" not in checked
        assert "Updated" in updated

    def test_a_section_with_no_marker_is_called_skipped_and_named(self, capsys, registered):
        readme_update.handle_command("readme", ["update", "@made_up"])

        printed = capsys.readouterr().out
        assert "Skipped" in printed and "no marker found" in printed
        assert "LAST_UPDATED" in printed

    def test_a_section_with_nothing_to_generate_is_silent_on_update_and_named_on_check(self, capsys, registered):
        """Noise here is noise on every run; check mode is the place that says nothing changed."""
        readme_update.handle_command("readme", ["update", "@made_up"])
        updated = capsys.readouterr().out

        readme_update.handle_command("readme", ["check", "@made_up"])
        checked = capsys.readouterr().out

        assert "Up to date" not in updated
        assert "Up to date" in checked and "MODULES" in checked

    def test_no_target_is_refused_with_the_usage_line_and_nothing_is_written(self, capsys, registered):
        """`readme update` with no branch must never fan out across the fleet."""
        before = (registered / "README.md").read_text(encoding="utf-8")

        readme_update.handle_command("readme", ["update"])

        assert "Usage: drone @seedgo readme update @branch" in capsys.readouterr().err
        assert (registered / "README.md").read_text(encoding="utf-8") == before

    def test_an_unknown_branch_is_named_back_in_the_error(self, capsys, registered):
        readme_update.handle_command("readme", ["update", "@nope_xyz"])

        assert "Branch '@nope_xyz' not found in registry" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# update_readme_auto_sections — the write itself
# ---------------------------------------------------------------------------


class TestMarkerReplacement:
    def test_the_marked_region_is_replaced_and_prose_outside_it_is_untouched(self, branch):
        """The whole product promise: rewrite between markers, never a hand-written line."""
        result = readme_generator.update_readme_auto_sections(str(branch))

        written = (branch / "README.md").read_text(encoding="utf-8")
        assert result["updated"] == ["tree"]
        assert "stale" not in written
        assert "main.py" in written
        assert written.startswith("# Title\nprose above\n")
        assert written.endswith("prose below\n")

    def test_a_section_with_no_markers_is_reported_not_silently_dropped(self, branch):
        result = readme_generator.update_readme_auto_sections(str(branch))

        assert "last_updated" in result["missing_markers"]
        assert "last_updated" not in result["updated"]

    def test_a_dry_run_reports_the_change_and_writes_nothing(self, branch):
        before = (branch / "README.md").read_text(encoding="utf-8")

        result = readme_generator.update_readme_auto_sections(str(branch), dry_run=True)

        assert result["updated"] == ["tree"] and result["dry_run"] is True
        assert (branch / "README.md").read_text(encoding="utf-8") == before

    def test_a_missing_readme_is_an_error_not_a_crash(self, tmp_path):
        result = readme_generator.update_readme_auto_sections(str(tmp_path))

        assert result["errors"] == ["README.md not found"]
        assert result["updated"] == []

    def test_every_marker_name_in_the_map_is_recognised(self, tmp_path):
        """A marker the generator emits but cannot find again is a silent no-op."""
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "main.py").write_text("# entry\n", encoding="utf-8")
        body = "\n".join(f"<!-- AUTO:{m} -->\nx\n<!-- /AUTO:{m} -->" for m in ("TREE", "LAST_UPDATED"))
        (tmp_path / "README.md").write_text(body + "\n", encoding="utf-8")

        result = readme_generator.update_readme_auto_sections(str(tmp_path))

        assert sorted(result["updated"]) == ["last_updated", "tree"]
        assert result["missing_markers"] == []


# ---------------------------------------------------------------------------
# readme_generator — the sections
# ---------------------------------------------------------------------------


class TestTreeSection:
    def test_a_missing_directory_yields_no_section_rather_than_a_broken_fence(self, tmp_path):
        assert readme_generator.generate_tree_section(str(tmp_path / "nonexistent")) == ""

    def test_a_real_tree_is_fenced_and_names_the_files_in_it(self, tmp_path):
        (tmp_path / "apps").mkdir()
        (tmp_path / "apps" / "main.py").write_text("# entry\n", encoding="utf-8")

        result = readme_generator.generate_tree_section(str(tmp_path))

        assert result.startswith("```") and result.endswith("```")
        assert "apps" in result and "main.py" in result

    def test_pycache_never_reaches_a_published_readme(self, tmp_path):
        (tmp_path / "__pycache__").mkdir()
        (tmp_path / "__pycache__" / "m.cpython-312.pyc").write_text("", encoding="utf-8")
        (tmp_path / "real_file.py").write_text("# code\n", encoding="utf-8")

        result = readme_generator.generate_tree_section(str(tmp_path))

        assert "__pycache__" not in result
        assert "real_file.py" in result


class TestModulesSection:
    @staticmethod
    def _modules_dir(tmp_path):
        modules = tmp_path / "apps" / "modules"
        modules.mkdir(parents=True)
        return modules

    def test_no_modules_directory_yields_no_section(self, tmp_path):
        assert readme_generator.generate_modules_section(str(tmp_path)) == ""

    def test_each_module_is_listed_with_its_own_description_and_init_is_not(self, tmp_path):
        modules = self._modules_dir(tmp_path)
        (modules / "audit_ops.py").write_text('"""Audit Operations Module"""\n', encoding="utf-8")
        (modules / "__init__.py").write_text("", encoding="utf-8")

        result = readme_generator.generate_modules_section(str(tmp_path))

        assert "audit_ops" in result and "Audit Operations Module" in result
        assert "__init__" not in result

    def test_a_meta_name_line_beats_the_docstring_below_it(self, tmp_path):
        """Every product file carries both; the header is the one the README must show."""
        modules = self._modules_dir(tmp_path)
        (modules / "both.py").write_text(
            '# Name: both.py - The Header Description\n"""The Docstring Line"""\n', encoding="utf-8"
        )

        result = readme_generator.generate_modules_section(str(tmp_path))

        assert "The Header Description" in result
        assert "The Docstring Line" not in result

    def test_a_module_with_only_a_docstring_is_described_by_its_first_line(self, tmp_path):
        modules = self._modules_dir(tmp_path)
        (modules / "prose.py").write_text('"""My cool module\n\nMore details here.\n"""\nx = 1\n', encoding="utf-8")

        result = readme_generator.generate_modules_section(str(tmp_path))

        assert result == "- **prose** - My cool module"

    def test_a_module_that_describes_nothing_is_listed_bare_rather_than_guessed_at(self, tmp_path):
        modules = self._modules_dir(tmp_path)
        (modules / "bare.py").write_text("x = 1\ny = 2\n", encoding="utf-8")

        result = readme_generator.generate_modules_section(str(tmp_path))

        assert result == "- **bare**"


# ---------------------------------------------------------------------------
# readme_ops — target resolution
# ---------------------------------------------------------------------------


class TestTargetResolution:
    def test_no_target_is_its_own_error_not_a_silent_all(self):
        assert readme_ops.resolve_targets([]) == ([], "no_args")

    def test_an_unknown_branch_is_named_back_in_the_error(self, registered):
        branches, error = readme_ops.resolve_targets(["nope_xyz"])

        assert branches == []
        assert error == "not_found:nope_xyz"

    def test_a_named_branch_resolves_to_the_path_its_registry_entry_gives(self, registered):
        branches, error = readme_ops.resolve_targets(["@made_up"])

        assert error is None and len(branches) == 1
        assert branches[0]["path"] == str(registered)

    def test_the_generator_loads_from_beside_the_ops_handler(self):
        """load_generator resolves its own neighbour; a move breaks the update silently."""
        generator = readme_ops.load_generator()

        assert generator is not None
        assert hasattr(generator, "update_readme_auto_sections")
