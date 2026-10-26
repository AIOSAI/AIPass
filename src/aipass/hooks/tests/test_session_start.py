# =================== AIPass ====================
# Name: test_session_start.py
# Version: 1.3.0
# Description: Tests for the SessionStart handlers: cadence reset, the culture file, the session pointer
# Branch: hooks
# Created: 2026-07-07
# Modified: 2026-10-25
# =============================================

"""Tests for apps/handlers/lifecycle/session_start.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(constant) — _SKIP_SOURCES' member strings, pinned by the resume/compact tests' effect
# seedgo: no-test-needed(documentation) — that handle() carries a docstring
# seedgo: no-test-needed(ruff) — that the module parses and its logger import resolves

import json
import os
import sys
from unittest.mock import patch

import pytest

import aipass.hooks.apps.modules.cadence as cadence_mod
import aipass.hooks.apps.modules.cc_sessions as cc_sessions_mod
from aipass.hooks.apps.handlers.lifecycle.session_start import handle, handle_culture, handle_session_pointer
from aipass.hooks.apps.modules.cadence import should_fire

CADENCE_MODULE = "aipass.hooks.apps.modules.cadence"


def _branch(tmp_path):
    (tmp_path / ".trinity").mkdir()
    (tmp_path / ".trinity" / "passport.json").write_text("{}", encoding="utf-8")
    return tmp_path


def _pointer(branch) -> dict | None:
    path = branch / ".ai_mail.local" / "session.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _rollout(tmp_path, source: str) -> str:
    """A Codex rollout whose first line is session_meta, as the SessionStart hook finds it."""
    path = tmp_path / "rollout.jsonl"
    meta = {"type": "session_meta", "payload": {"id": "s-codex", "source": source}}
    path.write_text(json.dumps(meta) + "\n", encoding="utf-8")
    return str(path)


@pytest.fixture
def claude_argv(monkeypatch):
    """Stand in for the process walk: the argv of the nearest `claude` ancestor (an interactive one by default)."""
    argv = {"args": ["/home/u/.local/bin/claude", "--resume", "s-claude"]}
    monkeypatch.setattr(cc_sessions_mod, "cli_ancestor", lambda name: argv["args"] if name == "claude" else None)
    return argv


@pytest.mark.usefixtures("claude_argv")
class TestSessionPointer:
    def test_a_codex_session_start_records_the_session_and_codex(self, tmp_path):
        branch = _branch(tmp_path)
        hook_data = {
            "session_id": "s-codex",
            "source": "startup",
            "cwd": str(branch),
            "provider": "codex",
            "transcript_path": _rollout(tmp_path, "cli"),
        }
        assert handle_session_pointer(hook_data) == {"stdout": "", "exit_code": 0}
        pointer = _pointer(branch)
        assert pointer is not None
        assert (pointer["session_id"], pointer["provider"], pointer["set_by"]) == ("s-codex", "codex", "session-start")

    def test_a_codex_exec_session_writes_no_pointer(self, tmp_path):
        branch = _branch(tmp_path)
        hook_data = {"session_id": "s-codex", "cwd": str(branch), "provider": "codex"}
        handle_session_pointer({**hook_data, "transcript_path": _rollout(tmp_path, "exec")})
        assert _pointer(branch) is None

    def test_an_unreadable_codex_rollout_writes_no_pointer(self, tmp_path):
        branch = _branch(tmp_path)
        hook_data = {"session_id": "s-codex", "cwd": str(branch), "provider": "codex"}
        handle_session_pointer({**hook_data, "transcript_path": str(tmp_path / "missing.jsonl")})
        assert _pointer(branch) is None

    def test_a_payload_naming_no_provider_records_claude(self, tmp_path):
        branch = _branch(tmp_path)
        handle_session_pointer({"session_id": "s-claude", "source": "resume", "cwd": str(branch)})
        pointer = _pointer(branch)
        assert pointer is not None
        assert (pointer["session_id"], pointer["provider"]) == ("s-claude", "claude")

    @pytest.mark.parametrize("flag", ["-p", "--print"])
    def test_a_headless_claude_session_writes_no_pointer(self, tmp_path, claude_argv, flag):
        claude_argv["args"] = ["/home/u/.local/bin/claude", "--resume", "s-claude", flag, "Hi."]
        branch = _branch(tmp_path)
        handle_session_pointer({"session_id": "s-claude", "source": "resume", "cwd": str(branch)})
        assert _pointer(branch) is None

    def test_no_claude_ancestor_writes_no_pointer(self, tmp_path, claude_argv):
        claude_argv["args"] = None
        branch = _branch(tmp_path)
        handle_session_pointer({"session_id": "s-claude", "source": "startup", "cwd": str(branch)})
        assert _pointer(branch) is None

    def test_a_compact_leaves_the_pointer_alone(self, tmp_path):
        branch = _branch(tmp_path)
        handle_session_pointer({"session_id": "s1", "source": "compact", "cwd": str(branch)})
        assert _pointer(branch) is None

    def test_no_passport_means_no_branch_and_no_write(self, tmp_path):
        handle_session_pointer({"session_id": "s1", "source": "startup", "cwd": str(tmp_path)})
        assert _pointer(tmp_path) is None

    @pytest.mark.parametrize("session_id", ["", None, 7])
    def test_no_usable_session_id_writes_nothing(self, tmp_path, session_id):
        branch = _branch(tmp_path)
        handle_session_pointer({"session_id": session_id, "source": "startup", "cwd": str(branch)})
        assert _pointer(branch) is None


class TestCulture:
    def test_the_culture_file_under_aipass_home_is_injected_whole(self, tmp_path, monkeypatch):
        (tmp_path / ".claude").mkdir()
        (tmp_path / ".claude" / "AGENTS.md").write_text("# AIPass - Culture\nCode is truth.\n", encoding="utf-8")
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
        assert handle_culture({}) == {"stdout": "# AIPass - Culture\nCode is truth.\n", "exit_code": 0}

    def test_no_culture_file_injects_nothing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AIPASS_HOME", str(tmp_path))
        assert handle_culture({}) == {"stdout": "", "exit_code": 0}

    def test_aipass_home_unset_injects_nothing(self, monkeypatch):
        monkeypatch.delenv("AIPASS_HOME", raising=False)
        assert handle_culture({}) == {"stdout": "", "exit_code": 0}


def _reset_cadence_globals(monkeypatch: pytest.MonkeyPatch) -> None:
    """Model a fresh process; monkeypatch puts the module's own values back at teardown."""
    monkeypatch.setattr(cadence_mod, "_turn", None)
    monkeypatch.setattr(cadence_mod, "_config", None)


