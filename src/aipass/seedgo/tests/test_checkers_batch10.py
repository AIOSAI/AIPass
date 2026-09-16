"""Tests for seedgo checker handlers -- batch 10 (hardcoded_path, startup_budget)."""

# =================== META ====================
# Name: test_checkers_batch10.py
# Description: Unit tests for hardcoded_path_check and context/startup_budget_check
# Version: 1.1.0
# Created: 2026-06-18
# Modified: 2026-09-15
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

    def test_the_shipped_manifest_carries_patricks_ruled_ten_thousand(self):
        """The one live-tree pin: the ruled number, where the ratchet will read it.

        Patrick ruled 10,000 on 2026-09-15 at 16:02. The room had proposed
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
