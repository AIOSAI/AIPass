# ===================AIPASS====================
# META DATA HEADER
# Name: tests/test_dead_cwd_imports.py
# Date: 2026-08-31
# Version: 1.0.0
# Category: canary/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-31): Windows dead-cwd import defect — two-world subprocess
#     pins, live-injection controls, and the AST ban on inspect.stack
#
# CODE STANDARDS:
#   - Error handling: Use error handler system (apps/handlers/error/)
# =============================================

"""Pins for the Windows dead-cwd import defect (FPLAN round 4).

THE DEFECT. ntpath.realpath reads os.getcwd() UNCONDITIONALLY, while
posixpath reads it only for relative paths. Path.resolve() routes through
realpath. So on Windows any resolve REACHED AT IMPORT makes the module
unimportable in a process whose cwd is unreadable. The discriminator is
reached-at-import, not written-at-module-scope — which is why these pins
RUN the import in a child rather than grepping for the spelling.

TWO WORLDS, because one cannot convict both species:

  World A  wraps realpath to read the cwd first (emulating ntpath on this
           POSIX box), then denies os.getcwd. Convicts a raw Path.resolve().
           It CANNOT convict inspect.stack: denying getcwd also kills
           os.path.abspath, so inspect.getmodule dies at getabsfile INSIDE
           its own except clause and stack() completes green for the wrong
           reason (measured by @daemon, reproduced here).

  World B  denies os.path.realpath directly and leaves abspath working.
           Convicts inspect.stack() via getmodule's unguarded realpath at
           inspect.py:1009.

Measured against canary's own tree on 2026-08-31, BEFORE the cure:
World A convicted handlers/__init__.py:16 (the raw resolve) and World B
convicted handlers/__init__.py:15 (inspect.stack) — two species in one
function — with json_handler.py:23 masked underneath both.

Every child probe rides a '<string>' pseudo-frame via python -c. NEVER
stdin: linecache caches stdin, and the probe would lie green (@hooks).
"""

import ast
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

BRANCH_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BRANCH_ROOT.parents[2]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

# Every importable module in canary's tree.
CANARY_MODULES = [
    "aipass.canary",
    "aipass.canary.apps",
    "aipass.canary.apps.canary",
    "aipass.canary.apps.handlers",
    "aipass.canary.apps.handlers.paths",
    "aipass.canary.apps.handlers.json",
    "aipass.canary.apps.handlers.json.json_handler",
    "aipass.canary.apps.modules",
    "aipass.canary.apps.plugins",
]

# Non-optional cross-branch imports, preloaded in the healthy world so the
# denial convicts canary's own code rather than a sibling's. None of these
# sits behind try/except ImportError, so preloading them stops testing
# nothing that was under test (@flow's rule: a preload is a claim you stop
# testing).
PRELOAD = [
    "aipass.cli.apps.modules",
    "aipass.prax",
    "aipass.aipass.shared.json_handler",
]

_WORLD_A = """
import os, os.path
_real = os.path.realpath
def realpath(p, *a, **k):
    os.getcwd()
    return _real(p, *a, **k)
os.path.realpath = realpath
def _dead_cwd(*a, **k):
    raise FileNotFoundError(2, "No such file or directory")
os.getcwd = _dead_cwd
"""

_WORLD_B = """
import os, os.path
def _dead_realpath(*a, **k):
    raise FileNotFoundError(2, "No such file or directory")
os.path.realpath = _dead_realpath
"""

WORLDS = {"A": _WORLD_A, "B": _WORLD_B}


def _run_child(body: str) -> subprocess.CompletedProcess:
    """Run body in a child interpreter on a '<string>' pseudo-frame."""
    return subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO_ROOT),
    )


def _import_probe(module: str, world: str, inject: bool = True) -> subprocess.CompletedProcess:
    """Import `module` under `world`. inject=False kills the injection."""
    body = (
        "".join(f"import {m}\n" for m in PRELOAD) + (WORLDS[world] if inject else "") + f"import {module}\n"
        "print('PROBE_OK')\n"
    )
    return _run_child(body)


