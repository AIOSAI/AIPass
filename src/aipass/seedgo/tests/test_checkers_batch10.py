# =================== META ====================
# Name: test_checkers_batch10.py
# Description: Tests for hardcoded_path, developer_home, startup_budget, the ratchets, router_assert, oversize_test_file
# Version: 1.5.1
# Created: 2026-06-18
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/aipass_standards/hardcoded_path_check.py and batch-10 checkers."""

# Batch 10: hardcoded_path, startup_budget, the two ratchets, router_assert, oversize_test_file.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every checker module in this batch parses and imports
# seedgo: no-test-needed(stdlib) — re's matching itself; the patterns are pinned by what they catch here

import hashlib
import json

import pytest

# THE CONTEXT PACK IS IMPORTED AT MODULE SCOPE, AND THAT IS LOAD-BEARING.
# startup_budget_check reads its caps off @hooks' and @prax' REAL modules, so
# importing it inside a test body would bind those owners to mocks: every cap
# would come back a MagicMock, every row would read ERROR, and the tests that
# prove a cap is READ from its owner would be passing against nothing. Imported
# here, at collection time, the owners are real -- and a monkeypatch on one of
# their constants is then what moves a row. hardcoded_path_check joins them for
# the same reason: its own infrastructure (logger, json_handler, is_bypassed) is
# real too, so no mock stands between a test and the code it measures.
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as sb
from aipass.seedgo.apps.handlers.context_standards import startup_ratchet as ratchet
from aipass.seedgo.apps.handlers.context_standards import name_ratchet as names
from aipass.seedgo.apps.handlers.aipass_standards import applicability
from aipass.seedgo.apps.handlers.aipass_standards import router_assert_check as router_assert
from aipass.seedgo.apps.handlers.aipass_standards import oversize_test_file_check as oversize
from aipass.seedgo.apps.handlers.aipass_standards import hardcoded_path_check
from aipass.seedgo.apps.handlers.audit import branch_audit


def _scanned(tmp_path, content: str) -> str:
    """What the public check_module says about a file holding *content*."""
    sample = tmp_path / "sample.py"
    sample.write_text(content, encoding="utf-8")
    return hardcoded_path_check.check_module(str(sample))["checks"][0]["message"]


class TestScanFile:
    """Tests for the _scan_file helper, reached through the public check_module."""

    def test_posix_home_detected(self, tmp_path):
        content = 'ROOT = "/home/someone/Projects/AIPass"\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: POSIX home path (")

    def test_macos_home_detected(self, tmp_path):
        content = 'ROOT = "/Users/carol/Projects/AIPass"\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: macOS home path (")

    def test_windows_home_detected(self, tmp_path):
        content = 'ROOT = "C:\\\\Users\\\\someone\\\\Projects"\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: Windows home path (")

    def test_dash_encoded_posix_detected(self, tmp_path):
        content = 'dirs = ["-home-someone-Projects-AIPass"]\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: dash-encoded POSIX home (")

    def test_dash_encoded_macos_detected(self, tmp_path):
        content = 'dirs = ["-Users-carol-Projects-AIPass"]\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: dash-encoded macOS home (")

    def test_comment_skipped(self, tmp_path):
        content = '# ROOT = "/home/someone/Projects/AIPass"\n'
        said = _scanned(tmp_path, content)
        assert said == "No hardcoded absolute home paths found"

    def test_indented_comment_skipped(self, tmp_path):
        content = '    # path = "/home/someone/test"\n'
        said = _scanned(tmp_path, content)
        assert said == "No hardcoded absolute home paths found"

    def test_docstring_skipped(self, tmp_path):
        content = '"""\nExample: /home/someone/Projects\n"""\nx = 1\n'
        said = _scanned(tmp_path, content)
        assert said == "No hardcoded absolute home paths found"

    def test_clean_file(self, tmp_path):
        content = "from pathlib import Path\nROOT = Path(__file__).parent\n"
        said = _scanned(tmp_path, content)
        assert said == "No hardcoded absolute home paths found"

    def test_generic_user_not_flagged(self, tmp_path):
        content = 'path = "/home/user/Projects/AIPass"\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L1: POSIX home path (")

    def test_multiple_violations_same_file(self, tmp_path):
        content = 'A = "/home/alice/foo"\nB = "/Users/bob/bar"\nC = "-home-charlie-baz"\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("3 hardcoded path(s): ")

    def test_line_numbers_correct(self, tmp_path):
        content = 'clean = 1\nbad = "/home/someone/x"\nalso_clean = 2\n'
        said = _scanned(tmp_path, content)
        assert said.startswith("1 hardcoded path(s): L2: ")


class TestCheckModule:
    """Tests for check_module entry point."""

    def test_clean_file_passes(self, tmp_path):
        f = tmp_path / "clean.py"
        f.write_text("from pathlib import Path\nROOT = Path(__file__).parent\n", encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["standard"] == "HARDCODED_PATH"

    def test_violation_fails(self, tmp_path):
        f = tmp_path / "bad.py"
        f.write_text('ROOT = "/home/someone/Projects/AIPass"\n', encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_bypass_whole_standard(self, tmp_path):
        f = tmp_path / "bypassed.py"
        f.write_text('ROOT = "/home/someone/Projects/AIPass"\n', encoding="utf-8")
        rules = [{"standard": "hardcoded_path", "file": "bypassed.py"}]
        result = hardcoded_path_check.check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True
        assert result["score"] == 100

    def test_bypass_specific_line(self, tmp_path):
        f = tmp_path / "partial.py"
        f.write_text('A = "/home/alice/ok"\nB = "/home/bob/also_ok"\n', encoding="utf-8")
        rules = [
            {"standard": "hardcoded_path", "file": "partial.py", "lines": [1, 2]},
        ]
        result = hardcoded_path_check.check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True

    def test_init_py_skipped(self, tmp_path):
        f = tmp_path / "__init__.py"
        f.write_text('X = "/home/someone/nope"\n', encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        assert result["passed"] is True
        assert "skipped" in result["checks"][0]["message"].lower()

    def test_nonexistent_file(self, tmp_path):
        result = hardcoded_path_check.check_module(str(tmp_path / "no_such_file.py"))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_non_python_skipped(self, tmp_path):
        f = tmp_path / "readme.md"
        f.write_text("/home/someone/whatever\n", encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        assert result["passed"] is True

    def test_violation_message_includes_line_info(self, tmp_path):
        f = tmp_path / "info.py"
        f.write_text('x = "/home/alice/stuff"\n', encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        msg = result["checks"][0]["message"]
        assert "L1" in msg
        assert "POSIX home path" in msg

    def test_more_than_three_violations_truncates(self, tmp_path):
        f = tmp_path / "many.py"
        lines = [f'v{i} = "/home/u{i}/x"\n' for i in range(5)]
        f.write_text("".join(lines), encoding="utf-8")
        result = hardcoded_path_check.check_module(str(f))
        msg = result["checks"][0]["message"]
        assert "and 2 more" in msg


class TestInDocstring:
    """Tests for docstring detection."""

    def test_single_line_docstring(self, tmp_path):
        """A one-line docstring opens no block: neither it nor the line after is inside."""
        lines = ['"""Docstring at /home/someone/a."""', 'x = "/home/someone/y"']
        said = _scanned(tmp_path, "\n".join(lines) + "\n")
        assert said.startswith("2 hardcoded path(s): L1: POSIX home path ("), said
        assert "L2: POSIX home path (" in said, said

    def test_multiline_docstring(self, tmp_path):
        lines = ['"""', "/home/someone/inside", '"""', "/home/someone/outside"]
        said = _scanned(tmp_path, "\n".join(lines) + "\n")
        assert said.startswith("1 hardcoded path(s): L4: POSIX home path (")

    def test_single_quote_docstring(self, tmp_path):
        lines = ["'''", "/home/someone/inside", "'''", "/home/someone/outside"]
        said = _scanned(tmp_path, "\n".join(lines) + "\n")
        assert said.startswith("1 hardcoded path(s): L4: POSIX home path (")


#
# Every test here names the defect or the contract it protects. What is pinned
# is what a plausible future edit could break, and the whole standard rests on
# two claims that a single careless line would undo:
#
#   * a cap is READ from its owner on every call, never copied into this tree
#     (the pins monkeypatch the OWNER's constant and watch the row move; a
#     `from ... import BRANCH_CHAR_BUDGET` binding would leave them red)
#   * a cap that cannot be read is an ERROR row, never a default and never a
#     silent pass (the defect trinity_check exists for, one layer up)
#
# Nothing below reads the live fleet. Every branch under test is written into
# tmp_path by the test that measures it, so no assertion moves when a README
# does.


def _branch(root, **files):
    """Write a throwaway branch tree and hand back its root.

    Keys are branch-relative paths; a value of None means "do not create it",
    which is how ABSENT is set up without a special case in the test body.
    """
    for rel, text in files.items():
        if text is None:
            continue
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


def _cells(result):
    """The fleet row's cells, keyed by column label."""
    return {cell["label"]: cell for cell in result["fleet_row"]["cells"]}


