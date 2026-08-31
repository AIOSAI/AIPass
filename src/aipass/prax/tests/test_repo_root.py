# ===================AIPASS====================
# META DATA HEADER
# Name: test_repo_root.py - Repo-Root Resolution Pins
# Date: 2026-08-31
# Version: 1.0.0
# Category: prax/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-31): Initial creation — @memory's dead-cwd report, plus the
#     second crash site the sweep found in introspection
#
# CODE STANDARDS:
#   - Pytest function style (no unittest classes)
#   - Dead-cwd behaviour is proved in a SUBPROCESS — a test that deletes its own
#     working directory in-process cannot get back
# =============================================

"""Pins for repo-root resolution that must never read the process CWD.

@memory reported on 2026-08-31, with a full traceback: config/load.py's
_find_repo_root ended `return Path.cwd()`, and because nearly every handler in
AIPass does `logger = get_system_logger()` at module level, that walk runs during
IMPORT. A process whose working directory has been deleted crashed importing
almost anything; a registry-less checkout (every clean CI clone — the registry is
gitignored) silently resolved system_logs/ against wherever the shell stood.

Prax carried EIGHT copies of that function. The cure is one shared module, and
the guard against the ninth copy is structural: an AST sweep, with a positive
control so it cannot be quietly silenced.

The sweep found a second crash site @memory's traceback could not reach, because
their caller was a real absolute file: introspection.detect_branch_from_path
resolves the CALLER's path, and a pseudo-filename like <stdin> is relative, so
resolve() reads the cwd there too.
"""

import ast
import subprocess
import sys
import textwrap
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath

import pytest

from aipass.prax.apps.handlers import repo_root as repo_root_mod


def _answer(result) -> str:
    """The last line a probe printed — its answer, not its noise."""
    return result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ""


APPS_DIR = Path(repo_root_mod.__file__).resolve().parents[1]
REPO_SRC = str(Path(repo_root_mod.__file__).resolve().parents[5])


# The condition these tests pin is "os.getcwd() raises" — NOT "a directory was
# deleted". Deleting the working directory is one CAUSE of that condition, and it
# is the one cause Windows makes structurally impossible: the OS locks a process's
# current directory, so rmtree fails with WinError 32 and the world dies at SETUP,
# never reaching the claim. @memory owns the shared recipe and ruled on
# 2026-08-31: inject the condition instead. Same call site, same exception, same
# import-time crash — and it runs on every platform.
#
# A skipif(win32) would have been an honest test stating its world, and it is
# still refused: it would retire the pin on the exact platform whose CI leg found
# the defect. TestBothConstructionsAgree below licenses the substitution — the
# injection stands in for the deletion only for as long as that test says the two
# worlds give the identical answer from the identical call site.
_INJECT_DEAD_CWD = """
import os as _os


def _no_working_directory(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_os.getcwd = _no_working_directory
try:
    _os.getcwd()
    print("INVALID-PROBE: the working directory still answers")
    raise SystemExit(3)
except FileNotFoundError:
    pass
"""

_DELETE_CWD = """
import os as _os, shutil as _shutil, tempfile as _tempfile
_d = _tempfile.mkdtemp()
_os.chdir(_d)
_shutil.rmtree(_d)
try:
    _os.getcwd()
    print("INVALID-PROBE: the working directory still answers")
    raise SystemExit(3)
except OSError:
    pass
"""


# Without this the dead-cwd probes are weaker than they look on a developer
# machine: the marker walk SUCCEEDS here, so the fallback that reads the working
# directory is never reached and the probe proves only that the happy path does
# not need a cwd. CI has no registry (it is gitignored), which is why the defect
# showed there and not here. Making the marker unfindable puts every machine in
# CI's world for the length of the probe.
_MARKER_ABSENT = """
from aipass.prax.apps.handlers import repo_root as _rr
_rr.REGISTRY_MARKER = "AIPASS_REGISTRY_THAT_CANNOT_EXIST.json"
"""


