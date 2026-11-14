# =================== AIPass ====================
# META DATA HEADER
# Name: test_import_dead_cwd.py - commons imports without a readable cwd
# Description: Pins that commons imports with a deleted cwd, and the sys.path[0] repair in apps/commons.py
# Version: 1.2.0
# Created: 2026-08-31
# Modified: 2026-11-02
# Category: commons/tests
# =============================================

"""Tests for apps/commons.py and every module under apps/: each imports without a readable working directory."""

# The declared pass — what is NOT tested here, and what covers it instead:

import ast
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.commons.tests import support_fence

KIN_PROBE = Path(support_fence.__file__)

# The worlds deny getcwd; other branches are preloaded healthy so only commons' own sites are
# measured. Below 3.11 pathlib caches its accessor at its own import, so the denial cannot fire
# there: the probe reports it (never a skipif), asserted to happen only below 3.11.

# Shared by every world below, with its arming probe, so no world can go quietly vacuous.
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


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

# Probe the instrument: does THIS interpreter's resolve() of a relative path reach
# the denied call at all? Pre-3.11 pathlib already cached the original in its
# _NormalAccessor at its own import, so the rebind above cannot reach it there.
import pathlib

try:
    pathlib.Path("relative").resolve()
    print("PROBE_VACUOUS")
except FileNotFoundError:
    print("PROBE_ARMED")
"""

# json_handler, identity_ops and db each build a module-level constant from Path(__file__).resolve();
# reaching any of them also runs the package guard in apps/handlers/__init__.py.
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

# The fence probe (support_fence.py) under the denial, from the seat the test names. Apart from the
# sweep because the fence resolves every frame's path, a cwd read the constants above do not make.
_FENCE_PROBE_BODY = r"""
import runpy
import sys

sys.argv = [{seat!r}, {shape!r}]
runpy.run_path({seat!r}, run_name="__main__")
"""


def _fence_world(seat: Path, shape: str) -> str:
    return _PREAMBLE + _FENCE_PROBE_BODY.format(seat=str(seat), shape=shape)


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )


def _assert_probe_armed(out: str) -> None:
    """The instrument must be able to fire, or the pin proves nothing."""
    if "PROBE_VACUOUS" in out:
        # Legal only below 3.11, where pathlib cached its accessor before the rebind ran.
        assert sys.version_info < (3, 11), (
            "resolve() survived the denial on an interpreter that reads "
            "os.getcwd live - the instrument is broken, not the world"
        )
    else:
        assert "PROBE_ARMED" in out, f"probe printed neither outcome:\n{out}"


def test_handler_modules_import_with_dead_cwd():
    """The three module-level resolve() sites, under a denied cwd."""
    result = _run(SWEEP_WORLD)
    out = result.stdout

    assert "IMPORTED" in out, f"import died under the dead-cwd world:\nstdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


@pytest.mark.parametrize("shape", ["pkg", "deep", "mock"])
def test_the_fence_lets_its_own_branch_in_under_a_dead_cwd(shape):
    """The kin seat is allowed with every path resolve denied, so the fence's walk needs no cwd."""
    result = _run(_fence_world(KIN_PROBE, shape))
    out = result.stdout

    assert out.strip().splitlines()[-1:] == ["ALLOWED"], f"stdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


def test_the_fence_refuses_an_elsewhere_caller_under_a_dead_cwd(tmp_path):
    """A seat outside any aipass tree is still refused and named when no path can be resolved."""
    seat = tmp_path / "elsewhere" / "probe.py"
    seat.parent.mkdir(parents=True)
    shutil.copy(KIN_PROBE, seat)

    result = _run(_fence_world(seat, "pkg"))
    out = result.stdout

    assert out.strip().splitlines()[-1:] == ["DENIED Caller branch: unknown"], f"stdout={out}\nstderr={result.stderr}"
    _assert_probe_armed(out)


# A peer with an uncured guard raises FileNotFoundError at import, an OSError `except ImportError`
# misses; commons' optional cross-branch imports must survive it. A meta_path finder raises it,
# because the claim is the exception type crossing the branch boundary, not how the peer raised it.

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


