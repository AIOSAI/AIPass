# =================== AIPass ====================
# Name: test_cadence.py
# Version: 1.10.0
# Description: Tests for cadence module (DPLAN-0200): the fire decision; regroup and counter in test_cadence_regroup.py
# Branch: hooks
# Created: 2026-06-08
# Modified: 2026-10-25
# =============================================

"""Tests for apps/modules/cadence.py: the fire decision."""

# Cadence runs MULTI-PROCESS in production: each UserPromptSubmit hook is a
# separate OS process. Tests model that by resetting the module _turn cache
# between calls (= new process) and aging the state file past the mtime
# debounce window (= a real prior turn, not a sibling in the same turn).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that cadence.py parses and imports, ruff and collection cover it
# seedgo: no-test-needed(documentation) — is_automated(), reset_counter() and should_fire() carry docstrings
# seedgo: no-test-needed(stdlib) — fcntl, unavailable on Windows; the platform fallback never runs on this CI

import contextlib
import json
import os
import time
from unittest.mock import patch

import pytest

from aipass.hooks.apps.modules import cadence
from aipass.hooks.apps.modules.cadence import (
    is_automated,
    reset_counter,
    should_fire,
    should_fire_mail,
)
from aipass.hooks.tests.support_cadence import MODULE, _kept_redirect, _reset_module_globals, _write_state

pytestmark = pytest.mark.usefixtures("_restore_cadence_globals")


#: A harness task-notification as it reached a live UserPromptSubmit hook on
#: Claude Code 2.1.273: the text opens with the tag and the payload carries no
#: `source` key (DPLAN-0348, measured 2026-09-16).
_NOTIFICATION = "<task-notification>\n<task-id>b1hws2iup</task-id>\n<status>completed</status>\n</task-notification>"


