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

import json
import importlib
import os
import time
from unittest.mock import patch

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
