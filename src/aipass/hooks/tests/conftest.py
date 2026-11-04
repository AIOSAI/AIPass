# =================== AIPass ====================
# Name: conftest.py
# Version: 2.8.1
# Description: Shared pytest fixtures for hooks tests
# Branch: hooks
# Layer: tests
# Created: 2026-05-18
# Modified: 2026-11-04
# =============================================

"""Shared pytest fixtures for hooks tests.

``AIPASS_TEST_LOG_DIR`` is armed at import (the repo-root conftest refuses a run that reaches
the json shim with it unset) and again per test by ``mock_infrastructure``.
"""

import json
import os
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from typing import Generator
from unittest.mock import patch

if "AIPASS_TEST_LOG_DIR" not in os.environ:
    os.environ["AIPASS_TEST_LOG_DIR"] = tempfile.mkdtemp(prefix="aipass_test_logs_")

import pytest

from aipass.ai_mail.apps.modules import door_dispatch_grant, door_verified_caller
from aipass.cli.apps.modules import display
from aipass.hooks.apps import sound
from aipass.hooks.apps.handlers.config import diagnostics, trust_registry
from aipass.hooks.apps.handlers.json import json_handler
from aipass.hooks.apps.handlers.lifecycle import session_boot
from aipass.hooks.apps.modules import cadence, cc_transcripts
from aipass.hooks.apps.modules import diagnostics_state as ds

collect_ignore_glob = [".archive/*"]


@pytest.fixture(autouse=True)
def isolated_engine_log(tmp_path_factory, monkeypatch) -> Path:
    """The engine's diagnostics log goes to a file under the pytest temp root, per test.

    Under pytest the real log dir is shared by every run and every seat.
    """
    sandbox = tmp_path_factory.mktemp("engine_log") / "engine.jsonl"
    monkeypatch.setattr(diagnostics, "_get_log_file", lambda: sandbox)
    return sandbox


class TriggerRecorder:
    """Stands where cli keeps its trigger: records each fire and reaches no bus."""

    def __init__(self) -> None:
        self.fired: list[tuple[str, dict]] = []

    def fire(self, event: str, **kwargs) -> None:
        self.fired.append((event, kwargs))


@pytest.fixture(autouse=True)
def recorded_cli_trigger(monkeypatch) -> TriggerRecorder:
    """cli's header fires cli_header_displayed on the real bus; here it fires on a recorder.

    The loaded flag stays set so cli never imports the real trigger in the recorder's place.
    """
    recorder = TriggerRecorder()
    monkeypatch.setattr(display, "_TRIGGER", recorder)
    monkeypatch.setattr(display, "_TRIGGER_LOADED", True)
    return recorder


@pytest.fixture(autouse=True, scope="session")
def pinned_console_width() -> None:
    """Rich sizes an unpinned console on every print: 80 on POSIX and 79 on Windows
    under pytest's capture, the terminal's width under -s, COLUMNS when exported."""
    for console in (display.CONSOLE, display.err_console):
        console.width = 200


@pytest.fixture(autouse=True)
def clean_command_state() -> Generator[None, None, None]:
    """error() marks the process failed; a test must not hand that to the next."""
    yield
    display.reset_command_state()


@pytest.fixture(autouse=True)
def mock_infrastructure(tmp_path, monkeypatch) -> Path:
    """Redirect this branch's json writes into a temp dir.

    Without the seam the shim writes the real hooks_json/; the sandbox is read off the shim so it cannot drift.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path))
    sandbox = json_handler.get_json_path("probe", "config").parent
    sandbox.mkdir(parents=True, exist_ok=True)
    return sandbox


@pytest.fixture(autouse=True)
def isolated_mute_flag(tmp_path_factory, monkeypatch) -> Path:
    """Keep every test off the owner's LIVE sound flag, and off the old mute flags is_muted() removes."""
    sandbox = tmp_path_factory.mktemp("mute_flag")
    monkeypatch.setattr(sound, "SOUND_FLAG", sandbox / "home" / "aipass-hooks-sound-on")
    monkeypatch.setattr(sound, "MUTE_FLAG", sandbox / "home" / "aipass-hooks-muted")
    monkeypatch.setattr(sound, "LEGACY_MUTE_FLAG", sandbox / "tmp" / "aipass-hooks-muted")
    return sound.SOUND_FLAG


@pytest.fixture(autouse=True)
def isolated_trust_registry(tmp_path_factory, monkeypatch) -> Path:
    """Keep the trust registry out of the LIVE ~/.aipass/trusted_projects.json.

    REGISTRY_PATH binds at import, and bootstrap() WRITES it when a test meets an absent registry.
    """
    sandbox = tmp_path_factory.mktemp("trust_registry") / "trusted_projects.json"
    monkeypatch.setattr(trust_registry, "REGISTRY_PATH", sandbox)
    return sandbox


@pytest.fixture
def temp_test_dir() -> Generator[Path, None, None]:
    """Creates temporary directory for testing, cleans up after."""
    test_dir = Path(tempfile.mkdtemp())
    yield test_dir
    if test_dir.exists():
        shutil.rmtree(test_dir)