def _group(result, name):
    """One check dict by its group name."""
    return next(check for check in result["checks"] if check["name"] == name)


def _memory_config(root, **budgets):
    """A stand-in memory.config.json carrying only the file_budgets key.

    Written rather than mocked because the checker's contract is that it READS
    @memory's config: a mocked loader would prove only that a mock was called.
    """
    path = root / "memory.config.json"
    path.write_text(json.dumps({"entry_limits": {"file_budgets": budgets}}), encoding="utf-8")
    return path


class TestStartupBudgetCapsAreRead:
    """Each cap comes from its owner, on every call. Copy one and these go red."""

    def test_the_prompt_cap_moves_when_hooks_moves_it(self, monkeypatch, tmp_path):
        """@hooks owns BRANCH_CHAR_BUDGET; seedgo must never carry a copy of 9,000."""
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y" * 100})

        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 40)
        over = _cells(sb.check_branch(str(root)))["PROMPT"]
        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 500)
        under = _cells(sb.check_branch(str(root)))["PROMPT"]

        assert (over["cap"], over["state"]) == (40, "over")
        assert (under["cap"], under["state"]) == (500, "under")
        assert over["chars"] == under["chars"] == 100, "the file never changed; only the owner's cap did"

    def test_the_dashboard_cap_moves_when_prax_moves_it(self, monkeypatch, tmp_path):
        """@prax owns DASHBOARD_CHAR_BUDGET, exported from apps/modules/dashboard."""
        root = _branch(tmp_path / "b", **{"README.md": "x", "DASHBOARD.local.json": "{}" + " " * 98})

        monkeypatch.setattr(sb.prax_dashboard, "DASHBOARD_CHAR_BUDGET", 50)
        over = _cells(sb.check_branch(str(root)))["DASH"]
        monkeypatch.setattr(sb.prax_dashboard, "DASHBOARD_CHAR_BUDGET", 5000)
        under = _cells(sb.check_branch(str(root)))["DASH"]

        assert (over["cap"], over["state"]) == (50, "over")
        assert (under["cap"], under["state"]) == (5000, "under")

    def test_the_trinity_caps_move_when_memorys_config_moves_them(self, monkeypatch, tmp_path):
        """@memory's memory.config.json owns the .trinity ceilings -- all three."""
        root = _branch(tmp_path / "b", **{"README.md": "x", ".trinity/local.json": "{}" + " " * 98})
        config = _memory_config(tmp_path, **{"local.json": {"max_chars": 40}})
        monkeypatch.setattr(sb, "memory_config_path", lambda: config)

        cell = _cells(sb.check_branch(str(root)))["LOCAL"]

        assert (cell["cap"], cell["chars"], cell["state"]) == (40, 100, "over")

    def test_the_readme_cap_lives_in_the_packs_own_config(self, monkeypatch, tmp_path):
        """seedgo owns 10,000, so seedgo keeps it in pack.json, not in Python."""
        manifest = tmp_path / "pack.json"
        manifest.write_text(json.dumps({"caps": {"README.md": {"max_chars": 5}}}), encoding="utf-8")
        root = _branch(tmp_path / "b", **{"README.md": "0123456789"})
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: manifest)

        cell = _cells(sb.check_branch(str(root)))["README"]

        assert (cell["cap"], cell["chars"], cell["state"]) == (5, 10, "over")

    def test_the_shipped_manifest_carries_the_owners_ruled_ten_thousand(self):
        """The one live-tree pin: the ruled number, where the ratchet will read it."""
        assert sb.readme_cap() == (10000, "")


class TestStartupBudgetFailsHonestly:
    """An unreadable owner is an ERROR row. Never a default, never a pass."""

    def test_an_unreadable_memory_config_is_an_error_not_a_pass(self, monkeypatch, tmp_path):
        """A broken config must not score; it must say who owns the number."""
        broken = tmp_path / "memory.config.json"
        broken.write_text("{ this is not json", encoding="utf-8")
        root = _branch(tmp_path / "b", **{"README.md": "x", ".trinity/local.json": "{}"})
        monkeypatch.setattr(sb, "memory_config_path", lambda: broken)

        result = sb.check_branch(str(root))
        trinity = _group(result, "Trinity files")

        assert trinity["passed"] is False
        assert trinity["score"] == 0, "an unmeasurable cap fails the group; it never passes it"
        assert "memory" in trinity["message"], "the error row must name the owner"
        assert "25,000" not in trinity["message"], "no remembered number may stand in for the config"
        assert _cells(result)["LOCAL"]["state"] == "error"

    def test_a_missing_file_budgets_key_is_an_error_not_a_pass(self, monkeypatch, tmp_path):
        """A parseable config with no budgets is the seed's trigger -- refuse it too."""
        empty = tmp_path / "memory.config.json"
        empty.write_text(json.dumps({"entry_limits": {}}), encoding="utf-8")
        root = _branch(tmp_path / "b", **{"README.md": "x", ".trinity/local.json": "{}"})
        monkeypatch.setattr(sb, "memory_config_path", lambda: empty)

        trinity = _group(sb.check_branch(str(root)), "Trinity files")

        assert trinity["score"] == 0
        assert "file_budgets" in trinity["message"]

    def test_an_unimportable_owner_module_is_an_error_row_naming_it(self, monkeypatch, tmp_path):
        """@hooks unimportable: the row says hooks, and the standard does not vanish."""
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y"})
        monkeypatch.setattr(sb, "hooks_grounding", None)
        monkeypatch.setattr(sb, "_HOOKS_IMPORT_ERROR", "ModuleNotFoundError: no aipass.hooks")

        result = sb.check_branch(str(root))
        prompt = _group(result, "Branch prompt")

        assert prompt["score"] == 0
        assert "hooks" in prompt["message"] and "9,000" not in prompt["message"]
        assert _cells(result)["PROMPT"]["state"] == "error"
        assert _cells(result)["PROMPT"]["cap"] is None, "an unknown cap is None, never a plausible number"

    def test_a_missing_cap_is_an_error_even_when_the_file_is_absent(self, monkeypatch, tmp_path):
        """'we do not know the limit' and 'there is no file' are different facts."""
        root = _branch(tmp_path / "b", **{"README.md": "x"})
        monkeypatch.setattr(sb, "prax_dashboard", None)
        monkeypatch.setattr(sb, "_PRAX_IMPORT_ERROR", "ImportError: boom")

        assert _cells(sb.check_branch(str(root)))["DASH"]["state"] == "error"


