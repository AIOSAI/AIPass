# =================== AIPass ====================
# Name: test_cadence.py
# Version: 1.0.0
# Description: Tests for cadence module (DPLAN-0200)
# Branch: hooks
# Created: 2026-06-08
# Modified: 2026-06-08
# =============================================

"""Tests for apps/modules/cadence.py.

Cadence runs MULTI-PROCESS in production: each UserPromptSubmit hook is a
separate OS process. Tests model that by resetting the module _turn cache
between calls (= new process) and aging the state file past the mtime
debounce window (= a real prior turn, not a sibling in the same turn).
"""

import contextlib
import json
import importlib
import os
import time
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import cadence

MODULE = "aipass.hooks.apps.modules.cadence"


def _reset_module_globals():
    """Reset module-level caches between tests (also = simulate a new process)."""
    import aipass.hooks.apps.modules.cadence as mod

    mod._turn = None
    mod._config = None


def _write_state(tmp_path, turn, token=-1, session="test-session", aged=True):
    """Write a cadence state file. aged=True backdates mtime past the debounce
    window so it reads as a PREVIOUS turn; aged=False = sibling in same turn."""
    state_file = tmp_path / f"aipass-cadence-{session}.json"
    state_file.write_text(json.dumps({"turn": turn, "token": token}))
    if aged:
        old = time.time() - 10
        os.utime(state_file, (old, old))
    return state_file


