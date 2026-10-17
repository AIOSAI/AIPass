# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins daemon imports against a dead working directory
# Version: 1.1.1
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/module_root.py — every daemon module imports without a readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — Path.resolve's own cwd read in the platform realpath; measured in the child worlds
# seedgo: no-test-needed(ruff) — that each swept file parses; the sweeps ast.parse every one and would raise first

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.daemon.apps.handlers import module_root
from aipass.daemon.apps.handlers.json import json_handler
from aipass.daemon.apps.handlers.module_root import module_file

# A dropbox, like .archive, is a sandbox nothing looks into or runs from; __pycache__ holds no source.
# Named here, not seedgo's list: seedgo's handlers refuse a caller from another branch.
SWEEP_SKIP_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})

# On Windows ntpath.realpath reads the cwd unconditionally, so module-level Path(__file__).resolve() and
# inspect.stack() (getmodule's unguarded realpath) die at import when the cwd is gone. World A emulates ntpath;
# world B denies realpath outright. Both are needed: only B convicts inspect.stack() on every platform.
# The child runs as python -c: linecache caches <stdin>, so a <stdin> probe reads green on unfixed code.

# Other branches' import-time code is preloaded in the healthy world: this pin measures daemon's sites only.
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

# Appended to both worlds: <=3.10 pathlib captured os.path.realpath in _NormalAccessor, out of the rebind's
# reach. The class binding is the one resolve() reads; 3.11+ has no such class.
ARM_PATHLIB_ACCESSOR = """
import os
import pathlib

_accessor = getattr(pathlib, "_NormalAccessor", None)
if _accessor is not None:
    _accessor.realpath = staticmethod(os.path.realpath)
"""

# VACUOUS means the instrument went blind, never that the world is safe, so it is asserted against.
PROBE = """
import pathlib
import sys

try:
    pathlib.Path(pathlib.__file__).resolve()
    sys.stdout.write("PROBE_VACUOUS\\n")
except FileNotFoundError:
    sys.stdout.write("PROBE_ARMED\\n")
"""

# Negative control: a world that cannot kill inspect.stack() proves nothing about the cured guard.
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

# Keyed on os.name, which picks the abspath that decides it. "posix" is measured live here; "nt" is derived
# from a Windows CI failure and becomes measured the first time this file runs green on Windows.
STACK_IN_WORLD_A = {
    "posix": "STACK_LIVES",
    "nt": "STACK_DIES",
}

_BRANCH = Path(__file__).resolve().parents[1]
APPS = _BRANCH / "apps"

# tools/ is swept: a tool that dies on its first line breaks exactly when someone diagnoses. It is gitignored,
# so it is named unconditionally and the sweep skips a root not on disk rather than failing CI.
SWEPT_ROOTS = (APPS, _BRANCH / "tools")


def _sweepable(root: Path):
    """Python files under *root*, or nothing if the root is not on this machine."""
    if not root.is_dir():
        return []
    return [f for f in sorted(root.rglob("*.py")) if not SWEEP_SKIP_DIRS.intersection(f.relative_to(root).parts[:-1])]


