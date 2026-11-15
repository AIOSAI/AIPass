# =================== AIPass ====================
# Name: test_install.py
# Description: Tests for aipass install — one-command bootstrap (DPLAN-0233)
# Version: 1.8.0
# Created: 2026-07-05
# Modified: 2026-11-15
# =============================================

"""Tests for apps/modules/install.py (DPLAN-0233) and the install command it drives."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that every module this file imports parses and imports

import io
import json
import os
import shlex
import subprocess as _sp
import sys
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from aipass.aipass.apps.handlers.ui.progress import GLYPH_FAIL, GLYPH_PASS, GLYPH_WARN
from aipass.aipass.apps.modules import doctor, install as _install
from aipass.aipass.apps.modules.doctor import CheckResult
from aipass.aipass.apps.modules._doctor_wire import DECLINED_WARNING, NOT_APPLIED_NON_INTERACTIVE
from aipass.aipass.tests.support_doctor import _home_at
from aipass.aipass.apps.modules.install import (
    DEFAULT_HOME,
    REPO_URL,
    TOTAL_STEPS,
    SourceRefused,
    acquire_install_lock,
    _check_and_fix_owner,
    _clone_repo,
    install_lock_path,
    _install_phone_face,
    _looks_like_aipass_tree,
    release_install_lock,
    _resolve_home,
    _resolve_source,
    _run_setup,
    handle_command,
    install_report_path,
    print_help,
    print_introspection,
    run_finish,
    run_install,
    wake_command,
)

_MOD = "aipass.aipass.apps.modules.install"
# The trigger object install fires on: _fire_lock_removed imports it from here at call time.
_BUS = "aipass.trigger.apps.modules.core.trigger"


@pytest.fixture(autouse=True)
def phone_face_step_stays_offline():
    """No test in this file runs the real Phone face + baud-cli step, or reaches the network.

    Unstubbed, step 4 installs into the real ~/.aipass/baud and points the live api at it.
    A network call fails at teardown: the step swallows exceptions, so a raise would pass.
    The phone print's reader is stubbed too, or it probes this host's tailscale and @api.
    """
    with (
        patch("aipass.aipass.apps.modules.baud.install_best_effort", return_value=False) as step,
        patch(f"{_MOD}._phone_print", return_value=None),
        patch("urllib.request.urlopen") as network,
    ):
        yield step
    assert not network.called, f"a test reached the network: {network.call_args_list}"


_REAL_PREFLIGHT = doctor.run_doctor_preflight


@pytest.fixture(autouse=True)
def doctor_stays_stubbed(monkeypatch):
    """Step 5's doctor --fix is stubbed: unstubbed it reads and rewires this host's provider settings."""
    calls: list[dict] = []
    monkeypatch.setattr(
        doctor,
        "run_doctor_preflight",
        lambda non_interactive=False, yes=False: (
            calls.append({"non_interactive": non_interactive, "yes": yes}) or ({}, (0, 0, 0))
        ),
    )
    return calls


_REAL_RUN = _sp.run


def _the_homes_aipass(argv, **_kw) -> _sp.CompletedProcess:
    """The home's `aipass doctor ...` answered in this process: doctor's own handle_command reads the argv."""
    try:
        doctor.handle_command("doctor", argv[1:])
    except SystemExit as exc:
        return _sp.CompletedProcess(argv, int(exc.code or 0))
    return _sp.CompletedProcess(argv, 0)


@pytest.fixture(autouse=True)
def homes_doctor(monkeypatch) -> list:
    """Step 5 runs `<home>/.venv/bin/aipass doctor`; that one process is answered in-process, the rest run.

    Returns each doctor call as (argv, kwargs).
    """
    calls: list = []

    def run(argv, **kw):
        if Path(argv[0]).parts[-3:] == (".venv", "bin", "aipass"):
            calls.append((argv, kw))
            return _the_homes_aipass(argv, **kw)
        return _REAL_RUN(argv, **kw)

    monkeypatch.setattr(_sp, "run", run)
    return calls


def _installed_in(home: Path, monkeypatch) -> None:
    """install.py reads as inside `home`, an install from the home's own venv: the lock event fires in-process."""
    monkeypatch.setattr(_install, "__file__", str(home / "x" / "install.py"))


class TestLooksLikeAipassTree:
    """Detecting whether a directory already holds an AIPass source tree."""

    def test_setup_sh_and_aipass_registry_present(self, tmp_path: Path) -> None:
        """A directory with setup.sh and AIPASS_REGISTRY.json reads as an AIPass tree."""
        _aipass_tree(tmp_path)
        assert _looks_like_aipass_tree(tmp_path) is True

    def test_setup_sh_alone_is_not_a_tree(self, tmp_path: Path) -> None:
        """Any project with a setup.sh is not an AIPass home."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        assert _looks_like_aipass_tree(tmp_path) is False

    def test_project_registry_is_not_a_tree(self, tmp_path: Path) -> None:
        """A user project (setup.sh + MYPROJ_REGISTRY.json) is not the AIPass home."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        (tmp_path / "MYPROJ_REGISTRY.json").write_text("{}", encoding="utf-8")
        assert _looks_like_aipass_tree(tmp_path) is False

    def test_empty_dir(self, tmp_path: Path) -> None:
        """An empty directory is not an AIPass tree."""
        assert _looks_like_aipass_tree(tmp_path) is False

    def test_missing_dir(self, tmp_path: Path) -> None:
        """A non-existent path is not an AIPass tree."""
        assert _looks_like_aipass_tree(tmp_path / "nope") is False


