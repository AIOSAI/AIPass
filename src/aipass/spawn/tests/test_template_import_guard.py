"""What the newborn's handler guard must survive on its very first import.

Every citizen is born carrying `apps/handlers/__init__.py` from the template,
and that file runs `_guard_branch_access()` at import time — so a defect in it
is not a defect in one branch, it is a defect in every branch the factory has
ever shipped and every one it will ship.

MEASURED 2026-08-30 (@drone's dead-cwd pin, reported by @devpulse): the guard
resolved frame filenames BEFORE skipping pseudo-files like `<string>`, and
`Path(...).resolve()` on a relative or pseudo filename calls `os.getcwd()`. Any
process whose working directory had been deleted therefore died with
FileNotFoundError while importing ANY branch. All 18 live copies were fixed in
32db831c; these pins guard the TEMPLATE, so the next spawned branch is born
with the guarded form instead of re-inheriting the defect.

The tests render the template into a throwaway package and import it in a
subprocess, because that is the only way to exercise a file whose whole
behaviour happens at import time. The defect pins reproduce it in two worlds —
an injected cwd failure that runs on every OS, and a genuinely deleted directory
that runs wherever the OS allows the recipe — and the fence pins exist so the
fix cannot be mistaken for a weakened guard: it must still refuse an outside
caller and still admit an inside one.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir


TEMPLATE_CLASSES = sorted(get_available_classes())

GUARD_RELATIVE_PATH = Path("apps") / "handlers" / "__init__.py"


def _template_guard(class_name: str) -> Path:
    return get_template_dir(class_name) / GUARD_RELATIVE_PATH


def _render(source: str) -> str:
    """Fill the two branch placeholders the way a real mint does."""
    return source.replace("{{BRANCHNAME}}", "NEWBORN").replace("{{BRANCH}}", "newborn")


def _plant_newborn(root: Path, class_name: str) -> Path:
    """Write the rendered guard at the path a real newborn would carry it.

    Returns the directory to put on sys.path.
    """
    package = root / "aipass" / "newborn" / "apps" / "handlers"
    package.mkdir(parents=True)

    for parent in (root / "aipass", root / "aipass" / "newborn", root / "aipass" / "newborn" / "apps"):
        (parent / "__init__.py").write_text("", encoding="utf-8")

    (package / "__init__.py").write_text(
        _render(_template_guard(class_name).read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return root


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script).strip()],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


# =============================================================================
# The two worlds, and why both exist
# =============================================================================

# The condition these pins reproduce is "the cwd read RAISES", not "a directory
# was deleted" — deletion is one way to arrive there, and on Windows it is not
# an available one: Windows locks a process's current directory, so the recipe
# dies at rmdir with WinError 32 before the test reaches its claim (round-2
# Windows gate, relayed by @devpulse 2026-08-31).
#
# MY PICK, stated so it can be quoted: BOTH, scoped by what each can honestly
# measure — @memory's injection as the portable pin that runs on every OS, and
# @drone's real-world recipe kept and skipped on win32, because Windows makes
# the RECIPE unavailable, not the STATE (a disconnected share or an ejected
# volume hands a live Windows process a dead cwd).
#
# @devpulse asked whether mine are the quiet species — a relative path resolving
# to the WRONG place rather than crashing — because the injection would then
# need to fake a different world. I MEASURED IT RATHER THAN ANSWERING: I rebuilt
# the pre-32db831c form (resolve first, skip second) and ran it with a live cwd
# from outside the newborn tree. Both forms imported cleanly. The old form
# still skipped `<string>` — it just paid for the resolve first — so the ONLY
# behavioural difference between defective and fixed is whether that resolve
# raises. There is no quiet species here, and that is precisely what licenses
# the injection: it reproduces the whole of the discriminator, not part of it.
#
# The injection carries a POSITIVE CONTROL for the same reason @memory's own
# skip-reads-green mutant taught the fleet: a faked world that fails to fake
# anything makes every pin pass. The child proves the call site is broken before
# it imports, and a test whose world did not take SKIPS with that reason instead
# of reporting a green it did not earn.

WINDOWS_RECIPE_SKIP = (
    "Windows locks a process's current working directory, so this recipe dies at "
    "rmtree with WinError 32 before reaching its claim. Windows makes the RECIPE "
    "unavailable, not the STATE — the portable injection pin above covers the "
    "state on every OS, and a disconnected share is how a live Windows process "
    "reaches it for real."
)

# The control probe is the SAME text in both worlds, so neither world can be
# graded by a friendlier instrument than the other. It runs the exact call the
# defective guard made — Path("<string>").resolve() — and reports whether that
# call is currently broken.
_CONTROL_PROBE = """
    try:
        _ProbePath("<string>").resolve()
    except OSError:
        print("CONTROL_LIVE")
    else:
        print("CONTROL_DEAD")
