# =================== AIPass ====================
# Name: test_handlers_init.py
# Description: Tests for handlers/__init__.py branch access guard
# Version: 1.0.0
# Created: 2026-05-12
# Modified: 2026-05-12
# =============================================

"""Tests for handlers/__init__.py — branch access guard."""

import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

# ---------------------------------------------------------------------------
# The handlers __init__.py runs _guard_branch_access() at import time.
# We import the individual functions after the module is already loaded
# (conftest triggers it through transitive imports).  That sidesteps the
# import-time guard and lets us call each function in isolation.
# ---------------------------------------------------------------------------

from aipass.flow.apps.handlers import (  # noqa: E402
    MY_BRANCH,
    _extract_branch_name,
    _find_real_caller,
    _guard_branch_access,
)


# ===================================================================
# 1. _extract_branch_name
# ===================================================================


class TestExtractBranchName:
    """Extract the branch name from various file paths."""

    def test_flow_branch_path(self):
        """Path containing 'aipass/flow' returns 'flow'."""
        result = _extract_branch_name("/home/user/Projects/AIPass/src/aipass/flow/apps/handlers/foo.py")
        assert result == "flow"

    def test_memory_branch_path(self):
        """Path containing 'aipass/memory' returns 'memory'."""
        result = _extract_branch_name("/home/user/Projects/AIPass/src/aipass/memory/apps/modules/vectorize.py")
        assert result == "memory"

    def test_nexus_branch_path(self):
        """Path containing 'Nexus' returns the segment after it."""
        result = _extract_branch_name("/home/user/Projects/AIPass/Nexus/core/main.py")
        assert result == "core"

    def test_aipass_drone_path(self):
        """Path containing 'aipass/drone' returns 'drone'."""
        result = _extract_branch_name("/home/user/Projects/AIPass/src/aipass/drone/handler.py")
        assert result == "drone"

    def test_unknown_path_returns_unknown(self):
        """Path with no recognised branch marker returns 'unknown'."""
        result = _extract_branch_name("/usr/lib/python3/site-packages/some_lib/util.py")
        assert result == "unknown"

    def test_aipass_at_end_of_path(self):
        """If 'aipass' is the last segment there is no branch name after it."""
        result = _extract_branch_name("/home/user/aipass")
        assert result == "unknown"

    def test_forward_slash_path(self):
        """Forward-slash paths are parsed correctly on all platforms."""
        result = _extract_branch_name("C:/Users/dev/Projects/AIPass/src/aipass/flow/test.py")
        assert result == "flow"


# ===================================================================
# 2. _find_real_caller
# ===================================================================


