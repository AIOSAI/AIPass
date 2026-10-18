# =================== AIPass ====================
# Name: test_template_import_guard.py
# Description: What the newborn's handler guard must survive on its very first import
# Version: 1.1.1
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for templates/citizen/apps/handlers/__init__.py, the newborn's import-time access guard."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/modules/core.py parses and imports
# seedgo: no-test-needed(documentation) — docstrings on the guard's helper functions in the template

import ast
import importlib
import ntpath
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir
from aipass.spawn.apps.modules import core
from aipass.spawn.tests.support_template_import_guard import (
    _ARM_THE_ROUTE,
    _BUILD_PROBE_PATH,
    _CONTROL_PROBE,
    _DENY_REALPATH,
    _EMULATE_310,
    _HOST_FACTS,
    _PATHLIB_ROUTE_PROBE,
    _PLATFORM_EMULATIONS,
    _child_script,
    _require_live_world,
    _run,
    _simulation_unavailable,
)

# The guard runs at import in every newborn, so it is rendered and imported in a subprocess.
# It must survive an unreadable cwd (resolving a pseudo filename calls os.getcwd) and still
# refuse an outside caller. CPython line numbers below are courtesies; the mechanism is the claim.


TEMPLATE_CLASSES = sorted(get_available_classes())

GUARD_RELATIVE_PATH = Path("apps") / "handlers" / "__init__.py"


def _template_guard(class_name: str) -> Path:
    return get_template_dir(class_name) / GUARD_RELATIVE_PATH


def _render(source: str) -> str:
    """Fill the two branch placeholders the way a real mint does."""
    return source.replace("{{BRANCHNAME}}", "NEWBORN").replace("{{BRANCH}}", "newborn")