class TestShouldFire:
    def setup_method(self):
        _reset_module_globals()

    def test_turn_0_always_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        state_file = tmp_path / "aipass-cadence-test-session.json"

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert json.loads(state_file.read_text())["turn"] == 0

    def test_turn_0_fires_all_loaders(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert should_fire("branch") is True

    def test_non_fire_turn_returns_false(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        _write_state(tmp_path, turn=0)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is False

    def test_fire_turn_returns_true(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        _write_state(tmp_path, turn=3)

        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": True, "period": 5, "loaders": {"global": {"offset": 4}}}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_cadence_disabled_always_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 1}))

        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": False}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_no_session_id_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                assert should_fire("global") is True

    def test_counter_increments_once_across_sibling_processes(self, tmp_path):
        """Each loader is a SEPARATE OS process. The counter must advance
        exactly once per real turn no matter how many siblings call it."""
        from aipass.hooks.apps.modules.cadence import should_fire

        state_file = _write_state(tmp_path, turn=3)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global")
            for _ in range(4):  # 4 more siblings, each a fresh process
                _reset_module_globals()
                should_fire("branch")
            data = json.loads(state_file.read_text())
            assert data["turn"] == 4

    def test_sibling_processes_agree_on_turn_no_leapfrog(self, tmp_path):
        """The S210 live bug: global saw turn N, branch saw N+1 — they
        leapfrogged and never both fired. Both siblings must see the SAME
        turn and make the SAME decision."""
        from aipass.hooks.apps.modules.cadence import should_fire

        _write_state(tmp_path, turn=4)  # next real turn = 5 = fire (5 % 5 == 0)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            _reset_module_globals()  # branch runs as a separate process
            assert should_fire("branch") is True

    def test_token_backstop_blocks_double_increment(self, tmp_path):
        """Even past the debounce window, an unchanged transcript token means
        no new turn happened — the counter must not advance."""
        from aipass.hooks.apps.modules.cadence import should_fire

        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 100)
        state_file = _write_state(tmp_path, turn=3, token=100)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global", {"transcript_path": str(transcript)})
            assert json.loads(state_file.read_text())["turn"] == 3

    def test_reset_special_case_survives_debounce(self, tmp_path):
        """turn < 0 (post-compact reset) must ALWAYS increment to 0, even when
        the reset just happened (fresh mtime would normally debounce)."""
        from aipass.hooks.apps.modules.cadence import should_fire

        state_file = _write_state(tmp_path, turn=-1, aged=False)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert json.loads(state_file.read_text())["turn"] == 0

    def test_period_zero_always_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 2}))

        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": True, "period": 0}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_stagger_offsets(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps({"enabled": True, "period": 5, "loaders": {"global": {"offset": 0}, "branch": {"offset": 2}}})
        )

        _write_state(tmp_path, turn=4)

        from aipass.hooks.apps.modules.cadence import should_fire

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True
            assert should_fire("branch") is False

    def test_unknown_loader_uses_offset_zero(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        _write_state(tmp_path, turn=4)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("unknown_loader") is True


class TestResetCounter:
    def setup_method(self):
        _reset_module_globals()

    def test_reset_writes_minus_one(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        data = json.loads(state_file.read_text())
        assert data["turn"] == -1

    def test_reset_then_next_turn_is_zero(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter, should_fire

        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            reset_counter()

        _reset_module_globals()

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            data = json.loads(state_file.read_text())
            assert data["turn"] == 0

    def test_reset_no_session_id_is_noop(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter()

        assert not list(tmp_path.glob("aipass-cadence-*"))

    def test_reset_creates_file_if_missing(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        state_file = tmp_path / "aipass-cadence-test-session.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text())["turn"] == -1


class TestConsumeRegroupPending:
    """DPLAN-0276: PostToolUse backstop consumes the flag reset_counter() sets."""

    def setup_method(self):
        _reset_module_globals()

    def test_returns_false_when_no_state_file(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import consume_regroup_pending

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            assert consume_regroup_pending() is False

    def test_returns_true_once_after_reset(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import consume_regroup_pending, reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()
            assert consume_regroup_pending() is True
            assert consume_regroup_pending() is False

    def test_survives_multiple_back_to_back_resets_still_fires_once(self, tmp_path):
        """Replays the incident: several PreCompacts fire with no intervening
        UserPromptSubmit. The flag must still be pending exactly once total,
        not once per reset."""
        from aipass.hooks.apps.modules.cadence import consume_regroup_pending, reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()
            reset_counter()
            reset_counter()
            assert consume_regroup_pending() is True
            assert consume_regroup_pending() is False

    def test_fallback_to_hook_data_session_id(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import consume_regroup_pending, reset_counter

        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter(hook_data={"session_id": "fallback-id"})
                assert consume_regroup_pending(hook_data={"session_id": "fallback-id"}) is True
                assert consume_regroup_pending(hook_data={"session_id": "fallback-id"}) is False

    def test_real_turn_after_reset_implicitly_clears_pending(self, tmp_path):
        """Once a real UserPromptSubmit turn fires (turn 0), _load_and_increment
        overwrites state without regroup_pending — so a late-arriving normal turn
        clears the backstop flag too, even if PostToolUse never consumed it."""
        from aipass.hooks.apps.modules.cadence import consume_regroup_pending, reset_counter, should_fire

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            reset_counter()

        _reset_module_globals()

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert consume_regroup_pending() is False


class TestConfig:
    def setup_method(self):
        _reset_module_globals()

    def test_defaults_used_when_no_config_file(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import _load_config

        with patch(f"{MODULE}._CONFIG_PATH", tmp_path / "nonexistent.json"):
            config = _load_config()

        assert config["enabled"] is True
        assert config["period"] == 5
        assert config["loaders"]["branch"]["offset"] == 0
        assert "global" not in config["loaders"]

    def test_defaults_include_tiered_loaders(self, tmp_path):
        """Fresh clone with no cadence_config.json gets tiered cadence out of the box."""
        from aipass.hooks.apps.modules.cadence import _load_config

        with patch(f"{MODULE}._CONFIG_PATH", tmp_path / "nonexistent.json"):
            config = _load_config()

        assert config["loaders"]["tier0"]["period"] == 5
        assert config["loaders"]["navmap"]["period"] == 5
        assert config["loaders"]["navmap"]["offset"] == 0

    def test_config_deep_merges_over_defaults(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import _load_config

        config_file = tmp_path / "cadence.json"
        config_file.write_text(json.dumps({"period": 10, "loaders": {"global": {"offset": 3}}}))

        with patch(f"{MODULE}._CONFIG_PATH", config_file):
            config = _load_config()

        assert config["period"] == 10
        assert config["loaders"]["global"]["offset"] == 3
        assert config["loaders"]["branch"]["offset"] == 0
        assert config["enabled"] is True

    def test_bad_config_falls_back_to_defaults(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import _load_config

        config_file = tmp_path / "cadence.json"
        config_file.write_text("not valid json{{{")

        with patch(f"{MODULE}._CONFIG_PATH", config_file):
            config = _load_config()

        assert config["period"] == 5


class TestDeepMerge:
    def test_nested_merge(self):
        from aipass.hooks.apps.modules.cadence import _deep_merge

        base = {"a": 1, "b": {"c": 2, "d": 3}}
        updates = {"b": {"c": 99}, "e": 4}
        result = _deep_merge(base, updates)

        assert result["a"] == 1
        assert result["b"]["c"] == 99
        assert result["b"]["d"] == 3
        assert result["e"] == 4

    def test_overwrites_non_dict(self):
        from aipass.hooks.apps.modules.cadence import _deep_merge

        base = {"a": [1, 2]}
        result = _deep_merge(base, {"a": [3]})
        assert result["a"] == [3]


class TestPerSessionIsolation:
    def setup_method(self):
        _reset_module_globals()

    def test_different_sessions_use_different_files(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        state_a = _write_state(tmp_path, turn=4, session="session-a")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "session-a"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global")
            data_a = json.loads(state_a.read_text())
            assert data_a["turn"] == 5

        _reset_module_globals()

        state_b = tmp_path / "aipass-cadence-session-b.json"
        assert not state_b.exists()

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "session-b"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            data_b = json.loads(state_b.read_text())
            assert data_b["turn"] == 0


class TestModuleInterface:
    def setup_method(self):
        _reset_module_globals()

    def test_handle_command_cadence_returns_true(self):
        from aipass.hooks.apps.modules.cadence import handle_command

        with patch(f"{MODULE}.print_introspection"):
            assert handle_command("cadence", []) is True

    def test_handle_command_unknown_returns_false(self):
        from aipass.hooks.apps.modules.cadence import handle_command

        assert handle_command("other", []) is False

    def test_print_introspection_runs(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import print_introspection

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            print_introspection()


class TestCompactIntegration:
    def setup_method(self):
        _reset_module_globals()

    def test_compact_handler_resets_cadence(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}))

        import aipass.hooks.apps.modules.cadence as cadence_mod

        with (
            patch.object(cadence_mod, "_GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            mock_cadence = importlib.import_module("aipass.hooks.apps.modules.cadence")
            mock_cadence.reset_counter()

        data = json.loads(state_file.read_text())
        assert data["turn"] == -1


class TestLoaderCadenceGuard:
    def setup_method(self):
        _reset_module_globals()

    def test_tier0_kernel_fires_every_turn(self, tmp_path):
        """tier0 has period:1 — fires on every turn including non-fire turns for others."""
        from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1}},
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            result = handle({})

        assert result["exit_code"] == 0

    def test_branch_loader_skips_on_non_fire_turn(self, tmp_path):
        """Skip = empty stdout AND no sound key — a skipped loader is SILENT."""
        from aipass.hooks.apps.handlers.prompt.branch_loader import handle

        _write_state(tmp_path, turn=0)  # next turn = 1 = skip

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            result = handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result


class TestResetCounterObservability:
    """Tests for reset_counter fail-loud logging and session ID tracking."""

    def setup_method(self):
        _reset_module_globals()

    def test_reset_logs_session_id_and_prev_turn(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        _write_state(tmp_path, turn=11)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            reset_counter()

        reset_calls = [c for c in mock_logger.info.call_args_list if "post-compact re-injection" in str(c)]
        assert len(reset_calls) == 1
        fmt_str = reset_calls[0][0][0]
        fmt_args = reset_calls[0][0][1:]
        log_line = fmt_str % fmt_args
        assert "session=test-ses" in log_line
        assert "prev_turn=11" in log_line

    def test_reset_no_session_logs_warning(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter()

        calls = [str(c) for c in mock_logger.info.call_args_list]
        warning_calls = [c for c in calls if "SKIPPED" in c]
        assert len(warning_calls) == 1

    def test_reset_fallback_to_hook_data_session_id(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        state_file = tmp_path / "aipass-cadence-fallback-id.json"
        state_file.write_text(json.dumps({"turn": 5}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter(hook_data={"session_id": "fallback-id"})

        data = json.loads(state_file.read_text())
        assert data["turn"] == -1

    def test_reset_fallback_creates_file_if_missing(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter(hook_data={"session_id": "new-fallback"})

        state_file = tmp_path / "aipass-cadence-new-fallback.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text())["turn"] == -1

    def test_reset_env_takes_priority_over_hook_data(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        env_file = tmp_path / "aipass-cadence-env-session.json"
        env_file.write_text(json.dumps({"turn": 9}))

        hook_file = tmp_path / "aipass-cadence-hook-session.json"
        hook_file.write_text(json.dumps({"turn": 3}))

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "env-session"}),
        ):
            reset_counter(hook_data={"session_id": "hook-session"})

        assert json.loads(env_file.read_text())["turn"] == -1
        assert json.loads(hook_file.read_text())["turn"] == 3

    def test_reset_hook_data_empty_session_id_logs_skip(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", env, clear=True):
                reset_counter(hook_data={"session_id": ""})

        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("SKIPPED" in c for c in calls)

    def test_reset_prev_turn_from_corrupt_file(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text("not valid json{{{")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        data = json.loads(state_file.read_text())
        assert data["turn"] == -1


class TestPostCompactDeterminism:
    """Prove that post-compaction reload fires ALL loaders deterministically."""

    def setup_method(self):
        _reset_module_globals()

    def test_all_tiered_loaders_fire_after_reset(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter, should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {
                        "tier0": {"period": 1},
                        "navmap": {"period": 5, "offset": 0},
                        "branch": {"offset": 0},
                    },
                }
            )
        )

        _write_state(tmp_path, turn=11)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            reset_counter()

        _reset_module_globals()

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0") is True
            _reset_module_globals()
            assert should_fire("navmap") is True
            _reset_module_globals()
            assert should_fire("branch") is True

    def test_reset_at_any_turn_produces_turn_zero(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter, should_fire

        for prev_turn in [0, 1, 4, 5, 10, 11, 99]:
            _reset_module_globals()
            _write_state(tmp_path, turn=prev_turn)

            with (
                patch(f"{MODULE}._GUARD_DIR", tmp_path),
                patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
                patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
            ):
                reset_counter()

            _reset_module_globals()

            with (
                patch(f"{MODULE}._GUARD_DIR", tmp_path),
                patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
                patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
            ):
                result = should_fire("navmap")
                state = json.loads((tmp_path / "aipass-cadence-test-session.json").read_text())
                assert state["turn"] == 0, f"Expected turn 0 after reset from {prev_turn}"
                assert result is True, f"navmap should fire after reset from turn {prev_turn}"

    def test_compact_handler_calls_reset_with_hook_data(self):
        from aipass.hooks.apps.handlers.lifecycle.compact import handle

        import tempfile

        hook_data = {"cwd": tempfile.gettempdir() + "/fake", "session_id": "test-123"}

        with (
            patch("importlib.import_module") as mock_import,
        ):
            mock_cadence = mock_import.return_value
            result = handle(hook_data)

        mock_cadence.reset_counter.assert_called_once_with(hook_data=hook_data, caller="compact")
        assert result["exit_code"] == 0

    def test_double_reset_is_idempotent(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import reset_counter

        _write_state(tmp_path, turn=11)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()
            _reset_module_globals()
            reset_counter()

        state_file = tmp_path / "aipass-cadence-test-session.json"
        data = json.loads(state_file.read_text())
        assert data["turn"] == -1


class TestPerLoaderPeriod:
    def setup_method(self):
        _reset_module_globals()

    def test_loader_period_overrides_global(self, tmp_path):
        """A loader with period:1 fires every turn, even when global period is 5."""
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1}, "global": {"offset": 0}},
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("tier0") is True
            _reset_module_globals()
            assert should_fire("global") is False

    def test_loader_without_period_uses_global(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"global": {"offset": 0}},
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is False

    def test_tier0_period_1_fires_every_turn(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1}},
                }
            )
        )

        for turn_val in range(1, 8):
            _reset_module_globals()
            _write_state(tmp_path, turn=turn_val - 1)

            with (
                patch(f"{MODULE}._GUARD_DIR", tmp_path),
                patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
                patch(f"{MODULE}._CONFIG_PATH", config),
            ):
                assert should_fire("tier0") is True, f"tier0 should fire on turn {turn_val}"

    def test_navmap_period_5_skips_non_fire_turns(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("navmap") is False

    def test_navmap_fires_on_turn_0(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
                }
            )
        )

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("navmap") is True

    def test_navmap_fires_after_reset_counter(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire, reset_counter

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
                }
            )
        )

        _write_state(tmp_path, turn=7)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            reset_counter()

        _reset_module_globals()

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("navmap") is True

    def test_per_loader_period_zero_always_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"always": {"period": 0}},
                }
            )
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("always") is True


def _write_mail_state(tmp_path, last_fired, session="test-session"):
    """Write the mail-loop state file (last turn the banner fired)."""
    state_file = tmp_path / f"aipass-mailcadence-{session}.json"
    state_file.write_text(json.dumps({"last_fired_turn": last_fired}))
    return state_file


@contextlib.contextmanager
def _mail_env(tmp_path, config):
    """Standard patch stack for mail cadence tests."""
    with (
        patch(f"{MODULE}._GUARD_DIR", tmp_path),
        patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        patch(f"{MODULE}._CONFIG_PATH", config),
    ):
        yield


class TestShouldFireMail:
    """Mail banner cadence: announce on arrival, repeat every Nth turn, silent at zero."""

    def setup_method(self):
        _reset_module_globals()

    def _config(self, tmp_path, period=5, enabled=True):
        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": enabled, "period": 5, "loaders": {"email": {"period": period}}}))
        return config

    def test_zero_mail_is_silent(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(0, {}) is False

    def test_first_sighting_fires(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        _write_state(tmp_path, turn=6)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_fires_at_plus_period_not_plus_one(self, tmp_path):
        """The canary: over an 11-turn session with mail always present, the banner
        fires on arrival and then only every 5th turn — never on consecutive turns."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path, period=5)
        fired_on = []
        for turn in range(11):
            _reset_module_globals()
            _write_state(tmp_path, turn=turn - 1)
            with _mail_env(tmp_path, config):
                if should_fire_mail(3, {}):
                    fired_on.append(turn)

        assert fired_on == [0, 5, 10]

    def test_empty_inbox_clears_state_so_next_arrival_announces(self, tmp_path):
        """Read your mail at turn 1, new mail lands at turn 2 -> announced at turn 2,
        not held until turn 5. Clearing on zero is what makes that true."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)

        _write_state(tmp_path, turn=-1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(2, {}) is True  # turn 0, first sighting

        _reset_module_globals()
        _write_state(tmp_path, turn=0)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(0, {}) is False  # turn 1, inbox emptied

        _reset_module_globals()
        _write_state(tmp_path, turn=1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True  # turn 2, fresh arrival announces

    def test_without_clearing_the_next_arrival_would_be_muted(self, tmp_path):
        """Control for the test above: same turn 2 arrival, but with stale state left
        behind (as if zero had not cleared it) the banner is suppressed."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        _write_mail_state(tmp_path, last_fired=0)
        _write_state(tmp_path, turn=1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is False

    def test_counter_reset_re_announces(self, tmp_path):
        """After a compact the turn counter restarts at 0 while mail state says 7.
        Negative elapsed must re-announce, not go permanently silent."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        _write_mail_state(tmp_path, last_fired=7)
        _write_state(tmp_path, turn=-1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_cadence_disabled_fires_every_turn(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path, enabled=False)
        _write_mail_state(tmp_path, last_fired=3)
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_period_zero_fires_every_turn(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path, period=0)
        _write_mail_state(tmp_path, last_fired=3)
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_disabled_still_silent_at_zero(self, tmp_path):
        """Disabled restores fire-every-turn, but never invents a banner for no mail."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path, enabled=False)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(0, {}) is False

    def test_no_session_id_fires(self, tmp_path):
        """No session = no state to loop on; announce rather than swallow mail."""
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", env, clear=True),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire_mail(1, {}) is True

    def test_corrupt_mail_state_treated_as_never_fired(self, tmp_path):
        from aipass.hooks.apps.modules.cadence import should_fire_mail

        config = self._config(tmp_path)
        (tmp_path / "aipass-mailcadence-test-session.json").write_text("{not json")
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True


class TestShouldFireAdvisory:
    """Throttle for STANDING conditions — states that stay true for days and
    re-assert on every qualifying edit. @devpulse's seat sat over the todos cap
    long enough to write 209 identical lines and trip @trigger's
    repeat-signature escalation (Patrick's ruling, 2026-08-19)."""

    @pytest.fixture(autouse=True)
    def _state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "advisory-test")
        self.tmp = tmp_path

    def _at_turn(self, turn):
        return patch.object(cadence, "current_turn", return_value=turn)

    def test_fires_the_first_time(self):
        with self._at_turn(1):
            assert cadence.should_fire_advisory("todos_count") is True

    def test_silent_on_the_very_next_turn(self):
        with self._at_turn(1):
            cadence.should_fire_advisory("todos_count")
        with self._at_turn(2):
            assert cadence.should_fire_advisory("todos_count") is False

    def test_silent_for_repeated_edits_within_one_turn(self):
        """The actual defect: many edits, one turn, 209 log lines."""
        with self._at_turn(7):
            fired = [cadence.should_fire_advisory("todos_count") for _ in range(20)]
        assert fired.count(True) == 1

    def test_fires_again_after_the_period(self):
        with self._at_turn(1):
            cadence.should_fire_advisory("todos_count")
        with self._at_turn(1 + cadence.ADVISORY_PERIOD):
            assert cadence.should_fire_advisory("todos_count") is True

    def test_silent_one_turn_short_of_the_period(self):
        with self._at_turn(1):
            cadence.should_fire_advisory("todos_count")
        with self._at_turn(cadence.ADVISORY_PERIOD):
            assert cadence.should_fire_advisory("todos_count") is False

    def test_a_counter_reset_re_announces(self):
        """Backwards means compact or a new session — the old numbering must
        not buy silence in the new one."""
        with self._at_turn(50):
            cadence.should_fire_advisory("todos_count")
        with self._at_turn(2):
            assert cadence.should_fire_advisory("todos_count") is True

    def test_advisories_are_throttled_independently(self):
        with self._at_turn(1):
            assert cadence.should_fire_advisory("todos_count") is True
            assert cadence.should_fire_advisory("something_else") is True

    def test_no_session_id_cannot_throttle_so_it_fires(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert cadence.should_fire_advisory("todos_count") is True

    def test_unreadable_turn_falls_back_to_elapsed_time(self):
        """An unreadable counter must still throttle — degrading to
        fire-every-time is the bug being fixed, not a fallback."""
        with self._at_turn(None):
            assert cadence.should_fire_advisory("todos_count") is True
            assert cadence.should_fire_advisory("todos_count") is False

    def test_time_fallback_fires_once_the_window_passes(self):
        with self._at_turn(None):
            cadence.should_fire_advisory("todos_count")
            path = self.tmp / "aipass-advisory-todos_count-advisory-test.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            data["at"] = data["at"] - cadence.ADVISORY_SECONDS - 1
            path.write_text(json.dumps(data), encoding="utf-8")
            assert cadence.should_fire_advisory("todos_count") is True

    def test_corrupt_state_is_treated_as_never_fired(self):
        path = self.tmp / "aipass-advisory-todos_count-advisory-test.json"
        path.write_text("{ not json", encoding="utf-8")
        with self._at_turn(3):
            assert cadence.should_fire_advisory("todos_count") is True

    def test_unwritable_state_still_fires(self):
        """Losing the advisory is worse than repeating it."""
        with self._at_turn(1), patch.object(cadence.Path, "write_text", side_effect=OSError("read-only")):
            assert cadence.should_fire_advisory("todos_count") is True


class TestCurrentTurn:
    """Read-only: a PreToolUse consumer must never advance the counter — many
    tool calls share one turn, and the token guard keys off UserPromptSubmit."""

    @pytest.fixture(autouse=True)
    def _state(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "turn-test")
        self.path = tmp_path / "aipass-cadence-turn-test.json"

    def test_reads_the_stored_turn(self):
        self.path.write_text(json.dumps({"turn": 12, "token": 5}), encoding="utf-8")
        assert cadence.current_turn() == 12

    def test_does_not_advance_it(self):
        self.path.write_text(json.dumps({"turn": 12, "token": 5}), encoding="utf-8")
        for _ in range(5):
            cadence.current_turn()
        assert json.loads(self.path.read_text(encoding="utf-8"))["turn"] == 12

    def test_missing_state_is_none(self):
        assert cadence.current_turn() is None

    def test_corrupt_state_is_none(self):
        self.path.write_text("{ not json", encoding="utf-8")
        assert cadence.current_turn() is None

    def test_no_session_id_is_none(self, monkeypatch):
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        assert cadence.current_turn() is None
