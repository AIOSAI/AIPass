# =================== AIPass ====================
# Name: test_handler_guard.py
# Description: Tests for cross-branch import protection guard
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for apps/handlers/__init__.py -- cross-branch import protection.

Tests:
- _extract_branch_name: extracts branch from path segments
- _find_real_caller: walks call stack, returns (filepath, import_line) tuple
- _guard_branch_access: allows /api/ callers, blocks others, handles None caller
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# The handlers __init__.py is replaced by a stub in conftest (to bypass the
# guard at import time).  Load the real file directly so we can test its
# functions without triggering the module-level _guard_branch_access() call.
# ---------------------------------------------------------------------------
_INIT_PATH = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"
_spec = importlib.util.spec_from_file_location("_guard_impl", str(_INIT_PATH))
assert _spec is not None and _spec.loader is not None
_guard_mod = importlib.util.module_from_spec(_spec)

# Patch _guard_branch_access to a no-op before exec so the module-level call
# does not block us during test collection.
_original_guard = None


def _noop_guard() -> None:
    pass


# Temporarily override _guard_branch_access during module load
_spec.loader.exec_module(_guard_mod)

# Now extract the real functions for testing
_extract_branch_name = _guard_mod._extract_branch_name
_find_real_caller = _guard_mod._find_real_caller
_guard_branch_access = _guard_mod._guard_branch_access
_MOD_NAME = "_guard_impl"


# =============================================
# _extract_branch_name
# =============================================


class TestExtractBranchName:
    """Verifies branch name extraction from file paths."""

    def test_memory_branch(self) -> None:
        """Path containing 'memory' extracts the next segment."""
        path = "/home/user/Projects/memory/archive/loader.py"
        assert _extract_branch_name(path) == "archive"

    def test_seedgo_branch(self) -> None:
        """Path containing 'seedgo' extracts the next segment."""
        path = "/home/user/Projects/seedgo/core/checks.py"
        assert _extract_branch_name(path) == "core"

    def test_vscode_branch(self) -> None:
        """Path containing '.vscode' extracts the next segment."""
        path = "/home/user/.vscode/extensions/some_ext/main.py"
        assert _extract_branch_name(path) == "extensions"

    def test_aipass_before_apps_returns_aipass(self) -> None:
        """Path with 'aipass' immediately before 'apps' returns 'aipass'."""
        path = "/home/user/Projects/aipass/apps/modules/bridge.py"
        assert _extract_branch_name(path) == "aipass"

    def test_unknown_path(self) -> None:
        """Path without recognised markers returns 'unknown'."""
        path = "/usr/lib/python3/random_lib.py"
        assert _extract_branch_name(path) == "unknown"


# =============================================
# _find_real_caller
# =============================================


class TestFindRealCaller:
    """Verifies the stack-walking caller-detection helper."""

    def test_returns_tuple(self) -> None:
        """Result must be a two-element tuple."""
        result = _find_real_caller()
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_the_caller_it_finds_from_here_is_this_file(self) -> None:
        """
        Called from this file, it resolves to THIS file — no guard, no or-None.

        Three tests used to share this call and none of them could fail. Two
        asserted `x is None or isinstance(x, str)`, which is true of None and
        true of every string, so the guard returning None for everything
        passed both. The third asserted the real thing behind
        `if filepath is not None:` — a branch that a broken resolver never
        enters, so the one test that knew the answer skipped itself exactly
        when it mattered.

        There is no uncertainty to guard here: this test IS a real file with a
        real frame, so a None is a defect and is asserted as one.
        """
        filepath, import_line = _find_real_caller()

        assert filepath is not None, "the guard could not resolve a caller from a real test file"
        assert Path(filepath).name == "test_handler_guard.py"
        assert isinstance(import_line, str), "a resolved frame must carry its code context"


# =============================================
# _guard_branch_access
# =============================================


class TestGuardBranchAccess:
    """Verifies the import guard via controlled mock scenarios."""

    def test_allows_api_branch_caller(self) -> None:
        """Caller whose resolved path contains /api/ passes through."""
        fake_caller = "/home/user/Projects/AIPass/src/aipass/api/apps/modules/bridge.py"
        with patch.object(
            _guard_mod,
            "_find_real_caller",
            return_value=(fake_caller, "from aipass.api.apps.handlers import x"),
        ):
            # The oracle is the CONTRAST, not the silence: acceptance here is
            # the absence of a raise, so a guard emptied to `pass` would have
            # satisfied a bare call. A foreign caller through the same door on
            # the same mock must still be refused, and that is what makes the
            # pass-through mean something.
            assert _guard_branch_access() is None

        foreign = "/home/user/Projects/AIPass/src/aipass/baud/apps/modules/thing.py"
        with patch.object(
            _guard_mod,
            "_find_real_caller",
            return_value=(foreign, "from aipass.api.apps.handlers import x"),
        ):
            with pytest.raises(ImportError, match="ACCESS DENIED"):
                _guard_branch_access()

    def test_blocks_non_api_branch_caller(self) -> None:
        """Caller outside /api/ triggers ImportError with ACCESS DENIED."""
        fake_caller = "/home/user/Projects/AIPass/src/aipass/backup/apps/sync.py"
        with patch.object(
            _guard_mod,
            "_find_real_caller",
            return_value=(fake_caller, "from aipass.api.apps.handlers import x"),
        ):
            with pytest.raises(ImportError, match="ACCESS DENIED"):
                _guard_branch_access()

    def test_allows_none_caller(self) -> None:
        """When _find_real_caller returns (None, None) the guard passes."""
        with patch.object(
            _guard_mod,
            "_find_real_caller",
            return_value=(None, None),
        ):
            with patch("inspect.stack", return_value=[]):
                # An unresolvable caller is ALLOWED, deliberately: refusing what
                # cannot be identified would break every legitimate entry the
                # frame walk cannot see. Asserted rather than left implicit, so
                # the day that policy flips this test says so.
                assert _guard_branch_access() is None
