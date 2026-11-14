# =================== AIPass ====================
# Name: test_repo_root.py
# Description: Pins for handlers/repo_root.py - one repo-root answer, never the cwd
# Version: 1.3.0
# Created: 2026-08-31
# Modified: 2026-11-02
# =============================================

"""Tests for apps/handlers/repo_root.py."""

# Two species: BEHAVIOURAL pins hand the walk a registry-less world so the fallback
# runs on every machine; STRUCTURAL pins sweep the tree so no lane keeps a private copy.

# The declared pass — what is NOT tested here, and what covers it instead:

import importlib
import inspect
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

import aipass.memory.tests.test_residency_scope as residency
from aipass.memory.apps.handlers import repo_root as rr
from aipass.memory.tests import support_fence
from aipass.memory.apps.handlers.monitor import registry_scope
from aipass.memory.tests.dead_cwd import (
    ACCESSOR_SHAPE,
    DEAD_CWD_WORLD,
    DELETE_CWD_WORLD,
)

# Judged by the parts BELOW the walk's root: a checkout under a dir named dropbox must not hide itself.
_SKIPPED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _walk(root: Path, pattern: str = "*.py") -> list[Path]:
    """Every file under *root* matching *pattern*, outside the skipped directories."""
    return sorted(path for path in root.rglob(pattern) if not _SKIPPED_DIRS.intersection(path.relative_to(root).parts))


def test_the_walk_skips_dropbox_archive_and_caches_below_its_root_only(tmp_path: Path) -> None:
    """Red first against a bare rglob. The root stands inside a directory named dropbox; live/ is the control."""
    root = tmp_path / "dropbox" / "checkout"
    for name in (*sorted(_SKIPPED_DIRS), "live"):
        (root / name).mkdir(parents=True)
        (root / name / "test_x.py").write_text("", encoding="utf-8")
    assert _walk(root) == [root / "live" / "test_x.py"]


# The sweep reads the tree, never a hand-kept list (that is how the tenth copy hid).
_APPS = Path(rr.__file__).resolve().parent.parent
_SOURCES = _walk(_APPS)

# "Where was the caller standing" is a question ABOUT THE CALLER; cwd answers it.
_CALLER_CWD_SITES = {
    "detector.py",
    # rolls the todo pad of the branch the CALLER stands in (AIPASS_CALLER_CWD first).
    "todo_roll.py",
}


def _src_root() -> str:
    """The importable source root, for subprocesses that must not inherit sys.path."""
    return str(Path(rr.__file__).resolve().parents[5])


def _prose_lines(text: str) -> set[int]:
    """Line numbers occupied by string literals — docstrings included.

    A file may describe the bug it cured without being convicted of having it.
    """
    import ast

    covered: set[int] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.end_lineno:
            covered.update(range(node.lineno, node.end_lineno + 1))
    return covered


def _cwd_reads(text: str) -> list[int]:
    """Line numbers where ``Path.cwd()`` appears in CODE, not in prose or a comment."""
    prose = _prose_lines(text)
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if "Path.cwd()" in line and not line.lstrip().startswith("#") and number not in prose
    ]


