# =================== META ====================
# Name: test_tests_lane.py
# Description: Template v1 — tests_lane module, retire_ops and template_ops
# Version: 1.0.2
# Created: 2026-09-21
# Modified: 2026-09-27
# =============================================

"""Tests for apps/modules/tests_lane.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/tests_lane/ parses and imports
# seedgo: no-test-needed(documentation) — that the public handler functions carry docstrings
# seedgo: no-test-needed(constant) — RECEIPT_FILE's spelling and the BUMP_EVENT string; both asserted BY NAME
# seedgo: no-test-needed(stdlib) — shutil.move's ability to move a file
# seedgo: no-test-needed(cli) — Rich's rendering of the status table

import json

import pytest

from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.tests_lane import template_ops
from aipass.seedgo.apps.modules import CommandRefused, tests_lane


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """A whole repo the test built: two branches, a registry, no live paths.

    The seam is registry_scan, which both discovery and retire_ops resolve
    through, so one patch moves the repo root AND the branch list at once.
    """
    for name in ("alpha", "beta"):
        branch = tmp_path / "src" / "aipass" / name
        (branch / "apps").mkdir(parents=True)
        (branch / "apps" / f"{name}.py").write_text("# entry point\n", encoding="utf-8")
    (tmp_path / "src" / "aipass" / "alpha" / "tests").mkdir()

    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps(
            {
                "branches": [
                    {"name": "ALPHA", "path": str(tmp_path / "src" / "aipass" / "alpha")},
                    {"name": "BETA", "path": str(tmp_path / "src" / "aipass" / "beta")},
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(registry_scan, "find_registry", lambda: registry)
    monkeypatch.setattr(registry_scan, "caller_registries", list)
    monkeypatch.setattr(tests_lane, "BRANCH", "alpha")
    return tmp_path


@pytest.fixture
def retired(fleet):
    """One file already retired out of alpha's tests/, with its log line."""
    folder = fleet / ".backup" / "tests" / "alpha"
    folder.mkdir(parents=True)
    (folder / "test_old.py").write_text("# the retired file\n", encoding="utf-8")
    (folder / "retired.json").write_text(
        json.dumps(
            {
                "document_metadata": {"managed_by": "seedgo"},
                "entries": [
                    {
                        "what": "test_old.py",
                        "when": "2026-09-21T00:11:00-07:00",
                        "why": "replaced under template v1",
                        "from": "src/aipass/alpha/tests/test_old.py",
                        "by": "seedgo",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return fleet


@pytest.fixture
def gold(tmp_path, monkeypatch):
    """A gold templates directory this test wrote, never the branch's own."""
    folder = tmp_path / "gold"
    folder.mkdir()
    (folder / "templates.json").write_text(
        json.dumps({"template_versions": {"test_template": "9.9.9"}}), encoding="utf-8"
    )
    (folder / "test_template_v1.md").write_text("# Test template\n\nthe page body\n", encoding="utf-8")
    monkeypatch.setattr(template_ops, "GOLD_DIR", folder)
    return folder


# ---------------------------------------------------------------------------
# handle_command — the routing a user actually types
# ---------------------------------------------------------------------------


class TestHandleCommand:
    def test_a_command_that_is_not_ours_is_declined(self):
        assert tests_lane.handle_command("wrong_command", []) is False

    def test_both_spellings_reach_this_modules_introspection(self, capsys):
        for spelling in ("tests", "tests_lane"):
            assert tests_lane.handle_command(spelling, []) is True
        assert capsys.readouterr().out.count("tests_lane Module") == 2

    def test_an_unknown_subcommand_refuses_with_the_argument_exit_code(self, capsys):
        """The owner's 2026-09-07 ruling: an unrecognised argument exits non-zero."""
        with pytest.raises(CommandRefused) as refusal:
            tests_lane.handle_command("tests", ["bogus_subcommand"])

        out, err = capsys.readouterr()
        assert refusal.value.code == 7
        assert "Unknown subcommand: 'bogus_subcommand'" in err
        assert "Valid subcommands:" in out

    def test_a_help_flag_behind_a_verb_explains_instead_of_running_it(self, capsys, retired):
        """`tests retired -h` must describe the lane, never list it."""
        assert tests_lane.handle_command("tests", ["retired", "-h"]) is True

        printed = capsys.readouterr().out
        assert "COMMANDS:" in printed
        assert "test_old.py" not in printed


# ---------------------------------------------------------------------------
# tests retired — the retire lane, through the command
# ---------------------------------------------------------------------------


class TestRetiredListing:
    def test_a_retired_file_is_listed_with_the_line_that_put_it_there(self, capsys, retired):
        tests_lane.handle_command("tests", ["retired"])

        printed = capsys.readouterr().out
        assert "test_old.py" in printed
        assert "replaced under template v1" in printed
        assert "src/aipass/alpha/tests/test_old.py" in printed

    def test_an_empty_lane_says_so_rather_than_printing_an_empty_table(self, capsys, fleet):
        tests_lane.handle_command("tests", ["retired"])

        printed = capsys.readouterr().out
        assert "nothing retired" in printed
        assert "Restore one" not in printed

    def test_a_log_line_whose_file_is_gone_is_called_out_on_stderr(self, capsys, retired):
        """A line nobody can act on is worse than no line; the lane has to say so."""
        (retired / ".backup" / "tests" / "alpha" / "test_old.py").unlink()

        tests_lane.handle_command("tests", ["retired"])

        out, err = capsys.readouterr()
        assert "test_old.py" in out
        assert "the file is gone" in err

    def test_a_file_with_no_log_line_is_still_listed_rather_than_hidden(self, capsys, retired):
        folder = retired / ".backup" / "tests" / "alpha"
        (folder / "test_unlogged.py").write_text("# dropped in by hand\n", encoding="utf-8")

        tests_lane.handle_command("tests", ["retired"])

        printed = capsys.readouterr().out
        assert "test_unlogged.py" in printed
        assert "nothing recorded it" in printed


# ---------------------------------------------------------------------------
# tests restore — a move back, never a copy
# ---------------------------------------------------------------------------


class TestRestore:
    def test_restore_returns_the_file_to_the_path_its_log_line_names(self, capsys, retired):
        tests_lane.handle_command("tests", ["restore", "test_old.py"])

        landed = retired / "src" / "aipass" / "alpha" / "tests" / "test_old.py"
        assert landed.read_text(encoding="utf-8") == "# the retired file\n"
        assert not (retired / ".backup" / "tests" / "alpha" / "test_old.py").exists()
        assert "Restored" in capsys.readouterr().out

    def test_a_restored_file_loses_its_log_line_so_it_is_not_claimed_twice(self, retired):
        tests_lane.handle_command("tests", ["restore", "test_old"])

        log = json.loads((retired / ".backup" / "tests" / "alpha" / "retired.json").read_text(encoding="utf-8"))
        assert log["entries"] == []

    def test_a_name_that_was_never_retired_is_an_error_not_a_silent_pass(self, capsys, retired):
        tests_lane.handle_command("tests", ["restore", "test_never_here.py"])

        assert "nothing retired under that name" in capsys.readouterr().err

    def test_a_file_with_no_log_line_refuses_rather_than_guess_a_destination(self, capsys, retired):
        """Inventing a plausible tests/ for it would be the silent-fallback disease."""
        folder = retired / ".backup" / "tests" / "alpha"
        (folder / "test_unlogged.py").write_text("# dropped in by hand\n", encoding="utf-8")

        tests_lane.handle_command("tests", ["restore", "test_unlogged.py"])

        assert "no log line" in capsys.readouterr().err
        assert (folder / "test_unlogged.py").exists()

    def test_restore_refuses_rather_than_overwrite_a_live_file(self, capsys, retired):
        live = retired / "src" / "aipass" / "alpha" / "tests" / "test_old.py"
        live.write_text("# the file that is already there\n", encoding="utf-8")

        tests_lane.handle_command("tests", ["restore", "test_old.py"])

        assert "already exists" in capsys.readouterr().err
        assert live.read_text(encoding="utf-8") == "# the file that is already there\n"
        assert (retired / ".backup" / "tests" / "alpha" / "test_old.py").exists()

    def test_restore_with_no_name_prints_the_usage_line(self, capsys, retired):
        tests_lane.handle_command("tests", ["restore"])

        assert "Usage: drone @seedgo tests restore <name>" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tests template-status — receipts against gold
# ---------------------------------------------------------------------------


class TestTemplateStatus:
    def test_a_branch_with_no_receipt_is_named_as_unstamped(self, capsys, fleet, gold):
        tests_lane.handle_command("tests", ["template-status"])

        printed = capsys.readouterr().out
        assert "0/2 carry the current version" in printed
        assert "alpha: NO RECEIPT" in printed

    def test_a_branch_carrying_gold_is_counted_current(self, capsys, fleet, gold):
        receipt = fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE
        receipt.write_text(json.dumps({"template_versions": {"test_template": "9.9.9"}}), encoding="utf-8")

        tests_lane.handle_command("tests", ["template-status"])

        printed = capsys.readouterr().out
        assert "1/2 carry the current version" in printed
        assert "alpha:" not in printed

    def test_an_old_version_is_reported_with_the_version_it_carries(self, capsys, fleet, gold):
        receipt = fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE
        receipt.write_text(json.dumps({"template_versions": {"test_template": "0.1.0"}}), encoding="utf-8")

        tests_lane.handle_command("tests", ["template-status"])

        assert "alpha: test_template 0.1.0" in capsys.readouterr().out

    def test_a_missing_gold_manifest_is_an_error_not_an_empty_all_clear(self, capsys, fleet, gold):
        """Zero gold versions would make every branch read as current."""
        (gold / "templates.json").unlink()

        tests_lane.handle_command("tests", ["template-status"])

        assert "No gold versions" in capsys.readouterr().err


# ---------------------------------------------------------------------------
# tests template bump — the write, and the report that precedes it
# ---------------------------------------------------------------------------


class TestTemplateBump:
    def test_a_dry_run_names_who_would_be_stamped_and_writes_nothing(self, capsys, fleet, gold):
        tests_lane.handle_command("tests", ["template", "bump"])

        printed = capsys.readouterr().out
        assert "DRY RUN" in printed and "would-stamp   alpha" in printed
        assert "Nothing was written" in printed
        assert not (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).exists()

    def test_confirm_writes_the_receipt_and_the_page_into_the_branch(self, fleet, gold):
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        tests_dir = fleet / "src" / "aipass" / "alpha" / "tests"
        receipt = json.loads((tests_dir / template_ops.RECEIPT_FILE).read_text(encoding="utf-8"))
        assert receipt["template_versions"] == {"test_template": "9.9.9"}
        assert receipt["stamped_by"] == "seedgo tests template bump"
        assert "the page body" in (tests_dir / "TEST_TEMPLATE.md").read_text(encoding="utf-8")

    def test_a_branch_with_no_tests_directory_is_named_not_created(self, capsys, fleet, gold):
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert "no-tests-dir  beta" in capsys.readouterr().out
        assert not (fleet / "src" / "aipass" / "beta" / "tests").exists()

    def test_naming_one_branch_leaves_every_other_branch_alone(self, capsys, fleet, gold):
        tests_lane.handle_command("tests", ["template", "bump", "@beta", "--confirm"])

        assert "skipped       alpha" in capsys.readouterr().out
        assert not (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).exists()

    def test_a_second_bump_leaves_a_current_branch_untouched(self, capsys, fleet, gold):
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])
        stamped = (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).read_text(encoding="utf-8")
        capsys.readouterr()

        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert "current       alpha" in capsys.readouterr().out
        assert (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).read_text(
            encoding="utf-8"
        ) == stamped

    def test_a_stamp_that_cannot_land_is_reported_failed_with_its_error(self, fleet, gold):
        """A failed write came back as the action text "failed: <error>", a string no caller compares.

        Mutant: _stamp's old `except Exception: return f"failed: {exc}"` — killed.
        """
        (fleet / "src" / "aipass" / "alpha" / "tests" / "TEST_TEMPLATE.md").mkdir()

        outcome = template_ops.bump(confirm=True, only="alpha")

        alpha = [row for row in outcome["branches"] if row["branch"] == "alpha"]
        assert [row["action"] for row in alpha] == ["failed"]
        assert "TEST_TEMPLATE.md" in alpha[0]["error"]

    def test_a_test_body_is_never_distributed(self, fleet, gold):
        """The one thing this lane must never do: a branch's tests stay its own."""
        mine = fleet / "src" / "aipass" / "alpha" / "tests" / "test_theirs.py"
        mine.write_text("# alpha's own test\n", encoding="utf-8")

        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert mine.read_text(encoding="utf-8") == "# alpha's own test\n"
        landed = {p.name for p in (fleet / "src" / "aipass" / "alpha" / "tests").iterdir()}
        assert landed == {"test_theirs.py", "TEST_TEMPLATE.md", template_ops.RECEIPT_FILE}

    def test_an_unknown_verb_under_template_refuses_with_the_argument_exit_code(self, capsys, fleet, gold):
        with pytest.raises(CommandRefused) as refusal:
            tests_lane.handle_command("tests", ["template", "sprinkle"])

        assert refusal.value.code == 7
        assert "template sprinkle" in capsys.readouterr().err