def _plant_newborn(root: Path, class_name: str) -> Path:
    """Write the rendered guard at the path a real newborn would carry it; returns the sys.path root."""
    package = root / "aipass" / "newborn" / "apps" / "handlers"
    package.mkdir(parents=True)

    for parent in (root / "aipass", root / "aipass" / "newborn", root / "aipass" / "newborn" / "apps"):
        (parent / "__init__.py").write_text("", encoding="utf-8")

    (package / "__init__.py").write_text(
        _render(_template_guard(class_name).read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return root


# Named by a variable so the verdict is the fence's frame walk, not its line rule.
_FOREIGN_PROBE = """
    import importlib

    name = "aipass.newborn.apps." + "handlers"
    try:
        importlib.import_module(name)
    except ImportError as exc:
        callers = [ln.strip() for ln in str(exc).splitlines() if "Caller branch" in ln]
        print(callers[0] if "ACCESS DENIED" in str(exc) and callers else "OTHER")
    else:
        print("ALLOWED")
    """


def _run_seat(seat: Path, root: Path, body: str, cwd: Path) -> subprocess.CompletedProcess:
    """Write `body` as a file at `seat`, with the planted tree first on sys.path, and run it.

    A real file, not `-c`: the fence judges a caller by its file's path."""
    seat.parent.mkdir(parents=True, exist_ok=True)
    head = f"import sys\n\nsys.path.insert(0, {str(root)!r})\n\n"
    seat.write_text(head + textwrap.dedent(body).strip() + "\n", encoding="utf-8")
    return subprocess.run(
        [sys.executable, str(seat)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=str(cwd),
    )


# The condition is "the cwd read RAISES": an injected world runs on every OS, a deleted
# directory wherever the OS allows it. The injection carries a positive control, so a world
# that did not take SKIPS instead of reading green.

WINDOWS_RECIPE_SKIP = (
    "Windows locks a process's current working directory, so this recipe dies at "
    "rmtree with WinError 32 before reaching its claim. Windows makes the RECIPE "
    "unavailable, not the STATE — the portable injection pin above covers the "
    "state on every OS, and a disconnected share is how a live Windows process "
    "reaches it for real."
)

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

PORTABLE_WORLDS = {
    "getcwd-denied": _INJECT_DEAD_CWD,
    # Windows CI died in inspect's unprotected os.path.realpath; a getcwd denial never reaches it on POSIX.
    "realpath-denied": _DENY_REALPATH,
}

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


# Relative input: on <=3.10 cwd and resolve ride different captured attributes.
_PATHLIB_ROUTE_PROBE_RELATIVE = """
    from pathlib import Path as _RoutePath

    try:
        _RoutePath("relative_thing").resolve()
    except OSError:
        print("PATHLIB_ARMED")
    else:
        print("PATHLIB_INERT")
"""

# Patches a dunder, never `pathlib.Path = X(Path)`: Path.__new__'s `cls is Path` global lookup
# would then downgrade X to a plain PosixPath. Pinned below against a tidier rewrite.
_A_CONCRETE_CLASS_THAT_SPELLS_ANOTHER_DIALECT = """
    import pathlib

    _real_fspath = pathlib.PurePath.__fspath__

    def _fspath_in_another_dialect(self):
        return _real_fspath(self).replace("/", chr(92))

    pathlib.PurePath.__fspath__ = _fspath_in_another_dialect
    print("DIALECT_INSTALLED")
"""

# Every row runs through an explicit platform emulation, whatever the host.
_GETCWD_TABLE = {
    ("posix", "absolute"): "PATHLIB_INERT",
    ("posix", "relative"): "PATHLIB_ARMED",
    ("nt", "absolute"): "PATHLIB_ARMED",
    ("nt", "relative"): "PATHLIB_ARMED",
}


class TestTheGetcwdRouteNeedsNoAccessorPatch:
    """@skills' round-7 return finding, answered by measurement.

    realpath looks up os.getcwd at call time, so no accessor patch is needed; Path.cwd() on <=3.10
    stays unreachable, and the guard never calls it. Emulate both platforms or neither."""

    @staticmethod
    def _emulation_or_skip(route: str) -> str:
        """One gate for every row that installs a platform, and the only one."""
        emulation, requires = _PLATFORM_EMULATIONS[route]
        why = _simulation_unavailable(requires, _HOST_FACTS)
        if why:
            pytest.skip(f"the {route} emulation cannot speak from this host: {why}")
        return emulation

    def _verdict(self, route: str, probe: str) -> str:
        emulation = self._emulation_or_skip(route)

        result = _run(
            _child_script(
                emulation,
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _INJECT_DEAD_CWD,
                _PATHLIB_ROUTE_PROBE if probe == "absolute" else _PATHLIB_ROUTE_PROBE_RELATIVE,
            ),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "PROBE_NOT_ABS" not in lines, (
            f"the probe literal is not absolute under the {route} emulation — an "
            f"absolute path is whatever that platform says it is:\n{result.stdout}"
        )
        assert "ROUTE_ARMED" in lines, f"the route never armed ({route}/{probe}):\n{result.stdout}\n{result.stderr}"

        built = result.stdout.split("PROBE_PATH ", 1)[1].splitlines()[0]
        if route == "nt":
            assert ntpath.splitdrive(built)[0], (
                "the windows emulation built a drive-less literal. On 3.12 that "
                "changes nothing (ntpath.isabs still accepted rooted paths); on "
                "3.13 abspath falls through to os.getcwd and the probe dies "
                f"building its own argument: {built!r}"
            )
        else:
            assert not ntpath.splitdrive(built)[0], f"a posix row produced a drive: {built!r}"

        armed = [line for line in lines if line.startswith("PATHLIB_")]
        assert armed, f"the probe reported nothing ({route}/{probe}):\n{result.stdout}\n{result.stderr}"
        return armed[0]

    @pytest.mark.parametrize(("route", "probe"), sorted(_GETCWD_TABLE))
    def test_the_getcwd_denial_answers_the_same_way_the_table_says(self, route, probe):
        expected = _GETCWD_TABLE[(route, probe)]

        assert self._verdict(route, probe) == expected, (
            f"the {route} route answered differently for a {probe} path than the "
            "table says. If this is the nt row, read ntpath.realpath again "
            "before editing the table — the getcwd read ABOVE the isabs check "
            "is what the row is derived from (ordering, not line number)."
        )

    def test_the_live_platform_agrees_with_its_own_row(self):
        """The emulations are stand-ins; this is the host answering for itself."""
        route = "nt" if os.name == "nt" else "posix"

        result = _run(
            _child_script(_BUILD_PROBE_PATH, _EMULATE_310, _ARM_THE_ROUTE, _INJECT_DEAD_CWD, _PATHLIB_ROUTE_PROBE),
            cwd=Path(__file__).parent,
        )
        lines = result.stdout.split()
        assert "ROUTE_ARMED" in lines, result.stdout
        live = [line for line in lines if line.startswith("PATHLIB_")][0]

        assert live == _GETCWD_TABLE[(route, "absolute")], (
            f"this host is {os.name!r} and answered {live} where its own table "
            f"row says {_GETCWD_TABLE[(route, 'absolute')]}"
        )

    def test_the_relative_probe_is_inert_with_no_world_at_all(self):
        """The control for the control: no denial, no arming."""
        result = _run(
            _child_script(_BUILD_PROBE_PATH, _EMULATE_310, _ARM_THE_ROUTE, _PATHLIB_ROUTE_PROBE_RELATIVE),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            "the relative probe raised with NO world installed — it is "
            f"convicting for its own shape, not for the denial:\n{result.stdout}\n{result.stderr}"
        )

    def test_a_posix_route_with_a_foreign_dialect_class_is_the_windows_red(self):
        """CI's windows red, reproduced from Linux — and the reason for the gate.

        Only a foreign-dialect concrete class differs from the posix row; INERT becomes ARMED."""
        emulation = self._emulation_or_skip("posix")

        result = _run(
            _child_script(
                emulation,
                _BUILD_PROBE_PATH,
                _A_CONCRETE_CLASS_THAT_SPELLS_ANOTHER_DIALECT,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _INJECT_DEAD_CWD,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "DIALECT_INSTALLED" in result.stdout.split(), (
            f"the chimera never got built, so this measured nothing:\n{result.stdout}\n{result.stderr}"
        )
        assert "PATHLIB_ARMED" in result.stdout.split(), (
            "a posix os.path with a foreign-dialect concrete class no longer "
            "reads the cwd for an absolute literal — if this is genuinely fixed "
            f"upstream, the windows skip above can go:\n{result.stdout}\n{result.stderr}"
        )
        assert self._verdict("posix", "absolute") == "PATHLIB_INERT", (
            "the control moved too — then the difference above is not the dialect"
        )

    def test_a_stand_in_that_subclasses_the_class_it_replaces_is_downgraded(self):
        """Why the dialect stand-in patches a dunder instead of adding a class.

        Kept or downgraded are both legal; a half-built surviving subclass never is."""
        result = _run(
            _child_script(
                _BUILD_PROBE_PATH,
                """
                import pathlib

                class _Subclassed(pathlib.Path):
                    pass

                pathlib.Path = _Subclassed
                _made = pathlib.Path(_ARM_ABS)
                _kept = type(_made) is _Subclassed
                print("SUBCLASS_KEPT" if _kept else "SUBCLASS_DOWNGRADED", type(_made).__name__)
                print("INITIALISED" if hasattr(_made, "_raw_paths") else "UNINITIALISED")
                """,
            ),
            cwd=Path(__file__).parent,
        )

        lines = result.stdout.split()
        assert ("SUBCLASS_KEPT" in lines) != ("SUBCLASS_DOWNGRADED" in lines), (
            f"the probe reported neither verdict:\n{result.stdout}\n{result.stderr}"
        )
        if "SUBCLASS_DOWNGRADED" in lines:
            assert "UNINITIALISED" in lines, (
                "the interpreter swapped the class but ran __init__ anyway — then "
                "the trap this comment describes is not the one that happens here"
            )
        else:
            assert "INITIALISED" in lines, (
                "a subclass survived installation as a HALF-BUILT object: it will "
                f"die at the first str(), a long way from here:\n{result.stdout}"
            )

    def test_no_row_of_the_table_runs_bare(self):
        """@memory's rule, pinned where it can rot: emulate BOTH or neither.

        A bare row is indistinguishable on its own host, so the table itself is pinned."""
        for route, (prelude, _requires) in _PLATFORM_EMULATIONS.items():
            assert prelude.strip(), (
                f"the {route!r} row installs nothing, so it measures whatever "
                "host runs it under a label that says otherwise"
            )
        assert set(_PLATFORM_EMULATIONS) == {row for row, _ in _GETCWD_TABLE}, (
            "a table row has no platform emulation, or an emulation has no rows"
        )

    @pytest.mark.parametrize("route", sorted(_PLATFORM_EMULATIONS))
    def test_an_emulation_stacked_on_its_own_platform_is_one_layer(self, route):
        """@seedgo's round-8 find, relayed by @devpulse, checked here.

        On Windows the nt emulation lands on a host already nt; applying it twice shows that from Linux."""
        emulation = self._emulation_or_skip(route)
        result = _run(
            _child_script(
                emulation,
                emulation,
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "RecursionError" not in result.stderr, (
            f"the {route} emulation calls the name it replaced — stacking it on "
            f"its own platform recurses:\n{result.stderr[-400:]}"
        )
        assert "ROUTE_ARMED" in result.stdout.split(), (
            f"the {route} emulation stopped working when applied twice:\n{result.stdout}\n{result.stderr}"
        )

    @pytest.mark.parametrize("route", sorted(_PLATFORM_EMULATIONS))
    def test_each_platform_emulation_is_inert_without_the_denial(self, route):
        """And the same for the platform stand-ins themselves (else every row is vacuously ARMED)."""
        result = _run(
            _child_script(
                self._emulation_or_skip(route),
                _BUILD_PROBE_PATH,
                _EMULATE_310,
                _ARM_THE_ROUTE,
                _PATHLIB_ROUTE_PROBE,
            ),
            cwd=Path(__file__).parent,
        )

        assert "PATHLIB_INERT" in result.stdout.split(), (
            f"the {route} emulation arms the probe with no denial installed — "
            f"every {route} row above is measuring the stand-in:\n{result.stdout}\n{result.stderr}"
        )


@pytest.mark.parametrize("world", sorted(PORTABLE_WORLDS))
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_cwd_that_cannot_be_read(class_name, world, tmp_path):
    """Import the newborn's handlers where reading the cwd raises.

    `-c` makes the top frame `<string>`; resolving it before skipping it is the defect."""
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _in_dead_cwd(
        root,
        PORTABLE_WORLDS[world],
        """
        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    lines = _require_live_world(result, world)
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported in the '{world}' world:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_a_cwd_inside_the_newborn_buys_a_foreign_seat_nothing(class_name, tmp_path):
    """A pseudo filename is never resolved, pinned through the import a stranger makes.

    Resolved against a cwd inside the newborn, frozen-bootstrap frames would read as kin."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    result = _run_seat(
        tmp_path / "aipass" / "foreign" / "probe.py",
        root,
        _FOREIGN_PROBE,
        cwd=root / "aipass" / "newborn",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Caller branch: foreign"


@pytest.mark.skipif(sys.platform == "win32", reason=WINDOWS_RECIPE_SKIP)
@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_deleted_working_directory(class_name, tmp_path):
    """The same claim against a genuinely deleted cwd — no faking at all."""
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

    lines = _require_live_world(result, "getcwd-denied")  # _DELETE_CWD is a cwd world
    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported from a deleted cwd:\n{result.stderr}"
    )
    assert lines[-1] == "IMPORTED"


class TestBothConstructionsAgree:
    """@memory's licensing condition, made a test rather than a promise.

    The injection is a valid stand-in only while it answers the call site as the deleted world does."""

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
        """The control's own negative control — it must be able to say NO."""
        result = _run(_NO_WORLD_AT_ALL, cwd=Path(__file__).parent)

        assert result.returncode == 0, result.stderr
        assert result.stdout.split() == ["CONTROL_DEAD"], (
            "the control probe reports a broken world on a healthy machine — it "
            f"cannot distinguish anything: {result.stdout!r}"
        )

    def test_the_windows_skip_states_the_ruling_not_just_the_symptom(self):
        """The skip reason is the evidence a future reader gets — pin it."""
        marks = [
            m
            for m in getattr(test_newborn_import_survives_a_deleted_working_directory, "pytestmark")
            if m.name == "skipif"
        ]
        assert len(marks) == 1, "the deleted-cwd recipe lost its platform skip"

        reason = marks[0].kwargs["reason"]
        assert "WinError 32" in reason
        assert "RECIPE" in reason and "STATE" in reason, "the skip must say WHY Windows is excused, not just that it is"
        assert marks[0].args[0] is (sys.platform == "win32")


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_still_refuses_an_outside_caller(class_name, tmp_path):
    """A file outside any aipass tree importing the newborn's handlers is refused as unknown."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    result = _run_seat(tmp_path / "outsider" / "trespass.py", root, _FOREIGN_PROBE, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Caller branch: unknown"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_refuses_a_foreign_branch_and_names_it(class_name, tmp_path):
    """A file under another branch's directory is refused, and the refusal names that branch."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    result = _run_seat(tmp_path / "aipass" / "foreign" / "probe.py", root, _FOREIGN_PROBE, cwd=tmp_path)

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "Caller branch: foreign"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_the_newborns_modules_door_is_open_to_a_foreign_branch(class_name, tmp_path):
    """A foreign seat imports a newborn module that imports the handlers on its behalf.

    Kin asked, so the fence lets it through. The scaffold ships no door file, so one is planted."""
    root = _plant_newborn(tmp_path / "tree", class_name)
    modules = root / "aipass" / "newborn" / "apps" / "modules"
    modules.mkdir()
    (modules / "__init__.py").write_text("", encoding="utf-8")
    (modules / "door_probe.py").write_text(
        "from aipass.newborn.apps.handlers import MY_BRANCH\n\n__all__ = ['MY_BRANCH']\n", encoding="utf-8"
    )

    result = _run_seat(
        tmp_path / "aipass" / "foreign" / "probe.py",
        root,
        """
        import importlib

        door = importlib.import_module("aipass.newborn.apps.modules.door_probe")
        print("ALLOWED " + door.MY_BRANCH)
        """,
        cwd=tmp_path,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "ALLOWED newborn"


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
        encoding="utf-8",
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, f"the guard locked a newborn out of its own handlers:\n{result.stderr}"
    assert result.stdout.strip() == "ADMITTED"


def _unguarded_module_level_resolves(source: str) -> list:
    """Line numbers of resolve() calls that run at import and are not guarded (module level, outside any try)."""
    tree = ast.parse(source)

    guarded = {
        getattr(node, "lineno")
        for block in ast.walk(tree)
        if isinstance(block, ast.Try)
        for node in ast.walk(block)
        if hasattr(node, "lineno")
    }

    # Walk what RUNS at import: function bodies are pruned, defaults and decorators are not.
    # Limit: a module-level call into a local function is not followed (needs a call graph).
    found = []
    pending: list[ast.AST] = list(tree.body)
    while pending:
        node = pending.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            pending.extend(getattr(node, "decorator_list", []))
            args = getattr(node, "args", None)
            if args is not None:
                pending.extend(args.defaults)
                pending.extend(d for d in args.kw_defaults if d is not None)
            continue
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "resolve"
            and node.lineno not in guarded
        ):
            found.append(node.lineno)
        pending.extend(ast.iter_child_nodes(node))

    return sorted(found)


class TestImportTimeRootDerivationSurvivesADeadCwd:
    """A newborn must not inherit a cwd read that runs at import.

    At module level a resolve() is guarded (ntpath.realpath reads the cwd even for absolute paths);
    inside a function it stays and raises, because a wrong-but-plausible root is worse."""

    def test_no_unguarded_module_level_resolve_anywhere_in_the_template(self):
        """The species, not the site — so a newborn cannot re-inherit the idiom."""
        offenders = []
        for path in _swept_py_files(get_template_dir("specialist")):
            # Render first: skipping unparseable placeholder files would exempt the likeliest offenders.
            offenders += [
                f"{path.name}:{line}"
                for line in _unguarded_module_level_resolves(_render(path.read_text(encoding="utf-8")))
            ]

        assert offenders == [], (
            "unguarded module-level resolve() in the template — this runs at "
            "import on every newborn, and ntpath.realpath reads the cwd even for "
            f"an absolute path: {offenders}"
        )

    @pytest.mark.parametrize(
        "label,source,expected",
        [
            (
                "module-level unguarded — the defect",
                "from pathlib import Path\nROOT = Path(__file__).resolve().parents[3]\n",
                [2],
            ),
            (
                "module-level guarded — the cure",
                "from pathlib import Path\ntry:\n    ROOT = Path(__file__).resolve().parents[3]\n"
                "except OSError:\n    ROOT = Path(__file__).parents[3]\n",
                [],
            ),
            (
                "inside a function — deliberately out of scope",
                "from pathlib import Path\ndef root():\n    return Path(__file__).resolve().parents[3]\n",
                [],
            ),
            (
                "default argument — written in a def, RUN at import",
                "from pathlib import Path\ndef root(base=Path(__file__).resolve()):\n    return base\n",
                [2],
            ),
            (
                "keyword-only default — same, one syntax over",
                "from pathlib import Path\ndef root(*, base=Path(__file__).resolve()):\n    return base\n",
                [2],
            ),
            (
                "decorator — also evaluated at import",
                "from pathlib import Path\n@register(Path(__file__).resolve())\ndef root():\n    pass\n",
                [2],
            ),
        ],
    )
    def test_the_detector_can_tell_the_three_cases_apart(self, label, source, expected):
        """The detector's own control — it must be able to say yes AND no."""
        assert _unguarded_module_level_resolves(source) == expected, label


class TestOptionalPeerImportsAreWideEnough:
    """A peer branch being broken is allowed; dying of it is not.

    A peer's import can raise OSError, so the fallback catches it; not Exception, so a real bug stays loud."""

    @staticmethod
    def _deny(module_prefix, exc):
        """A finder that raises `exc` for the named module and its children."""

        class _Denier:
            @staticmethod
            def find_spec(name, path=None, target=None):
                if name == module_prefix or name.startswith(module_prefix + "."):
                    raise exc
                return None

        return _Denier

    @staticmethod
    def _todos_meta_line(branch_root):
        """The local.json line carrying todos_meta, whole, as it stands on disk."""
        text = (branch_root / ".trinity" / "local.json").read_text(encoding="utf-8")
        return next(line for line in text.splitlines() if '"todos_meta"' in line)

    @pytest.mark.parametrize(
        "exc",
        [
            FileNotFoundError(2, "No such file or directory"),
            PermissionError(13, "Permission denied"),
            ImportError("@memory is not installed"),
        ],
        ids=["dead-cwd", "unreadable", "absent"],
    )
    def test_meta_tabs_fall_back_when_memory_is_broken_or_absent(self, exc, monkeypatch, tmp_path):
        """Through the public mint; the empty-tab fallback leaves the template's todos_meta line as is."""
        denier = self._deny("aipass.memory", exc)
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        try:
            result = core.spawn_agent(str(tmp_path / "newbie"), role="Test", purpose="meta-tab fallback")
        except (ImportError, OSError) as err:
            pytest.fail(f"a peer raising {type(exc).__name__} took spawn's mint down instead of falling back: {err}")

        assert result["success"] is True
        template_root = get_template_dir(get_available_classes()[0])
        assert self._todos_meta_line(tmp_path / "newbie") == self._todos_meta_line(template_root)

    def test_the_denier_actually_denies(self, monkeypatch):
        """Negative control: an inert finder would make the pins above vacuous."""
        denier = self._deny("aipass.memory", FileNotFoundError(2, "denied"))
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        with pytest.raises(FileNotFoundError):
            importlib.import_module("aipass.memory.apps.modules.door_tab_renderer")

    def test_a_real_programming_error_is_still_fatal(self, monkeypatch, tmp_path):
        """The width is OSError, not Exception — a broken peer must stay loud."""
        denier = self._deny("aipass.memory", ValueError("peer has a bug"))
        monkeypatch.setattr(sys, "meta_path", [denier] + sys.meta_path)
        for name in [m for m in sys.modules if m.startswith("aipass.memory")]:
            monkeypatch.delitem(sys.modules, name, raising=False)

        with pytest.raises(ValueError, match="peer has a bug"):
            core.spawn_agent(str(tmp_path / "newbie"), role="Test", purpose="meta-tab fatal")

        assert not (tmp_path / "newbie").exists(), "the lookup runs before the copy: nothing is minted"


def _inspect_stack_calls(source: str) -> list:
    """Line numbers of every ``inspect.stack()`` CALL in ``source``, under any of its three spellings.

    AST, never a string search: the guard's docstring names ``inspect.stack()`` to explain the cure."""
    tree = ast.parse(source)

    imports = [node for node in ast.walk(tree) if isinstance(node, ast.Import)]
    module_aliases = {"inspect"} | {a.asname or a.name for node in imports for a in node.names if a.name == "inspect"}
    from_inspect = [node for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module == "inspect"]
    direct_names = {a.asname or a.name for node in from_inspect for a in node.names if a.name == "stack"}

    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "stack"
            and isinstance(func.value, ast.Name)
            and func.value.id in module_aliases
        ):
            found.append(node.lineno)
        elif isinstance(func, ast.Name) and func.id in direct_names:
            found.append(node.lineno)

    return sorted(found)


# The template's dropbox and .archive are shipped content, so swept; apps/ holds real archives.
_SWEEP_SKIP_DIRS = frozenset({"__pycache__"})
_APPS_SKIP_DIRS = frozenset({"__pycache__", ".archive", "dropbox"})


def _swept_py_files(root: Path, skip: frozenset[str] = _SWEEP_SKIP_DIRS) -> list[Path]:
    """Every .py under root, in order, outside the directories skip names."""
    return [path for path in sorted(root.rglob("*.py")) if not skip.intersection(path.relative_to(root).parts)]


_BANNED_ROOTS = (
    (Path(__file__).resolve().parents[1] / "apps", _APPS_SKIP_DIRS),
    (get_template_dir("specialist"), _SWEEP_SKIP_DIRS),
)


# A floor, so a blinded walk cannot read as a clean tree.
_MIN_FILES_SWEPT = 40


class TestTheStackWalkCannotComeBack:
    """The deleted second walk has no behavioural instrument — so pin the source.

    Its branch is unreachable from any import-shaped test: restoring the walk leaves the suite green."""

    def test_the_guard_has_no_stack_walk(self):
        source = (Path(__file__).resolve().parents[1] / "apps" / "handlers" / "__init__.py").read_text(encoding="utf-8")

        assert _inspect_stack_calls(source) == [], (
            "inspect.stack() is back in the handler guard. It reads the cwd on "
            "Windows before any of the guard's own code runs — walk frames with "
            "sys._getframe instead"
        )

    def test_no_stack_walk_anywhere_in_apps_or_the_template(self):
        """Tree-wide, because zero legitimate callers remain — CHECKED, not assumed."""
        offenders = []
        swept = 0

        for root, skip in _BANNED_ROOTS:
            for path in _swept_py_files(root, skip):
                swept += 1
                offenders += [
                    f"{path.name}:{line}" for line in _inspect_stack_calls(_render(path.read_text(encoding="utf-8")))
                ]

        assert swept >= _MIN_FILES_SWEPT, (
            f"the sweep only reached {swept} files (expected at least "
            f"{_MIN_FILES_SWEPT}) — an empty result from a blinded walk is not "
            "evidence of a clean tree"
        )
        assert offenders == [], f"inspect.stack() at import-capable sites: {offenders}"

    def test_the_sweep_watches_the_template_dropbox_and_archive(self, tmp_path):
        """The template's dropbox and .archive are shipped content, swept; __pycache__ is not.

        The root sits under a dropbox, so a skip read on the whole path would hide everything."""
        root = tmp_path / "dropbox" / "citizen"
        for relative in ("kept.py", "dropbox/shipped.py", ".archive/shipped.py", "__pycache__/stale.py"):
            (root / relative).parent.mkdir(parents=True, exist_ok=True)
            (root / relative).write_text("import inspect\n", encoding="utf-8")

        assert _swept_py_files(root) == [
            root / ".archive" / "shipped.py",
            root / "dropbox" / "shipped.py",
            root / "kept.py",
        ]
        # apps/ holds real archives: its sweep skips them.
        assert _swept_py_files(root, _APPS_SKIP_DIRS) == [root / "kept.py"]


class TestTheStackMatcherIsTheRealOne:
    """Controls run through the SHIPPED matcher, never a copy of it.

    A control that exercises a second implementation proves that copy correct
    and says nothing about the pin above.
    """

    def test_a_planted_call_convicts_at_the_right_line(self):
        source = "import inspect\n\n\ndef f():\n    return inspect.stack()\n"

        assert _inspect_stack_calls(source) == [5]

    def test_prose_that_names_the_walk_is_not_a_violation(self):
        """The cure explains itself by naming the defect — that must stay legal.

        A stub, not the live guard: reading the live file would make this a second copy of the ban."""
        prose = "Replaces the inspect.stack() walk of the first guard (2026-04-25)."

        assert _inspect_stack_calls(f'def stub():\n    """{prose}"""\n') == []

    @pytest.mark.parametrize(
        "label,source,expected",
        [
            ("numpy.stack", "import numpy\nx = numpy.stack([1])\n", []),
            ("traceback.stack", "import traceback\nx = traceback.stack()\n", []),
            ("self.stack", "class C:\n    def f(self):\n        return self.stack()\n", []),
            ("bare reference, never called", "import inspect\nf = inspect.stack\n", []),
            ("inspect.currentframe is legal", "import inspect\nx = inspect.currentframe()\n", []),
            ("module alias", "import inspect as i\nx = i.stack()\n", [2]),
            ("direct import", "from inspect import stack\nx = stack()\n", [2]),
            ("direct import aliased", "from inspect import stack as s\nx = s()\n", [2]),
            ("a different from-import", "from inspect import currentframe\nx = currentframe()\n", []),
        ],
    )
    def test_the_matcher_tells_the_cases_apart(self, label, source, expected):
        assert _inspect_stack_calls(source) == expected, label


class TestNewbornsAreBornPinned:
    """The template ships the AST pin, and it works in the position it lands in.

    It ships in the self-contained test_scaffold.py (no conftest). Limit: ``spawn update`` never
    overwrites .py, so only future citizens get it. Run green AND red in its landing position."""

    @staticmethod
    def _mint(root: Path, guard_source: str) -> Path:
        branch = root / "newborn"
        (branch / "apps" / "handlers").mkdir(parents=True)
        (branch / "tests").mkdir()
        (branch / "apps" / "handlers" / "__init__.py").write_text(guard_source, encoding="utf-8")

        scaffold = get_template_dir("specialist") / "tests" / "test_scaffold.py"
        (branch / "tests" / "test_scaffold.py").write_text(
            _render(scaffold.read_text(encoding="utf-8")), encoding="utf-8"
        )
        return branch

    @staticmethod
    def _run_scaffold(branch: Path):
        return subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                str(branch / "tests" / "test_scaffold.py"),
                "-p",
                "no:randomly",
                "-q",
                "--no-header",
                "-k",
                "stack",
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            cwd=str(branch),
        )

    def test_a_newborn_with_the_cured_guard_passes_its_own_pin(self, tmp_path):
        cured = _render(_template_guard("specialist").read_text(encoding="utf-8"))
        branch = self._mint(tmp_path, cured)

        result = self._run_scaffold(branch)

        assert result.returncode == 0, f"a newborn fails the pin it is born with:\n{result.stdout}\n{result.stderr}"

    def test_a_newborn_that_regrows_the_walk_fails_its_own_pin(self, tmp_path):
        """The pin the newborn ships has to be able to convict, not just pass."""
        regressed = _render(_template_guard("specialist").read_text(encoding="utf-8")).replace(
            "    frame = sys._getframe(1)",
            "    import inspect\n\n    stack = inspect.stack()\n    frame = sys._getframe(1)",
        )
        assert "inspect.stack()" in regressed
        branch = self._mint(tmp_path, regressed)

        result = self._run_scaffold(branch)

        assert result.returncode != 0, (
            "a newborn that regrew the stack walk still passed its own pin — the "
            f"shipped pin cannot convict:\n{result.stdout}"
        )
        assert "handler guard" in result.stdout
