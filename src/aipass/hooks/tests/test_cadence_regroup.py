# =================== AIPass ====================
# Name: test_cadence_regroup.py
# Description: Cadence's regroup and counter machinery: reset, the regroup token and part queue, config, fail-loud
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Tests for apps/modules/cadence.py: the regroup and counter machinery."""

# reset_counter and its observability, the post-compact regroup token and part
# queue, the sized fire log, the merged config and its introspection, per-session
# isolation, the loader guard and the degraded (fail-open) turn. The fire decision
# itself is test_cadence.py.

# Cadence runs MULTI-PROCESS in production: each UserPromptSubmit hook is a
# separate OS process. Tests model that by resetting the module _turn cache
# between calls (= new process) and aging the state file past the mtime
# debounce window (= a real prior turn, not a sibling in the same turn).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that cadence.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — reset_counter() and should_fire() carry docstrings
# seedgo: no-test-needed(constant) — HELP_COMMANDS' description text, pinned only as reaching print_introspection

import json
import os
from unittest.mock import patch

import pytest

from aipass.hooks.apps.handlers.lifecycle.compact import handle as _compact_handle
from aipass.hooks.apps.handlers.prompt.branch_loader import handle as _branch_loader_handle
from aipass.hooks.apps.handlers.prompt.tier0_kernel import handle as _tier0_kernel_handle
from aipass.hooks.apps.modules import cadence
from aipass.hooks.apps.modules.cadence import (
    consume_regroup_pending,
    degraded_reason,
    handle_command,
    pop_regroup_part,
    print_introspection,
    queue_regroup_parts,
    reset_counter,
    should_fire,
    should_fire_advisory,
)
from aipass.hooks.tests.support_cadence import MODULE, _kept_redirect, _reset_module_globals, _write_state

pytestmark = pytest.mark.usefixtures("_restore_cadence_globals")


class TestResetCounter:
    def setup_method(self):
        _reset_module_globals()

    def test_reset_writes_minus_one(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}), encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1

    def test_reset_then_next_turn_is_zero(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}), encoding="utf-8")

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
            data = json.loads(state_file.read_text(encoding="utf-8"))
            assert data["turn"] == 0

    def test_reset_no_session_id_is_noop(self, tmp_path):
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter()

        assert not list(tmp_path.glob("aipass-cadence-*"))

    def test_reset_creates_file_if_missing(self, tmp_path):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        state_file = tmp_path / "aipass-cadence-test-session.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == -1


class TestConsumeRegroupPending:
    """DPLAN-0276: PostToolUse backstop consumes the flag reset_counter() sets."""

    def setup_method(self):
        _reset_module_globals()

    def test_returns_false_when_no_state_file(self, tmp_path):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            assert consume_regroup_pending() is False

    def test_returns_true_once_after_reset(self, tmp_path):
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
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter(hook_data={"session_id": "fallback-id"})
                assert consume_regroup_pending(hook_data={"session_id": "fallback-id"}) is True
                assert consume_regroup_pending(hook_data={"session_id": "fallback-id"}) is False

    def test_real_turn_after_reset_implicitly_clears_pending(self, tmp_path):
        """Once a real UserPromptSubmit turn fires (turn 0), _load_and_increment
        overwrites state without regroup_pending — so a late-arriving normal turn
        clears the backstop flag too, even if PostToolUse never consumed it."""
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


class TestRegroupPartQueue:
    """Issue #752: the re-ground is spread over consecutive tool calls, one part each.

    The queue shares the regroup token's state file ON PURPOSE, so the two
    things that end a re-ground end the queue too: a real UserPromptSubmit
    (the cadence turn-0 path takes over) and a new compaction (it starts over).
    """

    def setup_method(self):
        _reset_module_globals()

    def _env(self, tmp_path):
        return (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        )

    def test_nothing_queued_pops_nothing(self, tmp_path):
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            assert pop_regroup_part() is None
            reset_counter()
            assert pop_regroup_part() is None

    def test_each_part_is_handed_out_exactly_once_then_silence(self, tmp_path):
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            queue_regroup_parts(3)
            assert [pop_regroup_part() for _ in range(6)] == [(2, 3), (3, 3), None, None, None, None]

    def test_the_last_pop_removes_the_keys(self, tmp_path):
        """An exhausted queue must not linger as state a later reader misreads."""
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            queue_regroup_parts(2)
            pop_regroup_part()
        state = json.loads((tmp_path / "aipass-cadence-test-session.json").read_text(encoding="utf-8"))
        assert "regroup_next" not in state
        assert "regroup_total" not in state

    def test_a_single_part_regroup_queues_nothing(self, tmp_path):
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            queue_regroup_parts(1)
            assert pop_regroup_part() is None

    def test_queueing_keeps_the_token_state_intact(self, tmp_path):
        """The queue writes beside the token; it must not re-arm or erase it."""
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            assert consume_regroup_pending() is True
            queue_regroup_parts(3)
            assert consume_regroup_pending() is False
        state = json.loads((tmp_path / "aipass-cadence-test-session.json").read_text(encoding="utf-8"))
        assert state["turn"] == -1

    def test_a_real_prompt_cancels_the_remaining_parts(self, tmp_path):
        """The cadence turn-0 path re-injects every loader on that prompt, so the
        backstop's remaining parts would only repeat it."""
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            queue_regroup_parts(3)
            assert pop_regroup_part() == (2, 3)
        _reset_module_globals()
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            assert should_fire("global") is True
            assert pop_regroup_part() is None

    def test_a_new_compaction_drops_the_old_queue(self, tmp_path):
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg, patch(f"{MODULE}._REGROUP_DEBOUNCE_S", 0.0):
            reset_counter()
            queue_regroup_parts(3)
            reset_counter()
            assert pop_regroup_part() is None

    def test_a_duplicate_reset_on_the_same_boundary_keeps_the_queue(self, tmp_path):
        """Two PreCompact callers reacting to one compaction (DPLAN-0278) are one
        boundary: the second must not cancel parts the first one's re-ground owes."""
        guard, env, cfg = self._env(tmp_path)
        with guard, env, cfg:
            reset_counter()
            queue_regroup_parts(3)
            reset_counter()
            assert pop_regroup_part() == (2, 3)

    def test_fallback_to_hook_data_session_id(self, tmp_path):
        hook_data = {"session_id": "fallback-id"}
        with patch(f"{MODULE}._GUARD_DIR", tmp_path):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter(hook_data=hook_data)
                queue_regroup_parts(2, hook_data=hook_data)
                assert pop_regroup_part(hook_data=hook_data) == (2, 2)
                assert pop_regroup_part(hook_data=hook_data) is None


