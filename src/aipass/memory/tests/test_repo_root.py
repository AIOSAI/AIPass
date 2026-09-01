"""Pins for ``handlers/repo_root.py`` — one repo-root answer, never the cwd.

WHY A WHOLE MODULE FOR ONE FUNCTION
-----------------------------------
@drone reported the ``Path.cwd()`` fallback in ``registry_scope`` and it was
cured the same hour. CI went red again within that hour on ``detector.py``:
byte-identical function, one file over, one of TEN copies. The subprocess pin
written for the first fix is what caught it — but only because CI runs a bare
checkout where the fallback is actually reached. On a developer machine the
walk finds the live registry and the defect is invisible.

So the pins here come in two species, deliberately:

  * BEHAVIOURAL — what the function does when the fallback IS taken. These run
    everywhere, because they hand the walk a directory with no registry above
    it rather than waiting for the machine to be bare.
  * STRUCTURAL — that no lane keeps a private copy of the answer. This is the
    pin that would have caught ``detector.py`` before CI did, and it is the
    only one that makes a third round impossible. A test that can only fail in
    an environment we do not run locally is not a guard, it is a report.
"""

import importlib
import inspect
import re
import subprocess
import sys
from pathlib import Path

import pytest

from aipass.memory.apps.handlers import repo_root as rr
from aipass.memory.tests.dead_cwd import (
    ACCESSOR_SHAPE,
    DEAD_CWD_WORLD,
    DELETE_CWD_WORLD,
    REALPATH_DENIED_WORLD,
    WINDOWS_EMULATED_WORLD,
    WINDOWS_REALPATH_WORLD,
)

# Every .py in the branch's own source, minus archives (kept deliberately as
# written) and caches. The sweep must read the tree, not a list someone
# maintains by hand — a hand-maintained list is how the tenth copy hid.
_APPS = Path(rr.__file__).resolve().parent.parent
_SOURCES = sorted(
    path for path in _APPS.rglob("*.py") if ".archive" not in path.parts and "__pycache__" not in path.parts
)

# The one other species of cwd read in this tree, and it is not this defect:
# "where was the caller standing" is a QUESTION ABOUT THE CALLER, and cwd is
# the right answer to it. Named here so the sweep refuses everything else.
_CALLER_CWD_SITES = {
    "detector.py",
    "memory_watcher.py",
}


def _src_root() -> str:
    """The importable source root, for subprocesses that must not inherit sys.path."""
    return str(Path(rr.__file__).resolve().parents[5])


def _prose_lines(text: str) -> set[int]:
    """Line numbers occupied by string literals — docstrings included.

    The sweeps below convict a file for CONTAINING a construct, and every
    docstring that explains this defect has to spell it. Reading the parse tree
    rather than guessing at quote characters means a file can describe the bug
    it cured without being convicted of having it.
    """
    import ast

    covered: set[int] = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and node.end_lineno:
            covered.update(range(node.lineno, node.end_lineno + 1))
    return covered


def _cwd_reads(text: str) -> list[int]:
    """Line numbers where ``Path.cwd()`` appears in CODE, not in prose or a comment.

    Extracted so it can be measured against a known sample. A filter is an
    instrument, and an instrument nothing checks can be silenced without
    anything going red — a mutation that made ``_prose_lines`` return every
    line left the whole sweep vacuous and the suite green.
    """
    prose = _prose_lines(text)
    return [
        number
        for number, line in enumerate(text.splitlines(), start=1)
        if "Path.cwd()" in line and not line.lstrip().startswith("#") and number not in prose
    ]


# ---------------------------------------------------------------------------
# BEHAVIOURAL — what the fallback resolves to
# ---------------------------------------------------------------------------


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

    ``repo_root`` imports ``json_handler`` INSIDE ``_record_fallback`` — a
    module-level edge would be a cycle now that ``json_handler`` imports
    ``module_file`` from here — so the patch has to land on the object that
    function-local import will actually find. That is whatever ``sys.modules``
    holds at call time, which under this suite's infrastructure mock is not the
    module a plain ``from ... import json_handler`` at the top of this file
    binds. Patching a name the code under test never reads is the quietest way
    to write a test that cannot fail.
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


# ---------------------------------------------------------------------------
# STRUCTURAL — no lane keeps a private copy
# ---------------------------------------------------------------------------


class TestNoLaneKeepsAPrivateCopyOfTheAnswer:
    """The sweep pin. This is the one that catches the eleventh copy."""

    def test_only_repo_root_implements_the_walk(self):
        """A second implementation is how the first cure missed nine files.

        Delegating wrappers are fine and expected — several lanes keep a local
        ``_find_repo_root`` name because tests patch it. What is refused is a
        second BODY: a wrapper is one line that calls this module.
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
        assert not offenders, (
            f"{len(offenders)} lane(s) implement the walk themselves instead of delegating: {offenders}"
        )

    def test_no_lane_falls_back_to_the_process_directory(self):
        """`return Path.cwd()` is the exact construct that broke CI twice."""
        offenders = [
            str(path.relative_to(_APPS))
            for path in _SOURCES
            if re.search(r"^\s*return Path\.cwd\(\)", path.read_text(encoding="utf-8"), re.MULTILINE)
        ]
        assert not offenders, f"process-directory fallback still present in: {offenders}"

    def test_the_only_remaining_cwd_reads_are_the_caller_cwd_species(self):
        """Not a ban on cwd — a ban on cwd standing in for "where does the code live".

        `AIPASS_CALLER_CWD` reads are a question ABOUT THE CALLER, and cwd is
        the correct answer to that question. They are named, so a new one has
        to be argued for rather than blend in.

        PROSE IS NOT CODE. The docstrings that explain this defect necessarily
        SPELL it, and a sweep that convicts a file for describing the bug it
        fixed would be uncurable — the only way to pass would be to stop
        explaining. String and comment lines are excluded structurally, via the
        parse tree, not by guessing at quote characters.
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
        assert not offenders, f"unexplained Path.cwd() reads: {offenders}"


class TestTheSweepCanStillSee:
    """The positive control. A filter nothing checks can be silenced quietly.

    A mutation that made ``_prose_lines`` cover every line left the sweep above
    unable to flag anything and the whole suite green — the instrument reported
    its own blindness as a clean bill of health. Same species as a guard fixture
    that skips: the assertion existed and could no longer fail.
    """

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