def _run_without_a_working_directory(body: str, world: str = _INJECT_DEAD_CWD, marker_absent: bool = True):
    """Run a snippet in a process whose working directory cannot be read."""
    script = (
        world
        + textwrap.dedent(
            f"""
        import sys
        sys.path.insert(0, {REPO_SRC!r})
        """
        )
        + (_MARKER_ABSENT if marker_absent else "")
        + textwrap.dedent(body)
    )
    # Fed on STDIN, not with -c, and that detail is the test. A `-c` caller
    # produces no usable stack filename so introspection bails early; a `<stdin>`
    # caller produces a RELATIVE pseudo-filename, which is exactly what
    # detect_branch_from_path then hands to resolve().
    return subprocess.run([sys.executable, "-"], input=script, capture_output=True, text=True, timeout=120)


# =============================================================================
# THE SHARED RESOLVER
# =============================================================================


class TestSourceRoot:
    """The fallback is derived from the FILE, and nothing else.

    The component walk is pinned through _walk_to_source_root on BOTH path
    dialects, from either platform. @devpulse's Windows CI leg found the first
    version of these tests asserting on ``Path("/x/checkout/src/...")``, which is
    rooted-but-driveless and therefore NOT absolute as a WindowsPath — so
    source_root's guard refused the fabricated start and answered with the real
    checkout. The verdict was TEST-WORLD, not production: source_root calls no
    resolve() at all, and the module's only resolve() is on __file__, which is
    absolute and needs no working directory. A fabricated POSIX literal simply
    stops being the world you meant on the other platform.
    """

    @pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
    def test_the_directory_containing_src_is_the_checkout(self, flavour):
        start = flavour("/x/checkout/src/aipass/prax/a.py")
        assert repo_root_mod._walk_to_source_root(start) == flavour("/x/checkout")

    @pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
    def test_no_src_component_falls_to_the_root(self, flavour):
        """Defined, incapable of raising, and absurd enough to fail loudly.

        A plausible-looking answer here is worse than an absurd one: it would
        resolve quietly into somebody's home directory.
        """
        walked = repo_root_mod._walk_to_source_root(flavour("/nowhere/at/all/a.py"))
        assert walked == flavour("/")

    def test_a_drive_qualified_windows_path_walks_to_its_own_checkout(self):
        """The spelling a real Windows caller actually produces."""
        start = PureWindowsPath(r"D:\a\AIPass\AIPass\src\aipass\prax\a.py")
        assert repo_root_mod._walk_to_source_root(start) == PureWindowsPath(r"D:\a\AIPass\AIPass")

    @pytest.mark.parametrize("flavour", [PurePosixPath, PureWindowsPath])
    def test_the_src_match_is_exact_case_not_folded(self, flavour):
        """A deliberate semantic, pinned because a mutation folding it survived.

        Case-folding the component match would "work" on Windows and GUESS on
        Linux, where SRC/ and src/ are genuinely different directories. Guessing
        across case is the same move that made Path.glob read a lowercase file as
        the registry trust anchor. An unrecognised layout takes the loud last
        resort instead — which is what the last resort is for.
        """
        assert repo_root_mod._walk_to_source_root(flavour("/x/SRC/aipass/prax/a.py")) == flavour("/")

    def test_a_relative_start_is_refused_not_resolved(self):
        """Resolving it would read the working directory this module exists to avoid."""
        assert repo_root_mod.source_root(Path("relative/a.py")) == repo_root_mod.source_root()

    def test_a_rooted_driveless_start_is_refused_on_windows_spelling(self):
        """The exact shape that made the CI leg red, now stated as the rule.

        source_root only trusts an ABSOLUTE start. On Windows a rooted path with
        no drive is not absolute, so it is refused — correctly, because resolving
        it would read the working directory. Pinned so nobody 'fixes' the guard
        to accept it.
        """
        assert not PureWindowsPath("/x/checkout/src/aipass/prax/a.py").is_absolute()
        assert PurePosixPath("/x/checkout/src/aipass/prax/a.py").is_absolute()


