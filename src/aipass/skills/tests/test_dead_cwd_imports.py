# ===================AIPASS====================
# META DATA HEADER
# Name: test_dead_cwd_imports.py - Dead-cwd import pins
# Date: 2026-08-31
# Version: 1.0.0
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-31): Windows round 4 - every skills module must import
#     with an unreadable working directory, in two denial worlds
#
# CODE STANDARDS:
#   - Measures by RUNNING in a child process, never by grepping spellings
# =============================================

"""
Every skills module must import when the working directory is unreadable.

THE DEFECT. ``ntpath.realpath`` calls ``os.getcwd()`` on its first lines
UNCONDITIONALLY - before it checks whether the path is even relative.
``posixpath.realpath`` reads the cwd only for relative paths, which is why this
was invisible on Linux for as long as it existed. ``Path.resolve()`` routes
through realpath, so on Windows every ``Path(__file__).resolve()`` REACHED AT
IMPORT is an import-time crash for a process whose directory was deleted or
whose network share dropped. Not "degrades" - cannot import.

WHY TWO WORLDS. They convict different constructions and neither is sufficient:

  World A - take the Windows reading of realpath (call getcwd first), then deny
            getcwd. Convicts a raw ``Path.resolve()`` reached at import.
            It CANNOT convict ``inspect.stack()``: denying getcwd kills
            abspath, so ``getmodule`` dies inside ``getabsfile`` where inspect
            already catches it, and stack() completes green for the wrong
            reason.
  World B - deny ``os.path.realpath`` outright and leave abspath working.
            Convicts ``inspect.stack()`` through getmodule's UNGUARDED
            ``os.path.realpath`` at inspect.py:1009.

WHY SUBPROCESSES. The defect is import-time. A module already in
``sys.modules`` cannot demonstrate it, and the denial has to be installed
before the first import rather than around it.

WHY ``python -c`` AND NOT STDIN. A probe piped through stdin gets cached by
linecache under the ``<stdin>`` key, and the probe then lies green. The child
rides a string-pseudo frame instead.
"""

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from dead_cwd_world import (  # noqa: E402
    ACCESSOR_SHAPE,
    NATIVE_PATHS,
    NT_EMULATED_PLATFORM,
    POSIX_EMULATED_PLATFORM,
    WORLD_A,
    WORLD_B,
    WORLD_GETCWD_DENIED,
)

SRC_ROOT = Path(__file__).resolve().parents[3]
BRANCH_ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"


def _skills_modules() -> list:
    """Every importable skills module, by dotted name.

    Returns:
        list[str]: Dotted module names, tests and templates excluded.
    """
    mods = []
    for path in sorted((SRC_ROOT / "aipass" / "skills").rglob("*.py")):
        rel = path.relative_to(SRC_ROOT)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if {"tests", "__pycache__", "templates"} & set(rel.parts):
            continue
        parts = list(rel.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods.append(".".join(parts))
    return mods


SKILLS_MODULES = _skills_modules()

# The child probe. Rides a <string> frame; each denial raises a FRESH exception
# instance - a single reused instance accumulates __traceback__ frames across
# raises and the blame it reports is then the instrument's, not the tree's.
_PROBE = r"""
import os
import os.path
import sys

MODE = sys.argv[1]
TARGET = sys.argv[2]
CONTROL_ONLY = TARGET == "__control__"

# Preloaded in the HEALTHY world: machinery the denial is not aimed at. Kept
# deliberately small - a preload is a claim you stop testing.
import json, linecache, importlib, inspect, pathlib  # noqa
import aipass.prax  # noqa - another branch, not the thing measured


def _denied():
    return FileNotFoundError(2, "No such file or directory (dead cwd)")


INJECT = os.environ.get("SKILLS_PROBE_INJECT", "1") == "1"

# The worlds are defined ONCE, in tests/dead_cwd_world.py, and injected here as
# TEXT because the world has to exist before the module under test is imported.
# They patch pathlib's pre-3.11 _NormalAccessor as well as the module name: the
# accessor CAPTURED its copy when pathlib was first imported, so on 3.10 a bare
# module rebind patches a name nothing reads again and the world never arms.
if INJECT and MODE in ("A", "B"):
    exec(os.environ["SKILLS_WORLD_TEXT"])

if CONTROL_ONLY:
    # Does this world actually deny the call the DEFECT makes? World A must
    # break Path.resolve(); world B must break inspect.stack(). A world that
    # denies neither turns every pin below vacuously green.
    if MODE == "A":
        # ABSOLUTE, deliberately. posixpath.realpath reads the cwd for any
        # RELATIVE path regardless of what is patched, so a probe using "."
        # reports LIVE for the path's shape rather than for the world - it was
        # doing exactly that here until 2026-08-31.
        try:
            pathlib.Path(os.path.abspath(os.sep)).joinpath("probe").resolve()
        except OSError:
            print("CONTROL_LIVE")
            sys.exit(0)
    elif MODE == "B":
        try:
            inspect.stack()
        except OSError:
            print("CONTROL_LIVE")
            sys.exit(0)
    elif MODE == "healthy":
        print("CONTROL_LIVE")
        sys.exit(0)
    print("CONTROL_DEAD")
    sys.exit(3)

try:
    __import__(TARGET)
except Exception as exc:  # noqa: BLE001 - the measurement IS the exception
    import traceback

    frames = traceback.extract_tb(exc.__traceback__)
    ours = [f for f in frames if "/aipass/skills/" in f.filename.replace("\\", "/")]
    frame = ours[-1] if ours else (frames[-1] if frames else None)
    where = "unknown"
    if frame is not None:
        rel = frame.filename.replace("\\", "/").split("/aipass/skills/")[-1]
        where = "%s:%d" % (rel, frame.lineno)
    print("RED %s %s %s: %s" % (TARGET, where, type(exc).__name__, exc))
    sys.exit(1)
print("OK %s" % TARGET)
"""


def _run_probe(mode: str, target: str, inject: bool = True):
    """Import one module in a child process under a denial world.

    Args:
        mode: "healthy", "A", or "B".
        target: Dotted module name, or "__control__" for the control probe.
        inject: False kills the injection - the negative control for the
            positive control.

    Returns:
        subprocess.CompletedProcess: The child's result.
    """
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env["SKILLS_PROBE_INJECT"] = "1" if inject else "0"
    env["SKILLS_WORLD_TEXT"] = {"A": WORLD_A, "B": WORLD_B}.get(mode, "")
    # The suite sets AIPASS_TEST_LOG_DIR, and log_streamer returns on it BEFORE
    # its resolve. Inheriting it here made reverting that site survive every
    # pin — a measurement that quietly stopped reaching the code it measures.
    env.pop("AIPASS_TEST_LOG_DIR", None)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; exec(compile(sys.argv[3], '<string>', 'exec'))",
            mode,
            target,
            _PROBE,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=120,
    )