# ---------------------------------------------------------------------------
# IMPORT-TIME — the crash species
# ---------------------------------------------------------------------------

# The four lanes that resolve their root while being IMPORTED. For these the
# defect needs no call: `import` is the crash site, which is why the CI
# traceback ran through handlers/__init__ and never reached a test body.
_IMPORT_TIME_LANES = [
    "aipass.memory.apps.handlers.monitor.detector",
    "aipass.memory.apps.handlers.monitor.registry_scope",
    "aipass.memory.apps.handlers.central_writer",
    "aipass.memory.apps.handlers.templates.trinity_push",
    "aipass.memory.apps.handlers.rollover.orchestrator",
]

# --- BUILDING THE WORLD, TWICE, BECAUSE ONE WAY DOES NOT EXIST EVERYWHERE ----
#
# The original recipe deletes the process's working directory. That is a REAL
# world on POSIX and an IMPOSSIBLE one on Windows: Windows holds a lock on the
# directory a process is standing in, so the rmdir raises PermissionError
# (WinError 32) and every pin built this way dies at SETUP rather than at its
# claim — which is how these arrived on the Windows CI leg.
#
# The condition being pinned is NOT "a directory was deleted". It is
# "``os.getcwd()`` raises", which is what ``Path.cwd()`` does underneath and the
# only thing this code can actually observe. Deleting the directory is one way
# to cause it; a disconnected network share or an ejected volume is another, and
# those DO happen on Windows. So the primary construction denies ``getcwd``
# directly — the failure itself rather than one cause of it — and runs on every
# platform.
#
# Injecting it is not faking the world, on the same reasoning that lets the
# marker be denied in-process: the interpreter raises the real exception from
# the real call site. And the claim does not rest on that argument alone —
# ``TestBothConstructionsAgree`` runs BOTH recipes on POSIX and asserts they
# produce the same outcome, which is what licenses using the injected one where
# the real one cannot be built.
_DENY_CWD = DEAD_CWD_WORLD

_DELETE_CWD = DELETE_CWD_WORLD

_WINDOWS_CANNOT_DELETE_ITS_OWN_CWD = pytest.mark.skipif(
    sys.platform == "win32",
    reason=(
        "Windows locks a process's working directory, so it cannot be deleted from inside — "
        "this WORLD cannot be built here by this construction (PermissionError WinError 32 at "
        "the rmdir, before the pin's own claim is ever reached). The same defect is pinned on "
        "every platform by the getcwd-denial construction, and the two are proved equivalent "
        "on POSIX by TestBothConstructionsAgree."
    ),
)


class TestEveryImportTimeLaneSurvivesADeadWorkingDirectory:
    """Importing must never raise, in any world. Subprocess, because cwd is process-wide.

    Once the working directory is gone, EVERY ``Path.cwd()`` in the interpreter
    raises — pytest's own included. Deleting the runner's cwd would take the
    suite down with it, so the condition is created in a child.

    THE PIN JUDGES ONLY THIS BRANCH, and that distinction is the whole point of
    running it. On a bare tree the import chain reaches @prax before it reaches
    us: every handler in the fleet does ``logger = get_system_logger()`` at
    module level, and prax's own ``config/load.py`` carries this exact species
    — a repo-root walk whose last resort is ``Path.cwd()``. So a raw "did the
    import survive" assertion measures two branches at once and reports prax's
    line as memory's defect.

    THE BLOCKER IS CLEARED, AND SO THE ESCAPE HATCH IS GONE (2026-08-31, later
    the same night). @prax swept eight sites of the same species and their fix
    landed, so this reports a HARD failure again — verified here by rebuilding
    the bare stand-in against their tree: 11/11 memory modules import clean in a
    dead cwd with no substitution at all.

    An xfail that outlives its blocker is worse than no pin, because a
    regression upstream would go on reporting itself as an expected failure.
    What survives is the ATTRIBUTION: a crash outside this branch still fails,
    and it fails naming the tree it happened in, because convicting ourselves of
    somebody else's line is how a real defect gets fixed in the wrong place.
    """

    _NOT_OURS = "/aipass/prax/"

    @pytest.mark.parametrize("world", [_DENY_CWD, pytest.param(_DELETE_CWD, marks=_WINDOWS_CANNOT_DELETE_ITS_OWN_CWD)])
    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_importing_survives(self, module, world):
        probe = f"import os, sys\nsys.path.insert(0, {_src_root()!r})\n{world}import {module}\nprint('OK')\n"
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
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
    """The measurement that isolates this branch from the fleet's shared logger.

    The class above cannot prove memory is cured on a bare tree, because prax
    raises first and an xfail proves nothing about us. Here prax's copy is
    neutralised in the child — replaced, not caught — so what remains is
    memory's tree alone. If any of these go red the defect IS ours.

    Neutralising rather than skipping matters: a skip when the world is
    inconvenient is how a guard quietly stops guarding. This still runs, it
    still asserts, and it names exactly what it held constant.
    """

    @pytest.mark.parametrize("world", [_DENY_CWD, pytest.param(_DELETE_CWD, marks=_WINDOWS_CANNOT_DELETE_ITS_OWN_CWD)])
    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_this_branch_imports_in_a_bare_world(self, module, world):
        probe = (
            # The world FIRST. It no longer has to be — DEAD_CWD_WORLD patches
            # the 3.10 accessor too, so import order stops deciding whether the
            # world is hostile — but a probe that reads in the order it takes
            # effect cannot quietly regrow the dependency.
            f"{world}"
            "import sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "import aipass.prax.apps.handlers.config.load as prax_load\n"
            f"prax_load._find_repo_root = lambda: pathlib.Path({str(rr.SOURCE_ROOT)!r})\n"
            f"import {module}\n"
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"{module} could not be imported in a dead cwd with prax held constant — "
            f"this one IS memory's:\n{result.stderr}"
        )
        assert "OK" in result.stdout

    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_this_branch_imports_where_the_fallback_actually_runs(self, module):
        """@drone's technique, adopted: make the world hostile instead of waiting for it.

        The pins above cannot reach the fallback on a developer machine — a real
        registry sits above these files, the walk succeeds, and the branch that
        broke CI twice is never executed. @drone hit the mirror of this the same
        night (a sweep asserting "the checkout is a project root", true here and
        false on a bare runner, red within two hours) and their cure is better
        than my caveat: deny the marker in-process so the fallback leg RUNS,
        on any machine, bare or not.

        So the registry is made invisible before the import. With the cure in
        place these pass; with ``Path.cwd()`` restored they raise
        ``FileNotFoundError`` right here, on this laptop, with no CI required.
        That is the difference between a pin with teeth and a pin that files a
        report from an environment we do not run.
        """
        probe = (
            f"{_DENY_CWD}"
            "import sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "import aipass.prax.apps.handlers.config.load as prax_load\n"
            f"prax_load._find_repo_root = lambda: pathlib.Path({str(rr.SOURCE_ROOT)!r})\n"
            # every registry on this machine becomes invisible, so the walk in
            # every lane runs off the end and the fallback is what answers
            "_real_exists = pathlib.Path.exists\n"
            "pathlib.Path.exists = lambda self, *a, **k: (\n"
            "    False if self.name.endswith('_REGISTRY.json') else _real_exists(self, *a, **k)\n"
            ")\n"
            f"import {module} as target\n"
            "print('OK')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, (
            f"{module} took the fallback and died — this is the CI defect reproduced locally:\n{result.stderr}"
        )
        assert "OK" in result.stdout


