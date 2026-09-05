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
denied. Other branches' import-time code is held CONSTANT by preloading it in
the healthy world - this pin measures commons' own sites, not the fleet's
rollout state.

Pre-3.11, pathlib itself has already cached the real function by the time the
rebind below runs: _NormalAccessor.realpath is `staticmethod(os.path.realpath)`
bound at pathlib's OWN import (which the preceding aipass/rich imports trigger
transitively), and Path.resolve() calls that cached staticmethod - never a live
`os.path.realpath` lookup - so the rebind cannot reach it, for an absolute path
or a relative one. 3.11 rewrote resolve() to call `os.path.realpath(...)`
directly each time, a live attribute lookup the rebind does reach. So the
denial cannot fire below 3.11 and the probe says so - the pin still asserts the
imports succeed there, it just proves less. Pinned as a probe with both
outcomes, never a skipif: the vacuous world is named in the output, and
vacuity is asserted to occur only on interpreters where it is the truth.
"""

import ast
import os
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
# call at all? 3.11+ looks up os.path.realpath live; pre-3.11 pathlib already
# cached the original in _NormalAccessor.realpath at its own import, so the
# rebind above cannot reach it and the denial cannot fire there.
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
        # cached os.path.realpath in its own accessor before this rebind ran).
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
# Then it was measured through a symlink ON LINUX: CPython sets sys.path[0] to
# the REAL script directory while __file__ keeps the SYMLINKED spelling. Drop
# the resolve and the repair silently stops happening on a symlinked checkout,
# and commons.py shadows the commons package again.
#
# ROUND 5 CORRECTION. The first version of this pin asserted `sys.path[0] ==
# resolved` flat, on every platform, and it went RED on the Windows runner
# (28ee90d5, run 33431848734). The production cure was never wrong - commons.py
# removes BOTH spellings, so it does not care which one the host uses - but the
# PIN had turned one platform's measurement into a universal law.
#
# SPECIES VERDICT, derived rather than guessed: this is NOT drone's
# recipe-not-state case. That pin's own structure answers it - symlink
# creation is wrapped in a try that SKIPS, so a runner lacking the privilege
# would have produced a skip. CI produced a FAILURE, therefore the world was
# BUILT on Windows and only the assertion was POSIX-shaped. No marker is
# needed; the expectation table below is.
#
# Split per @canary: CAUSE (two spellings exist), OUTCOME (sys.path[0] is one
# of the two), LINK (commons.py removes both), so a future red names its own
# mechanism instead of pointing at a compound assertion.


# What sys.path[0] equals for a script invoked through a symlinked directory.
#   "resolved"   - the real directory, symlink followed
#   "unresolved" - the spelling the invocation used
#   None         - NOT MEASURED LIVE on this platform yet
#
# posix: measured live here, 2026-08-31, and re-measured on every run.
# nt:    the round-5 CI red IS the Windows measurement, and it is a NEGATIVE
#        one - it proves sys.path[0] is not unconditionally "resolved" there,
#        not which spelling it is. Left None deliberately. It becomes a live
#        measurement the first time this file runs green on Windows and
#        somebody reads the recorded values out of the outcome pin's message.
_SYS_PATH0_SPELLING = {
    "posix": "resolved",
    "nt": None,
}


def _spellings_matching(path0: str, unresolved: str, resolved: str) -> list:
    """Which of the two spellings apps/commons.py removes does sys.path[0] equal?

    Extracted from the pin that uses it so the answer is testable with
    SYNTHETIC values. The interesting cases - a third spelling, or a host
    where both spellings coincide - are unreachable on any single platform,
    and a judgement only exercised through a live probe is a judgement only
    one platform ever checks. That is the same unreachable-branch species
    round 5 exists to close, one level up.
    """
    spellings = {"resolved": resolved, "unresolved": unresolved}
    return sorted(name for name, value in spellings.items() if value == path0)


def _assert_matches_table(platform: str, matched: list, path0: str = "") -> None:
    """Hold a run against the recorded expectation for its platform.

    A None entry means "measured negatively, value unknown" - the nt case -
    and asserts nothing beyond what the outcome pin already did. Extracted so
    the DISAGREEING case is reachable: on any single platform the live probe
    always agrees with its own table row, so an assertion only ever fed live
    values is an assertion that never fails and never can.
    """
    expected = _SYS_PATH0_SPELLING[platform]
    if expected is None:
        return
    assert expected in matched, (
        f"on {platform} sys.path[0] was recorded as {expected!r} but this run "
        f"matched {matched} — the table is now wrong, and the repair may be "
        f"relying on a spelling the host stopped using. sys.path[0]={path0!r}"
    )


def _assert_probe_is_usable(probe: dict) -> None:
    """Judge a probe result. Synthetic-testable for the same reason as above."""
    if not probe["built"]:
        assert probe["reason"], "the world failed to build and did not say why"
        assert os.name == "nt", (
            f"a POSIX host could not build a symlink world: {probe['reason']} — "
            "that is a broken machine, not a platform difference"
        )
    else:
        assert probe["path0"] and probe["unresolved"] and probe["resolved"], (
            f"the probe reported success with an empty field: {probe}"
        )


def _assert_caller_is_none_world(out: str, stderr: str) -> None:
    """Judge the caller-is-None world's output. Both arming probes enforced."""
    assert "STACK_DIES" in out, f"arming probe 1: the ntpath world did not bite:\n{out}\n{stderr}"
    assert "CALLER_IS_NONE" in out, (
        "arming probe 2: the world did not reach the caller-is-None branch, so "
        f"a regrown walk there would go unwatched:\n{out}"
    )
    assert "GUARD_RETURNED" in out, (
        f"the guard raised instead of returning for a caller-less stack:\nstdout={out}\nstderr={stderr}"
    )