"""

_INJECT_DEAD_CWD = (
    """
    import errno, os
    from pathlib import Path as _ProbePath

    def _no_cwd(*args, **kwargs):
        raise FileNotFoundError(errno.ENOENT, "No such file or directory")

    os.getcwd = _no_cwd
"""
    + _CONTROL_PROBE
)

_DELETE_CWD = (
    """
    import os, shutil, tempfile
    from pathlib import Path as _ProbePath

    doomed = tempfile.mkdtemp()
    os.chdir(doomed)
    shutil.rmtree(doomed)
"""
    + _CONTROL_PROBE
)

_NO_WORLD_AT_ALL = (
    """
    from pathlib import Path as _ProbePath
"""
    + _CONTROL_PROBE
)


def _in_dead_cwd(root: Path, world: str, tail: str, cwd: Path):
    """Run `tail` in a child whose cwd read is broken by `world`."""
    return _run(
        f"""
        import sys
        sys.path.insert(0, {str(root)!r})
        {textwrap.indent(textwrap.dedent(world).strip(), " " * 8).lstrip()}
        {textwrap.indent(textwrap.dedent(tail).strip(), " " * 8).lstrip()}
        """,
        cwd=cwd,
    )


def _require_live_world(result):
    """Skip rather than pass when the faked world did not actually break."""
    lines = result.stdout.split()
    if "CONTROL_DEAD" in lines:
        pytest.skip(
            "world not exercised: the injected os.getcwd failure does not reach "
            "Path.resolve() on this platform (Windows resolves through "
            "_getfullpathname, not os.getcwd), so nothing is claimed either way"
        )
    assert "CONTROL_LIVE" in lines, (
        f"the child never reported whether its world took:\n{result.stdout}\n{result.stderr}"
    )
    return lines


# =============================================================================
# The defect itself — portable form (runs on every OS)
# =============================================================================


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_cwd_that_cannot_be_read(class_name, tmp_path):
    """Import the newborn's handlers where reading the cwd raises.

    `-c` gives the top frame the pseudo-filename `<string>`, and the defective
    guard resolved it before skipping it — so the import died on a call the
    fixed guard never makes. MEASURED red against the pre-fix form on Linux.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        _INJECT_DEAD_CWD,
        """
        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result)
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported when the cwd cannot be read:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_resolve_is_never_reached_for_a_pseudo_filename(class_name, tmp_path):
    """Ordering pin: pseudo-files are skipped before anything touches the disk.

    Behaviourally identical to the pin above for today's code, but it fails on
    the ORDERING rather than on the whole import — so a future rewrite that
    reintroduces an early resolve() is named precisely.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        _INJECT_DEAD_CWD,
        """
        from aipass.newborn.apps.handlers import _find_real_caller

        caller, line = _find_real_caller()
        print("NO_CRASH")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result)
    assert result.returncode == 0, f"_find_real_caller still needs a cwd:\n{result.stderr}"
    assert lines[-1] == "NO_CRASH"


# =============================================================================
# The defect itself — real-world form (POSIX only, by ruling)
# =============================================================================


@pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_RECIPE_SKIP)
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_deleted_working_directory(class_name, tmp_path):
    """The same claim against a genuinely deleted cwd — no faking at all.

    This is the pin the injection stands in for. Keeping it means the stand-in
    is never the only evidence on the platforms where the real world is
    reachable.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        _DELETE_CWD,
        """
        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result)
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported from a deleted cwd:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


class TestBothConstructionsAgree:
    """@memory's licensing condition, made a test rather than a promise.

    The injection is a legitimate stand-in only for as long as it produces the
    IDENTICAL answer from the IDENTICAL call site as the real deleted-directory
    world. Both run on POSIX, so that is checkable here every time the suite
    runs — and the day it stops being true, this goes red instead of the
    stand-in quietly drifting away from the world it claims to model.
    """

    CALL_SITE = """
        from pathlib import Path

        try:
            Path("<string>").resolve()
        except OSError:
            print("RAISED")
        else:
            print("RESOLVED")
        """

    @pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_RECIPE_SKIP)
    def test_the_two_worlds_answer_the_call_site_identically(self, tmp_path):
        (tmp_path / "stand_here").mkdir()

        injected = _in_dead_cwd(tmp_path, _INJECT_DEAD_CWD, self.CALL_SITE, tmp_path / "stand_here")
        deleted = _in_dead_cwd(tmp_path, _DELETE_CWD, self.CALL_SITE, tmp_path / "stand_here")

        assert injected.returncode == deleted.returncode == 0
        assert injected.stdout.split() == deleted.stdout.split() == ["CONTROL_LIVE", "RAISED"], (
            "the injection no longer models the deleted-directory world:\n"
            f"  injected: {injected.stdout.split()}\n  deleted:  {deleted.stdout.split()}"
        )

    def test_the_control_probe_can_report_a_world_that_did_not_take(self):
        """The control's own negative control — it must be able to say NO.

        A control that always reports CONTROL_LIVE is worse than no control: it
        turns every portable pin into a vacuous green on exactly the platform
        where the injection may not reach the call site. Run the probe with no
        world applied at all; a healthy cwd must make it say so.
        """
        result = _run(_NO_WORLD_AT_ALL, cwd=Path(__file__).parent)

        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["CONTROL_DEAD"], (
            "the control probe reports a broken world on a healthy machine — it "
            f"cannot distinguish anything: {result.stdout!r}"
        )

    def test_the_windows_skip_states_the_ruling_not_just_the_symptom(self):
        """The skip reason is the evidence a future reader gets — pin it.

        Readable from Linux, so both answers are observable without a Windows
        box: what is pinned is what the skipped tests SAY, not that they ran.
        """
        marks = [m for m in test_newborn_import_survives_a_deleted_working_directory.pytestmark if m.name == "skipif"]
        assert len(marks) == 1, "the deleted-cwd recipe lost its platform skip"

        reason = marks[0].kwargs["reason"]
        assert "WinError 32" in reason
        assert "RECIPE" in reason and "STATE" in reason, "the skip must say WHY Windows is excused, not just that it is"
        assert marks[0].args[0] is (sys.platform == "win32")


# =============================================================================
# The fence the fix must not have weakened
# =============================================================================


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_still_refuses_an_outside_caller(class_name, tmp_path):
    """A file outside the newborn's tree importing its handlers is still blocked."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    outsider = tmp_path / "outsider"
    outsider.mkdir()
    caller = outsider / "trespass.py"
    caller.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            try:
                import aipass.newborn.apps.handlers
            except ImportError as exc:
                print("BLOCKED" if "ACCESS DENIED" in str(exc) else "OTHER")
            else:
                print("ALLOWED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(caller)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_admits_its_own_code(class_name, tmp_path):
    """A file inside the newborn's own tree imports its handlers freely."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    insider = root / "aipass" / "newborn" / "apps" / "inside.py"
    insider.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            import aipass.newborn.apps.handlers
            print("ADMITTED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(insider)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, f"the guard locked a newborn out of its own handlers:\n{result.stderr}"
    assert result.stdout.strip() == "ADMITTED"