class TestResolveHome:
    """Resolving the install home from flags, env, and defaults."""

    def test_here_returns_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """--here resolves to the current working directory, the real one (monkeypatch.chdir)."""
        monkeypatch.chdir(tmp_path)
        assert _resolve_home(None, here=True, non_interactive=False) == tmp_path.resolve()

    def test_explicit_path(self, tmp_path: Path) -> None:
        """An explicit --path is expanded and resolved."""
        target = tmp_path / "tools" / "aipass"
        assert _resolve_home(str(target), here=False, non_interactive=False) == target.resolve()

    def test_non_interactive_defaults(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """From an ordinary directory, non-interactive still falls back to DEFAULT_HOME.

        cwd is pinned explicitly: it is load-bearing.
        """
        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == DEFAULT_HOME.resolve()

    def test_non_interactive_honours_an_aipass_cwd(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Standing in an AIPass tree, a headless install targets THAT tree.

        Pins: a headless install inside a checkout went to ~/AIPass instead.
        """
        _aipass_tree(tmp_path)
        monkeypatch.chdir(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": ""}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == tmp_path.resolve()

    def test_uses_valid_env(self, tmp_path: Path) -> None:
        """A valid AIPASS_HOME pointing at a real tree is honoured."""
        _aipass_tree(tmp_path)
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == tmp_path.resolve()

    def test_ignores_invalid_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """An AIPASS_HOME that is not an AIPass tree is ignored for the default."""
        elsewhere = tmp_path / "not_a_tree"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)
        with patch.dict("os.environ", {"AIPASS_HOME": str(tmp_path)}, clear=False):
            assert _resolve_home(None, here=False, non_interactive=True) == DEFAULT_HOME.resolve()


class TestInstallLock:
    """The concurrent-install lock.

    Before 2026-09-07 (FPLAN-0492 wave 6) there was no lock at all: a second
    install of the same home raced the first through clone and setup.sh and
    died somewhere in the middle without ever naming the conflict.
    """

    def test_lock_lives_beside_home_not_inside_it(self, tmp_path: Path) -> None:
        """The lock must not live in a directory the clone has yet to create."""
        home = tmp_path / "AIPass"
        lock = install_lock_path(home)
        assert lock.parent == tmp_path
        assert home not in lock.parents

    def test_second_install_refuses_naming_the_lock(self, tmp_path: Path) -> None:
        """A live holder makes the second attempt refuse, naming lock and pid.

        Mutant: `return lock` -> `return lock.parent` (the claim hands back the wrong path) -> red.
        """
        home = tmp_path / "AIPass"
        first = acquire_install_lock(home)
        assert first == install_lock_path(home)

        with patch(f"{_MOD}.error") as err:
            second = acquire_install_lock(home)

        assert second is None
        message = err.call_args[0][0]
        assert str(install_lock_path(home)) in message
        assert str(os.getpid()) in message

    def test_release_frees_the_home(self, tmp_path: Path, monkeypatch) -> None:
        """After release the next install can claim it, and the removal is announced once.

        Mutant: `"install_lock_released"` -> `"released"` in release_install_lock -> red.
        Mutant: the in-home check inverted -> the in-process fire never runs -> red.
        """
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        lock = acquire_install_lock(home)
        with patch(_BUS) as bus:
            release_install_lock(lock)
        bus.fire.assert_called_once_with(
            "file_deleted", path=str(install_lock_path(home)), reason="install_lock_released"
        )
        assert not install_lock_path(home).exists()
        assert acquire_install_lock(home) is not None

    def test_stale_lock_from_a_dead_pid_is_taken_over(self, tmp_path: Path, monkeypatch) -> None:
        """A crashed install must not wedge the home forever.

        Mutant: `return acquire_install_lock(home, _retry=False)` -> `return None` -> red.
        """
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        lock = install_lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999 2026-09-07T00:00:00+00:00\n", encoding="utf-8")

        with patch(f"{_MOD}._pid_alive", return_value=False), patch(_BUS) as bus:
            claimed = acquire_install_lock(home)

        bus.fire.assert_called_once_with("file_deleted", path=str(lock), reason="stale_install_lock_cleared")
        assert claimed == lock
        assert str(os.getpid()) in lock.read_text(encoding="utf-8")

    def test_live_holder_is_never_stolen(self, tmp_path: Path) -> None:
        """The counterfactual: a lock whose pid IS alive is left alone."""
        home = tmp_path / "AIPass"
        lock = install_lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("999999999 2026-09-07T00:00:00+00:00\n", encoding="utf-8")

        with patch(f"{_MOD}._pid_alive", return_value=True):
            with patch(f"{_MOD}.error"):
                assert acquire_install_lock(home) is None

        assert "999999999" in lock.read_text(encoding="utf-8")

    def test_holder_with_no_readable_pid_is_never_stolen(self, tmp_path: Path) -> None:
        """A lock naming no pid is not a dead holder: the lock stays, and the refusal names it.

        Mutant: `if _retry and alive is False:` -> `if _retry and not alive:` -> red.
        """
        home = tmp_path / "AIPass"
        lock = install_lock_path(home)
        lock.parent.mkdir(parents=True, exist_ok=True)
        lock.write_text("garbage\n", encoding="utf-8")

        with patch(f"{_MOD}.error") as err, patch(_BUS) as bus:
            assert acquire_install_lock(home) is None

        bus.fire.assert_not_called()
        assert lock.read_text(encoding="utf-8") == "garbage\n"
        assert f"(lock: {lock})" in err.call_args[0][0]

    def test_a_bootstrap_outside_the_home_fires_through_the_homes_drone_from_the_home(self, tmp_path: Path) -> None:
        """Mutant: `cwd=str(home)` dropped -> the drone runs from pytest's cwd -> red."""
        home = tmp_path / "AIPass"
        record = tmp_path / "drone_argv.txt"
        drone = home / ".venv" / "bin" / "drone"
        drone.parent.mkdir(parents=True)
        drone.write_text(f'#!/bin/sh\n{{ pwd -P; printf "%s\\n" "$@"; }} > "{record}"\n', encoding="utf-8")
        drone.chmod(0o755)
        lock = acquire_install_lock(home)
        with patch(_BUS) as bus:
            release_install_lock(lock)
        bus.fire.assert_not_called()
        assert record.read_text(encoding="utf-8").splitlines() == [
            str(home.resolve()), "@trigger", "fire", "file_deleted", f"path={lock}", "reason=install_lock_released"
        ]  # fmt: skip

    def test_a_bootstrap_with_no_drone_yet_warns_and_fires_nothing(self, tmp_path: Path, caplog) -> None:
        """Mutant: the no-drone guard dropped -> the run fails on the missing file, another warning -> red."""
        home = tmp_path / "AIPass"
        lock = acquire_install_lock(home)
        with patch(_BUS) as bus, patch(f"{_MOD}.subprocess.run", wraps=_sp.run) as run:
            release_install_lock(lock)
        bus.fire.assert_not_called()
        run.assert_not_called()
        assert not lock.exists()
        drone = home / ".venv" / "bin" / "drone"
        assert f"[install] no drone at {drone} yet: file_deleted for {lock} not fired" in caplog.text


class TestCloneRepo:
    """Fetching the framework into the home via git clone."""

    def test_dry_run_no_subprocess(self, tmp_path: Path) -> None:
        """Dry-run reports success without shelling out."""
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path / "home", dry_run=True) is True
            run.assert_not_called()

    def test_refuses_non_empty_dir(self, tmp_path: Path) -> None:
        """A non-empty target is refused rather than clobbered."""
        (tmp_path / "existing.txt").write_text("x", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path, dry_run=False) is False
            run.assert_not_called()

    def test_missing_git(self, tmp_path: Path, tools_on_path) -> None:
        """Absent git means clone fails cleanly without calling subprocess. PATH holds no git."""
        tools_on_path()
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path / "home", dry_run=False) is False
            run.assert_not_called()

    def test_success(self, tmp_path: Path, tools_on_path) -> None:
        """A zero-exit git clone returns success, and clones exactly once. PATH holds a git.

        The argv handed to git is pinned whole: a shallow clone of the public repo into home.
        Mutant: `"--depth", "1", ` dropped from the clone argv -> red.
        """
        home = tmp_path / "home"
        tools_on_path("git")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _clone_repo(home, dry_run=False) is True
            clone_calls = [c for c in run.call_args_list if "clone" in c.args[0]]
            assert len(clone_calls) == 1
            assert clone_calls[0].args[0] == ["git", "clone", "--depth", "1", REPO_URL, str(home)]

    def test_nonzero_exit(self, tmp_path: Path, tools_on_path) -> None:
        """A non-zero git clone exit reports failure. PATH holds a git, so the lookup is not the cause."""
        tools_on_path("git")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=1)):
            assert _clone_repo(tmp_path / "home", dry_run=False) is False

    def test_a_failed_clone_says_so_before_the_log_line_that_could_raise(self, tmp_path, tools_on_path, capsys):
        """An unwritable log home must not be the last word on a failed clone (container proof, 2026-10-13).

        Mutant: the warning moved below logger.warning -> the PermissionError fires first, no line -> red.
        """
        tools_on_path("git")
        denied = PermissionError(13, "Permission denied", str(tmp_path / "system_logs"))
        with (
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=128)),
            patch(f"{_MOD}.logger.warning", side_effect=denied),
        ):
            with pytest.raises(PermissionError):
                _clone_repo(tmp_path / "home", dry_run=False)
        assert "git clone failed (exit 128) — git's own message is above" in capsys.readouterr().err