class TestTheDeadCwdProbeIsAHonestInstrument:
    """The pins above prove nothing unless the world they build really is hostile.

    Both constructions get a positive control, because the whole argument for
    using the injected one on Windows is that it produces the SAME condition —
    and an unchecked instrument is what let a blinded filter report a vacuous
    sweep as green earlier tonight.
    """

    _CHECK = (
        "import pathlib\n"
        "try:\n"
        "    pathlib.Path.cwd()\n"
        "    print('NO_RAISE')\n"
        "except FileNotFoundError:\n"
        "    print('RAISED')\n"
    )

    def test_denying_getcwd_makes_reading_the_cwd_raise(self):
        """The portable construction. Runs on Windows, where the other cannot."""
        result = subprocess.run([sys.executable, "-c", _DENY_CWD + self._CHECK], capture_output=True, text=True)
        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"

    @_WINDOWS_CANNOT_DELETE_ITS_OWN_CWD
    def test_deleting_the_cwd_makes_reading_the_cwd_raise(self):
        """The real world, where the platform allows it to be built."""
        result = subprocess.run([sys.executable, "-c", _DELETE_CWD + self._CHECK], capture_output=True, text=True)
        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"


class TestBothConstructionsAgree:
    """What licenses using the injected world where the real one cannot be built.

    Windows locks a process's working directory, so ``_DELETE_CWD`` cannot run
    there at all — it raises PermissionError at the rmdir, before any claim is
    reached. That is not a reason to stop pinning the defect on Windows; it is a
    reason to pin the CONDITION (``os.getcwd()`` raises) rather than one cause
    of it.

    But "these two are equivalent" is an argument, and arguments belong in
    tests. On POSIX both worlds can be built, so both are built and compared —
    against the cured code AND against the defect restored. If they ever stop
    agreeing, the Windows coverage is resting on a claim that has expired.
    """

    _ASK = (
        "import sys, pathlib\n"
        f"sys.path.insert(0, {_src_root()!r})\n"
        "_real = pathlib.Path.exists\n"
        "pathlib.Path.exists = lambda self, *a, **k: (\n"
        "    False if self.name.endswith('_REGISTRY.json') else _real(self, *a, **k)\n"
        ")\n"
        "import aipass.prax.apps.handlers.config.load as prax_load\n"
        "prax_load._find_repo_root = lambda: pathlib.Path(__file__ if False else '/')\n"
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
        )

    @_WINDOWS_CANNOT_DELETE_ITS_OWN_CWD
    def test_the_two_worlds_produce_the_same_answer(self):
        denied, deleted = self._run(_DENY_CWD), self._run(_DELETE_CWD)
        assert denied.returncode == 0, denied.stderr
        assert deleted.returncode == 0, deleted.stderr
        assert denied.stdout.strip() == deleted.stdout.strip(), (
            f"the injected world and the real one disagree — the Windows coverage rests on them "
            f"agreeing.\ndenied:  {denied.stdout!r}\ndeleted: {deleted.stdout!r}"
        )


class TestAFilenameIsNotAnExistsCall:
    """``exists_exactly`` — the half of the pair with no glob to warn a reader.

    @seedgo published it as their own discriminator's blind spot on 2026-08-31:
    a cased LITERAL folds too, so ``(dir / "AIPASS_REGISTRY.json").exists()``
    returns True for a file actually named ``aipass_registry.json`` on Windows
    and on a macOS default volume.

    It lives here rather than at each caller because ``find_repo_root`` IS such
    a check, run at module level in four modules. A folded bait file accepted as
    THE REPO ROOT hands every writer downstream a tree nobody chose — which is
    the quiet defect this module was built to end, arriving through a door it
    did not cover.
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
        """The documented fallback, pinned so it is a decision and not an accident.

        This is a READ anchor and today's behaviour is ``exists()`` alone.
        Refusing a file that is demonstrably there because its directory could
        not be enumerated would be a new failure invented by the guard.
        """
        target = tmp_path / "AIPASS_REGISTRY.json"
        target.write_text("{}", encoding="utf-8")

        def _denied(*args, **kwargs):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(rr.os, "scandir", _denied)

        assert rr.exists_exactly(target) is True

    def test_the_repo_root_walk_does_not_anchor_on_a_folded_bait_file(self, tmp_path, case_insensitive_exists):
        """The whole reason this guard is in THIS module.

        A directory carrying a lowercase ``aipass_registry.json`` must not be
        answered as the repo root. Every writer in this tree resolves through
        here, and a guessed root is a write into somebody else's directory.
        """
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

    It was written in ``registry_scope`` for that module's two globs, with a
    docstring claiming a third walk could not be written without it. @drone's
    sweep and @seedgo's fleet discriminator then named two more in this tree —
    ``detector`` and ``memory_watcher`` — both written years before the filter
    existed. The claim was true about the future and said nothing about the
    past, so the body moved to the module all four already import.
    """

    def test_registry_scope_delegates_rather_than_carrying_a_twin(self):
        from aipass.memory.apps.handlers.monitor import registry_scope

        source = inspect.getsource(registry_scope._exactly_named)

        assert "repo_root.exactly_named" in source, "the ten-copy lesson, one package over"
        assert "endswith" not in source.split('"""')[-1], "a second implementation is a second answer"

    @pytest.mark.parametrize(
        "module_name",
        [
            "aipass.memory.apps.handlers.monitor.detector",
            "aipass.memory.apps.handlers.monitor.memory_watcher",
            "aipass.memory.apps.handlers.monitor.registry_scope",
        ],
    )
    def test_no_registry_glob_in_this_tree_is_left_unfiltered(self, module_name):
        """The structural pin: catch it where it is WRITTEN, not only where it runs.

        Last night's lesson cost a second CI red — a cure that landed on one of
        N identical sites while the rest kept the disease. This reads the source
        rather than the behaviour, so a fifth walk added tomorrow is red on the
        line it is typed on.
        """
        source = inspect.getsource(importlib.import_module(module_name))

        for number, line in enumerate(source.splitlines(), start=1):
            if "glob(" not in line or "_REGISTRY.json" not in line:
                continue
            assert "exactly_named(" in line, f"{module_name}:{number} globs registries with no exact-case filter"