class TestShouldFire:
    def setup_method(self):
        _reset_module_globals()

    def test_turn_0_always_fires(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == 0

    def test_turn_0_fires_all_loaders(self, tmp_path):
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert should_fire("branch") is True

    def test_non_fire_turn_returns_false(self, tmp_path):
        _write_state(tmp_path, turn=0)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is False

    def test_fire_turn_returns_true(self, tmp_path):
        _write_state(tmp_path, turn=3)

        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps({"enabled": True, "period": 5, "loaders": {"global": {"offset": 4}}}), encoding="utf-8"
        )

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_cadence_disabled_always_fires(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 1}), encoding="utf-8")

        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": False}), encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_no_session_id_withholds_all_but_the_kernel_and_the_notices(self, tmp_path):
        """The degraded fail mode (DPLAN-0347): not every loader every turn, not dark."""
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {}, clear=False),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            env = dict(__import__("os").environ)
            env.pop("CLAUDE_CODE_SESSION_ID", None)
            with patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True):
                assert should_fire("global") is False
                for withheld in ("navmap", "branch", "identity"):
                    assert should_fire(withheld) is False, withheld
                for kept in ("tier0", "alert"):
                    assert should_fire(kept) is True, kept

    def test_counter_increments_once_across_sibling_processes(self, tmp_path):
        """Each loader is a SEPARATE OS process. The counter must advance
        exactly once per real turn no matter how many siblings call it."""
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
            data = json.loads(state_file.read_text(encoding="utf-8"))
            assert data["turn"] == 4

    def test_sibling_processes_agree_on_turn_no_leapfrog(self, tmp_path):
        """The S210 live bug: global saw turn N, branch saw N+1 — they
        leapfrogged and never both fired. Both siblings must see the SAME
        turn and make the SAME decision."""
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
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 100, encoding="utf-8")
        state_file = _write_state(tmp_path, turn=3, token=100)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global", {"transcript_path": str(transcript)})
            assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == 3

    def test_reset_special_case_survives_debounce(self, tmp_path):
        """turn < 0 (post-compact reset) must ALWAYS increment to 0, even when
        the reset just happened (fresh mtime would normally debounce)."""
        state_file = _write_state(tmp_path, turn=-1, aged=False)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("global") is True
            assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == 0

    def test_period_zero_always_fires(self, tmp_path):
        state_file = tmp_path / "aipass-cadence-test-session.json"
        state_file.write_text(json.dumps({"turn": 2}), encoding="utf-8")

        config = tmp_path / "cadence.json"
        config.write_text(json.dumps({"enabled": True, "period": 0}), encoding="utf-8")

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True

    def test_stagger_offsets(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps({"enabled": True, "period": 5, "loaders": {"global": {"offset": 0}, "branch": {"offset": 2}}}),
            encoding="utf-8",
        )

        _write_state(tmp_path, turn=4)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("global") is True
            assert should_fire("branch") is False

    def test_unknown_loader_uses_offset_zero(self, tmp_path):
        _write_state(tmp_path, turn=4)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            assert should_fire("unknown_loader") is True

    # --- DPLAN-0348: a turn the harness sent is not a turn ---

    def test_is_automated_reads_the_payload_source_first(self):
        """The 2.1.273 hook schema declares `source`; a payload that carries it decides by it."""
        assert is_automated({"source": "system", "prompt": "typed words"}) is True
        assert is_automated({"source": "user", "prompt": _NOTIFICATION}) is False
        for other in ("sdk", "loop_wakeup", "schedule_wakeup", "poll_event"):
            assert is_automated({"source": other, "prompt": "x"}) is False, other

    def test_is_automated_falls_back_to_how_the_prompt_opens(self):
        """No live payload carried `source`, so the text decides, and only by how it opens."""
        assert is_automated({"prompt": _NOTIFICATION}) is True
        assert is_automated({"prompt": "\n  " + _NOTIFICATION}) is True
        assert is_automated({"prompt": "[SYSTEM NOTIFICATION] monitor expired"}) is True
        # A human quoting a marker mid-sentence keeps their grounding.
        assert is_automated({"prompt": "why did a <task-notification> land here?"}) is False
        assert is_automated({"prompt": "I got a [SYSTEM NOTIFICATION today"}) is False
        # A dispatch wake and a slash command, as they reached the hook.
        assert is_automated({"prompt": "Hi. Check inbox, process new emails, update memories when done."}) is False
        assert is_automated({"prompt": "/prep"}) is False

    def test_is_automated_reads_a_missing_prompt_as_human(self):
        """A payload change must fail toward today's behaviour, never go dark."""
        for payload in (None, {}, {"prompt": ""}, {"prompt": None}, {"source": None}, {"source": "", "prompt": "hi"}):
            assert is_automated(payload) is False, payload

    def test_an_automated_turn_neither_counts_nor_writes_the_state(self, tmp_path):
        """33 harness wakes in 15 idle hours advanced the counter like typed turns.

        The token is left alone too: a stored token equal to the next real
        turn's would debounce that turn away, so the human turn after the wake
        must still count.
        """
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 500, encoding="utf-8")
        state_file = _write_state(tmp_path, turn=3, token=100)
        before = (state_file.read_text(encoding="utf-8"), state_file.stat().st_mtime)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            wake = {"transcript_path": str(transcript), "prompt": _NOTIFICATION}
            for loader in ("tier0", "navmap", "identity", "branch", "alert"):
                _reset_module_globals()
                should_fire(loader, wake)
            # Mail is the sibling that still reads the counter on a wake, so it is the one that could write it.
            _reset_module_globals()
            cadence.should_fire_mail(1, wake)
            assert (state_file.read_text(encoding="utf-8"), state_file.stat().st_mtime) == before

            _reset_module_globals()
            should_fire("tier0", {"transcript_path": str(transcript), "prompt": "a human turn"})
            state = json.loads(state_file.read_text(encoding="utf-8"))
            assert (state["turn"], state["token"]) == (4, 500)

    def test_an_automated_prompt_after_a_compaction_fires_no_grounding(self, tmp_path):
        """The 09:30 row: turn 0 on a harness wake delivered 20,310 chars to nobody.

        The guard sits before the turn-0 clause, the wake leaves the armed state
        as it found it (regroup token included), and the next human prompt is
        still turn 0 and grounds in full.
        """
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            cadence.reset_counter()
            state_file = tmp_path / "aipass-cadence-test-session.json"
            armed = json.loads(state_file.read_text(encoding="utf-8"))
            for loader in ("tier0", "navmap", "identity", "branch"):
                _reset_module_globals()
                assert cadence.should_fire(loader, {"prompt": _NOTIFICATION}) is False, loader
            assert json.loads(state_file.read_text(encoding="utf-8")) == armed

            for loader in ("tier0", "navmap", "identity", "branch"):
                _reset_module_globals()
                assert cadence.should_fire(loader, {"prompt": "the owner types"}) is True, loader

    def test_an_automated_turn_is_never_a_beat_but_mail_still_announces(self, tmp_path):
        """The channels. Mail announces on arrival whoever sent the turn. An alert's
        arrival is not cadence-gated at all (persistent_alert), so should_fire('alert')
        only decides a REPEAT, and a turn that does not count is not a beat to repeat on:
        read without advancing, a stored beat would otherwise repeat on every wake."""
        notification = {"prompt": _NOTIFICATION}
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            for stored in (4, 5):
                state_file = _write_state(tmp_path, turn=stored)
                _reset_module_globals()
                assert cadence.should_fire("alert", notification) is False, stored
            _reset_module_globals()
            assert cadence.should_fire_mail(2, notification) is True
            assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == 5