class TestStartupBudgetMeasurement:
    """Chars, absence, and the per-string cap no column can express."""

    def test_multibyte_characters_are_counted_as_characters_not_bytes(self, monkeypatch, tmp_path):
        """wc -m, never wc -c. The boardroom corrected this three times in one day."""
        text = "日" * 10  # 10 chars, 30 bytes in UTF-8
        root = _branch(tmp_path / "b", **{"README.md": text})
        manifest = tmp_path / "pack.json"
        manifest.write_text(json.dumps({"caps": {"README.md": {"max_chars": 20}}}), encoding="utf-8")
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: manifest)

        cell = _cells(sb.check_branch(str(root)))["README"]

        assert len(text.encode("utf-8")) == 30, "the fixture is only interesting while it is multi-byte"
        assert cell["chars"] == 10
        assert cell["state"] == "under", "30 bytes against a 20-char cap would have read OVER"

    def test_an_absent_file_is_absent_not_zero(self, tmp_path):
        """A branch with no dashboard yet has not scored zero -- it has not been measured."""
        root = _branch(tmp_path / "b", **{"README.md": "x"})

        result = sb.check_branch(str(root))
        dash_cell = _cells(result)["DASH"]

        assert dash_cell["state"] == "absent"
        assert dash_cell["chars"] is None, "absent must never be spelled as a number"
        assert _group(result, "Dashboard")["score"] is None, "an unmeasured group scores None, not 0 and not 100"
        assert _group(result, "Dashboard")["passed"] is True, "absence is not a violation"
        assert "absent" in _group(result, "Dashboard")["message"]

    def test_a_branch_with_none_of_the_six_files_is_not_applicable(self, monkeypatch, tmp_path):
        """Neither 0 nor 100 -- the third answer, as trinity_check rules it."""
        config = _memory_config(
            tmp_path,
            **{
                "local.json": {"max_chars": 25000},
                "observations.json": {"max_chars": 15000},
                "passport.json": {"max_chars": 6000, "max_string_chars": 600},
            },
        )
        monkeypatch.setattr(sb, "memory_config_path", lambda: config)
        root = _branch(tmp_path / "bare")
        root.mkdir(parents=True, exist_ok=True)

        result = sb.check_branch(str(root))

        assert result["not_applicable"] is True
        assert result["score"] is None and result["passed"] is None

    def test_an_oversized_string_in_a_small_passport_still_fails(self, monkeypatch, tmp_path):
        """@memory caps passport.json twice: 6,000 for the file, 600 per string."""
        passport = json.dumps({"identity": {"purpose": "p" * 700}})
        root = _branch(tmp_path / "b", **{"README.md": "x", ".trinity/passport.json": passport})
        config = _memory_config(tmp_path, **{"passport.json": {"max_chars": 6000, "max_string_chars": 600}})
        monkeypatch.setattr(sb, "memory_config_path", lambda: config)

        result = sb.check_branch(str(root))
        trinity = _group(result, "Trinity files")

        assert _cells(result)["PASSPORT"]["state"] == "under", "the FILE is well under its 6,000 budget"
        assert trinity["passed"] is False, "the oversized string must still fail the group"
        assert any("identity.purpose" in note for note in result["fleet_row"]["notes"])


class TestStartupBudgetContract:
    """The module surface branch_audit and the cache read off this checker."""

    def test_the_standard_is_advisory_and_the_audit_can_see_it(self):
        """ADVISORY keeps the row out of the gating average (branch_audit.py:638)."""
        checkers = branch_audit.discover_checkers(sb.pack_manifest_path().parent)

        assert sorted(checkers) == ["startup_budget"], "the pack runs alone -- that is why it is a pack"
        assert getattr(checkers["startup_budget"], "ADVISORY", False) is True
        assert getattr(checkers["startup_budget"], "AUDIT_SCOPE", "") == "branch_level"

    def test_an_over_cap_branch_still_reports_advisory_and_is_never_gated(self, tmp_path):
        """The row goes red and carries its own 'this gates nothing' flag."""
        manifest_cap, cap_error = sb.readme_cap()
        assert manifest_cap is not None, f"the shipped pack.json must publish a README cap: {cap_error}"
        root = _branch(tmp_path / "b", **{"README.md": "x" * (manifest_cap + 1)})

        result = sb.check_branch(str(root))

        assert result["advisory"] is True
        assert result["passed"] is False and result["score"] < 100

    def test_external_inputs_names_memorys_config_and_the_other_owners(self):
        """The cache watches the owners' files, or a moved cap re-scores nothing."""
        named = [path.as_posix() for path in sb.external_inputs()]

        assert any(p.endswith("memory/memory_json/custom_config/memory.config.json") for p in named), named
        assert any(p.endswith("hooks/apps/modules/grounding_content.py") for p in named), named
        assert any(p.endswith("prax/apps/handlers/dashboard/operations.py") for p in named), named
        assert any(p.endswith("prax/apps/modules/dashboard.py") for p in named), named

    def test_branch_inputs_covers_every_file_the_score_reads(self):
        """A measured file outside the declared globs is a permanently stale row."""
        from fnmatch import fnmatch

        for rel, _label in sb.MEASURED_FILES:
            assert any(fnmatch(rel, pattern) for pattern in sb.BRANCH_INPUTS), f"{rel} is scored but never watched"


#
# The advisory row next door gates nothing on purpose. This is the part that
# holds, so what is pinned here is what a red must be able to say and what it
# must refuse to do:
#
#   * a gated file over its cap turns CI red, and the line names FOUR things --
#     the file, the measured size, the cap, and the owning branch. A red that
#     does not name the owner costs a seat a round trip.
#   * every cap is still READ from its owner on every run. The pins below move
#     the OWNER's number and watch the verdict flip; a constant copied into the
#     gate leaves them red.
#   * a cap that cannot be read is a RED naming the owner, never a remembered
#     default. A gate that substitutes last week's number has stopped
#     measuring and has not said so.
#   * `<=` passes. A branch that diets to exactly its cap is not failed by one.
#   * .trinity/, the dashboard and docs/ are NOT gated -- the first two are
#     gitignored and a CI checkout holds neither, so a gate on them would
#     measure nothing on every run and pass by accident forever.
#
# Nothing here reads the live fleet except the two pins that say so in their
# names. Every branch under test is written into tmp_path.


def _gate(root, name="probe"):
    """Run the gate over one throwaway branch and hand back the whole verdict."""
    return ratchet.run([{"name": name, "path": str(root)}])


def _gated_row(result, rel):
    """The row for one gated file."""
    return next(row for row in result["rows"] if row["rel"] == rel)


