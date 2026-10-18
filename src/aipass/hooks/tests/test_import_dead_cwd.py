# =================== AIPass ====================
# Name: test_import_dead_cwd.py
# Description: Pins hooks imports against a dead working directory (two worlds)
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/__init__.py's guard: every hooks module imports without a readable cwd."""

# ntpath.realpath calls os.getcwd() unconditionally, so on Windows an import-time resolve() needs a live cwd.
# Two worlds, each convicting half: A emulates ntpath (resolve), B denies realpath (inspect.stack()).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that every hooks module parses; this file pins only import under a dead cwd
# seedgo: no-test-needed(stdlib) — os.getcwd() raising once the working directory is gone; the worlds emulate it

import ast
import subprocess
import sys
from pathlib import Path

import pytest

BRANCH_ROOT = Path(__file__).resolve().parents[1]
GUARD_SOURCE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"

# Other branches' import-time code is preloaded before any denial: this pins hooks' sites only.
_PRELOAD = """
from aipass.prax import logger  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
"""

_WORLD_A = """
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

_WORLD_B = """
import os


def _denied_realpath(path, **kw):
    raise FileNotFoundError(2, "realpath denied", "")


os.path.realpath = _denied_realpath
# os.path.abspath stays WORKING - world B denies realpath only, so a cure that
# merely swaps one for the other is not accidentally blessed here.

# Probe the instrument from a <string> frame: not on disk and not in
# linecache, so getsourcefile falls through to getmodule and reaches the
# denied call - the same fall-through the frozen importlib frames of a real
# import take. A <stdin> frame IS linecached and would report vacuity.
try:
    exec(compile("import inspect; inspect.stack()", "<string>", "exec"), {})
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""


# Compared on the parts BELOW the walk's root, so a root inside one of these names is still walked.
_NEVER_WALKED = ("dropbox", ".archive", "__pycache__")


def _module_names(root: Path = BRANCH_ROOT / "apps", base: Path = BRANCH_ROOT.parents[1]) -> list[str]:
    """Every importable module under this branch's apps/ tree.

    Discovered, never listed. Dotted and ``(disabled)`` names are SyntaxErrors in the child script.
    """
    names = set()
    for path in root.rglob("*.py"):
        if any(part in _NEVER_WALKED for part in path.relative_to(root).parts):
            continue
        relative = path.relative_to(base).with_suffix("")
        parts = list(relative.parts)
        if any(part.startswith(".") for part in parts):
            continue
        if any("(disabled)" in part for part in parts):
            continue
        if parts[-1] == "__init__":
            parts.pop()
        names.add(".".join(parts))
    return sorted(names)


def _run_world(world: str, imports: str) -> subprocess.CompletedProcess:
    """Run a denial world in a child process.

    A child, before any aipass import, so no module has cached the real functions.
    """
    script = _PRELOAD + world + imports + '\nprint("IMPORTED")\n'
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=300,
        cwd=str(BRANCH_ROOT.parents[2]),
    )


def _assert_world_was_armed(out: str) -> None:
    """A world that could not fire proves nothing; say so rather than pass."""
    if "PROBE_VACUOUS" in out:
        # Pre-3.11 pathlib never routes an absolute resolve through os.path.realpath.
        assert sys.version_info < (3, 11), (
            "the denial did not fire on an interpreter that routes through "
            "os.path.realpath - the instrument is broken, not the world"
        )
    else:
        assert "PROBE_ARMED" in out, f"the instrument reported neither outcome:\n{out}"