class TestFindRepoRoot:
    """Marker first, source root second, working directory never."""

    def test_the_marker_wins_when_present(self, tmp_path):
        root = tmp_path / "checkout"
        (root / "src" / "aipass" / "prax").mkdir(parents=True)
        (root / repo_root_mod.REGISTRY_MARKER).write_text("{}")
        assert repo_root_mod.find_repo_root(root / "src" / "aipass" / "prax" / "a.py") == root

    def test_a_registry_less_checkout_resolves_to_the_checkout(self, tmp_path):
        """Every clean CI clone: the marker is gitignored, so it is never there."""
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        assert repo_root_mod.find_repo_root(start) == tmp_path / "checkout"

    def test_a_relative_start_is_refused_not_walked_from_the_cwd(self, tmp_path, monkeypatch):
        """The mutation this kills: accepting a relative start.

        It survives every dead-cwd pin, because with a relative path the walk
        simply finds nothing and falls through. The damage shows with a LIVE cwd:
        a caller standing inside some other checkout would have the marker found
        THERE, and this function would confidently return somebody else's repo.
        """
        foreign = tmp_path / "someone_elses_checkout"
        (foreign / "src" / "aipass" / "prax").mkdir(parents=True)
        (foreign / repo_root_mod.REGISTRY_MARKER).write_text("{}")
        monkeypatch.chdir(foreign)

        # Walking this relative start reaches Path(".") — which IS the foreign
        # checkout — and finds the marker there.
        resolved = repo_root_mod.find_repo_root(Path("src/aipass/prax/a.py"))
        assert resolved not in (Path("."), foreign), (
            f"a relative start was walked from the working directory: {resolved}"
        )
        assert resolved == repo_root_mod.find_repo_root()

    def test_the_fallback_is_announced(self, tmp_path, caplog, monkeypatch):
        """A fallback nobody can see is how the next one survives (@memory)."""
        monkeypatch.setattr(repo_root_mod, "_ANNOUNCED", set())
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        with caplog.at_level("WARNING", logger=repo_root_mod.__name__):
            repo_root_mod.find_repo_root(start)
        assert repo_root_mod.REGISTRY_MARKER in caplog.text

    def test_the_announcement_is_once_per_process_not_once_per_call(self, tmp_path, caplog, monkeypatch):
        """Every module in the branch reaches this during import — a per-call
        warning would bury CI output on exactly the checkout it is about."""
        monkeypatch.setattr(repo_root_mod, "_ANNOUNCED", set())
        start = tmp_path / "checkout" / "src" / "aipass" / "prax" / "a.py"
        start.parent.mkdir(parents=True)
        with caplog.at_level("WARNING", logger=repo_root_mod.__name__):
            for _ in range(5):
                repo_root_mod.find_repo_root(start)
        assert caplog.text.count("[repo_root]") == 1

    def test_this_module_imports_nothing_from_prax(self):
        """@memory's caveat, pinned structurally instead of with a try/except.

        This runs inside the construction of prax's own logger. A diagnostic that
        needs the logger it is being emitted from is a second crash wearing a
        diagnostic's clothes — so the guarantee is that there is nothing here to
        recurse INTO, not that a recursion would be caught.
        """
        tree = ast.parse(Path(repo_root_mod.__file__).read_text(encoding="utf-8"))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported += [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        assert not [name for name in imported if name.startswith("aipass")], imported


# =============================================================================
# THE DEAD CWD — proved, not reasoned
# =============================================================================


class TestDeadCwd:
    """@memory's condition: the working directory is gone and something imports."""

    def test_the_resolver_answers_without_a_working_directory(self):
        result = _run_without_a_working_directory(
            """
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path("/no/such/src/aipass/x/a.py")))
            """
        )
        assert result.returncode == 0, result.stderr
        assert "ANSWER" in result.stdout, result.stderr

    def test_the_logger_can_be_built_without_a_working_directory(self):
        """The end-to-end case, and the one @memory's traceback could not reach.

        Their caller was a real absolute file, so resolution of the CALLER path
        succeeded and the walk got as far as load.py. Run from a pseudo-filename
        — a heredoc, an embedded interpreter, any `<stdin>` caller — and
        introspection.detect_branch_from_path resolves a RELATIVE path first and
        dies one frame earlier.
        """
        result = _run_without_a_working_directory(
            """
            from aipass.prax.apps.modules.logger import get_system_logger
            print("LOGGER", get_system_logger().name)
            """
        )
        assert result.returncode == 0, result.stderr
        assert "LOGGER" in result.stdout, result.stderr

    def test_the_fallback_path_is_the_one_being_exercised(self):
        """Positive control on the WORLD, not the claim — and the honesty note.

        On this machine the marker walk succeeds, so without _MARKER_ABSENT these
        probes would only prove the happy path needs no working directory. That
        is exactly why the defect showed on CI (no registry — it is gitignored)
        and not here. This asserts the answer really is the source-root fallback,
        so the branch under test is the one that used to read Path.cwd().

        What this pin CANNOT do is fail against the pre-fix code on a machine that
        has a registry: the old walk hardcoded its own marker, so nothing in this
        process could make it miss. That negative control needs a registry-less
        checkout, and it was run as one — @memory's traceback, reproduced and then
        cured, 2026-08-31.
        """
        result = _run_without_a_working_directory(
            """
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path(repo_root.__file__)))
            """
        )
        assert result.returncode == 0, result.stderr
        assert _answer(result).split(" ", 1)[1] == str(repo_root_mod.source_root())

    def test_the_system_logs_dir_resolves_without_a_working_directory(self):
        result = _run_without_a_working_directory(
            """
            from aipass.prax.apps.handlers.config.load import get_system_logs_dir
            print("LOGS", get_system_logs_dir())
            """
        )
        assert result.returncode == 0, result.stderr
        assert "LOGS" in result.stdout, result.stderr


class TestCallerPathResolution:
    """introspection._resolve_caller_path — the second crash site.

    @memory's traceback stopped at config/load.py because their caller was a real
    absolute file. Run the same probe from a heredoc and detect_branch_from_path
    dies ONE FRAME EARLIER, resolving a relative pseudo-filename.
    """

    def test_a_pseudo_filename_is_not_a_path(self):
        from aipass.prax.apps.handlers.logging import introspection

        assert introspection._resolve_caller_path("<stdin>") is None
        assert introspection._resolve_caller_path("<string>") is None

    def test_a_relative_caller_is_refused_even_when_the_cwd_is_alive(self, tmp_path, monkeypatch):
        """The half the dead-cwd pin cannot see, and the reason this guard exists
        for correctness and not only for crashes.

        With a LIVE working directory a relative caller path resolves fine — to
        the wrong place. It would be attributed to whatever branch the caller's
        shell happened to be standing in, silently. Dropping the is_absolute
        guard survives the dead-cwd pin (the try/except catches that) and is
        killed only here.
        """
        from aipass.prax.apps.handlers.logging import introspection

        branch_dir = tmp_path / "src" / "aipass" / "someoneelse" / "apps"
        branch_dir.mkdir(parents=True)
        (branch_dir / "mod.py").write_text("")
        monkeypatch.chdir(branch_dir)

        assert introspection._resolve_caller_path("mod.py") is None

    def test_an_absolute_caller_still_resolves(self, tmp_path):
        from aipass.prax.apps.handlers.logging import introspection

        real = tmp_path / "mod.py"
        real.write_text("")
        assert introspection._resolve_caller_path(str(real)) == real.resolve()

    def test_an_unresolvable_absolute_path_is_an_answer_not_a_crash(self, monkeypatch):
        """Branch detection is a routing hint. Not knowing where the caller lives
        must never take down the caller's import."""
        from aipass.prax.apps.handlers.logging import introspection

        def boom(self, *_args, **_kwargs):
            raise OSError("no cwd")

        monkeypatch.setattr(Path, "resolve", boom)
        assert introspection._resolve_caller_path("/absolute/but/unresolvable.py") is None


class TestBothConstructionsAgree:
    """The licence for substituting the injected world for the deleted one.

    @memory's ruling allows injecting a raising os.getcwd in place of deleting
    the working directory, because the CONDITION is what the pins are about. This
    class is the condition on that licence: on POSIX both worlds are buildable,
    so both must produce the IDENTICAL answer from the IDENTICAL call site. The
    day they diverge, the stand-in stops being a stand-in and these go red rather
    than the substitution quietly drifting.

    Skipped on Windows for the reason the substitution exists at all — the OS
    locks a process's current directory, so the deletion world cannot be built
    there to compare against.
    """

    PROBE = """
        from aipass.prax.apps.handlers import repo_root
        from pathlib import Path
        print("ANSWER", repo_root.find_repo_root(Path("/no/such/src/aipass/x/a.py")))
        """

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="the deleted-cwd world is unbuildable on Windows — WinError 32, the OS locks it",
    )
    def test_the_injected_world_and_the_deleted_world_give_the_same_answer(self):
        injected = _run_without_a_working_directory(self.PROBE, world=_INJECT_DEAD_CWD)
        deleted = _run_without_a_working_directory(self.PROBE, world=_DELETE_CWD)

        assert injected.returncode == 0, injected.stderr
        assert deleted.returncode == 0, deleted.stderr
        assert _answer(injected) == _answer(deleted), (
            f"injected={_answer(injected)!r} deleted={_answer(deleted)!r} — the stand-in no longer stands in"
        )

    @pytest.mark.skipif(
        sys.platform == "win32",
        reason="the deleted-cwd world is unbuildable on Windows — WinError 32, the OS locks it",
    )
    def test_both_worlds_really_do_break_the_working_directory(self):
        """Positive control on the WORLDS, not on the claim.

        Each recipe's own INVALID-PROBE guard fires if the working directory
        still answers; this proves the guard is reachable, so a world that
        silently failed to break anything could not pass as a dead-cwd test.
        """
        probe = """
            import os
            try:
                os.getcwd()
                print("ALIVE")
            except OSError:
                print("BROKEN")
            """
        for name, world in (("injected", _INJECT_DEAD_CWD), ("deleted", _DELETE_CWD)):
            result = _run_without_a_working_directory(probe, world=world)
            assert "BROKEN" in result.stdout, f"{name}: {result.stdout!r} {result.stderr!r}"


