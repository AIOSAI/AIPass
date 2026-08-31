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

if MODE == "A" and INJECT:
    _real_realpath = os.path.realpath

    def _windows_shaped_realpath(path, **kwargs):
        os.getcwd()
        return _real_realpath(path, **kwargs)

    def _denied_getcwd(*a, **k):
        raise _denied()

    os.path.realpath = _windows_shaped_realpath
    os.getcwd = _denied_getcwd
elif MODE == "B" and INJECT:
    def _denied_realpath(path, **kwargs):
        raise _denied()

    os.path.realpath = _denied_realpath

if CONTROL_ONLY:
    # Does this world actually deny the call the DEFECT makes? World A must
    # break Path.resolve(); world B must break inspect.stack(). A world that
    # denies neither turns every pin below vacuously green.
    if MODE == "A":
        try:
            pathlib.Path(__file__ if "__file__" in dir() else ".").resolve()
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


def _denied_realpath(path, **kwargs):
    raise FileNotFoundError(2, "No such file or directory (dead cwd)")


os.path.realpath = _denied_realpath

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


def _denied_getcwd(*a, **k):
    raise FileNotFoundError(2, "No such file or directory (dead cwd)")


os.getcwd = _denied_getcwd

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


def _denied_realpath(path, **kwargs):
    raise FileNotFoundError(2, "No such file or directory (dead cwd)")


os.path.realpath = _denied_realpath

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
