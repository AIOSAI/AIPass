# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins daemon imports against a dead working directory
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""Every daemon module must import without a readable working directory.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding):
ntpath.realpath calls the working-directory reader UNCONDITIONALLY - not only
for relative paths, the way posixpath does - and Path.resolve() routes through
it. So on Windows every module-level Path(__file__).resolve() is an import-time
working-directory read, and a process whose cwd was deleted cannot import the
module at all. inspect.stack() carries the same defect one layer down:
getmodule()'s os.path.realpath sits outside every try in that function.

THE MASK, and why the count in this docstring is worth keeping. Before the cure
all 35 importable daemon modules died, and they all died at the SAME line - the
handlers guard's inspect.stack(). Curing the guard alone took it to 25 dead, and
those 25 all died at the SECOND mask, json_handler's _DAEMON_ROOT. A count taken
before the top mask is cured measures the mask, not the tree: measure, cure,
RE-measure. Final state 36/36 importing in both worlds.

TWO WORLDS, AND THEY ARE NOT REDUNDANT - measured here, not assumed:
  A - ntpath emulation: os.path.realpath is wrapped to read the working
      directory first, then that reader is denied.
  B - os.path.realpath denied outright while the working directory still
      reads.

WORLD A'S STACK OUTCOME IS PLATFORM-DEPENDENT, and the qualifier took two
corrections to get right. The deciding variable is ABSPATH:

  POSIX - posixpath.abspath calls os.getcwd() for its normalisation, so denying
      getcwd kills abspath too. inspect.getmodule then dies on the way IN, at
      getabsfile, and that call sits inside getmodule's own
      `except (TypeError, FileNotFoundError): return None`. getmodule returns
      None, inspect.stack() COMPLETES. World A cannot convict the stack half here.
  WINDOWS - ntpath.abspath rides Win32 _getfullpathname and never touches
      getcwd, so it SURVIVES the denial. getmodule proceeds past getabsfile and
      reaches the `os.path.realpath(f)` line further down - the one outside
      every try - and inspect.stack() DIES.

The history is worth keeping because the rule came out of it. Round 4 measured
the POSIX half here and wrote it as "world A cannot convict stack" - unqualified.
@cli measured the opposite in a variant that patched abspath functional, and
@devpulse reconciled the two: same world name, different instruments. That
produced the tightening "world A AS CONSTRUCTED HERE". Then round 4 shipped and
the real Windows runner redded this very pin with its own assertion text
(windows-setup, run 33431848734) - because there was one more dimension the
sentence still did not carry. The rule now reads: AS CONSTRUCTED HERE, ON THIS
PLATFORM. A measurement is of an instrument AND a platform, and naming only the
instrument is how a true sentence travels somewhere it is false.

The pin did exactly what it was built to do - it went red the moment the
measured behaviour stopped matching, on the platform that could show it. It is
now a TABLE rather than a single expectation; see STACK_IN_WORLD_A.
Measured 2026-08-31: denying os.getcwd also kills os.path.abspath, so
inspect.getmodule dies on its way IN, at getabsfile - and that call sits inside
`except (TypeError, FileNotFoundError): return None`. getmodule returns None,
inspect.stack() completes, and a guard still calling it would pass world A for
the wrong reason. World B leaves the working directory readable, so getabsfile
succeeds and execution reaches the `os.path.realpath(f)` line further down
getmodule - the one outside every try. That is the only world of the two that
kills inspect.stack(), and it is why the fleet recipe names both.

The asymmetry is asserted per world below rather than papered over, and
test_world_a_cannot_convict_inspect_stack pins it so nobody collapses the two
worlds into one and quietly loses the stack half of the cure.