# ---------------------------------------------------------------------------
# Controls first: a pin whose world is not live reports nothing at all
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["A", "B"])
def test_denial_world_is_live(mode):
    """Each world must actually deny the call the defect makes."""
    result = _run_probe(mode, "__control__")
    assert "CONTROL_LIVE" in result.stdout, (
        f"world {mode} did not deny its target call; every pin below would be "
        f"vacuously green. stdout={result.stdout!r} stderr={result.stderr[-400:]!r}"
    )


@pytest.mark.parametrize("mode", ["A", "B"])
def test_control_can_say_no(mode):
    """Kill the injection and the control must REPORT it, not pass anyway.

    The negative control for the positive control. Without this, a control
    that always prints CONTROL_LIVE would certify a dead world.
    """
    result = _run_probe(mode, "__control__", inject=False)
    assert "CONTROL_DEAD" in result.stdout, (
        f"world {mode} control reported live with the injection removed - it "
        f"cannot detect a dead world. stdout={result.stdout!r}"
    )


def test_healthy_world_imports_everything():
    """Baseline: with no denial, every module imports.

    A red here is a broken tree, not a dead-cwd finding, and it would make the
    denial worlds unreadable.
    """
    failures = [(m, _run_probe("healthy", m)) for m in SKILLS_MODULES]
    red = [(m, r.stdout.strip() or r.stderr.strip()[-300:]) for m, r in failures if r.returncode != 0]
    assert not red, f"modules failed to import in a HEALTHY world: {red}"


# ---------------------------------------------------------------------------
# The measurement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["A", "B"])
def test_every_module_imports_with_a_dead_cwd(mode):
    """No skills module may need a readable cwd to be imported."""
    red = []
    for module in SKILLS_MODULES:
        result = _run_probe(mode, module)
        if result.returncode != 0:
            red.append(result.stdout.strip() or result.stderr.strip()[-300:])
    assert not red, (
        f"world {mode}: {len(red)} of {len(SKILLS_MODULES)} skills modules "
        f"cannot be imported with an unreadable cwd:\n" + "\n".join(red)
    )


# ---------------------------------------------------------------------------
# The pin-shape hole: the deleted second walk is unreachable from any
# import-shaped test, so restoring it leaves every behavioural pin green
# ---------------------------------------------------------------------------


def _inspect_stack_calls(source: str) -> list:
    """Find inspect.stack() calls in source, by parse tree.

    Args:
        source: Python source text.

    Returns:
        list[int]: Line numbers of every ``inspect.stack(...)`` call.
    """
    found = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id == "inspect"
        ):
            found.append(node.lineno)
    return found


def test_guard_contains_no_inspect_stack_call():
    """The guard must not call inspect.stack(), at any line.

    Behavioural pins CANNOT catch a restored ``inspect.stack()`` walk in the
    caller-is-None branch: apps/__init__.py always supplies a real-file frame,
    so that branch is unreachable from an import-shaped test and returns either
    way. Measured in trigger and reproduced in hooks, drone, api and backup.
    This is a parse-tree ban, not a string ban - the docstring above the walk
    names inspect.stack while explaining the defect.
    """
    lines = _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8"))
    assert not lines, (
        f"inspect.stack() called in {GUARD_FILE} at line(s) {lines}; it needs a "
        f"readable cwd before any of the guard's own code runs (getmodule -> "
        f"os.path.realpath, inspect.py:1009, outside any try)"
    )


