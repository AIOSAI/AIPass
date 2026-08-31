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

World A AS CONSTRUCTED HERE convicts the RESOLVE half and CANNOT convict the
inspect.stack() half. The qualifier is load-bearing - @devpulse reconciled this
with @cli's one-world claim on 2026-08-31 and the deciding variable is ABSPATH.
Deny os.getcwd, as this file does, and abspath dies with it. Give abspath
ntpath's non-raising behaviour instead and getmodule proceeds to the unguarded
realpath, so world A DOES convict stack. Both measurements are true of different
instruments. Verified here before banking:
  getcwd denied, abspath dies with it   -> STACK_LIVES
  getcwd denied, abspath left functional -> STACK_DIES
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
import subprocess
import sys
from pathlib import Path

import pytest

# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before any denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures daemon's sites only. When
# the fleet is cured these preloads can drop.
PRELOAD = """
import aipass.prax  # noqa: F401
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

APPS = Path(__file__).resolve().parents[1] / "apps"


def _run_world(denial: str) -> subprocess.CompletedProcess:
    """Run the import set in a child whose frame is <string>, never <stdin>."""
    source = PRELOAD + denial + PROBE + STACK_DIES + IMPORTS
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_world(result: subprocess.CompletedProcess, label: str, *, convicts_stack: bool) -> str:
    """Assert the imports survived, and that the world was armed for what it can prove.

    Args:
        result: The finished child process.
        label: "A" or "B", for the failure message.
        convicts_stack: Whether inspect.stack() is expected to DIE in this
            world. Measured per world, never assumed - see the module docstring.

    Returns:
        The child's stdout, so a caller can assert on the parts it owns.
    """
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

    if convicts_stack:
        # The negative control FOR the positive control: a world that cannot
        # kill the old shape proves nothing about the new one, and every import
        # assertion above it would be vacuously green.
        assert "STACK_DIES" in out, (
            f"world {label}: inspect.stack() SURVIVED the denial, so this world "
            "cannot convict the shape the guard was cured of - every import "
            "assertion above is vacuous"
        )
    return out


def test_daemon_imports_survive_world_a_ntpath_emulation():
    """The resolve half: every module-level Path(__file__).resolve() is denied.

    This world does NOT convict inspect.stack() - see the module docstring and
    test_world_a_cannot_convict_inspect_stack. It is kept because it is the only
    one of the two that denies the working-directory READ itself, which is the
    condition a deleted cwd actually creates.
    """
    _assert_world(_run_world(WORLD_A), "A", convicts_stack=False)


def test_daemon_imports_survive_world_b_realpath_denied():
    """The stack half: the only world that reaches getmodule's unguarded realpath."""
    _assert_world(_run_world(WORLD_B), "B", convicts_stack=True)


def test_world_a_cannot_convict_inspect_stack():
    """Pin the asymmetry, so the two worlds are never collapsed into one.

    If this ever goes red because world A started killing inspect.stack(), the
    honest response is to tighten world A's expectation above - not to delete
    world B. If it goes red the other way round the recipe has been quietly
    simplified and the stack half of the cure lost its only instrument.
    """
    out = _assert_world(_run_world(WORLD_A), "A", convicts_stack=False)
    if "PROBE_ARMED" in out:
        assert "STACK_LIVES" in out, (
            "world A now convicts inspect.stack() - measured behaviour changed; "
            "re-measure both worlds before trusting either"
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
        for source in sorted(APPS.rglob("*.py")):
            if ".archive" in source.parts:
                continue
            for lineno in _inspect_stack_calls(source.read_text(encoding="utf-8")):
                offenders.append(f"{source.relative_to(APPS)}:{lineno}")

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
        for source in sorted(APPS.rglob("*.py")):
            if ".archive" in source.parts:
                continue
            for lineno in _module_level_resolves(source.read_text(encoding="utf-8")):
                offenders.append(f"{source.relative_to(APPS)}:{lineno}")

        assert offenders == [], "module-level .resolve() outside module_file(): " + ", ".join(offenders)

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
