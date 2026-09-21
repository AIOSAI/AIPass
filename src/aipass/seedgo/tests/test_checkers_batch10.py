"""Tests for seedgo checker handlers -- batch 10 (hardcoded_path, startup_budget, the two ratchets,
router_assert, oversize_test_file)."""

# =================== META ====================
# Name: test_checkers_batch10.py
# Description: Unit tests for hardcoded_path_check, startup_budget_check, the two ratchets, router_assert, oversize_test_file
# Version: 1.4.0
# Created: 2026-06-18
# Modified: 2026-09-20
# =============================================

import json

import pytest
from unittest.mock import MagicMock

# THE CONTEXT PACK IS IMPORTED AT MODULE SCOPE, AND THAT IS LOAD-BEARING.
# The autouse fixture below puts a MagicMock at `aipass.prax` in sys.modules for
# every test in this file. startup_budget_check reads its caps off @hooks' and
# @prax' REAL modules, so importing it inside a test body would bind those
# owners to mocks: every cap would come back a MagicMock, every row would read
# ERROR, and the tests that prove a cap is READ from its owner would be passing
# against nothing. Imported here, at collection time, the owners are real -- and
# a monkeypatch on one of their constants is then what moves a row.
from aipass.seedgo.apps.handlers.context_standards import startup_budget_check as sb  # noqa: E402
from aipass.seedgo.apps.handlers.context_standards import startup_ratchet as ratchet  # noqa: E402
from aipass.seedgo.apps.handlers.context_standards import name_ratchet as names  # noqa: E402
from aipass.seedgo.apps.handlers.aipass_standards import applicability  # noqa: E402
from aipass.seedgo.apps.handlers.aipass_standards import router_assert_check as router_assert  # noqa: E402
from aipass.seedgo.apps.handlers.aipass_standards import oversize_test_file_check as oversize  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    from aipass.seedgo.apps.handlers.bypass.utils import is_bypassed as real_is_bypassed

    bypass_pkg = MagicMock()
    bypass_utils = MagicMock()
    bypass_utils.is_bypassed = real_is_bypassed
    bypass_pkg.utils = bypass_utils
    bypass_ignore = MagicMock()
    bypass_ignore.get_template_ignore_patterns = MagicMock(return_value=[])
    bypass_pkg.ignore_handler = bypass_ignore
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass", bypass_pkg)
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.bypass.utils", bypass_utils)
    monkeypatch.setitem(
        sys.modules,
        "aipass.seedgo.apps.handlers.bypass.ignore_handler",
        bypass_ignore,
    )

    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ===========================================================================
# 1. _scan_file — core scanning logic
# ===========================================================================


