# =================== AIPass ====================
# META DATA HEADER
# Name: test_import_dead_cwd.py
# Description: trigger imports without a readable cwd
# Created: 2026-08-31
# Modified: 2026-10-17
# Version: 1.4.0
# Category: trigger/tests
# =============================================

"""Tests that apps/trigger.py and every module under apps/ import without a readable cwd."""

# ntpath.realpath reads os.getcwd() unconditionally, so on Windows any import-time
# Path.resolve() dies when the cwd is deleted; one such site in trigger breaks every
# importer of prax's logger. Each world is a subprocess: in-process the imports already ran.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(behaviour) — what each module under apps/modules/ does once imported; each has its own tests

import subprocess
import sys
from pathlib import Path

import pytest

from aipass.trigger.apps.config import module_file
from aipass.trigger.apps.handlers import repo_root
from aipass.trigger.tests import support_fence

# Peers held constant in the healthy world. @prax is never preloaded: its logger
# imports trigger, so preloading it would import the sites under test before the denial.
_PRELOAD = r"""
import rich.console  # noqa: F401
import inspect  # noqa: F401
import linecache  # noqa: F401
"""

# CPython 3.10's pathlib captures os.path.realpath onto _NormalAccessor at first import,
# so patching os.path alone leaves the world inert there. staticmethod is required: a bare
# function binds as a method and eats the path into `self`. 3.11+ has no _NormalAccessor.
_ACCESSOR_PATCH = r"""
import pathlib

_captured = getattr(pathlib, "_NormalAccessor", None)
if _captured is not None:
    _captured.realpath = staticmethod(os.path.realpath)
"""

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
"""
    + _ACCESSOR_PATCH
    + r"""
# Probe the instrument: does THIS interpreter's resolve() reach the denied call?
# The path is ABSOLUTE on purpose - a relative one dies in abspath for its own
# shape and would report ARMED whatever the patch did or failed to do.
try:
    pathlib.Path(pathlib.__file__).resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""
)

# The ntpath-shaped denial: on POSIX getmodule() catches abspath's FileNotFoundError before
# inspect.stack() reaches realpath, so only an ntpath-style non-raising abspath convicts it.
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
"""
    + _ACCESSOR_PATCH
    + r"""
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

# One site per line so a failure names the module that died.
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

NTPATH_GUARD_WORLD = (
    _NTPATH_PREAMBLE
    + r"""
import aipass.trigger.apps.handlers  # noqa: F401

print("IMPORTED")
"""
)

NTPATH_SWEEP_WORLD = _NTPATH_PREAMBLE + _SITES


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _assert_probe_armed(out: str) -> None:
    """The instrument must be able to fire, or the pin proves nothing."""
    assert "PROBE_ARMED" in out, (
        "the denial did not reach resolve() - the instrument is broken, not the "
        f"world, and every pin under it proves nothing:\n{out}"
    )


# The judgement is fed synthetic strings: no real world on this host produces a vacuous probe.


def test_a_vacuous_probe_is_refused_on_this_interpreter_too():
    """A vacuous probe is refused on every interpreter, 3.10 included."""
    with pytest.raises(AssertionError):
        _assert_probe_armed("PROBE_VACUOUS\nIMPORTED\n")


def test_an_armed_probe_is_accepted():
    """The judgement is not simply 'always raise' - it has to let a real world through."""
    _assert_probe_armed("PROBE_ARMED\nIMPORTED\n")


def test_a_probe_that_printed_nothing_is_refused():
    """Silence is not consent: a world that crashed before probing proves nothing."""
    with pytest.raises(AssertionError):
        _assert_probe_armed("IMPORTED\n")