def _run_world(denial: str) -> subprocess.CompletedProcess:
    """Run the import set in a child whose frame is <string>, never <stdin>."""
    source = PRELOAD + denial + ARM_PATHLIB_ACCESSOR + PROBE + STACK_DIES + IMPORTS
    return subprocess.run(
        [sys.executable, "-c", source],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def _assert_world(result: subprocess.CompletedProcess, label: str, *, expect_stack: str) -> str:
    """Assert the imports survived, and that the world behaved exactly as tabled.

    expect_stack is the exact token, asserted both ways: a boolean only ever checked STACK_DIES.
    """
    assert expect_stack in ("STACK_DIES", "STACK_LIVES"), expect_stack
    out = result.stdout
    assert "IMPORTED" in out, (
        f"world {label}: import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    )

    assert "PROBE_VACUOUS" not in out, (
        f"world {label}: resolve() survived the denial - the instrument went blind, "
        "not the world safe. Every interpreter this fleet runs on reaches realpath "
        "from resolve(): 3.11+ through the live os.path.realpath, 3.10 through "
        "_NormalAccessor, and both worlds rebind each. Measured 2026-09-03."
    )

    assert "PROBE_ARMED" in out, f"world {label}: probe reported neither outcome: {out}"

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
    """The resolve half: every module-level Path(__file__).resolve() is denied."""
    _assert_world(_run_world(WORLD_A), "A", expect_stack=STACK_IN_WORLD_A[os.name])


def test_daemon_imports_survive_world_b_realpath_denied():
    """The stack half, and the one world that convicts it on EVERY platform."""
    _assert_world(_run_world(WORLD_B), "B", expect_stack="STACK_DIES")


def test_world_a_stack_outcome_matches_the_platform_table():
    """Pin world A's stack outcome to the table, so the two worlds stay distinct."""
    # A table with a hole would read green by skipping, so the hole is a failure here.
    assert set(STACK_IN_WORLD_A) == {"posix", "nt"}, STACK_IN_WORLD_A
    assert set(STACK_IN_WORLD_A.values()) <= {"STACK_LIVES", "STACK_DIES"}, STACK_IN_WORLD_A
    assert os.name in STACK_IN_WORLD_A, (
        f"this machine is os.name={os.name!r} and the table has no entry - the pin is skipping rather than measuring"
    )
    expected = STACK_IN_WORLD_A[os.name]

    _assert_world(_run_world(WORLD_A), "A", expect_stack=expected)


# Only a parse convicts inspect.stack(): the caller-is-None branch it sat in is unreachable from any import world.


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every inspect.stack() call in *source*, by parse.

    Never a string scan: the guard's own docstring names inspect.stack() while explaining the defect.
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


# A module-level .resolve() is an import-time cwd read, and no import pin names WHICH line did it. Acquitted:
# a resolve inside a module-level try that catches OSError (the guard's own shape in apps/handlers/__init__.py).


def _catches_oserror(handler: ast.ExceptHandler) -> bool:
    """True when an except clause names OSError, alone or in a tuple."""
    names = handler.type.elts if isinstance(handler.type, ast.Tuple) else [handler.type]
    return any(isinstance(name, ast.Name) and name.id == "OSError" for name in names)


def _module_level_resolves(source: str) -> list:
    """Lines calling .resolve() at MODULE level (outside any def/class), unguarded."""
    tree = ast.parse(source)
    nested = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for child in ast.walk(node):
                nested.add(id(child))
    for stmt in tree.body:
        if isinstance(stmt, ast.Try) and any(_catches_oserror(h) for h in stmt.handlers):
            for node in stmt.body:
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
        """The roots list is a fact about the code, so it is pinned like one."""
        assert APPS in SWEPT_ROOTS, "apps/ dropped out of the sweep"
        assert _BRANCH / "tools" in SWEPT_ROOTS, "tools/ dropped out of the sweep"

    def test_the_sweep_reads_tools_when_it_is_present(self):
        """And when the directory IS here, it must actually be read."""
        tools = _BRANCH / "tools"
        if not tools.is_dir():
            pytest.skip("tools/ is not on this machine - gitignored, so a fresh clone has none")

        assert _sweepable(tools), "tools/ is present but the sweep reads no Python from it"

    def test_the_sweep_never_enters_a_dropbox_or_an_archive(self, tmp_path):
        """Nothing looks into a dropbox, a sandbox like .archive.

        The root stands inside a directory named dropbox: a skip judged on the whole path would read nothing.
        """
        tools = tmp_path / "dropbox" / "tools"
        for folder in ("handlers", "dropbox", ".archive", "handlers/dropbox"):
            (tools / folder).mkdir(parents=True)
        for rel in ("handlers/kept.py", "dropbox/stray.py", ".archive/old.py", "handlers/dropbox/stray.py"):
            (tools / rel).write_text("", encoding="utf-8")

        assert [f.relative_to(tools).as_posix() for f in _sweepable(tools)] == ["handlers/kept.py"]

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


# module_file must resolve when it can: every import pin above stays green with the fallback forced on every call.


class TestModuleFileResolvesWhenItCan:
    def test_a_healthy_world_gets_a_resolved_path(self, tmp_path):
        """The symlink is the point: resolving is why the call exists."""
        real = tmp_path / "real"
        real.mkdir()
        target = real / "mod.py"
        target.write_text("", encoding="utf-8")
        link = tmp_path / "link.py"
        link.symlink_to(target)

        assert module_file(str(link)) == target.resolve()

    def test_the_fallback_is_reached_only_on_oserror(self, tmp_path, monkeypatch):
        """And when reached, it still names the right file - absolutely, spelled through the symlink."""
        real = tmp_path / "real"
        real.mkdir()
        target = real / "mod.py"
        target.write_text("", encoding="utf-8")
        link = tmp_path / "link.py"
        link.symlink_to(target)

        monkeypatch.setattr(module_root, "Path", _UnresolvablePath)

        result = module_root.module_file(str(link))

        assert result == link, f"the fallback resolved anyway: {result}"
        assert result.is_absolute(), "the fallback returned a path that names nowhere in particular"

    def test_the_fallback_never_raises_when_the_diagnostic_lane_is_down(self, tmp_path, monkeypatch):
        """The world that denies the filesystem can deny the logger too.

        module_file's logger call must sit inside its try, or a failing logger crashes the import.
        """
        target = tmp_path / "mod.py"
        target.write_text("", encoding="utf-8")

        raising = _RaisingLogger()
        monkeypatch.setattr(module_root, "Path", _UnresolvablePath)
        monkeypatch.setattr(module_root, "logger", raising)

        # Control: the stand-in really raises, so a green below is not a dead injection.
        with pytest.raises(RuntimeError):
            module_root.logger.debug("probe")
        control_calls = len(raising.calls)

        result = module_root.module_file(str(target))

        assert result == target
        # Counted past the control's own call, which would otherwise satisfy this alone.
        assert len(raising.calls) > control_calls, "the diagnostic lane was never reached - the pin proved nothing"

    def test_the_fallback_never_raises_when_the_audit_write_fails(self, tmp_path, monkeypatch):
        """json_handler unavailable is the other half of the same bare world."""
        target = tmp_path / "mod.py"
        target.write_text("", encoding="utf-8")

        def exploding_import(*args, **kwargs):
            raise RuntimeError("the audit lane is down too")

        monkeypatch.setattr(module_root, "Path", _UnresolvablePath)
        monkeypatch.setattr(module_root, "__import__", exploding_import, raising=False)

        def exploding_log(*args, **kwargs):
            raise RuntimeError("the audit lane is down too")

        monkeypatch.setattr(json_handler, "log_operation", exploding_log)

        with pytest.raises(RuntimeError):
            json_handler.log_operation("probe", {})

        assert module_root.module_file(str(target)) == target


class _UnresolvablePath(type(Path())):
    """A path whose resolve() fails the way a dead working directory makes it fail."""

    def resolve(self, strict=False):
        raise OSError(2, "no working directory")


class _RaisingLogger:
    """A logger whose every call fails - the worst world module_file can meet."""

    def __init__(self):
        self.calls = []

    def _fail(self, *args, **kwargs):
        self.calls.append(args)
        raise RuntimeError("logging is down")

    debug = _fail
    warning = _fail
    info = _fail
    error = _fail