def test_ast_ban_convicts_a_real_call():
    """Positive control: the ban must fire on an actual call."""
    assert _inspect_stack_calls("import inspect\nframes = inspect.stack()\n") == [2]


def test_ast_ban_ignores_a_docstring_mention():
    """Negative control: prose naming inspect.stack is not a call."""
    source = '"""We do not use inspect.stack() here, and here is why."""\nx = 1\n'
    assert _inspect_stack_calls(source) == []


def test_ast_ban_ignores_an_unrelated_stack_attribute():
    """Negative control: numpy.stack is a different function entirely."""
    source = "import numpy\narr = numpy.stack([1, 2])\n"
    assert _inspect_stack_calls(source) == []


# ---------------------------------------------------------------------------
# Runtime species: the audit trail's caller name
# ---------------------------------------------------------------------------


_CALLER_MODULE = r"""
from aipass.skills.apps.handlers.json import json_handler


def log_operation():
    return json_handler._get_caller_module_name()


def a_named_caller():
    return log_operation()
"""

# The child denies realpath, then imports the module above FROM A <string>
# FRAME. That frame is what convicts inspect.stack(): getsourcefile() returns
# early for a filename that exists on disk and never reaches getmodule, so a
# stack of nothing but real files does NOT need realpath. Put one pseudo-frame
# underneath and getmodule runs, hits os.path.realpath at inspect.py:1009
# outside any try, and dies. This is why the dispatch specifies a
# string-pseudo frame: without it the pin passes over the live defect.
_CALLER_DRIVER = r"""
import os
import os.path
import sys


def _denied_realpath(*a, **k):
    raise FileNotFoundError(2, "No such file or directory (dead cwd)")


os.path.realpath = _denied_realpath

# Pre-3.11 pathlib captured its realpath at class creation, so a bare module
# rebind leaves the world inert on 3.10. Takes any arguments because a plain
# function on a class arrives BOUND - the accessor is passed as self.
import pathlib as _pl

if hasattr(_pl, "_NormalAccessor"):
    _pl._NormalAccessor.realpath = staticmethod(_denied_realpath)

sys.path.insert(0, sys.argv[1])
import a_named_module

# inspect memoises filename -> module name, and a cache HIT returns before
# getmodule reaches os.path.realpath. Cold is the world a fresh process has.
import inspect

inspect.modulesbyfile.clear()
inspect._filesbymodname.clear()

print("CALLER=%s" % a_named_module.a_named_caller())
"""


def test_caller_module_name_survives_and_still_answers(tmp_path):
    """The caller name must survive a dead cwd AND still name the caller.

    Returning "unknown" for every caller also satisfies a does-not-crash
    assertion, and it destroys the audit trail while doing so — so this
    asserts the ANSWER, not merely the absence of a crash.

    The caller lives in a real file (a ``<string>`` frame has no module name to
    report, so the pin could not tell a working answer from a degraded one),
    and it is driven from a ``<string>`` frame (without a pseudo-frame in the
    stack, inspect.stack() never reaches the realpath that convicts it).
    """
    (tmp_path / "a_named_module.py").write_text(_CALLER_MODULE, encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env.pop("AIPASS_TEST_LOG_DIR", None)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; exec(compile(sys.argv[2], '<string>', 'exec'))",
            str(tmp_path),
            _CALLER_DRIVER,
        ],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, f"caller-name probe crashed: {result.stderr[-800:]}"
    assert "CALLER=a_named_module" in result.stdout, f"caller name degraded under a dead cwd: {result.stdout!r}"


# ---------------------------------------------------------------------------
# Skills-specific: the search paths a skill unit resolves at RUNTIME
#
# Skill units run in host processes this branch did not choose - the telegram
# relay, cron-fired lanes, hook subprocesses - which are exactly the processes
# likely to hold a deleted or disconnected working directory. Import-time pins
# cannot see these: both sites are inside functions.
# ---------------------------------------------------------------------------


_RUNTIME_PROBE = r"""
import os
import sys

from aipass.skills.apps.handlers import creator_handler, discovery_handler


# THE 3.10 FAILURE lived here as a private copy of the denial. It rebound
# os.getcwd only, and before 3.11 Path.cwd() is cls(cls._accessor.getcwd()) -
# the copy the accessor CAPTURED when pathlib was first imported. The world
# never armed on that leg, production behaved normally, and both pins below
# asserted a refusal that had no cause to happen. The world now comes from the
# ONE definition in tests/dead_cwd_world.py, so it cannot drift again.
exec(os.environ["SKILLS_WORLD_TEXT"])
import pathlib as _pl

# An arming probe must ask the call ITS OWN world denies (@seedgo's rule).
try:
    _pl.Path.cwd()
except OSError:
    print("ARMED_CWD=1")
else:
    print("ARMED_CWD=0")

labels = [label for _path, label in discovery_handler.get_search_paths()]
print("SEARCH_PATHS=%s" % ",".join(labels))

result = creator_handler.create_skill("probe-skill", "markdown_only")
print("CREATE_SUCCESS=%s" % result["success"])
print("CREATE_ERROR_MENTIONS_CWD=%s" % ("working directory" in (result["error"] or "")))
"""