class TestScanFile:
    """Tests for the _scan_file helper."""

    def test_posix_home_detected(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'ROOT = "/home/patrick/Projects/AIPass"\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "POSIX home path"

    def test_macos_home_detected(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'ROOT = "/Users/patrick/Projects/AIPass"\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "macOS home path"

    def test_windows_home_detected(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'ROOT = "C:\\\\Users\\\\patrick\\\\Projects"\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "Windows home path"

    def test_dash_encoded_posix_detected(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'dirs = ["-home-patrick-Projects-AIPass"]\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "dash-encoded POSIX home"

    def test_dash_encoded_macos_detected(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'dirs = ["-Users-patrick-Projects-AIPass"]\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "dash-encoded macOS home"

    def test_comment_skipped(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = '# ROOT = "/home/patrick/Projects/AIPass"\n'
        result = _scan_file(content)
        assert len(result) == 0

    def test_indented_comment_skipped(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = '    # path = "/home/patrick/test"\n'
        result = _scan_file(content)
        assert len(result) == 0

    def test_docstring_skipped(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = '"""\nExample: /home/patrick/Projects\n"""\nx = 1\n'
        result = _scan_file(content)
        assert len(result) == 0

    def test_clean_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = "from pathlib import Path\nROOT = Path(__file__).parent\n"
        result = _scan_file(content)
        assert len(result) == 0

    def test_generic_user_not_flagged(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'path = "/home/user/Projects/AIPass"\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][1] == "POSIX home path"

    def test_multiple_violations_same_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'A = "/home/alice/foo"\nB = "/Users/bob/bar"\nC = "-home-charlie-baz"\n'
        result = _scan_file(content)
        assert len(result) == 3

    def test_line_numbers_correct(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _scan_file

        content = 'clean = 1\nbad = "/home/patrick/x"\nalso_clean = 2\n'
        result = _scan_file(content)
        assert len(result) == 1
        assert result[0][0] == 2


# ===========================================================================
# 2. check_module — full integration via tmp files
# ===========================================================================


class TestCheckModule:
    """Tests for check_module entry point."""

    def test_clean_file_passes(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "clean.py"
        f.write_text("from pathlib import Path\nROOT = Path(__file__).parent\n")
        result = check_module(str(f))
        assert result["passed"] is True
        assert result["score"] == 100
        assert result["standard"] == "HARDCODED_PATH"

    def test_violation_fails(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "bad.py"
        f.write_text('ROOT = "/home/patrick/Projects/AIPass"\n')
        result = check_module(str(f))
        assert result["passed"] is False
        assert result["score"] == 0

    def test_bypass_whole_standard(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "bypassed.py"
        f.write_text('ROOT = "/home/patrick/Projects/AIPass"\n')
        rules = [{"standard": "hardcoded_path", "file": "bypassed.py"}]
        result = check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True
        assert result["score"] == 100

    def test_bypass_specific_line(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "partial.py"
        f.write_text('A = "/home/alice/ok"\nB = "/home/bob/also_ok"\n')
        rules = [
            {"standard": "hardcoded_path", "file": "partial.py", "lines": [1, 2]},
        ]
        result = check_module(str(f), bypass_rules=rules)
        assert result["passed"] is True

    def test_init_py_skipped(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "__init__.py"
        f.write_text('X = "/home/patrick/nope"\n')
        result = check_module(str(f))
        assert result["passed"] is True
        assert "skipped" in result["checks"][0]["message"].lower()

    def test_nonexistent_file(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        result = check_module("/no/such/file.py")
        assert result["passed"] is False
        assert result["score"] == 0

    def test_non_python_skipped(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "readme.md"
        f.write_text("/home/patrick/whatever\n")
        result = check_module(str(f))
        assert result["passed"] is True

    def test_violation_message_includes_line_info(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "info.py"
        f.write_text('x = "/home/alice/stuff"\n')
        result = check_module(str(f))
        msg = result["checks"][0]["message"]
        assert "L1" in msg
        assert "POSIX home path" in msg

    def test_more_than_three_violations_truncates(self, tmp_path):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import check_module

        f = tmp_path / "many.py"
        lines = [f'v{i} = "/home/u{i}/x"\n' for i in range(5)]
        f.write_text("".join(lines))
        result = check_module(str(f))
        msg = result["checks"][0]["message"]
        assert "and 2 more" in msg


# ===========================================================================
# 3. _in_docstring — edge cases
# ===========================================================================


class TestInDocstring:
    """Tests for docstring detection."""

    def test_single_line_docstring(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _in_docstring

        lines = ['"""This is a docstring."""', 'x = "/home/pat/y"']
        assert _in_docstring(lines, 0) is False
        assert _in_docstring(lines, 1) is False

    def test_multiline_docstring(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _in_docstring

        lines = ['"""', "/home/patrick/inside", '"""', "/home/patrick/outside"]
        assert _in_docstring(lines, 1) is True
        assert _in_docstring(lines, 3) is False

    def test_single_quote_docstring(self):
        from aipass.seedgo.apps.handlers.aipass_standards.hardcoded_path_check import _in_docstring

        lines = ["'''", "/home/patrick/inside", "'''", "/home/patrick/outside"]
        assert _in_docstring(lines, 1) is True
        assert _in_docstring(lines, 3) is False


# ===========================================================================
# 4. startup_budget_check -- the context pack (DPLAN-0347, boardroom thread 16)
# ===========================================================================
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
        """@hooks owns BRANCH_CHAR_BUDGET; seedgo must never carry a copy of 9,000.

        A `from aipass.hooks... import BRANCH_CHAR_BUDGET` at module scope, or a
        literal in this branch, would keep the row green against a number @hooks
        has since moved -- the exact failure "read, never copy" was ruled to end
        (DPLAN-0347, "Who owns each cap").
        """
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
        """seedgo owns 10,000, so seedgo keeps it in pack.json, not in Python.

        Phase 5's per-file CI ratchet has to read and move that number without
        importing Python; a constant in the checker would put the fleet's README
        cap somewhere no non-Python tool can reach.
        """
        manifest = tmp_path / "pack.json"
        manifest.write_text(json.dumps({"caps": {"README.md": {"max_chars": 5}}}), encoding="utf-8")
        root = _branch(tmp_path / "b", **{"README.md": "0123456789"})
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: manifest)

        cell = _cells(sb.check_branch(str(root)))["README"]

        assert (cell["cap"], cell["chars"], cell["state"]) == (5, 10, "over")

    def test_the_shipped_manifest_carries_the_owners_ruled_ten_thousand(self):
        """The one live-tree pin: the ruled number, where the ratchet will read it.

        The user ruled 10,000 on 2026-09-15 at 16:02. The room had proposed
        6,000 and FPLAN-0593 lines 179/221 still say 6,000; if anyone edits
        pack.json back to the stale number, this is what says so.
        """
        assert sb.readme_cap() == (10000, "")


class TestStartupBudgetFailsHonestly:
    """An unreadable owner is an ERROR row. Never a default, never a pass."""

    def test_an_unreadable_memory_config_is_an_error_not_a_pass(self, monkeypatch, tmp_path):
        """A broken config must not score; it must say who owns the number.

        @memory's own loader serves a REGENERATION SEED when the config
        publishes no budgets -- correct for @memory, fatal for an auditor, which
        would then print a confident green against numbers no config contains.
        """
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
        """@hooks unimportable: the row says hooks, and the standard does not vanish.

        Guarded imports are why: discover_checkers() drops a pack module that
        raises on exec, so a bare import would delete the whole standard from the
        audit and the fleet would read a table that simply stopped existing.
        """
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
        """wc -m, never wc -c. The boardroom corrected this three times in one day.

        st_size or an encode() would report 30 bytes for these 10 characters and
        a README would read three times its real length -- which is how a cap
        gets set against a number nobody can reproduce.
        """
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
        """A branch with no dashboard yet has not scored zero -- it has not been measured.

        .trinity/ and DASHBOARD.local.json are gitignored. Counting a missing
        file as 0 chars is a silent pass; counting it as a violation blames a
        branch for a fact about git.
        """
        root = _branch(tmp_path / "b", **{"README.md": "x"})

        result = sb.check_branch(str(root))
        dash_cell = _cells(result)["DASH"]

        assert dash_cell["state"] == "absent"
        assert dash_cell["chars"] is None, "absent must never be spelled as a number"
        assert _group(result, "Dashboard")["score"] is None, "an unmeasured group scores None, not 0 and not 100"
        assert _group(result, "Dashboard")["passed"] is True, "absence is not a violation"
        assert "absent" in _group(result, "Dashboard")["message"]

    def test_a_branch_with_none_of_the_six_files_is_not_applicable(self, monkeypatch, tmp_path):
        """Neither 0 nor 100 -- the third answer, as trinity_check rules it.

        Every cap is pointed at a known-good source first, so this test answers
        only its own question: an unreadable cap is an ERROR row by design, and
        that is pinned above rather than smuggled in here.
        """
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
        """@memory caps passport.json twice: 6,000 for the file, 600 per string.

        aipass' identity.purpose is 869 chars inside a 5,461-char passport. A
        rule that only measured the file would call that branch clean.
        """
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
        """ADVISORY keeps the row out of the gating average (branch_audit.py:638).

        Read through discover_checkers(), which is how branch_audit meets this
        module: a checker the pack loader cannot load is a standard that silently
        does not exist, and ADVISORY read off the loaded module is the exact
        expression `advisory_standards` uses.
        """
        from aipass.seedgo.apps.handlers.audit import branch_audit

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
        """The cache watches the owners' files, or a moved cap re-scores nothing.

        With only BRANCH_INPUTS declared, an owner editing its cap leaves every
        branch serving the row it cached against the OLD number until someone
        runs --full. That is what happened to trinity's rows on 2026-09-15, and
        it is why branch_audit grew _external_input_files().
        """
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


# ===========================================================================
# 5. startup_ratchet -- the per-file CI gate (DPLAN-0347 / FPLAN-0593 phase 5)
# ===========================================================================
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
# THE NAME RATCHET (DPLAN-0350) shares these classes: same shape of gate, a
# count held at a baseline instead of a size held at a cap. The owner's name
# is never spelled in this file -- every fixture reads it off the module, so
# the pattern lives in one place and these tests cannot become the next hit.
# ---------------------------------------------------------------------------

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
        """The four things a red must say, in one greppable line.

        A failure line that says only "README too big" sends whoever reads it
        looking for the number and then for whose number it is. The owner is
        named inline because that is the difference between a fix and a round
        trip -- and the cap is printed beside the measurement so nobody has to
        go and find out what the limit was on the day the job ran.
        """
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
        """The prompt is gated too, and its cap belongs to another branch.

        @hooks owns BRANCH_CHAR_BUDGET, so an over-cap prompt must send the
        reader to @hooks -- not to seedgo, which merely runs the measurement.
        """
        monkeypatch.setattr(sb.hooks_grounding, "BRANCH_CHAR_BUDGET", 10)
        root = _branch(tmp_path / "b", **{"README.md": "x", ".aipass/aipass_local_prompt.md": "y" * 30})

        result = _gate(root)
        line = next(one for one in result["failure_lines"] if "aipass_local_prompt" in one)

        assert result["passed"] is False
        assert _gated_row(result, ".aipass/aipass_local_prompt.md")["state"] == "over"
        assert "30 chars" in line and "10 chars" in line and "@hooks" in line

    def test_a_file_that_cannot_be_decoded_is_red_not_skipped(self, monkeypatch, tmp_path):
        """An unreadable README is not a small README.

        Falling through to "no measurement, no problem" is how a gate goes
        quiet: the one file it exists to hold becomes the one file it never
        reads, and the run stays green.
        """
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        root = tmp_path / "b"
        root.mkdir(parents=True, exist_ok=True)
        (root / "README.md").write_bytes(b"\xff\xfe\x00 not utf-8 \xff")

        result = _gate(root)

        assert result["passed"] is False
        assert _gated_row(result, "README.md")["state"] == "error"
        assert "cannot be read" in result["failure_lines"][0]

    def test_a_new_line_naming_the_owner_is_red_and_the_log_never_names_him(self, tmp_path):
        """The name ratchet's red says where, and masks what.

        A CI log on a public repo is public: a red that quoted the line would
        ship the very word it exists to stop. The file and line number are
        enough to find it, and the mask says what was there.
        """
        result = _names(tmp_path, {"src/aipass/probe/README.md": f"intro\nAsk {NAME.title()} first.\n"})
        said = _said(result)

        assert result["passed"] is False
        assert "src/aipass/probe/README.md" in said, "the file"
        assert "L2" in said, "the line"
        assert names.MASK in said, "what was there, masked"
        assert "NEW by 1" in said
        assert NAME not in said.lower(), "the log carried the name it guards"

    def test_the_name_is_matched_in_any_case_and_inside_an_identifier(self, tmp_path):
        """Substring, case-insensitive: an identifier ships the name as surely as prose.

        Five of the residual lines devpulse counted were test names. A
        word-boundary match would have passed every one of them.
        """
        text = f"def test_the_{NAME}_ruling():\n    pass\nWHO = '{NAME.upper()}'\n"

        result = _names(tmp_path, {"src/aipass/probe/tests/test_x.py": text})

        assert result["counts"] == {"src/aipass/probe/tests/test_x.py": {names.RULE_NAME: 2}}
        assert result["passed"] is False

    def test_a_real_home_path_in_a_prompt_or_a_content_file_is_red(self, tmp_path):
        """Three OS spellings of a person's home, in the two file kinds that render.

        A prompt is read by a seat on somebody else's machine and a
        ``*_content.py`` is printed to one; a home directory there tells the
        reader whose machine the text was written on.
        """
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
        """A file NAME ships too, and it is not something a baseline can hold.

        The baseline is keyed by path; baselining this one would write the name
        into the baseline. So it is line 0 of the file, masked, and red.
        """
        rel = f"docs/{NAME}_notes.md"

        result = _names(tmp_path, {rel: "nothing in here\n"})

        assert result["passed"] is False
        assert result["hits"][0].line == 0
        assert NAME not in _said(result).lower()


class TestRatchetBoundary:
    """`<=` passes. The boundary is the cap itself, and it is said out loud."""

    def test_a_file_exactly_at_its_cap_passes(self, monkeypatch, tmp_path):
        """A branch that diets to precisely 10,000 is not failed by zero chars.

        The same comparison the advisory checker makes (`chars > cap`), so the
        gate and the table can never disagree about the branch sitting on the
        line. The banner says it in words for the same reason.
        """
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
        """wc -m, never wc -c -- the unit the boardroom corrected three times.

        Ten multi-byte characters are thirty bytes. A gate measuring st_size
        would red-line a README three times shorter than its cap.
        """
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 20))
        root = _branch(tmp_path / "b", **{"README.md": "日" * 10})

        row = _gated_row(_gate(root), "README.md")

        assert row["chars"] == 10 and row["state"] == "under"

    def test_a_file_at_its_baseline_passes_and_one_more_line_is_red(self, tmp_path):
        """The name ratchet's boundary is the baseline count itself, as with a cap.

        Today's residue is written down and passes; the next line to join it is
        the red. Two lines against a baseline of two is the fleet on the day
        the ratchet landed.
        """
        rel = "src/aipass/probe/tests/test_x.py"
        two = f"a = '{NAME}'\nb = '{NAME}'\n"

        held = _names(tmp_path / "held", {rel: two}, baseline={rel: {names.RULE_NAME: 2}})
        grown = _names(tmp_path / "grown", {rel: two + f"c = '{NAME}'\n"}, baseline={rel: {names.RULE_NAME: 2}})

        assert held["passed"] is True, _said(held)
        assert grown["passed"] is False
        assert "3 name line(s), baseline 2" in _said(grown)

    def test_a_home_path_outside_markdown_and_content_files_is_not_this_rule(self, tmp_path):
        """The home-path rule reads what renders; code is hardcoded_path's lane.

        A ``/home/alice/`` fixture in a test or a handler is the scored
        hardcoded_path standard's to judge, and two rules redding one line only
        splits the diagnosis.
        """
        result = _names(tmp_path, {"src/aipass/probe/apps/handlers/x.py": 'P = "/home/alice/x"\n'})

        assert result["passed"] is True, _said(result)
        assert result["hits"] == []

    def test_a_home_path_with_no_trailing_slash_still_names_someone(self, tmp_path):
        """``/home/alice`` at the end of a table cell names alice as surely as ``/home/alice/``.

        Measured at HEAD before widening: two lines in the telegram port map
        spelled a home that way, and the brief's slash-terminated shape saw
        neither.
        """
        result = _names(tmp_path, {"docs/map.md": "| log dir | Hardcoded /home/alice in glob |\n"})

        assert result["counts"] == {"docs/map.md": {names.RULE_HOME: 1}}

    def test_a_placeholder_home_segment_is_not_a_person(self, tmp_path):
        """Docs need examples. ``/home/user/`` names nobody, so it passes.

        Only a segment that could be somebody's login is red; the allowlist is
        the spellings the fleet's docs use for "your name here" plus the CI
        runner accounts, which are GitHub's, not a person's.
        """
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
        """The gate holds @hooks' number, not a remembered 9,000.

        The file never changes between the two runs; only BRANCH_CHAR_BUDGET
        does. A `from ... import BRANCH_CHAR_BUDGET` binding, or a literal in
        seedgo, would keep one of these two verdicts wrong.
        """
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
        """Stored as a NAME, fetched with getattr -- never bound at import.

        A bound function object is the owner's answer copied at import time.
        The attribute spelling is what lets the lookup happen on every run, and
        it is the same idiom the checker uses for @hooks' and @prax' constants.
        """
        for gated in ratchet.GATED_FILES:
            assert isinstance(gated.cap_reader, str), "a bound function is a copy taken at import"
            assert callable(getattr(sb, gated.cap_reader)), f"{gated.cap_reader} must resolve on the checker"

    def test_no_cap_NUMBER_is_written_into_the_gate(self):
        """The gate carries paths and owner names. Never an integer cap.

        Read with ast, so the prose that discusses 10,000 and 9,000 is not
        mistaken for a constant -- what is forbidden is a literal the code can
        compare against, not a sentence explaining why there isn't one.
        """
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
        """seedgo cannot read its own number: say so, do not remember one.

        This is the defect the whole pack was written against, one layer up. A
        gate that silently substitutes the cap it saw last week is a gate that
        has stopped measuring and has not told anybody.
        """
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
        """A baseline that will not parse is not "nothing baselined".

        Reading it as empty would red all twenty residual lines at once and
        teach the reader the gate is noise; reading it as "pass" would stop
        the ratchet. Neither: the run is red and says which file.
        """
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
        """git runs, refuses (not a repository), prints nothing on stdout.

        An empty stdout parses to an empty file list, and an empty list has no
        hits. The exit code is the only thing that says the list is not real.
        """
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
        """A missing README is readme_check's red, not a second differently-worded one.

        The scored pack already fails "README exists" and gates at 100% in the
        same CI job. This rule is about GROWTH; duplicating that red here would
        only split the diagnosis across two messages.
        """
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
        """Gitignored files cannot be gated by a job that never sees them.

        .trinity/ and DASHBOARD.local.json are machine-local; a CI checkout
        holds neither, so a gate on them would measure nothing on every run and
        pass by accident forever. docs/ is measured by the advisory lane but
        left ungated while the fleet still holds pages that predate the
        20,000-chars-per-page rule.
        """
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

    def test_the_states_match_the_advisory_checkers_vocabulary(self):
        """One table vocabulary across both rules, or two readers of one report."""
        assert (ratchet.STATE_UNDER, ratchet.STATE_OVER) == (sb._STATE_UNDER, sb._STATE_OVER)
        assert (ratchet.STATE_ABSENT, ratchet.STATE_ERROR) == (sb._STATE_ABSENT, sb._STATE_ERROR)
        assert ratchet.FAILING_STATES == (ratchet.STATE_OVER, ratchet.STATE_ERROR), "absent never fails the gate"

    def test_the_owners_history_and_open_calls_are_never_opened(self, tmp_path):
        """Every exemption in the brief, each at a path that really takes it.

        The culture doc, changelogs and plans are history and stay (the
        ruling); the hook run logs, settings.json and the suspend tool wait on
        the owner; batch10 is hardcoded_path's own inputs and this ratchet's
        tests. Each file here names the owner and none of them is read.
        """
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
        """A near miss of an exempt path is an ordinary file and is read.

        An exemption written a character too wide becomes the place the name
        regrows -- another branch's settings.json, a CLAUDE.md outside
        ``.claude/``, the next batch of checker tests.
        """
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

    def test_the_pattern_is_the_name_this_files_fixtures_carry(self):
        """An oracle the module does not control: every other case reads the name
        off the module, so a wrong name would agree with itself and pass them all.

        This file is exempt precisely because hardcoded_path's inputs above are
        home paths with the real name in them, and they stay by the ruling. The
        ratchet's pattern must find them -- fifteen lines on the day it landed.
        """
        with open(__file__, encoding="utf-8") as handle:
            own = handle.read()

        found = [hit for hit in names.scan_text("fixtures.py", own) if hit.rule == names.RULE_NAME]

        assert len(found) >= 10, f"the pattern finds {len(found)} of this file's fixture lines"

    def test_every_exemption_is_named_in_the_checks_doc(self):
        """The brief: the exemptions are built in AND named in the check's doc."""
        for pattern in names.EXEMPT_PATHS + names.EXEMPT_NAMES:
            assert pattern in (names.__doc__ or ""), f"{pattern} is exempt but the doc never says so"

    def test_an_untracked_file_is_never_read(self, tmp_path):
        """Tracked means ``git ls-files``: scratch that does not ship is not the ratchet's.

        Built as a real repository, because this is the one fact a handed-in
        file list cannot prove.
        """
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
        """The same rule .github/scripts/seedgo_audit.py applies, so one fleet.

        A file gated on a branch the audit does not score -- or the reverse --
        is a hole nobody would find until it was used.
        """
        fleet = tmp_path / "src" / "aipass"
        for name in ("alpha", "bravo"):
            (fleet / name / "apps").mkdir(parents=True)
        (fleet / "not_a_branch").mkdir(parents=True)
        (fleet / "loose.py").parent.mkdir(parents=True, exist_ok=True)
        (fleet / "loose.py").write_text("x", encoding="utf-8")

        found = ratchet.discover_branches(tmp_path)

        assert [branch["name"] for branch in found] == ["alpha", "bravo"]

    def test_the_paths_stay_relative_to_the_root_it_was_given(self, tmp_path):
        """No absolute path is invented, so CI logs read repo-relative.

        A gate that resolved to an absolute path would print lines shaped like
        one host and unusable from anywhere else.
        """
        (tmp_path / "src" / "aipass" / "alpha" / "apps").mkdir(parents=True)

        from pathlib import Path as _Path

        relative = ratchet.discover_branches(_Path("."))
        assert all(not _Path(branch["path"]).is_absolute() for branch in relative), relative

    def test_a_root_with_no_fleet_yields_no_branches_rather_than_raising(self, tmp_path):
        """A gate that crashes on an odd cwd cannot report that anything is wrong."""
        assert ratchet.discover_branches(tmp_path / "nowhere") == []

    def test_the_live_fleet_is_under_every_gated_cap(self):
        """The one live-tree pin: the state the ratchet was dropped on.

        Seventeen README diets landed on 2026-09-15 to make this true. If this
        goes red, a gated file grew -- and the failure lines say which.
        """
        from pathlib import Path as _Path

        repo_root = _Path(__file__).resolve().parents[4]
        result = ratchet.run(ratchet.discover_branches(repo_root))

        assert len(result["rows"]) >= 2, "the walk found no branches -- the pin would be vacuous"
        assert result["passed"] is True, "\n".join(result["failure_lines"])


class TestRatchetReport:
    """What the job prints when nothing is wrong -- which is most runs."""

    def test_every_branch_is_printed_not_only_the_failing_ones(self, monkeypatch, tmp_path):
        """A gate whose log only appears on red hides how close a branch is running.

        The reading that lets a diet happen BEFORE the red is the green one.
        """
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 10000))
        alpha = _branch(tmp_path / "alpha", **{"README.md": "x" * 10})
        bravo = _branch(tmp_path / "bravo", **{"README.md": "y" * 20})

        report = ratchet.run([{"name": "alpha", "path": str(alpha)}, {"name": "bravo", "path": str(bravo)}])["report"]

        assert any("alpha" in line and "10/10,000" in line for line in report), report
        assert any("bravo" in line and "20/10,000" in line for line in report), report
        assert report[-1].startswith("  2 branch(es), 4 gated file(s)")
        assert "0 over cap, 0 unmeasurable" in report[-1]

    def test_the_gate_never_prints_it_returns_lines(self, capsys, monkeypatch, tmp_path):
        """A handler that writes to stdout cannot be called from a test or a dashboard.

        The .github runner prints; this module hands it strings. Anything else
        makes the module unusable anywhere output is not already expected.
        """
        monkeypatch.setattr(sb, "pack_manifest_path", lambda: _pack_manifest(tmp_path, 1))
        root = _branch(tmp_path / "b", **{"README.md": "x" * 50})

        _gate(root)

        assert capsys.readouterr().out == "", "the gate printed instead of returning"

    def test_a_loose_baseline_is_reported_with_the_number_to_write(self, tmp_path):
        """A ratchet only turns one way when somebody tightens it.

        A file that drops below its baseline passes -- the cure is never red --
        but the room it leaves is room for a new line nobody would see, so the
        report names the entry and the number that closes it.
        """
        rel = "src/aipass/probe/tests/test_x.py"

        result = _names(tmp_path, {rel: f"a = '{NAME}'\n"}, baseline={rel: {names.RULE_NAME: 3}})

        assert result["passed"] is True
        assert result["loose"] == [{"rel": rel, "rule": names.RULE_NAME, "count": 1, "allowed": 3}]
        assert any(rel in line and "write 1" in line for line in result["report"])

    def test_the_name_ratchet_never_prints_and_never_names_the_owner_itself(self, capsys):
        """The checker is the one file that must know the name -- and is not a hit.

        The module assembles the name from pieces, so its own source scans
        clean; the shipped baseline carries paths and counts only, so it cannot
        become the next place the name ships; and the run prints nothing.
        """
        module = names.__file__
        with open(module, encoding="utf-8") as handle:
            source = handle.read()
        shipped = names.BASELINE_PATH.read_text(encoding="utf-8")

        baseline, reason = names.load_baseline(names.BASELINE_PATH)

        assert names.scan_text("name_ratchet.py", source) == []
        assert NAME not in shipped.lower()
        assert reason == "" and baseline, "the shipped baseline must load"
        assert capsys.readouterr().out == ""


# =============================================
# router_assert — the is-True router rule (gold seal phase 2, rule 1)
# =============================================


class TestRouterAssertFires:
    """The two shapes the rule exists to convict."""

    def test_the_one_liner_form_is_convicted(self):
        """`assert handle_command(...) is True` and nothing else.

        Reddens if the direct-call arm of _is_sole_router_true stops reading
        the callee — the shape 86 of the fleet's 172 hits take.
        """
        source = "def test_x():\n    assert handle_command('x', []) is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]

    def test_the_assign_then_assert_form_is_convicted(self):
        """`result = handle_command(...)` then `assert result is True`.

        This is the majority shape and the one my own phase-1 grep missed,
        which is how 169 was reported for a population of 223. Reddens if
        _router_bound_names stops following the assignment.
        """
        source = "def test_x():\n    result = handle_command('x', [])\n    assert result is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]

    def test_an_attribute_call_is_the_same_router(self):
        """`mod.handle_command(...)` is the same protocol as the bare name.

        Reddens if _callee_name stops reading ast.Attribute — most branches
        import the module, not the function.
        """
        source = "def test_x():\n    assert mod.handle_command('x', []) is True\n"
        assert router_assert.find_violations(source) == [(1, "test_x")]


class TestRouterAssertStaysSilent:
    """Every acquittal, each for a different reason."""

    def test_a_decline_is_a_whole_contract(self):
        """`is False` is never convicted — 117 fleet units depend on this.

        Reddens if the rule is widened from `is True` to "the sole return
        flag", which is the version that would delete correct tests.
        """
        source = "def test_x():\n    assert handle_command('not_mine', []) is False\n"
        assert router_assert.find_violations(source) == []

    def test_one_honest_assertion_acquits_the_unit(self):
        """A second assert means the test proves something the True does not.

        Reddens if `all()` becomes `any()` — the difference between convicting
        a vacuous test and convicting every test that also checks routing.
        """
        source = "def test_x():\n    assert handle_command('x', []) is True\n    assert con.print.called\n"
        assert router_assert.find_violations(source) == []

    def test_a_mock_assert_call_is_an_oracle(self):
        """`assert_called_once_with` raises on its own; there is no `assert`.

        Reddens if the effect scan drops mock's family — a test asserting
        exactly the effect the message asks for would be convicted for it.
        """
        source = (
            "def test_x():\n    assert handle_command('x', []) is True\n    con.print.assert_called_once_with('hi')\n"
        )
        assert router_assert.find_violations(source) == []

    def test_an_underscore_helper_is_an_oracle(self):
        """A module-local `_assert_*` helper carries the whole oracle.

        This was a REAL false positive, found in the first precision sample:
        aipass/tests/test_help_flag.py:174 asserts through
        `_assert_nothing_happened` and the rule matched only "assert_".
        Reddens if the lstrip("_") is removed.
        """
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
        """`is_valid(...) is True` is a real claim: the True IS the behaviour.

        Reddens if ROUTER_NAMES is widened to "anything returning a bool",
        which would convict every predicate test in the fleet.
        """
        source = "def test_x():\n    assert is_valid('abc') is True\n"
        assert router_assert.find_violations(source) == []

    def test_a_unit_with_no_assertions_is_not_this_rules_problem(self):
        """No assert at all is no_oracle's finding, not router_assert's.

        Reddens if the `if not asserts: continue` guard goes — `all([])` is
        True, so every assertionless test would be convicted here.
        """
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

    def test_a_line_bypass_silences_one_unit_and_not_the_file(self, tmp_path):
        """The declared deviation is cheap; the silent one stays impossible.

        Reddens if check_module stops passing the unit's line to is_bypassed —
        a file-wide bypass would then be the only way out of one bad test.
        """
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

    def test_the_backlog_line_skips_retired_tests(self, tmp_path):
        """A unit under tests/.archive/ can never be convicted, so it is not owed.

        Reddens if the is_retired_path guard goes. Measured 2026-09-20: the
        backlog reported daemon 8 against a lane that could only ever convict
        7, because tests/.archive/test_actions_module.py was counted. A
        backlog nobody can burn down is a number, not a debt.
        """
        live = tmp_path / "tests"
        (live / ".archive").mkdir(parents=True)
        unit = "def test_x():\n    assert handle_command('x', []) is True\n"
        (live / "test_live.py").write_text(unit, encoding="utf-8")
        (live / ".archive" / "test_retired.py").write_text(unit, encoding="utf-8")

        lines = router_assert.check_branch_info(str(tmp_path))

        assert len(lines) == 1
        assert "1 test(s) in 1 file(s)" in lines[0]
        assert "unscored" in lines[0]

    def test_a_clean_branch_says_nothing_at_all(self, tmp_path):
        """No backlog, no line — an info channel that always speaks is noise."""
        (tmp_path / "tests").mkdir()
        (tmp_path / "tests" / "test_clean.py").write_text(
            "def test_x():\n    assert handle_command('x', []) is False\n", encoding="utf-8"
        )

        assert router_assert.check_branch_info(str(tmp_path)) == []

    def test_the_standard_scores_nothing_because_it_declares_tests(self):
        """APPLIES_TO=tests keeps it out of the audit's apps/ corpus entirely.

        This is the whole day-one guarantee: 172 fleet convictions and not one
        branch's number moved. Reddens the moment the declaration changes.
        """
        assert router_assert.APPLIES_TO == applicability.TESTS


# =============================================
# oversize_test_file — the 1,500 code-line cap (gold seal phase 2, rule 2)
# =============================================


class TestOversizeTestFileMeasures:
    """What counts as a code line, and what is given back."""

    def test_payload_inside_a_multiline_string_is_not_code(self):
        """A fixture blob is data the assertions read, not lines to split.

        Reddens if _payload_lines stops subtracting — a file holding one
        1,500-line JSON sample would then be convicted for the sample.
        """
        source = 'FIXTURE = """\n' + "line\n" * 50 + '"""\nx = 1\n'

        code, total, payload = oversize.measure(source)

        assert (total, payload, code) == (53, 52, 1)

    def test_a_docstring_is_payload_too(self):
        """A size rule must never be a reason to delete the bug a test names.

        Reddens if payload is narrowed to "fixtures only" by, say, skipping
        the first statement of a function — the gold standard asks authors to
        write these sentences, so the size rule pays for them.
        """
        source = 'def test_x():\n    """\n' + "    why this test exists\n" * 20 + '    """\n    assert True\n'

        code, _total, payload = oversize.measure(source)

        assert payload == 22
        assert code == 2

    def test_an_fstring_span_is_counted_once(self):
        """Nested constants inside one f-string must not double-count.

        A sum of spans overstates a file by the lines an f-string shares with
        its own children; measured 2026-09-20 that was 26 lines on this
        branch's largest file. Reddens if the line SET becomes a sum.
        """
        source = 'V = 1\nS = f"""\n{V}\nmiddle\n{V}\n"""\n'

        code, total, payload = oversize.measure(source)

        assert (total, payload, code) == (6, 5, 1)

    def test_an_unparseable_file_is_measured_whole(self):
        """Breaking the syntax must not be a way under the cap.

        Reddens if the SyntaxError arm returns 0 or skips the file: "delete
        one bracket" would become the cheapest way to silence this rule.
        """
        code, total, payload = oversize.measure("def test_x(:\n" + "x = 1\n" * 40)

        assert (total, payload, code) == (41, 0, 41)


class TestOversizeTestFileLanes:
    """The cap itself, the message, and the unscored backlog."""

    def test_the_cap_convicts_at_one_line_over_and_not_at_the_cap(self, tmp_path):
        """The boundary is `>`, not `>=`.

        Reddens on an off-by-one that convicts a file sitting exactly on a
        published cap — the one number an author will aim for.
        """
        at_cap = tmp_path / "test_at.py"
        over = tmp_path / "test_over.py"
        at_cap.write_text("x = 1\n" * oversize.CODE_LINE_CAP, encoding="utf-8")
        over.write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8")

        assert oversize.check_module(str(at_cap))["passed"] is True
        assert oversize.check_module(str(over))["passed"] is False

    def test_the_conviction_names_the_payload_it_already_forgave(self, tmp_path):
        """An author at 10,524 lines needs to know 5,929 were already given back.

        Reddens if the message drops to a bare count — the cap then reads as
        unreachable and the rule gets bypassed instead of acted on.
        """
        big = tmp_path / "test_big.py"
        big.write_text(
            'P = """\n' + "pad\n" * 100 + '"""\n' + "x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8"
        )

        message = oversize.check_module(str(big))["checks"][0]["message"]

        assert "102 of string payload already excluded" in message
        assert "split it along the unit under test" in message

    def test_the_message_sends_the_author_to_the_gate_not_around_it(self, tmp_path):
        """The cure needs new test files, which the hooks gate refuses.

        Reddens if the message ever tells an author to just create the files.
        The rule must not instruct anyone to route around a policy gate.
        """
        big = tmp_path / "test_big.py"
        big.write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8")

        message = oversize.check_module(str(big))["checks"][0]["message"]

        assert "@devpulse" in message
        assert "moving tests is not adding them" in message.lower()

    def test_the_backlog_names_the_largest_offender(self, tmp_path):
        """ "3 files over the cap" gives an owner nowhere to start.

        Reddens if the info line degrades to a count.
        """
        tests = tmp_path / "tests"
        tests.mkdir()
        (tests / "test_small.py").write_text("x = 1\n" * 10, encoding="utf-8")
        (tests / "test_mid.py").write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 5), encoding="utf-8")
        (tests / "test_worst.py").write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 900), encoding="utf-8")

        lines = oversize.check_branch_info(str(tmp_path))

        assert len(lines) == 1
        assert "2 test file(s) over" in lines[0]
        assert "largest test_worst.py at 2400" in lines[0]
        assert "unscored" in lines[0]

    def test_the_backlog_skips_retired_tests(self, tmp_path):
        """A file under tests/.archive/ can never be convicted, so it is not owed.

        Same defect router_assert's backlog shipped with: a debt nobody can
        burn down is a number, not a backlog.
        """
        tests = tmp_path / "tests"
        (tests / ".archive").mkdir(parents=True)
        (tests / ".archive" / "test_old.py").write_text("x = 1\n" * (oversize.CODE_LINE_CAP + 1), encoding="utf-8")

        assert oversize.check_branch_info(str(tmp_path)) == []

    def test_the_standard_scores_nothing_because_it_declares_tests(self):
        """APPLIES_TO=tests keeps it out of the audit's apps/ corpus entirely.

        34 fleet convictions on arrival and not one branch's number moved.
        Reddens the moment the declaration changes.
        """
        assert oversize.APPLIES_TO == applicability.TESTS