Both injections happen in a CHILD process before any aipass import, so no module
has cached the real functions, and the child rides a <string> frame (python -c).
<string> is load-bearing and NOT interchangeable with <stdin>: linecache caches
<stdin> content, so a <stdin> probe can resolve names the real defect cannot and
report green on unfixed code (@hooks' finding).

STACK_DIES / PROBE_ARMED runs before any assertion. Where the interpreter's own
pathlib never routes resolve() through os.path.realpath (3.10 resolves absolute
paths without touching the working directory), the denial cannot fire and the
probe says so - the pin still asserts the imports succeed there, it just proves
less. Pinned as a probe with both outcomes, never a skipif: the vacuous world is
named in the output, and vacuity is asserted to occur only on interpreters where
it is the truth.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before any denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures daemon's sites only. When
# the fleet is cured these preloads can drop.
PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import aipass.cli.apps.modules.display  # noqa: F401
"""

# The denial, world A: what ntpath.realpath does on Windows.
WORLD_A = """
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

# The denial, world B: realpath itself is gone, abspath still works.
WORLD_B = """
import os


def _denied_realpath(*args, **kwargs):
    raise FileNotFoundError(2, "realpath denied (no working directory)", "")


os.path.realpath = _denied_realpath
"""

# Does THIS interpreter's resolve() reach the denied call for an absolute path?
# 3.11+ routes through os.path.realpath; 3.10 resolves absolute paths without
# the working directory, so the denial cannot fire there.
PROBE = """
import pathlib
import sys

try:
    pathlib.Path(pathlib.__file__).resolve()
    sys.stdout.write("PROBE_VACUOUS\\n")
except FileNotFoundError:
    sys.stdout.write("PROBE_ARMED\\n")
"""

# inspect.stack() must be observed dying in this world, or a guard that still
# called it would pass for the wrong reason. This is the negative control FOR
# the positive control: an instrument that cannot kill the old shape proves
# nothing about the new one.
STACK_DIES = """
import inspect
import sys


def _pseudo_frame_probe():
    return inspect.stack()


try:
    _pseudo_frame_probe()
    sys.stdout.write("STACK_LIVES\\n")
except OSError:
    sys.stdout.write("STACK_DIES\\n")
"""

IMPORTS = """
import sys

import aipass.daemon.apps.handlers  # noqa: F401
import aipass.daemon.apps.handlers.module_root  # noqa: F401
import aipass.daemon.apps.handlers.json.json_handler  # noqa: F401
import aipass.daemon.apps.handlers.schedule.discovery  # noqa: F401
import aipass.daemon.apps.handlers.schedule.runstate  # noqa: F401
import aipass.daemon.apps.handlers.schedule.rotation  # noqa: F401
import aipass.daemon.apps.handlers.schedule.telegram_notifier  # noqa: F401
import aipass.daemon.apps.handlers.monitoring.activity_collector  # noqa: F401
import aipass.daemon.apps.handlers.monitoring.inbox_scanner  # noqa: F401
import aipass.daemon.apps.handlers.monitoring.memory_health  # noqa: F401
import aipass.daemon.apps.handlers.monitoring.red_flag_detector  # noqa: F401
import aipass.daemon.apps.handlers.monitoring.report_generator  # noqa: F401
import aipass.daemon.apps.handlers.update.data_loader  # noqa: F401
import aipass.daemon.apps.modules.run  # noqa: F401
import aipass.daemon.apps.modules.rotation  # noqa: F401
import aipass.daemon.apps.modules.inbox_sweep  # noqa: F401
import aipass.daemon.apps.modules.activity_report  # noqa: F401
import aipass.daemon.apps.modules.queue  # noqa: F401
import aipass.daemon.apps.modules.update  # noqa: F401
import aipass.daemon.apps.modules.timer_install  # noqa: F401
import aipass.daemon.apps.modules.wakeup_ops  # noqa: F401
import aipass.daemon.apps.daemon  # noqa: F401
import aipass.daemon.apps.daemon_wakeup  # noqa: F401

sys.stdout.write("IMPORTED\\n")
"""

# Whether world A's denial reaches the unguarded realpath inside getmodule, by
# platform. Keyed on os.name because the deciding variable - which abspath
# implementation is in play - is exactly what os.name selects.
#
# PROVENANCE, stated because the two halves are not equally strong:
#   "posix" is MEASURED LIVE by this file on every POSIX run. If it is wrong,
#       this test fails here, today.
#   "nt" is DERIVED FROM A CI FAILURE - windows-setup run 33431848734, where the
#       previous single-expectation form of this pin failed on the Windows
#       runner carrying its own assertion text. That red IS the Windows
#       measurement; no one has stepped through ntpath by hand. It becomes
#       measured-live the first time this file runs green on a Windows box.
STACK_IN_WORLD_A = {
    "posix": "STACK_LIVES",
    "nt": "STACK_DIES",
}

_BRANCH = Path(__file__).resolve().parents[1]
APPS = _BRANCH / "apps"

# tools/ is swept too, and that is a correction rather than completeness for its
# own sake. Round 4 named tools/verify_branch.py as a deliberate EXCLUSION - the
# reasoning was that nothing imports it, so it cannot take an import down, and
# that reasoning still holds. What it missed is that the file is a TOOL a person
# runs, and a tool that dies on its own first line because the working directory
# is gone is broken exactly when someone is trying to diagnose something.
# @spawn measured it and found five branches carrying five different md5s of
# this file - pasted, never distributed, so there is no upstream to fix.
# A sweep scoped to apps/ could never have caught it.
#
# tools/ IS GITIGNORED (.gitignore:57, a blanket `tools/` rule), so it exists on
# a developer machine and NOT in a fresh clone. The roots list therefore names
# it unconditionally - that is a fact about what this branch sweeps - while the
# sweep itself skips roots that are not on disk. Requiring the directory to
# EXIST would be a pin that encodes today's machine and goes red on CI, which is
# a species this branch has shipped before (S51: two live-fleet pins broke the
# hour the fleet grew).
SWEPT_ROOTS = (APPS, _BRANCH / "tools")


def _sweepable(root: Path):
    """Python files under *root*, or nothing if the root is not on this machine."""
    if not root.is_dir():
        return []
    return [f for f in sorted(root.rglob("*.py")) if ".archive" not in f.parts]


def _run_world(denial: str) -> subprocess.CompletedProcess:
    """Run the import set in a child whose frame is <string>, never <stdin>."""
    source = PRELOAD + denial + PROBE + STACK_DIES + IMPORTS
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_world(result: subprocess.CompletedProcess, label: str, *, expect_stack: str) -> str:
    """Assert the imports survived, and that the world behaved exactly as tabled.

    expect_stack is the EXACT token required, not a boolean, and both directions
    are asserted. That is a fix for a surviving mutant: with a boolean, only the
    STACK_DIES direction was ever checked, so neutering the table comparison left
    the whole file green on POSIX - the platform whose entry is STACK_LIVES. An
    expectation that can only fail one way is half an expectation.

    Args:
        result: The finished child process.
        label: "A" or "B", for the failure message.
        expect_stack: "STACK_DIES" or "STACK_LIVES" - what inspect.stack() must
            do in this world on THIS platform. Measured per world and per
            platform, never assumed; see STACK_IN_WORLD_A.

    Returns:
        The child's stdout, so a caller can assert on the parts it owns.
    """
    assert expect_stack in ("STACK_DIES", "STACK_LIVES"), expect_stack
    out = result.stdout
    assert "IMPORTED" in out, (
        f"world {label}: import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    )

    if "PROBE_VACUOUS" in out:
        # Allowed only where it is the interpreter's truth (pre-3.11 pathlib
        # never routes an absolute resolve through os.path.realpath).
        assert sys.version_info < (3, 11), (
            f"world {label}: resolve() survived the denial on an interpreter that "
            "routes through os.path.realpath - the instrument is broken, not the world"
        )
        return out

    assert "PROBE_ARMED" in out, f"world {label}: probe reported neither outcome: {out}"

    # The negative control FOR the positive control, asserted in BOTH directions.
    # STACK_DIES missing where expected means the world cannot convict the shape
    # the guard was cured of, and every import assertion above it is vacuous.
    # STACK_LIVES missing where expected means the world became more hostile than
    # it was measured to be, and the table is now describing something else.
    observed = "STACK_DIES" if "STACK_DIES" in out else "STACK_LIVES" if "STACK_LIVES" in out else None
    assert observed is not None, f"world {label}: the stack probe reported neither outcome:\n{out}"
    assert observed == expect_stack, (
        f"world {label} on os.name={os.name!r}: inspect.stack() {observed}, table "
        f"says {expect_stack}. If {expect_stack} was STACK_DIES, this world can no "
        "longer convict the cured shape and the import assertions above are "
        "vacuous; if it was STACK_LIVES, the world got more hostile than measured. "
        "Either way: re-measure both worlds on this platform before trusting either."
    )
    return out


def test_daemon_imports_survive_world_a_ntpath_emulation():
    """The resolve half: every module-level Path(__file__).resolve() is denied.

    Whether this world ALSO convicts inspect.stack() depends on the platform -
    see STACK_IN_WORLD_A and the module docstring. It is kept on both platforms
    because it is the only one of the two that denies the working-directory READ
    itself, which is the condition a deleted cwd actually creates.
    """
    _assert_world(_run_world(WORLD_A), "A", expect_stack=STACK_IN_WORLD_A[os.name])


def test_daemon_imports_survive_world_b_realpath_denied():
    """The stack half, and the one world that convicts it on EVERY platform.

    World B leaves the working directory readable and denies os.path.realpath
    outright, so abspath succeeds on posixpath and ntpath alike and getmodule
    always reaches the unguarded realpath. That platform-independence is why it
    is the load-bearing instrument for the stack half, and why world A's
    per-platform table below is a fact to record rather than a gap to fill.
    """
    _assert_world(_run_world(WORLD_B), "B", expect_stack="STACK_DIES")


def test_world_a_stack_outcome_matches_the_platform_table():
    """Pin world A's stack outcome to the table, so the two worlds stay distinct.

    This test earned its keep: in its previous single-expectation form it went
    RED on the Windows CI runner carrying its own assertion text, which is how
    the platform dimension was found at all. The table is the fix; the pin is
    unchanged in purpose.

    A red here means the observed behaviour left the table on THIS platform.
    The honest response is to re-measure both worlds on this platform and
    correct the entry - never to delete world B, and never to widen the
    assertion until it cannot fail. Which entry is measured live and which is
    derived from CI is recorded on STACK_IN_WORLD_A itself.
    """
    expected = STACK_IN_WORLD_A.get(os.name)
    if expected is None:
        pytest.skip(f"no measured world-A stack outcome for os.name={os.name!r} - add one rather than guessing")

    # The comparison itself lives in _assert_world, which asserts the exact
    # token in BOTH directions. A second copy here was removed rather than kept:
    # a mutant proved it unkillable, and an assertion no mutant can kill is
    # decoration that makes the file look better covered than it is.
    _assert_world(_run_world(WORLD_A), "A", expect_stack=expected)


def test_the_platform_table_covers_the_platforms_this_fleet_runs_on():
    """A table with a hole reads green by skipping - so the hole is a test.

    AIPass CI runs Linux, macOS (both os.name == 'posix') and Windows
    ('nt'). If either key disappears, the skip above would quietly retire the
    pin on the platform whose CI failure created the table in the first place.
    """
    assert set(STACK_IN_WORLD_A) == {"posix", "nt"}, STACK_IN_WORLD_A
    assert set(STACK_IN_WORLD_A.values()) <= {"STACK_LIVES", "STACK_DIES"}, STACK_IN_WORLD_A
    assert os.name in STACK_IN_WORLD_A, (
        f"this machine is os.name={os.name!r} and the table has no entry - the pin is skipping rather than measuring"
    )


# ---------------------------------------------------------------------------
# The structural pin. @trigger measured why this is required: restoring the
# deleted inspect.stack() walk left 1058 tests green, because the
# caller-is-None branch it sat in is unreachable from any import-shaped world.
# Only a parse of the file convicts it.
# ---------------------------------------------------------------------------


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every inspect.stack() call in *source*, by parse.

    An AST matcher, never a string scan: the guard's own docstring NAMES
    inspect.stack() while explaining the defect, and a spelling ban would
    convict the explanation while acquitting the code - which is how a cure
    ends up undocumented.
    """
    tree = ast.parse(source)
    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stack"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "inspect"
    ]


class TestTheGuardNeverCallsInspectStack:
    def test_the_guard_is_free_of_inspect_stack(self):
        guard = (APPS / "handlers" / "__init__.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(guard) == [], (
            "inspect.stack() is back in the guard - it needs a readable working "
            "directory on Windows before any of the guard's own code runs "
            "(getmodule's os.path.realpath sits outside any try)"
        )
        assert "import inspect" not in [line.strip() for line in guard.splitlines()], (
            "the guard imports inspect again - nothing in the cured shape needs it"
        )

    def test_the_json_handler_caller_walk_is_free_of_inspect_stack(self):
        """The runtime half. log_operation runs on essentially every tick."""
        handler = (APPS / "handlers" / "json" / "json_handler.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(handler) == [], (
            "inspect.stack() is back in _get_caller_module_name - the audit line "
            "would take its own caller down on a Windows box with no working directory"
        )

    def test_no_daemon_module_calls_inspect_stack(self):
        """The sweep, so the next copy of the template line is caught at birth."""
        offenders = []
        for root in SWEPT_ROOTS:
            for source in _sweepable(root):
                for lineno in _inspect_stack_calls(source.read_text(encoding="utf-8")):
                    offenders.append(f"{source.relative_to(_BRANCH)}:{lineno}")

        assert offenders == [], "inspect.stack() calls in daemon: " + ", ".join(offenders)

    def test_the_matcher_convicts_a_real_call(self):
        """Positive control - a ban that convicts nothing reads green forever."""
        assert _inspect_stack_calls("import inspect\nframes = inspect.stack()\n") == [2]

    def test_the_matcher_clears_prose_that_names_the_defect(self):
        """Docstring negative control - the red that would rewrite the cure's own comments."""
        assert _inspect_stack_calls('"""inspect.stack() is banned here."""\n') == [], (
            "a docstring explaining the cure is not the defect; convicting it is how cures go unexplained"
        )

    def test_the_matcher_clears_an_unrelated_stack_attribute(self):
        """numpy.stack shape - the attribute name alone must not convict."""
        assert _inspect_stack_calls("import numpy\nnumpy.stack([])\n") == []

    def test_the_matcher_clears_inspect_signature(self):
        """rotation.py legitimately calls inspect.signature; only .stack is banned."""
        assert _inspect_stack_calls("import inspect\ninspect.signature(f)\n") == []


# ---------------------------------------------------------------------------
# The resolve half of the same species, banned at parse level for the same
# reason: a module-level Path(__file__).resolve() is an import-time
# working-directory read, and no import-shaped pin can name WHICH line did it.
# ---------------------------------------------------------------------------


def _module_level_resolves(source: str) -> list:
    """Lines calling .resolve() at MODULE level (outside any def/class).

    Only module level: a resolve inside a function is reached when the function
    is called, and module_file() itself must be allowed to make the call it
    exists to guard.
    """
    tree = ast.parse(source)
    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(node):
                nested.add(id(child))

    return [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "resolve"
        and id(node) not in nested
    ]


class TestNoModuleLevelResolveSurvives:
    def test_every_module_level_resolve_routes_through_module_file(self):
        offenders = []
        for root in SWEPT_ROOTS:
            for source in _sweepable(root):
                for lineno in _module_level_resolves(source.read_text(encoding="utf-8")):
                    offenders.append(f"{source.relative_to(_BRANCH)}:{lineno}")

        assert offenders == [], "module-level .resolve() outside module_file(): " + ", ".join(offenders)

    def test_the_roots_list_still_names_tools(self):
        """The roots list is a fact about the code, so it is pinned like one.

        The apps/-only scope is exactly what let tools/verify_branch.py stand
        uncured through round 4. This goes red if tools/ is dropped from the
        sweep - which is a code change someone makes - and stays green when the
        directory is merely absent, which is what a fresh clone looks like,
        because tools/ is gitignored.
        """
        assert APPS in SWEPT_ROOTS, "apps/ dropped out of the sweep"
        assert _BRANCH / "tools" in SWEPT_ROOTS, "tools/ dropped out of the sweep"

    def test_the_sweep_reads_tools_when_it_is_present(self):
        """And when the directory IS here, it must actually be read.

        Skipped rather than failed where tools/ is absent: on CI that absence is
        the truth (gitignored), and a pin that fails for it would be asserting a
        fact about the machine. The skip states which world it saw.
        """
        tools = _BRANCH / "tools"
        if not tools.is_dir():
            pytest.skip("tools/ is not on this machine - gitignored, so a fresh clone has none")

        assert _sweepable(tools), "tools/ is present but the sweep reads no Python from it"

    def test_the_matcher_convicts_the_shape_that_was_cured(self):
        """Positive control - the exact pre-cure line, from json_handler.py:35."""
        assert _module_level_resolves(
            "from pathlib import Path\n_DAEMON_ROOT = Path(__file__).resolve().parents[3]\n"
        ) == [2]

    def test_the_matcher_clears_a_resolve_inside_a_function(self):
        """module_file()'s own guarded call must not be convicted."""
        assert _module_level_resolves("from pathlib import Path\n\n\ndef f(p):\n    return Path(p).resolve()\n") == []

    def test_the_matcher_clears_prose_that_names_the_defect(self):
        assert _module_level_resolves('"""Path(__file__).resolve() is the defect."""\n') == []


# ---------------------------------------------------------------------------
# module_file()'s own contract. Added because a mutant SURVIVED: forcing the
# fallback on every call left all fourteen pins above green. Every one of them
# asks "did the import survive", and the unresolved spelling imports perfectly
# well - so nothing was measuring the reason .resolve() is called at all. A
# permanently-degraded resolver would have shipped silently.
# ---------------------------------------------------------------------------


class TestModuleFileResolvesWhenItCan:
    def test_a_healthy_world_gets_a_resolved_path(self, tmp_path):
        """The symlink is the point: resolving is why the call exists."""
        from aipass.daemon.apps.handlers.module_root import module_file

        real = tmp_path / "real"
        real.mkdir()
        target = real / "mod.py"
        target.write_text("", encoding="utf-8")
        link = tmp_path / "link.py"
        link.symlink_to(target)

        assert module_file(str(link)) == target.resolve()

    def test_the_fallback_is_reached_only_on_oserror(self, tmp_path, monkeypatch):
        """And when reached, it still names the right file - absolutely."""
        from aipass.daemon.apps.handlers import module_root

        target = tmp_path / "mod.py"
        target.write_text("", encoding="utf-8")

        def denied(self, *args, **kwargs):
            raise OSError(2, "no working directory")

        monkeypatch.setattr(Path, "resolve", denied)

        result = module_root.module_file(str(target))

        assert result == target
        assert result.is_absolute(), "the fallback returned a path that names nowhere in particular"

    def test_the_fallback_never_raises_when_the_diagnostic_lane_is_down(self, tmp_path, monkeypatch):
        """The world that denies the filesystem can deny the logger too.

        This pin found a real defect: the first cut called logger.debug from
        module_file() itself, outside every try, so a failing logger turned the
        survivable import into a crash - inside the guard written to prevent
        exactly that crash.
        """
        from aipass.daemon.apps.handlers import module_root

        target = tmp_path / "mod.py"
        target.write_text("", encoding="utf-8")

        def denied(self, *args, **kwargs):
            raise OSError(2, "no working directory")

        raising = _RaisingLogger()
        monkeypatch.setattr(Path, "resolve", denied)
        monkeypatch.setattr(module_root, "logger", raising)

        # Control: the stand-in really does raise, so a green below is not green
        # because the injection did nothing.
        with pytest.raises(RuntimeError):
            module_root.logger.debug("probe")

        result = module_root.module_file(str(target))

        assert result == target
        assert raising.calls, "the diagnostic lane was never reached - the pin proved nothing"

    def test_the_fallback_never_raises_when_the_audit_write_fails(self, tmp_path, monkeypatch):
        """json_handler unavailable is the other half of the same bare world."""
        from aipass.daemon.apps.handlers import module_root

        target = tmp_path / "mod.py"
        target.write_text("", encoding="utf-8")

        def denied(self, *args, **kwargs):
            raise OSError(2, "no working directory")

        def exploding_import(*args, **kwargs):
            raise RuntimeError("the audit lane is down too")

        monkeypatch.setattr(Path, "resolve", denied)
        monkeypatch.setattr(module_root, "__import__", exploding_import, raising=False)

        from aipass.daemon.apps.handlers.json import json_handler

        def exploding_log(*args, **kwargs):
            raise RuntimeError("the audit lane is down too")

        monkeypatch.setattr(json_handler, "log_operation", exploding_log)

        with pytest.raises(RuntimeError):
            json_handler.log_operation("probe", {})

        assert module_root.module_file(str(target)) == target


class _RaisingLogger:
    """A logger whose every call fails - the worst world module_file can meet.

    Counts its calls, so a test can tell "the diagnostic lane was exercised and
    swallowed" apart from "the diagnostic lane was never reached".
    """

    def __init__(self):
        self.calls = []

    def _fail(self, *args, **kwargs):
        self.calls.append(args)
        raise RuntimeError("logging is down")

    debug = _fail
    warning = _fail
    info = _fail
    error = _fail
