# ===================AIPASS====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - trigger imports without a readable cwd
# Date: 2026-08-31
# Version: 1.0.0
# Category: trigger/tests
# =============================================

"""Every trigger module must import without a readable working directory.

THE MECHANISM, measured on the Windows CI gate 2026-08-31 (@memory's finding,
relayed round 4): ntpath.realpath calls os.getcwd() UNCONDITIONALLY - not only
for relative paths, the way posixpath does - and Path.resolve() routes through
it. So on Windows every Path(__file__).resolve() REACHED AT IMPORT is a
working-directory read, and a process whose cwd was deleted cannot import the
module at all.

WHY THIS BRANCH, LOUDLY. @prax reproduced it on Linux against trigger and their
traceback is the reason this file exists: prax's logger imports
discovery/watcher.py, which imports aipass.trigger.apps.modules.core, which ran
trigger's handler guard, which died on line 12. One guard in one branch took
down every consumer of prax's logger. Trigger carried eight import-time sites
plus the guard.

THE WORLD injects ntpath's behaviour as a CONDITION rather than a platform:
os.path.realpath is wrapped to read os.getcwd() first, then os.getcwd is denied.
The injection happens in a child process before any aipass import, so no module
has cached the real functions. In-process this property is unobservable - the
imports already happened - which is why every world here is a subprocess.

WHY THE PRELOAD LIST IS SHORT HERE. The fleet pattern preloads peer branches in
the healthy world so a pin measures its own branch only. Trigger cannot preload
@prax: prax's logger imports trigger, so preloading prax would import the very
sites under test in the healthy world and the pin would go green measuring
nothing. It is preloaded UNDER the denial instead, which is sound because prax's
own cure landed 2026-08-31 (verified: prax imports clean in this world). @cli was preloaded
healthy while its guard still walked inspect.stack(); that preload was retired
2026-08-31 once their cure was verified from here.
"""

import subprocess
import sys
from pathlib import Path

# Peers held constant in the healthy world, before the denial.
#
# @cli's preload was here and is RETIRED. Two facts, and the second corrects
# what this file used to claim: their guard was cured 2026-08-31 and verified
# importing clean under the ntpath world below from this branch — AND @cli is
# never reached from these worlds at all. Measured: after importing every site
# below under the denial, no aipass.cli module is in sys.modules. prax is (it is
# on trigger's import path); prax does not pull cli. So the preload was
# belt-and-braces, not load-bearing, and this file previously said otherwise.
#
# @prax is deliberately NOT preloaded and never can be — prax's logger imports
# trigger, so preloading it would import the sites under test in the HEALTHY
# world and every assert here would go green measuring nothing. Prax rides under
# the denial instead, which is sound because their own cure landed the same day.
_PRELOAD = r"""
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401
"""