class TestTheFallbackIsDerivedFromTheSourceTree:
    """A registry-less world resolves to where the CODE is, not where the caller is."""

    def test_a_registryless_walk_returns_the_source_root(self, tmp_path):
        """No AIPASS_REGISTRY.json above tmp_path, so the fallback is exercised."""
        assert rr.find_repo_root(tmp_path) == rr.SOURCE_ROOT

    def test_the_answer_does_not_depend_on_where_the_caller_stands(self, tmp_path, monkeypatch):
        """The QUIET defect: two callers in different directories got different roots."""
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        from_elsewhere = rr.find_repo_root(tmp_path)
        monkeypatch.chdir(tmp_path)
        assert rr.find_repo_root(tmp_path) == from_elsewhere

    def test_the_source_root_is_the_parent_of_src(self):
        """SOURCE_ROOT is the checkout, derived from the layout `src/` guarantees."""
        assert (rr.SOURCE_ROOT / "src").is_dir()

    def test_a_real_registry_above_the_start_wins(self, tmp_path):
        """The fallback is a last resort, not a shortcut past the walk."""
        (tmp_path / rr.CORE_REGISTRY).write_text("{}", encoding="utf-8")
        nested = tmp_path / "a" / "b"
        nested.mkdir(parents=True)
        assert rr.find_repo_root(nested) == tmp_path

    def test_the_marker_is_a_parameter_not_a_constant(self, tmp_path):
        """Callers that mark a root with a different file get the same walk."""
        (tmp_path / "OTHER_MARKER.json").write_text("{}", encoding="utf-8")
        nested = tmp_path / "a"
        nested.mkdir()
        assert rr.find_repo_root(nested, marker="OTHER_MARKER.json") == tmp_path

    def test_the_fallback_says_so_out_loud(self, tmp_path, caplog):
        """A fallback nobody can see is how the next one survives."""
        with caplog.at_level("WARNING"):
            rr.find_repo_root(tmp_path, caller="a_named_lane")
        assert any("a_named_lane" in record.message for record in caplog.records), (
            f"the fallback did not name its caller: {[r.message for r in caplog.records]}"
        )

    def test_a_successful_walk_is_silent(self, tmp_path, caplog):
        """Only the fallback is news. A found registry is the normal case."""
        (tmp_path / rr.CORE_REGISTRY).write_text("{}", encoding="utf-8")
        with caplog.at_level("WARNING"):
            rr.find_repo_root(tmp_path)
        assert not caplog.records, [r.message for r in caplog.records]