# =============================================================================
# THE SWEEP — no ninth copy
# =============================================================================

# The single sanctioned working-directory read in prax: `drone @prax dashboard
# refresh` with no argument means "the branch I am standing in", and the cwd IS
# the question there rather than a fallback for a question it could not answer.
CWD_ALLOWLIST = {"apps/modules/dashboard.py"}


def _module_key(relative: PurePath) -> str:
    """The one spelling a module is named by, on every platform.

    Normalised at the sweep BOUNDARY rather than at each comparison, because a
    separator-sensitive key is the kind of thing that gets fixed in one place and
    stays broken in the next. Path.relative_to returns the OS's own separators,
    so on Windows the raw str() disagreed with the forward-slash allowlist and
    the sweep convicted a line it had been told to ignore (@devpulse, Windows CI,
    2026-08-31).
    """
    return relative.as_posix()


def _modules_reading_the_cwd(root: Path) -> dict:
    """AST scan: which files call Path.cwd() or os.getcwd()?"""
    found = {}
    for path in sorted(root.rglob("*.py")):
        if ".archive" in path.parts or "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - not our lane
            continue
        lines = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
                continue
            owner = node.func.value
            name = getattr(owner, "id", None)
            if (name == "Path" and node.func.attr == "cwd") or (name == "os" and node.func.attr == "getcwd"):
                lines.append(node.lineno)
        if lines:
            found[_module_key(path.relative_to(root.parent))] = lines
    return found


