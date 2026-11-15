# =================== AIPass ====================
# Name: test_dead_cwd_imports.py
# Description: Dead-cwd import pins
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-15
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-11-14): Linux only - the faked-Windows worlds A/B and the accessor emulation go;
#     every pin runs under the getcwd-denied world, child logs stay in the test seam
#   - v1.1.1 (2026-10-22): Telethon import probe cut (Telegram left skills); walk skips '(disabled)' files
#   - v1.1.0 (2026-10-08): The old guard's caller-is-None case, read through
#     private names, becomes two dead-cwd pins on the v2 fence (DPLAN-0404)
#   - v1.0.0 (2026-08-31): Windows round 4 - every skills module must import
#     with an unreadable working directory, in two denial worlds
#
# CODE STANDARDS:
#   - Measures by RUNNING in a child process, never by grepping spellings
# =============================================

"""Tests that every skills module, and the guard in apps/handlers/__init__.py, survive a dead cwd."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — Path.resolve() itself; only whether a world reaches it

import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.skills.tests.dead_cwd_world import WORLD_GETCWD_DENIED

SRC_ROOT = Path(__file__).resolve().parents[3]
BRANCH_ROOT = Path(__file__).resolve().parents[1]
GUARD_FILE = BRANCH_ROOT / "apps" / "handlers" / "__init__.py"


def _skills_modules(branch_root: Path = BRANCH_ROOT) -> list:
    """Every importable skills module, by dotted name.

    Skips are judged on parts relative to branch_root, so a checkout under a directory named dropbox is still walked.
    """
    mods = []
    for path in sorted(branch_root.rglob("*.py")):
        rel = path.relative_to(branch_root)
        if any(part.startswith(".") for part in rel.parts):
            continue
        if {"tests", "__pycache__", "templates", "dropbox", "docs.local"} & set(rel.parts):
            continue
        # A '(disabled)' file is parked by name: not an identifier, so nothing can import it.
        if not all(part.isidentifier() for part in rel.with_suffix("").parts):
            continue
        parts = ["aipass", "skills", *rel.with_suffix("").parts]
        if parts[-1] == "__init__":
            parts = parts[:-1]
        mods.append(".".join(parts))
    return mods


SKILLS_MODULES = _skills_modules()

# Each denial raises a FRESH exception: a reused one accumulates __traceback__ frames and blames the instrument.
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
from aipass.prax import logger  # noqa - another branch, not the thing measured; lazy init loads nothing bare


def _denied():
    return FileNotFoundError(2, "No such file or directory (dead cwd)")


INJECT = os.environ.get("SKILLS_PROBE_INJECT", "1") == "1"

# The world is defined ONCE, in tests/dead_cwd_world.py, and injected here as
# TEXT because it has to exist before the module under test is imported.
if INJECT and MODE == "dead":
    exec(os.environ["SKILLS_WORLD_TEXT"])

if CONTROL_ONLY:
    # A world that does not deny Path.cwd() turns every pin below vacuously green.
    if MODE == "dead":
        try:
            pathlib.Path.cwd()
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
    ours = [f for f in frames if "/aipass/skills/" in f.filename]
    frame = ours[-1] if ours else (frames[-1] if frames else None)
    where = "unknown"
    if frame is not None:
        rel = frame.filename.split("/aipass/skills/")[-1]
        where = "%s:%d" % (rel, frame.lineno)
    print("RED %s %s %s: %s" % (TARGET, where, type(exc).__name__, exc))
    sys.exit(1)
print("OK %s" % TARGET)
"""


# A child process, because the denial must be installed before the first import, not around it.
def _run_probe(mode: str, target: str, inject: bool = True):
    """Import one module in a child process under the getcwd-denied world; inject=False is the negative control."""
    # The per-test AIPASS_TEST_LOG_DIR seam is inherited: a child's json writes land in tmp, never skills_json/.
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env["SKILLS_PROBE_INJECT"] = "1" if inject else "0"
    env["SKILLS_WORLD_TEXT"] = WORLD_GETCWD_DENIED if mode == "dead" else ""
    # A -c string, not stdin: linecache caches a <stdin> probe and the probe then lies green.
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
        encoding="utf-8",
        env=env,
        cwd=str(SRC_ROOT),
        timeout=120,
    )


@pytest.mark.parametrize("mode", ["dead"])
def test_denial_world_is_live(mode):
    """Each world must actually deny the call the defect makes."""
    result = _run_probe(mode, "__control__")
    assert "CONTROL_LIVE" in result.stdout, (
        f"world {mode} did not deny its target call; every pin below would be "
        f"vacuously green. stdout={result.stdout!r} stderr={result.stderr[-400:]!r}"
    )