def _pack_manifest(root, cap):
    """A stand-in for this pack's pack.json carrying only the README cap."""
    path = root / "pack.json"
    path.write_text(json.dumps({"caps": {"README.md": {"max_chars": cap}}}), encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# The name ratchet shares these classes: a count held at a baseline instead of a size held at a cap. The
# owner's name is never spelled here: fixtures read it off the module, so these tests cannot become a hit.

NAME = names.OWNER_NAME


def _names(root, files, baseline=None):
    """Run the name ratchet over a throwaway tree, the file list handed in.

    ``files`` maps repo-relative path -> text. Handing the list in stands for
    ``git ls-files``; the one test that proves "tracked" means git builds a
    real repository instead.
    """
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    base = root / "baseline.json"
    base.write_text(json.dumps({"files": baseline or {}}), encoding="utf-8")
    return names.run(root, files=list(files), baseline_path=base)


def _said(result):
    """Everything the name ratchet would put in a CI log, as one string."""
    return "\n".join(result["report"] + result["failure_lines"])


class TestRatchetRed:
    """What CI prints when a gated file grows past its cap."""

    def test_an_over_cap_readme_is_red_and_names_file_measured_cap_and_owner(self, monkeypatch, tmp_path):
        """The four things a red must say, in one greppable line."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 40))
        root = _branch(tmp_path / "b", **{"README.md": "x" * 51})

        result = _gate(root, name="probe")
        line = result["failure_lines"][0]

        assert result["passed"] is False
        assert _gated_row(result, "README.md")["state"] == "over"
        assert "README.md" in line, "the file"
        assert "51 chars" in line, "the measurement"
        assert "40 chars" in line, "the cap"
        assert "@seedgo" in line, "the owner -- a red without it costs a round trip"
        assert "OVER by 11" in line

    def test_an_over_cap_branch_prompt_is_red_and_names_hooks(self, monkeypatch, tmp_path):
        """The prompt is gated too, and its cap belongs to another branch."""
        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 10)
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y" * 30})

        result = _gate(root)
        line = next(one for one in result["failure_lines"] if "aipass_local_prompt" in one)

        assert result["passed"] is False
        assert _gated_row(result, ".aipass/aipass_local_prompt.md")["state"] == "over"
        assert "30 chars" in line and "10 chars" in line and "@hooks" in line

    def test_a_file_that_cannot_be_decoded_is_red_not_skipped(self, monkeypatch, tmp_path):
        """An unreadable README is not a small README."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        root = tmp_path / "b"
        root.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xff")

        result = _gate(root)

        assert result["passed"] is False
        assert _gated_row(result, "README.md")["state"] == "error"
        assert "cannot be read" in result["failure_lines"][0]

    def test_a_new_line_naming_the_owner_is_red_and_the_log_never_names_him(self, tmp_path):
        """The name ratchet's red says where, and masks what."""
        result = _names(tmp_path, {"src/aipass/probe/README.md": f"intro\nAsk {NAME.title()} first.\n"})
        said = _said(result)

        assert result["passed"] is False
        assert "src/aipass/probe/README.md" in said, "the file"
        assert "L2" in said, "the line"
        assert names.MASK in said, "what was there, masked"
        assert "NEW by 1" in said
        assert NAME not in said.lower(), "the log carried the name it guards"

    def test_the_name_is_matched_in_any_case_and_inside_an_identifier(self, tmp_path):
        """Substring, case-insensitive: an identifier ships the name as surely as prose."""
        text = f"def test_the_{NAME}_ruling():\n    pass\nWHO = '{NAME.upper()}'\n"

        result = _names(tmp_path, {"src/aipass/probe/tests/test_x.py": text})

        assert result["counts"] == {"src/aipass/probe/tests/test_x.py": {names.RULE_NAME: 2}}
        assert result["passed"] is False

    def test_a_real_home_path_in_a_prompt_or_a_content_file_is_red(self, tmp_path):
        """Three OS spellings of a person's home, in the two file kinds that render."""
        files = {
            ".aipass/aipass_local_prompt.md": "Logs live in /home/alice/logs\n",
            "src/aipass/probe/apps/handlers/x_content.py": 'WHERE = "C:\\\\Users\\\\bob\\\\AppData"\n',
            "docs/setup.md": "open /Users/carol/Desktop and C:\\Users\\dave\\x\n",
        }

        result = _names(tmp_path, files)

        assert result["passed"] is False
        assert {rel: rules.get(names.RULE_HOME) for rel, rules in result["counts"].items()} == {
            ".aipass/aipass_local_prompt.md": 1,
            "src/aipass/probe/apps/handlers/x_content.py": 1,
            "docs/setup.md": 1,
        }

    def test_a_tracked_path_carrying_the_name_is_red(self, tmp_path):
        """A file NAME ships too, and it is not something a baseline can hold."""
        rel = f"docs/{NAME}_notes.md"

        result = _names(tmp_path, {rel: "nothing in here\n"})

        assert result["passed"] is False
        assert result["hits"][0].line == 0
        assert NAME not in _said(result).lower()


class TestRatchetBoundary:
    """`<=` passes. The boundary is the cap itself, and it is said out loud."""

    def test_a_file_exactly_at_its_cap_passes(self, monkeypatch, tmp_path):
        """A branch that diets to precisely 10,000 is not failed by zero chars."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 40))
        root = _branch(tmp_path / "b", **{"README.md": "x" * 40})

        result = _gate(root)

        assert result["passed"] is True
        assert _gated_row(result, "README.md")["state"] == "under"
        assert result["failure_lines"] == []
        assert "AT its cap passes" in ratchet.TITLE, "the boundary is printed, not left to be guessed"

    def test_one_char_over_the_cap_is_red(self, monkeypatch, tmp_path):
        """OVER is strictly greater -- the other side of the same line."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 40))
        root = _branch(tmp_path / "b", **{"README.md": "x" * 41})

        assert _gate(root)["passed"] is False

    def test_chars_not_bytes_decides_the_boundary(self, monkeypatch, tmp_path):
        """wc -m, never wc -c -- the unit the boardroom corrected three times."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 20))
        root = _branch(tmp_path / "b", **{"README.md": "日" * 10})

        row = _gated_row(_gate(root), "README.md")

        assert row["chars"] == 10 and row["state"] == "under"

    def test_a_file_at_its_baseline_passes_and_one_more_line_is_red(self, tmp_path):
        """The name ratchet's boundary is the baseline count itself, as with a cap."""
        rel = "src/aipass/probe/tests/test_x.py"
        two = f"a = '{NAME}'\nb = '{NAME}'\n"

        held = _names(tmp_path / "held", {rel: two}, baseline={rel: {names.RULE_NAME: 2}})
        grown = _names(tmp_path / "grown", {rel: two + f"c = '{NAME}'\n"}, baseline={rel: {names.RULE_NAME: 2}})

        assert held["passed"] is True, _said(held)
        assert grown["passed"] is False
        assert "3 name line(s), baseline 2" in _said(grown)

    def test_a_home_path_outside_markdown_and_content_files_is_not_this_rule(self, tmp_path):
        """The home-path rule reads what renders; code is hardcoded_path's lane."""
        result = _names(tmp_path, {"src/aipass/probe/apps/handlers/x.py": 'P = "/home/alice/x"\n'})

        assert result["passed"] is True, _said(result)
        assert result["hits"] == []

    def test_a_home_path_with_no_trailing_slash_still_names_someone(self, tmp_path):
        """``/home/alice`` at the end of a table cell names alice as surely as ``/home/alice/``."""
        result = _names(tmp_path, {"docs/map.md": "| log dir | Hardcoded /home/alice in glob |\n"})

        assert result["counts"] == {"docs/map.md": {names.RULE_HOME: 1}}

    def test_a_placeholder_home_segment_is_not_a_person(self, tmp_path):
        """Docs need examples. ``/home/user/`` names nobody, so it passes."""
        text = (
            "/home/user/project and /home/<you>/x and /Users/me/Desktop\n"
            "C:\\Users\\someone\\x and /home/$USER/x and /home/runner/work/x\n"
            "C:\\Users\\RUNNER~1\\AppData and /home/{name}/x and /Users/username/x\n"
            "everything lives under /home/user.\n"
        )

        result = _names(tmp_path, {"docs/setup.md": text})

        assert result["passed"] is True, _said(result)


class TestRatchetReadsTheOwnersCap:
    """Move the owner's number and the verdict moves. Copy it and these go red."""

    def test_the_prompt_verdict_flips_when_hooks_moves_its_constant(self, monkeypatch, tmp_path):
        """The gate holds @hooks' number, not a remembered 9,000."""
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y" * 100})

        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 50)
        red = _gate(root)
        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 500)
        green = _gate(root)

        assert red["passed"] is False and green["passed"] is True
        assert _gated_row(red, ".aipass/aipass_local_prompt.md")["cap"] == 50
        assert _gated_row(green, ".aipass/aipass_local_prompt.md")["cap"] == 500
        assert _gated_row(red, ".aipass/aipass_local_prompt.md")["chars"] == 100, "only the owner's cap moved"

    def test_the_readme_verdict_flips_when_the_manifest_moves(self, monkeypatch, tmp_path):
        """seedgo's own cap lives in pack.json so a non-Python tool can move it."""
        root = _branch(tmp_path / "b", **{"README.md": "x" * 100})

        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 50))
        red = _gate(root)
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 500))
        green = _gate(root)

        assert red["passed"] is False and green["passed"] is True
        assert _gated_row(red, "README.md")["cap"] == 50
        assert _gated_row(green, "README.md")["cap"] == 500
        assert _gated_row(red, "README.md")["chars"] == 100, "only the manifest moved"

    def test_the_cap_reader_is_looked_up_by_name_at_measurement_time(self):
        """Stored as a NAME, fetched with getattr -- never bound at import."""
        for gated in ratchet.GATED_FILES:
            assert isinstance(gated.cap_reader, str), "a bound function is a copy taken at import"
            assert callable(getattr(sb, gated.cap_reader)), f"{gated.cap_reader} must resolve on the checker"

    def test_no_cap_number_is_written_into_the_gate(self):
        """The gate carries paths and owner names. Never an integer cap."""
        import ast

        source = ratchet.__file__
        with open(source, encoding="utf-8") as handle:
            tree = ast.parse(handle.read())
        literals = {
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
        }

        assert literals.isdisjoint({10000, 9000, 6000, 15000, 25000, 600}), (
            f"a cap was copied into the gate: {literals}"
        )