class TestTheAuditLineCanNeverTakeAnImportDown:
    """Four callers resolve at MODULE level, so this write happens during their import.

    ``_record_fallback`` imports json_handler at call time, so the patch lands on
    whatever ``sys.modules`` holds, not on a top-of-file binding the code never reads.
    """

    @staticmethod
    def _the_module_the_fallback_will_import():
        return sys.modules["aipass.memory.apps.handlers.json.json_handler"]

    def test_a_failing_log_operation_does_not_propagate(self, tmp_path, monkeypatch):
        """A diagnostic write must not become the crash it was diagnosing."""

        def explode(*_args, **_kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(self._the_module_the_fallback_will_import(), "log_operation", explode)
        assert rr.find_repo_root(tmp_path) == rr.SOURCE_ROOT

    def test_the_fallback_is_still_recorded_when_it_can_be(self, tmp_path, monkeypatch):
        """Defensive does not mean absent — the operation is logged on the happy path."""
        seen = []
        monkeypatch.setattr(
            self._the_module_the_fallback_will_import(), "log_operation", lambda *a, **k: seen.append((a, k))
        )
        rr.find_repo_root(tmp_path, caller="a_named_lane")
        assert seen, "the fallback was taken and nothing was recorded"
        assert seen[0][0][0] == "repo_root_fallback"


class TestNoLaneKeepsAPrivateCopyOfTheAnswer:
    """The sweep pin. This is the one that catches the eleventh copy."""

    def test_only_repo_root_implements_the_walk(self):
        """A second implementation is how the first cure missed nine files.

        Delegating wrappers are fine (tests patch the local name); a second BODY is not.
        """
        offenders = []
        for path in _SOURCES:
            if path == Path(rr.__file__).resolve():
                continue
            text = path.read_text(encoding="utf-8")
            for match in re.finditer(r"def _?find_repo_root\b[^\n]*\n((?:[ \t]+[^\n]*\n|\n)*)", text):
                body = match.group(1)
                if "repo_root.find_repo_root" not in body and "rr.find_repo_root" not in body:
                    offenders.append(path.relative_to(_APPS))
        assert offenders == [], (
            f"{len(offenders)} lane(s) implement the walk themselves instead of delegating: {offenders}"
        )

    def test_the_write_fence_stands_on_this_source_tree_not_the_callers_directory(self, tmp_path):
        """The fence's root is this module's answer. A cwd — even one holding a registry — never moves it."""
        elsewhere = tmp_path / "another_repo"
        elsewhere.mkdir()
        (elsewhere / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
        probe = (
            "import sys\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "from aipass.memory.apps.handlers import write_fence\n"
            "print(write_fence.ROOT)\n"
        )
        env = {**os.environ, "AIPASS_CALLER_CWD": str(elsewhere)}

        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", cwd=str(elsewhere), env=env
        )

        assert result.returncode == 0, result.stderr
        assert Path(result.stdout.strip().splitlines()[-1]) == rr.find_repo_root(caller="test")

    def test_no_lane_falls_back_to_the_process_directory(self):
        """`return Path.cwd()` is the exact construct that broke CI twice."""
        offenders = [
            str(path.relative_to(_APPS))
            for path in _SOURCES
            if re.search(r"^\s*return Path\.cwd\(\)", path.read_text(encoding="utf-8"), re.MULTILINE)
        ]
        assert offenders == [], f"process-directory fallback still present in: {offenders}"

    def test_the_only_remaining_cwd_reads_are_the_caller_cwd_species(self):
        """Not a ban on cwd — a ban on cwd standing in for "where does the code live".

        `AIPASS_CALLER_CWD` sites are named so a new one has to be argued for.
        String and comment lines are excluded via the parse tree.
        """
        offenders = []
        for path in _SOURCES:
            text = path.read_text(encoding="utf-8")
            lines = text.splitlines()
            for number in _cwd_reads(text):
                if "AIPASS_CALLER_CWD" in lines[number - 1]:
                    if path.name not in _CALLER_CWD_SITES:
                        offenders.append(f"{path.relative_to(_APPS)}:{number} (unlisted caller-cwd site)")
                    continue
                if path == Path(rr.__file__).resolve():
                    continue
                offenders.append(f"{path.relative_to(_APPS)}:{number}")
        assert offenders == [], f"unexplained Path.cwd() reads: {offenders}"


class TestTheSweepCanStillSee:
    """The positive control. A filter nothing checks can be silenced quietly."""

    _SAMPLE = (
        '"""A docstring that mentions Path.cwd() while explaining the defect."""\n'
        "\n"
        "# A comment mentioning Path.cwd() too.\n"
        "def offender():\n"
        "    return Path.cwd()\n"
    )

    def test_it_finds_the_construct_in_code(self):
        assert _cwd_reads(self._SAMPLE) == [5], (
            "the sweep cannot see a Path.cwd() sitting in plain code — it would pass over the real tree "
            "for the same reason"
        )

    def test_it_does_not_convict_prose_or_comments(self):
        assert 1 not in _cwd_reads(self._SAMPLE)
        assert 3 not in _cwd_reads(self._SAMPLE)


# Lanes that resolve their root while being IMPORTED: `import` is the crash site.
_IMPORT_TIME_LANES = [
    "aipass.memory.apps.handlers.monitor.detector",
    "aipass.memory.apps.handlers.monitor.registry_scope",
    "aipass.memory.apps.handlers.central_writer",
    "aipass.memory.apps.handlers.templates.trinity_push",
    "aipass.memory.apps.handlers.rollover.orchestrator",
]

# The condition pinned is "os.getcwd() raises", built by denying getcwd or deleting the cwd.
# TestBothConstructionsAgree proves the two equivalent.
_DENY_CWD = DEAD_CWD_WORLD

_DELETE_CWD = DELETE_CWD_WORLD


class TestEveryImportTimeLaneSurvivesADeadWorkingDirectory:
    """Importing must never raise, in any world. Subprocess, because cwd is process-wide."""

    _NOT_OURS = "/aipass/prax/"

    @pytest.mark.parametrize("world", [_DENY_CWD, _DELETE_CWD])
    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_importing_survives(self, module, world):
        probe = f"import os, sys\nsys.path.insert(0, {_src_root()!r})\n{world}import {module}\nprint('OK')\n"
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, (
            f"{module} could not be imported in a dead cwd. "
            + (
                "THE CRASH IS NOT IN THIS BRANCH — it is in @prax, which was cured on 2026-08-31 "
                "and has regressed. Route it there rather than editing memory.\n"
                if self._NOT_OURS in result.stderr
                else ""
            )
            + result.stderr
        )
        assert "OK" in result.stdout


class TestMemorysHalfIsCuredEvenWhereTheChainStillBreaks:
    """@prax's copy is neutralised in the child, so what remains is memory's tree alone."""

    @pytest.mark.parametrize("world", [_DENY_CWD, _DELETE_CWD])
    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_this_branch_imports_in_a_bare_world(self, module, world):
        probe = (
            # The world first, in the order it takes effect.
            f"{world}import sys, pathlib\nsys.path.insert(0, {_src_root()!r})\nimport {module}\nprint('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, (
            f"{module} could not be imported in a dead cwd with prax held constant — "
            f"this one IS memory's:\n{result.stderr}"
        )
        assert "OK" in result.stdout

    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_this_branch_imports_where_the_fallback_actually_runs(self, module):
        """Every registry is made invisible, so the fallback RUNS on any machine."""
        probe = (
            f"{_DENY_CWD}"
            "import sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "_real_exists = pathlib.Path.exists\n"
            "pathlib.Path.exists = lambda self, *a, **k: (\n"
            "    False if self.name.endswith('_REGISTRY.json') else _real_exists(self, *a, **k)\n"
            ")\n"
            f"import {module} as target\n"
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, (
            f"{module} took the fallback and died — this is the CI defect reproduced locally:\n{result.stderr}"
        )
        assert "OK" in result.stdout


class TestTheDeadCwdProbeIsAHonestInstrument:
    """The pins above prove nothing unless the world they build really is hostile."""

    _CHECK = (
        "import pathlib\n"
        "try:\n"
        "    pathlib.Path.cwd()\n"
        "    print('NO_RAISE')\n"
        "except FileNotFoundError:\n"
        "    print('RAISED')\n"
    )

    def test_denying_getcwd_makes_reading_the_cwd_raise(self):
        """The injected construction."""
        result = subprocess.run(
            [sys.executable, "-c", _DENY_CWD + self._CHECK], capture_output=True, text=True, encoding="utf-8"
        )
        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"

    def test_deleting_the_cwd_makes_reading_the_cwd_raise(self):
        """The real world."""
        result = subprocess.run(
            [sys.executable, "-c", _DELETE_CWD + self._CHECK], capture_output=True, text=True, encoding="utf-8"
        )
        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"


class TestBothConstructionsAgree:
    """What licenses using the injected world where the real one cannot be built.

    Both worlds are built and compared; if they stop agreeing, the pins that only deny
    getcwd rest on an expired claim.
    """

    _ASK = (
        "import sys, pathlib\n"
        f"sys.path.insert(0, {_src_root()!r})\n"
        "_real = pathlib.Path.exists\n"
        "pathlib.Path.exists = lambda self, *a, **k: (\n"
        "    False if self.name.endswith('_REGISTRY.json') else _real(self, *a, **k)\n"
        ")\n"
        "from aipass.memory.apps.handlers import repo_root\n"
        "print('ANSWER', repo_root.find_repo_root())\n"
    )

    @staticmethod
    def _run(world):
        """Ask the resolver the same question in *world* and report what came back."""
        return subprocess.run(
            [sys.executable, "-c", world + TestBothConstructionsAgree._ASK],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

    def test_the_two_worlds_produce_the_same_answer(self):
        denied, deleted = self._run(_DENY_CWD), self._run(_DELETE_CWD)
        assert denied.returncode == 0, denied.stderr
        assert deleted.returncode == 0, deleted.stderr
        assert denied.stdout.strip() == deleted.stdout.strip(), (
            f"the injected world and the real one disagree — the getcwd-denial pins rest on them "
            f"agreeing.\ndenied:  {denied.stdout!r}\ndeleted: {deleted.stdout!r}"
        )


class TestAFilenameIsNotAnExistsCall:
    """``exists_exactly`` — the half of the pair with no glob to warn a reader.

    A cased literal folds on a case-insensitive filesystem; a folded bait file accepted as THE
    REPO ROOT would hand every writer a tree nobody chose.
    """

    def test_the_injected_world_really_folds(self, tmp_path, case_insensitive_exists):
        """Positive control. A fold that does not fold makes every pin below vacuous."""
        (tmp_path / "aipass_registry.json").write_text("{}", encoding="utf-8")

        assert (tmp_path / "AIPASS_REGISTRY.json").exists(), "the emulation is not folding"

    def test_a_folded_name_is_not_the_name_that_was_asked_for(self, tmp_path, case_insensitive_exists):
        (tmp_path / "aipass_registry.json").write_text("{}", encoding="utf-8")

        assert rr.exists_exactly(tmp_path / "AIPASS_REGISTRY.json") is False

    def test_the_exact_name_still_answers_yes(self, tmp_path, case_insensitive_exists):
        """The guard must not refuse the file it exists to find."""
        (tmp_path / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

        assert rr.exists_exactly(tmp_path / "AIPASS_REGISTRY.json") is True

    def test_absent_is_absent_without_listing_anything(self, tmp_path):
        assert rr.exists_exactly(tmp_path / "AIPASS_REGISTRY.json") is False

    def test_an_unlistable_parent_trusts_exists_rather_than_inventing_a_refusal(self, tmp_path, monkeypatch):
        """An unlistable parent trusts exists(): refusing a file that is there is a new failure."""
        target = tmp_path / "AIPASS_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")

        denied = []

        def _denied(directory):
            denied.append(directory)
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(rr.os, "scandir", _denied)

        assert rr.exists_exactly(target) is True
        assert denied == [tmp_path]

    def test_the_repo_root_walk_does_not_anchor_on_a_folded_bait_file(self, tmp_path, case_insensitive_exists):
        """A lowercase ``aipass_registry.json`` is never answered as the repo root."""
        bait = tmp_path / "someone_elses_repo"
        (bait / "deep").mkdir(parents=True)
        (bait / "aipass_registry.json").write_text("{}", encoding="utf-8")

        found = rr.find_repo_root(bait / "deep", caller="test")

        assert found != bait
        assert found == rr.SOURCE_ROOT, "the fallback is the source tree, never a folded guess"

    def test_the_walk_still_finds_a_correctly_spelled_marker(self, tmp_path, case_insensitive_exists):
        """The positive half: the guard must not blind the walk it protects."""
        real = tmp_path / "a_real_repo"
        (real / "deep").mkdir(parents=True)
        (real / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

        assert rr.find_repo_root(real / "deep", caller="test") == real


class TestTheFilterHasOneImplementationForFourWalks:
    """``exactly_named`` moved here the day the third and fourth walks turned up.

    Four walks import this module; a body in each would be four answers.
    """

    def test_registry_scope_delegates_rather_than_carrying_a_twin(self):
        # The module's text, sliced to the helper: the claim is about its source, not a call into it.
        source = inspect.getsource(registry_scope).split("def _exactly_named(", 1)[1].split("\ndef ", 1)[0]

        assert "repo_root.exactly_named" in source, "the ten-copy lesson, one package over"
        assert "endswith" not in source.split('"""')[-1], "a second implementation is a second answer"

    @pytest.mark.parametrize(
        ("module_name", "sites"),
        [
            ("aipass.memory.apps.handlers.monitor.detector", 1),
            # Zero: the watcher reads the rollover scope; a glob here is a second walk.
            ("aipass.memory.apps.handlers.monitor.memory_watcher", 0),
            ("aipass.memory.apps.handlers.monitor.registry_scope", 2),
        ],
    )
    def test_no_registry_glob_in_this_tree_is_left_unfiltered(self, module_name, sites):
        """The structural pin: catch it where it is WRITTEN, not only where it runs.

        The per-module count floors the loop, so a site the matcher cannot see is red, not silent.
        """
        source = inspect.getsource(importlib.import_module(module_name))

        globbed = [
            (number, line)
            for number, line in enumerate(source.splitlines(), start=1)
            if "glob(" in line and ("_REGISTRY.json" in line or "REGISTRY_GLOB" in line)
        ]
        assert len(globbed) == sites, (
            f"{module_name}: expected {sites} registry-glob site(s), read {len(globbed)} — "
            "a site moved, was added, or slipped past the matcher"
        )
        for number, line in globbed:
            assert "exactly_named(" in line, f"{module_name}:{number} globs registries with no exact-case filter"


class TestTheDeniedWorldSurvivesEveryWayPathlibCallsIt:
    """The 3.10 red, reproduced on whatever interpreter is running this.

    ``_NormalAccessor.getcwd = os.getcwd`` stores a function on a class, so it arrives
    BOUND; ``ACCESSOR_SHAPE`` reproduces that on any version.
    """

    _ASK = (
        "try:\n"
        "    _accessor.getcwd()\n"
        "    print('NO_RAISE')\n"
        "except FileNotFoundError:\n"
        "    print('RAISED')\n"
        "except TypeError as exc:\n"
        "    print('TYPEERROR', exc)\n"
    )

    def test_the_denial_answers_when_pathlib_calls_it_as_a_bound_method(self):
        """Red on this laptop with the old ``lambda:`` spelling. That is the point."""
        result = subprocess.run(
            [sys.executable, "-c", _DENY_CWD + ACCESSOR_SHAPE + self._ASK],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"

    def test_the_world_patches_an_accessor_that_already_captured_the_real_getcwd(self):
        """The defect CI could NOT see, and the more dangerous of the two.

        On 3.10 the accessor captures ``os.getcwd`` at pathlib import, so a denial installed
        later never reaches it. The accessor is BUILT here so the pin bites on 3.11+ too.
        """
        pre_captured = (
            "import os, pathlib\n"
            "class _NormalAccessor:\n"
            "    getcwd = os.getcwd\n"
            "pathlib._NormalAccessor = _NormalAccessor\n"
            "_accessor = _NormalAccessor()\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", pre_captured + _DENY_CWD + self._ASK],
            capture_output=True,
            text=True,
            encoding="utf-8",
        )

        assert "RAISED" in result.stdout, f"the world never reached the accessor: {result.stdout}{result.stderr}"

    def test_the_world_is_defined_once_for_the_whole_branch(self):
        """Two files carried two spellings of one world, and both were wrong."""
        assert residency.DEAD_CWD_WORLD is DEAD_CWD_WORLD
        # Assembled: a literal needle would convict this file.
        retyped = "getcwd" + " = " + "lambda"
        for module in (residency, sys.modules[__name__]):
            source = inspect.getsource(module)
            assert retyped not in source, f"{module.__name__} retyped the world instead of importing it"


class TestTheFenceStillJudgesInADeadWorkingDirectory:
    """The old guard's dead-cwd pins, on the fence's public shape.

    With ``os.getcwd()`` raising, the fence neither dies nor waves a caller through.
    ``<string>`` and runpy are transport; the probe's own file decides.
    """

    @staticmethod
    def _run(seat: Path, shape: str) -> str:
        """Run the fence probe at *seat* in a dead-cwd child; answer its one output line."""
        probe = (
            f"{_DENY_CWD}"
            "import runpy, sys\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            f"sys.argv = [{str(seat)!r}, {shape!r}]\n"
            f"runpy.run_path({str(seat)!r}, run_name='__main__')\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8", timeout=120
        )
        assert result.returncode == 0, result.stderr[-600:]
        return result.stdout.strip().splitlines()[-1]

    def test_the_cwd_is_dead_in_the_child(self):
        """Arming probe: the world bites, so the verdicts below were reached in it."""
        probe = (
            f"{_DENY_CWD}import os\ntry:\n    os.getcwd()\n    print('INERT')\nexcept OSError:\n    print('ARMED')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        assert "ARMED" in result.stdout, result.stdout

    def test_kin_is_allowed_with_the_cwd_dead(self):
        assert self._run(Path(support_fence.__file__), "pkg") == "ALLOWED"

    def test_an_elsewhere_caller_is_refused_with_the_cwd_dead(self, tmp_path):
        seat = tmp_path / "elsewhere" / "probe.py"
        seat.parent.mkdir(parents=True)
        shutil.copy(support_fence.__file__, seat)
        assert self._run(seat, "pkg") == "DENIED Caller branch: unknown"