class TestRegroupFireLog:
    """Issue #752, pin 4: one sized cadence.log line per fire — a one-grep diagnosis."""

    def test_the_line_names_loader_part_and_both_sizes(self):
        with patch.object(cadence, "logger") as log:
            cadence.log_regroup_fire("branch,identity", 1, 3, "ab—c", 9000)

        log.info.assert_called_once()
        fmt, *args = log.info.call_args.args
        line = fmt % tuple(args)
        assert "[HOOKS] regroup fired loader=branch,identity part=1/3" in line
        assert "bytes=6" in line  # the em dash is three UTF-8 bytes
        assert "chars=4" in line
        log.warning.assert_not_called()

    def test_an_over_budget_fire_is_a_warning_that_says_so(self):
        with patch.object(cadence, "logger") as log:
            cadence.log_regroup_fire("navmap", 2, 2, "x" * 12, 10)

        log.warning.assert_called_once()
        fmt, *args = log.warning.call_args.args
        assert "OVER-BUDGET" in fmt % tuple(args)
        log.info.assert_not_called()

    def test_chars_are_utf16_units_the_way_claude_code_counts(self):
        """A non-BMP character is ONE Python code point and TWO JS length units."""
        with patch.object(cadence, "logger") as log:
            cadence.log_regroup_fire("kernel", 1, 1, "\U0001f600", 9000)

        fmt, *args = log.info.call_args.args
        assert "chars=2" in fmt % tuple(args)


def _config_shown(capsys, config_path) -> str:
    """The merged config as `drone @hooks cadence` prints it (fleet green leg 8: not _load_config by name)."""
    with patch(f"{MODULE}._CONFIG_PATH", config_path):
        print_introspection()
    return capsys.readouterr().err