class TestRatchetFailsHonestly:
    """An unreadable cap is a red naming the owner. Never a pass, never a default."""

    def test_an_unreadable_manifest_is_red_and_names_seedgo(self, monkeypatch, tmp_path):
        """seedgo cannot read its own number: say so, do not remember one."""
        broken = tmp_path / "pack.json"
        broken.write_text("{ this manifest no longer parses", encoding="utf-8")
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: broken)
        root = _branch(tmp_path / "b", **{"README.md": "x"})

        result = _gate(root)
        line = result["failure_lines"][0]

        assert result["passed"] is False, "an unmeasurable gate is a failing gate"
        assert _gated_row(result, "README.md")["state"] == "error"
        assert _gated_row(result, "README.md")["cap"] is None, "an unknown cap is None, never a plausible number"
        assert "@seedgo" in line and "UNREADABLE" in line
        assert "10,000" not in line and "10000" not in line, "no remembered number may stand in for the config"

    def test_an_unimportable_owner_is_red_and_names_hooks(self, monkeypatch, tmp_path):
        """@hooks gone: the prompt row says hooks, and it does not pass."""
        monkeypatch.setattr(sb, "hooks_grounding", None)
        monkeypatch.setattr(sb, "_HOOKS_IMPORT_ERROR", "ModuleNotFoundError: no aipass.hooks")
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y"})

        result = _gate(root)
        line = next(one for one in result["failure_lines"] if "aipass_local_prompt" in one)

        assert result["passed"] is False
        assert "@hooks" in line and "9,000" not in line and "9000" not in line

    def test_an_unreadable_baseline_is_red_not_an_empty_one(self, tmp_path):
        """A baseline that will not parse is not "nothing baselined"."""
        base = tmp_path / "baseline.json"
        base.write_text("{not json", encoding="utf-8")
        (tmp_path / "clean.md").write_text("nothing here\n", encoding="utf-8")

        result = names.run(tmp_path, files=["clean.md"], baseline_path=base)

        assert result["passed"] is False
        assert "baseline.json" in _said(result)

    def test_a_tree_git_cannot_list_is_red_not_clean(self, monkeypatch, tmp_path):
        """No file list is not a clean tree. "Tracked" is git's answer or nothing."""

        def no_git(*args, **kwargs):
            raise FileNotFoundError("git")

        monkeypatch.setattr(names.subprocess, "run", no_git)

        result = names.run(tmp_path, baseline_path=names.BASELINE_PATH)

        assert result["passed"] is False
        assert "git ls-files" in _said(result)

    def test_a_directory_that_is_no_checkout_is_red_not_empty(self, tmp_path):
        """git runs, refuses (not a repository), prints nothing on stdout."""
        import shutil

        if shutil.which("git") is None:
            pytest.skip("git is not on PATH")

        result = names.run(tmp_path, baseline_path=names.BASELINE_PATH)

        assert result["passed"] is False
        assert "git ls-files exited" in _said(result)

    def test_a_tracked_file_that_cannot_be_opened_is_red(self, monkeypatch, tmp_path):
        """A file the ratchet could not read is a file it did not check."""
        real = names.Path.read_bytes

        def locked(self):
            if self.name == "locked.md":
                raise PermissionError("locked")
            return real(self)

        monkeypatch.setattr(names.Path, "read_bytes", locked)

        result = _names(tmp_path, {"locked.md": "fine\n", "open.md": "fine\n"})

        assert result["passed"] is False
        assert "locked.md cannot be read" in _said(result)
        assert result["tally"]["read"] == 1

    def test_an_unreadable_cap_is_red_even_when_the_file_is_absent(self, monkeypatch, tmp_path):
        """'We do not know the limit' and 'there is no file' are different facts."""
        monkeypatch.setattr(sb, "hooks_grounding", None)
        monkeypatch.setattr(sb, "_HOOKS_IMPORT_ERROR", "ImportError: boom")
        root = _branch(tmp_path / "b", **{"README.md": "x"})

        assert _gated_row(_gate(root), ".aipass/aipass_local_prompt.md")["state"] == "error"

    def test_an_absent_gated_file_is_not_a_failure(self, monkeypatch, tmp_path):
        """A missing README is readme_check's red, not a second differently-worded one."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        root = tmp_path / "bare"
        root.mkdir(parents=True, exist_ok=True)

        result = _gate(root)

        assert result["passed"] is True
        assert {row["state"] for row in result["rows"]} == {"absent"}
        assert all(row["chars"] is None for row in result["rows"]), "absent is never spelled as a number"


class TestRatchetScope:
    """Two files, both tracked in git. What is left out, and why."""

    def test_trinity_and_the_dashboard_and_docs_are_not_gated(self, monkeypatch, tmp_path):
        """Gitignored files cannot be gated by a job that never sees them."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        huge = "z" * 200000
        root = _branch(
            tmp_path / "b",
            **{
                "README.md": "x",
                ".trinity/local.json": huge,
                ".trinity/observations.json": huge,
                ".trinity/passport.json": huge,
                "DASHBOARD.local.json": huge,
                "docs/research.md": huge,
            },
        )

        result = _gate(root)

        assert result["passed"] is True, "none of those five files is gated"
        assert sorted(row["rel"] for row in result["rows"]) == [".aipass/aipass_local_prompt.md", "README.md"]

    def test_the_gated_paths_come_from_the_checker_not_a_second_spelling(self):
        """One spelling of each path, or the gate and the table hold different files."""
        measured = {rel for rel, _label in sb.MEASURED_FILES}

        for gated in ratchet.GATED_FILES:
            assert gated.rel in measured, f"{gated.rel} is gated but the advisory row never measures it"
        assert {gated.rel for gated in ratchet.GATED_FILES} == {sb.README_REL, sb.PROMPT_REL}

    def test_the_states_match_the_advisory_checkers_vocabulary(self, monkeypatch, tmp_path):
        """One table vocabulary across both rules, or two readers of one report."""
        manifest = tmp_path / "pack.json"
        manifest.write_text(json.dumps({"caps": {"README.md": {"max_chars": 5}}}), encoding="utf-8")
        config = _memory_config(tmp_path, **{"local.json": {}})
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: manifest)
        monkeypatch.setattr(sb, "memory_config_path", lambda: config)
        root = _branch(tmp_path / "b", **{"README.md": "0123456789", ".aipass/aipass_local_prompt.md": "y"})

        cells = _cells(sb.check_branch(str(root)))

        assert (cells["PROMPT"]["state"], cells["README"]["state"]) == (ratchet.STATE_UNDER, ratchet.STATE_OVER)
        assert (cells["DASH"]["state"], cells["LOCAL"]["state"]) == (ratchet.STATE_ABSENT, ratchet.STATE_ERROR)
        assert ratchet.FAILING_STATES == (ratchet.STATE_OVER, ratchet.STATE_ERROR), "absent never fails the gate"

    def test_the_owners_history_and_open_calls_are_never_opened(self, tmp_path):
        """Every exemption in the brief, each at a path that really takes it."""
        exempt = [
            ".claude/CLAUDE.md",
            "CHANGELOG.md",
            "src/aipass/flow/CHANGELOG.md",
            "src/aipass/flow/docs/DPLAN-0350_names.md",
            ".claude/hooks/engine.jsonl",
            ".claude/hooks/engine_test.log",
            ".claude/settings.json",
            "src/aipass/seedgo/tests/test_checkers_batch10.py",
            "src/aipass/skills/tools/suspend/deep/run.py",
        ]

        result = _names(tmp_path, {rel: f"{NAME}\n" for rel in exempt})

        assert result["passed"] is True, _said(result)
        assert result["tally"]["exempt"] == len(exempt)
        assert result["hits"] == []

    def test_an_exemption_is_that_file_not_its_family(self, tmp_path):
        """A near miss of an exempt path is an ordinary file and is read."""
        near = [
            "CLAUDE.md",
            "src/aipass/probe/.claude/settings.json",
            "src/aipass/seedgo/tests/test_checkers_batch11.py",
            "src/aipass/skills/tools/suspended.md",
            "docs/PLAN.md",
            "docs/CHANGELOG.md.txt",
        ]

        result = _names(tmp_path, {rel: f"{NAME}\n" for rel in near})

        assert sorted(result["counts"]) == sorted(near)

    def test_the_pattern_is_the_owners_name_by_a_digest_the_module_does_not_hold(self):
        """An oracle the module does not control: every other case reads the name
        off the module, so a wrong name would agree with itself and pass them all."""
        digest = hashlib.sha256(names.OWNER_NAME.encode("utf-8")).hexdigest()

        assert digest == "23ddda4810068cc44360dffd31b6c5a9ad13fb9e6a69c9354a5d1b07f1b9843f"

    def test_every_exemption_is_named_in_the_checks_doc(self):
        """The brief: the exemptions are built in AND named in the check's doc."""
        for pattern in names.EXEMPT_PATHS + names.EXEMPT_NAMES:
            assert pattern in (names.__doc__ or ""), f"{pattern} is exempt but the doc never says so"

    def test_an_untracked_file_is_never_read(self, tmp_path):
        """Tracked means ``git ls-files``: scratch that does not ship is not the ratchet's."""
        import shutil
        import subprocess

        if shutil.which("git") is None:
            pytest.skip("git is not on PATH")
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True, timeout=60)
        (tmp_path / "shipped.md").write_text(f"{NAME}\n", encoding="utf-8")
        (tmp_path / "scratch.md").write_text(f"{NAME}\n", encoding="utf-8")
        subprocess.run(["git", "-C", str(tmp_path), "add", "shipped.md"], check=True, timeout=60)
        base = tmp_path / "baseline.json"
        base.write_text(json.dumps({"files": {}}), encoding="utf-8")

        result = names.run(tmp_path, baseline_path=base)

        assert list(result["counts"]) == ["shipped.md"]


