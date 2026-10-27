# =================== AIPass ====================
# Name: conftest.py
# Description: Shared fixtures for the drone suite
# Version: 1.3.2
# Created: 2026-03-05
# Modified: 2026-10-26
# =============================================

"""Shared pytest fixtures for drone tests."""

import os
import tempfile

# Must be set before any prax import, which initializes the logger.
if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import json
import logging
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Generator

import pytest

from aipass.cli.apps.modules import display
from aipass.drone.apps.handlers import registry_handler, router_handler
from aipass.drone.apps.handlers.git import session_home
from aipass.drone.apps.handlers.json import json_handler

# Not imported from seedgo: its guard refuses another branch's caller.
SANDBOX_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})

# .archive/ holds verbatim disposal copies of old tests that must never be collected.
collect_ignore_glob = [".archive/*", "**/.archive/*"]


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Pin Rich's width: unpinned it is 80 on POSIX, 79 on Windows, or the terminal's."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def _clean_identity_dedupe(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give every test a fresh caller-identity dedupe set (dedupe is per process; pytest is one)."""
    monkeypatch.setattr(router_handler, "_LOGGED_IDENTITY_SIGNATURES", set())


@pytest.fixture(autouse=True)
def _no_agent_session(monkeypatch: pytest.MonkeyPatch) -> None:
    """The suite runs inside a real agent session, and the git fence would place every tmp seat against it."""
    monkeypatch.delenv(session_home.SESSION_ENV, raising=False)


@pytest.fixture(autouse=True)
def _isolate_deletion_log(tmp_path: Path) -> Generator[None, None, None]:
    """Point the deletion record at tmp, so tests never forge entries in the live audit trail."""
    os.environ["AIPASS_DELETION_LOG"] = str(tmp_path / "deletions.jsonl")
    yield
    os.environ.pop("AIPASS_DELETION_LOG", None)


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after.

    Teardown steps OUT first: autouse monkeypatch undoes its chdir after this runs,
    and Windows cannot rmtree the cwd (WinError 32).
    """
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    try:
        inside = Path.cwd().resolve().is_relative_to(test_dir.resolve())
    except FileNotFoundError as exc:
        logging.getLogger(__name__).debug("temp_test_dir: cwd already gone (%s)", exc)
        inside = True
    if inside:
        os.chdir(tempfile.gettempdir())
    if test_dir.exists():
        shutil.rmtree(test_dir)


OWNER_REGISTRY_ID = "test-registry-0000-0000"


def make_owner_project(
    root: Path,
    *,
    branch: str = "devpulse",
    registry_name: str = "AIPASS_REGISTRY.json",
    citizen_class: str = "manager",
    owner: bool = True,
    registry_id: str = OWNER_REGISTRY_ID,
    passport_registry_id: str | None = None,
    branch_dir: Path | None = None,
    record_path: str | None = None,
) -> Path:
    """Mint a project in which *branch* genuinely holds owner-tier, and return its home.

    Writes all four owner-tier facts (manager class, tenancy, owner flag, recorded path);
    each keyword breaks exactly one. *record_path* may be relative (external-project style).
    """
    home = branch_dir if branch_dir is not None else root
    home.mkdir(parents=True, exist_ok=True)

    registry = {
        "metadata": {"id": registry_id, "name": "TEST-PROJECT", "version": "1.0.0"},
        "branches": [
            {
                "name": branch,
                "path": record_path if record_path is not None else str(home),
                "email": f"@{branch}",
                "status": "active",
                "owner": owner,
            }
        ],
    }
    (root / registry_name).write_text(json.dumps(registry, indent=2), encoding="utf-8")

    trinity = home / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    passport = {
        "branch_info": {"branch_name": branch},
        "identity": {"name": branch, "citizen_class": citizen_class},
        "citizenship": {
            "registered": True,
            "registry_id": passport_registry_id if passport_registry_id is not None else registry_id,
        },
    }
    (trinity / "passport.json").write_text(json.dumps(passport, indent=2), encoding="utf-8")
    return home


@pytest.fixture()
def devpulse_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp project in which devpulse genuinely holds owner-tier."""
    make_owner_project(tmp_path)
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def seedgo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp directory with a non-owner passport."""
    trinity = tmp_path / ".trinity"
    trinity.mkdir()
    passport = trinity / "passport.json"
    passport.write_text(
        json.dumps({"branch_info": {"branch_name": "seedgo"}}),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture()
def repo_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Create a temp repo root with AIPASS_REGISTRY.json."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text("{}", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


@pytest.fixture
def sample_registry(temp_test_dir: Path) -> Path:
    """Create a sample AIPASS_REGISTRY.json for testing."""
    registry = {
        "metadata": {"version": "1.0.0"},
        "branches": [
            {
                "name": "TEST_BRANCH",
                "path": str(temp_test_dir / "test_branch"),
                "profile": "library",
                "description": "Test branch",
                "email": "@test_branch",
                "status": "active",
            }
        ],
    }
    registry_path = temp_test_dir / "AIPASS_REGISTRY.json"
    registry_path.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry_path


DELETABLE_CWD_MARKER = "deletable_cwd"

WINDOWS_CWD_REASON = (
    "This test builds its world by deleting the directory the process stands in. "
    "Windows holds the current directory open without delete sharing, so rmtree(cwd) "
    "raises PermissionError WinError 32 and the directory is never removed — the RECIPE "
    "is unavailable there, not the STATE. A disconnected share or an ejected volume still "
    "leaves a live Windows process whose getcwd() raises, so the guards themselves stay "
    "pinned on every OS by the patched-Path.cwd construction (tests/test_no_cwd_sweep.py "
    "and the portable siblings beside each skipped test). What Windows loses is only the "
    "end-to-end half: that a real deletion actually produces the state."
)


def pytest_configure(config):
    """Register the marker here, not pytest.ini: the root CI run uses another inifile with --strict-markers."""
    config.addinivalue_line(
        "markers",
        f"{DELETABLE_CWD_MARKER}: needs a process to delete the directory it stands in (POSIX only)",
    )


def python_sources(root: Path) -> list[Path]:
    """Every ``.py`` under *root*, sorted, skipping SANDBOX_DIRS judged only BELOW *root*.

    A root that itself stands inside a dropbox is still walked.
    """
    return sorted(p for p in root.rglob("*.py") if not SANDBOX_DIRS.intersection(p.relative_to(root).parts[:-1]))


def host_platform() -> str:
    """``sys.platform``, as a seam so the Windows branch is testable without patching sys."""
    return sys.platform


def pytest_collection_modifyitems(config, items):
    """Skip deletable-cwd tests on Windows only, and say the whole reason."""
    if host_platform() != "win32":
        return
    skip = pytest.mark.skip(reason=WINDOWS_CWD_REASON)
    for item in items:
        if DELETABLE_CWD_MARKER in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _seal_home_fallbacks(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Close the two AIPass-home fallbacks behind AIPASS_HOME for every test.

    The suite runs on the AIPass venv, so both fallbacks would otherwise find the live home.
    """
    monkeypatch.setattr(registry_handler, "_interpreter_home", lambda: tmp_path / "_no_aipass_home")
    monkeypatch.setattr(
        registry_handler, "_enrolment_file", lambda: tmp_path / "_no_user_home" / ".aipass" / "trusted_projects.json"
    )
    # Once-per-process announcements: each test starts as a fresh process does.
    monkeypatch.setattr(registry_handler, "_ANNOUNCED_HOMES", set())


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect drone's json writes into a temp dir; returns the measured sandbox.

    Autouse: the fleet json service writes to the real drone_json/ unless the seam is set,
    and resolves it per call, so setting it after import still works.
    """
    # Own subdirectory: a seam AT tmp_path creates tmp_path/drone/, colliding with tests' own dirs.
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


_REAL_RUN = subprocess.run
GITHUB_SLUG = "AIOSAI/AIPass"


def github_stand_in(answers: dict[str, object], calls: list[tuple[list[str], str | None]]):
    """gh answering from *answers*, keyed by its argv after 'gh'; any other gh call is GitHub's 404. git is real.

    Patching any module's ``subprocess.run`` swaps the one shared function, so git must pass through.
    """

    def run(argv: list[str], *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if argv[0] != "gh":
            return _REAL_RUN(argv, *args, **kwargs)
        calls.append((list(argv[1:]), kwargs.get("input")))
        answer = answers.get(" ".join(argv[1:]))
        if answer is None:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr="gh: Not Found (HTTP 404)")
        return subprocess.CompletedProcess(argv, 0, stdout=answer if isinstance(answer, str) else json.dumps(answer))

    return run


def chore_ledger(tmp_path: Path) -> list[dict]:
    """The GitHub chore records, read from beside the test's isolated deletion log."""
    path = tmp_path / "git_gh_writes.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