class TestEveryModuleImportsWithoutACwd:
    """The whole tree, both worlds. One import statement per module in one
    child: a module that dies takes the run down and names its own line."""

    IMPORTS = "\n".join(f"import {name}  # noqa: F401" for name in _module_names())

    def test_world_a_ntpath_emulation(self):
        """Convicts an unguarded Path(__file__).resolve() reached at import."""
        result = _run_world(_WORLD_A, self.IMPORTS)
        _assert_world_was_armed(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"an import died with cwd unreadable:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_world_b_realpath_denied(self):
        """Convicts inspect.stack() at inspect.py:1009."""
        result = _run_world(_WORLD_B, self.IMPORTS)
        _assert_world_was_armed(result.stdout)
        assert "IMPORTED" in result.stdout, (
            f"an import died with realpath denied:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    def test_the_module_list_is_not_empty(self):
        """Positive control. Both tests above pass trivially over no imports -
        a broken discovery walk would report a cured tree that was never read."""
        names = _module_names()
        assert len(names) > 40, f"module discovery found only {len(names)}: {names}"
        assert "aipass.hooks.apps.modules.engine" in names
        assert "aipass.hooks.apps.handlers.security.edit_gate" in names

    def test_the_walk_skips_sandboxes_and_bytecode(self, tmp_path):
        """A dropbox, an .archive and a __pycache__ under the root are never
        walked; the live file beside them is, so an empty walk cannot pass."""
        root = tmp_path / "apps"
        root.mkdir()
        (root / "live.py").write_text("", encoding="utf-8")
        for skipped in ("dropbox", ".archive", "__pycache__"):
            (root / skipped).mkdir()
            (root / skipped / "inside.py").write_text("", encoding="utf-8")
        assert _module_names(root, tmp_path) == ["apps.live"]

    def test_a_root_inside_a_dropbox_is_still_walked(self, tmp_path):
        """The skip compares the parts BELOW the root of the walk, never the
        whole path: a root that stands inside a dropbox keeps its files."""
        root = tmp_path / "dropbox" / "apps"
        root.mkdir(parents=True)
        (root / "live.py").write_text("", encoding="utf-8")
        assert _module_names(root, tmp_path) == ["dropbox.apps.live"]

    def test_the_worlds_are_not_the_same_world(self):
        """World B must deny realpath OUTRIGHT; world A must deny getcwd. If a
        later edit merged them, both tests would prove the same half."""
        assert "os.getcwd = _dead_getcwd" in _WORLD_A
        assert "os.getcwd" not in _WORLD_B.replace("os.getcwd = _dead_getcwd", "")
        assert "_denied_realpath" in _WORLD_B


class TestTheCureCannotBeSilentlyReverted:
    """``inspect.stack()`` in the guard is the defect, not a style preference.

    An import probe cannot reach the caller-is-None branch, so the ban is structural.
    """

    def test_the_guard_source_is_actually_read(self):
        """Positive control for the checks below: a wrong path would let them
        all pass while reading nothing. Fence v2's public line, never a private name."""
        text = GUARD_SOURCE.read_text(encoding="utf-8")
        assert 'MY_BRANCH = "hooks"' in text

    def test_the_fence_lets_kin_through_with_no_cwd(self):
        """The kin seat imports its handlers under world A (the ntpath-shaped denial): ALLOWED.

        Red against a frame walk whose resolve has no OSError arm.
        """
        probe = BRANCH_ROOT / "tests" / "support_fence.py"
        run_kin = f"\nimport runpy\nimport sys\nsys.argv = [{str(probe)!r}, 'pkg']\n"
        result = _run_world(_WORLD_A, run_kin + "runpy.run_path(sys.argv[0], run_name='__main__')\n")
        _assert_world_was_armed(result.stdout)
        assert "ALLOWED" in result.stdout.splitlines(), (
            f"the fence refused or died on its kin under a dead cwd:\nstdout={result.stdout}\nstderr={result.stderr}"
        )

    @staticmethod
    def _inspect_stack_calls(source: str) -> list[int]:
        """Lines calling ``inspect.stack()``, by shape."""
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

    def test_inspect_stack_is_gone_from_the_guard(self):
        lines = self._inspect_stack_calls(GUARD_SOURCE.read_text(encoding="utf-8"))
        assert lines == [], (
            "inspect.stack() reaches os.path.realpath, which needs a readable cwd "
            f"on Windows - walk frames with sys._getframe instead (line {lines})"
        )

    def test_that_ban_would_convict_a_real_call(self):
        """Negative control. A matcher that matches nothing passes on every
        file, including a reverted one."""
        assert self._inspect_stack_calls("import inspect\ndef f():\n    return inspect.stack()\n") == [3]

    def test_that_ban_acquits_the_docstring_that_names_it(self):
        """Negative control for the other direction: the shape rule must not
        convict prose. This is why the ban is AST and not a grep."""
        assert self._inspect_stack_calls('"""We do not call inspect.stack() here."""\n') == []

    def test_the_frame_walk_is_what_replaced_it(self):
        """Names the cure, so 'delete inspect and break the guard' is not a way
        to make the ban above pass."""
        text = GUARD_SOURCE.read_text(encoding="utf-8")
        assert "sys._getframe" in text
        assert "linecache" in text, "code_context needs a replacement, not deletion"

    def test_the_guards_own_resolve_is_guarded(self):
        """The world-A conviction site. An unguarded resolve in this file is
        reached by every import of hooks' handlers, so it decides every hook."""
        tree = ast.parse(GUARD_SOURCE.read_text(encoding="utf-8"))
        unguarded = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "resolve"
            and not _inside_try(tree, node)
        ]
        assert unguarded == [], f"resolve() outside a try/except in the guard (line {unguarded})"


def _try_body_nodes(tree: ast.AST) -> set[int]:
    """Identities of every node inside some ``try`` body.

    The caller keeps *tree* alive: these are ``id()`` values a collected tree could reuse.
    """
    inside: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Try):
            continue
        for statement in node.body:
            inside.update(id(child) for child in ast.walk(statement))
    return inside


def _inside_try(tree: ast.AST, target: ast.AST) -> bool:
    """Whether a node sits inside the body of a ``try`` statement."""
    return id(target) in _try_body_nodes(tree)


class TestTheInsideTryHelperIsNotVacuous:
    """Negative control for the helper the resolve ban depends on. A helper
    that always returned True would acquit an unguarded call silently."""

    def test_it_sees_a_guarded_call(self):
        tree = ast.parse("from pathlib import Path\ntry:\n    Path('x').resolve()\nexcept OSError:\n    pass\n")
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert _inside_try(tree, call) is True

    def test_it_sees_an_unguarded_call(self):
        tree = ast.parse("from pathlib import Path\nPath('x').resolve()\n")
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert _inside_try(tree, call) is False

    def test_a_call_in_the_except_body_is_not_guarded(self):
        """The fallback itself must not resolve - that is the same crash one
        line later. Only the try BODY counts as guarded."""
        tree = ast.parse("from pathlib import Path\ntry:\n    pass\nexcept OSError:\n    Path('x').resolve()\n")
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert _inside_try(tree, call) is False


@pytest.mark.parametrize("world_name", ["A", "B"])
def test_the_ordinary_import_still_works(world_name):
    """A guard that refused everything, or a world that killed the interpreter
    before any hooks code ran, would pass every denial test above."""
    world = {"A": _WORLD_A, "B": _WORLD_B}[world_name]
    result = _run_world(world, "import aipass.hooks.apps.modules.engine  # noqa: F401")
    assert "IMPORTED" in result.stdout, result.stderr