class TestPerLoaderPeriod:
    def setup_method(self):
        _reset_module_globals()

    def test_loader_period_overrides_global(self, tmp_path):
        """A loader with period:1 fires every turn, even when global period is 5."""
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1, "beat": True}, "global": {"offset": 0}},
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
            assert should_fire("tier0") is True
            _reset_module_globals()
            assert should_fire("global") is False

    def test_loader_without_period_uses_global(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"global": {"offset": 0}},
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
            assert should_fire("global") is False

    def test_tier0_period_1_fires_every_turn(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"tier0": {"period": 1, "beat": True}},
                }
            ),
            encoding="utf-8",
        )

        # The turns spelled out, not range(1, 8): "every turn" is the whole
        # claim, so the seven turns are the test data and an iterable that
        # produced none of them would have passed silently.
        fired = {}
        for turn_val in (1, 2, 3, 4, 5, 6, 7):
            _reset_module_globals()
            _write_state(tmp_path, turn=turn_val - 1)

            with (
                patch(f"{MODULE}._GUARD_DIR", tmp_path),
                patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
                patch(f"{MODULE}._CONFIG_PATH", config),
            ):
                fired[turn_val] = should_fire("tier0")

        assert fired == {1: True, 2: True, 3: True, 4: True, 5: True, 6: True, 7: True}

    def test_navmap_period_5_skips_non_fire_turns(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
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
            assert should_fire("navmap") is False

    def test_navmap_fires_on_turn_0(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
                }
            ),
            encoding="utf-8",
        )

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire("navmap") is True

    def test_navmap_fires_after_reset_counter(self, tmp_path):
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"navmap": {"period": 5, "offset": 0}},
                }
            ),
            encoding="utf-8",
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
        config = tmp_path / "cadence.json"
        config.write_text(
            json.dumps(
                {
                    "enabled": True,
                    "period": 5,
                    "loaders": {"always": {"period": 0}},
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
            assert should_fire("always") is True


def _write_mail_state(tmp_path, last_fired, session="test-session"):
    """Write the mail-loop state file (last turn the banner fired)."""
    state_file = tmp_path / f"aipass-mailcadence-{session}.json"
    state_file.write_text(json.dumps({"last_fired_turn": last_fired}), encoding="utf-8")
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
        config.write_text(
            json.dumps({"enabled": enabled, "period": 5, "loaders": {"email": {"period": period}}}), encoding="utf-8"
        )
        return config

    def test_zero_mail_is_silent(self, tmp_path):
        config = self._config(tmp_path)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(0, {}) is False

    def test_first_sighting_fires(self, tmp_path):
        config = self._config(tmp_path)
        _write_state(tmp_path, turn=6)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_fires_at_plus_period_not_plus_one(self, tmp_path):
        """The canary: over an 11-turn session with mail always present, the banner
        fires on arrival and then only every 5th turn — never on consecutive turns."""
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
        config = self._config(tmp_path)
        _write_mail_state(tmp_path, last_fired=0)
        _write_state(tmp_path, turn=1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is False

    def test_counter_reset_re_announces(self, tmp_path):
        """After a compact the turn counter restarts at 0 while mail state says 7.
        Negative elapsed must re-announce, not go permanently silent."""
        config = self._config(tmp_path)
        _write_mail_state(tmp_path, last_fired=7)
        _write_state(tmp_path, turn=-1)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_cadence_disabled_fires_every_turn(self, tmp_path):
        config = self._config(tmp_path, enabled=False)
        _write_mail_state(tmp_path, last_fired=3)
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_period_zero_fires_every_turn(self, tmp_path):
        config = self._config(tmp_path, period=0)
        _write_mail_state(tmp_path, last_fired=3)
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True

    def test_disabled_still_silent_at_zero(self, tmp_path):
        """Disabled restores fire-every-turn, but never invents a banner for no mail."""
        config = self._config(tmp_path, enabled=False)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(0, {}) is False

    def test_no_session_id_fires(self, tmp_path):
        """No session = no state to loop on; announce rather than swallow mail."""
        config = self._config(tmp_path)
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_SESSION_ID", None)
        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {**_kept_redirect(), **env}, clear=True),
            patch(f"{MODULE}._CONFIG_PATH", config),
        ):
            assert should_fire_mail(1, {}) is True

    def test_corrupt_mail_state_treated_as_never_fired(self, tmp_path):
        config = self._config(tmp_path)
        (tmp_path / "aipass-mailcadence-test-session.json").write_text("{not json", encoding="utf-8")
        _write_state(tmp_path, turn=3)
        with _mail_env(tmp_path, config):
            assert should_fire_mail(1, {}) is True


class TestShouldFireAdvisory:
    """Throttle for STANDING conditions — states that stay true for days and
    re-assert on every qualifying edit. @devpulse's seat sat over the todos cap
    long enough to write 209 identical lines and trip @trigger's
    repeat-signature escalation (the owner's ruling, 2026-08-19)."""

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
        """Losing the advisory is worse than repeating it.

        The state cannot be written because a file stands where the guard dir
        should be: the platform refuses the write, no pathlib patch (fleet green leg 7).
        """
        blocker = self.tmp / "blocker"
        blocker.write_text("", encoding="utf-8")
        with self._at_turn(1), patch.object(cadence, "_GUARD_DIR", blocker):
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


class TestTurnToken:
    def setup_method(self):
        _reset_module_globals()

    def test_an_unmeasurable_transcript_answers_minus_one_not_an_empty_files_zero(self, tmp_path):
        empty = tmp_path / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        assert cadence.turn_token({"transcript_path": str(empty)}) == 0
        assert cadence.turn_token({"transcript_path": str(tmp_path / "missing.jsonl")}) == -1
        assert cadence.turn_token({}) == -1

    def test_a_missing_transcript_at_turn_zero_logs_no_info_line(self, tmp_path, caplog):
        caplog.set_level("DEBUG")
        assert cadence.turn_token({"transcript_path": str(tmp_path / "missing.jsonl")}) == -1
        assert not [r for r in caplog.records if r.levelname == "INFO" and "transcript" in r.getMessage()]

    def test_two_unmeasurable_turns_in_a_row_still_count(self, tmp_path):
        state_file = _write_state(tmp_path, turn=3, token=-1)

        with (
            patch(f"{MODULE}._GUARD_DIR", tmp_path),
            patch.dict("os.environ", {"CLAUDE_CODE_SESSION_ID": "test-session"}),
            patch(f"{MODULE}._CONFIG_PATH", tmp_path / "cadence.json"),
        ):
            should_fire("global", {"transcript_path": str(tmp_path / "missing.jsonl")})
            assert json.loads(state_file.read_text(encoding="utf-8"))["turn"] == 4


class TestBranchOverride:
    """DPLAN-0355: a per-branch loader override, resolved from the prompt's cwd."""

    def _fleet(self, tmp_path, monkeypatch, config: dict) -> dict:
        """Two branches under a repo root, the config in tmp_path, the session counted there."""
        root = tmp_path / "repo"
        (root / ".git").mkdir(parents=True)
        dirs = {"root": root}
        for name in ("canary", "devpulse"):
            (root / name / ".trinity").mkdir(parents=True)
            dirs[name] = root / name
        config_file = tmp_path / "cadence.json"
        config_file.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setattr(cadence, "_CONFIG_PATH", config_file)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session")
        return dirs

    def _decide(self, tmp_path, loader: str, cwd, turn: int) -> bool:
        """A fresh process deciding *loader* on *turn* for a prompt from *cwd*."""
        _reset_module_globals()
        state = tmp_path / "aipass-cadence-test-session.json"
        state.unlink(missing_ok=True)
        if turn > 0:
            _write_state(tmp_path, turn=turn - 1)
        return should_fire(loader, {"cwd": str(cwd)})

    # The global tier0 beats here, so the override is what turns it off.
    _BEAT_FALSE = {
        "loaders": {"tier0": {"beat": True}},
        "branches": {"canary": {"loaders": {"tier0": {"beat": False}}}},
    }

    def test_a_beat_false_override_fires_at_turn_0_and_skips_turns_5_and_10(self, tmp_path, monkeypatch):
        dirs = self._fleet(tmp_path, monkeypatch, self._BEAT_FALSE)

        assert [self._decide(tmp_path, "tier0", dirs["canary"], turn) for turn in (0, 5, 10)] == [True, False, False]

    def test_a_branch_with_no_override_still_fires_on_the_beat(self, tmp_path, monkeypatch):
        dirs = self._fleet(tmp_path, monkeypatch, self._BEAT_FALSE)

        assert [self._decide(tmp_path, "tier0", dirs["devpulse"], turn) for turn in (0, 4, 5, 10)] == [
            True,
            False,
            True,
            True,
        ]

    def test_a_loader_the_override_does_not_name_inherits_global(self, tmp_path, monkeypatch):
        dirs = self._fleet(tmp_path, monkeypatch, self._BEAT_FALSE)

        assert self._decide(tmp_path, "identity", dirs["canary"], 5) is True

    def test_an_override_merges_over_the_global_entry_not_in_place_of_it(self, tmp_path, monkeypatch):
        config = {
            "loaders": {"tier0": {"period": 4, "beat": True}},
            "branches": {"canary": {"loaders": {"tier0": {"offset": 1}}}},
        }
        dirs = self._fleet(tmp_path, monkeypatch, config)

        assert self._decide(tmp_path, "tier0", dirs["canary"], 5) is True
        assert self._decide(tmp_path, "tier0", dirs["canary"], 4) is False

    def test_the_decision_line_names_the_branch(self, tmp_path, monkeypatch, caplog):
        dirs = self._fleet(tmp_path, monkeypatch, self._BEAT_FALSE)

        self._decide(tmp_path, "tier0", dirs["canary"], 5)

        assert "cadence skipped loader=tier0 turn=5" in caplog.text
        assert "branch=canary" in caplog.text

    def test_a_cwd_under_no_branch_uses_global_and_says_so(self, tmp_path, monkeypatch, caplog):
        config = {"loaders": {"tier0": {"beat": True}}, "branches": {"repo": {"loaders": {"tier0": {"beat": False}}}}}
        dirs = self._fleet(tmp_path, monkeypatch, config)

        assert self._decide(tmp_path, "tier0", dirs["root"], 5) is True
        assert "under no branch" in caplog.text

    def test_a_malformed_override_logs_error_and_serves_global(self, tmp_path, monkeypatch, caplog):
        config = {"loaders": {"tier0": {"beat": True}}, "branches": {"canary": {"loaders": {"tier0": {"beat": "no"}}}}}
        dirs = self._fleet(tmp_path, monkeypatch, config)

        assert self._decide(tmp_path, "tier0", dirs["canary"], 5) is True
        errors = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
        assert errors and "beat" in errors[0]


class TestOneDecisionPerPrompt:
    """DPLAN-0355 follow-up: siblings of one prompt agree on its turn however far apart they run."""

    def _sibling(self, tmp_path, payload: dict, age: float | None = None) -> int:
        """A fresh loader process reading the turn; *age* backdates the state file first."""
        state = tmp_path / "aipass-cadence-test-session.json"
        if age is not None:
            old = time.time() - age
            os.utime(state, (old, old))
        _reset_module_globals()
        should_fire("tier0", payload)
        return json.loads(state.read_text(encoding="utf-8"))["turn"]

    def test_a_headless_first_prompt_stays_on_turn_0_for_a_sibling_3s_late(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setattr(cadence, "_CONFIG_PATH", tmp_path / "cadence.json")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session")
        _write_state(tmp_path, turn=-1, aged=False)
        payload = {"prompt": "hi", "transcript_path": str(tmp_path / "not-written-yet.jsonl")}

        assert [self._sibling(tmp_path, payload), self._sibling(tmp_path, payload, age=3)] == [0, 0]

    def test_a_next_prompt_counts_within_2s_even_with_the_same_text(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setattr(cadence, "_CONFIG_PATH", tmp_path / "cadence.json")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session")
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 100, encoding="utf-8")
        _write_state(tmp_path, turn=-1, aged=False)
        payload = {"prompt": "continue", "transcript_path": str(transcript)}

        first = self._sibling(tmp_path, payload)
        transcript.write_text("x" * 200, encoding="utf-8")

        assert [first, self._sibling(tmp_path, payload)] == [0, 1]

    def test_siblings_with_a_real_transcript_stay_on_one_turn_past_2s(self, tmp_path, monkeypatch):
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setattr(cadence, "_CONFIG_PATH", tmp_path / "cadence.json")
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session")
        transcript = tmp_path / "transcript.jsonl"
        transcript.write_text("x" * 100, encoding="utf-8")
        _write_state(tmp_path, turn=4)
        payload = {"prompt": "go on", "transcript_path": str(transcript)}

        assert [self._sibling(tmp_path, payload), self._sibling(tmp_path, payload, age=3)] == [5, 5]


class TestShippedDefaults:
    """What a clone runs on: cadence_config.json is gitignored, so DEFAULTS alone decide."""

    def _decide(self, tmp_path, monkeypatch, loader: str, turn: int, config: dict | None = None) -> bool:
        """A fresh process deciding *loader* on *turn*; no config file unless *config* is given."""
        config_file = tmp_path / "cadence.json"
        if config is not None:
            config_file.write_text(json.dumps(config), encoding="utf-8")
        monkeypatch.setattr(cadence, "_GUARD_DIR", tmp_path)
        monkeypatch.setattr(cadence, "_CONFIG_PATH", config_file)
        monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "test-session")
        _reset_module_globals()
        (tmp_path / "aipass-cadence-test-session.json").unlink(missing_ok=True)
        if turn > 0:
            _write_state(tmp_path, turn=turn - 1)
        return should_fire(loader)

    @pytest.mark.parametrize("loader", ["tier0", "navmap"])
    def test_the_kernel_and_navmap_ground_at_turn_0_and_skip_turns_5_and_10(self, tmp_path, monkeypatch, loader):
        assert [self._decide(tmp_path, monkeypatch, loader, turn) for turn in (0, 5, 10)] == [True, False, False]

    @pytest.mark.parametrize("loader", ["identity", "branch", "alert"])
    def test_every_other_loader_still_fires_on_the_beat(self, tmp_path, monkeypatch, loader):
        assert [self._decide(tmp_path, monkeypatch, loader, turn) for turn in (0, 4, 5)] == [True, False, True]

    def test_a_config_file_beat_true_puts_the_kernel_back_on_the_beat(self, tmp_path, monkeypatch):
        config = {"loaders": {"tier0": {"beat": True}}}

        assert self._decide(tmp_path, monkeypatch, "tier0", 5, config) is True
        assert self._decide(tmp_path, monkeypatch, "navmap", 5, config) is False