class TestTheDeniedWorldSurvivesEveryWayPathlibCallsIt:
    """The 3.10 red, reproduced on whatever interpreter is running this.

    CI found it and none of us runs 3.10 locally, so the honest question was
    whether this could be pinned here at all or only reported. It can: the
    mechanism is plain Python, not a 3.10 feature. ``_NormalAccessor.getcwd =
    os.getcwd`` stores a FUNCTION on a class, and a function reached through an
    instance is a bound method on every version — so ``Path.cwd()`` handed the
    accessor as ``self`` to a zero-argument lambda and got ``TypeError`` where
    the pin expected ``FileNotFoundError``.

    ``ACCESSOR_SHAPE`` is those three lines and nothing else. Running the world
    against it here is the same move as denying ``getcwd`` instead of deleting a
    directory: pin the CONDITION (the call arrives bound) rather than the cause
    (an interpreter that binds it).
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
            [sys.executable, "-c", _DENY_CWD + ACCESSOR_SHAPE + self._ASK], capture_output=True, text=True
        )

        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"

    def test_the_world_patches_an_accessor_that_already_captured_the_real_getcwd(self):
        """The defect CI could NOT see, and the more dangerous of the two.

        On 3.10 the accessor captures ``os.getcwd`` when ``pathlib`` is first
        imported, so a probe importing pathlib BEFORE installing the denial gets
        an accessor holding the REAL function — a world that is not hostile at
        all. Four of this branch's probes were written that way. On 3.10 they
        were passing while asserting nothing, and nothing in the output tells a
        vacuous pin apart from a cured defect.

        A first draft of this pin just reordered the imports and asserted the
        world still bit. It SURVIVED the mutant that removes the accessor patch,
        because on 3.11+ there is no accessor and order genuinely does not
        matter — a green light wired to nothing, in the test written to stop
        exactly that. So the accessor is BUILT here, having captured the real
        ``os.getcwd`` first, which is 3.10's situation reproduced rather than
        described.
        """
        pre_captured = (
            "import os, pathlib\n"
            "class _NormalAccessor:\n"
            "    getcwd = os.getcwd\n"
            "pathlib._NormalAccessor = _NormalAccessor\n"
            "_accessor = _NormalAccessor()\n"
        )

        result = subprocess.run(
            [sys.executable, "-c", pre_captured + _DENY_CWD + self._ASK], capture_output=True, text=True
        )

        assert "RAISED" in result.stdout, f"the world never reached the accessor: {result.stdout}{result.stderr}"

    def test_the_world_is_defined_once_for_the_whole_branch(self):
        """Two files carried two spellings of one world, and both were wrong.

        The version bug was in both copies; only one of them was on the line CI
        happened to run first. A world with two implementations is two worlds,
        and the cheapest place to notice that is here.
        """
        import aipass.memory.tests.test_residency_scope as residency

        assert residency.DEAD_CWD_WORLD is DEAD_CWD_WORLD
        # Assembled rather than written out: a literal needle in the assertion
        # makes this file its own first offender, which the first run proved by
        # convicting this very line.
        retyped = "getcwd" + " = " + "lambda"
        for module in (residency, sys.modules[__name__]):
            source = inspect.getsource(module)
            assert retyped not in source, f"{module.__name__} retyped the world instead of importing it"


# Was a local copy, and the copy is what went red on Python 3.10: it patched
# ``os.path.realpath`` without patching the accessor 3.10's pathlib had already
# captured it into, so the probe below printed NO_RAISE and every pin under it
# was vacuous on that interpreter. The cure lives in ``dead_cwd.py`` beside the
# getcwd world that already carried it — which is where this constant should
# have been all along, since living apart from that docstring is how it came to
# repeat the exact trap the docstring describes.
_WINDOWS_REALPATH = WINDOWS_REALPATH_WORLD


class TestResolvingOwnFileIsACwdReadOnWindows:
    """The Windows CI reds, and they were NOT the world being unbuildable.

    @devpulse's steer offered two honest outcomes — a guard in the code if the
    frame is mine, or the deletion-recipe treatment if it is not. The frame was
    mine, and then thirty-one more were.

    THE MECHANISM. ``ntpath.realpath`` computes ``os.getcwd()``
    UNCONDITIONALLY — not only for a relative path, the way ``posixpath`` does —
    and ``Path.resolve()`` goes through it. So on Windows every
    ``Path(__file__).resolve()`` is a working-directory read, and this branch
    had thirty-two of them running at import time. CI showed the first
    (``inspect.stack()`` in the handlers guard, which resolves every frame's
    source file); behind it the traceback simply moved down.

    So the condition to inject is "resolving a path reads the cwd", which is a
    property of the STDLIB on that platform and reproducible here in six lines.
    Pinning "we are on Windows" would have pinned nothing runnable.

    WHAT THIS CLASS DOES NOT CLAIM. It holds the OTHER branches' copy of the
    template-born guard constant, because ``prax/apps/handlers/__init__.py``
    carries the identical ``inspect.stack()`` defect and would crash first. That
    is memory's half proved, and the fleet's half named rather than assumed —
    routed to @spawn, who owns the template all eighteen copies came from.
    """

    _HOLD_OTHER_BRANCHES = (
        "import aipass.prax.apps.handlers as _prax_handlers\n"
        "_prax_handlers._find_real_caller = lambda: (None, None)\n"
        "import aipass.prax.apps.handlers.config.load as _prax_load\n"
        f"_prax_load._find_repo_root = lambda: pathlib.Path({str(rr.SOURCE_ROOT)!r})\n"
    )

    def _probe(self, module):
        return (
            "import sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            + self._HOLD_OTHER_BRANCHES
            + _WINDOWS_REALPATH
            + _DENY_CWD
            + f"import {module}\n"
            "print('OK')\n"
        )

    def test_the_injected_world_really_reads_the_cwd(self):
        """Positive control: prove ``resolve()`` bites before trusting the pins."""
        probe = (
            "import pathlib\n" + _WINDOWS_REALPATH + _DENY_CWD + "try:\n"
            "    pathlib.Path(__file__ if '__file__' in dir() else '/tmp').resolve()\n"
            "    print('NO_RAISE')\n"
            "except FileNotFoundError:\n"
            "    print('RAISED')\n"
        )
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)

        assert "RAISED" in result.stdout, f"{result.stdout}{result.stderr}"

    @pytest.mark.parametrize("module", _IMPORT_TIME_LANES)
    def test_this_branch_imports_where_resolving_a_path_reads_the_cwd(self, module):
        result = subprocess.run([sys.executable, "-c", self._probe(module)], capture_output=True, text=True)

        assert result.returncode == 0, (
            f"{module} died where Path.resolve() reads the cwd — this is the Windows CI red "
            f"reproduced on POSIX:\n{result.stderr}"
        )
        assert "OK" in result.stdout

    def test_no_import_time_line_in_this_branch_resolves_its_own_file(self):
        """The structural half, because the behavioural half only covers what it imports.

        The first sweep of this species keyed on "written at module scope" and
        missed ``find_repo_root``'s own default argument — a line inside a
        function that four lanes reach during import, and the last crash
        standing. So this reads every module the import-time lanes pull in and
        fails on the idiom itself, wherever it is written.
        """
        offenders = []
        for path in _SOURCES:
            text = path.read_text(encoding="utf-8")
            prose = _prose_lines(text)
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or number in prose:
                    continue
                if "Path(__file__).resolve()" not in stripped:
                    continue
                offenders.append(f"{path.relative_to(_APPS.parent)}:{number}")

        assert not offenders, "use repo_root.module_file(__file__) — resolve() reads the cwd on Windows: " + ", ".join(
            offenders
        )


class TestNothingReadsTheStackAtImportTime:
    """``inspect.stack()`` is a cwd read on Windows, and I could not reproduce it here.

    The Windows CI traceback is unambiguous: ``inspect.stack()`` builds a
    FrameInfo per frame, ``getsourcefile`` -> ``getmodule`` -> ``os.path.realpath``,
    and ``ntpath.realpath`` reads the working directory. It crashed the import
    of every handler in this branch.

    ON POSIX IT DOES NOT CRASH FROM A DEAD CWD, and the reason is exact rather
    than the cache guess this docstring first carried. ``inspect.getmodule``
    reaches the unprotected ``os.path.realpath`` only past this, at
    ``inspect.py:991``::

        try:
            file = getabsfile(object, _filename)
        except (TypeError, FileNotFoundError):
            return None

    On POSIX ``abspath`` raises inside ``getabsfile`` — and inspect SWALLOWS it,
    returning None before the realpath loop is reached. On Windows
    ``ntpath.abspath`` uses ``_getfullpathname`` and does not raise for an
    absolute path, so execution continues INTO the loop and dies on the
    unprotected ``realpath`` there. Same stdlib, opposite outcome, and the
    difference is which of two calls fails first.

    Credit where it is due: @spawn measured this on the Windows gate and read it
    out of CPython rather than inferring it, correcting a platform claim I had
    mailed them a few hours earlier. Verified here against
    ``/usr/lib/python3.12/inspect.py`` before adopting it.

    Restoring ``inspect.stack()`` therefore leaves the DEAD-CWD pins GREEN,
    which I found by running the mutant rather than by assuming it died.

    THIS DOCSTRING USED TO SAY "on POSIX it cannot crash" AND THAT WAS WRONG —
    corrected 2026-08-31 after @spawn reproduced it on Linux and this branch
    verified the recipe rather than taking their word. The dead-cwd world is
    the wrong injection, not POSIX the wrong platform. See
    ``TestTheStackReadIsReproducibleAfterAll`` below for the world that does
    reach the crash and for the behavioural pins that now stand beside this one.

    This pin stays anyway, and not as a leftover: it fails on the line the
    construct is WRITTEN on, which is where the next copy will appear, and it
    convicts a file that never runs in any test. The behavioural pin can only
    judge the lanes it imports.
    """

    def test_no_module_reached_during_import_walks_the_stack_with_inspect(self):
        offenders = []
        for path in _SOURCES:
            text = path.read_text(encoding="utf-8")
            prose = _prose_lines(text)
            for number, line in enumerate(text.splitlines(), start=1):
                stripped = line.strip()
                if stripped.startswith("#") or number in prose:
                    continue
                if "inspect.stack()" in stripped:
                    offenders.append(f"{path.relative_to(_APPS.parent)}:{number}")

        assert not offenders, (
            "inspect.stack() resolves every frame's source file, which reads the working "
            "directory on Windows — walk sys._getframe() instead: " + ", ".join(offenders)
        )


class TestTheStackReadIsReproducibleAfterAll:
    """The behavioural half of the pin above, which this branch said was impossible.

    THE CORRECTION, AND WHOSE IT IS. On 2026-08-31 I wrote "on POSIX it cannot
    crash" into the class above and shipped a structural-only pin on the
    strength of it. @spawn reproduced the crash on Linux the same night. I was
    denying the wrong call: the dead-cwd world denies ``os.getcwd``, and on
    POSIX ``posixpath.abspath`` raises FIRST — inside ``inspect.getabsfile()``,
    where inspect catches it. The unprotected ``os.path.realpath`` in
    ``getmodule``'s loop is never reached, so the world is hostile to a call the
    defect does not make.

    THE RECIPE HAS TWO INGREDIENTS, and missing either one produces a green:

    1. deny ``os.path.realpath`` directly, and
    2. give the top frame a PSEUDO-FILENAME, which means launching the child
       with ``python -c`` rather than as a script.

    Ingredient 2 is the one that is easy to drop as noise. ``getsourcefile()``
    opens with a fast path — ``if os.path.exists(filename): return filename`` —
    so a frame that came from a real file on disk returns before ``getmodule``
    is ever called and no realpath happens at all. Only ``<string>`` and
    ``<stdin>`` fall through. Read out of ``inspect.py`` here before adopting
    it, on the same standard I asked @spawn to hold me to.

    So the third test below is a NEGATIVE CONTROL FOR THE POSITIVE CONTROL: it
    proves the crash needs the launcher, not just the denial. Without it, a
    future simplification that runs the probe as a script would leave the
    positive control passing while measuring nothing, and a vacuous control and
    a cured defect produce the same green.

    WHAT THIS PIN DOES NOT REACH, measured by mutating both sites rather than
    reasoned about. ``handlers/__init__.py`` has TWO frame walks, and the import
    probe below only executes one of them:

    * ``_find_real_caller`` — load-bearing, taken on every import. Restoring
      ``inspect.stack()`` here reddens the first test with CI's own traceback,
      ``inspect.py:1009 getmodule -> os.path.realpath``.
    * the ``caller_file is None`` diagnostic branch — reached only when NO
      real-file frame exists above the guard, and a package import always has
      one: ``apps/__init__.py`` does ``from . import handlers``, so it is
      always the caller. Restoring ``inspect.stack()`` there leaves every
      IMPORT-shaped pin GREEN.

    CORRECTED THE NEXT MORNING, AND THE CORRECTION IS AGAINST MY OWN SENTENCE.
    I wrote "only the structural sweep convicts it" and @devpulse relayed that
    fleet-wide. It was too strong. Import-shaped pins cannot reach that branch;
    a DIRECT CALL to ``_guard_branch_access()`` from a ``python -c`` child
    reaches it easily, and @spawn measured that while I was still calling it
    unreachable. ``TestTheDiagnosticBranchIsReachableAfterAll`` below is the
    behavioural sibling, and the regrown-walk mutant now dies to both
    instruments.

    The structural pin stays regardless, and for a reason the correction does
    not touch: it needs no subprocess, it names the defect on the line it is
    written on, and it convicts files no probe imports. What changed is the
    claim, not the pin — "unreachable from the probes I built" was reported as
    "unreachable", and those are not the same sentence.
    """

    _WORLD = REALPATH_DENIED_WORLD

    # What the guard used to call. The crash is inside ``inspect.stack()``
    # itself — before any of the walking code runs — so the construct IS the
    # reproduction; nothing about the surrounding loop changes the answer.
    _PROBE = (
        "import inspect\n"
        "try:\n"
        "    depth = len(inspect.stack())\n"
        "except Exception as exc:\n"
        "    print('RAISED', type(exc).__name__)\n"
        "else:\n"
        "    print('SURVIVED', depth)\n"
    )

    def test_the_shipped_guard_imports_clean_in_the_world_that_kills_the_old_one(self):
        probe = f"import sys\nsys.path.insert(0, {_src_root()!r})\n{self._WORLD}import aipass.memory.apps.handlers\nprint('OK')\n"
        result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
        assert result.returncode == 0, (
            "handlers/__init__.py could not be imported with os.path.realpath denied — "
            "this is the Windows CI crash, reproduced.\n" + result.stderr
        )
        assert "OK" in result.stdout

    def test_the_construct_the_guard_used_to_call_dies_in_that_same_world(self):
        """Positive control: the world is hostile, and hostile to THIS call."""
        result = subprocess.run([sys.executable, "-c", self._WORLD + self._PROBE], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "RAISED FileNotFoundError" in result.stdout, (
            "The realpath denial did not reach inspect.stack(), so the pin above is measuring nothing: " + result.stdout
        )

    def test_the_crash_needs_a_pseudo_filename_frame_not_just_the_denial(self, tmp_path):
        """Negative control FOR the control: same world, real file, no crash.

        If this ever starts reporting RAISED, the recipe has become
        one-ingredient and the class docstring is out of date. If the test above
        is ever rewritten to run from a file, it will silently join this one.
        """
        script = tmp_path / "from_a_real_file.py"
        script.write_text(self._WORLD + self._PROBE, encoding="utf-8")
        result = subprocess.run([sys.executable, str(script)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert result.stdout.startswith("SURVIVED"), (
            "A frame from a real file reached the unprotected realpath, which contradicts "
            "getsourcefile()'s os.path.exists fast path: " + result.stdout
        )


class TestTheDiagnosticBranchIsReachableAfterAll:
    """The second correction of the day, and it is against my own sentence.

    I wrote — and @devpulse relayed fleet-wide — that the guard's
    ``caller_file is None`` branch can only be watched structurally. The true
    sentence is narrower: it is unreachable from IMPORT-shaped pins, because
    ``apps/__init__.py`` does ``from . import handlers`` and so always supplies
    a real-file frame. It is perfectly reachable by CALLING
    ``_guard_branch_access()`` directly from a ``python -c`` child: every frame
    is then a string pseudo-name or importlib, both skipped, ``_find_real_caller``
    returns None, and the branch RUNS.

    @spawn measured that; @devpulse confirmed it in their own tree before
    relaying it. It is a better sentence than mine and it costs about fifteen
    lines, so the excuse for not having the behavioural sibling was never the
    price.

    TWO ARMING PROBES, because this world has two ways to be silently inert and
    each would leave the pin green while measuring nothing:

    * the realpath denial might not bite at all, and
    * the guard might be reaching a DIFFERENT path — if ``_find_real_caller``
      returns a real file, the branch under test never runs and the assertion
      below is about code that did not execute.

    The second probe is the one I would not have written a week ago. "The test
    passed" and "the test ran the line" are different claims, and only the
    second one is worth anything in a world built by injection.
    """

    _WORLD = REALPATH_DENIED_WORLD
    _SETUP = "import aipass.memory.apps.handlers as h\n"

    def _child(self, body: str) -> subprocess.CompletedProcess:
        probe = f"import sys\nsys.path.insert(0, {_src_root()!r})\n{self._WORLD}{self._SETUP}{body}"
        return subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)

    def test_the_denial_bites_in_this_child(self):
        """Arming probe 1: the world is hostile where the defect would live."""
        result = self._child(
            "import inspect\n"
            "try:\n"
            "    inspect.stack()\n"
            "except FileNotFoundError:\n"
            "    print('ARMED')\n"
            "else:\n"
            "    print('INERT')\n"
        )
        assert result.returncode == 0, result.stderr
        assert "ARMED" in result.stdout, "realpath is not denied in this child: " + result.stdout

    def test_the_guard_really_takes_the_caller_is_none_branch_here(self):
        """Arming probe 2: the line under test is the line that runs."""
        result = self._child("print('CALLER', h._find_real_caller())\n")
        assert result.returncode == 0, result.stderr
        assert "CALLER (None, None)" in result.stdout, (
            "a real-file frame reached the walk, so the diagnostic branch is NOT what the "
            "pin below exercises: " + result.stdout
        )

    def test_the_diagnostic_branch_returns_instead_of_crashing(self):
        result = self._child("h._guard_branch_access()\nprint('RETURNED')\n")
        assert result.returncode == 0, (
            "the caller-is-None branch crashed with os.path.realpath denied — this is the "
            "second inspect.stack() walk, regrown.\n" + result.stderr
        )
        assert "RETURNED" in result.stdout


class TestTheTwoWorldsMustNotBeStacked:
    """Denying MORE can deny LESS — on POSIX. This class used to say it everywhere.

    THE CI RED THAT REWROTE IT. On 8550ed10 windows-setup was down to exactly
    two failures and both were this class::

        test_getcwd_alone_does_not              assert 'DIES' == 'SURVIVES'
        test_stacking_them_undoes_the_conviction assert 'DIES' == 'SURVIVES'

    My failure message told the reader to suspect a CPython change. Wrong
    suspect: it was the PLATFORM, and the mistake underneath it was that I
    measured three verdicts on Linux and wrote them down as facts about
    ``inspect``. They are facts about ``posixpath``.

    THE TABLE, and what decides each row. On POSIX, ``abspath`` raises inside
    ``inspect.getabsfile()`` — which sits in inspect's own
    ``except (TypeError, FileNotFoundError)`` — so a getcwd denial is SWALLOWED
    and the unprotected ``os.path.realpath`` in ``getmodule`` is never reached.
    On nt, ``abspath`` rides Win32 ``_getfullpathname`` and never touches
    ``os.getcwd``, so it sails through that try and arrives at
    ``ntpath.realpath``, which reads the cwd unconditionally.

    ==================  ========  ========
    world               posix     nt
    ==================  ========  ========
    realpath denied     DIES      DIES
    getcwd denied       SURVIVES  DIES
    both denied         SURVIVES  DIES
    ==================  ========  ========

    KEYED ON ``os.name``, not ``sys.platform``, because the question this table
    answers is WHICH PATH MODULE the stdlib is using — @ai_mail's rule, and the
    right one here: ``sys.platform`` would need a darwin row that behaves
    exactly like linux, since darwin runs posixpath.

    WHICH HALVES ARE MEASURED WHERE, stated because a derived row that reads
    like a measured one is how a guess becomes a fact:

    * posix rows — measured live, on this host, every run.
    * nt rows — measured TWICE. Once on the real Windows runner (8550ed10:
      ``realpath denied`` PASSED, and the two reds carry their actual verdict in
      the assertion diff, so all three are positive measurements of a value and
      not merely proof that something was not SURVIVES). And once here, inside
      ``WINDOWS_EMULATED_WORLD``, which patches BOTH halves so every nt row runs
      on this machine and is falsifiable on it forever.

    Emulating the denial was never enough; the platform had to be emulated. That
    is @prax's correction, and this class is the thing it was aimed at.
    """

    _PROBE = (
        "import inspect\n"
        "try:\n"
        "    inspect.stack()\n"
        "except Exception:\n"
        "    print('DIES')\n"
        "else:\n"
        "    print('SURVIVES')\n"
    )

    # The whole claim, in the shape the reader can check against the docstring.
    _EXPECTED = {
        ("posix", "realpath"): "DIES",
        ("posix", "getcwd"): "SURVIVES",
        ("posix", "both"): "SURVIVES",
        ("nt", "realpath"): "DIES",
        ("nt", "getcwd"): "DIES",
        ("nt", "both"): "DIES",
    }

    _DENIALS = {
        "realpath": REALPATH_DENIED_WORLD,
        "getcwd": DEAD_CWD_WORLD,
        "both": DEAD_CWD_WORLD + REALPATH_DENIED_WORLD,
    }

    def _verdict(self, world: str) -> str:
        result = subprocess.run([sys.executable, "-c", world + self._PROBE], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_the_platform_emulation_actually_arms(self):
        """Arming probe: without BOTH halves patched, the nt rows are posix rows.

        The abspath half is the one that is easy to leave out, and leaving it
        out is silent — the table below would still pass three of its six rows
        and the two that changed would look like a platform fact.
        """
        world = (
            WINDOWS_EMULATED_WORLD
            + DEAD_CWD_WORLD
            + (
                "import os\n"
                "try:\n"
                "    os.path.abspath('relative')\n"
                "    print('ABSPATH_SURVIVED_THE_DENIAL')\n"
                "except FileNotFoundError:\n"
                "    print('ABSPATH_DIED')\n"
            )
        )
        result = subprocess.run([sys.executable, "-c", world], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        assert "ABSPATH_SURVIVED_THE_DENIAL" in result.stdout, (
            "the Win32 abspath half is not installed, so the nt rows below are measuring posix: " + result.stdout
        )

    @pytest.mark.parametrize("denial", ["realpath", "getcwd", "both"])
    @pytest.mark.parametrize("platform", ["posix", "nt"])
    def test_the_table_holds(self, platform, denial):
        prefix = WINDOWS_EMULATED_WORLD if platform == "nt" else ""
        expected = self._EXPECTED[(platform, denial)]
        assert self._verdict(prefix + self._DENIALS[denial]) == expected, (
            f"the {platform} row for a {denial} denial moved. On posix that would be a change in "
            "CPython's inspect.getmodule; on nt it would mean the emulation no longer matches the "
            "runner. Re-read dead_cwd.py and the CI log before trusting either world."
        )

    def test_no_probe_in_this_branch_stacks_them_outside_the_table(self):
        """Structural: only the table above may build the masking world.

        The masking is real on posix and the stacked world is genuinely kinder
        there, so a probe that reaches for "as hostile as possible" and
        concatenates both gets a world where the defect cannot fire.
        """
        offenders = []
        for path in sorted(Path(__file__).parent.rglob("test_*.py")):
            if path.name == Path(__file__).name:
                continue
            text = path.read_text(encoding="utf-8")
            if "DEAD_CWD_WORLD + REALPATH_DENIED_WORLD" in text:
                offenders.append(path.name)
        assert not offenders, "these stack the two denials and measure a kinder world: " + ", ".join(offenders)


class TestTheWindowsWorldSurvivesEveryWayPathlibReachesRealpath:
    """Python 3.10 held its own copy of ``os.path.realpath``, and my probe missed it.

    CI, 2026-08-31, commit 8550ed10, Python 3.10 ONLY (3.11/3.12/3.13 green)::

        TestResolvingOwnFileIsACwdReadOnWindows::test_the_injected_world_really_reads_the_cwd
        AssertionError: NO_RAISE

    That is the arming probe doing its whole job. The world was inert on that
    interpreter, so every pin beneath it — the thirty-two import-time lanes —
    had been passing on 3.10 while asserting nothing, and no other test could
    have said so: a vacuous pin and a cured defect produce the same green.

    THE MECHANISM, READ OUT OF CPython 3.10's ``Lib/pathlib.py`` rather than
    inferred, because the diagnosis that reached me was that 3.10's pathlib does
    not delegate to ``os.path.realpath`` at all, and that is not what the source
    says::

        358:  realpath = staticmethod(os.path.realpath)        # _NormalAccessor
        1077: s = self._accessor.realpath(self, strict=strict)  # Path.resolve

    It DOES delegate. It just took its copy when pathlib was first imported. So
    a probe that imports pathlib and then rebinds ``os.path.realpath`` is
    rebinding a name nothing will read again. 3.11 deleted the accessor and
    calls ``os.path.realpath`` at use, which is why exactly one version reddened.

    WHICH MAKES THIS THE SAME DEFECT AS THE GETCWD ONE, one constant over. The
    getcwd world has carried the accessor cure since the last 3.10 red, with a
    docstring explaining the trap in detail. Its sibling did not, because the
    sibling lived in this test file instead of next to that docstring. A cure
    that does not travel to the constant twenty lines away is the shape this
    branch has now shipped twice; both worlds live in ``dead_cwd.py`` now.

    NOT FALSIFIABLE BY RUNNING 3.10 — there is no 3.10 interpreter on this
    machine. So the accessor is BUILT here instead, the way ``ACCESSOR_SHAPE``
    already builds the getcwd one, and the pins below run on any interpreter.
    That is a stand-in for a version, and it expires the moment a real 3.10 run
    disagrees with it — which is the honest form for a row a local host cannot
    reach.
    """

    # 3.10's shape, reduced to the two lines that matter: the accessor takes
    # its copy of os.path.realpath at class-definition time (pathlib.py:358),
    # and Path.resolve reaches it through an INSTANCE (pathlib.py:1077).
    _PRE_CAPTURED_ACCESSOR = (
        "import os, pathlib\n"
        "class _NormalAccessor:\n"
        "    realpath = staticmethod(os.path.realpath)\n"
        "pathlib._NormalAccessor = _NormalAccessor\n"
        "pathlib._the_accessor = _NormalAccessor()\n"
    )

    # Asked the way 3.10 asks: through an instance, which is what makes the
    # staticmethod load-bearing rather than decoration.
    _ASK_THE_ACCESSOR = (
        "import pathlib\n"
        "try:\n"
        "    got = pathlib._the_accessor.realpath('/tmp')\n"
        "    print('NO_RAISE', got)\n"
        "except FileNotFoundError:\n"
        "    print('RAISED')\n"
    )

    _BARE_PATCH = (
        "import os\n"
        "_before = os.path.realpath\n"
        "def _reads_the_cwd(p, *a, **k):\n"
        "    os.getcwd()\n"
        "    return _before(p, *a, **k)\n"
        "os.path.realpath = _reads_the_cwd\n"
    )

    def _verdict(self, world: str) -> str:
        result = subprocess.run([sys.executable, "-c", world], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def test_the_bare_patch_never_reaches_a_pre_captured_accessor(self):
        """The 3.10 defect, reproduced on this interpreter. Red before the cure."""
        world = self._PRE_CAPTURED_ACCESSOR + self._BARE_PATCH + DEAD_CWD_WORLD + self._ASK_THE_ACCESSOR
        assert self._verdict(world).startswith("NO_RAISE"), (
            "a bare os.path.realpath patch now reaches a pre-captured accessor, which would "
            "mean the 3.10 red had some other cause — re-read the CI log before trusting this file"
        )

    def test_the_shipped_world_does_reach_it(self):
        """The cure: patch the accessor when one exists, exactly as the getcwd world does."""
        world = self._PRE_CAPTURED_ACCESSOR + WINDOWS_REALPATH_WORLD + DEAD_CWD_WORLD + self._ASK_THE_ACCESSOR
        assert self._verdict(world) == "RAISED", (
            "WINDOWS_REALPATH_WORLD did not arm through the accessor — this is the Python 3.10 "
            "NO_RAISE from CI, reproduced"
        )

    def test_it_still_arms_where_there_is_no_accessor_at_all(self):
        """3.11+ has no accessor. The cure must not depend on finding one."""
        world = (
            WINDOWS_REALPATH_WORLD
            + DEAD_CWD_WORLD
            + (
                "import pathlib\n"
                "try:\n"
                "    pathlib.Path('/tmp').resolve()\n"
                "    print('NO_RAISE')\n"
                "except FileNotFoundError:\n"
                "    print('RAISED')\n"
            )
        )
        assert self._verdict(world) == "RAISED"

    def test_the_accessor_still_answers_CORRECTLY_when_the_cwd_is_fine(self):
        """A world that raises for the right reason can still return the wrong path.

        ``staticmethod`` is what stops this. Through an instance a plain
        function BINDS, so the accessor arrives as the first positional and the
        real path slides into ``*a`` — the denial still fires, so every
        raise-shaped pin above stays green, and the world silently starts
        resolving the accessor object instead of the file. Dropping the
        ``staticmethod`` survived the whole suite until this test existed, which
        is why it is here rather than in a comment saying "obviously needed".
        """
        world = self._PRE_CAPTURED_ACCESSOR + WINDOWS_REALPATH_WORLD + self._ASK_THE_ACCESSOR
        assert self._verdict(world) == "NO_RAISE /tmp", (
            "the patched accessor did not return the path it was handed — a bound plain "
            "function eats the argument. It must be a staticmethod."
        )
