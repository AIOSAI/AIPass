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
import os
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

# CI's world, built on Linux. @spawn measured the mechanism on the Windows gate
# 2026-08-31: ntpath.realpath calls os.getcwd() unconditionally on its first
# lines — before it checks whether the path is even absolute — and inspect's
# getmodule() calls os.path.realpath OUTSIDE a try. posixpath.realpath does not
# take that path, and the equivalent POSIX raise happens inside getabsfile()
# where inspect swallows it. That is the whole reason a denied working directory
# was survivable on Linux and fatal on Windows.
#
# Denying os.path.realpath is therefore not a second world — it is the SAME
# denial reaching the call Windows actually makes. Against the pre-cure guard
# these pins go red on Linux; the getcwd-only world stays green, which is the
# demonstration of why Linux missed it.
#
# CORRECTION 2026-08-31, and it matters for anyone reading these pins as
# evidence: this world convicts an unguarded MODULE-LEVEL Path(__file__).
# resolve(). It does NOT convict inspect.stack(), and I reported to @devpulse
# that it did. What actually happens, measured three ways: getcwd-denied ->
# stack SURVIVES; getcwd AND realpath denied -> stack SURVIVES; realpath denied
# ALONE -> stack DIES. The reason is _NTPATH_SHAPED below. @trigger and @seedgo
# both flagged it before I measured it; they were right.
_DENY_REALPATH = (
    _INJECT_DEAD_CWD
    + """
import os.path as _ospath


def _no_realpath(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_ospath.realpath = _no_realpath
"""
)

# THE WORLD THAT CONVICTS A STACK WALK. realpath raises, getcwd still answers.
#
# That combination looks artificial until you look at what Windows does.
# `ntpath.abspath` does not call `os.getcwd()` at all — it calls the Win32
# `_getfullpathname`, which reads the process directory from the OS and sails
# straight past a patched (or broken) getcwd. `ntpath.realpath` DOES call
# os.getcwd(), in Python, on its first lines. So on a Windows box with no usable
# working directory, abspath works and realpath raises — which is exactly this
# world, and exactly why inspect dies there.
#
# Follow it through inspect: getsourcefile() only calls getmodule() for a
# filename that does not exist on disk (`<stdin>` qualifies, which is why these
# probes are fed on stdin). getmodule() opens with getabsfile(), wrapped in
# `except (TypeError, FileNotFoundError)` — so denying getcwd makes abspath
# raise there and inspect SWALLOWS it, returning None before the dangerous line.
# Let abspath succeed and the walk reaches `modulesbyfile[os.path.realpath(f)]`,
# which is not in any try. That is the unguarded call, and reaching it requires
# a working getcwd.
#
# So the getcwd denial is not merely insufficient here — it is what HIDES the
# defect. A world can be too hostile to convict.
_NTPATH_SHAPED = """
import os.path as _ospath


def _no_realpath(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


_ospath.realpath = _no_realpath
"""

# WINDOWS, EMULATED ON LINUX. Three facts about ntpath vs posixpath in 3.12:
#   1. ntpath.realpath calls os.getcwd() unconditionally on its first lines.
#   2. ntpath.abspath does NOT — it calls the Win32 _getfullpathname, which reads
#      the process directory from the OS and never touches os.getcwd.
#   3. posixpath routes BOTH through os.getcwd.
#
# That third fact is the whole POSIX/Windows asymmetry, and it is why the same
# injected getcwd denial produces opposite verdicts on the two platforms. On
# Windows abspath survives the denial and realpath does not, so inspect's
# getabsfile succeeds and the walk reaches the unguarded realpath: ALL THREE
# worlds below convict there. On Linux the denial kills abspath first, inside
# getabsfile's own except, and inspect returns None before the dangerous line.
#
# Measured on the real Windows runner 2026-08-31 (run 33431848734, reported by
# @devpulse): getcwd-denied DIED, realpath-denied DIED, ntpath-shaped DIED.
# This world reproduces that reading on Linux, which is the only way prax can
# check it — there is no Windows box here.
_WINDOWS_EMULATED = """
import os as _os
import os.path as _ospath

_OS_LEVEL_CWD = _os.getcwd()
_real_realpath = _ospath.realpath
_real_join = _ospath.join
_real_normpath = _ospath.normpath


def _no_working_directory(*_args, **_kwargs):
    raise FileNotFoundError(2, "No such file or directory")


def _win_abspath(path):
    path = _os.fspath(path)
    if not _ospath.isabs(path):
        path = _real_join(_OS_LEVEL_CWD, path)
    return _real_normpath(path)


def _win_realpath(path, *_args, **_kwargs):
    _os.getcwd()
    return _real_realpath(path, *_args, **_kwargs)


_ospath.abspath = _win_abspath
_ospath.realpath = _win_realpath
_os.getcwd = _no_working_directory
"""

