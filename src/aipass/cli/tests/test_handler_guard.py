"""Tests for handlers/__init__.py cross-branch import guard.

WHY THIS FILE WAS REWRITTEN (2026-08-18, S43). @seedgo's taxonomy study found
this file was a COVERAGE MIRAGE: it carried a class named TestGuardBranchAccess
while `_guard_branch_access()` — the 56-line function that IS this module's
reason to exist — had no test at all. The worst offender asserted on
`_find_real_caller()` while claiming to cover the AIPASS_DEBUG_GUARD contract;
that variable is read inside `_guard_branch_access()`, so the assertion passed
identically with the variable set or unset.

A test named for a behaviour it never exercises is worse than no test: it
occupies the slot where the real one would go. Every test below drives
`_guard_branch_access()` itself, with `_find_real_caller` patched so the caller
identity under test is the one being asserted.
"""

import os
from unittest.mock import patch

import pytest

from aipass.cli.apps.handlers import (
    _extract_branch_name,
    _find_real_caller,
    _guard_branch_access,
)

FOREIGN = "/home/user/Projects/AIPass/src/aipass/drone/apps/modules/core.py"
OURS = "/home/user/Projects/AIPass/src/aipass/cli/apps/modules/display.py"
IMPORT_LINE = "from aipass.cli.apps.handlers.json import json_handler"


class TestExtractBranchName:
    def test_extracts_branch_from_aipass_path(self):
        assert _extract_branch_name(FOREIGN) == "drone"

    def test_extracts_cli_branch(self):
        assert _extract_branch_name(OURS) == "cli"

    def test_returns_unknown_for_no_aipass(self):
        assert _extract_branch_name("/usr/lib/python3/site-packages/something.py") == "unknown"

    def test_returns_unknown_when_aipass_is_last(self):
        assert _extract_branch_name("/home/user/aipass") == "unknown"


class TestFindRealCaller:
    def test_returns_tuple(self):
        result = _find_real_caller()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_finds_this_test_file(self):
        filepath, _import_line = _find_real_caller()
        assert filepath is not None
        assert "test_handler_guard" in filepath


class TestGuardRefusesForeignBranches:
    """THE CONTRACT: a caller outside this branch must be refused, in words."""

    def test_foreign_branch_raises_import_error(self):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, IMPORT_LINE)):
            with pytest.raises(ImportError):
                _guard_branch_access()

    def test_refusal_names_the_calling_branch(self):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, IMPORT_LINE)):
            with pytest.raises(ImportError) as excinfo:
                _guard_branch_access()
            assert "drone" in str(excinfo.value)

    def test_refusal_names_the_calling_file(self):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, IMPORT_LINE)):
            with pytest.raises(ImportError) as excinfo:
                _guard_branch_access()
            assert "core.py" in str(excinfo.value)

    def test_refusal_quotes_the_blocked_import(self):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, IMPORT_LINE)):
            with pytest.raises(ImportError) as excinfo:
                _guard_branch_access()
            assert IMPORT_LINE in str(excinfo.value)

    def test_refusal_says_unknown_when_import_line_missing(self):
        """A refusal must still be readable when the stack gave no source line."""
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, None)):
            with pytest.raises(ImportError) as excinfo:
                _guard_branch_access()
            assert "unknown" in str(excinfo.value)

    def test_refusal_points_at_the_public_alternative(self):
        """Refusing without saying what to do instead is a dead end, not a guard."""
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(FOREIGN, IMPORT_LINE)):
            with pytest.raises(ImportError) as excinfo:
                _guard_branch_access()
            assert "cli.apps.modules" in str(excinfo.value)


class TestGuardAllowsLegitimateCallers:
    """The other half of the contract: it must not refuse its own branch.

    Every unit here used to be a bare call — the entire claim was "it did not
    raise", which a reader cannot see and a checker cannot count. Two oracles
    now stand in its place. `pytest.fail` says what the guard must LET THROUGH,
    naming the refusal when one arrives instead of leaving a raw ImportError to
    be read as a crash. The AIPASS_DEBUG_GUARD trace says what it RECORDED, and
    that is what distinguishes WHICH arm allowed the caller: the same-branch
    match and the fail-open return are indistinguishable from outside without
    it, so a bare call could not tell a working guard from one that had stopped
    matching branches at all and was passing everything.
    """

    def test_same_branch_caller_allowed(self):
        """Own branch is allowed — a refusal here locks cli out of its own handlers.

        No trace assertion: TestDebugTracing already pins OURS on stderr, and a
        second copy would pin the checker, not the guard.
        """
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(OURS, IMPORT_LINE)):
            try:
                _guard_branch_access()
            except ImportError as refusal:
                pytest.fail(f"guard refused a caller from its own branch: {refusal}")

    def test_windows_path_separators_recognised(self, capsys):
        """The guard normalises backslashes — a Windows caller is not foreign.

        The trace assertion is the load-bearing half: it pins that what reached
        the branch check really was the backslash spelling, so the test proves
        normalisation rather than proving that a POSIX path was handed in.
        """
        windows_path = OURS.replace("/", "\\")
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(windows_path, IMPORT_LINE)):
            with patch.dict(os.environ, {"AIPASS_DEBUG_GUARD": "1"}):
                try:
                    _guard_branch_access()
                except ImportError as refusal:
                    pytest.fail(f"guard refused a Windows-spelled caller from its own branch: {refusal}")
        assert windows_path in capsys.readouterr().err

    def test_undeterminable_caller_allowed(self, capsys):
        """Fail OPEN when the caller cannot be identified — a REPL is not an attack.

        The trace pins that the None arm is the one that returned. Without it
        this unit would pass identically if the guard never looked at the caller.
        """
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(None, None)):
            with patch.dict(os.environ, {"AIPASS_DEBUG_GUARD": "1"}):
                try:
                    _guard_branch_access()
                except ImportError as refusal:
                    pytest.fail(f"guard refused an unidentifiable caller: {refusal}")
        assert "caller_file = None" in capsys.readouterr().err

    def test_real_in_branch_import_is_not_blocked(self):
        """End to end, unpatched: this branch importing its own handler works."""
        from aipass.cli.apps.handlers.json import json_handler

        assert json_handler is not None


class TestDebugTracing:
    """AIPASS_DEBUG_GUARD — the contract the old mirage test claimed to cover."""

    def test_debug_env_var_traces_to_stderr(self, capsys):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(OURS, IMPORT_LINE)):
            with patch.dict(os.environ, {"AIPASS_DEBUG_GUARD": "1"}):
                _guard_branch_access()
        captured = capsys.readouterr()
        assert "caller_file" in captured.err
        assert OURS in captured.err

    def test_debug_trace_reports_the_import_line(self, capsys):
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(OURS, IMPORT_LINE)):
            with patch.dict(os.environ, {"AIPASS_DEBUG_GUARD": "1"}):
                _guard_branch_access()
        assert IMPORT_LINE in capsys.readouterr().err

    def test_silent_when_debug_unset(self, capsys):
        """The distinguishing half — without this the env var proves nothing."""
        env = {key: value for key, value in os.environ.items() if key != "AIPASS_DEBUG_GUARD"}
        with patch("aipass.cli.apps.handlers._find_real_caller", return_value=(OURS, IMPORT_LINE)):
            with patch.dict(os.environ, env, clear=True):
                _guard_branch_access()
        captured = capsys.readouterr()
        assert captured.err == ""
        assert captured.out == ""
