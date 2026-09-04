# =================== AIPass ====================
# Name: test_relay_switch_gate.py
# Description: Tests for the relay's skills-switch gate — the third door
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Tests for the third door: the relay's skills-switch gate.

APLAN-0016 (S115) measured a skill that `drone @skills switch` reported OFF
still sending on every prompt — 508 relayed user messages in the ten days after
Patrick switched telegram off on 2026-08-18. Cause: the hooks bridge invokes
this handler BY FILE PATH, so `run_skill` — and the switch gate inside it — is
never on that path.

These tests therefore load the module **the way the bridge does**, from its file
path via importlib, not through `run_skill` and not through the package import
the rest of the suite uses. A gate that only holds on the package path would
leave the measured defect exactly where it was found, so proving the by-path
lane is the whole point of this file.

Cases:
  - OFF        -> no outbound send attempted (the defect)
  - ON         -> send attempted (the gate does not break normal operation)
  - unreadable -> no outbound send attempted (fails CLOSED)
  - contract   -> the hook return shape survives every one of those
"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aipass.skills.apps.handlers import switch_handler as sh
from aipass.skills.apps.handlers.json import json_handler as jh


_RELAY_PATH = Path(__file__).resolve().parents[1] / "apps" / "handlers" / "user_message_relay.py"
_SKILL = "telegram"


# =============================================
# FIXTURES
# =============================================