# The measured answer to "which worlds kill inspect.stack()", PER PLATFORM.
#
# This table used to be one universal shape asserting SURVIVED / SURVIVED /
# DIED, and it went red on the real Windows runner — correctly. The control was
# built to refuse a POSIX expectation passing silently where it is false, and
# the first platform it met was the one that proved it necessary. Encoding a
# measurement from one OS as a property of the interpreter is the same mistake
# as the one the pins in this file exist to catch, one level up.
EXPECTED_WORLD_VERDICTS = (
    {"getcwd-denied": "DIED", "realpath-denied": "DIED", "ntpath-shaped": "DIED"}
    if os.name == "nt"
    else {"getcwd-denied": "SURVIVED", "realpath-denied": "SURVIVED", "ntpath-shaped": "DIED"}
)

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


WORLDS = [
    pytest.param(_INJECT_DEAD_CWD, id="getcwd-denied"),
    pytest.param(_DENY_REALPATH, id="realpath-denied"),
]

# The import-crash pins above use WORLDS. The caller-attribution pins below need
# a third, because the two above are both too hostile to reach the call that
# breaks — see _NTPATH_SHAPED. Kept as a separate list rather than appended, so
# that nobody widens the import pins onto a world where getcwd works and quietly
# stops testing the thing those pins exist for.
ATTRIBUTION_WORLDS = WORLDS + [pytest.param(_NTPATH_SHAPED, id="ntpath-shaped")]