@pytest.mark.parametrize("mode", ["dead"])
def test_control_can_say_no(mode):
    """Kill the injection and the control must REPORT it, not pass anyway."""
    result = _run_probe(mode, "__control__", inject=False)
    assert "CONTROL_DEAD" in result.stdout, (
        f"world {mode} control reported live with the injection removed - it "
        f"cannot detect a dead world. stdout={result.stdout!r}"
    )


def test_healthy_world_imports_everything():
    """Baseline: with no denial, every module imports."""
    failures = [(m, _run_probe("healthy", m)) for m in SKILLS_MODULES]
    red = [(m, r.stdout.strip() or r.stderr.strip()[-300:]) for m, r in failures if r.returncode != 0]
    assert red == [], f"modules failed to import in a HEALTHY world: {red}"


@pytest.mark.parametrize("mode", ["dead"])
def test_every_module_imports_with_a_dead_cwd(mode):
    """No skills module may need a readable cwd to be imported."""
    red = []
    for module in SKILLS_MODULES:
        result = _run_probe(mode, module)
        if result.returncode != 0:
            red.append(result.stdout.strip() or result.stderr.strip()[-300:])
    assert red == [], (
        f"world {mode}: {len(red)} of {len(SKILLS_MODULES)} skills modules "
        f"cannot be imported with an unreadable cwd:\n" + "\n".join(red)
    )


def _inspect_stack_calls(source: str) -> list:
    """Find inspect.stack() calls in source, by parse tree."""
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

    No import-shaped pin reaches the caller-is-None branch. A parse-tree ban, since the guard's prose names the call.
    """
    lines = _inspect_stack_calls(GUARD_FILE.read_text(encoding="utf-8"))
    assert lines == [], (
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


_CALLER_MODULE = r"""
from aipass.skills.apps.handlers.json import json_handler


def writes_an_audit_entry():
    json_handler.log_operation("dead_cwd_probe")
    return json_handler.get_json_path("probe", "log").parent


def a_named_caller():
    return writes_an_audit_entry()
"""

# Driven from a <string> frame: a relative pseudo-filename is what makes inspect's abspath read the denied cwd.
_CALLER_DRIVER = r"""
import os
import os.path
import sys

exec(os.environ["SKILLS_WORLD_TEXT"])

sys.path.insert(0, sys.argv[1])
# The driver loads the shim first, from a <string> frame the fence reads as
# transport: a_named_module sits under tmp, a foreign seat the fence refuses
# (DPLAN-0404). The caller's name is this pin's subject; the fence has its own.
import aipass.skills.apps.handlers.json.json_handler
import a_named_module

# inspect memoises filename -> module name, and a cache HIT returns before
# getmodule reaches os.path.realpath. Cold is the world a fresh process has.
import inspect

inspect.modulesbyfile.clear()
inspect._filesbymodname.clear()

json_dir = a_named_module.a_named_caller()
print("WROTE=%s" % ",".join(sorted(p.name for p in json_dir.iterdir())))
"""


def test_caller_module_name_survives_and_still_answers(tmp_path):
    """The caller name must survive a dead cwd AND still name the caller.

    "unknown" also passes a does-not-crash check, so the ANSWER is read off the document the entry landed in.
    """
    (tmp_path / "a_named_module.py").write_text(_CALLER_MODULE, encoding="utf-8")
    # The seam is SET to tmp_path, not inherited: unset, the shim writes into the live skills_json/.
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env["AIPASS_TEST_LOG_DIR"] = str(tmp_path / "_aipass_json_seam")
    env["SKILLS_WORLD_TEXT"] = WORLD_GETCWD_DENIED
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
        encoding="utf-8",
        env=env,
        cwd=str(SRC_ROOT),
        timeout=60,
    )
    assert result.returncode == 0, f"caller-name probe crashed: {result.stderr[-800:]}"
    assert "WROTE=" in result.stdout, f"the audit entry never landed: {result.stdout!r}"
    written = [line for line in result.stdout.splitlines() if line.startswith("WROTE=")][0]
    assert "a_named_module_log.json" in written, (
        f"caller name degraded under a dead cwd - the entry was filed elsewhere: {written}"
    )


# Runtime paths, which import-time pins cannot see: both sites are inside functions.
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

# An arming probe must ask the call ITS OWN world denies (@sentry's rule).
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


def _run_runtime_probe(tmp_path: Path):
    """Exercise the cwd-derived runtime paths with getcwd denied; run from tmp so a regressed refusal writes only there."""
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT))
    env["SKILLS_WORLD_TEXT"] = WORLD_GETCWD_DENIED
    return subprocess.run(
        [sys.executable, "-c", "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))", _RUNTIME_PROBE],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(tmp_path),
        timeout=60,
    )


def test_skill_discovery_survives_a_dead_cwd(tmp_path):
    """Discovery must keep serving global and builtin skills without a cwd; only the project path drops."""
    result = _run_runtime_probe(tmp_path)
    assert result.returncode == 0, f"runtime probe crashed: {result.stderr[-800:]}"
    assert "ARMED_CWD=1" in result.stdout, (
        f"Path.cwd() did not raise, so the world never armed and this pin asserts nothing: {result.stdout!r}"
    )
    line = [ln for ln in result.stdout.splitlines() if ln.startswith("SEARCH_PATHS=")][0]
    labels = line.split("=", 1)[1].split(",")
    assert "project" not in labels, f"the un-answerable path was still offered: {labels}"
    assert "global" in labels and "builtin" in labels, f"discovery lost paths it could still resolve: {labels}"


def test_skill_creation_refuses_rather_than_guessing(tmp_path):
    """Creating into "the current project" must REFUSE, not write elsewhere."""
    result = _run_runtime_probe(tmp_path)
    assert result.returncode == 0, f"runtime probe crashed: {result.stderr[-800:]}"
    assert "ARMED_CWD=1" in result.stdout, (
        f"Path.cwd() did not raise, so the world never armed and this pin asserts nothing: {result.stdout!r}"
    )
    assert "CREATE_SUCCESS=False" in result.stdout, f"creation did not refuse without a cwd: {result.stdout!r}"
    assert "CREATE_ERROR_MENTIONS_CWD=True" in result.stdout, f"refusal did not name the reason: {result.stdout!r}"


# The child removes its own cwd and denies os.getcwd().
_FENCE_DEAD_CWD_DRIVER = r"""
import os
import runpy
import sys