def _aipass_tree(home: Path) -> None:
    """Make `home` read as an AIPass tree: setup.sh and AIPASS_REGISTRY.json."""
    (home / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
    (home / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")


def _checkout(tmp_path: Path) -> Path:
    """A directory that reads as a checkout: a .git directory, made without running git (no git from this seat)."""
    repo = tmp_path / "checkout"
    (repo / ".git").mkdir(parents=True)
    (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    return repo


class TestSource:
    """--source (DPLAN-0408): clone from a local checkout's committed HEAD, or a URL, never a silent fall back."""

    def test_no_source_is_the_public_repo(self) -> None:
        assert _resolve_source(None) == REPO_URL

    @pytest.mark.parametrize("url", ["https://example.org/AIPass.git", "git@example.org:o/AIPass.git"])
    def test_a_url_is_cloned_as_given(self, url: str) -> None:
        assert _resolve_source(url) == url

    def test_a_local_checkout_is_cloned_through_file_uri(self, tmp_path: Path) -> None:
        """file:// keeps --depth 1 honoured and takes the committed HEAD only, never the working tree."""
        repo = _checkout(tmp_path)
        assert _resolve_source(str(repo)) == repo.resolve().as_uri()
        assert _resolve_source(str(repo)).startswith("file://")

    def test_a_worktree_whose_dot_git_is_a_file_is_a_checkout(self, tmp_path: Path) -> None:
        repo = tmp_path / "worktree"
        repo.mkdir()
        (repo / ".git").write_text("gitdir: elsewhere\n", encoding="utf-8")
        assert _resolve_source(str(repo)) == repo.resolve().as_uri()

    def test_refusals_name_the_path(self, tmp_path: Path) -> None:
        missing = tmp_path / "nowhere"
        plain = tmp_path / "plain"
        plain.mkdir()
        hollow = tmp_path / "hollow"
        (hollow / ".git").mkdir(parents=True)
        a_file = tmp_path / "file.txt"
        a_file.write_text("x", encoding="utf-8")
        cases = {
            str(missing): f"{missing} does not exist",
            str(plain): f"{plain} is not a repository (no .git, or an empty one)",
            str(hollow): f"{hollow} is not a repository (no .git, or an empty one)",
            str(a_file): f"{a_file} is not a directory",
            "": "it needs a path or a URL",
        }
        for given, words in cases.items():
            with pytest.raises(SourceRefused) as exc:
                _resolve_source(given)
            assert str(exc.value) == words

    def test_the_clone_argv_carries_the_source(self, tmp_path: Path, tools_on_path) -> None:
        """Shallow clone of the given source into the home. Mutant: the clone hard-codes REPO_URL -> red."""
        home = tmp_path / "home"
        uri = _checkout(tmp_path).resolve().as_uri()
        tools_on_path("git")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _clone_repo(home, dry_run=False, source=uri) is True
        clone_calls = [c for c in run.call_args_list if "clone" in c.args[0]]
        assert clone_calls[0].args[0] == ["git", "clone", "--depth", "1", uri, str(home)]

    def test_the_dry_run_names_the_source(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        uri = _checkout(tmp_path).resolve().as_uri()
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _clone_repo(tmp_path / "home", dry_run=True, source=uri) is True
        run.assert_not_called()
        assert f"would run: git clone --depth 1 {uri}" in " ".join(capsys.readouterr().out.split())

    def test_run_install_hands_the_resolved_source_to_the_clone(self, tmp_path: Path) -> None:
        """Mutant: --source parsed but not passed to the clone -> the public repo is cloned -> red."""
        repo = _checkout(tmp_path)
        home = tmp_path / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=False) as clone,
            patch(_BUS),
        ):
            rc = run_install(non_interactive=True, dry_run=False, source=str(repo))
        assert rc == 1
        clone.assert_called_once_with(home, False, source=repo.resolve().as_uri())

    def test_a_bad_source_is_refused_before_anything_is_made(self, tmp_path, capsys) -> None:
        """Exit 2 with the path named; no home resolved, no lock, no clone, no fall back to GitHub."""
        missing = tmp_path / "nowhere"
        with (
            patch(f"{_MOD}._resolve_home") as resolve,
            patch(f"{_MOD}._clone_repo") as clone,
        ):
            rc = run_install(non_interactive=True, dry_run=False, source=str(missing))
        assert rc == 2
        resolve.assert_not_called()
        clone.assert_not_called()
        assert f"--source refused: {missing} does not exist" in " ".join(capsys.readouterr().err.split())

    def test_handle_command_threads_source_and_refuses_a_valueless_one(self, tmp_path: Path) -> None:
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--source", str(tmp_path)])
            with pytest.raises(SystemExit):
                handle_command("install", [])
            with pytest.raises(SystemExit):
                handle_command("install", ["--source"])
        assert [c.kwargs["source"] for c in run.call_args_list] == [str(tmp_path), None, ""]

    def test_a_url_token_is_never_printed_or_logged(self, tmp_path: Path, capsys) -> None:
        """A --source URL's user:token@ is stripped from the printed Source line, the dry run and the log."""
        url = "https://user:s3cret-token@example.org/AIPass.git"
        with (
            patch(f"{_MOD}._resolve_home", return_value=tmp_path / "AIPass"),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._run_setup", return_value=False),
            patch(f"{_MOD}.json_handler", autospec=True) as jh,
        ):
            with pytest.raises(SystemExit):
                handle_command("install", ["--source", url, "--dry-run"])
        out = capsys.readouterr().out
        assert "s3cret-token" not in out + str(jh.log_operation.call_args_list)
        assert "https://example.org/AIPass.git" in out

    def test_the_help_lists_source(self, capsys: pytest.CaptureFixture[str]) -> None:
        print_help()
        printed = " ".join(capsys.readouterr().out.split())
        assert "aipass install --source PATH|URL" in printed
        assert "a local path clones its committed HEAD; for the install sandbox" in printed


class TestFlagSpellings:
    """DPLAN-0409 C3: every value flag reads `--flag value` and `--flag=value` alike, in one place."""

    @pytest.mark.parametrize(
        ("flag", "kwarg", "value"),
        [
            ("--path", "path", "/opt/aipass-home"),
            ("--baud-tag", "baud_tag", "v0.2.1"),
            ("--source", "source", "/src/a"),
        ],
    )
    def test_both_spellings_reach_run_install_with_the_same_value(self, flag: str, kwarg: str, value: str) -> None:
        """Mutant: the equals branch removed -> `--source=/x` clones the public repo -> red."""
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", [flag, value])
            with pytest.raises(SystemExit):
                handle_command("install", [f"{flag}={value}"])
        assert [c.kwargs[kwarg] for c in run.call_args_list] == [value, value]

    @pytest.mark.parametrize(
        ("given", "words"), [("--source=", "--source refused"), ("--baud-tag=", "--baud-tag refused")]
    )
    def test_an_empty_equals_value_is_refused_with_2_and_nothing_made(self, given, words, capsys) -> None:
        with (
            patch(f"{_MOD}._resolve_home") as resolve,
            patch(f"{_MOD}._clone_repo") as clone,
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command("install", [given])
        assert exc.value.code == 2
        resolve.assert_not_called()
        clone.assert_not_called()
        assert words in capsys.readouterr().err

    def test_absent_flags_keep_their_defaults(self) -> None:
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", [])
        kwargs = run.call_args.kwargs
        assert (kwargs["path"], kwargs["baud_tag"], kwargs["source"]) == (None, "latest", None)


class TestRunSetup:
    """Running the repo setup.sh."""

    def test_dry_run_no_subprocess(self, tmp_path: Path) -> None:
        """Dry-run reports success without running setup.sh."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run") as run:
            assert _run_setup(tmp_path, dry_run=True) is True
            run.assert_not_called()

    def test_missing_script(self, tmp_path: Path) -> None:
        """A missing setup.sh reports failure."""
        assert _run_setup(tmp_path, dry_run=False) is False

    def test_success(self, tmp_path: Path) -> None:
        """A zero-exit setup.sh returns success."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False) is True
            run.assert_called_once()

    def test_no_symlink_flag_forwarded(self, tmp_path: Path) -> None:
        """--no-symlink passes through to setup.sh (#660)."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, no_symlink=True) is True
        argv = run.call_args[0][0]
        assert "--no-symlink" in argv
        assert "--force-symlink" not in argv

    def test_force_symlink_flag_forwarded(self, tmp_path: Path) -> None:
        """--force-symlink passes through to setup.sh (#660)."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, force_symlink=True) is True
        argv = run.call_args[0][0]
        assert "--force-symlink" in argv

    def test_symlink_flags_absent_by_default(self, tmp_path: Path) -> None:
        """No symlink flags forwarded unless requested (#660), nothing exported. Mutant: env always a dict -> red."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False) is True
        argv = run.call_args[0][0]
        assert "--no-symlink" not in argv
        assert "--force-symlink" not in argv
        assert run.call_args.kwargs["stdin"] is None
        assert run.call_args.kwargs["env"] is None

    def test_non_interactive_closes_setups_stdin_and_says_so_in_its_env(self, tmp_path: Path) -> None:
        """setup.sh asks on [ -t 0 ]: under --non-interactive it gets no tty (container proof, 2026-10-13).

        Mutant: non_interactive not read -> the user's tty reaches setup.sh -> red.
        """
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, non_interactive=True) is True
        assert run.call_args.kwargs["stdin"] is _sp.DEVNULL
        assert run.call_args.kwargs["env"]["AIPASS_NON_INTERACTIVE"] == "1"

    def test_yes_exports_consent_to_setup_and_leaves_its_stdin_open(self, tmp_path: Path) -> None:
        """Mutant: `YES_ENV: "1"` keyed on non_interactive instead of yes -> red."""
        (tmp_path / "setup.sh").write_text("#!/usr/bin/env bash\n", encoding="utf-8")
        with patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run:
            assert _run_setup(tmp_path, dry_run=False, yes=True) is True
        env = run.call_args.kwargs["env"]
        assert env["AIPASS_YES"] == "1"
        assert "AIPASS_NON_INTERACTIVE" not in env
        assert run.call_args.kwargs["stdin"] is None

    def test_the_install_flag_reaches_setup(self, tmp_path: Path) -> None:
        """aipass install --non-interactive threads into the setup step. Mutant: the call drops the flag -> red."""
        home = tmp_path / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=True),
            patch(f"{_MOD}._run_setup", return_value=False) as setup,
            patch(_BUS),
        ):
            run_install(non_interactive=True, dry_run=False)
        assert setup.call_args.kwargs["non_interactive"] is True


class TestRunInstall:
    """The five-step orchestrator."""

    def test_dry_run_is_side_effect_free(self, tmp_path: Path) -> None:
        """Dry-run walks all steps, the phone face included, with no subprocess and no network.

        It takes no install lock: a dry run writes nothing, so it has nothing to guard.
        Mutant: dry run takes the install lock again -> red.
        """
        home = tmp_path / "parent" / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}.subprocess.run") as run,
            patch("urllib.request.urlopen") as net,
        ):
            rc = run_install(non_interactive=True, dry_run=True)
        assert rc == 0
        run.assert_not_called()
        net.assert_not_called()
        assert not install_lock_path(home).parent.exists()

    def test_aborts_when_clone_fails(self, tmp_path: Path, monkeypatch) -> None:
        """A failed fetch aborts before the setup step runs.

        The throwaway gate is passed, so the run reaches the clone itself.
        Guards past the clone: the offline fixture, a home never made, a non-terminal stdin.
        Mutant: the clone failure's `return 1` -> `return 0` -> red at rc.
        """
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=False) as clone,
            patch(f"{_MOD}._run_setup") as setup,
            patch(_BUS) as bus,
        ):
            rc = run_install(non_interactive=True, dry_run=False)
        clone.assert_called_once_with(home, False, source=REPO_URL)
        setup.assert_not_called()
        assert rc == 1
        bus.fire.assert_called_once_with(
            "file_deleted", path=str(install_lock_path(home)), reason="install_lock_released"
        )

    def test_full_happy_path(self, tmp_path: Path, monkeypatch) -> None:
        """Clone + setup + verify + owner check + next-steps returns success."""
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=True),
            patch(f"{_MOD}._run_setup", return_value=True),
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}),
            patch(f"{_MOD}._check_and_fix_owner") as owner,
            patch(f"{_MOD}._install_phone_face", return_value=True) as face,
            patch(_BUS) as bus,
        ):
            rc = run_install(non_interactive=True, dry_run=False)
        assert rc == 0
        owner.assert_called_once_with(home, "/x/drone")
        bus.fire.assert_called_once_with(
            "file_deleted", path=str(install_lock_path(home)), reason="install_lock_released"
        )
        face.assert_called_once_with(False, False, "latest")
        assert install_report_path(home).is_file()

    def test_a_bad_baud_tag_is_refused_before_anything_is_cloned(self, tmp_path: Path) -> None:
        """--baud-tag is checked first: a bad tag exits 2 with no home, no lock, no clone (FPLAN-0642 slice B).

        Mutant: the validate_tag call dropped from run_install -> the clone runs, rc 0 -> red.
        """
        with (
            patch(f"{_MOD}._resolve_home") as resolve,
            patch(f"{_MOD}._clone_repo") as clone,
            patch(f"{_MOD}._install_phone_face") as face,
        ):
            rc = run_install(non_interactive=True, dry_run=False, baud_tag="../escape")
        assert rc == 2
        resolve.assert_not_called()
        clone.assert_not_called()
        face.assert_not_called()

    def test_a_good_baud_tag_reaches_the_phone_face_step(self, tmp_path: Path) -> None:
        """The tag a user typed is the tag step 4 installs. Mutant: step 4 handed LATEST -> red."""
        home = tmp_path / "AIPass"
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=True),
            patch(f"{_MOD}._run_setup", return_value=True),
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}),
            patch(f"{_MOD}._check_and_fix_owner"),
            patch(f"{_MOD}._install_phone_face", return_value=True) as face,
            patch(_BUS),
        ):
            rc = run_install(non_interactive=True, dry_run=False, baud_tag="v0.2.1")
        assert rc == 0
        face.assert_called_once_with(False, False, "v0.2.1")

    def test_phone_face_sits_between_verify_and_the_health_check_and_a_requested_miss_fails_the_install(
        self, tmp_path: Path, monkeypatch
    ) -> None:
        """Step 4 of 5 runs after the verified binaries and before the doctor; a requested miss exits 1 (FPLAN-0926)."""
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        order = MagicMock()
        with (
            patch(f"{_MOD}._resolve_home", return_value=home),
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}._clone_repo", return_value=True),
            patch(f"{_MOD}._run_setup", return_value=True),
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}) as verify,
            patch(f"{_MOD}._check_and_fix_owner"),
            patch(f"{_MOD}._install_phone_face", return_value=False) as face,
            patch(f"{_MOD}.render_step_header", return_value="") as header,
            patch(_BUS) as bus,
        ):
            order.attach_mock(verify, "verify")
            order.attach_mock(face, "face")
            monkeypatch.setattr(doctor, "run_doctor_preflight", lambda **_kw: (order.doctor(), ({}, (0, 0, 0)))[1])
            rc = run_install(non_interactive=True, dry_run=False, no_baud=False)
        assert rc == 1
        bus.fire.assert_called_once_with(
            "file_deleted", path=str(install_lock_path(home)), reason="install_lock_released"
        )
        assert [c[0] for c in order.mock_calls] == ["verify", "face", "doctor"]
        assert header.call_args_list[3:] == [call(4, 5, "Phone face + baud-cli"), call(5, 5, "Health check")]


class TestHandleCommand:
    """Command routing for `aipass install`."""

    def test_ignores_other_commands(self) -> None:
        """A non-install command is not handled here."""
        assert handle_command("doctor", []) is False

    def test_help(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--help is handled without exiting. Mutant: print_help() dropped from the --help branch -> red."""
        assert handle_command("install", ["--help"]) is True
        out, err = capsys.readouterr()
        assert "USAGE:" in out
        assert "--non-interactive" in out

    def test_info(self, capsys: pytest.CaptureFixture[str]) -> None:
        """--info is handled without exiting. Mutant: print_introspection() dropped from the --info branch -> red."""
        assert handle_command("install", ["--info"]) is True
        out, err = capsys.readouterr()
        assert "install Module" in out
        assert "Default home:" in out

    def test_runs_and_exits(self) -> None:
        """A run request calls run_install and exits with its code."""
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit) as exc:
                handle_command("install", ["--dry-run", "--non-interactive"])
        assert exc.value.code == 0
        run.assert_called_once()

    def test_passes_path_flag(self) -> None:
        """--path and --non-interactive are threaded into run_install."""
        target = str(Path.home() / "custom-aipass-home")
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--path", target, "--non-interactive"])
        _, kwargs = run.call_args
        assert kwargs["path"] == target
        assert kwargs["non_interactive"] is True

    def test_passes_no_baud_flag(self) -> None:
        """--no-baud is threaded into run_install (FPLAN-0587)."""
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--no-baud"])
        assert run.call_args.kwargs["no_baud"] is True

    def test_passes_baud_tag_flag(self) -> None:
        """--baud-tag TAG is threaded into run_install; absent, it is latest.

        Mutant: handle_command reads the flag as LATEST always -> red.
        """
        with patch(f"{_MOD}.run_install", return_value=0) as run:
            with pytest.raises(SystemExit):
                handle_command("install", ["--baud-tag", "v0.2.1"])
            with pytest.raises(SystemExit):
                handle_command("install", [])
        assert [c.kwargs["baud_tag"] for c in run.call_args_list] == ["v0.2.1", "latest"]

    def test_a_valueless_baud_tag_is_refused_not_swallowed(self, capsys: pytest.CaptureFixture[str]) -> None:
        """`--baud-tag --no-baud` does not install the tag "--no-baud", nor fall back to latest: exit 2.

        Mutant: a valueless --baud-tag read as LATEST -> the install runs -> red.
        """
        with patch(f"{_MOD}._resolve_home") as resolve:
            with pytest.raises(SystemExit) as exc:
                handle_command("install", ["--baud-tag", "--no-baud"])
        assert exc.value.code == 2
        resolve.assert_not_called()
        assert "--baud-tag refused: '--no-baud'" in capsys.readouterr().err

    def test_symlink_flags_reach_setup_sh(self, tmp_path: Path) -> None:
        """--no-symlink and --force-symlink typed at the command land on setup.sh's argv (#660).

        The real run_install and _run_setup run; only the setup.sh process is stubbed.
        Mutant: `no_symlink = "--no-symlink" in run_args` -> `no_symlink = False` -> red.
        Mutant: `force_symlink = "--force-symlink" in run_args` -> `force_symlink = False` -> red.
        """
        home = tmp_path / "AIPass"
        home.mkdir()
        _aipass_tree(home)
        with (
            patch(f"{_MOD}.is_throwaway_path", return_value=False),
            patch(f"{_MOD}.subprocess.run", return_value=MagicMock(returncode=0)) as run,
            patch(f"{_MOD}._verify_binaries", return_value={"drone": "/x/drone", "aipass": "/x/aipass"}),
            patch(f"{_MOD}._check_and_fix_owner"),
            patch(f"{_MOD}._health_check", return_value=([], {"pass": 0, "warn": 0, "error": 0})),
            patch(_BUS),
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command(
                    "install",
                    ["--path", str(home), "--non-interactive", "--no-baud", "--no-symlink", "--force-symlink"],
                )
        assert exc.value.code == 0
        setup_calls = [c.args[0] for c in run.call_args_list if c.args[0][:1] == ["bash"]]
        assert setup_calls == [["bash", str(home / "setup.sh"), "--no-finish", "--no-symlink", "--force-symlink"]]

    def test_finish_routes_to_run_finish(self) -> None:
        """--finish routes to run_finish instead of run_install."""
        with (
            patch(f"{_MOD}.run_finish", return_value=0) as finish,
            patch(f"{_MOD}.run_install") as install,
        ):
            with pytest.raises(SystemExit) as exc:
                handle_command("install", ["--finish", "--here"])
        assert exc.value.code == 0
        install.assert_not_called()
        assert finish.call_args.kwargs == {
            "non_interactive": False, "path": None, "here": True, "dry_run": False, "yes": False
        }  # fmt: skip


class TestInstallPhoneFaceStep:
    """The Phone face + baud-cli step delegates to aipass baud and honours --no-baud (FPLAN-0587, FPLAN-0589)."""

    def test_no_baud_skips_without_touching_baud(self) -> None:
        """--no-baud: skipped, reported as not installed, baud never called."""
        with patch("aipass.aipass.apps.modules.baud.install_best_effort") as best:
            assert _install_phone_face(dry_run=False, no_baud=True) is False
        best.assert_not_called()

    def test_delegates_to_the_best_effort_install(self) -> None:
        """Without --no-baud the step is baud's best-effort install, dry-run threaded."""
        with patch("aipass.aipass.apps.modules.baud.install_best_effort", return_value=True) as best:
            assert _install_phone_face(dry_run=True, no_baud=False) is True
        best.assert_called_once_with(dry_run=True, tag="latest")

    def test_the_tag_reaches_the_best_effort_install(self) -> None:
        """--baud-tag is passed straight through as baud's --tag. Mutant: tag dropped -> red."""
        with patch("aipass.aipass.apps.modules.baud.install_best_effort", return_value=True) as best:
            _install_phone_face(dry_run=False, no_baud=False, baud_tag="v0.2.1")
        best.assert_called_once_with(dry_run=False, tag="v0.2.1")


class _Stdin(io.StringIO):
    """A real text stream for input() to read, answering isatty() as told."""

    def __init__(self, text: str, tty: bool) -> None:
        super().__init__(text)
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


_ROWS = {
    "System": [CheckResult("python", GLYPH_PASS, "3.12", "")],
    "Services": [
        CheckResult("wire verify", GLYPH_FAIL, "[red]2 orphan entries[/red]", "drone @hooks verify"),
        CheckResult("hooks", GLYPH_WARN, "2 hook(s) missing", "aipass doctor --fix"),
    ],
}


def _finish(home: Path, monkeypatch, capsys, rows=None, counts=(1, 1, 0)) -> "tuple[int, str, str]":
    """`aipass install --finish --non-interactive` on `home` with the doctor answering `rows`."""
    monkeypatch.setattr(
        doctor, "run_doctor_preflight", lambda non_interactive=False, yes=False: (rows or _ROWS, counts)
    )
    with pytest.raises(SystemExit) as exc:
        handle_command("install", ["--finish", "--path", str(home), "--non-interactive"])
    out, err = capsys.readouterr()
    return int(exc.value.code or 0), out, err


def _doctor_world(tmp_path: Path, monkeypatch) -> Path:
    """The real doctor --fix with every group but the provider wire stubbed. Returns the settings file."""
    for name in ("_check_system", "check_identity", "_check_community", "_check_structure", "_check_scaffold"):
        monkeypatch.setattr(doctor, name, lambda: [])
    for name in ("_check_sandbox", "check_wire_verify", "_fix_owner_seating", "_fix_shared_skills"):
        monkeypatch.setattr(doctor, name, lambda: [])
    monkeypatch.setattr(doctor, "_fix_instruction_shadow", lambda: [])
    monkeypatch.setattr(doctor, "_check_services", lambda **_kw: [])
    claude = tmp_path / ".claude"
    claude.mkdir()
    manifest = claude / "provider_manifest.json"
    manifest.write_text(
        json.dumps({"cli": {"claude": {"hooks": [], "settings": {"includeGitInstructions": False}}}}), encoding="utf-8"
    )
    monkeypatch.setattr(doctor, "_find_manifest", lambda: manifest)
    monkeypatch.setattr(doctor, "run_doctor_preflight", _REAL_PREFLIGHT)
    settings = claude / "settings.json"
    settings.write_text(json.dumps({"env": {}}), encoding="utf-8")
    return settings


def _full_install(home: Path, monkeypatch, *flags: str) -> "tuple[int, list]":
    """`aipass install --path home --non-interactive *flags` on an AIPass tree; every subprocess recorded.

    None runs: the home's doctor is answered in-process (homes_doctor), every other call exits 0.
    """
    home.mkdir(exist_ok=True)
    _aipass_tree(home)
    ran: list = []
    homes = _sp.run

    def run(argv, **kw):
        ran.append((argv, kw.get("env")))
        return homes(argv, **kw) if argv[1:2] == ["doctor"] else _sp.CompletedProcess(argv, 0, "", "")

    monkeypatch.setattr(_sp, "run", run)
    monkeypatch.setattr(sys, "argv", ["aipass", "install"])
    with patch(f"{_MOD}.is_throwaway_path", return_value=False), patch(_BUS), pytest.raises(SystemExit) as exc:
        handle_command("install", ["--path", str(home), "--non-interactive", *flags])
    return int(exc.value.code or 0), ran


class TestInstallReport:
    """Step 5 and the final screen: doctor --fix, the report in devpulse's dropbox, one wake command, no launch."""

    def test_the_report_lands_in_the_dropbox_with_the_contract_shape_and_every_attention_row(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """The rows arrive through the home doctor's rows file.

        Mutants: markup kept in detail; severity inverted; setup.sh's lines dropped; the file's rows or counts
        not returned by the health check -> each red.
        """
        home = tmp_path / "AIPass"
        home.mkdir()
        (home / "AIPASS_REGISTRY.json").write_text('{"metadata": {"user": "someone"}}', encoding="utf-8")
        (home / ".aipass").mkdir()
        items = "srt missing — run: sudo npm install -g srt\n\nrg missing\n"
        (home / ".aipass" / "setup_attention.txt").write_text(items, encoding="utf-8")
        rc, _out, _err = _finish(home, monkeypatch, capsys)

        raw = install_report_path(home).read_text(encoding="utf-8")
        report = json.loads(raw)
        assert rc == 0
        assert install_report_path(home) == home / "src" / "aipass" / "devpulse" / "dropbox" / "install_report.json"
        assert raw.endswith("}\n")
        assert set(report) == {
            "kind", "version", "written_at", "home", "aipass_version", "user_name", "outcome", "failed_steps",
            "doctor", "attention",
        }  # fmt: skip
        assert (report["kind"], report["version"], report["outcome"]) == ("aipass_install_report", 1, "installed")
        assert report["failed_steps"] == []
        assert (report["home"], report["user_name"]) == (str(home), "someone")
        assert report["doctor"] == {"pass": 1, "warn": 1, "error": 0}
        assert datetime.fromisoformat(report["written_at"]).utcoffset() == timedelta(0)
        setup = {"group": "Setup", "label": "setup.sh", "severity": "warning", "remediation": ""}
        assert report["attention"] == [
            {"group": "Services", "label": "wire verify", "severity": "error", "detail": "2 orphan entries",
             "remediation": "drone @hooks verify"},
            {"group": "Services", "label": "hooks", "severity": "warning", "detail": "2 hook(s) missing",
             "remediation": "aipass doctor --fix"},
            {**setup, "detail": "srt missing — run: sudo npm install -g srt"},
            {**setup, "detail": "rg missing"},
        ]  # fmt: skip

    def test_an_unreadable_setup_attention_file_is_one_error_row_not_a_silent_empty(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Bad UTF-8 in setup.sh's file. Mutant: the decode error read as no items -> red."""
        home = tmp_path / "AIPass"
        (home / ".aipass").mkdir(parents=True)
        items = home / ".aipass" / "setup_attention.txt"
        items.write_bytes(b"\xff\xfe not utf-8\n")
        rc, _out, _err = _finish(home, monkeypatch, capsys, rows={"System": _ROWS["System"]}, counts=(1, 0, 0))

        (row,) = json.loads(install_report_path(home).read_text(encoding="utf-8"))["attention"]
        assert rc == 0
        assert (row["group"], row["label"], row["severity"]) == ("Setup", "setup.sh", "error")
        assert row["detail"].startswith(f"setup.sh's action items unreadable at {items}: ")
        assert "utf-8" in row["detail"]

    def test_the_final_screen_lists_each_row_then_the_report_then_one_quoted_wake_line(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutant: the path not shlex-quoted -> a home with a space breaks the cd -> red."""
        home = tmp_path / "my home"
        home.mkdir()
        rc, out, _err = _finish(home, monkeypatch, capsys)

        lines = out.splitlines()
        devpulse = shlex.quote(str(home / "src" / "aipass" / "devpulse"))
        wake = (
            f'cd {devpulse} && claude "Read dropbox/install_report.json: a fresh AIPass install. '
            'Greet me by name, then walk me through each attention item."'
        )
        assert rc == 0
        assert wake_command(home) == wake
        assert "".join(f"AIPass installed at {home}".split()) in "".join(out.split())
        assert "  error: wire verify: 2 orphan entries -> drone @hooks verify" in lines
        assert "  warning: hooks: 2 hook(s) missing -> aipass doctor --fix" in lines
        assert lines.count(wake) == 1
        assert lines.index(f"Report: {install_report_path(home)}") < lines.index(wake)

    def test_a_clean_doctor_is_installed_exit_0_with_the_success_line_and_nothing_needs_attention(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutants: the empty-attention line dropped; the error test reads "pass" not "error" -> each red."""
        home = tmp_path / "AIPass"
        home.mkdir()
        rc, out, err = _finish(home, monkeypatch, capsys, rows={"System": _ROWS["System"]}, counts=(1, 0, 0))

        report = json.loads(install_report_path(home).read_text(encoding="utf-8"))
        assert rc == 0
        assert f"AIPass installed at {home}" in " ".join(out.split())
        assert f"{home}, but" not in " ".join(err.split())
        assert "Nothing needs attention." in out.splitlines()
        assert (report["outcome"], report["attention"]) == ("installed", [])

    def test_a_full_install_launches_nothing(self, tmp_path: Path, monkeypatch, capsys) -> None:
        """Mutant: a `claude` subprocess run after the report -> red."""
        home = tmp_path / "AIPass"
        rc, ran = _full_install(home, monkeypatch, "--no-baud")

        argvs = [argv for argv, _env in ran]
        assert rc == 0
        assert ["bash", str(home / "setup.sh"), "--no-finish"] in argvs
        assert [argv for argv in argvs if "claude" in " ".join(map(str, argv))] == []
        assert install_report_path(home).is_file()

    def test_a_non_interactive_install_writes_no_settings_and_shows_the_warn_row(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutant: the install door's old auto-consent -> the settings file is rewritten -> red."""
        settings = _doctor_world(tmp_path, monkeypatch)
        original = settings.read_bytes()
        home = tmp_path / "AIPass"
        home.mkdir()
        with patch("sys.stdin", _Stdin("y\n", tty=True)), _home_at(tmp_path), pytest.raises(SystemExit) as exc:
            handle_command("install", ["--finish", "--path", str(home), "--non-interactive"])

        out = capsys.readouterr().out
        attention = json.loads(install_report_path(home).read_text(encoding="utf-8"))["attention"]
        assert exc.value.code == 0
        assert settings.read_bytes() == original
        assert (
            f"  warning: settings fix: {NOT_APPLIED_NON_INTERACTIVE} -> aipass doctor --fix --yes" in out.splitlines()
        )
        assert {"label": "settings fix", "detail": NOT_APPLIED_NON_INTERACTIVE} in [
            {"label": a["label"], "detail": a["detail"]} for a in attention
        ]

    def test_a_declined_install_warns_what_will_not_work_and_names_the_fix(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutant: the old header-only warning on decline -> the what-will-not-work line is missing -> red."""
        settings = _doctor_world(tmp_path, monkeypatch)
        original = settings.read_bytes()
        home = tmp_path / "AIPass"
        home.mkdir()
        with patch("sys.stdin", _Stdin("n\n", tty=True)), _home_at(tmp_path):
            rc = run_finish(path=str(home))

        err = " ".join(capsys.readouterr().err.split())
        assert rc == 0
        assert settings.read_bytes() == original
        assert " ".join(DECLINED_WARNING.split()) in err
        assert "Wire them later: aipass doctor --fix" in err

    def test_an_unwritable_dropbox_is_a_loud_error_exit_1_and_no_wake_line(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """A file where devpulse's directory goes makes the mkdir fail. Mutant: the write error returns 0 -> red."""
        home = tmp_path / "AIPass"
        (home / "src" / "aipass").mkdir(parents=True)
        (home / "src" / "aipass" / "devpulse").write_text("not a directory", encoding="utf-8")
        rc, out, err = _finish(home, monkeypatch, capsys)

        assert rc == 1
        assert "".join(f"Could not write the install report at {install_report_path(home)}".split()) in "".join(
            err.split()
        )
        assert "claude" not in out

    def test_a_requested_phone_face_that_misses_exits_1_and_the_report_names_it_first(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutants: `failed` always []; the success line kept; "installed"; exit 0; phone row last -> each red."""
        monkeypatch.setattr(doctor, "run_doctor_preflight", lambda non_interactive=False, yes=False: (_ROWS, (1, 1, 1)))
        home = tmp_path / "AIPass"
        rc, _ran = _full_install(home, monkeypatch)

        out, err = capsys.readouterr()
        report = json.loads(install_report_path(home).read_text(encoding="utf-8"))
        assert rc == 1
        assert f"AIPass installed at {home}, but a requested step failed: phone face" in " ".join(err.split())
        assert "✅ AIPass installed" not in out + err
        assert (report["outcome"], report["failed_steps"]) == ("step_failed", ["phone face"])
        assert [a["label"] for a in report["attention"]] == ["phone face", "wire verify", "hooks"]
        assert report["attention"][0]["severity"] == "error"

    def test_no_baud_skips_the_phone_face_and_the_install_still_succeeds(self, tmp_path: Path, monkeypatch) -> None:
        """Mutant: `failed = [] if face_installed or no_baud` -> `if face_installed` -> red."""
        home = tmp_path / "AIPass"
        rc, _ran = _full_install(home, monkeypatch, "--no-baud")

        report = json.loads(install_report_path(home).read_text(encoding="utf-8"))
        assert rc == 0
        assert (report["outcome"], report["failed_steps"]) == ("installed", [])

    @pytest.mark.parametrize("door", [[], ["--finish"]])
    def test_yes_reaches_the_doctor_and_setup_sh(self, door, tmp_path: Path, monkeypatch, doctor_stays_stubbed) -> None:
        """Mutants: yes dropped at any hop (run_install, run_finish, _health_check, _run_setup) -> each red."""
        home = tmp_path / "AIPass"
        _rc, ran = _full_install(home, monkeypatch, "--no-baud", "--yes", *door)

        assert doctor_stays_stubbed == [{"non_interactive": True, "yes": True}]
        setup_envs = [env for argv, env in ran if argv[:1] == ["bash"]]
        assert [env["AIPASS_YES"] for env in setup_envs] == ([] if door else ["1"])

    def test_a_dry_run_runs_no_doctor_and_writes_no_report(self, tmp_path: Path, capsys, doctor_stays_stubbed) -> None:
        """Mutant: the dry-run guard in the final screen dropped -> the report is written -> red."""
        home = tmp_path / "AIPass"
        with patch(f"{_MOD}.is_throwaway_path", return_value=False):
            rc = run_install(non_interactive=True, dry_run=True, path=str(home))

        out = " ".join(capsys.readouterr().out.split())
        assert rc == 0
        assert doctor_stays_stubbed == []
        assert not install_report_path(home).exists()
        assert "[dry-run] would run: aipass doctor --fix" in out
        assert f"[dry-run] would write the install report: {install_report_path(home)}" in out


class TestHealthCheck:
    """Step 5 runs the home's own `aipass doctor --fix` in the home, never the bootstrap's doctor in-process."""

    def test_the_homes_doctor_runs_in_the_home_with_its_argv_env_and_no_terminal_under_non_interactive(
        self, tmp_path: Path, monkeypatch, capsys, homes_doctor
    ) -> None:
        """Mutants: cwd dropped; no AIPASS_HOME; os.environ dropped; stdin always None; --yes dropped -> each red."""
        home = tmp_path / "AIPass"
        home.mkdir()
        monkeypatch.setenv("AIPASS_PROBE", "kept")
        with pytest.raises(SystemExit):
            handle_command("install", ["--finish", "--path", str(home), "--non-interactive", "--yes"])

        ((argv, kw),) = homes_doctor
        rows_file = home / ".aipass" / "install_doctor_rows.json"
        assert argv == [
            str(home / ".venv" / "bin" / "aipass"), "doctor", "--fix", "--rows-json", str(rows_file), "--yes",
            "--non-interactive",
        ]  # fmt: skip
        assert kw["cwd"] == str(home)
        assert (kw["env"]["AIPASS_HOME"], kw["env"]["AIPASS_PROBE"]) == (str(home), "kept")
        assert kw["stdin"] is _sp.DEVNULL
        assert kw["timeout"] == 600

    def test_an_interactive_install_hands_the_doctor_the_users_terminal_and_no_flags(
        self, tmp_path: Path, homes_doctor
    ) -> None:
        """Mutants: stdin always DEVNULL; --non-interactive always passed -> each red."""
        home = tmp_path / "AIPass"
        home.mkdir()
        run_finish(path=str(home))

        ((argv, kw),) = homes_doctor
        assert argv[2:] == ["--fix", "--rows-json", str(home / ".aipass" / "install_doctor_rows.json")]
        assert kw["stdin"] is None

    def _did_not_run(self, home: Path, detail: str) -> dict:
        crash = {"group": "Doctor", "label": "doctor", "severity": "error", "detail": detail}
        return {**crash, "remediation": f"cd {shlex.quote(str(home))} && aipass doctor --fix"}

    def test_a_doctor_that_exits_non_zero_is_one_error_row_and_fails_the_install(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutant: the returncode check dropped -> the missing rows file is the detail, not the exit -> red."""
        home = tmp_path / "my home"
        home.mkdir()
        monkeypatch.setattr(_sp, "run", lambda argv, **_kw: _sp.CompletedProcess(argv, 3))
        rc = run_finish(non_interactive=True, path=str(home))

        report = json.loads(install_report_path(home).read_text(encoding="utf-8"))
        assert rc == 1
        assert report["attention"] == [self._did_not_run(home, "did not run: exit 3")]
        assert report["doctor"] == {"pass": 0, "warn": 0, "error": 1}
        assert "Health check did not run" in capsys.readouterr().err

    def test_a_home_with_no_aipass_binary_is_the_same_row_not_a_raise(self, tmp_path: Path, monkeypatch) -> None:
        """The real subprocess.run on a missing binary. Mutant: OSError dropped from the except -> it raises -> red."""
        home = tmp_path / "AIPass"
        home.mkdir()
        monkeypatch.setattr(_sp, "run", _REAL_RUN)
        rc = run_finish(non_interactive=True, path=str(home))

        (row,) = json.loads(install_report_path(home).read_text(encoding="utf-8"))["attention"]
        assert rc == 1
        assert row == self._did_not_run(home, row["detail"])
        assert row["detail"].startswith("did not run: [Errno")

    def test_a_doctor_error_is_the_closing_error_line_outcome_doctor_errors_and_exit_1(
        self, tmp_path: Path, monkeypatch, capsys
    ) -> None:
        """Mutants: the counts' error clause dropped; outcome "installed" on errors; exit 0 on errors -> each red."""
        home = tmp_path / "AIPass"
        home.mkdir()
        rc, out, err = _finish(home, monkeypatch, capsys, counts=(1, 1, 1))

        report = json.loads(install_report_path(home).read_text(encoding="utf-8"))
        assert rc == 1
        assert f"AIPass installed at {home}, but the health check found 1 error(s)" in " ".join(err.split())
        assert "✅ AIPass installed" not in out + err
        assert (report["outcome"], report["failed_steps"]) == ("doctor_errors", [])


class TestSmoke:
    """Help/introspection render and constants hold."""

    def test_print_help_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """print_help names the command, the step order and the init hand-off.

        Mutant: --no-baud usage line not printed -> red.
        It also tells the user a dry run takes no lock, so previewing beside a live install is safe.
        Mutant: the dry-run lock sentence not printed -> red.
        """
        print_help()
        out, _err = capsys.readouterr()
        printed = " ".join(out.split())
        assert "aipass install \u2014 one-command bootstrap of AIPass" in printed
        assert "resolve home -> fetch -> setup.sh -> verify -> phone face + baud-cli -> doctor + report" in printed
        assert "--no-baud" in printed
        assert "aipass init <dir>" in printed
        assert "A dry run takes no install lock, so it can preview beside a live install." in printed

    def test_print_introspection_runs(self, capsys: pytest.CaptureFixture[str]) -> None:
        """print_introspection names the module, the default home and the source.

        Mutant: Source line not printed -> red.
        """
        print_introspection()
        out, _err = capsys.readouterr()
        printed = " ".join(out.split())
        assert "install Module" in printed
        assert str(DEFAULT_HOME) in printed
        assert REPO_URL in printed

    def test_total_steps_constant(self) -> None:
        """The install flow advertises five steps (the phone face is step 4)."""
        assert TOTAL_STEPS == 5


# ---------------------------------------------------------------------------
# Throwaway-path gate (#688)
# ---------------------------------------------------------------------------


class TestThrowawayGate:
    """Install refuses throwaway homes unless --force-global-home."""

    def test_refuses_tmp_home(self, tmp_path) -> None:
        """run_install returns 1 when home resolves to a temp path."""
        with (
            patch(
                "aipass.aipass.apps.modules.install._resolve_home",
                return_value=tmp_path,
            ),
            patch("aipass.aipass.apps.modules.install.sys.argv", ["aipass", "install"]),
        ):
            result = run_install(non_interactive=True)
        assert result == 1

    def test_force_flag_overrides(self, tmp_path, monkeypatch) -> None:
        """--force-global-home lets a temp home proceed past the gate.

        The home sits one level under tmp_path, as in the other lock tests: the lock
        lies in the home's parent, so a home of tmp_path itself put it in pytest's base.
        """
        home = tmp_path / "AIPass"
        _installed_in(home, monkeypatch)
        with (
            patch(
                "aipass.aipass.apps.modules.install._resolve_home",
                return_value=home,
            ),
            patch(
                "aipass.aipass.apps.modules.install.sys.argv",
                ["aipass", "install", "--force-global-home"],
            ),
            patch(
                "aipass.aipass.apps.modules.install._looks_like_aipass_tree",
                return_value=True,
            ),
            patch(
                "aipass.aipass.apps.modules.install._run_setup",
                return_value=True,
            ),
            patch(
                "aipass.aipass.apps.modules.install._verify_binaries",
                return_value={"drone": "x", "aipass": "x"},
            ),
            patch("aipass.aipass.apps.modules.install._check_and_fix_owner"),
            patch(f"{_MOD}._install_phone_face", return_value=True),
            patch(_BUS) as bus,
        ):
            result = run_install(non_interactive=True)
        assert result == 0
        bus.fire.assert_called_once_with(
            "file_deleted", path=str(install_lock_path(home)), reason="install_lock_released"
        )


# ---------------------------------------------------------------------------
# _check_and_fix_owner tests (DPLAN-0239 P5)
# ---------------------------------------------------------------------------


class TestCheckAndFixOwner:
    """Tests for install-time owner/identity check+fix retro-trigger."""

    def test_clean_check_skips_fix(self, tmp_path) -> None:
        """A clean --check never runs --fix.

        Mutant: `if check_proc.returncode != 0:` -> `if check_proc.returncode == 0:` -> red.
        """
        mock_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            return_value=mock_proc,
        ) as mock_run:
            _check_and_fix_owner(tmp_path)
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0] == ["drone", "@spawn", "sync-registry", "--check"]
        assert mock_run.call_args.kwargs["cwd"] == str(tmp_path)

    def test_the_given_drone_binary_runs(self, tmp_path) -> None:
        """A drone found in the home's venv is used, not whatever PATH holds."""
        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            return_value=MagicMock(returncode=0, stdout="", stderr=""),
        ) as mock_run:
            _check_and_fix_owner(tmp_path, str(tmp_path / ".venv" / "bin" / "drone"))
        assert mock_run.call_args[0][0][0] == str(tmp_path / ".venv" / "bin" / "drone")

    def test_issues_trigger_fix(self, tmp_path) -> None:
        check_proc = MagicMock(returncode=1, stdout="", stderr="")
        fix_proc = MagicMock(returncode=0, stdout="", stderr="")
        with patch(
            "aipass.aipass.apps.modules.install.subprocess.run",
            side_effect=[check_proc, fix_proc],
        ) as mock_run:
            _check_and_fix_owner(tmp_path)
        assert mock_run.call_count == 2
        fix_args = mock_run.call_args_list[1][0][0]
        assert "--fix" in fix_args

    @pytest.mark.parametrize("failure", [FileNotFoundError("drone"), _sp.TimeoutExpired("drone", 30)])
    def test_a_check_that_cannot_run_says_so_and_names_the_fix(self, tmp_path, capsys, failure) -> None:
        """Mutant: the except only logs again (the install reads as checked) -> red."""
        with patch("aipass.aipass.apps.modules.install.subprocess.run", side_effect=failure):
            _check_and_fix_owner(tmp_path)
        _out, err = capsys.readouterr()
        assert "Owner/identity NOT checked" in err
        assert "sync-registry --fix" in err

    def test_a_failed_repair_says_so_and_names_the_fix(self, tmp_path, capsys) -> None:
        """Mutant: the failed --fix only logs again -> red."""
        procs = [MagicMock(returncode=1, stdout="", stderr=""), MagicMock(returncode=2, stdout="", stderr="")]
        with patch("aipass.aipass.apps.modules.install.subprocess.run", side_effect=procs):
            _check_and_fix_owner(tmp_path)
        _out, err = capsys.readouterr()
        assert "repair failed (exit 2)" in err
        assert "sync-registry --fix" in err


# =============================================================================
# TestClonedBranchIsNamed — say which branch the user actually got
# =============================================================================


class TestClonedBranchIsNamed:
    """A reinstall clones the repo DEFAULT branch, not the one you stand on.

    The clone target stays the default branch on purpose; it must say which branch landed.
    """

    @staticmethod
    def _clone(tmp_path, branch_stdout="main\n", rc=0):
        home = tmp_path / "home"
        calls = []

        def fake_run(cmd, *a, **kw):
            calls.append(cmd)
            if "clone" in cmd:
                home.mkdir(parents=True, exist_ok=True)
                return _sp.CompletedProcess(cmd, rc)
            return _sp.CompletedProcess(cmd, 0, stdout=branch_stdout, stderr="")

        printed = []
        asked = []

        def which(name):
            asked.append(name)
            return str(tmp_path / "bin" / name)

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch.object(
                _install.console,
                "print",
                side_effect=lambda *a, **k: printed.append(" ".join(str(x) for x in a)),
            ),
        ):
            ok = _install._clone_repo(home, dry_run=False, which=which)
        assert asked == ["git"]  # the clone asks the seam for git once, and nothing else
        return ok, " ".join(printed), calls

    def test_prints_the_branch_that_landed(self, tmp_path) -> None:
        """The name is MEASURED after the clone, so the message cannot be wrong."""
        ok, printed, _calls = self._clone(tmp_path, branch_stdout="main\n")

        assert ok is True
        assert "main" in printed

    def test_reports_the_real_branch_not_a_guess(self, tmp_path) -> None:
        """A repo whose default is not 'main' reports its actual name."""
        _ok, printed, _calls = self._clone(tmp_path, branch_stdout="trunk\n")

        assert "trunk" in printed
        assert "main" not in printed

    def test_unreadable_branch_does_not_fail_the_install(self, tmp_path) -> None:
        """Naming is a courtesy — it must never turn a good clone into a failure."""
        home = tmp_path / "home"

        def fake_run(cmd, *a, **kw):
            if "clone" in cmd:
                home.mkdir(parents=True, exist_ok=True)
                return _sp.CompletedProcess(cmd, 0)
            raise OSError("git gone")

        with (
            patch("subprocess.run", side_effect=fake_run),
            patch.object(_install.console, "print"),
        ):
            assert _install._clone_repo(home, dry_run=False, which=lambda name: str(tmp_path / "bin" / name)) is True

    def test_failed_clone_still_returns_false(self, tmp_path) -> None:
        """The added step must not mask a real clone failure."""
        ok, _printed, _calls = self._clone(tmp_path, rc=1)

        assert ok is False