@pytest.fixture()
def relay_by_path():
    """Load user_message_relay from its FILE PATH, as the hooks bridge does.

    Deliberately not `import ...user_message_relay`: the defect lived precisely
    in the difference between the two entry paths.
    """
    spec = importlib.util.spec_from_file_location("_relay_under_test_by_path", _RELAY_PATH)
    assert spec is not None and spec.loader is not None, f"no import spec for {_RELAY_PATH}"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def state_dir(tmp_path, monkeypatch):
    """Point the switch state at a temp dir — never the live skills_json/.

    The redirect is the AIPASS_TEST_LOG_DIR seam the fleet json service reads
    per call (DPLAN-0325); the directory is measured off the service so it
    cannot drift from where the switch actually writes.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    target = jh.get_json_path("switch", "data").parent
    target.mkdir(parents=True, exist_ok=True)
    return target


def _write_switch(state_dir, enabled):
    """Write a real switch_state.json the real read_state() will parse."""
    payload = {"skills": {_SKILL: {"enabled": enabled, "reason": "test"}}}
    (state_dir / "switch_state.json").write_text(json.dumps(payload), encoding="utf-8")


@pytest.fixture()
def bot_dirs(tmp_path, relay_by_path):
    """A discoverable bot, so only the gate can stop a send."""
    mirror = tmp_path / "mirror"
    pending = tmp_path / "pending"
    work = tmp_path / "branch_workdir"
    for d in (mirror, pending, work):
        d.mkdir()

    (mirror / "test_bot.json").write_text(
        json.dumps(
            {
                "chat_id": 42,
                "bot_token": "123:FAKETOKEN",
                "work_dir": str(work),
                "bot_id": "test_bot",
            }
        )
    )

    with (
        patch.object(relay_by_path, "MIRROR_DIR", mirror),
        patch.object(relay_by_path, "PENDING_DIR", pending),
    ):
        yield {"work": work}


def _hook_payload(work_dir, prompt="a real user message"):
    return {"prompt": prompt, "cwd": str(work_dir), "agent_id": ""}


def _ok_response():
    """A mock urlopen response Telegram would call a success.

    Every OFF-case test uses this deliberately: with a failing mock the send
    path suppresses the sound key and the dedup hash by itself, so the test
    would pass against ungated code and prove nothing.
    """
    resp = MagicMock()
    resp.read.return_value = json.dumps({"ok": True}).encode()
    resp.__enter__ = lambda s: s
    resp.__exit__ = lambda *a: None
    return resp


# =============================================
# 1. THE DEFECT — OFF must send nothing
# =============================================


class TestSwitchedOffSendsNothing:
    def test_off_attempts_no_outbound_send(self, relay_by_path, bot_dirs, state_dir):
        """The measured defect: OFF, bot present, prompt clean — still sent."""
        _write_switch(state_dir, enabled=False)

        with patch.object(relay_by_path, "urlopen") as mock_url:
            result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_not_called()
        assert result == {"stdout": "", "exit_code": 0}

    def test_off_emits_no_sound_key(self, relay_by_path, bot_dirs, state_dir):
        """No sound either — a silent relay must be silent on every channel."""
        _write_switch(state_dir, enabled=False)

        with patch.object(relay_by_path, "urlopen", return_value=_ok_response()):
            result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        assert "sound" not in result

    def test_off_does_not_advance_the_dedup_hash(self, relay_by_path, bot_dirs, state_dir):
        """A message refused by the gate was never sent, so it is not 'last sent'."""
        _write_switch(state_dir, enabled=False)

        with patch.object(relay_by_path, "urlopen", return_value=_ok_response()):
            relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        assert relay_by_path._last_relay_hash == ""


# =============================================
# 2. ON — the gate must not break normal operation
# =============================================


class TestSwitchedOnStillRelays:
    def test_on_attempts_the_send(self, relay_by_path, bot_dirs, state_dir):
        _write_switch(state_dir, enabled=True)

        with patch.object(relay_by_path, "urlopen", return_value=_ok_response()) as mock_url:
            result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_called_once()
        assert result["sound"] == "user message relay"

    def test_no_recorded_entry_means_on(self, relay_by_path, bot_dirs, state_dir):
        """A skill never toggled is ON — the gate must not invent an OFF."""
        with patch.object(relay_by_path, "urlopen", return_value=_ok_response()) as mock_url:
            relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_called_once()


# =============================================
# 3. FAIL CLOSED — unreadable state sends nothing
# =============================================


class TestUnreadableStateFailsClosed:
    def test_corrupt_state_file_sends_nothing(self, relay_by_path, bot_dirs, state_dir):
        """Real corrupt document, parsed by the real read_state()."""
        (state_dir / "switch_state.json").write_text("{not json", encoding="utf-8")

        with patch.object(relay_by_path, "urlopen") as mock_url:
            result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_not_called()
        assert result == {"stdout": "", "exit_code": 0}

    def test_switch_raising_anything_sends_nothing(self, relay_by_path, bot_dirs, state_dir):
        """Any failure to tell — not just the declared one — stays silent."""
        with patch.object(sh, "is_enabled", side_effect=RuntimeError("boom")):
            with patch.object(relay_by_path, "urlopen") as mock_url:
                result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_not_called()
        assert result == {"stdout": "", "exit_code": 0}

    def test_declared_unreadable_sends_nothing(self, relay_by_path, bot_dirs, state_dir):
        with patch.object(sh, "is_enabled", side_effect=sh.SwitchStateUnreadable("unreadable")):
            with patch.object(relay_by_path, "urlopen") as mock_url:
                relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        mock_url.assert_not_called()


# =============================================
# 4. HOOK CONTRACT — the bridge never sees an error
# =============================================


class TestHookContractHolds:
    @pytest.mark.parametrize("enabled", [True, False])
    def test_return_shape_survives_both_states(self, relay_by_path, bot_dirs, state_dir, enabled):
        _write_switch(state_dir, enabled=enabled)

        with patch.object(relay_by_path, "urlopen", return_value=_ok_response()):
            result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))

        assert result["stdout"] == ""
        assert result["exit_code"] == 0

    def test_gate_never_raises_to_the_bridge(self, relay_by_path, bot_dirs, state_dir):
        (state_dir / "switch_state.json").write_text("{not json", encoding="utf-8")
        result = relay_by_path.handle(_hook_payload(bot_dirs["work"]))
        assert result["exit_code"] == 0