@pytest.mark.parametrize("module", CANARY_MODULES)
@pytest.mark.parametrize("world", sorted(WORLDS))
def test_module_imports_with_no_readable_cwd(module, world):
    """Every canary module imports in a process whose cwd is unreadable."""
    result = _import_probe(module, world)
    assert "PROBE_OK" in result.stdout, f"{module} failed to import in world {world}:\n{result.stderr[-2000:]}"


@pytest.mark.parametrize("world", sorted(WORLDS))
def test_the_injection_is_live(world):
    """POSITIVE CONTROL: the denial actually denies.

    Without this, a typo in the injection turns every pin above into a
    vacuous green — the modules would 'survive' a world that was never
    hostile. Runs the exact construct the defect used.
    """
    body = WORLDS[world] + (
        "from pathlib import Path\n"
        "try:\n"
        "    Path(__file__ if '__file__' in dir() else '/etc/hostname').resolve()\n"
        "    print('CONTROL_DEAD')\n"
        "except OSError:\n"
        "    print('CONTROL_LIVE')\n"
    )
    result = _run_child(body)
    assert "CONTROL_LIVE" in result.stdout, (
        f"world {world} injection did not deny resolve — every pin in this "
        f"file is vacuous until it does:\n{result.stdout}\n{result.stderr[-1000:]}"
    )


@pytest.mark.parametrize("world", sorted(WORLDS))
def test_control_catches_a_dead_injection(world):
    """NEGATIVE CONTROL FOR THE POSITIVE CONTROL (@spawn's instrument).

    Kill the injection and the liveness probe must report CONTROL_DEAD. A
    control that cannot say NO proves nothing when it says YES.
    """
    body = (
        "from pathlib import Path\n"
        "try:\n"
        "    Path('/etc/hostname').resolve()\n"
        "    print('CONTROL_DEAD')\n"
        "except OSError:\n"
        "    print('CONTROL_LIVE')\n"
    )
    result = _run_child(body)
    assert "CONTROL_DEAD" in result.stdout, (
        "with no injection the probe still reported a denial — the probe is "
        f"not measuring the injection:\n{result.stdout}\n{result.stderr[-1000:]}"
    )


# The world-A/inspect.stack outcome is PLATFORM-DEPENDENT, and the deciding
# fact is whether os.path.abspath survives a getcwd denial:
#
#   POSIX    posixpath.abspath calls os.getcwd() for a relative path, so the
#            denial kills it. getabsfile raises inside getmodule's OWN except,
#            getmodule returns None, and inspect.stack() never reaches the
#            unguarded realpath at inspect.py:1009 -> STACK SURVIVES.
#            MEASURED HERE, live, by test_world_a_abspath_outcome below.
#
#   WINDOWS  ntpath.abspath rides the Win32 _getfullpathname and never touches
#            getcwd, so it SURVIVES the denial. getmodule proceeds to realpath
#            - which world A wraps to read getcwd first - and it dies there
#            -> STACK DIES. Windows convicts inspect.stack naturally, which is
#            why the platform found this defect and POSIX did not.
#            MEASURED ON CI, not here: this pin's own round-4 assertion text
#            came back red from windows-setup on 28ee90d5 (run 33431848734).
#            That failure IS the measurement; canary has no Windows box.
#
# Neither outcome is a bug. World B exists because the POSIX half cannot
# convict inspect.stack; on Windows world A already does. Deleting either
# branch of this table retires a live measurement on one platform.

STACK_SURVIVES_WORLD_A = os.name != "nt"