# The posix-shaped denial: enough to reach every module-level resolve().
_PREAMBLE = (
    _PRELOAD
    + r"""
import os

_real_realpath = os.path.realpath


def _ntpath_condition(path, **kw):
    os.getcwd()  # ntpath.realpath reads cwd before checking absoluteness
    return _real_realpath(path, **kw)


os.path.realpath = _ntpath_condition


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument: does THIS interpreter's resolve() reach the denied call
# for an absolute path? 3.11+ routes through os.path.realpath; 3.10 resolves
# absolute paths without cwd, so the denial cannot fire there.
import pathlib

try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""
)

# The ntpath-SHAPED denial, needed to reach the guard's old defect.
#
# On POSIX every route inspect.stack() takes to os.path.realpath runs through
# getabsfile(), whose os.path.abspath raises FileNotFoundError for the relative
# "<frozen importlib._bootstrap>" filenames an import stack carries - and
# getmodule() CATCHES FileNotFoundError, so the unguarded
# `modulesbyfile[os.path.realpath(f)]` below it is never reached. A pin built on
# the preamble above therefore goes GREEN against a reintroduced inspect.stack():
# it measures the module-level resolve() next door, not the stack walk.
#
# ntpath has no such early raise, so on Windows getmodule() proceeds and dies.
# Emulated by giving abspath ntpath's non-raising behaviour while realpath keeps
# reading cwd - the injection then denies the call the DEFECT actually makes
# (@memory's rule), not one the platform happens to catch first.
_NTPATH_PREAMBLE = (
    _PRELOAD
    + r"""
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

# Probe against the defect ITSELF, not a proxy: does inspect.stack() die in this
# world? If it does not, this pin proves nothing.
import inspect

try:
    inspect.stack()
    print("STACK_SURVIVES")
except FileNotFoundError:
    print("STACK_DIES")
"""
)

# Every trigger site that resolves a path at IMPORT, named one per line so a
# failure says which module died rather than "the branch".
#
# events/plan_file.py was a fourth _find_repo_root caller and is gone: retired
# 2026-08-31 as measured inert (see apps/handlers/events/.archive/plan_file.py).
# This pin went red when it was archived, which is the list doing its job.
_SITES = r"""
import aipass.trigger.apps.handlers  # noqa: F401
print("GUARD_OK")
import aipass.trigger.apps.config  # noqa: F401
print("CONFIG_OK")
import aipass.trigger.apps.handlers.json.json_handler  # noqa: F401
print("JSON_OK")
import aipass.trigger.apps.handlers.escalation  # noqa: F401
print("ESCALATION_OK")
import aipass.trigger.apps.handlers.events.error_detected  # noqa: F401
print("ERROR_DETECTED_OK")
import aipass.trigger.apps.handlers.events.runaway_handler  # noqa: F401
print("RUNAWAY_OK")
import aipass.trigger.apps.modules.medic  # noqa: F401
print("MEDIC_OK")
import aipass.trigger.apps.modules.core  # noqa: F401
print("IMPORTED")
"""

SWEEP_WORLD = _PREAMBLE + _SITES

# The guard alone, under the world its old implementation actually died in.
NTPATH_GUARD_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.trigger.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)

# The whole branch under the ntpath world - the shape @prax's traceback took.
NTPATH_SWEEP_WORLD = _NTPATH_PREAMBLE + _SITES


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        timeout=120,
    )


def _assert_probe_armed(out: str) -> None:
    """The instrument must be able to fire, or the pin proves nothing."""
    if "PROBE_VACUOUS" in out:
        # Allowed only where it is the interpreter's truth (pre-3.11 pathlib
        # never routes an absolute resolve through os.path.realpath).
        assert sys.version_info < (3, 11), (
            "resolve() survived the denial on an interpreter that routes through "
            f"os.path.realpath - the instrument is broken, not the world:\n{out}"
        )
    else:
        assert "PROBE_ARMED" in out, f"probe printed neither outcome:\n{out}"


def test_import_time_sites_survive_a_denied_cwd():
    """The eight import-time resolve sites, under a denied working directory."""
    result = _run(SWEEP_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"a trigger import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


def test_handlers_guard_survives_the_ntpath_shaped_denial():
    """The guard must not walk inspect.stack().

    Separate from the sweep because the posix-shaped world is satisfied by the
    guarded resolve alone. This one is RED against an inspect.stack() walk and
    green against the sys._getframe cure.
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


def test_whole_branch_imports_under_the_ntpath_shaped_denial():
    """@prax's traceback, as a pin: importing trigger must not need a cwd."""
    result = _run(NTPATH_SWEEP_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world went vacuous - this pin proves nothing:\n{out}"
    assert "IMPORTED" in out, f"a trigger import died under the ntpath world:\nstdout={out}\nstderr={result.stderr}"


def test_repo_root_fallback_is_the_source_tree_never_the_process_directory():
    """The QUIET defect: four walks used to end in `return Path.cwd()`.

    A registry-less tree (every clean clone; AIPASS_REGISTRY.json is gitignored)
    took that fallback on every import, so each caller resolved against whatever
    directory the shell happened to be in. Pinned from a child process standing
    somewhere unrelated, because in-process the cwd is the repo root and the
    wrong answer and the right one look identical.
    """
    world = r"""
import os
import tempfile
from pathlib import Path

os.chdir(tempfile.gettempdir())

from aipass.trigger.apps.handlers.repo_root import SOURCE_ROOT, find_repo_root

# A marker that exists nowhere above this file forces the fallback.
answer = find_repo_root(marker="AIPASS_NO_SUCH_MARKER.json", caller="pin")
print("ANSWER", answer)
print("SOURCE_ROOT", SOURCE_ROOT)
print("CWD", Path.cwd())
"""
    result = _run(world)
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines() if " " in line)

    assert lines.get("ANSWER") == lines.get("SOURCE_ROOT"), (
        f"the fallback is no longer the source tree:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert lines.get("ANSWER") != lines.get("CWD"), (
        "the child stood in the repo root, so this run could not tell the source "
        f"tree from the process directory - the pin measured nothing:\n{result.stdout}"
    )


def test_repo_root_refuses_a_case_folded_marker(tmp_path, monkeypatch):
    """A cased literal folds too: exists() answers about `aipass_registry.json`.

    find_repo_root decides which installation this branch belongs to and several
    callers build write paths from the answer, so a folded bait file accepted as
    THE repo root is the quiet defect arriving through a different door.

    THE FOLDING IS INJECTED, not waited for. On ext4 the bait cannot fire, so a
    test that merely places a lowercase file and asserts refusal passes for the
    wrong reason - measured: a mutant degrading exists_exactly() to a bare
    exists() SURVIVED that shape on Linux. Path.exists is given the answer a
    folding filesystem would give, which is the call the defect actually makes.
    """
    from aipass.trigger.apps.handlers import repo_root

    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")
    start = bait_dir / "deep"
    start.mkdir()

    real_exists = Path.exists

    def folding_exists(self, *args, **kwargs):
        if real_exists(self, *args, **kwargs):
            return True
        try:
            names = {entry.name.lower() for entry in self.parent.iterdir()}
        except OSError:
            return False
        return self.name.lower() in names

    monkeypatch.setattr(Path, "exists", folding_exists)

    # The instrument must be live, or this pin proves nothing.
    assert (bait_dir / "AIPASS_REGISTRY.json").exists(), "the folding injection never fired"

    assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json"), (
        "a case-folded bait file was accepted as the blessed filename"
    )
    assert repo_root.find_repo_root(start, caller="pin") != bait_dir, (
        "the walk stopped at a directory holding aipass_registry.json"
    )

    # And the exact spelling is still accepted, under the same injected world.
    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    assert repo_root.exists_exactly(real_dir / "AIPASS_REGISTRY.json")
    assert repo_root.find_repo_root(real_dir, caller="pin") == real_dir


