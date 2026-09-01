# =================== AIPass ====================
# Name: test_handlers_guard_import.py
# Description: The branch-access guard must import without a readable cwd
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The import-time branch guard must not need a filesystem to run.

THE DEFECT (@spawn's find, 2026-08-31, 16 branches carried it). ``_find_real_caller``
opened with ``inspect.stack()``, which builds a FrameInfo per frame and reaches
``getsourcefile() -> getmodule() -> os.path.realpath()``. On Windows
``ntpath.realpath`` calls ``os.getcwd()`` unconditionally in its opening lines —
before it checks whether the path is even absolute — at a call site inside
``getmodule`` that is not wrapped in a try. So importing ANY handler in this
package needed a readable cwd on Windows, and a disconnected share killed the
import of a package whose only job at that moment was to check a name.

WHY IT HID ON LINUX, and why these pins deny what they deny. ``posixpath.realpath``
does not call ``getcwd`` for an absolute path, so the POSIX equivalent raises
earlier inside ``getabsfile()`` where ``inspect`` catches it. Denying
``os.getcwd`` on Linux therefore proves nothing here — measured, both ways, before
these pins were written. The instrument denies ``os.path.realpath``: the call the
defect actually makes.

Everything runs in a SUBPROCESS because the thing under test happens at import
time, and a package already in ``sys.modules`` cannot be imported again.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[4]
TARGET = "aipass.ai_mail.apps.handlers"


def _run(*parts: str) -> subprocess.CompletedProcess:
    """Run the dedented *parts* in a fresh interpreter rooted at the repo.

    Each part is dedented SEPARATELY and then joined. Dedenting the concatenation
    takes the common prefix across both, which silently leaves the second block
    over-indented — my first cut did exactly that and the positive control failed
    with IndentationError rather than with the defect it was meant to reproduce.
    """
    body = "\n".join(textwrap.dedent(part) for part in parts)
    return subprocess.run(
        [sys.executable, "-c", body],
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        timeout=120,
    )


DENY_REALPATH = """
    import os, os.path
    def _denied(*a, **k):
        raise OSError(9, "realpath denied - emulating a host with no readable cwd")
    os.path.realpath = _denied
"""


class TestTheInstrumentBites:
    """Controls first. A denial that denies nothing turns the pin below green
    for the wrong reason."""

    def test_positive_control_inspect_stack_dies_under_the_denial(self):
        """Exercises the MECHANISM the old guard used — ``inspect.stack()``
        itself — not a re-implementation of it. If this passes, the instrument
        is not reproducing the defect and the pin below is measuring nothing."""
        result = _run(
            DENY_REALPATH,
            """
            import inspect
            try:
                inspect.stack()
                print("SURVIVED")
            except OSError:
                print("DIED")
            """,
        )
        assert "DIED" in result.stdout, f"instrument did not bite: {result.stdout!r} {result.stderr!r}"

    def test_negative_control_inspect_stack_is_fine_without_the_denial(self):
        """The same call, instrument NOT installed. If this also dies, something
        other than the denial is doing the work."""
        result = _run(
            """
            import inspect
            try:
                inspect.stack()
                print("SURVIVED")
            except OSError:
                print("DIED")
            """
        )
        assert "SURVIVED" in result.stdout, f"{result.stdout!r} {result.stderr!r}"


class TestTheGuardImportsWithoutAFilesystem:
    def test_importing_handlers_survives_a_denied_realpath(self):
        """The pin. Red against the pre-fix guard on THIS machine — measured, not
        assumed: the old shape returned ``OSError: [Errno 9] denied`` from this
        exact harness before the cure."""
        result = _run(DENY_REALPATH, f"import {TARGET}\nprint('IMPORT OK')")
        assert "IMPORT OK" in result.stdout, f"the branch guard still needs a filesystem to run:\n{result.stderr}"

    def test_importing_handlers_survives_a_denied_getcwd(self):
        """The dead-cwd world from the other direction. Passes before AND after
        the cure on Linux — kept because it is the world Windows actually
        presents, and its silence here is the evidence that ``getcwd`` was never
        the right thing to deny on this platform."""
        result = _run(
            """
            import os
            def _denied(*a, **k):
                raise OSError(2, "no cwd")
            os.getcwd = _denied
            """,
            f"import {TARGET}\nprint('IMPORT OK')",
        )
        assert "IMPORT OK" in result.stdout, result.stderr

    def test_the_ordinary_import_still_works(self):
        """A guard that refused everything would pass every denial test above."""
        result = _run(f"import {TARGET}\nprint('IMPORT OK')")
        assert "IMPORT OK" in result.stdout, result.stderr


class TestTheCureCannotBeSilentlyReverted:
    """``inspect.stack()`` is the defect, not a style preference. The ban is on
    the call, so a revert goes red here rather than on the next Windows train."""

    SOURCE = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py"

    def test_the_guard_source_is_actually_read(self):
        """Positive control for the two greps below: a wrong path would let both
        pass while reading nothing."""
        text = self.SOURCE.read_text(encoding="utf-8")
        assert "_find_real_caller" in text and "_guard_branch_access" in text

    def test_inspect_stack_is_gone_from_the_guard(self):
        """AST, not grep. The first cut asserted the STRING was absent and went
        red against a cured file — it was matching the explanation of the defect
        in the guard's own docstring. Banning a spelling instead of a shape gets
        you a rule that convicts prose and acquits code."""
        tree = ast.parse(self.SOURCE.read_text(encoding="utf-8"), filename=str(self.SOURCE))
        calls = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "stack"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "inspect"
        ]
        assert calls == [], (
            "inspect.stack() reaches os.path.realpath, which needs a readable cwd on "
            f"Windows — walk frames with sys._getframe instead (line {[c.lineno for c in calls]})"
        )

    def test_that_ban_would_convict_a_real_call(self):
        """Negative control for the rule above. An AST matcher that matches
        nothing passes on every file, including a reverted one."""
        tree = ast.parse("import inspect\ndef f():\n    return inspect.stack()\n")
        found = [
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and n.func.attr == "stack"
            and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "inspect"
        ]
        assert len(found) == 1

    def test_the_frame_walk_is_what_replaced_it(self):
        """Names the cure, so 'removed inspect and broke the guard' is not a way
        to make the test above pass."""
        text = self.SOURCE.read_text(encoding="utf-8")
        assert "sys._getframe" in text
        assert "linecache" in text, "code_context needs a replacement, not deletion"