def _run_runtime_probe():
    """Exercise the cwd-derived runtime paths with getcwd denied."""
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env.pop("AIPASS_TEST_LOG_DIR", None)
    env["SKILLS_WORLD_TEXT"] = WORLD_GETCWD_DENIED
    return subprocess.run(
        [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", _RUNTIME_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )


def test_skill_discovery_survives_a_dead_cwd():
    """Discovery must keep serving global and builtin skills without a cwd.

    "The current project" has no answer when there is no current directory, so
    that ONE search path drops out. Taking all of discovery down with it would
    make every `drone @skills list/info/run` fail in the host processes most
    likely to hit this.
    """
    result = _run_runtime_probe()
    assert result.returncode == 0, f"runtime probe crashed: {result.stderr[-800:]}"
    assert "ARMED_CWD=1" in result.stdout, (
        f"Path.cwd() did not raise, so the world never armed and this pin asserts nothing: {result.stdout!r}"
    )
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("SEARCH_PATHS=")][0]
    labels = line.split("=", 1)[1].split(",")
    assert "project" not in labels, f"the un-answerable path was still offered: {labels}"
    assert "global" in labels and "builtin" in labels, f"discovery lost paths it could still resolve: {labels}"


def test_skill_creation_refuses_rather_than_guessing():
    """Creating into "the current project" must REFUSE, not write elsewhere.

    Unlike discovery this path writes. A default target that cannot be computed
    has to fail loudly: scaffolding a skill into the wrong tree is worse than
    scaffolding none.
    """
    result = _run_runtime_probe()
    assert result.returncode == 0, f"runtime probe crashed: {result.stderr[-800:]}"
    assert "ARMED_CWD=1" in result.stdout, (
        f"Path.cwd() did not raise, so the world never armed and this pin asserts nothing: {result.stdout!r}"
    )
    assert "CREATE_SUCCESS=False" in result.stdout, f"creation did not refuse without a cwd: {result.stdout!r}"
    assert "CREATE_ERROR_MENTIONS_CWD=True" in result.stdout, f"refusal did not name the reason: {result.stdout!r}"


# ---------------------------------------------------------------------------
# The caller-is-None branch, measured by BEHAVIOUR as well as by parse tree
#
# The round-4 guidance said only an AST ban can watch this branch. That was too
# strong, and spawn measured the correction: the branch is unreachable from
# IMPORT-shaped pins (apps/__init__.py always supplies a real-file frame), but
# calling _guard_branch_access() DIRECTLY from a -c child reaches it - every
# frame is then string-pseudo or importlib, both skipped, so _find_real_caller
# returns None and the branch runs. A regrown inspect.stack() walk dies there
# under a realpath denial; the cured plain return survives.
#
# The AST ban stays: it needs no subprocess and names the defect precisely.
# This is its behavioural sibling, not its replacement.
# ---------------------------------------------------------------------------


_NONE_BRANCH_PROBE = r"""
import os
import os.path
import sys

import aipass.skills.apps.handlers as guard


def _denied_realpath(*a, **k):
    raise FileNotFoundError(2, "No such file or directory (dead cwd)")


os.path.realpath = _denied_realpath

# Pre-3.11 pathlib captured its realpath at class creation, so a bare module
# rebind leaves the world inert on 3.10. Takes any arguments because a plain
# function on a class arrives BOUND - the accessor is passed as self.
import pathlib as _pl

if hasattr(_pl, "_NormalAccessor"):
    _pl._NormalAccessor.realpath = staticmethod(_denied_realpath)

# ARMING PROBE 1 - the denial actually bites the call the defect makes. A world
# spelled too realistically (running this as a script, where every frame is a
# real on-disk file and getsourcefile early-returns) leaves the denial inert
# and turns the assertion below vacuously green.
import inspect

inspect.modulesbyfile.clear()
inspect._filesbymodname.clear()
try:
    inspect.stack()
except OSError:
    print("ARMED_DENIAL=1")
else:
    print("ARMED_DENIAL=0")

# ARMING PROBE 2 - we are really in the caller-is-None branch, not some other
# path that happens to return quietly.
caller_file, _line = guard._find_real_caller()
print("ARMED_NONE=%s" % (1 if caller_file is None else 0))

guard._guard_branch_access()
print("GUARD_RETURNED=1")
"""


def test_caller_is_none_branch_returns_without_a_readable_cwd():
    """Reaching the caller-is-None branch must not need a cwd.

    Both arming probes must report before the assertion means anything: a
    denial that does not bite, or a stack that never produced None, would make
    this pass over a live defect.
    """
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env.pop("AIPASS_TEST_LOG_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", _NONE_BRANCH_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )
    assert "ARMED_DENIAL=1" in result.stdout, (
        f"the realpath denial did not bite inspect.stack(); this pin would be "
        f"vacuously green. stdout={result.stdout!r} stderr={result.stderr[-400:]!r}"
    )
    assert "ARMED_NONE=1" in result.stdout, (
        f"_find_real_caller did not return None, so the branch under test never ran. stdout={result.stdout!r}"
    )
    assert result.returncode == 0 and "GUARD_RETURNED=1" in result.stdout, (
        f"the guard could not complete the caller-is-None branch with an unreadable cwd: {result.stderr[-800:]}"
    )


# ---------------------------------------------------------------------------
# Same family, different symptom: a WARNING emitted at MODULE IMPORT
#
# Ten imports across the denial worlds produced ten identical warnings about
# one condition and escalated a medic alert. An absent optional dependency is a
# property of the environment, not of the import - so it is reported once, at
# first use, where it names something a caller actually tried to do.
# ---------------------------------------------------------------------------


_IMPORT_WARNING_PROBE = r"""
import importlib
import sys

records = []


class _Recorder:
    def warning(self, msg, *a, **k):
        records.append(str(msg))

    def __getattr__(self, _name):
        return lambda *a, **k: None


import aipass.prax

aipass.prax.logger = _Recorder()

import aipass.skills.lib.telegram.apps.handlers.botfather_client as bfc

bfc.logger = _Recorder.__call__ if False else bfc.logger
before = len(records)

# Import the module three more times the way a fresh process would.
for _ in range(3):
    del sys.modules["aipass.skills.lib.telegram.apps.handlers.botfather_client"]
    mod = importlib.import_module(
        "aipass.skills.lib.telegram.apps.handlers.botfather_client"
    )
    mod.logger = _Recorder()

telethon_warnings = [r for r in records if "Telethon not installed" in r]
print("IMPORT_TIME_TELETHON_WARNINGS=%d" % len(telethon_warnings))
"""


def test_absent_telethon_is_not_announced_on_every_import():
    """Importing the module must not log the same environment fact each time.

    A WARNING at module scope fires once per import. Repeated across a sweep
    that imports every module in several worlds, one condition became ten
    identical records and an escalation - noise measured as severity.
    """
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env.pop("AIPASS_TEST_LOG_DIR", None)
    result = subprocess.run(
        [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", _IMPORT_WARNING_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, f"import-warning probe crashed: {result.stderr[-800:]}"
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("IMPORT_TIME_TELETHON_WARNINGS=")][0]
    assert line.endswith("=0"), f"the absent-Telethon condition is still announced at import time: {line}"


# ---------------------------------------------------------------------------
# The accessor trap, reproduced locally
#
# There is no Python 3.10 on this machine. Rather than record a derived row -
# a CI red is a NEGATIVE measurement: it proves not-unconditionally-X, never
# which value - these rebuild pre-3.11 pathlib's capture on whatever
# interpreter is running, so the discrimination CI found stays falsifiable here
# forever. Without them, dropping the accessor patch from the shipped worlds
# would go unnoticed on 3.11+ and red again on the next 3.10 leg.
# ---------------------------------------------------------------------------


_EMULATION = r"""
import os
import os.path
import pathlib

# The platform emulation is installed BEFORE the shape, so the capture below
# sees the emulated dialect. An empty string here means "this host, unchanged".
{platform}

{shape}

_acc = pathlib._NormalAccessor()


def _cwd_pre_311():
    # 3.10: Path.cwd() -> cls(cls._accessor.getcwd())
    return pathlib.Path(_acc.getcwd())


def _resolve_pre_311():
    # 3.10 Lib/pathlib.py:1077 -> s = self._accessor.realpath(self, strict=...)
    # A LITERAL, not os.path.abspath(os.sep) + "probe": building the argument
    # through the host's path module puts host behaviour inside a probe that
    # exists to measure the patch.
    #
    # HONEST RECORD, measured 2026-08-31 (M25): swapping the literal back for
    # the host-built spelling SURVIVES the whole suite. It is an EQUIVALENT
    # MUTANT, and not narrowly - the four-cell table below is flat:
    #
    #     capture     dialect   literal    host-built
    #     sentinel    posix     NO_RAISE   NO_RAISE
    #     sentinel    nt        NO_RAISE   NO_RAISE
    #     live        posix     NO_RAISE   NO_RAISE
    #     live        nt        RAISED     RAISED
    #
    # Every accessor this runs against - sentinel, denial, cwd-reading wrapper
    # - answers before it looks at the path, so the argument decides nothing
    # in any cell. The literal is therefore a PURITY rule and not a measured
    # discriminator: it is here so that no host path module is consulted
    # inside an instrument, which is the round-7 species stated as a habit.
    # It would start deciding the day a world let a real realpath run to
    # completion on this route. Recorded rather than scored as a kill,
    # because a mutation run that quietly counts it is lying.
    return _acc.realpath("/probe")


{world}

_CALL = {{"cwd": _cwd_pre_311, "resolve": _resolve_pre_311}}[os.environ.get("EMU_CALL", "cwd")]

try:
    _CALL()
except FileNotFoundError:
    print("VERDICT=RAISED")
except TypeError as exc:
    # A zero-argument replacement bound through the accessor. The world denied
    # nothing; it broke the call signature.
    print("VERDICT=TYPEERROR(%s)" % exc)
else:
    print("VERDICT=NO_RAISE")
"""

_BARE_MODULE_PATCH = "def _dead(*a, **k):\n    raise FileNotFoundError(2, 'dead cwd')\nos.getcwd = _dead\n"

# A bare module patch that ALSO gives os.path.realpath the windows shape.
# Reaches nothing the accessor captured, which is exactly the point.
_BARE_WINDOWS_MODULE_PATCH = _BARE_MODULE_PATCH + (
    "_rr = os.path.realpath\n"
    "def _reads(p, *a, **k):\n"
    "    os.getcwd()\n"
    "    return _rr(p, *a, **k)\n"
    "os.path.realpath = _reads\n"
)

_ZERO_ARG_ACCESSOR_PATCH = (
    "def _dead():\n"
    "    raise FileNotFoundError(2, 'dead cwd')\n"
    "os.getcwd = _dead\n"
    "pathlib._NormalAccessor.getcwd = _dead\n"
)

# The shape as it was WRITTEN BEFORE ROUND 7 - capturing the live host
# realpath. Kept as a named constant, not as a comment, because it is the only
# thing that makes the platform slot falsifiable: it is the one shape whose
# verdict is SUPPOSED to move with the dialect.
_LIVE_CAPTURE_SHAPE = (
    "class _NormalAccessor:\n"
    "    getcwd = staticmethod(os.getcwd)\n"
    "    realpath = staticmethod(os.path.realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)

_LAZY_SHAPE = (
    "class _NormalAccessor:\n"
    "    @property\n"
    "    def getcwd(self):\n"
    "        return os.getcwd\n"
    "    realpath = staticmethod(os.path.realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)


_PLATFORMS = {
    "host": "",
    "posix": POSIX_EMULATED_PLATFORM,
    "nt": NT_EMULATED_PLATFORM,
}


def _run_emulation(shape: str, world: str, call: str = "cwd", platform: str = "host") -> str:
    """Run the pre-3.11 accessor emulation under a given world.

    Args:
        shape: Source defining ``pathlib._NormalAccessor``.
        world: Source installing a denial.
        call: Which pre-3.11 route to exercise - "cwd" for
            ``Path.cwd() -> _accessor.getcwd()``, or "resolve" for
            ``Path.resolve() -> _accessor.realpath()``. They are patched
            separately and a world can arm one while leaving the other inert.
        platform: "host" to leave this interpreter's path module alone, or
            "posix"/"nt" to install that dialect's realpath before the shape
            captures anything. Every verdict here must be identical under all
            three - see ``test_every_accessor_verdict_is_platform_blind``.

    Returns:
        str: The child's VERDICT line.
    """
    source = _EMULATION.format(platform=_PLATFORMS[platform], shape=shape, world=world)
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env.pop("AIPASS_TEST_LOG_DIR", None)
    env["EMU_CALL"] = call
    result = subprocess.run(
        [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", source],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, f"emulation crashed: {result.stderr[-600:]}"
    return [ln for ln in result.stdout.splitlines() if ln.startswith("VERDICT=")][0]


class TestTheAccessorTrapIsReproducibleLocally:
    """Pin the 3.10 discrimination on whatever interpreter is running."""

    def test_a_bare_module_patch_does_not_reach_a_captured_accessor(self):
        """This is the defect: rebinding a name nothing reads again.

        The accessor took its copy of os.getcwd at class creation, so the
        world reports no denial at all - and every pin underneath it would be
        vacuously green.
        """
        assert _run_emulation(ACCESSOR_SHAPE, _BARE_MODULE_PATCH) == "VERDICT=NO_RAISE"

    def test_the_shipped_world_does_reach_a_captured_accessor(self):
        """The cure, measured against the same emulation.

        Same shape, same call, different world text - and this one arms. That
        difference IS the fix; without it this pin and the one above would
        agree and neither would mean anything.
        """
        assert _run_emulation(ACCESSOR_SHAPE, WORLD_A) == "VERDICT=RAISED"

    def test_a_zero_argument_denial_breaks_the_call_instead_of_denying_it(self):
        """A plain function on a class arrives BOUND - the accessor is self.

        Without ``*a`` or ``staticmethod`` the replacement raises TypeError,
        not FileNotFoundError, so a pin that only asserts "it raised" passes
        for the wrong reason. Both halves are carried deliberately; either
        alone cures this, which is why neither may be deleted as redundant.
        """
        verdict = _run_emulation(ACCESSOR_SHAPE, _ZERO_ARG_ACCESSOR_PATCH)
        assert verdict.startswith("VERDICT=TYPEERROR"), verdict

    def test_the_emulation_itself_captures_eagerly(self):
        """The published shape must capture at class creation, not at read.

        A lazily-read accessor resolves the PATCHED name and would arm under
        the bare module patch - so the two pins above would stop
        distinguishing an accessor patch from a module patch, and the
        instrument would quietly stop measuring the thing it exists for.
        """
        assert _run_emulation(_LAZY_SHAPE, _BARE_MODULE_PATCH) == "VERDICT=RAISED"
        assert _run_emulation(ACCESSOR_SHAPE, _BARE_MODULE_PATCH) == "VERDICT=NO_RAISE"

    def test_the_runtime_world_also_reaches_a_captured_accessor(self):
        """The getcwd world the runtime pins use, under the same emulation.

        Its consequence exists only before 3.11, so on this interpreter no
        behavioural pin can tell the cured world from the uncured one. This is
        where that difference is measured.
        """
        assert _run_emulation(ACCESSOR_SHAPE, WORLD_GETCWD_DENIED) == "VERDICT=RAISED"

    def test_the_platform_slot_is_live(self):
        """ARMING PROBE for the litmus below - and the CI red, kept local.

        A litmus that requires verdicts NOT to move is vacuously green if the
        platform emulation never reaches the child: drop the slot, patch
        nothing, and all three runs are the same run. So one shape must be
        held whose verdict is SUPPOSED to move, and the honest choice is the
        exact shape round 6 shipped - a live capture of the host realpath.

        posix leaves an absolute path alone; nt reads the cwd before looking
        at it. Same world, same call, two answers - which IS the windows-setup
        red of round 7, reproduced on Linux and now unable to leave silently.
        """
        posix = _run_emulation(_LIVE_CAPTURE_SHAPE, _BARE_WINDOWS_MODULE_PATCH, call="resolve", platform="posix")
        nt = _run_emulation(_LIVE_CAPTURE_SHAPE, _BARE_WINDOWS_MODULE_PATCH, call="resolve", platform="nt")
        assert posix == "VERDICT=NO_RAISE", posix
        assert nt == "VERDICT=RAISED", nt
        assert posix != nt, "the platform slot reached nothing; the litmus below proves nothing"

    def test_every_accessor_verdict_is_platform_blind(self):
        """THE LITMUS: no verdict in this class may move with the platform.

        This class measures whether a PATCH reached a CAPTURED attribute. That
        question has nothing to do with which path dialect the host speaks, so
        every probe here must answer the same under a posix realpath, an nt
        realpath, and this interpreter's own - and any probe whose answer moves
        is importing behaviour it is not testing.

        It cost a windows-setup red to learn: ``ACCESSOR_SHAPE`` used to
        capture the LIVE ``os.path.realpath``, and on nt that reads the cwd on
        its own account, so a world that reached NOTHING still answered RAISED
        and the pin below convicted the host. Restore that capture and this
        pin reddens here, on Linux, without waiting for CI.
        """
        cases = [
            (ACCESSOR_SHAPE, _BARE_MODULE_PATCH, "cwd"),
            (ACCESSOR_SHAPE, WORLD_A, "cwd"),
            (ACCESSOR_SHAPE, WORLD_GETCWD_DENIED, "cwd"),
            (_LAZY_SHAPE, _BARE_MODULE_PATCH, "cwd"),
            (ACCESSOR_SHAPE, WORLD_A, "resolve"),
            (ACCESSOR_SHAPE, _BARE_WINDOWS_MODULE_PATCH, "resolve"),
        ]
        moved = []
        for shape, world, call in cases:
            verdicts = {
                platform: _run_emulation(shape, world, call=call, platform=platform)
                for platform in ("host", "posix", "nt")
            }
            if len(set(verdicts.values())) != 1:
                moved.append((call, verdicts))
        assert not moved, f"verdicts moved with the platform: {moved}"


class TestTheArmingProbeIsDialectDependent:
    """Why the world A arming probe uses an ABSOLUTE path - per dialect.

    Round 6 established this claim on posix and shipped it as universal, and
    the windows-setup leg refused it. It is TWO rows, not one, and each is
    measured here under an emulated dialect rather than derived from a CI red:

        dialect   relative probe   absolute probe
        posix     RAISED           NO_RAISE
        nt        RAISED           RAISED

    posixpath.realpath consults the cwd only to complete a RELATIVE path;
    ntpath.realpath reads it on its first lines whatever it was handed. So the
    relative probe raises in both dialects, and in neither does that raise
    mean the world armed - it means the path had a shape. That is the whole
    claim, and it is what makes an arming probe spelled "." dishonest.

    The absolute probe is where the dialects part, and the nt row is a fact
    rather than a defect: ntpath's cwd read is a module-attribute lookup, so a
    bare ``os.getcwd`` rebind reaches THROUGH a captured realpath on nt while
    being inert on posix. The pre-3.11 capture that hid a dead world on 3.10
    Linux would not have hidden it on 3.10 Windows.
    """

    _EXPECTED = {
        "posix": {"relative": "RAISED", "absolute": "NO_RAISE"},
        "nt": {"relative": "RAISED", "absolute": "RAISED"},
    }

    @staticmethod
    def _probe(platform: str, path: str) -> str:
        """Resolve one path under one emulated dialect, cwd denied."""
        source = (
            "import os\nimport os.path\n" + _PLATFORMS[platform] + _BARE_MODULE_PATCH + "try:\n"
            "    os.path.realpath(%r)\n"
            "    print('VERDICT=NO_RAISE')\n"
            "except OSError:\n"
            "    print('VERDICT=RAISED')\n" % path
        )
        env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
        env.pop("AIPASS_TEST_LOG_DIR", None)
        result = subprocess.run(
            [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", source],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(SRC_ROOT),
            timeout=60,
        )
        assert result.returncode == 0, result.stderr[-600:]
        return result.stdout.strip().split("=", 1)[1]

    @pytest.mark.parametrize("dialect", ["posix", "nt"])
    def test_a_relative_probe_raises_in_both_dialects(self, dialect):
        """The load-bearing half: "." can never report a world, only a shape.

        Both dialects, same answer, and the world here armed NOTHING the
        captured accessor reads - so a RAISED from "." is worth nothing as an
        arming signal on any platform.
        """
        assert self._probe(dialect, NATIVE_PATHS[dialect]["relative"]) == "RAISED"

    @pytest.mark.parametrize("dialect", ["posix", "nt"])
    def test_the_absolute_probe_answers_per_dialect(self, dialect):
        """The half that parts, with both rows measured on this host."""
        expected = self._EXPECTED[dialect]["absolute"]
        assert self._probe(dialect, NATIVE_PATHS[dialect]["absolute"]) == expected

    def test_a_dialect_probe_fed_the_other_dialect_spelling_measures_nothing(self):
        """Negative control for the table: the spellings are not swappable.

        Hand posix's "/probe" to the nt shape and it still raises - but for
        the shape's unconditional read, not for anything about the path. Hand
        nt's "C:\\probe" to the posix shape and it raises too, because
        posixpath does not read a drive letter as absolute. Either mix-up
        produces an all-RAISED table that looks like agreement and measures
        the SPELLING. This is why NATIVE_PATHS exists.
        """
        assert self._probe("posix", NATIVE_PATHS["nt"]["absolute"]) == "RAISED"
        assert self._probe("nt", NATIVE_PATHS["posix"]["absolute"]) == "RAISED"

    def test_the_live_host_agrees_with_its_own_dialect_row(self):
        """The emulations are stand-ins; this is the run that licenses them.

        Drives the real thing - ``pathlib.Path(p).resolve()`` on this
        interpreter, this platform, no dialect patched - and requires it to
        land on the row the table claims for ``os.name``. The day a host stops
        agreeing with its own row, the table is wrong rather than the host.
        """
        probe = (
            "import os, pathlib\n" + _BARE_MODULE_PATCH + "def _try(p):\n"
            "    try:\n"
            "        pathlib.Path(p).resolve()\n"
            "        return 'NO_RAISE'\n"
            "    except OSError:\n"
            "        return 'RAISED'\n"
            "print('REL=%s ABS=%s' % (_try(_REL), _try(_ABS)))\n"
        )
        preamble = "import os, os.path\n_REL = '.'\n_ABS = os.path.abspath(os.sep) + 'probe'\n"
        env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
        env.pop("AIPASS_TEST_LOG_DIR", None)
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))",
                preamble + probe,
            ],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(SRC_ROOT),
            timeout=60,
        )
        assert result.returncode == 0, result.stderr[-600:]
        row = self._EXPECTED[os.name if os.name in self._EXPECTED else "posix"]
        assert f"REL={row['relative']}" in result.stdout, (
            f"host {os.name} disagrees with its own table row: {result.stdout!r}"
        )
        assert f"ABS={row['absolute']}" in result.stdout, (
            f"host {os.name} disagrees with its own table row: {result.stdout!r}"
        )


class TestTheAccessorTrapResolveRoute:
    """The realpath half of the capture - Path.resolve(), not Path.cwd().

    Before 3.11 these ride DIFFERENT captured attributes, so arming one says
    nothing about the other.
    """

    def test_world_a_reaches_the_captured_accessor_on_the_RESOLVE_route(self):
        """WORLD_A patches two accessor attributes; this measures the second.

        ``Path.cwd()`` and ``Path.resolve()`` go through DIFFERENT captured
        attributes before 3.11 - ``getcwd`` and ``realpath``. Arming one says
        nothing about the other, and WORLD_A's realpath patch was unmeasured
        until a mutant removed it and the whole suite stayed green.
        """
        assert _run_emulation(ACCESSOR_SHAPE, WORLD_A, call="resolve") == "VERDICT=RAISED"

    def test_a_bare_module_patch_misses_the_resolve_route_too(self):
        """The same discrimination on the resolve route.

        Without this the pin above could pass because the world armed for some
        other reason rather than because it reached the accessor.
        """
        assert _run_emulation(ACCESSOR_SHAPE, _BARE_WINDOWS_MODULE_PATCH, call="resolve") == "VERDICT=NO_RAISE"