class TestConfig:
    def setup_method(self):
        _reset_module_globals()

    def test_defaults_used_when_no_config_file(self, tmp_path, capsys):
        shown = _config_shown(capsys, tmp_path / "nonexistent.json")

        assert "Enabled: True" in shown
        assert "Period: 5 turns" in shown
        assert "Loader 'branch': period=5 offset=0" in shown
        assert "Loader 'global'" not in shown

    def test_defaults_include_tiered_loaders(self, tmp_path, capsys):
        """Fresh clone with no cadence_config.json gets tiered cadence out of the box."""
        shown = _config_shown(capsys, tmp_path / "nonexistent.json")

        assert "Loader 'tier0': period=5" in shown
        assert "Loader 'navmap': period=5 offset=0" in shown

    def test_config_deep_merges_over_defaults(self, tmp_path, capsys):
        config_file = tmp_path / "cadence.json"
        config_file.write_text(json.dumps({"period": 10, "loaders": {"global": {"offset": 3}}}), encoding="utf-8")

        shown = _config_shown(capsys, config_file)

        assert "Period: 10 turns" in shown
        assert "Loader 'global': period=10 offset=3" in shown
        assert "Loader 'branch': period=10 offset=0" in shown  # no period of its own: the global one
        assert "Enabled: True" in shown

    def test_bad_config_falls_back_to_defaults(self, tmp_path, capsys):
        config_file = tmp_path / "cadence.json"
        config_file.write_text("not valid json{{{", encoding="utf-8")

        assert "Period: 5 turns" in _config_shown(capsys, config_file)


class TestDeepMerge:
    """The merge, read on the config it builds (fleet green leg 8: not _deep_merge by name)."""

    def setup_method(self):
        _reset_module_globals()

    def test_nested_merge(self, tmp_path, capsys):
        config_file = tmp_path / "cadence.json"
        config_file.write_text(json.dumps({"loaders": {"branch": {"offset": 2}}}), encoding="utf-8")

        shown = _config_shown(capsys, config_file)

        # The key it names is replaced; its sibling inside the same loader is kept.
        assert "Loader 'branch': period=5 offset=2" in shown
        assert "Loader 'tier0': period=5 offset=0" in shown

    def test_overwrites_non_dict(self, tmp_path, capsys):
        config_file = tmp_path / "cadence.json"
        config_file.write_text(json.dumps({"enabled": False}), encoding="utf-8")

        assert "Enabled: False" in _config_shown(capsys, config_file)


class TestPerSessionIsolation:
    def setup_method(self):
        _reset_module_globals()

    def test_different_sessions_use_different_files(self, tmp_path):
        state_a = _write_state(tmp_path, turn=4, session="session-a")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "session-a"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global")
            data_a = json.loads(state_a.read_text(encoding="utf-8"))
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
            data_b = json.loads(state_b.read_text(encoding="utf-8"))
            assert data_b["turn"] == 0


class TestModuleInterface:
    def setup_method(self):
        _reset_module_globals()

    def test_handle_command_cadence_returns_true(self):
        """`cadence` with no args routes to print_introspection; proven by a mutant deleting the call."""
        with patch(f"{MODULE}.print_introspection") as mock_intro:
            assert handle_command("cadence", []) is True
        mock_intro.assert_called_once_with()

    def test_handle_command_unknown_returns_false(self):
        assert handle_command("other", []) is False

    def test_print_introspection_runs(self, tmp_path, capsys):
        """Introspection names the module and reports the cadence it read.

        Had no oracle at all: it called print_introspection and asserted
        nothing, so an introspection that printed an empty string, or the wrong
        module's banner, was a pass. The config here is absent on purpose - the
        defaults are what a reader gets when a branch has no cadence.json, and
        that is the state most likely to be wrong and least likely to be looked
        at.
        """
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            print_introspection()

        # stderr: this module prints through the cli's err_console.
        err = capsys.readouterr().err
        assert err.startswith("cadence Module")
        assert "Enabled: True" in err
        assert "Loader 'tier0'" in err

    def test_introspection_shows_a_global_loader_whose_beat_is_off(self, tmp_path, capsys):
        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"loaders": {"tier0": {"beat": False}}}), encoding="utf-8")

        with patch(f"{MODULE}._CONFIG_PATH", config), patch(f"{MODULE}._GUARD_DIR", tmp_path):
            assert handle_command("cadence", []) is True

        err = capsys.readouterr().err
        assert "Loader 'tier0': period=5 offset=0 beat=off" in err
        assert "Loader 'navmap': period=5 offset=0 beat=on" in err