class TestThePolicyDidNotMoveWithTheMechanism:
    """The mechanism changed; who is allowed in must not have. These call the
    guard's own helpers directly rather than through an import, so they measure
    the decision instead of the plumbing."""

    def test_an_external_caller_is_still_classified_as_external(self):
        from aipass.ai_mail.apps.handlers import _extract_branch_name

        assert _extract_branch_name("/home/x/src/aipass/devpulse/apps/thing.py") == "devpulse"
        assert _extract_branch_name("/home/x/src/aipass/ai_mail/apps/thing.py") == "ai_mail"

    def test_an_unrecognisable_path_is_unknown_not_a_branch(self):
        from aipass.ai_mail.apps.handlers import _extract_branch_name

        assert _extract_branch_name("/tmp/nowhere/thing.py") == "unknown"

    @pytest.mark.parametrize(
        "caller,allowed",
        [
            ("/home/x/src/aipass/ai_mail/apps/handlers/paths.py", True),
            ("C:\\src\\aipass\\ai_mail\\apps\\thing.py", True),
            ("/home/x/src/aipass/devpulse/apps/thing.py", False),
            ("/home/x/src/aipass/memory/apps/thing.py", False),
        ],
    )
    def test_the_membership_rule_is_unchanged_and_separator_agnostic(self, caller, allowed):
        """The rule the guard applies: is ``/ai_mail/`` in the caller path, with
        backslashes normalised first. Windows spellings included because the OS
        that found the import defect is the one that spells paths the other way."""
        from aipass.ai_mail.apps.handlers import MY_BRANCH

        assert (f"/{MY_BRANCH}/" in caller.replace("\\", "/")) is allowed