@pytest.fixture()
def aipass_github(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An AIPass root whose origin is github.com/AIOSAI/AIPass, standing in devpulse's seat; returns the root.

    Git reads no host config, commits as a fixed identity (a CI runner has none to auto-detect) and stops at
    tmp_path; the caller env is cleared so the seat decides who calls.
    """
    (tmp_path / "gitconfig").write_text("", encoding="utf-8")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("GIT_CEILING_DIRECTORIES", os.pathsep.join(sorted({str(tmp_path), str(tmp_path.resolve())})))
    for name in ("GIT_AUTHOR_NAME", "GIT_COMMITTER_NAME"):
        monkeypatch.setenv(name, "Door Test")
    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):
        monkeypatch.setenv(name, "door@test.invalid")
    for name in ("AIPASS_BRANCH_NAME", "AIPASS_CALLER_CWD", "AIPASS_CALLER_BRANCH", "AIPASS_CALLER_IDENTITY_SOURCE"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "aipass"
    seat = make_owner_project(root, branch_dir=root / "src" / "aipass" / "devpulse")
    for argv in (["init", "-q", "-b", "main"], ["remote", "add", "origin", f"https://github.com/{GITHUB_SLUG}.git"]):
        _REAL_RUN(["git", *argv], cwd=root, check=True, capture_output=True, text=True)
    monkeypatch.chdir(seat)
    return root


@pytest.fixture()
def builder_seat(aipass_github: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A citizen of the same project who owns nothing, standing in its own branch."""
    seat = aipass_github / "src" / "aipass" / "seedgo"
    (seat / ".trinity").mkdir(parents=True)
    (seat / ".trinity" / "passport.json").write_text(
        json.dumps({"branch_info": {"branch_name": "seedgo"}}), encoding="utf-8"
    )
    monkeypatch.chdir(seat)
    return seat