@pytest.mark.parametrize("world", WORLDS)
class TestDeadCwd:
    """@memory's condition: the working directory cannot be read and something imports.

    Run in BOTH worlds, because one of them was invisible here. getcwd-denied is
    the condition as stated. realpath-denied is the same denial reaching the call
    Windows actually makes — ntpath.realpath asks for the working directory
    unconditionally, and inspect's getmodule calls it outside a try. Against the
    pre-cure guard the realpath world is red on Linux and the getcwd world is
    green; that difference IS the reason the Windows gate found this and eleven
    Linux runs did not.
    """

    def test_the_resolver_answers_without_a_working_directory(self, world):
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path("/no/such/src/aipass/x/a.py")))
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "ANSWER" in result.stdout, result.stderr

    def test_the_logger_can_be_built_without_a_working_directory(self, world):
        """The end-to-end case, and the one @memory's traceback could not reach.

        Their caller was a real absolute file, so resolution of the CALLER path
        succeeded and the walk got as far as load.py. Run from a pseudo-filename
        — a heredoc, an embedded interpreter, any `<stdin>` caller — and
        introspection.detect_branch_from_path resolves a RELATIVE path first and
        dies one frame earlier.
        """
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.modules.logger import get_system_logger
            print("LOGGER", get_system_logger().name)
            """,
        )
        assert result.returncode == 0, result.stderr
        assert "LOGGER" in result.stdout, result.stderr

    def test_the_fallback_path_is_the_one_being_exercised(self, world):
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
            world=world,
            body="""
            from aipass.prax.apps.handlers import repo_root
            from pathlib import Path
            print("ANSWER", repo_root.find_repo_root(Path(repo_root.__file__)))
            """,
        )
        assert result.returncode == 0, result.stderr
        assert _answer(result).split(" ", 1)[1] == str(repo_root_mod.source_root())

    def test_the_system_logs_dir_resolves_without_a_working_directory(self, world):
        result = _run_without_a_working_directory(
            world=world,
            body="""
            from aipass.prax.apps.handlers.config.load import get_system_logs_dir
            print("LOGS", get_system_logs_dir())
            """,
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
        # Deliberately NOT skipped. A module in prax's own tree that will not
        # parse is a hole in this sweep, and a sweep that skips its holes reports
        # the same green as a sweep that found nothing wrong. @canary made the
        # same call this morning after a SyntaxError mutant scored as a SURVIVOR:
        # an instrument that produced no reading must never be graded as a pass.
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError) as exc:
            raise AssertionError(f"{path} could not be parsed, so this sweep cannot see it: {exc}") from exc
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


# =============================================================================
# THE STACK WALK ITSELF — a structural instrument, because no import-shaped
# pin can reach the branch the deleted walk lived in
# =============================================================================


def _inspect_stack_calls(tree: ast.AST) -> list:
    """Every ``inspect.stack()`` CALL in a parsed module, by line number.

    A call, never a spelling. The guard's own docstring names ``inspect.stack()``
    three times while explaining why it must not be used, so a string ban would
    convict the explanation and force the cure to be undocumented — the
    instrument would be arguing against the record it depends on.
    """
    return sorted(
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "stack"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "inspect"
    )


def _docstrings(tree: ast.AST) -> list:
    """Every docstring in a parsed module — module, class and function."""
    return [
        ast.get_docstring(node)
        for node in ast.walk(tree)
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        and ast.get_docstring(node)
    ]


def _tree_modules() -> list:
    """Every live module under apps/, excluding archives and bytecode."""
    return [
        path
        for path in sorted(APPS_DIR.rglob("*.py"))
        if ".archive" not in path.parts and "__pycache__" not in path.parts
    ]


class TestNothingCallsInspectStack:
    """`inspect.stack()` is banned across apps/, and the ban is a CALL match.

    WHY A STRUCTURAL PIN AND NOT A BEHAVIOURAL ONE. @devpulse measured this
    across six branches: the guard's `caller_file is None` branch — where the
    deleted second walk lived — is UNREACHABLE from any import-shaped pin,
    because apps/__init__ always supplies a real-file frame. @aipass ran the
    experiment: restoring the walk left 1118 of 1120 tests green, and only the
    AST assertions died. So every dead-cwd pin in this file could stay green
    while somebody regrows the exact call that took Windows CI down.

    WHY THE BAN IS TREE-WIDE rather than scoped to the guard. After this round's
    two cures (config/load.py's log-dir resolver and json_handler's caller
    attribution) prax has no legitimate caller left, so the wider ban costs
    nothing and catches the next one wherever it lands. `inspect.currentframe()`
    is deliberately NOT banned: it is `sys._getframe` under another name and
    touches no filesystem.

    THE MECHANISM, for whoever reads this after the next regression.
    `inspect.stack()` builds a FrameInfo per frame -> getsourcefile() ->
    getmodule() -> `modulesbyfile[os.path.realpath(f)]`, and that realpath is
    not inside a try. On Windows `ntpath.realpath` calls `os.getcwd()`
    unconditionally on its first lines, before it checks whether the path is
    even absolute. So the whole call needs a readable working directory, on
    Windows, before any of the caller's own code runs.
    """

    def test_no_module_under_apps_calls_inspect_stack(self):
        offenders = {}
        for path in _tree_modules():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            lines = _inspect_stack_calls(tree)
            if lines:
                offenders[_module_key(path.relative_to(APPS_DIR.parent))] = lines
        assert not offenders, (
            "inspect.stack() needs a readable working directory on Windows and dies at import "
            f"in a process that has none. Use sys._getframe(n).f_code.co_filename: {offenders}"
        )

    def test_the_walk_actually_parsed_something(self):
        """Negative control for the sweep: a blinded walk reads clean too.

        The pin above is a proof of absence, and a proof of absence from an
        instrument that looked nowhere is worth nothing. This asserts the walk
        found a real tree before its silence is allowed to mean anything.
        """
        modules = _tree_modules()
        assert len(modules) > 50, (
            f"the apps/ walk found only {len(modules)} modules — the sweep above is reading a "
            "tree that is not there, so its green is vacuous"
        )

    def test_the_matcher_convicts_a_planted_call_at_the_right_line(self, tmp_path):
        """Positive control, through the REAL matcher rather than a copy of it."""
        planted = tmp_path / "planted.py"
        planted.write_text("import inspect\n\n\ndef f():\n    return inspect.stack()[1]\n")
        assert _inspect_stack_calls(ast.parse(planted.read_text())) == [5]

    def test_the_matcher_does_not_convict_the_docstring_that_explains_the_ban(self):
        """The guard's docstring says `inspect.stack()` and must stay legal.

        This is the pin that makes the ban survivable. A spelling ban would make
        the cure's own explanation illegal, and the next person would delete the
        explanation rather than the defect.

        REBUILT 2026-08-31 after @spawn caught the same shape in their tree and
        @devpulse relayed it. The first version asserted the whole live guard
        file was clean — which is a SECOND COPY OF THE BAN wearing a control's
        name. It proved it in my own mutant run: regrowing the walk redded this
        test too, and I reported that as a bonus kill when it was the control
        failing for the ban's reason. A control that can fail for the reason it
        is controlling for is not a control.

        So the fixture is the guard's REAL docstrings and nothing else, lifted
        by ast and re-emitted as string literals. That module contains no calls
        by construction, so regrowing the walk cannot touch this test — and it
        still uses live prose, so it expires the day the explanation is deleted.
        """
        guard = APPS_DIR / "handlers" / "__init__.py"
        tree = ast.parse(guard.read_text(encoding="utf-8"))
        mentions = [text for text in _docstrings(tree) if "inspect.stack()" in text]
        assert mentions, (
            "the guard no longer explains why it does not use inspect.stack() — if the "
            "explanation was removed to satisfy a checker, the checker is the defect"
        )
        prose_only = "\n".join(repr(text) for text in mentions)
        assert _inspect_stack_calls(ast.parse(prose_only)) == []

    @pytest.mark.parametrize(
        "source",
        [
            pytest.param("import numpy\n\nx = numpy.stack([1, 2])\n", id="numpy.stack"),
            pytest.param("import traceback\n\nx = traceback.stack()\n", id="traceback.stack"),
            pytest.param("x = self.stack()\n", id="self.stack"),
            pytest.param("import inspect\n\nx = inspect.currentframe()\n", id="inspect.currentframe"),
        ],
    )
    def test_the_matcher_clears_things_that_only_look_like_it(self, source):
        """Somebody else's `.stack` is not this defect. Convicting it teaches
        branches to route around the instrument, which is how a checker dies."""
        assert _inspect_stack_calls(ast.parse(source)) == []


class TestCallerAttributionWithoutAWorkingDirectory:
    """The two `inspect.stack()` sites this round cured, pinned by BEHAVIOUR.

    Both were found by peers running prax in their own denied worlds — @memory
    and @trigger independently, on the same morning. Neither was fatal on Linux
    and one was not fatal anywhere, which is exactly why they needed pins that
    do not depend on a crash.
    """

    def test_the_ntpath_shaped_world_actually_kills_a_stack_walk(self):
        """Negative control FOR the positive controls: is each world hostile?

        Written after measuring, not before, and the measurement corrected me.
        A bare inspect.stack() in each world:

            getcwd-denied            -> SURVIVES
            getcwd + realpath denied -> SURVIVES
            realpath denied alone    -> DIES

        So the two worlds this file already had could never have convicted a
        stack walk, and the pins that went red against the pre-cure guard were
        reading the module-level Path(__file__).resolve() next door. Without
        this control the two pins below would pass in two of three worlds for a
        reason unrelated to what they claim to measure.
        """
        verdicts = {}
        for world, name in (
            (_INJECT_DEAD_CWD, "getcwd-denied"),
            (_DENY_REALPATH, "realpath-denied"),
            (_NTPATH_SHAPED, "ntpath-shaped"),
        ):
            probe = subprocess.run(
                [sys.executable, "-"],
                input=world
                + textwrap.dedent(
                    """
                    import inspect

                    try:
                        inspect.stack()
                        print("SURVIVED")
                    except BaseException:
                        print("DIED")
                    """
                ),
                capture_output=True,
                text=True,
                timeout=120,
            )
            verdicts[name] = probe.stdout.strip()

        assert verdicts == EXPECTED_WORLD_VERDICTS, (
            f"the worlds no longer bite the way {os.name} was measured to bite. Expected "
            f"{EXPECTED_WORLD_VERDICTS}, got {verdicts}. If the new reading is real, re-derive the "
            "table from measurement rather than relaxing the assertion — this control exists to "
            "refuse a platform's expectation being carried onto a platform where it is false."
        )

    @pytest.mark.parametrize("world", ATTRIBUTION_WORLDS)
    def test_the_log_dir_resolver_names_its_caller_without_a_cwd(self, world):
        """config/load.py's `get_module_logs_dir()` with no module_name.

        This one was NOT caught and NOT logged — a bare `inspect.stack()[1]` in
        the primary local-log-directory resolver. On a Windows box whose cwd is
        gone it raises, from the logging path, at the moment logging is the only
        thing that could tell anyone what went wrong.
        """
        result = _run_without_a_working_directory(
            """
            import os
            import tempfile

            os.environ.setdefault("AIPASS_TEST_LOG_DIR", tempfile.mkdtemp(prefix="prax_probe_logs_"))
            from aipass.prax.apps.handlers.config.load import get_module_logs_dir

            print("LOGDIR", get_module_logs_dir().name)
            """,
            world=world,
        )
        assert result.returncode == 0, (
            "get_module_logs_dir() could not name its caller without a working directory.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # <stdin> is the caller here, so the stem is 'stdin' — the point is that a
        # name was derived at all, from a frame rather than from the filesystem.
        assert "LOGDIR " in result.stdout, f"no directory came back: {result.stdout}"

    @pytest.mark.parametrize("world", ATTRIBUTION_WORLDS)
    def test_the_operations_log_still_attributes_its_caller(self, world):
        """json_handler's `_get_caller_module_name`.

        Guarded and logged, so it survives — and records every operation as
        "unknown". @trigger saw it twice in a single import chain. Degraded is
        not cured: the audit log stops naming anyone exactly when a machine is
        in the state that makes the log worth reading.

        THE CALLER IS A REAL FILE ON DISK, written for this probe, and that is
        load-bearing in two directions. It has to be real, because after the
        pseudo-frame cure "unknown" is the CORRECT answer for a `<stdin>`
        caller — so a stdin caller leaves this pin unable to tell a frame with
        no module from a frame read that failed, which is the whole claim. And
        it must not be the ONLY frame: @commons measured that a stack of purely
        on-disk frames makes getsourcefile early-return before getmodule, so the
        realpath denial goes inert. The probe itself still runs from stdin, so
        that frame stays on the stack and inspect still reaches the unguarded
        call. Real name available, world still hostile.
        """
        result = _run_without_a_working_directory(
            """
            import sys
            import tempfile
            from pathlib import Path

            CALLER_SOURCE = [
                "from aipass.prax.apps.handlers.json import json_handler",
                "",
                "",
                "def stands_in_for_log_operation():",
                "    return json_handler._get_caller_module_name()",
                "",
                "",
                "def ask():",
                "    # Two levels: _get_caller_module_name skips [0]=itself and",
                "    # [1]=log_operation to reach [2], the real caller.",
                "    return stands_in_for_log_operation()",
            ]

            caller_dir = Path(tempfile.mkdtemp(prefix="prax_caller_"))
            (caller_dir / "a_real_caller.py").write_text(chr(10).join(CALLER_SOURCE), encoding="utf-8")
            sys.path.insert(0, str(caller_dir))

            import a_real_caller

            print("CALLER", a_real_caller.ask())
            """,
            world=world,
        )
        assert result.returncode == 0, (
            f"importing json_handler died without a working directory.\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "CALLER a_real_caller" in result.stdout, (
            "the caller was not attributed to the real file that asked — either the frame read "
            f"needed a working directory and threw the answer away, or it named the wrong "
            f"frame.\nstdout: {result.stdout}"
        )


class TestTheGuardsUndeterminableCallerBranch:
    """The `caller_file is None` branch, pinned by BEHAVIOUR as well as by AST.

    @devpulse's round-4 guidance said this branch is unreachable and only a
    structural ban can watch it. @spawn measured the correction and it is worth
    stating precisely, because I repeated the too-strong version: the branch is
    unreachable from IMPORT-shaped pins — apps/__init__ always supplies a
    real-file frame — but it IS reachable by calling `_guard_branch_access()`
    from a child whose every frame is a string pseudo-file or importlib. All of
    those are skipped, `_find_real_caller` returns None, and the branch runs.

    So the true sentence is "import-shaped pins cannot reach it", not "nothing
    can". The AST ban stays: it needs no subprocess and names the defect at its
    line. This is its sibling, and the two die together.
    """

    def _child(self, body: str):
        """Run `body` with realpath denied, in a `-c` child.

        `-c`, not a script file, and that is @commons' lesson rather than a
        style choice: run the probe as a real file on disk and EVERY frame
        getsourcefile sees exists, so it early-returns before getmodule and the
        denial is silently inert. The world would be spelled too realistically
        to bite.
        """
        script = (
            _NTPATH_SHAPED
            + textwrap.dedent(
                f"""
                import sys
                sys.path.insert(0, {REPO_SRC!r})
                """
            )
            + textwrap.dedent(body)
        )
        return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True, timeout=120)

    def test_the_branch_is_reachable_and_the_guard_returns_from_it(self):
        """Both arming probes, then the claim — in that order, in one child.

        Probe 1 proves the denial bites in THIS process shape (a `-c` child, not
        the stdin shape the rest of this file uses). Probe 2 proves
        `_find_real_caller` actually returned None, so a future change cannot
        quietly route the test down the ordinary caller path and still pass.
        Only then is the guard called.
        """
        result = self._child(
            """
            import inspect

            from aipass.prax.apps import handlers

            # ARMING PROBE 1 — is the world hostile at all?
            try:
                inspect.stack()
                print("ARM1 INERT")
            except BaseException:
                print("ARM1 BITES")

            # ARMING PROBE 2 — does the branch under test actually run?
            print("ARM2", handlers._find_real_caller())

            # THE CLAIM.
            handlers._guard_branch_access()
            print("GUARD RETURNED")
            """
        )
        assert "ARM1 BITES" in result.stdout, (
            "the realpath denial is inert in a -c child, so this test proves nothing about a "
            f"stack walk.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert "ARM2 (None, None)" in result.stdout, (
            "_find_real_caller found a caller, so the undeterminable-caller branch never ran and "
            f"the claim below is about a different code path.\nstdout: {result.stdout}"
        )
        assert "GUARD RETURNED" in result.stdout, (
            "the guard did not return from its undeterminable-caller branch in a process with no "
            f"usable realpath.\nstdout: {result.stdout}\nstderr: {result.stderr}"
        )
        assert result.returncode == 0, f"child exited {result.returncode}: {result.stderr}"


# Characters Windows refuses in a path component. Checked on every platform,
# because the point is that a name derived here must be creatable EVERYWHERE —
# Linux will happily make a directory called `<stdin>` and did, dozens of times,
# before anyone noticed.
_WINDOWS_RESERVED_CHARS = set('<>:"|?*')


class TestACallerNameIsNotAlwaysAModuleName:
    """A frame's co_filename is not always a file, and never automatically a name.

    FOUND BY THE WINDOWS RUNNER, 2026-08-31 (run 33431848734, @devpulse). Three
    parametrised worlds of test_the_log_dir_resolver_names_its_caller_without_a_cwd
    went red there and none of them went red here, and the working directory
    turned out to have nothing to do with it.

    `get_module_logs_dir()` derives its caller's module name from a frame and
    then MKDIRS it. From `python -c`, from stdin, from an eval or a frozen
    loader, that frame's co_filename is a pseudo-filename — `<stdin>`,
    `<string>`, `<frozen importlib._bootstrap>` — and `Path("<stdin>").stem` is
    `<stdin>`. On Linux that silently creates a directory called `<stdin>`; I
    found ten of them on this machine, made by these very pins. On Windows `<`
    and `>` are reserved and mkdir raises, from the logging path, which is
    exactly where an unhandled raise is worst.

    So the defect is not the working directory and it is not new — the old
    `inspect.stack()[1]` read the same co_filename and had the same hole. The
    round-4 pin is simply the first thing that ever called this from a
    pseudo-frame on a platform that objects.

    THE RULE: a pseudo-frame has no module behind it, so it gets the same answer
    as no caller at all. Guessing a name from `<...>` is worse than admitting
    there is none — it invents an attribution AND builds a directory for it.
    """

    def test_the_log_dir_from_a_pseudo_frame_is_creatable_on_every_platform(self):
        """The claim the Windows runner actually made, checkable here."""
        result = _run_without_a_working_directory(
            """
            import os
            import tempfile

            os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="prax_probe_logs_")
            from aipass.prax.apps.handlers.config.load import get_module_logs_dir

            print("LOGDIR", get_module_logs_dir().name)
            """,
            world=_NTPATH_SHAPED,
        )
        assert result.returncode == 0, f"probe died: {result.stdout}\n{result.stderr}"
        name = _answer(result).split("LOGDIR ", 1)[1]
        offending = sorted(_WINDOWS_RESERVED_CHARS & set(name))
        assert not offending, (
            f"get_module_logs_dir() derived the directory name {name!r} from a pseudo-frame and "
            f"created it. Windows refuses {offending} in a path component, so this raises there — "
            "from the logging path. A frame with no file behind it has no module name to give."
        )

    def test_the_operations_log_does_not_attribute_to_a_pseudo_frame(self):
        """json_handler reads the same co_filename and had the same hole.

        Less damaging — it names a record rather than creating a directory — but
        an operations log that attributes work to `<stdin>` is asserting
        something false about who did it.
        """
        result = _run_without_a_working_directory(
            """
            from aipass.prax.apps.handlers.json import json_handler


            def stands_in_for_log_operation():
                return json_handler._get_caller_module_name()


            def the_actual_caller():
                return stands_in_for_log_operation()


            print("CALLER", the_actual_caller())
            """,
            world=_NTPATH_SHAPED,
        )
        assert result.returncode == 0, f"probe died: {result.stdout}\n{result.stderr}"
        name = _answer(result).split("CALLER ", 1)[1]
        assert not (_WINDOWS_RESERVED_CHARS & set(name)), (
            f"the operations log attributed an entry to {name!r} — a pseudo-frame is not a module, "
            "and 'unknown' is the honest answer where there is nobody to name"
        )

    @pytest.mark.skipif(os.name == "nt", reason="on Windows this world IS the platform, not an emulation")
    def test_the_windows_emulation_reproduces_the_measured_windows_table(self):
        """The emulation is only worth having if it reads like the real runner.

        prax has no Windows box, so every Windows claim here is made through
        _WINDOWS_EMULATED. This asserts that world produces the table @devpulse
        measured on run 33431848734 — all three worlds convicting — rather than
        the POSIX table. Without it the emulation is an assertion about ntpath
        wearing the clothes of a measurement.
        """
        verdicts = {}
        for world, name in (
            (_INJECT_DEAD_CWD, "getcwd-denied"),
            (_DENY_REALPATH, "realpath-denied"),
            (_NTPATH_SHAPED, "ntpath-shaped"),
        ):
            # The emulation goes FIRST: it captures the real cwd before any
            # world takes getcwd away, which is what Win32 _getfullpathname has
            # and a patched os.getcwd does not.
            probe = subprocess.run(
                [sys.executable, "-"],
                input=_WINDOWS_EMULATED
                + world
                + textwrap.dedent(
                    """
                    import inspect

                    try:
                        inspect.stack()
                        print("SURVIVED")
                    except BaseException:
                        print("DIED")
                    """
                ),
                capture_output=True,
                text=True,
                timeout=120,
            )
            verdicts[name] = _answer(probe)

        assert verdicts == {
            "getcwd-denied": "DIED",
            "realpath-denied": "DIED",
            "ntpath-shaped": "DIED",
        }, f"the Windows emulation does not read like the Windows runner did: {verdicts}"