class TestRatchetFleetWalk:
    """The branch list: the audit's rule, from whatever root the caller names."""

    def test_a_directory_is_a_branch_when_it_has_apps(self, tmp_path):
        """The same rule .github/scripts/seedgo_audit.py applies, so one fleet."""
        fleet = tmp_path / "src" / "aipass"
        for name in ("alpha", "bravo"):
            (fleet / name / "apps").mkdir(parents=True)
        (fleet / "not_a_branch").mkdir(parents=True)
        (fleet / "loose.py").parent.mkdir(parents=True, exist_ok=True)
        (fleet / "loose.py").write_text("x", encoding="utf-8")

        found = ratchet.discover_branches(tmp_path)

        assert [branch["name"] for branch in found] == ["alpha", "bravo"]

    def test_the_paths_stay_relative_to_the_root_it_was_given(self, tmp_path):
        """No absolute path is invented, so CI logs read repo-relative."""
        (tmp_path / "src" / "aipass" / "alpha" / "apps").mkdir(parents=True)

        from pathlib import Path as _Path

        relative = ratchet.discover_branches(_Path("."))
        assert all(not _Path(branch["path"]).is_absolute() for branch in relative), relative

    def test_a_root_with_no_fleet_yields_no_branches_rather_than_raising(self, tmp_path):
        """A gate that crashes on an odd cwd cannot report that anything is wrong."""
        assert ratchet.discover_branches(tmp_path / "nowhere") == []

    def test_the_live_fleet_is_under_every_gated_cap(self):
        """The one live-tree pin: the state the ratchet was dropped on."""
        from pathlib import Path as _Path

        repo_root = _Path(__file__).resolve().parents[4]
        result = ratchet.run(ratchet.discover_branches(repo_root))

        assert len(result["rows"]) >= 2, "the walk found no branches -- the pin would be vacuous"
        assert result["passed"] is True, "\n".join(result["failure_lines"])


class TestRatchetReport:
    """What the job prints when nothing is wrong -- which is most runs."""

    def test_every_branch_is_printed_not_only_the_failing_ones(self, monkeypatch, tmp_path):
        """A gate whose log only appears on red hides how close a branch is running."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        alpha = _branch(tmp_path / "alpha", **{"README.md": "x" * 10})
        bravo = _branch(tmp_path / "bravo", **{"README.md": "y" * 20})

        report = ratchet.run([{"name": "alpha", "path": str(alpha)}, {"name": "bravo", "path": str(bravo)}])["report"]

        assert any("alpha" in line and "10/10,000" in line for line in report), report
        assert any("bravo" in line and "20/10,000" in line for line in report), report
        assert report[-1].startswith("  2 branch(es), 4 gated file(s)")
        assert "0 over cap, 0 unmeasurable" in report[-1]

    def test_the_gate_never_prints_it_returns_lines(self, capsys, monkeypatch, tmp_path):
        """A handler that writes to stdout cannot be called from a test or a dashboard."""
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 1))
        root = _branch(tmp_path / "b", **{"README.md": "x" * 50})

        _gate(root)

        assert capsys.readouterr().out == "", "the gate printed instead of returning"

    def test_a_loose_baseline_is_reported_with_the_number_to_write(self, tmp_path):
        """A ratchet only turns one way when somebody tightens it."""
        rel = "src/aipass/probe/tests/test_x.py"

        result = _names(tmp_path, {rel: f"a = '{NAME}'\n"}, baseline={rel: {names.RULE_NAME: 3}})

        assert result["passed"] is True
        assert result["loose"] == [{"rel": rel, "rule": names.RULE_NAME, "count": 1, "allowed": 3}]
        assert any(rel in line and "write 1" in line for line in result["report"])

    def test_the_name_ratchet_never_prints_and_never_names_the_owner_itself(self, capsys):
        """The checker is the one file that must know the name -- and is not a hit."""
        module = names.__file__
        with open(module, encoding="utf-8") as handle:
            source = handle.read()
        shipped = names.BASELINE_PATH.read_text(encoding="utf-8")

        baseline, reason = names.load_baseline(names.BASELINE_PATH)

        assert names.scan_text("name_ratchet.py", source) == []
        assert NAME not in shipped.lower()
        assert reason == "" and baseline, "the shipped baseline must load"
        assert capsys.readouterr().out == ""


class TestRouterAssertFires:
    """The two shapes the rule exists to convict."""

    def test_the_one_liner_form_is_convicted(self):
        """`assert handle_command(...) is True` and nothing else."""
        source = "def test_x():\n    assert handle_command('x', []) is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]

    def test_the_assign_then_assert_form_is_convicted(self):
        """`result = handle_command(...)` then `assert result is True`."""
        source = "def test_x():\n    result = handle_command('x', [])\n    assert result is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]

    def test_an_attribute_call_is_the_same_router(self):
        """`mod.handle_command(...)` is the same protocol as the bare name."""
        source = "def test_x():\n    assert mod.handle_command('x', []) is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]


class TestRouterAssertStaysSilent:
    """Every acquittal, each for a different reason."""

    def test_a_decline_is_a_whole_contract(self):
        """`is False` is never convicted — 117 fleet units depend on this."""
        source = "def test_x():\n    assert handle_command('not_mine', []) is False\n"
        assert router_assert.find_violations(source) == []

    def test_one_honest_assertion_acquits_the_unit(self):
        """A second assert means the test proves something the True does not."""
        source = "def test_x():\n    assert handle_command('x', []) is True\n    assert con.print.called\n"
        assert router_assert.find_violations(source) == []

    def test_a_mock_assert_call_is_an_oracle(self):
        """`assert_called_once_with` raises on its own; there is no `assert`."""
        source = (
            "def test_x():\n    assert handle_command('x', []) is True\n    con.print.assert_called_once_with('hi')\n"
        )
        assert router_assert.find_violations(source) == []

    def test_an_underscore_helper_is_an_oracle(self):
        """A module-local `_assert_*` helper carries the whole oracle."""
        source = (
            "def test_x():\n    assert handle_command('x', []) is True\n    _assert_nothing_happened(stub, 'init -h')\n"
        )
        assert router_assert.find_violations(source) == []

    def test_pytest_raises_is_an_oracle(self):
        """A refusal proved by a context manager needs no second assert."""
        source = (
            "def test_x():\n"
            "    with pytest.raises(CommandRefused):\n"
            "        handle_command('x', ['bogus'])\n"
            "    assert handle_command('x', []) is True\n"
        )
        assert router_assert.find_violations(source) == []

    def test_a_predicate_is_not_a_router(self):
        """`is_valid(...) is True` is a real claim: the True IS the behaviour."""
        source = "def test_x():\n    assert is_valid('abc') is True\n"
        assert router_assert.find_violations(source) == []

    def test_a_unit_with_no_assertions_is_not_this_rules_problem(self):
        """No assert at all is no_oracle's finding, not router_assert's."""
        assert router_assert.find_violations("def test_x():\n    handle_command('x', [])\n") == []


class TestRouterAssertLanes:
    """The per-file lane, the bypass door, and the unscored backlog."""

    def test_check_module_reports_the_owner_message(self, tmp_path):
        """The conviction carries the owner's sentence, not a bare count."""
        f = tmp_path / "test_thing.py"
        f.write_text("def test_x():\n    assert handle_command('x', []) is True\n", encoding="utf-8")

        result = router_assert.check_module(str(f))

        assert result["passed"] is False and result["score"] == 0
        assert "test_x:1" in result["checks"][0]["message"]
        assert "assert the effect" in result["checks"][0]["message"]

    def test_an_unparseable_file_is_not_judged_and_says_so(self, tmp_path):
        """A file that does not parse is named as not judged, never the clean "no test asserts"
        of a judged file."""
        f = tmp_path / "test_thing.py"
        f.write_text("def test_x(:\n    assert handle_command('x', []) is True\n", encoding="utf-8")

        result = router_assert.check_module(str(f))

        assert router_assert.find_violations(f.read_text(encoding="utf-8")) is None
        assert result["score"] == 100
        assert result["checks"][0]["message"] == (
            "Not judged: the file cannot be read or does not parse (ruff convicts that)"
        )

    def test_a_line_bypass_silences_one_unit_and_not_the_file(self, tmp_path):
        """The declared deviation is cheap; the silent one stays impossible."""
        f = tmp_path / "test_thing.py"
        f.write_text(
            "def test_one():\n    assert handle_command('x', []) is True\n"
            "\n"
            "def test_two():\n    assert handle_command('y', []) is True\n",
            encoding="utf-8",
        )
        rules = [{"standard": "router_assert", "file": "test_thing.py", "lines": [1]}]

        result = router_assert.check_module(str(f), bypass_rules=rules)

        assert result["passed"] is False
        assert "test_two:4" in result["checks"][0]["message"]
        assert "test_one" not in result["checks"][0]["message"]

    def test_the_standard_scores_nothing_because_it_declares_tests(self):
        """APPLIES_TO=tests keeps it out of the audit's apps/ corpus entirely."""
        assert router_assert.APPLIES_TO == applicability.TESTS