class TestLinecacheSwallowsItsOwnErrors:
    """Why the ``except OSError`` around ``linecache.getline`` survives mutation.

    Removing it changes nothing under every denial these tests can build, and
    that is not a missing pin — the except is UNREACHABLE, because linecache
    catches its own errors and returns "". A survivor that is explained by
    measurement is worth more than one explained by a comment, so the assumption
    the defensive code rests on is pinned here. If a future runtime starts
    raising, this goes red and that ``except`` becomes load-bearing.
    """

    TARGET = str(Path(__file__).resolve().parents[1] / "apps" / "handlers" / "paths.py")

    @pytest.mark.parametrize("module,attr", [("os", "stat"), ("tokenize", "open"), ("io", "open_code")])
    def test_getline_returns_empty_rather_than_raising(self, module, attr):
        result = _run(
            f"""
            import importlib, linecache
            mod = importlib.import_module({module!r})
            def _denied(*a, **k):
                raise OSError(9, "denied")
            setattr(mod, {attr!r}, _denied)
            linecache.clearcache()
            try:
                line = linecache.getline({self.TARGET!r}, 1)
                print("RETURNED", repr(line)[:20])
            except OSError:
                print("RAISED")
            """
        )
        assert "RAISED" not in result.stdout, (
            f"linecache now raises when {module}.{attr} is denied — the except in "
            "_find_real_caller is load-bearing again, and the guard needs a pin for it"
        )


class TestTheCallerIsNoneBranchRunsForReal:
    """The behavioural sibling to the AST ban, per @spawn's correction relayed
    2026-08-31: the deleted second ``inspect.stack()`` walk is unreachable from
    IMPORT-shaped pins, not unreachable full stop.

    ``apps/__init__.py`` always supplies a real-file frame, so importing the
    package can never drive ``caller_file is None``. Calling
    ``_guard_branch_access()`` DIRECTLY from a ``python -c`` child can: every
    frame is a string-pseudo or importlib, both skipped, so ``_find_real_caller``
    returns None and the branch runs. A regrown walk dies there under a realpath
    denial; the cured plain ``return`` survives.

    ``-c`` and never a script file: @commons' lesson — a world spelled too
    realistically is silently inert, because running the probe as a script makes
    every frame a real on-disk file and ``getsourcefile`` early-returns.
    """

    ARM_AND_CALL = """
    import os, os.path, sys
    _real_realpath = os.path.realpath

    # ARMING PROBE 1 — the denial actually bites. Without this the whole test
    # can pass in a world where nothing was ever denied.
    def _denied(*a, **k):
        raise OSError(9, "realpath denied")
    os.path.realpath = _denied
    import inspect
    try:
        inspect.stack()
        print("ARM1:INERT")
    except OSError:
        print("ARM1:LIVE")

    from aipass.ai_mail.apps.handlers import _find_real_caller, _guard_branch_access

    # ARMING PROBE 2 — the branch under test is the one being exercised. If a
    # real frame leaks in, the guard takes the ordinary path and the pin below
    # proves nothing about the None branch.
    caller, line = _find_real_caller()
    print("ARM2:CALLER=" + repr(caller))

    _guard_branch_access()
    print("GUARD:RETURNED")
    """

    def test_the_denial_is_live_and_the_none_branch_is_the_one_reached(self):
        """Both arming probes, asserted before the claim that depends on them."""
        result = _run(self.ARM_AND_CALL)
        assert "ARM1:LIVE" in result.stdout, f"denial inert: {result.stdout!r} {result.stderr!r}"
        assert "ARM2:CALLER=None" in result.stdout, (
            f"a real frame leaked in — the None branch was not exercised: {result.stdout!r}"
        )

    def test_the_guard_returns_instead_of_dying_there(self):
        """The claim. Red against a regrown stack walk, green against the cured
        plain return."""
        result = _run(self.ARM_AND_CALL)
        assert "GUARD:RETURNED" in result.stdout, (
            f"the caller-is-None branch still needs a filesystem:\n{result.stderr}"
        )

    def test_this_negative_control_cannot_fail_for_the_bans_reason(self):
        """@spawn's check, applied to my OWN control: their docstring control
        asserted the whole live guard file clean, so it was a second copy of the
        ban wearing a control's name — restoring the walk redded it too.

        Mine parses a synthetic source string that no edit to the guard can
        change, so it can only fail if the matcher itself stops matching. Pinned
        so a later 'simplification' to read the live file is caught.
        """
        source = Path(__file__).resolve().read_text(encoding="utf-8")
        control = source.split("def test_that_ban_would_convict_a_real_call")[1].split("def ")[0]
        assert "SOURCE" not in control and "read_text" not in control, (
            "the ban's negative control must not read the live guard file — "
            "a control that fails for the ban's reason is a second ban"
        )