def test_world_a_abspath_outcome_is_the_mechanism():
    """The fact the table above turns on, measured on whatever platform runs.

    Asserting the mechanism rather than only the outcome means a future
    interpreter that changes the abspath/getcwd coupling reds HERE, naming
    the cause, instead of reding the stack pin with no explanation.
    """
    body = _WORLD_A + (
        "import os, os.path\n"
        "try:\n"
        "    os.path.abspath('rel.py')\n"
        "    print('ABSPATH_SURVIVED')\n"
        "except OSError:\n"
        "    print('ABSPATH_DIED')\n"
    )
    result = _run_child(body)
    expected = "ABSPATH_DIED" if os.name != "nt" else "ABSPATH_SURVIVED"
    assert expected in result.stdout, (
        f"on {os.name}, world A's getcwd denial was expected to produce "
        f"{expected} from os.path.abspath. If this changed, the two-world "
        f"split and the stack table below both need re-deriving, not "
        f"deleting:\n{result.stdout}\n{result.stderr[-800:]}"
    )


def test_world_a_stack_outcome_matches_the_platform_table():
    """world A convicts inspect.stack on Windows and not on POSIX.

    Round 4 pinned the POSIX half as universal. It is not: windows-setup
    turned this assertion red on the real platform, which is the pin doing
    its job on a world it had never run in. The table is per-platform now.
    """
    body = _WORLD_A + (
        "import inspect\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    expected = "STACK_SURVIVED" if STACK_SURVIVES_WORLD_A else "STACK_DIED"
    assert expected in result.stdout, (
        f"world A on {os.name} was expected to produce {expected} from "
        f"inspect.stack(). See the platform table above: re-derive the table "
        f"rather than deleting the pin, and check "
        f"test_world_a_abspath_outcome_is_the_mechanism first — it names the "
        f"cause:\n{result.stdout}\n{result.stderr[-800:]}"
    )


def test_the_windows_half_of_the_table_reproduces_here():
    """Run the WINDOWS branch's mechanism on this platform, whatever it is.

    The table's Windows row would otherwise be an untested claim on every
    machine canary can actually run on — true today because CI said so, and
    unfalsifiable here forever after. The deciding fact is abspath surviving
    the getcwd denial, and that is emulable: patch abspath to ignore the cwd
    exactly as ntpath's _getfullpathname does, keep world A otherwise
    intact, and inspect.stack() must then die at the unguarded realpath.

    This does NOT make canary a Windows box and is not evidence about the
    real platform — @daemon and @cli measured the same reconciliation
    directly. It pins the CAUSAL LINK the table asserts, so the Windows row
    cannot quietly stop being true between CI runs.
    """
    body = _WORLD_A + (
        "import os, os.path, inspect\n"
        "os.path.abspath = lambda p, *a, **k: p if p.startswith('/') else '/fake/' + p\n"
        "try:\n"
        "    os.path.abspath('rel.py')\n"
        "    print('ABSPATH_SURVIVED')\n"
        "except OSError:\n"
        "    print('ABSPATH_DIED')\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    assert "ABSPATH_SURVIVED" in result.stdout, (
        "the ntpath emulation did not take — this pin proves nothing until "
        f"abspath survives:\n{result.stdout}\n{result.stderr[-800:]}"
    )
    assert "STACK_DIED" in result.stdout, (
        "with abspath surviving the getcwd denial, inspect.stack() was "
        "expected to die at inspect.py:1009 — that causal link is the whole "
        f"reason the Windows row of the table reads STACK_DIES:\n{result.stdout}"
    )


def test_world_b_does_convict_inspect_stack():
    """The other half of the same claim: world B is the one that convicts."""
    body = _WORLD_B + (
        "import inspect\n"
        "try:\n"
        "    inspect.stack()\n"
        "    print('STACK_SURVIVED')\n"
        "except OSError:\n"
        "    print('STACK_DIED')\n"
    )
    result = _run_child(body)
    assert "STACK_DIED" in result.stdout, (
        "world B no longer convicts inspect.stack — it is the only world that "
        f"can, so this pin failing means the species is unmeasured:\n{result.stdout}"
    )


# ---------------------------------------------------------------------------
# THE PIN-SHAPE HOLE (mandatory AST ban)
# ---------------------------------------------------------------------------
# @trigger measured that the deleted second walk is UNREACHABLE from any
# import-shaped pin — apps/__init__.py always supplies a real-file frame, so
# restoring the defect leaves every behavioural test green (reproduced in
# hooks, drone, api and backup). Only a source-shape pin can catch it.
# It is an AST ban, never a string ban: the docstring above legitimately
# names inspect.stack while explaining the defect.


def _inspect_stack_calls(source: str) -> list:
    """Return line numbers of every inspect.stack() CALL in source."""
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
    """BAN: the import guard must never call inspect.stack().

    inspect builds a FrameInfo per frame and getmodule() calls
    os.path.realpath outside any try (inspect.py:1009), so one call makes
    every consumer's import depend on a readable cwd.
    """
    offenders = _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8"))
    assert offenders == [], (
        f"inspect.stack() called at {GUARD_FILE}:{offenders} — walk frames "
        "with sys._getframe instead; see this module's docstring."
    )


def test_ast_ban_convicts_a_real_call():
    """POSITIVE CONTROL: the ban detects the construct it bans."""
    assert _inspect_stack_calls("import inspect\nx = inspect.stack()\n") == [2]


def test_ast_ban_ignores_the_name_in_a_docstring():
    """NEGATIVE CONTROL: prose naming inspect.stack() is not a call.

    This is why the ban is an AST walk and not a grep — the guard's own
    docstring explains the defect by name.
    """
    source = '"""Do not call inspect.stack() here."""\nx = 1\n'
    assert _inspect_stack_calls(source) == []


def test_ast_ban_ignores_an_unrelated_stack_attribute():
    """NEGATIVE CONTROL: numpy.stack is a different function entirely."""
    source = "import numpy\ny = numpy.stack([1, 2])\n"
    assert _inspect_stack_calls(source) == []


# ---------------------------------------------------------------------------
# THE QUIET SPECIES (live-cwd pins)
# ---------------------------------------------------------------------------
# A crash is the loud half. The quiet half is a path that resolves FINE to the
# WRONG place: the import succeeds, every not-crash assertion above passes, and
# the branch writes wherever the shell happened to stand. Mutant M6 (helper
# returns Path.cwd() instead of the raw spelling) is killed by world A but
# SURVIVES world B, where getcwd still works — so the loud pins alone would
# have shipped it. These pins run from a foreign cwd and check the VALUE.
#
# This matters more here than elsewhere: _CANARY_ROOT feeds _JSON_DIR, which is
# the directory canary WRITES into. A cwd-derived value there means probe
# output lands wherever the caller stood, not in the branch.


@pytest.mark.parametrize("foreign_cwd", [tempfile.gettempdir(), str(Path.home())])
def test_json_dir_is_branch_derived_not_cwd_derived(foreign_cwd):
    """The handler's write destination must not follow the caller's cwd."""
    body = (
        "import aipass.canary.apps.handlers.json.json_handler as jh\n"
        "print('JSON_DIR=' + str(jh._JSON_DIR))\n"
        "print('ROOT=' + str(jh._CANARY_ROOT))\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", body],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=foreign_cwd,
    )
    assert result.returncode == 0, result.stderr[-1500:]
    reported = dict(line.split("=", 1) for line in result.stdout.strip().splitlines() if "=" in line)
    assert reported["ROOT"] == str(BRANCH_ROOT), (
        f"_CANARY_ROOT followed the caller's cwd ({foreign_cwd}): got {reported['ROOT']}, expected {BRANCH_ROOT}"
    )
    assert reported["JSON_DIR"] == str(BRANCH_ROOT / "canary_json"), (
        f"_JSON_DIR followed the caller's cwd ({foreign_cwd}): "
        f"got {reported['JSON_DIR']} — canary would write its test data there"
    )