class TestNoPrivateCwdFallback:
    """Eight identical copies is how this survived. The ninth is a red test."""

    def test_no_module_outside_the_allowlist_reads_the_working_directory(self):
        offenders = {
            module: lines for module, lines in _modules_reading_the_cwd(APPS_DIR).items() if module not in CWD_ALLOWLIST
        }
        assert not offenders, (
            "these modules resolve against the process working directory — derive "
            f"from __file__ via handlers/repo_root.py instead: {offenders}"
        )

    def test_the_sweep_can_actually_see_a_violation(self, tmp_path):
        """Positive control. A sweep that finds nothing because it looks nowhere
        reports the same green as a clean tree."""
        planted = tmp_path / "apps" / "planted.py"
        planted.parent.mkdir(parents=True)
        planted.write_text("from pathlib import Path\n\n\ndef f():\n    return Path.cwd()\n")
        assert _modules_reading_the_cwd(tmp_path / "apps")

    def test_the_allowlist_matches_a_windows_spelled_key(self):
        """@devpulse's Windows CI leg: the sweep convicted an EXEMPTED line.

        Path.relative_to gives back the OS's own separators, so on Windows the
        key was ``apps\\modules\\dashboard.py`` while the allowlist holds a
        forward-slash literal. No match, so an allowlisted file was reported as
        an offender — the sweep accused the one line it had been told to ignore.

        Pinned with a Windows-spelled relative path so it runs red-first on
        Linux; a live-path assertion could never have caught this from here.
        """
        assert _module_key(PureWindowsPath(r"apps\modules\dashboard.py")) in CWD_ALLOWLIST
        assert _module_key(PurePosixPath("apps/modules/dashboard.py")) in CWD_ALLOWLIST

    def test_the_allowlist_names_only_files_that_exist(self):
        """An allowlist entry for a deleted file is a hole nobody can see."""
        for entry in CWD_ALLOWLIST:
            assert (APPS_DIR.parent / entry).exists(), entry