# The entry point's sys.path repair. Through a symlinked directory sys.path[0] may be the real
# directory while __file__ keeps the link, so commons.py removes BOTH spellings. Pinned as CAUSE
# (two spellings exist), OUTCOME (sys.path[0] is one of them) and LINK (commons.py removes both),
# so a red names its own mechanism.


# sys.path[0] through a symlinked directory: "resolved" or "unresolved".
_SYS_PATH0_SPELLING = {
    "posix": "resolved",
}


def _spellings_matching(path0: str, unresolved: str, resolved: str) -> list:
    """Which of the two spellings apps/commons.py removes does sys.path[0] equal?

    Extracted so a third spelling, or both coinciding, unreachable on any one platform, is testable.
    """
    spellings = {"resolved": resolved, "unresolved": unresolved}
    return sorted(name for name, value in spellings.items() if value == path0)


def _assert_matches_table(platform: str, matched: list, path0: str = "") -> None:
    """Hold a run against the recorded expectation for its platform.

    Extracted so the disagreeing case is reachable: a live probe always agrees with its own row.
    """
    expected = _SYS_PATH0_SPELLING[platform]
    assert expected in matched, (
        f"on {platform} sys.path[0] was recorded as {expected!r} but this run "
        f"matched {matched} — the table is now wrong, and the repair may be "
        f"relying on a spelling the host stopped using. sys.path[0]={path0!r}"
    )


def _assert_probe_is_usable(probe: dict) -> None:
    """Judge a probe result. Synthetic-testable for the same reason as above."""
    if not probe["built"]:
        assert probe["reason"], "the world failed to build and did not say why"
        raise AssertionError(f"the host could not build a symlink world: {probe['reason']} — that is a broken machine")
    else:
        assert probe["path0"] and probe["unresolved"] and probe["resolved"], (
            f"the probe reported success with an empty field: {probe}"
        )


def _symlink_spelling_probe(tmp_path) -> dict:
    """Run a script through a symlinked directory; an unbuildable world is returned as data, never skipped."""
    real = tmp_path / "real"
    real.mkdir()
    (real / "probe.py").write_text(
        "import sys\nfrom pathlib import Path\n"
        "print(sys.path[0])\nprint(str(Path(__file__).parent))\n"
        "print(str(Path(__file__).resolve().parent))\n",
        encoding="utf-8",
    )
    link = tmp_path / "link"
    link.symlink_to(real, target_is_directory=True)

    result = subprocess.run(
        [sys.executable, str(link / "probe.py")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "utf-8"},
        timeout=60,
    )
    lines = result.stdout.strip().splitlines()
    if len(lines) != 3:
        return {"built": False, "reason": f"probe produced {len(lines)} lines: {result.stdout!r} {result.stderr!r}"}

    path0, unresolved, resolved = lines
    return {"built": True, "reason": "", "path0": path0, "unresolved": unresolved, "resolved": resolved}


def test_symlink_world_buildability_is_recorded(tmp_path):
    """CONTROL — an unbuildable symlink world is an assertion either way, never a silent skip."""
    _assert_probe_is_usable(_symlink_spelling_probe(tmp_path))


def test_cause_a_symlinked_invocation_yields_two_spellings(tmp_path):
    """CAUSE — the fact that makes commons.py's .resolve() load-bearing at all."""
    probe = _symlink_spelling_probe(tmp_path)
    if not probe["built"]:
        return  # buildability is asserted by its own pin above

    assert probe["unresolved"] != probe["resolved"], (
        "the symlink was not exercised - this run measured nothing. "
        f"unresolved={probe['unresolved']!r} resolved={probe['resolved']!r}"
    )


def test_outcome_sys_path0_is_one_of_the_two_spellings_commons_removes(tmp_path):
    """OUTCOME — the claim production actually depends on."""
    probe = _symlink_spelling_probe(tmp_path)
    if not probe["built"]:
        return

    matched = _spellings_matching(probe["path0"], probe["unresolved"], probe["resolved"])

    assert probe["path0"] in (probe["unresolved"], probe["resolved"]), (
        "sys.path[0] is a THIRD spelling that apps/commons.py does not remove, "
        "so the shadowing repair silently does nothing here.\n"
        f"  os.name     = {os.name}\n"
        f"  sys.path[0] = {probe['path0']!r}\n"
        f"  unresolved  = {probe['unresolved']!r}\n"
        f"  resolved    = {probe['resolved']!r}"
    )

    _assert_matches_table(os.name, matched, probe["path0"])