def test_import_time_sites_survive_a_denied_cwd():
    """The eight import-time resolve sites, under a denied working directory."""
    result = _run(SWEEP_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"a trigger import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


def test_handlers_guard_survives_the_ntpath_shaped_denial():
    """The guard must not walk inspect.stack().

    The posix-shaped sweep cannot see a stack walk; this world can.
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


# _ACCESSOR_PATCH, falsified on any host by rebuilding 3.10's eager capture. The captured
# function is a sentinel that touches no filesystem or cwd: ntpath.realpath reads the cwd
# even for absolute paths, so a live capture makes raise/no-raise mean nothing on Windows.
# Two sentinels, because moving the source name after class creation is what shows eagerness.
_SENTINELS = r"""
def _sentinel_captured(path, *, strict=False):
    # Touches no filesystem, no cwd, no path module. Answers with a CONSTANT,
    # not a path, so no return-value check can start measuring the host.
    return "CAPTURED"


def _sentinel_moved(path, *, strict=False):
    return "MOVED"


_source_realpath = _sentinel_captured

# The control FOR the eagerness control (@flow's shape, 2026-08-31). The
# discriminator below is "did the answer follow the moved source name" - and it
# can only discriminate while the two sentinels give DIFFERENT answers. Collapse
# them to one string and the eagerness pin reports EAGER forever with nothing
# saying so; measured as a surviving mutant here before this line existed.
print("SENTINELS_DIFFER", _sentinel_captured(_ABS) != _sentinel_moved(_ABS))
"""

# The win32 branch of ntpath.realpath, rebuilt: off Windows ntpath.realpath wraps abspath.
_NT_SHAPED = r"""
import ntpath

_getcwd_reads = []


def _nt_shaped_realpath(path, *, strict=False):
    # ntpath.py:659-673, str branch: cwd is computed BEFORE the isabs test that
    # is the only thing that consumes it.
    path = ntpath.normpath(path)
    _getcwd_reads.append(1)
    cwd = os.getcwd()
    if not ntpath.isabs(path):
        path = ntpath.join(cwd, path)
    return path
"""

_CAPTURE_HEAD = r"""
import ntpath
import os
import posixpath
import sys

# ABSOLUTE on purpose - a relative path dies in abspath for its own shape and
# would report ARMED whatever the patch did or failed to do - and absolute IN
# BOTH DIALECTS, which is the round-8 correction.
#
# This was sys.executable, which is absolute in the HOST's dialect and nobody
# else's. On the Windows runner that is D:\a\...\python.exe, and
# posixpath.isabs() of it is FALSE - so the posix capture treated it as relative,
# joined the denied cwd, and reported ARMED where the row demanded INERT. The
# arming row had silently keyed on here-equals-a-posix-host.
#
# A rooted literal is absolute to posixpath AND to ntpath (drive-relative there,
# which costs nothing since nothing resolves it), and exists on no machine, so
# no filesystem can answer for the probe either. @spawn's sentence: the
# platform-shaped assumption moves up a level each time it is cured - round 6
# the world, round 7 the emulation, round 8 the thing that INSTALLS the probe.
_ABS = "/AIPASS_NO_SUCH_PROBE_PATH"
"""

# posixpath only: every posix-absolute path is also nt-absolute, so an ntpath check never fires.
_PROBE_CONTROL = r"""
print("PROBE_IS_ABS", posixpath.isabs(_ABS))
"""

# The nt shape must prove its cwd read fires for an absolute path before any verdict counts.
_ROUTE_CONTROL = r"""
if _CAPTURED is _nt_shaped_realpath or _HOST_REALPATH is _nt_shaped_realpath:
    _before = len(_getcwd_reads)
    _nt_shaped_realpath(_ABS)
    print("ROUTE_ARMED" if len(_getcwd_reads) > _before else "ROUTE_DARK")
"""

_BUILD_ACCESSOR = r"""
class _NormalAccessorShape:
    # EAGER, at class creation - exactly when pathlib 3.10 binds its own copy.
    realpath = staticmethod(_CAPTURED)


_accessor = _NormalAccessorShape()
"""

# An eager capture still answers "CAPTURED" after the source moves; a lazy wrapper answers "MOVED".
_EAGER_CONTROL = r"""
if _CAPTURED is _sentinel_captured:
    _source_realpath = _sentinel_moved
    print("EMULATION_EAGER" if _accessor.realpath(_ABS) == "CAPTURED" else "EMULATION_NOT_EAGER")
else:
    print("EMULATION_EAGER" if _NormalAccessorShape.realpath is _CAPTURED else "EMULATION_NOT_EAGER")
"""

_DENIAL_HEAD = r"""
_real_realpath = _HOST_REALPATH


def _denied(path, **kw):
    os.getcwd()
    return _real_realpath(path, **kw)


os.path.realpath = _denied


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd
"""

# The shipped fragment, aimed at the emulated holder rather than pathlib's.
_APPLY_SHIPPED_PATCH = r"""
_captured = _NormalAccessorShape
if _captured is not None:
    _captured.realpath = staticmethod(os.path.realpath)
"""

# Read through the instance, as pathlib 3.10's resolve() does.
_EXERCISE_CAPTURE = r"""
try:
    result = _accessor.realpath(_ABS)
except FileNotFoundError:
    print("CAPTURE_ARMED")
except TypeError as exc:
    print("PLAIN_EATS_SELF", type(exc).__name__)
else:
    # A return-value check, not a survived/raised one: a plain-function rebind
    # eats the path into `self` and can otherwise look like a pass.
    print("CAPTURE_INERT", result)
"""

_CAPTURE_EXPR = {
    "sentinel": "_sentinel_captured",
    "posix": "posixpath.realpath",
    "nt": "_nt_shaped_realpath",
}

_HOST_EXPR = {"posix": "posixpath.realpath", "nt": "_nt_shaped_realpath"}


def _capture_world(
    capture: str,
    *,
    host: str = "posix",
    apply_patch: bool = False,
    bare_rebind: bool = False,
    probe: str | None = None,
    spoof_executable: str | None = None,
) -> str:
    """Assemble one capture world.

    "posix"/"nt" captures rebuild the pre-cure shape; host varies with the capture held fixed.
    """
    world = ""
    if spoof_executable is not None:
        world += f"import sys\n\nsys.executable = {spoof_executable!r}\n"
    world += _CAPTURE_HEAD
    if probe is not None:
        world += f"_ABS = {probe!r}\n"
    world += _PROBE_CONTROL + _SENTINELS + _NT_SHAPED
    world += f"\n_CAPTURED = {_CAPTURE_EXPR[capture]}\n"
    world += f"_HOST_REALPATH = {_HOST_EXPR[host]}\n"
    world += _ROUTE_CONTROL + _BUILD_ACCESSOR + _EAGER_CONTROL + _DENIAL_HEAD
    if apply_patch:
        world += _APPLY_SHIPPED_PATCH
    if bare_rebind:
        world += "\n_NormalAccessorShape.realpath = os.path.realpath  # NO staticmethod\n"
    return world + _EXERCISE_CAPTURE


def _assert_emulation_sound(out: str, capture: str, host: str = "posix") -> None:
    """Nothing downstream may be believed until the emulation says it is real."""
    assert "SENTINELS_DIFFER True" in out, (
        "the two sentinels answer alike, so the eagerness discriminator below "
        f"cannot report anything but EAGER - it is dark, not passing:\n{out}"
    )
    assert "PROBE_IS_ABS True" in out, (
        "the probe path is not absolute to posixpath, the strict dialect, so this row is "
        f"measuring the host's notion of absoluteness rather than the patch:\n{out}"
    )
    assert "EMULATION_EAGER" in out, f"the emulation is not an eager capture - it describes another shape:\n{out}"
    if "nt" in (capture, host):
        assert "ROUTE_ARMED" in out, (
            "the nt-shaped realpath did not read the cwd for an ABSOLUTE path, so "
            f"this world is not the one that broke on the Windows runner:\n{out}"
        )


def test_the_captured_accessor_is_inert_under_a_bare_os_path_patch():
    """3.10's defect, rebuilt: patching os.path.realpath does not reach it."""
    result = _run(_capture_world("sentinel"))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "CAPTURE_INERT CAPTURED" in out, (
        "the bare os.path patch reached the captured copy, so there is nothing "
        f"for _ACCESSOR_PATCH to fix and this file is carrying dead weight:\n{out}"
    )


def test_the_shipped_accessor_patch_arms_the_captured_copy():
    """_ACCESSOR_PATCH is load-bearing: remove it and this pin goes red."""
    result = _run(_capture_world("sentinel", apply_patch=True))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "CAPTURE_ARMED" in out, (
        "the shipped accessor patch did not arm the captured copy - on 3.10 the "
        f"dead-cwd worlds are inert and every pin under them is vacuous:\n{out}"
    )


def test_the_accessor_patch_needs_staticmethod_not_a_bare_function():
    """Why _ACCESSOR_PATCH wraps: bare, the instance is eaten into the path slot.

    A bare rebind raises TypeError, which a "did it raise" pin reads as a cured world.
    """
    result = _run(_capture_world("sentinel", bare_rebind=True))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel")
    assert "PLAIN_EATS_SELF" in out, (
        "a bare function rebind did NOT bind as a method here - the staticmethod "
        f"wrapper in _ACCESSOR_PATCH may no longer be doing anything:\n{out}"
    )
    assert "CAPTURE_ARMED" not in out, f"the bare rebind looked like a working denial, which is the trap:\n{out}"


@pytest.mark.parametrize("host", ["posix", "nt"])
def test_the_inert_verdict_does_not_move_between_host_dialects(host: str):
    """@memory's litmus: run the probe under the opposite platform's dialect and
    require the verdict NOT to move.

    A live capture in place of the sentinel turns the nt row red here, on Linux.
    """
    result = _run(_capture_world("sentinel", host=host))
    out = result.stdout

    _assert_emulation_sound(out, "sentinel", host)
    assert "CAPTURE_INERT CAPTURED" in out, f"the sentinel verdict moved under the {host} host dialect:\n{out}"


@pytest.mark.parametrize(
    ("dialect", "expected"),
    [("posix", "CAPTURE_INERT"), ("nt", "CAPTURE_ARMED")],
)
def test_the_litmus_is_armed_by_a_shape_whose_verdict_does_move(dialect: str, expected: str):
    """The arming for the litmus above (@skills' trap (d)).

    The pre-cure live capture must diverge by dialect, or the litmus slot reaches nothing.
    """
    result = _run(_capture_world(dialect, host=dialect))
    out = result.stdout

    _assert_emulation_sound(out, dialect, dialect)
    assert expected in out, (
        f"the pre-cure {dialect} capture no longer reads {expected} - the failure "
        f"this file was rebuilt around has stopped reproducing:\n{out}"
    )


# Each host's sys.executable shape: absolute to its own dialect only.
_HOST_SHAPED_EXECUTABLE = {
    "posix": "/usr/bin/python3",
    "nt": "D:\\a\\AIPass\\AIPass\\.venv\\Scripts\\python.exe",
}


@pytest.mark.parametrize("host_shape", ["posix", "nt"])
def test_a_host_shaped_probe_path_is_refused_rather_than_silently_answered(host_shape: str):
    """The round-8 regression pin, and it convicts the INSTALLER not the world.

    The world refuses a probe path that is not absolute to posixpath, and says so.
    """
    result = _run(_capture_world("posix", probe=_HOST_SHAPED_EXECUTABLE[host_shape]))
    out = result.stdout

    if host_shape == "posix":
        assert "PROBE_IS_ABS True" in out, out
        assert "CAPTURE_INERT" in out, f"a posix-absolute probe stopped being inert against the posix capture:\n{out}"
        return

    assert "PROBE_IS_ABS False" in out, (
        "an nt-shaped executable path was accepted as absolute - "
        f"posixpath.isabs() must reject it, or round 8 can happen again:\n{out}"
    )
    with pytest.raises(AssertionError, match="not absolute to posixpath"):
        _assert_emulation_sound(out, "posix")


@pytest.mark.parametrize("host_shape", ["posix", "nt"])
def test_the_probe_path_does_not_follow_the_hosts_executable(host_shape: str):
    """Convicts the round-8 defect ITSELF on this machine, not just its symptom.

    The probe path must not be derived from the host (sys.executable, cwd, __file__).
    """
    result = _run(_capture_world("posix", spoof_executable=_HOST_SHAPED_EXECUTABLE[host_shape]))
    out = result.stdout

    _assert_emulation_sound(out, "posix")
    assert "CAPTURE_INERT" in out, (
        f"the posix arming row moved when sys.executable took its {host_shape} shape - "
        f"the probe path is following the host again:\n{out}"
    )


def test_the_shipped_probe_path_is_absolute_to_the_strict_dialect():
    """The positive half: the literal actually shipped satisfies the rule."""
    result = _run(_capture_world("posix"))

    assert "PROBE_IS_ABS True" in result.stdout, result.stdout
    _assert_emulation_sound(result.stdout, "posix")


def test_repo_root_fallback_is_the_source_tree_never_the_process_directory():
    """The QUIET defect: four walks used to end in `return Path.cwd()`.

    A registry-less fallback must be the source tree. Run from an unrelated directory: in-process the cwd is the repo root and hides the defect.
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


def test_repo_root_refuses_a_case_folded_marker(tmp_path):
    """A cased literal folds too: exists() answers about `aipass_registry.json`.

    Folding is injected through exists_fn: on ext4 a bare exists() mutant survives otherwise.
    """
    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")
    start = bait_dir / "deep"
    start.mkdir()

    def folding_exists(path: Path) -> bool:
        if path.exists():
            return True
        try:
            names = {entry.name.lower() for entry in path.parent.iterdir()}
        except OSError:
            return False
        return path.name.lower() in names

    # The instrument must be live, or this pin proves nothing.
    assert folding_exists(bait_dir / "AIPASS_REGISTRY.json"), "the folding injection never fired"

    assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json", exists_fn=folding_exists), (
        "a case-folded bait file was accepted as the blessed filename"
    )
    assert repo_root.find_repo_root(start, caller="pin", exists_fn=folding_exists) != bait_dir, (
        "the walk stopped at a directory holding aipass_registry.json"
    )

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    assert repo_root.exists_exactly(real_dir / "AIPASS_REGISTRY.json", exists_fn=folding_exists)
    assert repo_root.find_repo_root(real_dir, caller="pin", exists_fn=folding_exists) == real_dir

    # Proves the walk reads the probe at every step, not ext4's own answer.
    inner = real_dir / "inner"
    inner.mkdir()
    (inner / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    def deny_inner(path: Path) -> bool:
        return path.parent != inner and path.exists()

    assert repo_root.find_repo_root(inner, caller="pin", exists_fn=deny_inner) == real_dir, (
        "the walk did not read the probe it was handed"
    )


def test_the_folding_injection_is_a_real_negative_control(tmp_path, monkeypatch):
    """The control FOR the control: without the injection, the bait is inert."""
    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")

    if (bait_dir / "AIPASS_REGISTRY.json").exists():
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")
    else:
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")


# The fence probe from its kin seat under the ntpath-shaped denial. The dead cwd is
# emulated: Windows refuses to remove a process's own working directory.

KIN_SEAT_WORLD = (
    _NTPATH_PREAMBLE
    + f"""
import runpy
import sys

sys.argv = [{str(Path(support_fence.__file__))!r}, "pkg"]
runpy.run_path(sys.argv[0], run_name="__main__")
"""
)


def test_the_fence_lets_kin_through_with_no_cwd():
    """The kin seat imports its handlers under the ntpath-shaped denial: ALLOWED."""
    result = _run(KIN_SEAT_WORLD)
    out = result.stdout

    assert "STACK_DIES" in out, f"the ntpath world went vacuous - this pin proves nothing:\n{out}"
    assert out.strip().splitlines()[-1] == "ALLOWED", (
        f"the fence refused or died on its own kin under a dead cwd:\nstdout={out}\nstderr={result.stderr}"
    )


def test_module_file_resolves_through_a_symlink(tmp_path):
    """module_file hands back the real file behind a symlinked __file__."""
    real = tmp_path / "real_module.py"
    real.write_text("", encoding="utf-8")
    link = tmp_path / "linked_module.py"
    link.symlink_to(real)

    assert module_file(str(link)) == real.resolve()