def test_module_file_returns_an_absolute_path_when_resolve_fails():
    """The fallback spelling is absolute, so callers can still take .parents.

    Since Python 3.9 __file__ is absolute, which is what makes returning the
    raw spelling a correct answer rather than a degraded one. If that ever
    stops holding, parents[3] silently indexes a shorter path.
    """
    body = _WORLD_B + (
        "import aipass.canary.apps.handlers.paths as P\n"
        "p = P.module_file(r'" + str(GUARD_FILE) + "')\n"
        "print('ABS=' + str(p.is_absolute()))\n"
        "print('VAL=' + str(p))\n"
    )
    result = _run_child(body)
    assert "ABS=True" in result.stdout, result.stdout + result.stderr[-1000:]
    assert f"VAL={GUARD_FILE}" in result.stdout, result.stdout


# ---------------------------------------------------------------------------
# THE BEHAVIOURAL SIBLING for the caller-is-None branch
# ---------------------------------------------------------------------------
# CORRECTION TO THIS FILE'S ROUND-4 CLAIM. I reported that the AST ban was the
# ONLY instrument able to watch the deleted second walk. That was too strong,
# and @spawn measured the correction: the branch is unreachable from
# IMPORT-shaped pins (apps/__init__.py always supplies a real-file frame, so
# caller_file is never None on an import), but it IS reachable by calling
# _guard_branch_access() DIRECTLY from a python -c child — every frame is then
# string-pseudo or importlib, both skipped, so _find_real_caller returns None
# and the branch runs. Under a realpath denial a regrown walk dies there; the
# cured plain return survives.
#
# Both instruments are kept. The AST ban needs no subprocess and names the
# defect precisely; this one proves the cured branch actually behaves.


