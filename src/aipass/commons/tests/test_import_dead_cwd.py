# ===================AIPASS====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - commons imports without a readable cwd
# Date: 2026-08-31
# Version: 1.0.0
# Category: commons/tests
# =============================================

"""Every commons module must import without a readable working directory.

The mechanism, measured on the Windows CI gate 2026-08-31 (@memory's finding,
relayed round 4): ntpath.realpath calls os.getcwd() UNCONDITIONALLY - not only
for relative paths, the way posixpath does - and Path.resolve() routes through
it. So on Windows every Path(__file__).resolve() REACHED AT IMPORT is a
working-directory read, and a process whose cwd was deleted cannot import the
module at all. Commons carried four such sites (three module-level constants
plus the handlers guard, which reached the same call through inspect.stack()).

The world injects ntpath's behaviour as a CONDITION rather than a platform:
os.path.realpath is wrapped to read os.getcwd() first, then os.getcwd is
denied. The injection happens in a child process before any aipass import, so
no module has cached the real functions. Other branches' import-time code is
held CONSTANT by preloading it in the healthy world - this pin measures
commons' own sites, not the fleet's rollout state.

Where the interpreter's own pathlib never routes resolve() through
os.path.realpath (3.10 resolves absolute paths without touching cwd), the
denial cannot fire and the probe says so - the pin still asserts the imports
succeed there, it just proves less. Pinned as a probe with both outcomes,
never a skipif: the vacuous world is named in the output, and vacuity is
asserted to occur only on interpreters where it is the truth.
"""

import ast
import subprocess
import sys
from pathlib import Path

import pytest

# The denial, and the probe that proves the denial can actually fire.
# Shared by every world below so no world can go quietly vacuous.
_PREAMBLE = r"""
# Other branches' import-time code is held CONSTANT: preloaded in the healthy
# world, before the denial. Their dead-cwd cure is their own build (fleet
# rollout in flight, 2026-08-31); this pin measures commons' sites only.
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import rich.console  # noqa: F401
import linecache  # noqa: F401

import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument: does THIS interpreter's resolve() reach the denied
# call for an absolute path? 3.11+ routes through os.path.realpath; 3.10
# resolves absolute paths without cwd, so the denial cannot fire there.
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""

# The four sites, imported in one process. json_handler, identity_ops and db
# each build a module-level constant from Path(__file__).resolve(); reaching
# any of them also runs the package guard in apps/handlers/__init__.py.
SWEEP_WORLD = (
    _PREAMBLE
    + r"""
import aipass.commons.apps.handlers.json.json_handler  # noqa: F401
import aipass.commons.apps.handlers.identity.identity_ops  # noqa: F401
import aipass.commons.apps.handlers.database.db  # noqa: F401
import aipass.commons.apps.commons  # noqa: F401

print("IMPORTED")
"""
)

# The guard alone. Named separately because its cwd read arrives by a
# different route - inspect.stack() builds a FrameInfo per frame and
# getmodule() calls os.path.realpath() outside any try - so a cure to the
# constants would leave this red and a reader deserves to know which broke.
GUARD_WORLD = (
    _PREAMBLE
    + r"""
import aipass.commons.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)


# The same denial, shaped like ntpath rather than posixpath.
#
# NEEDED because the preamble above cannot reach the guard's OLD defect. On
# POSIX every route inspect.stack() takes to os.path.realpath runs through
# getabsfile(), whose os.path.abspath raises FileNotFoundError for the
# relative "<frozen importlib._bootstrap>" filenames an import stack carries -
# and getmodule() CATCHES FileNotFoundError, so the unguarded
# `modulesbyfile[os.path.realpath(f)]` line below it is never reached. The
# first draft of this pin went green against a reintroduced inspect.stack()
# for exactly that reason: it was measuring the module-level resolve() next
# door, not the stack walk.
#
# ntpath does not have that early raise, so on Windows getmodule() proceeds
# and dies on the unguarded realpath. Emulated here by giving abspath ntpath's
# non-raising behaviour while realpath keeps reading cwd - the injection then
# denies the call the DEFECT actually makes (@memory's rule), instead of one
# the platform happens to catch first.
_NTPATH_PREAMBLE = r"""
import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401

import os

_real_realpath = os.path.realpath
_real_abspath = os.path.abspath


def _ntpath_realpath(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


def _ntpath_abspath(path):
    # ntpath.abspath falls back rather than raising the way posixpath does.
    try:
        return _real_abspath(path)
    except OSError:
        return path


os.path.realpath = _ntpath_realpath
os.path.abspath = _ntpath_abspath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument against the defect ITSELF, not against a proxy: does
# inspect.stack() die in this world? If it does not, this pin proves nothing.
try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")
"""