class TestOversizeTestFileMeasures:
    """What counts as a code line, and what is given back."""

    def test_payload_inside_a_multiline_string_is_not_code(self):
        """A fixture blob is data the assertions read, not lines to split."""
        source = 'FIXTURE = """\n' + "line\n" * 50 + '"""\nx = 1\n'

        code, total, payload = oversize.measure(source)

        assert (total, payload, code) == (53, 52, 1)

    def test_a_docstring_is_payload_too(self):
        """A size rule must never be a reason to delete the bug a test names."""
        source = 'def test_x():\n    """\n' + "    why this test exists\n" * 20 + '    """\n    assert True\n'

        code, _total, payload = oversize.measure(source)

        assert payload == 22
        assert code == 2

    def test_an_fstring_span_is_counted_once(self):
        """Nested constants inside one f-string must not double-count."""
        source = 'V = 1\nS = f"""\n{V}\nmiddle\n{V}\n"""\n'

        code, total, payload = oversize.measure(source)

        assert (total, payload, code) == (6, 5, 1)

    def test_an_unparseable_file_is_measured_whole(self):
        """Breaking the syntax must not be a way under the cap."""
        code, total, payload = oversize.measure("def test_x(:\n" + "x = 1\n" * 40)

        assert (total, payload, code) == (41, 0, 41)


class TestOversizeTestFileLanes:
    """The cap itself, the message, and the unscored backlog."""

    def test_the_cap_convicts_at_one_line_over_and_not_at_the_cap(self, tmp_path):
        """The boundary is `>`, not `>=`."""
        at_cap = tmp_path / "test_at.py"
        over = tmp_path / "test_over.py"
        at_cap.write_text("x = 1\n" * oversize.CODE_LINE_CAP, encoding="utf-8")
        over.write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8")

        assert oversize.check_module(str(at_cap))["passed"] is True
        assert oversize.check_module(str(over))["passed"] is False

    def test_the_conviction_names_the_payload_it_already_forgave(self, tmp_path):
        """An author at 10,524 lines needs to know 5,929 were already given back."""
        big = tmp_path / "test_big.py"
        big.write_text(
            'P = """\n' + "pad\n" * 100 + '"""\n' + "x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8"
        )

        message = oversize.check_module(str(big))["checks"][0]["message"]

        assert "102 of string payload already excluded" in message
        assert "split it along the unit under test" in message

    def test_the_message_sends_the_author_to_the_gate_not_around_it(self, tmp_path):
        """The cure needs new test files, which the hooks gate refuses."""
        big = tmp_path / "test_big.py"
        big.write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8")

        message = oversize.check_module(str(big))["checks"][0]["message"]

        assert "@devpulse" in message
        assert "moving tests is not adding them" in message.lower()

    def test_the_standard_scores_nothing_because_it_declares_tests(self):
        """APPLIES_TO=tests keeps it out of the audit's apps/ corpus entirely."""
        assert oversize.APPLIES_TO == applicability.TESTS


# Module scope, never inside a test (template item 8). Here and not at the top because two
# bypass rules pin this file's earlier lines by number; an import above them would move them.
import shutil
import subprocess

from aipass.seedgo.apps import seedgo as seedgo_entry
from aipass.seedgo.apps.handlers.aipass_standards import developer_home_check as home
from aipass.seedgo.apps.modules import checklist

# Every spelling of one person's home: POSIX, POSIX with no separator, macOS, and Windows
# with one backslash, the doubled backslashes source and JSON carry, a slash, lower case.
_HOME_SPELLINGS = (
    "/home/jdoe/",
    "/home/jdoe",
    "/Users/jdoe/",
    "C:\\Users\\jdoe\\",
    "C:\\\\Users\\\\jdoe\\\\",
    "C:/Users/jdoe/",
    "c:\\users\\jdoe\\",
)
_TEXT_KINDS = ("notes.md", "data.json", "mod.py", "ci.yml", "script")


def _home_said(tmp_path, name: str, content, rules=None) -> dict:
    """What the public check_module says about a file named *name* holding *content*."""
    sample = tmp_path / name
    if isinstance(content, bytes):
        sample.write_bytes(content)
    else:
        sample.write_text(content, encoding="utf-8")
    return home.check_module(str(sample), bypass_rules=rules)


class TestDeveloperHomeConvicts:
    """Every spelling, in every text kind, and in prose as in code."""

    @pytest.mark.parametrize("kind", _TEXT_KINDS)
    @pytest.mark.parametrize("spelling", _HOME_SPELLINGS)
    def test_each_spelling_convicts_in_each_text_kind(self, tmp_path, kind, spelling):
        expected = spelling.rstrip("/\\")

        result = _home_said(tmp_path, kind, f"first line\nkept in {spelling} for now\n")

        assert result["passed"] is False
        assert result["checks"][0]["message"] == f"1 developer home path(s): L2: {expected}"

    def test_a_home_in_a_comment_or_a_docstring_still_convicts(self, tmp_path):
        source = '"""Cached under /home/jdoe/.cache."""\n# see /Users/jdoe/notes\nX = 1\n'

        message = _home_said(tmp_path, "mod.py", source)["checks"][0]["message"]

        assert message == "2 developer home path(s): L1: /home/jdoe; L2: /Users/jdoe"