def test_caller_is_none_branch_survives_a_realpath_denial():
    """Call the guard directly, with no real-file frame, under world B.

    Two arming probes first, because this pin is worthless if the world is
    not hostile or if the branch under test never ran:
      probe 1 — the denial bites (realpath raises).
      probe 2 — _find_real_caller() really returned None, so the guard took
                the caller-is-None path and not some other early return.

    ON PROBE 2 AND ITS MUTANT, recorded rather than left as a gap. Deleting
    probe 2 leaves this pin green (mutant M10 survives), because in TODAY's
    world the caller genuinely is None — it is an equivalent mutant here.
    It is not decorative: measured 2026-08-31, if _find_real_caller returns a
    KIN path instead, the guard still returns — via the kin early-return, the
    wrong reason entirely — and without probe 2 this pin passes vacuously
    while the branch it names is never executed. Probe 2 is what makes the
    pin's subject provable, so it stays.
    """
    body = (
        "".join(f"import {m}\n" for m in PRELOAD)
        + "import aipass.canary.apps.handlers as H\n"
        + _WORLD_B
        + "import os.path\n"
        "try:\n"
        "    os.path.realpath('x')\n"
        "    print('ARM1_DENIAL_INERT')\n"
        "except OSError:\n"
        "    print('ARM1_DENIAL_BITES')\n"
        "print('ARM2_CALLER=' + repr(H._find_real_caller()[0]))\n"
        "H._guard_branch_access()\n"
        "print('GUARD_RETURNED')\n"
    )
    result = _run_child(body)
    assert "ARM1_DENIAL_BITES" in result.stdout, (
        f"world B was inert — this pin proves nothing:\n{result.stdout}\n{result.stderr[-800:]}"
    )
    assert "ARM2_CALLER=None" in result.stdout, (
        f"_find_real_caller did not return None, so the caller-is-None branch was never exercised:\n{result.stdout}"
    )
    assert "GUARD_RETURNED" in result.stdout, (
        "the guard raised on the caller-is-None path under a realpath denial "
        f"— a frame walk has regrown there:\n{result.stdout}\n"
        f"{result.stderr[-1200:]}"
    )