@pytest.fixture
def sample_hooks_config() -> dict:
    """Minimal hooks.json config for testing."""
    return {
        "hooks_enabled": True,
        "UserPromptSubmit": {
            "test_hook": {
                "enabled": True,
                "command": "echo 'test output'",
                "matcher": "",
            }
        },
        "PreToolUse": {
            "matcher_hook": {
                "enabled": True,
                "command": "echo 'matched'",
                "matcher": "Edit|Write",
            },
            "disabled_hook": {
                "enabled": False,
                "command": "echo 'should not fire'",
                "matcher": "",
            },
        },
    }


@pytest.fixture
def hooks_config_file(temp_test_dir: Path, sample_hooks_config: dict) -> Path:
    """Creates a .aipass/hooks.json in temp dir."""
    config_dir = temp_test_dir / ".aipass"
    config_dir.mkdir()
    config_file = config_dir / "hooks.json"
    config_file.write_text(json.dumps(sample_hooks_config), encoding="utf-8")
    return config_file


@pytest.fixture
def mock_logger():
    """Mock the prax system logger."""
    with patch("aipass.hooks.apps.modules.engine.logger") as mock:
        yield mock


@pytest.fixture
def mock_subprocess():
    """Mock subprocess.run for hook execution tests."""
    with patch("aipass.hooks.apps.modules.engine.subprocess.run") as mock:
        yield mock


@pytest.fixture(autouse=True)
def isolated_cadence_state(tmp_path_factory, monkeypatch):
    """Keep per-session cadence/advisory state out of the LIVE seat's files.

    The state is keyed by CLAUDE_CODE_SESSION_ID, so an unisolated run reads and writes the running seat's.
    """
    monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path_factory.mktemp("cadence_state"))
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "pytest-session")


@pytest.fixture
def _restore_cadence_globals(monkeypatch):
    """Hand cadence's module caches back as they were found, whatever a test wrote."""
    monkeypatch.setattr(cadence, "_turn", None)
    monkeypatch.setattr(cadence, "_config", None)
    monkeypatch.setattr(cadence, "_turn_degraded", None)
    yield


@pytest.fixture
def _no_real_trust_banners():
    """dispatch() now runs both trust banners unconditionally on UserPromptSubmit.

    Stubbed so dispatch tests never walk CWD-to-home against the real ~/.aipass registry.
    """
    with (
        patch("aipass.hooks.apps.handlers.config.loader.trust_break_banner", return_value=None),
        patch("aipass.hooks.apps.handlers.config.loader.never_enrolled_banner", return_value=None),
    ):
        yield


_TMUX_OWN_TESTS = {
    "TestFindTmux",
    "TestTmuxSessionExists",
    "TestFindTmuxSessionForPid",
    "TestTmuxLookupsSurviveAMachineWithoutTmux",
}


@pytest.fixture
def _no_real_tmux_lookup(request):
    """Keep the MENU tests off a real subprocess.

    The menu asks tmux where each process lives: WinError 2 on the Windows runner, slow elsewhere.
    """
    if request.cls is not None and request.cls.__name__ in _TMUX_OWN_TESTS:
        yield
        return
    with patch.object(session_boot, "_find_tmux_session_for_pid", return_value=None):
        yield


@pytest.fixture
def fake_projects(tmp_path, monkeypatch):
    """Point the transcript reader at a throwaway projects root."""
    root = tmp_path / "projects_root"
    root.mkdir()
    monkeypatch.setattr(cc_transcripts, "PROJECTS_ROOT", root)
    return root


@pytest.fixture(autouse=True)
def isolated_diagnostics_state(tmp_path_factory, monkeypatch):
    """Keep the fleet-shared .diagnostics_state.json out of every test.

    Live sessions write it, so a test would read another branch's open error or erase one.
    """
    sandbox = tmp_path_factory.mktemp("diagnostics_state") / ".diagnostics_state.json"
    monkeypatch.setattr(ds, "LEGACY_FILE", sandbox)
    monkeypatch.setattr(ds, "STATE_DIR", sandbox.parent / "seats")


