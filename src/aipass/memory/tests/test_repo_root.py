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
    """Four callers resolve at MODULE level, so this write happens during their import."""

    def test_a_failing_log_operation_does_not_propagate(self, tmp_path, monkeypatch):
        """A diagnostic write must not become the crash it was diagnosing."""

        def explode(*_args, **_kwargs):
            raise OSError("read-only filesystem")

        monkeypatch.setattr(rr.json_handler, "log_operation", explode)
        assert rr.find_repo_root(tmp_path) == rr.SOURCE_ROOT

    def test_the_fallback_is_still_recorded_when_it_can_be(self, tmp_path, monkeypatch):
        """Defensive does not mean absent — the operation is logged on the happy path."""
        seen = []
        monkeypatch.setattr(rr.json_handler, "log_operation", lambda *a, **k: seen.append((a, k)))
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
_DENY_CWD = "import os\nos.getcwd = lambda: (_ for _ in ()).throw(FileNotFoundError(2, 'No such file or directory'))\n"

_DELETE_CWD = "import os, tempfile\nd = tempfile.mkdtemp()\nos.chdir(d); os.rmdir(d)\n"

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
            "import os, sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "import aipass.prax.apps.handlers.config.load as prax_load\n"
            f"prax_load._find_repo_root = lambda: pathlib.Path({str(rr.SOURCE_ROOT)!r})\n"
            f"{world}"
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
            "import os, sys, pathlib\n"
            f"sys.path.insert(0, {_src_root()!r})\n"
            "import aipass.prax.apps.handlers.config.load as prax_load\n"
            f"prax_load._find_repo_root = lambda: pathlib.Path({str(rr.SOURCE_ROOT)!r})\n"
            # every registry on this machine becomes invisible, so the walk in
            # every lane runs off the end and the fallback is what answers
            "_real_exists = pathlib.Path.exists\n"
            "pathlib.Path.exists = lambda self, *a, **k: (\n"
            "    False if self.name.endswith('_REGISTRY.json') else _real_exists(self, *a, **k)\n"
            ")\n"
            f"{_DENY_CWD}"
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