seat, shape, doomed = sys.argv[2:5]
os.chdir(doomed)
try:
    os.rmdir(doomed)
except OSError:
    print("REMOVED=0")
exec(os.environ["SKILLS_WORLD_TEXT"])

# ARMING PROBE - a cwd the child can still read would make the verdict below
# say nothing about a dead one.
try:
    os.getcwd()
except OSError:
    print("ARMED_CWD=1")
else:
    print("ARMED_CWD=0")

sys.argv = [seat, shape]
runpy.run_path(seat, run_name="__main__")
"""


def _run_fence_with_a_dead_cwd(seat: Path, tmp_path: Path) -> list:
    """Run the fence probe at `seat` (shape pkg) in a child whose cwd is gone."""
    doomed = tmp_path / "doomed_cwd"
    doomed.mkdir()
    env = dict(os.environ, PYTHONPATH=str(SRC_ROOT), SKILLS_WORLD_TEXT=WORLD_GETCWD_DENIED)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; exec(compile(sys.argv[1], '<string>', 'exec'))",
            _FENCE_DEAD_CWD_DRIVER,
            str(seat),
            "pkg",
            str(doomed),
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
        cwd=str(tmp_path),
        timeout=60,
    )
    assert result.returncode == 0, f"the fence probe crashed under a dead cwd: {result.stderr[-800:]}"
    lines = result.stdout.strip().splitlines()
    assert "ARMED_CWD=1" in lines, f"the cwd was still readable, so this pin asserts nothing: {lines}"
    return lines


def test_the_fence_lets_kin_through_with_a_dead_cwd(tmp_path):
    """The branch's own seat imports its handlers with no readable cwd."""
    kin_seat = BRANCH_ROOT / "tests" / "support_fence.py"
    assert _run_fence_with_a_dead_cwd(kin_seat, tmp_path)[-1] == "ALLOWED"


def test_the_fence_refuses_an_elsewhere_seat_with_a_dead_cwd(tmp_path):
    """A seat outside any branch is still refused, and named, with no readable cwd.

    Without this, a fence broken under a dead cwd passes the kin pin above by letting everybody in.
    """
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir()
    seat.write_bytes((BRANCH_ROOT / "tests" / "support_fence.py").read_bytes())
    assert _run_fence_with_a_dead_cwd(seat, tmp_path)[-1] == "DENIED Caller branch: unknown"


class TestTheModuleWalk:
    def test_the_walk_skips_sandboxes_by_name_relative_to_its_root(self, tmp_path):
        """Pins the shipped defect: docs.local/ scratch tools were walked and went RED as modules.

        The root stands inside a directory named dropbox, so a skip judged on the whole path would hide the branch.
        """
        branch = tmp_path / "dropbox" / "skills"
        for rel in (
            "apps/a.py",
            "dropbox/tool.py",
            "docs.local/x/tool.py",
            ".archive/old.py",
            "tests/test_a.py",
            "apps/b(disabled).py",
        ):
            target = branch / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text("", encoding="utf-8")

        assert _skills_modules(branch) == ["aipass.skills.apps.a"]