def _symlink_spelling_probe(tmp_path) -> dict:
    """Run a script through a symlinked directory and record what the host did.

    Returns a dict rather than skipping, so "this host cannot build the world"
    is DATA every platform asserts against instead of a silent absence.
    """
    real = tmp_path / "real"
    real.mkdir()
    (real / "probe.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "print(sys.path[0])\nprint(str(Path(__file__).parent))\n"
        "print(str(Path(__file__).resolve().parent))\n",
        encoding="utf-8",
    )
    link = tmp_path / "link"
    try:
        link.symlink_to(real, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:  # Windows without the privilege
        return {"built": False, "reason": f"{type(exc).__name__}: {exc}"}

    result = subprocess.run(
        [sys.executable, str(link / "probe.py")],
        capture_output=True,
        text=True,
        timeout=60,
    )
    lines = result.stdout.strip().splitlines()
    if len(lines) != 3:
        return {"built": False, "reason": f"probe produced {len(lines)} lines: {result.stdout!r} {result.stderr!r}"}

    path0, unresolved, resolved = lines
    return {"built": True, "reason": "", "path0": path0, "unresolved": unresolved, "resolved": resolved}


def test_this_platform_has_a_recorded_sys_path0_expectation():
    """
    A platform nobody has measured must not pass by being unlisted.

    The table carries None for "measured negatively, value unknown" - that is
    an entry. A MISSING key is the thing this refuses.
    """
    # Both platforms the fleet actually runs on must carry an entry, or a
    # mutant deleting the one this host does not use goes unnoticed.
    assert {"posix", "nt"} <= set(_SYS_PATH0_SPELLING), (
        f"the expectation table lost a known platform: {sorted(_SYS_PATH0_SPELLING)}"
    )
    assert os.name in _SYS_PATH0_SPELLING, (
        f"no recorded expectation for os.name={os.name!r} — measure it and add "
        "it to _SYS_PATH0_SPELLING rather than letting this file assert a "
        "POSIX fact on an unmeasured platform, which is exactly the round-5 red"
    )


def test_symlink_world_buildability_is_recorded(tmp_path):
    """
    CONTROL — the skip made observable.

    The old pin swallowed an unbuildable world into pytest.skip, where it read
    as "nothing to see". Here it is an assertion either way.
    """
    _assert_probe_is_usable(_symlink_spelling_probe(tmp_path))


def test_cause_a_symlinked_invocation_yields_two_spellings(tmp_path):
    """
    CAUSE — the fact that makes commons.py's .resolve() load-bearing at all.

    If __file__ and its resolved form were always the same string, removing
    one spelling would be enough and the resolve really would be dead weight.
    """
    probe = _symlink_spelling_probe(tmp_path)
    if not probe["built"]:
        return  # buildability is asserted by its own pin above

    assert probe["unresolved"] != probe["resolved"], (
        "the symlink was not exercised - this run measured nothing. "
        f"unresolved={probe['unresolved']!r} resolved={probe['resolved']!r}"
    )


def test_outcome_sys_path0_is_one_of_the_two_spellings_commons_removes(tmp_path):
    """
    OUTCOME — the claim production actually depends on, on every platform.

    commons.py removes BOTH spellings, so it does not need to know which one
    the host chose; it only needs the host to choose one of them. This is what
    the flat `== resolved` assertion should have said. The message records all
    three values, so a Windows red arrives already diagnosed.
    """
    probe = _symlink_spelling_probe(tmp_path)
    if not probe["built"]:
        return

    matched = _spellings_matching(probe["path0"], probe["unresolved"], probe["resolved"])

    assert matched, (
        "sys.path[0] is a THIRD spelling that apps/commons.py does not remove, "
        "so the shadowing repair silently does nothing here.\n"
        f"  os.name     = {os.name}\n"
        f"  sys.path[0] = {probe['path0']!r}\n"
        f"  unresolved  = {probe['unresolved']!r}\n"
        f"  resolved    = {probe['resolved']!r}"
    )

    _assert_matches_table(os.name, matched, probe["path0"])


def test_link_commons_removes_both_spellings(tmp_path):
    """
    LINK — the pin that actually protects the code, and the one that CANNOT
    fail for platform reasons.

    Whatever any host does with sys.path[0], the repair is correct as long as
    commons.py computes and removes both spellings. Source-level on purpose:
    the round-5 red came from proving this through a subprocess when it did
    not need a subprocess at all.
    """
    entry = Path(__file__).resolve().parent.parent / "apps" / "commons.py"
    source = entry.read_text(encoding="utf-8")

    assert "_script_dirs = [str(Path(__file__).parent)]" in source, (
        "the UNRESOLVED spelling is no longer collected — a host whose "
        "sys.path[0] keeps the invocation spelling is no longer repaired"
    )
    assert "_script_dirs.append(str(Path(__file__).resolve().parent))" in source, (
        "the RESOLVED spelling is no longer collected — this is the deletion the symlink measurement exists to prevent"
    )
    assert "sys.path.remove(_script_dir)" in source, "neither spelling is being removed from sys.path"


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


# ===========================================================================
# The caller-is-None branch, reached behaviourally
# ===========================================================================
#
# @devpulse's round-4 correction (relay 6be10723), measured by @spawn: the
# guidance that only an AST ban can watch this branch was TOO STRONG. It is
# unreachable from IMPORT-shaped pins - apps/__init__ always supplies a
# real-file frame, so _find_real_caller never returns None during an import,
# which is the nine-branch reproduction - but calling the guard DIRECTLY from
# a python -c child reaches it: every frame is a string pseudo-name or an
# importlib internal, both skipped, so the walk falls off the end.
#
# Kept ALONGSIDE the AST ban rather than replacing it: the ban needs no
# subprocess and names the defect precisely, this one proves the branch still
# behaves. Both die to a regrown walk, which is the point.

_CALLER_IS_NONE_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.commons.apps.handlers as guard

# ARMING PROBE 2: the world must actually exercise the caller-is-None branch.
# Without this the pin could pass by taking the same-branch return instead,
# and a regrown walk in the dead branch would never be touched.
caller_file, _ = guard._find_real_caller()
print("CALLER_IS_NONE" if caller_file is None else "CALLER_WAS:" + str(caller_file))

# The branch itself: no caller outside this file, so the guard must simply
# return. A regrown inspect.stack() walk dies here under the denial.
guard._guard_branch_access()
print("GUARD_RETURNED")
"""
)


def test_guard_returns_from_the_caller_is_none_branch_under_a_dead_cwd():
    """The branch no import-shaped pin in this file can reach."""
    result = _run(_CALLER_IS_NONE_WORLD)

    _assert_caller_is_none_world(result.stdout, result.stderr)


# ===========================================================================
# The judgements above, exercised with SYNTHETIC input
# ===========================================================================
#
# Round-5 mutant finding, in my own new pins: four mutants SURVIVED the first
# pass and every one of them mutated a branch Linux never executes - the nt
# table entry, the third-spelling case, the unbuildable-world case, an arming
# probe that never fires here. A judgement reached only through a live probe
# is a judgement exactly one platform ever checks, which is the same
# unreachable-branch species this round exists to close, one level up.
#
# So the judgements are called directly with made-up values. No subprocess, no
# symlink, no platform - every branch reachable everywhere.


@pytest.mark.parametrize(
    "path0, unresolved, resolved, expected, why",
    [
        ("/real", "/link", "/real", ["resolved"], "POSIX through a symlink — measured live"),
        ("/link", "/link", "/real", ["unresolved"], "a host that keeps the invocation spelling"),
        ("/real", "/real", "/real", ["resolved", "unresolved"], "no symlink: both spellings coincide"),
        ("/third", "/link", "/real", [], "a spelling commons.py does not remove — the repair is dead here"),
    ],
)
def test_the_spelling_matcher_answers_each_world(path0, unresolved, resolved, expected, why):
    """
    The third-spelling row is the one that matters and the one no platform
    reaches: it is the only input for which the outcome pin must FAIL.
    """
    assert _spellings_matching(path0, unresolved, resolved) == expected, why


def test_an_unbuildable_world_must_state_a_reason():
    """The unbuildable branch, reachable on a host that can build symlinks."""
    with pytest.raises(AssertionError, match="did not say why"):
        _assert_probe_is_usable({"built": False, "reason": ""})


def test_a_probe_reporting_success_with_an_empty_field_is_refused():
    """Success plus a blank value would make the outcome pin compare nothing."""
    with pytest.raises(AssertionError, match="empty field"):
        _assert_probe_is_usable({"built": True, "reason": "", "path0": "", "unresolved": "/a", "resolved": "/b"})


def test_a_usable_probe_passes_the_same_judgement():
    """POSITIVE CONTROL — the refusals above are not refusing everything."""
    _assert_probe_is_usable({"built": True, "reason": "", "path0": "/real", "unresolved": "/link", "resolved": "/real"})


@pytest.mark.parametrize(
    "out, missing",
    [
        ("CALLER_IS_NONE\nGUARD_RETURNED\n", "arming probe 1"),
        ("STACK_DIES\nGUARD_RETURNED\n", "arming probe 2"),
        ("STACK_DIES\nCALLER_IS_NONE\n", "the guard raised"),
    ],
)
def test_the_caller_is_none_judgement_needs_every_marker(out, missing):
    """
    Each marker is load-bearing: drop any one and the world proves less.

    Reachable here because the output is a string I hand it, not something a
    live child process happened to print.
    """
    with pytest.raises(AssertionError, match=missing):
        _assert_caller_is_none_world(out, "")


def test_the_caller_is_none_judgement_passes_a_complete_world():
    """POSITIVE CONTROL for the three refusals above."""
    _assert_caller_is_none_world("STACK_DIES\nCALLER_IS_NONE\nGUARD_RETURNED\n", "")


@pytest.mark.parametrize(
    "platform, matched, raises, why",
    [
        ("posix", ["resolved"], False, "the recorded POSIX answer"),
        ("posix", ["resolved", "unresolved"], False, "both spellings coincide — still contains the record"),
        ("posix", ["unresolved"], True, "POSIX stopped using the resolved spelling — the table is stale"),
        ("posix", [], True, "a third spelling — the record cannot be satisfied"),
        ("nt", ["unresolved"], False, "nt is recorded None: unknown, so nothing to contradict"),
        ("nt", [], False, "nt asserts nothing here; the outcome pin already refused this"),
    ],
)
def test_the_table_crosscheck_only_fires_where_something_was_recorded(platform, matched, raises, why):
    """
    The disagreeing rows are unreachable from any live probe.

    A live run on a given platform always agrees with its own row, so this
    check could be deleted without a single test noticing until a host
    changed behaviour years from now. Fed synthetically it has real teeth.
    """
    if raises:
        with pytest.raises(AssertionError, match="the table is now wrong"):
            _assert_matches_table(platform, matched)
    else:
        _assert_matches_table(platform, matched)


def test_the_outcome_pin_actually_calls_the_table_crosscheck():
    """
    STRUCTURAL — the call site, which no behavioural pin can reach.

    _assert_matches_table has real teeth now (fed synthetically it refuses a
    stale record), but DELETING ITS CALL from the outcome pin killed nothing:
    a live run on a healthy host always agrees with its own table row, so the
    call's absence is invisible. Same shape as the inspect.stack ban - when
    the branch cannot be executed, assert on the parse tree instead.
    """
    source = Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(source, filename=__file__)

    target = "test_outcome_sys_path0_is_one_of_the_two_spellings_commons_removes"
    functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == target]
    assert len(functions) == 1, f"expected exactly one {target}, found {len(functions)}"

    called = {
        node.func.id
        for node in ast.walk(functions[0])
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    assert "_assert_matches_table" in called, (
        "the outcome pin no longer holds its run against _SYS_PATH0_SPELLING, "
        "so the recorded per-platform expectation is decorative"
    )
    assert "_spellings_matching" in called, "the outcome pin no longer uses the matcher it is built on"