@pytest.fixture
def _fresh_cadence(monkeypatch):
    _reset_cadence_globals(monkeypatch)


def _write_state(tmp_path, turn, session="test-session"):
    import time

    state_file = tmp_path / f"aipass-cadence-{session}.json"
    state_file.write_text(json.dumps({"turn": turn, "token": -1}), encoding="utf-8")
    old = time.time() - 10
    os.utime(state_file, (old, old))
    return state_file


@pytest.mark.usefixtures("_fresh_cadence")
class TestSessionStartHandler:
    def test_startup_resets_cadence(self, tmp_path):
        state_file = _write_state(tmp_path, turn=7)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "startup", "session_id": "test-session"})

        assert result["exit_code"] == 0
        assert result["sound"] == "cadence reset"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1

    def test_clear_resets_cadence(self, tmp_path):
        state_file = _write_state(tmp_path, turn=3)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "clear", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1

    def test_resume_skips_reset(self, tmp_path):
        state_file = _write_state(tmp_path, turn=7)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "resume", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == 7

    def test_compact_source_skips_reset(self, tmp_path):
        """source=compact is skipped — PreCompact (compact.py) already reset for the
        same boundary. A duplicate reset here re-arms the regroup token a second
        time per compact (DPLAN-0278 over-fire mechanism)."""
        state_file = _write_state(tmp_path, turn=5)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"source": "compact", "session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == 5

    def test_empty_source_resets(self, tmp_path):
        state_file = _write_state(tmp_path, turn=4)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            result = handle({"session_id": "test-session"})

        assert result["exit_code"] == 0
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1

    def test_no_stdout_output(self, tmp_path, monkeypatch):
        """The real cadence runs, its state under tmp_path (fleet green leg 7: no importlib patch)."""
        monkeypatch.setattr(cadence_mod, "_GUARD_DIR", tmp_path)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "no-stdout")
        (tmp_path / "aipass-cadence-no-stdout.json").write_text(json.dumps({"turn": 7}), encoding="utf-8")
        result = handle({"source": "startup"})

        assert result["stdout"] == ""
        assert json.loads((tmp_path / "aipass-cadence-no-stdout.json").read_text(encoding="utf-8"))["turn"] == -1

    def test_cadence_import_failure_does_not_crash(self, monkeypatch):
        """None under the name in sys.modules makes the real import raise ModuleNotFoundError."""
        monkeypatch.setitem(sys.modules, cadence_mod.__name__, None)
        result = handle({"source": "startup"})

        assert result == {"stdout": "", "exit_code": 0}


@pytest.mark.usefixtures("_fresh_cadence")
class TestSessionStartCadenceIntegration:
    """End-to-end: SessionStart reset -> next turn fires all loaders."""

    def test_clear_then_all_loaders_fire(self, tmp_path, monkeypatch):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {
                        "tier0": {"period": 5, "offset": 0},
                        "navmap": {"period": 5, "offset": 0},
                        "branch": {"offset": 0},
                    },
                }
            ),
            encoding="utf-8",
        )

        _write_state(tmp_path, turn=3)

        # The siblings are handed a transcript_path, which is what keeps them on
        # ONE turn in production: the token is the transcript's size, identical
        # across every loader of the same turn, and _should_increment refuses to
        # increment while it matches. Without it the token is 0, the token guard
        # is disabled, and the only thing holding the three calls together is
        # the 2.0 s mtime debounce — so this unit went red whenever a loaded
        # full-suite run put more than two seconds between the first call and
        # the third (measured 2026-09-12: green alone, red twice in a 207 s
        # run). A real clock was deciding a question about token identity.
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text('{"type": "user"}\n', encoding="utf-8")
        turn_data = {"transcript_path": str(transcript)}

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            handle({"source": "clear", "session_id": "test-session"})

        _reset_cadence_globals(monkeypatch)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0", turn_data) is True
            _reset_cadence_globals(monkeypatch)
            assert should_fire("navmap", turn_data) is True
            _reset_cadence_globals(monkeypatch)
            assert should_fire("branch", turn_data) is True

    def test_resume_does_not_reset_counter_continues(self, tmp_path, monkeypatch):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {
                        "tier0": {"period": 5, "offset": 0},
                        "navmap": {"period": 5, "offset": 0},
                    },
                }
            ),
            encoding="utf-8",
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            handle({"source": "resume", "session_id": "test-session"})

        _reset_cadence_globals(monkeypatch)

        with (
            patch(f"{CADENCE_MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{CADENCE_MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0") is False
            _reset_cadence_globals(monkeypatch)
            assert should_fire("navmap") is False
