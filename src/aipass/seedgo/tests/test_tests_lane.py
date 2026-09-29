# =================== META ====================
# Name: test_tests_lane.py
# Description: Template v1 — tests_lane module, retire_ops and template_ops
# Version: 1.0.2
# Created: 2026-09-21
# Modified: 2026-09-28
# =============================================

"""Tests for apps/modules/tests_lane.py and the handlers it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every file in handlers/tests_lane/ parses and imports
# seedgo: no-test-needed(documentation) — that the public handler functions carry docstrings
# seedgo: no-test-needed(constant) — RECEIPT_FILE's spelling, asserted BY NAME; the bump tests pin the event's string
# seedgo: no-test-needed(stdlib) — shutil.move's ability to move a file
# seedgo: no-test-needed(cli) — Rich's rendering of the status table

import json

import pytest

from aipass.seedgo.apps.handlers import registry_scan
from aipass.seedgo.apps.handlers.json import json_handler
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


@pytest.fixture
def refused_receipts(monkeypatch) -> list:
    """write_json answers False at its home, and every path it was asked to write is kept."""
    asked: list = []

    def refuse(path, data):
        asked.append(path)
        return False

    monkeypatch.setattr(json_handler, "write_json", refuse)
    return asked


def bumped(dry_run: bool, stamped: int, branches: str) -> tuple:
    """The one event a bump announces, as the bus recorder holds it.

    Spelled out in full, the event's name included, so a renamed event or two
    keys swapped reddens every bump test (seedgo, fleet green leg 4).
    """
    return (
        "test_template_bumped",
        {"dry_run": dry_run, "stamped": stamped, "branches": branches, "versions": '{"test_template": "9.9.9"}'},
    )


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
    def test_a_dry_run_names_who_would_be_stamped_and_writes_nothing(self, capsys, fleet, gold, bus):
        """Mutants: the event renamed; stamped and dry_run swapped — both killed (leg 4)."""
        tests_lane.handle_command("tests", ["template", "bump"])

        printed = capsys.readouterr().out
        assert "DRY RUN" in printed and "would-stamp   alpha" in printed
        assert "Nothing was written" in printed
        assert not (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).exists()
        assert bus.fired == [bumped(dry_run=True, stamped=0, branches="")]

    def test_confirm_writes_the_receipt_and_the_page_into_the_branch(self, fleet, gold, bus):
        """Mutants: the event renamed; stamped and dry_run swapped — both killed (leg 4)."""
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        tests_dir = fleet / "src" / "aipass" / "alpha" / "tests"
        receipt = json.loads((tests_dir / template_ops.RECEIPT_FILE).read_text(encoding="utf-8"))
        assert receipt["template_versions"] == {"test_template": "9.9.9"}
        assert receipt["stamped_by"] == "seedgo tests template bump"
        assert "the page body" in (tests_dir / "TEST_TEMPLATE.md").read_text(encoding="utf-8")
        assert bus.fired == [bumped(dry_run=False, stamped=1, branches="alpha")]

    def test_a_branch_with_no_tests_directory_is_named_not_created(self, capsys, fleet, gold, bus):
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert "no-tests-dir  beta" in capsys.readouterr().out
        assert not (fleet / "src" / "aipass" / "beta" / "tests").exists()
        assert bus.fired == [bumped(dry_run=False, stamped=1, branches="alpha")]

    def test_naming_one_branch_leaves_every_other_branch_alone(self, capsys, fleet, gold, bus):
        tests_lane.handle_command("tests", ["template", "bump", "@beta", "--confirm"])

        assert "skipped       alpha" in capsys.readouterr().out
        assert not (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).exists()
        assert bus.fired == [bumped(dry_run=False, stamped=0, branches="")]

    def test_a_second_bump_leaves_a_current_branch_untouched(self, capsys, fleet, gold, bus):
        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])
        stamped = (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).read_text(encoding="utf-8")
        capsys.readouterr()

        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert "current       alpha" in capsys.readouterr().out
        assert (fleet / "src" / "aipass" / "alpha" / "tests" / template_ops.RECEIPT_FILE).read_text(
            encoding="utf-8"
        ) == stamped
        assert bus.fired == [
            bumped(dry_run=False, stamped=1, branches="alpha"),
            bumped(dry_run=False, stamped=0, branches=""),
        ]

    def test_a_stamp_that_cannot_land_is_reported_failed_with_its_error(self, fleet, gold):
        """A failed write came back as the action text "failed: <error>", a string no caller compares.

        Mutant: _stamp's old `except Exception: return f"failed: {exc}"` — killed.
        """
        tests_dir = fleet / "src" / "aipass" / "alpha" / "tests"
        (tests_dir / "TEST_TEMPLATE.md").mkdir()

        outcome = template_ops.bump(confirm=True, only="alpha")

        alpha = [row for row in outcome["branches"] if row["branch"] == "alpha"]
        assert [row["action"] for row in alpha] == ["failed"]
        assert "TEST_TEMPLATE.md" in alpha[0]["error"]
        assert not (tests_dir / template_ops.RECEIPT_FILE).exists()

    def test_a_receipt_that_does_not_land_is_failed_and_never_reads_current(self, fleet, gold, refused_receipts):
        """The receipt is written LAST, so a branch whose receipt did not land is stamped again next time.

        The receipt is the claim "this branch carries gold"; a later bump sees
        it and calls the branch current. Written first, a receipt beside a page
        that then failed would read current for ever (seedgo's order, leg 4).
        Mutant T2: the raise condition made always false — killed (leg 4).
        """
        branch = fleet / "src" / "aipass" / "alpha"

        outcome = template_ops.bump(confirm=True, only="alpha")

        target = template_ops.receipt_path(branch)
        assert refused_receipts == [target]
        assert outcome["branches"] == [
            {"branch": "alpha", "action": "failed", "carries": None, "error": f"receipt not written: {target}"},
            {"branch": "beta", "action": "skipped", "carries": None},
        ]
        assert "the page body" in (branch / "tests" / "TEST_TEMPLATE.md").read_text(encoding="utf-8")
        assert template_ops.read_receipt(branch) is None

    def test_a_page_that_is_not_utf8_stops_the_bump_before_any_branch_is_stamped(self, fleet, gold):
        """The page is read once, before the fleet: an unreadable page is the bump's error.

        It was read per branch inside the loop, and a UnicodeDecodeError (a
        ValueError, not an OSError) escaped bump() with no outcome returned
        (seedgo's decision, leg 4).
        """
        page = gold / "test_template_v1.md"
        page.write_bytes(b"\xff\xfe not utf-8 \x80")
        with pytest.raises(UnicodeDecodeError) as unreadable:
            page.read_text(encoding="utf-8")

        outcome = template_ops.bump(confirm=True, only="alpha")

        assert outcome == {
            "dry_run": False,
            "gold": {"test_template": "9.9.9"},
            "branches": [],
            "error": f"page unreadable: {page}: {unreadable.value}",
        }
        assert template_ops.read_receipt(fleet / "src" / "aipass" / "alpha") is None

    def test_the_command_prints_the_error_of_a_failed_stamp(self, capsys, fleet, gold, refused_receipts):
        """A failed row's reason reaches the user, and the shell reads the failure.

        The command exited 0 with a branch unstamped, so drone and a script
        saw success (seedgo's decision, leg 4: exit 2, a lane that could not run).
        Mutant L1: _run_bump's error print replaced by pass — killed (leg 4).
        """
        with pytest.raises(CommandRefused) as refusal:
            tests_lane.handle_command("tests", ["template", "bump", "@alpha", "--confirm"])

        assert refusal.value.code == 2
        target = template_ops.receipt_path(fleet / "src" / "aipass" / "alpha")
        assert refused_receipts == [target]
        printed = capsys.readouterr()
        lines = [line.strip() for line in printed.out.splitlines()]
        assert lines.count(f"receipt not written: {target}") == 1
        assert "1 of 2 branches not stamped" in printed.err

    def test_a_bump_with_nothing_to_distribute_exits_non_zero(self, capsys, fleet, gold):
        """An outcome error was printed and then handed the shell a 0 (seedgo's decision, leg 4)."""
        (gold / "test_template_v1.md").unlink()

        with pytest.raises(CommandRefused) as refusal:
            tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert refusal.value.code == 2
        assert f"no page to distribute: {gold / 'test_template_v1.md'} is missing" in capsys.readouterr().err

    def test_a_test_body_is_never_distributed(self, fleet, gold, bus):
        """The one thing this lane must never do: a branch's tests stay its own."""
        mine = fleet / "src" / "aipass" / "alpha" / "tests" / "test_theirs.py"
        mine.write_text("# alpha's own test\n", encoding="utf-8")

        tests_lane.handle_command("tests", ["template", "bump", "--confirm"])

        assert mine.read_text(encoding="utf-8") == "# alpha's own test\n"
        landed = {p.name for p in (fleet / "src" / "aipass" / "alpha" / "tests").iterdir()}
        assert landed == {"test_theirs.py", "TEST_TEMPLATE.md", template_ops.RECEIPT_FILE}
        assert bus.fired == [bumped(dry_run=False, stamped=1, branches="alpha")]

    def test_an_unknown_verb_under_template_refuses_with_the_argument_exit_code(self, capsys, fleet, gold):
        with pytest.raises(CommandRefused) as refusal:
            tests_lane.handle_command("tests", ["template", "sprinkle"])

        assert refusal.value.code == 7
        assert "template sprinkle" in capsys.readouterr().err