def test_link_commons_removes_both_spellings(tmp_path):
    """LINK — commons.py collects and removes both spellings; source-level."""
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


# log_operation's caller auto-detect (it names each module's log file) under a denied cwd. The
# frame doing the lookup is a real compiled probe_caller.py, so the pin asserts the answer, not only
# the absence of a crash.

_CALLER_PROBE_WORLD = r"""
import os
import sys

probe_dir = {probe_dir!r}

# Every write this world makes lands under probe_dir, never in the real tree.
os.environ["AIPASS_TEST_LOG_DIR"] = probe_dir

# Written BEFORE the denial: a genuine module on disk, so the frame the lookup
# reads is compiled source and not a "<string>" pseudo-name. It sits in tmp, a
# foreign seat, so it takes the shim through a modules door; the handlers fence
# refuses a foreign seat that imports the handler itself (DPLAN-0404).
#
# Measured THROUGH log_operation rather than by calling the detector, because
# after DPLAN-0325 there is no detector to call: the shim binds the one prax
# service and publishes nine names, none of them private. A direct call would
# also be one frame short — the service resolves the caller at _getframe(2),
# counting on log_operation's own frame sitting between — so the honest probe
# is the public one, and the ANSWER is read off the document it wrote.
with open(os.path.join(probe_dir, "probe_caller.py"), "w", encoding="utf-8") as fh:
    fh.write(
        "from aipass.commons.apps.modules.commons_identity import json_handler\n"
        "def _inner():\n"
        "    json_handler.log_operation('probe', {{'ok': True}})\n"
        "    directory = json_handler.get_json_path('probe', 'log').parent\n"
        "    written = sorted(p.name for p in directory.glob('*_log.json'))\n"
        "    return ','.join(n[: -len('_log.json')] for n in written)\n"
        "def ask():\n"
        "    return _inner()\n"
    )
sys.path.insert(0, probe_dir)

import aipass.prax  # noqa: F401
import aipass.prax.apps.modules.logger  # noqa: F401
import aipass.cli.apps.modules  # noqa: F401
import rich.console  # noqa: F401
import linecache  # noqa: F401
import probe_caller


def _dead_getcwd():
    raise FileNotFoundError(2, "cwd deleted", "")


os.getcwd = _dead_getcwd

try:
    print("NAME:" + probe_caller.ask())
except OSError as exc:
    print("RAISED:" + type(exc).__name__)
"""


def test_caller_module_autodetect_survives_and_answers_under_a_dead_cwd(tmp_path):
    """log_operation's module auto-detect must name the caller, not raise."""
    result = _run(_CALLER_PROBE_WORLD.format(probe_dir=str(tmp_path)))
    out = result.stdout

    assert "NAME:probe_caller" in out, (
        "the auto-detect either raised or named the wrong module under a dead "
        f"cwd:\nstdout={out}\nstderr={result.stderr}"
    )


# The judgements above, fed synthetic input: their failing branches (third spelling,
# unbuildable world) are unreachable from a live probe.


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
    """The third-spelling row is the only input for which the outcome pin must FAIL, and no live run reaches it."""
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
    "platform, matched, raises, why",
    [
        ("posix", ["resolved"], False, "the recorded POSIX answer"),
        ("posix", ["resolved", "unresolved"], False, "both spellings coincide — still contains the record"),
        ("posix", ["unresolved"], True, "POSIX stopped using the resolved spelling — the table is stale"),
        ("posix", [], True, "a third spelling — the record cannot be satisfied"),
    ],
)
def test_the_table_crosscheck_only_fires_where_something_was_recorded(platform, matched, raises, why):
    """The disagreeing rows are unreachable from any live probe; only synthetic input gives the check teeth."""
    if raises:
        with pytest.raises(AssertionError, match="the table is now wrong"):
            _assert_matches_table(platform, matched)
    else:
        _assert_matches_table(platform, matched)


def test_the_outcome_pin_actually_calls_the_table_crosscheck():
    """STRUCTURAL — the outcome pin calls the table crosscheck; deleting that call fails no behavioural pin."""
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