class TestFindRealCaller:
    """Walk the stack and return the first real (non-internal) file.

    REWRITTEN 2026-08-31. These tests used to patch
    ``aipass.flow.apps.handlers.inspect.stack`` and feed it MagicMock
    FrameInfos. That mock is why the defect below lived here undisturbed:
    ``inspect.stack()`` builds a FrameInfo per frame, which reaches
    ``getmodule()``'s unguarded ``os.path.realpath`` — a cwd read on Windows,
    before any of the guard's own code runs — and a stack that never executes
    cannot demonstrate that. The walk is ``sys._getframe`` now, so these drive
    REAL frames: ``compile(..., filename)`` gives a frame whatever
    ``co_filename`` the case needs, which is the same lever the mock provided
    and costs nothing in fidelity.
    """

    @staticmethod
    def _call_from(filename: str, source: str = "RESULT = _frc()"):
        """Run ``_find_real_caller()`` inside a frame named *filename*."""
        namespace = {"_frc": _find_real_caller, "RESULT": None}
        exec(compile(source, filename, "exec"), namespace)
        return namespace["RESULT"]

    def test_returns_real_file(self, tmp_path):
        """A real file on the stack comes back resolved, with its source line."""
        caller = tmp_path / "foo.py"
        caller.write_text("PADDING = 1\nRESULT = _frc()\n", encoding="utf-8")

        filepath, import_line = self._call_from(str(caller), caller.read_text(encoding="utf-8"))

        assert filepath == str(caller.resolve())
        # linecache reads the line the calling frame is ON. In production that
        # line is the import statement the guard fired for.
        assert import_line == "RESULT = _frc()"

    def test_skips_importlib_internals(self):
        """Frames with 'importlib' in the filename are skipped."""
        filepath, _ = self._call_from("/usr/lib/python3/importlib/_bootstrap.py")

        assert filepath is not None
        assert "importlib" not in filepath
        # The next real frame up is this test file itself.
        assert filepath.endswith("test_handlers_init.py")

    def test_skips_angle_bracket_filenames(self):
        """Frames whose filename starts with '<' are skipped.

        Skipped BEFORE the filesystem is touched: ``resolve()`` on ``<string>``
        needs a cwd, and a process whose cwd was deleted dies on that line.
        """
        filepath, _ = self._call_from("<string>")

        assert filepath is not None
        assert not filepath.startswith("<")
        assert filepath.endswith("test_handlers_init.py")

    def test_returns_none_when_no_real_frames(self):
        """Every frame internal or angle-bracket → (None, None).

        Run in a subprocess because it is the only way to own the WHOLE stack:
        inside pytest the frames above this one are real files, so the walk
        would rightly find one. A ``python -c`` process has a single
        ``<string>`` frame and nothing else — which is also exactly the shape
        production hits when drone routes a command.
        """
        script = (
            "from aipass.flow.apps.handlers import _find_real_caller\n"
            "ns = {'_frc': _find_real_caller, 'RESULT': None}\n"
            "exec(compile('RESULT = _frc()', '<string>', 'exec'), ns)\n"
            "print('RESULT:', ns['RESULT'])\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "RESULT: (None, None)" in result.stdout, result.stdout

    def test_none_code_context(self):
        """A frame naming a file that is not on disk yields import_line None.

        linecache returns "" rather than raising for a file it cannot read —
        which is the whole reason it replaced inspect's code_context here.
        """
        missing = str(Path(tempfile.gettempdir()) / "flow_no_such_file_9f3c.py")
        assert not Path(missing).exists()

        filepath, import_line = self._call_from(missing)

        assert filepath is not None
        assert import_line is None


# ===================================================================
# 3. _guard_branch_access
# ===================================================================


class TestGuardBranchAccess:
    """Test the import guard logic."""

    def test_allows_same_branch_import(self):
        """Caller from the same branch (flow) is allowed through."""
        caller = "/home/user/Projects/AIPass/src/aipass/flow/apps/modules/runner.py"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, "from aipass.flow.apps.handlers import x"),
        ):
            # Should not raise
            _guard_branch_access()

    def test_blocks_external_branch_import(self):
        """Caller from a different branch raises ImportError."""
        caller = "/home/user/Projects/AIPass/src/aipass/drone/apps/modules/dispatcher.py"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, "from aipass.flow.apps.handlers import x"),
        ):
            with pytest.raises(ImportError, match="ACCESS DENIED"):
                _guard_branch_access()

    def test_error_message_contains_caller_branch(self):
        """The ImportError message includes the caller's branch name."""
        caller = "/home/user/Projects/AIPass/src/aipass/memory/apps/modules/indexer.py"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, "from aipass.flow.apps.handlers import y"),
        ):
            with pytest.raises(ImportError, match="memory"):
                _guard_branch_access()

    def test_error_message_contains_import_line(self):
        """The ImportError message includes the blocked import line."""
        caller = "/home/user/Projects/AIPass/src/aipass/drone/handler.py"
        import_line = "from aipass.flow.apps.handlers.json import json_handler"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, import_line),
        ):
            with pytest.raises(ImportError, match="json_handler"):
                _guard_branch_access()

    def test_allows_when_caller_none_whatever_is_on_the_stack(self):
        """caller is None → allowed, and nothing else is consulted.

        REPLACES three tests (``<string>`` on the stack, ``<stdin>`` on the
        stack, neither) that each pinned one leg of a SECOND ``inspect.stack()``
        walk inside this branch. That walk returned "allow" on every path it
        could take, so it was a second copy of the cwd dependency in service of
        a branch that could not change the answer — deleted 2026-08-31. Three
        tests asserting the same allow through three routes read as coverage and
        were really one contract, so it is stated once here.

        The three worlds are still exercised: each drives the REAL walk to None
        by owning the whole stack in a subprocess, which the mocked version
        never did.

        NO IMPORT-SHAPED pin can reach the DELETION — ``apps/__init__.py``
        always supplies a real-file frame, so no import enters this branch at all
        (@trigger restored the walk in their tree and 1058 tests stayed green).
        An earlier version of this docstring said behaviour could not pin it at
        all; @spawn measured the correction (relayed by @devpulse 2026-08-31).
        Calling the guard DIRECTLY from a ``python -c`` child does reach it, and
        ``tests/test_import_dead_cwd.py`` carries both instruments now: the AST
        ban and that behavioural sibling. A regrown walk kills both.
        """
        for world in ("<string>", "<stdin>", "no special frames"):
            with patch(
                "aipass.flow.apps.handlers._find_real_caller",
                return_value=(None, None),
            ):
                # Should not raise, in any of the three.
                _guard_branch_access()

    def test_the_caller_none_branch_is_reached_by_a_real_stack(self):
        """Control for the test above: None is reachable without patching.

        Patching ``_find_real_caller`` to return None proves the guard's
        RESPONSE, not that the world exists. A ``python -c`` process is the
        world — one ``<string>`` frame, nothing above it — and it must import
        flow's handlers without raising.
        """
        script = (
            "import aipass.flow.apps.handlers as h\n"
            "ns = {'_frc': h._find_real_caller, 'RESULT': None}\n"
            "exec(compile('RESULT = _frc()', '<string>', 'exec'), ns)\n"
            "assert ns['RESULT'] == (None, None), ns['RESULT']\n"
            "exec(compile('h._guard_branch_access()', '<string>', 'exec'), {'h': h})\n"
            "print('ALLOWED')\n"
        )
        result = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

        assert result.returncode == 0, result.stdout + result.stderr
        assert "ALLOWED" in result.stdout, result.stdout

    def test_blocked_import_says_unknown_when_no_import_line(self):
        """When import_line is None, the error message says 'unknown'."""
        caller = "/home/user/Projects/AIPass/src/aipass/drone/x.py"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, None),
        ):
            with pytest.raises(ImportError, match="unknown"):
                _guard_branch_access()

    def test_my_branch_constant(self):
        """MY_BRANCH is set to 'flow'."""
        assert MY_BRANCH == "flow"

    def test_allows_flow_subpath_with_backslashes(self):
        """Windows-style paths with backslashes still match the flow branch."""
        # The guard replaces backslashes with forward slashes before checking
        caller = "C:\\Users\\dev\\Projects\\AIPass\\src\\aipass\\flow\\apps\\modules\\foo.py"

        with patch(
            "aipass.flow.apps.handlers._find_real_caller",
            return_value=(caller, "import x"),
        ):
            # Should not raise
            _guard_branch_access()