class TestEveryLaneUsesTheSharedResolver:
    """Structural: no lane keeps a private walk (@memory's sweep shape).

    Paired deliberately with the cwd sweep above, because each covers the other's
    blind spot. This one is NAME-based and a rename defeats it — but a renamed
    private walk still has to end somewhere, and if it ends at the working
    directory the cwd sweep names it. Matching the marker string instead was
    tried and rejected: a dozen modules legitimately READ AIPASS_REGISTRY.json,
    and a sweep that cannot tell reading the file from walking for the root gets
    muted for crying wolf.
    """

    def test_every_find_repo_root_delegates_to_the_shared_resolver(self):
        private = {}
        for path in sorted(APPS_DIR.rglob("*.py")):
            if ".archive" in path.parts or "__pycache__" in path.parts:
                continue
            if path == Path(repo_root_mod.__file__).resolve():
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name != "_find_repo_root":
                    continue
                delegates = any(
                    isinstance(inner, ast.Call)
                    and getattr(inner.func, "id", getattr(inner.func, "attr", None)) == "find_repo_root"
                    for inner in ast.walk(node)
                )
                if not delegates:
                    private.setdefault(_module_key(path.relative_to(APPS_DIR.parent)), []).append(node.lineno)
        assert not private, (
            f"these modules walk for the repo root themselves instead of calling handlers/repo_root.py: {private}"
        )

    def test_the_delegation_sweep_can_actually_see_a_violation(self, tmp_path):
        """Positive control: a sweep that looks nowhere reports the same green."""
        planted = tmp_path / "planted.py"
        planted.write_text("from pathlib import Path\n\n\ndef _find_repo_root():\n    return Path.cwd()\n")
        tree = ast.parse(planted.read_text())
        offenders = [
            node.lineno
            for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef)
            and node.name == "_find_repo_root"
            and not any(
                isinstance(inner, ast.Call)
                and getattr(inner.func, "id", getattr(inner.func, "attr", None)) == "find_repo_root"
                for inner in ast.walk(node)
            )
        ]
        assert offenders, "the sweep would not have seen a planted private walk"

    def test_the_lanes_agree_with_the_shared_answer(self):
        """Behavioural, not just structural: same question, one answer."""
        from aipass.prax.apps.handlers.config import load as load_mod
        from aipass.prax.apps.handlers.dashboard import refresh as refresh_mod
        from aipass.prax.apps.handlers.dashboard import status as status_mod

        expected = repo_root_mod.find_repo_root()
        assert load_mod._find_repo_root() == expected
        assert refresh_mod._find_repo_root() == expected
        assert status_mod._find_repo_root() == expected