def test_the_folding_injection_is_a_real_negative_control(tmp_path, monkeypatch):
    """The control FOR the control: without the injection, the bait is inert.

    Proves the previous test's refusal comes from exists_exactly and not from
    ext4 answering no - a green that would survive deleting the cure.
    """
    from aipass.trigger.apps.handlers import repo_root

    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")

    if (bait_dir / "AIPASS_REGISTRY.json").exists():
        # A genuinely folding host: the injection is redundant there, and the
        # pin above measures the live condition rather than an emulation.
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")
    else:
        # Case-sensitive host: the bait is invisible WITHOUT the injection,
        # which is exactly why the injection exists.
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")


# ===========================================================================
# The deleted second stack walk — reachable only OUTSIDE an import
# ===========================================================================
#
# @cli's finding, 2026-08-31, and it landed on this branch too: the guard's
# `caller_file is None` branch is UNREACHABLE from any import-shaped pin. During
# a real import apps/__init__.py does `from . import handlers`, so there is
# always a real-file frame above the guard and _find_real_caller never returns
# None. MEASURED HERE: restoring the deleted inspect.stack() walk as a mutant
# passed all 1058 trigger tests, including every world above. Five green pins and
# the defect back in the tree.
#
# The branch is reachable exactly where it was meant to be — a REPL or a -c
# script, the callers it exists to allow — so the world calls the guard directly
# instead of importing something.

NO_CALLER_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
from aipass.trigger.apps.handlers import _find_real_caller, _guard_branch_access

# Positive control: this world must actually REACH the branch under test.
# A -c frame is spelled "<string>", which the walk skips, so there is no
# caller outside this file and the guard takes its None arm.
caller, line = _find_real_caller()
if caller is None:
    print("NO_CALLER_REACHED")
else:
    print("NO_CALLER_NOT_REACHED", caller)

_guard_branch_access()
print("IMPORTED")
"""
)


def test_the_no_caller_branch_needs_no_cwd():
    """The guard's `caller_file is None` arm, under the ntpath-shaped denial.

    Red against a restored second inspect.stack() walk, which no import world
    can reach. Credited to @cli, who found it by mutating their own identical
    deletion and watching it stroll past five green pins.
    """
    result = _run(NO_CALLER_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world went vacuous - this pin proves nothing:\n{out}"
    assert "NO_CALLER_REACHED" in out, (
        f"the guard found a caller, so its None arm never ran and this pin measured nothing:\n{out}"
    )
    assert "IMPORTED" in out, (
        f"the guard's no-caller arm still depends on a readable cwd:\nstdout={out}\nstderr={result.stderr}"
    )