@pytest.fixture
def registered_projects(tmp_path: Path) -> dict:
    """AIPass, a project nested inside it, and a sibling Vera Studio, each with a REAL registry.

    Write permission reads the registries' rows, paths and ``owner`` flag; a ``{}`` registry tests only the fallback.
    """
    projects = tmp_path / "Projects"
    aipass = projects / "AIPass"
    for name in ("devpulse", "hooks", "memory", "sentry", "spawn", "flow"):
        (aipass / "src" / "aipass" / name).mkdir(parents=True)
    rows: list[dict] = [{"name": name, "path": f"src/aipass/{name}"} for name in ("HOOKS", "sentry", "spawn", "flow")]
    rows.append({"name": "memory", "path": str(aipass / "src" / "aipass" / "memory")})
    rows.append({"name": "devpulse", "path": "src/aipass/devpulse", "owner": True, "admin": True})
    (aipass / "AIPASS_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": rows}), encoding="utf-8")
    flow_json = aipass / "src" / "aipass" / "flow" / "flow_json"
    flow_json.mkdir()
    (flow_json / "PLAN_REGISTRY.json").write_text(json.dumps({"plans": {}, "next_number": 1}), encoding="utf-8")

    baud = aipass / "projects" / "baud"
    (baud / "src" / "baud" / "baud").mkdir(parents=True)
    baud_rows = [{"name": "baud", "path": "src/baud/baud", "owner": True}]
    (baud / "BAUD_REGISTRY.json").write_text(json.dumps({"metadata": {}, "branches": baud_rows}), encoding="utf-8")

    vera = projects / "Vera-Studio"
    vera_rows = {}
    for name in ("vera", "writer", "sentry"):
        (vera / "src" / "vera_studio" / name).mkdir(parents=True)
        vera_rows[name.upper()] = {"name": name.upper(), "path": f"src/vera_studio/{name}"}
    vera_rows["VERA"]["owner"] = True
    (vera / "VERA-STUDIO_REGISTRY.json").write_text(
        json.dumps({"metadata": {}, "branches": vera_rows}), encoding="utf-8"
    )

    seat = aipass / "src" / "aipass"
    vera_seat = vera / "src" / "vera_studio"
    return {
        "aipass": aipass,
        "vera": vera,
        "baud": baud,
        "devpulse": str(seat / "devpulse"),
        "hooks": str(seat / "hooks"),
        "memory": str(seat / "memory"),
        "sentry": str(seat / "sentry"),
        "spawn": str(seat / "spawn"),
        "flow": str(seat / "flow"),
        "vera_seat": str(vera_seat / "vera"),
        "writer": str(vera_seat / "writer"),
        "vera_sentry": str(vera_seat / "sentry"),
        "baud_seat": str(baud / "src" / "baud" / "baud"),
    }


@pytest.fixture(autouse=True)
def _no_inherited_dispatch_id(monkeypatch):
    """A dispatched seat's pytest inherits its AIPASS_DISPATCH_ID; every crossing test would then ask the real door."""
    monkeypatch.delenv("AIPASS_DISPATCH_ID", raising=False)


@pytest.fixture
def dispatch_grant(tmp_path: Path, monkeypatch) -> SimpleNamespace:
    """Dispatch d1's @hooks seat in a daemon session, a registry-less git tree beside it, @ai_mail's door faked.

    The fake answers as the door does and records each call; ``ended`` makes it refuse with that reason.
    """
    aipass = tmp_path / "Projects" / "AIPass"
    seat = aipass / "src" / "aipass" / "hooks"
    (seat / ".trinity").mkdir(parents=True)
    (seat / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    (aipass / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    seed = tmp_path / "Projects" / "seed"
    (seed / "src" / "hooks").mkdir(parents=True)
    for repo in (aipass, seed):
        (repo / ".git").mkdir()
        (repo / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    for name in (".git/config", "README.md", "package.json", "src/hooks/x.ts"):
        (seed / name).write_text("x\n", encoding="utf-8")
    grant = {"root": str(seed), "files": ["README.md"], "dirs": ["src/hooks"]}
    state = SimpleNamespace(
        aipass=aipass, seat=str(seat), seed=seed, grant=grant, calls=[], ended="", grantee="@hooks", admin=False
    )

    def granted(caller_branch, dispatch_id, target_path, repo_root=None, now=None):
        state.calls.append({"caller": caller_branch, "target": target_path, "repo_root": repo_root})
        root, target = Path(state.grant["root"]), Path(target_path)
        if dispatch_id != "d1":
            reason = f"dispatch {dispatch_id} is not open with a grant"
        elif state.ended:
            reason = state.ended
        elif "@" + caller_branch.lstrip("@") != state.grantee:
            reason = f"dispatch d1 was sent to {state.grantee}, not {caller_branch}"
        elif target in [root / f for f in state.grant["files"]] or any(
            target.is_relative_to(root / d) for d in state.grant["dirs"]
        ):
            return {"allowed": True, "dispatch_id": dispatch_id, "reason": f"{target} is granted"}
        else:
            reason = f"{target} is outside dispatch d1's grant"
        return {"allowed": False, "dispatch_id": dispatch_id, "reason": reason}

    def open_grants(repo_root=None, now=None):
        return [
            {
                "dispatch_id": "d1",
                "sender": "@grantor",
                "target": state.grantee,
                door_dispatch_grant.GRANT_KEY: state.grant,
            }
        ]

    monkeypatch.setattr(door_dispatch_grant, "granted", granted)
    monkeypatch.setattr(door_dispatch_grant, "open_grants", open_grants)
    monkeypatch.setattr(door_verified_caller, "is_verified_admin_caller", lambda: state.admin)
    for name in ("AIPASS_CALLER_BRANCH", "AIPASS_CALLER_CWD", "AIPASS_CALLER_IDENTITY_SOURCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AIPASS_DISPATCH_ID", "d1")
    monkeypatch.setenv("AIPASS_SESSION_TYPE", "daemon")
    return state