class TestDeveloperHomeAcquits:
    """The segments that name nobody, the shapes that are not homes, the files it declines."""

    @pytest.mark.parametrize(
        "line",
        [
            "/home/user/x",
            "/home/someone/x",
            "/Users/carol/x",
            "/home/<user>/x",
            "/home/<home>/x",
            "/home/{name}/x",
            "/home/$USER/x",
            "C:\\Users\\%USERNAME%\\x",
            "/home/runner/work",
            "/home/j/x",
            "it lives under /home/user.",
            "/tmp/pytest-of-jdoe/pytest-0/x",
            "https://example.com/home/jdoe/x",
        ],
    )
    def test_a_segment_naming_nobody_passes(self, tmp_path, line):
        result = _home_said(tmp_path, "notes.md", f"{line}\n")

        assert result["passed"] is True
        assert result["checks"][0]["message"] == "No developer home paths found"

    @pytest.mark.parametrize("name, content", [("pic.png", "/home/jdoe/\n"), ("notes.md", b"/home/jdoe/\0\n")])
    def test_a_non_text_kind_or_a_nul_byte_is_declined_unread(self, tmp_path, name, content):
        result = _home_said(tmp_path, name, content)

        assert result["passed"] is True
        assert result["checks"][0]["declined"] is True

    def test_a_line_bypass_acquits_that_line_only(self, tmp_path):
        rules = [{"file": "notes.md", "standard": "developer_home", "lines": [1], "reason": "fixture"}]

        result = _home_said(tmp_path, "notes.md", "/home/jdoe/a\nok\n/home/jdoe/b\n", rules)

        assert result["checks"][0]["message"] == "1 developer home path(s): L3: /home/jdoe"

    def test_a_whole_file_bypass_acquits_the_file(self, tmp_path):
        rules = [{"file": "notes.md", "standard": "developer_home", "reason": "fixture"}]

        result = _home_said(tmp_path, "notes.md", "/home/jdoe/a\n", rules)

        assert (result["passed"], result["checks"][0]["name"]) == (True, "Bypassed")

    def test_a_missing_file_fails(self, tmp_path):
        assert home.check_module(str(tmp_path / "gone.md"))["passed"] is False


def _tree(root, files: dict) -> list:
    """Write *files* (rel -> text) under *root*; the rel list a caller hands the runner."""
    for rel, text in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
    return list(files)


class TestDeveloperHomeTree:
    """scan_tracked: the CI runner over a whole tracked tree."""

    def test_a_hit_is_red_and_named_rel_and_line(self, tmp_path):
        files = _tree(tmp_path, {"docs/a.md": "ok\nunder /home/jdoe/x\n", "pic.png": "/home/jdoe/\n", "b.txt": "ok\n"})

        result = home.scan_tracked(tmp_path, files=files)

        assert result["passed"] is False
        assert result["hits"] == [("docs/a.md", 2, "/home/jdoe")]
        assert result["files_read"] == 2

    def test_a_clean_tree_is_green(self, tmp_path):
        files = _tree(tmp_path, {"docs/a.md": "under /home/<user>/x\n", "b.txt": "ok\n"})

        result = home.scan_tracked(tmp_path, files=files)

        assert (result["passed"], result["hits"], result["errors"]) == (True, [], [])

    def test_the_owning_branchs_line_rule_acquits_that_line(self, tmp_path):
        branch = tmp_path / "src" / "aipass" / "alpha"
        rule = {"file": "docs/a.md", "standard": "developer_home", "lines": [1], "reason": "fixture"}
        _tree(branch, {".seedgo/bypass.json": json.dumps({"bypass": [rule]})})
        files = _tree(tmp_path, {"src/aipass/alpha/docs/a.md": "/home/jdoe/a\n/home/jdoe/b\n"})

        result = home.scan_tracked(tmp_path, files=files)

        assert result["hits"] == [("src/aipass/alpha/docs/a.md", 2, "/home/jdoe")]

    def test_a_listed_file_that_cannot_be_read_is_red(self, monkeypatch, tmp_path):
        files = _tree(tmp_path, {"locked.md": "ok\n", "open.md": "ok\n"})
        real = home.Path.read_bytes

        def locked(self):
            if self.name == "locked.md":
                raise PermissionError("locked")
            return real(self)

        monkeypatch.setattr(home.Path, "read_bytes", locked)

        result = home.scan_tracked(tmp_path, files=files)

        assert result["passed"] is False
        assert [error.split(":")[0] for error in result["errors"]] == ["locked.md"]

    def test_a_tree_git_cannot_list_is_red_not_clean(self, tmp_path):
        result = home.scan_tracked(tmp_path / "nowhere")

        assert result["passed"] is False
        assert result["hits"] == [] and len(result["errors"]) == 1


class TestDeveloperHomeChecklist:
    """The per-file lane now judges a text file for a TEXT_FILES checker."""

    def test_a_markdown_file_with_a_home_fails_under_developer_home(self, tmp_path, monkeypatch):
        monkeypatch.setattr(checklist, "is_throwaway_path", lambda path: str(tmp_path) not in str(path))
        page = tmp_path / "notes.md"
        page.write_text("kept in /home/jdoe/x\n", encoding="utf-8")

        results = checklist.run_checklist(str(page))

        assert results == [
            {"standard": "developer_home", "passed": False, "detail": "1 developer home path(s): L1: /home/jdoe"}
        ]

    def test_a_png_is_still_not_a_python_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(checklist, "is_throwaway_path", lambda path: str(tmp_path) not in str(path))
        picture = tmp_path / "pic.png"
        picture.write_text("/home/jdoe/\n", encoding="utf-8")

        results = checklist.run_checklist(str(picture))

        assert results == [{"standard": "(skip)", "passed": True, "detail": "Not a Python file"}]


def _git_repo(root, files: dict) -> None:
    """A real repository with *files* tracked: the verb asks git, as CI will."""
    if shutil.which("git") is None:
        pytest.skip("git is not on PATH")
    subprocess.run(["git", "init", "-q", str(root)], check=True, timeout=60)
    _tree(root, files)
    subprocess.run(["git", "-C", str(root), "add", *files], check=True, timeout=60)


class TestDeveloperHomeVerb:
    """`seedgo home-paths scan <root>`: the exit code is the CI gate."""

    def test_a_red_repo_exits_non_zero_and_prints_rel_line(self, tmp_path, monkeypatch, capsys):
        _git_repo(tmp_path, {"docs/red.md": "ok\nkept in /home/jdoe/x\n"})
        monkeypatch.setattr("sys.argv", ["seedgo", "home-paths", "scan", str(tmp_path)])

        code = seedgo_entry.main()

        out, _err = capsys.readouterr()
        assert code != 0
        assert "docs/red.md:2: /home/jdoe" in out

    def test_a_clean_repo_exits_zero(self, tmp_path, monkeypatch, capsys):
        _git_repo(tmp_path, {"docs/clean.md": "kept in /home/<user>/x\n"})
        monkeypatch.setattr("sys.argv", ["seedgo", "home-paths", "scan", str(tmp_path)])

        code = seedgo_entry.main()

        out, _err = capsys.readouterr()
        assert code == 0
        assert "0 developer home path(s)" in out

    def test_an_unknown_flag_is_refused_with_seven(self, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["seedgo", "home-paths", "scan", "--bogus"])

        code = seedgo_entry.main()

        _out, err = capsys.readouterr()
        assert code == 7
        assert "--bogus" in err


class TestTheDocstringTableIsReadOncePerFile:
    """_scan_file reads one table of docstring states per file (seedgo, fleet green leg 19)."""

    def test_the_line_after_a_one_line_docstring_is_still_scanned(self, tmp_path):
        said = _scanned(tmp_path, '"""One line."""\np = "/home/someone/a"\n')
        assert said.startswith("1 hardcoded path(s): L2: POSIX home path ("), said

    def test_a_block_closes_and_the_line_after_it_is_scanned(self, tmp_path):
        said = _scanned(tmp_path, '"""\n/home/someone/inside\n"""\np = "/home/someone/b"\n')
        assert said.startswith("1 hardcoded path(s): L4: POSIX home path ("), said