# The guard, under the world its old implementation actually died in.
NTPATH_GUARD_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.commons.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        timeout=60,
    )


def _assert_probe_armed(out: str) -> None:
    """The instrument must be able to fire, or the pin proves nothing."""
    if "PROBE_VACUOUS" in out:
        # Allowed only where it is the interpreter's truth (pre-3.11 pathlib
        # never routes an absolute resolve through os.path.realpath).
        assert sys.version_info < (3, 11), (
            "resolve() survived the denial on an interpreter that routes "
            "through os.path.realpath - the instrument is broken, not the world"
        )
    else:
        assert "PROBE_ARMED" in out, f"probe printed neither outcome:\n{out}"


def test_handler_modules_import_with_dead_cwd():
    """The three module-level resolve() sites, under a denied cwd."""
    result = _run(SWEEP_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


def test_handlers_guard_imports_with_dead_cwd():
    """The package guard reaches the same cwd read through its stack walk."""
    result = _run(GUARD_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"the handlers guard died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


# ===========================================================================
# An uncured peer raises OSError at import, not ImportError
# ===========================================================================
#
# @prax's round-4 finding: while the fleet dead-cwd rollout is in flight, a
# peer branch whose guard is still uncured raises FileNotFoundError from its
# own import - an OSError, which `except ImportError` does not catch. Commons
# has 23 optional cross-branch imports (22 on @cli, 1 on @devpulse); every one
# of them would have propagated a peer's OSError and killed its own consumer.
#
# The peer is denied by a meta_path finder rather than by a dead cwd, because
# the claim is about the EXCEPTION TYPE crossing the branch boundary, not
# about how the peer came to raise it.

_DENY_PEER = r"""
import importlib.abc
import sys

DENIED = "{denied}"


class _UncuredPeer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == DENIED or fullname.startswith(DENIED + "."):
            raise FileNotFoundError(2, "uncured peer guard", "")
        return None


sys.meta_path.insert(0, _UncuredPeer())

# Prove the denial can fire before relying on it.
try:
    __import__(DENIED)
    print("DENIAL_VACUOUS")
except FileNotFoundError:
    print("DENIAL_ARMED")
except ImportError:
    print("DENIAL_WRONG_TYPE")
"""


def _peer_world(denied: str, body: str) -> str:
    return _DENY_PEER.format(denied=denied) + body


def test_modules_import_when_cli_peer_raises_oserror():
    """A module keeps its own fallback console when @cli cannot be imported."""
    world = _peer_world(
        "aipass.cli.apps.modules",
        r"""
import aipass.commons.apps.modules.post  # noqa: F401
import aipass.commons.apps.modules.feed  # noqa: F401
import aipass.commons.apps.modules.database  # noqa: F401

print("IMPORTED")
""",
    )
    result = _run(world)
    out = result.stdout

    assert "DENIAL_ARMED" in out, f"the peer denial never fired - the pin proves nothing:\n{out}"
    assert "IMPORTED" in out, (
        f"an OSError from an uncured peer escaped `except ImportError`:\nstdout={out}\nstderr={result.stderr}"
    )


def test_dashboard_writer_survives_an_oserror_from_devpulse():
    """The lazy @devpulse import degrades to None rather than raising."""
    world = _peer_world(
        "aipass.devpulse.apps.modules",
        r"""
from aipass.commons.apps.handlers.dashboard import dashboard_writer

assert dashboard_writer._get_write_section() is None, "expected the unavailable-peer fallback"

print("IMPORTED")
""",
    )
    result = _run(world)
    out = result.stdout

    assert "DENIAL_ARMED" in out, f"the peer denial never fired - the pin proves nothing:\n{out}"
    assert "IMPORTED" in out, (
        f"an OSError from an uncured peer escaped `except ImportError`:\nstdout={out}\nstderr={result.stderr}"
    )


def test_handlers_guard_survives_the_ntpath_shaped_denial():
    """
    The Item-2 pin proper: the guard must not walk inspect.stack().

    Separate from the world above because that one is satisfied by the
    module-level resolve() guard alone. This one is red against an
    inspect.stack() walk and green against the sys._getframe cure.
    """
    result = _run(NTPATH_GUARD_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, (
        "inspect.stack() survived the ntpath-shaped denial - the instrument no "
        f"longer reaches the defect and this pin is vacuous:\n{out}"
    )
    assert "IMPORTED" in out, (
        f"the handlers guard still depends on a readable cwd:\nstdout={out}\nstderr={result.stderr}"
    )


# ===========================================================================
# The entry point's sys.path repair
# ===========================================================================
#
# MEASURED 2026-08-31, and the measurement reversed the obvious conclusion.
# The first read of apps/commons.py said the .resolve() there was doing no
# work - __file__ has been absolute since 3.9, so why normalise it? - and the
# tidy cure for a Windows cwd read is to not make the call at all.
#
# Then it was measured through a symlink: CPython sets sys.path[0] to the REAL
# script directory while __file__ keeps the SYMLINKED spelling. Drop the
# resolve and the repair silently stops happening on any symlinked checkout,
# and commons.py shadows the commons package again. The resolve stays; it is
# guarded and both spellings are removed.


def test_sys_path_zero_is_the_resolved_script_dir_through_a_symlink(tmp_path):
    """
    The fact apps/commons.py's .resolve() depends on.

    Pinned because the resolve reads like dead weight - this is the evidence
    that deleting it breaks symlinked checkouts, kept next to the code that
    would break.
    """
    real = tmp_path / "real"
    real.mkdir()
    script = real / "probe.py"
    script.write_text(
        "import sys\nfrom pathlib import Path\n"
        "print(sys.path[0])\nprint(str(Path(__file__).parent))\n"
        "print(str(Path(__file__).resolve().parent))\n",
        encoding="utf-8",
    )
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # Windows without developer mode
        import pytest

        pytest.skip(f"host cannot create a directory symlink: {exc}")

    result = subprocess.run(
        [sys.executable, str(link / "probe.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    path0, unresolved, resolved = result.stdout.strip().splitlines()

    assert unresolved != resolved, "the symlink was not exercised — this run measured nothing"
    assert path0 == resolved, (
        "sys.path[0] no longer matches the RESOLVED script dir — apps/commons.py "
        "removes both spellings, but the comment explaining why resolve() is "
        "load-bearing is now wrong and should be corrected"
    )


# ===========================================================================
# json_handler's caller auto-detect - the second inspect.stack() in this tree
# ===========================================================================
#
# Found while answering the round-4 follow-up, not dispatched: _get_caller_module_name
# walked inspect.stack() to read ONE frame's filename. Same species as the guard,
# and live on every log_operation() call that does not pass module_name (which is
# most of them - the auto-detect is what names each module's log file).
#
# The world below is shaped so BOTH halves of the claim are measurable at once:
#   - a "<string>" entry frame, so the ntpath denial can actually fire (a frame
#     whose filename exists on disk short-circuits getsourcefile and the
#     instrument goes quiet - measured, see the harness note in the reply);
#   - a REAL compiled probe_caller.py as the frame the lookup reads, so the pin
#     asserts the ANSWER and not merely the absence of a crash (@aipass's rule:
#     if a probe compiles a caller frame, the frame doing the lookup must BE
#     the compiled one).

_CALLER_PROBE_WORLD = r"""
import os
import sys

probe_dir = {probe_dir!r}

# Written BEFORE the denial: a genuine module on disk, so the frame the lookup
# reads is compiled source and not a "<string>" pseudo-name.
with open(os.path.join(probe_dir, "probe_caller.py"), "w", encoding="utf-8") as fh:
    fh.write(
        "from aipass.commons.apps.handlers.json import json_handler\n"
        "def _inner():\n"
        "    return json_handler._get_caller_module_name()\n"
        "def ask():\n"
        "    return _inner()\n"
    )
sys.path.insert(0, probe_dir)

import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import rich.console  # noqa: F401
import inspect
import linecache  # noqa: F401
import probe_caller

_real_realpath = os.path.realpath
_real_abspath = os.path.abspath


def _ntpath_realpath(path, **kw):
    os.getcwd()
    return _real_realpath(path, **kw)


def _ntpath_abspath(path):
    try:
        return _real_abspath(path)
    except OSError:
        return path


os.path.realpath = _ntpath_realpath
os.path.abspath = _ntpath_abspath


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")

try:
    print("NAME:" + probe_caller.ask())
except OSError as exc:
    print("RAISED:" + type(exc).__name__)
"""


def test_caller_module_autodetect_survives_and_answers_under_a_dead_cwd(tmp_path):
    """log_operation's module auto-detect must name the caller, not raise."""
    result = _run(_CALLER_PROBE_WORLD.format(probe_dir=str(tmp_path)))
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world did not arm - this pin would pass vacuously:\n{out}\n{result.stderr}"
    assert "NAME:probe_caller" in out, (
        "the auto-detect either raised or named the wrong module under a dead "
        f"cwd:\nstdout={out}\nstderr={result.stderr}"
    )


# ===========================================================================
# Structural ban: no inspect.stack() anywhere in apps/
# ===========================================================================
#
# @devpulse's round-4 follow-up, measured fleet-wide by @trigger and reproduced
# in eight branches: the guard's DELETED second walk sat in the caller-is-None
# branch, which no import-shaped pin can reach - apps/__init__ always supplies
# a real-file frame, so that branch never runs during an import. Regrow the walk
# and every behavioural pin above stays green.
#
# A parse-tree ban, never a spelling ban: this file and the guard both NAME
# inspect.stack in prose while explaining the defect, and a string search would
# convict its own documentation.


def _inspect_stack_call_lines(source: str, filename: str) -> list:
    """Line numbers of every `inspect.stack(...)` CALL in source.

    An ast.Call whose func is Attribute 'stack' on Name 'inspect'. Prose,
    imports and any other .stack are invisible to it by construction.
    """
    tree = ast.parse(source, filename=filename)
    hits = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id == "inspect"
        ):
            hits.append(node.lineno)
    return hits


def _apps_modules() -> list:
    """Every production .py under apps/, excluding the parked pre-refactor tree."""
    apps = Path(__file__).resolve().parent.parent / "apps"
    return sorted(p for p in apps.rglob("*.py") if ".archive" not in p.parts)


def test_no_inspect_stack_call_anywhere_in_apps():
    """
    Tree-wide, because after round 4 there are zero legitimate callers left.

    The guard was cured by dispatch; json_handler's caller auto-detect was
    found and cured in the same session. Nothing in apps/ needs a FrameInfo
    per frame, so the ban costs nothing and closes the unreachable branch.
    """
    modules = _apps_modules()

    # Walk-actually-parsed control: a blinded walk that finds no files would
    # otherwise read as a clean tree.
    assert len(modules) > 60, f"the walk found only {len(modules)} modules — it is not seeing apps/"

    offenders = {}
    for path in modules:
        source = path.read_text(encoding="utf-8")
        try:
            lines = _inspect_stack_call_lines(source, str(path))
        except SyntaxError as exc:
            # Ignorance is not evidence of cleanliness.
            raise AssertionError(f"{path} could not be parsed, so it cannot be cleared: {exc}") from exc
        if lines:
            offenders[str(path.relative_to(path.parents[2]))] = lines

    assert not offenders, (
        f"inspect.stack() is back in apps/: {offenders}. It builds a FrameInfo "
        "per frame and reads os.getcwd() on Windows; use sys._getframe."
    )


def test_the_guard_specifically_carries_no_stack_walk():
    """
    Named separately from the tree-wide sweep so the failure reads plainly.

    The guard's second walk lived in the caller-is-None branch, which no
    import-shaped pin in this file can reach.
    """
    guard = Path(__file__).resolve().parent.parent / "apps" / "handlers" / "__init__.py"
    source = guard.read_text(encoding="utf-8")

    assert "inspect" in source, (
        "the guard no longer mentions inspect at all — if the explanation was "
        "deleted with the call, this pin's positive control is worth re-reading"
    )
    assert _inspect_stack_call_lines(source, str(guard)) == [], (
        "the handlers guard walks inspect.stack() again — the caller-is-None "
        "branch is invisible to every behavioural pin in this file"
    )


# --- controls, all through the REAL matcher, never a re-implementation -------


def test_the_matcher_convicts_a_planted_call_at_the_right_line():
    """POSITIVE CONTROL — without this the ban above proves nothing."""
    source = "import inspect\n\n\ndef f():\n    return inspect.stack()\n"

    assert _inspect_stack_call_lines(source, "<planted>") == [5]


def test_the_matcher_ignores_prose_naming_inspect_stack():
    """
    A spelling ban would convict this file's own docstrings, and the guard's.
    """
    source = '"""We do not use inspect.stack() here."""\n# inspect.stack() is banned\nx = 1\n'

    assert _inspect_stack_call_lines(source, "<prose>") == []


@pytest.mark.parametrize(
    "source, why",
    [
        ("import numpy\nnumpy.stack([1, 2])\n", "a different module's stack()"),
        ("import traceback\ntraceback.stack()\n", "traceback, not inspect"),
        ("self.stack()\n", "an attribute on self"),
        ("import inspect\ninspect.currentframe()\n", "currentframe is sys._getframe by another name"),
        ("import inspect\nstack = inspect.stack\n", "a reference, not a call"),
    ],
)
def test_the_matcher_leaves_legitimate_code_alone(source, why):
    """
    NEGATIVE CONTROLS — a matcher that convicts these would be unusable.

    inspect.currentframe() is deliberately legal: it is sys._getframe under
    another name and touches no filesystem.
    """
    assert _inspect_stack_call_lines(source, "<negative>") == [], f"matcher over-convicted: {why}"