class TestCompactIntegration:
    def setup_method(self):
        _reset_module_globals()

    def test_compact_handler_resets_cadence(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 7}), encoding="utf-8")

        with (
            patch.object(cadence, "_GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            cadence.reset_counter()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1


class TestLoaderCadenceGuard:
    def setup_method(self):
        _reset_module_globals()

    def test_tier0_kernel_fires_every_turn(self, tmp_path):
        """tier0 has period:1 — fires on every turn including non-fire turns for others."""
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1}},
                }
            ),
            encoding="utf-8",
        )

        _write_state(tmp_path, turn=2)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            result = _tier0_kernel_handle({})

        assert result["exit_code"] == 0

    def test_branch_loader_skips_on_non_fire_turn(self, tmp_path):
        """Skip = empty stdout AND no sound key — a skipped loader is SILENT."""
        _write_state(tmp_path, turn=0)  # next turn = 1 = skip

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            result = _branch_loader_handle({})

        assert result["stdout"] == ""
        assert result["exit_code"] == 0
        assert "sound" not in result


class TestResetCounterObservability:
    """Tests for reset_counter fail-loud logging and session ID tracking."""

    def setup_method(self):
        _reset_module_globals()

    def test_reset_logs_session_id_and_prev_turn(self, tmp_path):
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
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter()

        calls = [str(c) for c in mock_logger.info.call_args_list]
        warning_calls = [c for c in calls if "SKIPPED" in c]
        assert len(warning_calls) == 1

    def test_reset_fallback_to_hook_data_session_id(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-fallback-id.json"
        state_file.write_text(json.dumps({"turn": 5}), encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter(hook_data={"session_id": "fallback-id"})

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1

    def test_reset_fallback_creates_file_if_missing(self, tmp_path):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter(hook_data={"session_id": "new-fallback"})

        state_file = tmp_path / "aipass-cadence-new-fallback.json"
        assert state_file.exists()
        assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == -1

    def test_reset_env_takes_priority_over_hook_data(self, tmp_path):
        env_file = tmp_path / "aipass-cadence-env-session.json"
        env_file.write_text(json.dumps({"turn": 9}), encoding="utf-8")

        hook_file = tmp_path / "aipass-cadence-hook-session.json"
        hook_file.write_text(json.dumps({"turn": 3}), encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "env-session"}),
        ):
            reset_counter(hook_data={"session_id": "hook-session"})

        assert json.loads(env_file.read_text(encoding="utf-8"))["turn"] == -1
        assert json.loads(hook_file.read_text(encoding="utf-8"))["turn"] == 3

    def test_reset_hook_data_empty_session_id_logs_skip(self, tmp_path):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch(f"{MODULE}.logger") as mock_logger,
        ):
            env = dict(os.environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                reset_counter(hook_data={"session_id": ""})

        calls = [str(c) for c in mock_logger.info.call_args_list]
        assert any("SKIPPED" in c for c in calls)

    def test_reset_prev_turn_from_corrupt_file(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text("not valid json{{{", encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()

        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1


class TestPostCompactDeterminism:
    """Prove that post-compaction reload fires ALL loaders deterministically."""

    def setup_method(self):
        _reset_module_globals()

    def test_all_tiered_loaders_fire_after_reset(self, tmp_path):
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
            ),
            encoding="utf-8",
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
                state = json.loads((tmp_path / "aipass-cadence-test-session.json").read_text(encoding="utf-8"))
                assert state["turn"] == 0, f"Expected turn 0 after reset from {prev_turn}"
                assert result is True, f"navmap should fire after reset from turn {prev_turn}"

    def test_compact_handler_calls_reset_with_hook_data(self, tmp_path, monkeypatch):
        """compact resets the cadence counter and files the git answer under ## Git.

        _get_git_info is stood in by a recorder so no real git process starts; the
        ## Git assert is proven by a mutant on compact.handle (see the fleet green report).
        The real cadence runs with its guard dir under tmp_path (fleet green leg 7: no
        importlib patch): the reset is read off the disk, the session id from hook_data
        in the state file's name and the caller in the window stamp.
        """
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.delenv("CLAUDE_CODE_SESSION_ID", raising=False)
        (tmp_path / "aipass-cadence-test-123.json").write_text(json.dumps({"turn": 7}), encoding="utf-8")
        hook_data = {"cwd": str(tmp_path / "fake"), "session_id": "test-123"}
        git_answer = "Git branch: recorded-branch\nUncommitted changes: 3 files"

        with patch(
            "aipass.hooks.apps.handlers.lifecycle.compact._get_git_info",
            return_value=git_answer,
        ) as git_recorder:
            result = _compact_handle(hook_data)

        state = json.loads((tmp_path / "aipass-cadence-test-123.json").read_text(encoding="utf-8"))
        assert state["turn"] == -1
        window = json.loads((tmp_path / "aipass-window-opened-test-123.json").read_text(encoding="utf-8"))
        assert window["caller"] == "compact"
        git_recorder.assert_called_once_with()
        assert f"## Git\n{git_answer}" in result["stdout"].split("\n\n")
        assert result["exit_code"] == 0

    def test_double_reset_is_idempotent(self, tmp_path):
        _write_state(tmp_path, turn=11)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
        ):
            reset_counter()
            _reset_module_globals()
            reset_counter()

        state_file = tmp_path / "aipass-cadence-test-session.json"
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["turn"] == -1


class TestFailOpenIsLoud:
    """DPLAN-0347 row 1: a degraded read is a WARNING that names the cause — once per turn.

    A degraded read used to force turn 0, and turn 0 fires EVERY loader — the
    four heavy ones cost 13,235 to 21,536 chars per fire. The room ruled the
    degraded mode instead (FPLAN-0593 Phase 5): the kernel fires alone, the
    heavy loaders are withheld, and only the kernel's line is a WARNING, so a
    degraded turn costs one WARNING rather than one per loader.
    """

    def setup_method(self):
        _reset_module_globals()

    def _config(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": True, "period": 5}), encoding="utf-8")
        return config

    def test_no_session_id_warns_once_and_names_the_cause(self, tmp_path, caplog):
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True),
            patch(f"{MODULE}._CONFIG_PATH", self._config(tmp_path)),
        ):
            fired = {name: should_fire(name) for name in ("tier0", "navmap", "branch", "identity", "alert")}

        assert fired == {"tier0": True, "navmap": False, "branch": False, "identity": False, "alert": True}
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert len(warnings) == 1, "one degraded turn is one WARNING, not one per loader"
        assert "DEGRADED loader=tier0 fires" in warnings[0].getMessage()
        assert "CLAUDE_CODE_SESSION_ID" in warnings[0].getMessage()
        assert "DEGRADED loader=navmap WITHHELD" in caplog.text
        assert "CLAUDE_CODE_SESSION_ID" in (degraded_reason() or "")

    def test_an_unreadable_state_file_warns_with_the_cause(self, tmp_path, caplog):
        """A file stands where the guard dir should be, so the state cannot be opened.

        No builtins.open patch (fleet green leg 7): the test asks the platform what
        opening that path raises and asserts the warning carries the same words.
        """
        blocker = tmp_path / "blocker"
        blocker.write_text("", encoding="utf-8")
        with pytest.raises(OSError) as raised:
            open(blocker / "aipass-cadence-test-session.json", encoding="utf-8").close()

        with (
            patch(f"{MODULE}._GUARD_DIR", blocker),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", self._config(tmp_path)),
        ):
            assert should_fire("tier0") is True
            assert should_fire("navmap") is False

        # The cause rides in the DEGRADED warning itself, not only in the state-access line beside it.
        degraded = [r.getMessage() for r in caplog.records if "DEGRADED loader=tier0 fires" in r.getMessage()]
        assert len(degraded) == 1
        assert str(raised.value.strerror) in degraded[0]

    def test_a_healthy_turn_says_nothing_at_warning(self, tmp_path, caplog):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", self._config(tmp_path)),
        ):
            should_fire("identity")

        assert [r for r in caplog.records if r.levelname == "WARNING"] == []

    def test_the_advisory_throttle_warns_when_it_cannot_throttle(self, tmp_path, caplog):
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        with patch(f"{MODULE}._GUARD_DIR", tmp_path), patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
            assert should_fire_advisory("todos_count") is True

        assert "FAIL-OPEN advisory=todos_count" in caplog.text
