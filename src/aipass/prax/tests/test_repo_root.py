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
from pathlib import Path


from aipass.prax.apps.handlers import repo_root as repo_root_mod


APPS_DIR = Path(repo_root_mod.__file__).resolve().parents[1]
REPO_SRC = str(Path(repo_root_mod.__file__).resolve().parents[5])


def _run_with_dead_cwd(body: str) -> subprocess.CompletedProcess:
    """Run a snippet in a process whose working directory has been deleted."""
    script = textwrap.dedent(
        f"""
        import os, shutil, sys, tempfile
        _d = tempfile.mkdtemp()
        os.chdir(_d)
        shutil.rmtree(_d)
        try:
            os.getcwd()
            print("INVALID-PROBE: cwd still alive")
            raise SystemExit(3)
        except OSError:
            pass
        sys.path.insert(0, {REPO_SRC!r})
        """
    ) + textwrap.dedent(body)
    # Fed on STDIN, not with -c, and that detail is the test. A `-c` caller
    # produces no usable stack filename so introspection bails early; a `<stdin>`
    # caller produces a RELATIVE pseudo-filename, which is exactly what
    # detect_branch_from_path then hands to resolve().
    return subprocess.run([sys.executable, "-"], input=script, capture_output=True, text=True, timeout=120)


# =============================================================================
# THE SHARED RESOLVER
# =============================================================================


class TestSourceRoot:
    """The fallback is derived from the FILE, and nothing else."""

    def test_the_directory_containing_src_is_the_checkout(self):
        assert repo_root_mod.source_root(Path("/x/checkout/src/aipass/prax/a.py")) == Path("/x/checkout")

    def test_no_src_component_falls_to_the_filesystem_root(self):
        """Defined, incapable of raising, and absurd enough to fail loudly.

        A plausible-looking answer here is worse than an absurd one: it would
        resolve quietly into somebody's home directory.
        """
        assert repo_root_mod.source_root(Path("/nowhere/at/all/a.py")) == Path("/")

    def test_a_relative_start_is_refused_not_resolved(self):
        """Resolving it would read the working directory this module exists to avoid."""
        assert repo_root_mod.source_root(Path("relative/a.py")) == repo_root_mod.source_root()


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
        result = _run_with_dead_cwd(
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
        result = _run_with_dead_cwd(
            """
            from aipass.prax.apps.modules.logger import get_system_logger
            print("LOGGER", get_system_logger().name)
            """
        )
        assert result.returncode == 0, result.stderr
        assert "LOGGER" in result.stdout, result.stderr

    def test_the_system_logs_dir_resolves_without_a_working_directory(self):
        result = _run_with_dead_cwd(
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


# =============================================================================
# THE SWEEP — no ninth copy
# =============================================================================

# The single sanctioned working-directory read in prax: `drone @prax dashboard
# refresh` with no argument means "the branch I am standing in", and the cwd IS
# the question there rather than a fallback for a question it could not answer.
CWD_ALLOWLIST = {"apps/modules/dashboard.py"}


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
            found[str(path.relative_to(root.parent))] = lines
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
                    private.setdefault(str(path.relative_to(APPS_DIR.parent)), []).append(node.lineno)
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
