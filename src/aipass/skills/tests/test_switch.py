# =================== AIPass ====================
# Name: test_switch.py
# Description: Skill off-switch tests
# Version: 1.2.0
# Created: 2026-08-18
# Modified: 2026-10-22
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.2.0 (2026-10-22): Telegram left skills - its notifier door and unit-declaration tests go with it
#   - v1.1.0 (2026-09-14): Refusal line carries the recorded reason; notifier door gated (telegram retired)
#   - v1.0.0 (2026-08-18): Initial creation - DPLAN-0306 per-skill off-switch
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation via tmp_path - NEVER the live skills_json/ directory
#   - systemctl is ALWAYS faked - a test must never touch this machine's units
# =============================================

"""Tests for apps/handlers/switch_handler.py and the runner door that reads it."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that apps/handlers/switch_handler.py parses and carries no unused import
# seedgo: no-test-needed(stdlib) — json's rejection of a malformed document; only the refusal built on it is pinned

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.skills.apps.handlers import switch_handler as sh
from aipass.skills.apps.handlers.json import json_handler as jh
from aipass.skills.apps.modules import runner


class FakeSystemctl:
    """Models `systemctl --user` over a set of units, recording every argv it is handed."""

    def __init__(self, active=(), masked=(), stubborn=()):
        self.active = set(active)
        self.masked = set(masked)
        self.enabled = set(active)
        self.stubborn = set(stubborn)
        self.calls = []

    def __call__(self, *args, timeout=15):
        self.calls.append(list(args))
        verb = args[0]
        unit = args[1] if len(args) > 1 else None

        if verb == "is-active":
            return (0, "active", "") if unit in self.active else (3, "inactive", "")
        if verb == "stop":
            if unit not in self.stubborn:
                self.active.discard(unit)
            return (0, "", "")
        if verb == "disable":
            self.enabled.discard(unit)
            return (0, "", "")
        if verb == "mask":
            self.masked.add(unit)
            return (0, "", "")
        if verb == "unmask":
            self.masked.discard(unit)
            return (0, "", "")
        if verb == "enable":
            self.enabled.add(unit)
            return (0, "", "")
        if verb == "start":
            if unit in self.masked:
                return (1, "", f"Unit {unit} is masked.")
            self.active.add(unit)
            return (0, "", "")
        return (0, "", "")

    def verbs_for(self, unit):
        """Ordered list of verbs applied to one unit."""
        return [c[0] for c in self.calls if len(c) > 1 and c[1] == unit]


@pytest.fixture
def state_dir(tmp_path, monkeypatch):
    """Point the switch's state document at a throwaway directory.

    The json service reads the AIPASS_TEST_LOG_DIR seam per call; the directory is MEASURED
    off the service so this fixture cannot claim a sandbox the switch does not write into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    target = jh.get_json_path("switch", "data").parent
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def fake_units(monkeypatch):
    """Every declared-unit lookup answers with two fake units."""
    monkeypatch.setattr(sh, "declared_units", lambda name: ["fake-bot@one", "fake-bot@two"])


class TestStatePersistence:
    """The toggle's last value is what holds after a restart."""

    def test_state_path_follows_the_branch_json_dir(self, state_dir):
        # Resolved at call time, not import time, else isolation silently writes to the wrong place.
        assert sh.get_state_path() == state_dir / "switch_state.json"

    def test_a_skill_with_no_entry_is_on(self, state_dir):
        assert sh.is_enabled("telegram") is True

    def test_off_survives_a_process_restart(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")

        # A fresh interpreter, not importlib.reload(): reload rebinds SwitchStateUnreadable while
        # runner.py holds the old class, breaking later tests. The seam is spelled out, not inherited.
        probe = (
            "import sys;"
            "from aipass.skills.apps.handlers import switch_handler as s;"
            "sys.stdout.write(str(s.get_state_path()) + '|' + repr(s.is_enabled('telegram')))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(sh.__file__).resolve().parents[4]),
                "AIPASS_TEST_LOG_DIR": os.environ["AIPASS_TEST_LOG_DIR"],
            },
        )

        assert completed.returncode == 0, completed.stderr
        where, answer = completed.stdout.strip().split("|")
        assert Path(where) == state_dir / "switch_state.json", (
            f"the fresh interpreter read a different document than the one written: {where}"
        )
        assert answer == "False"

    def test_the_value_is_on_disk_not_in_memory(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")

        raw = json.loads((state_dir / "switch_state.json").read_text(encoding="utf-8"))
        assert raw["skills"]["telegram"]["enabled"] is False
        assert raw["skills"]["telegram"]["reason"] == "retired 08-18"

    def test_toggling_one_skill_leaves_the_others_alone(self, state_dir):
        sh.set_enabled("telegram", False)
        sh.set_enabled("github", True)
        sh.set_enabled("screen_lock", False)

        assert sh.is_enabled("telegram") is False
        assert sh.is_enabled("github") is True
        assert sh.is_enabled("screen_lock") is False

    def test_re_recording_the_same_value_keeps_the_reason(self, state_dir):
        # The reason is the record of why a skill is dark; a bare repeat must not erase it.
        sh.set_enabled("telegram", False, reason="retired 08-18 by ruling")
        sh.set_enabled("telegram", False)

        entry = sh.read_state()["telegram"]
        assert entry["reason"] == "retired 08-18 by ruling"

    def test_a_new_reason_replaces_the_old_one(self, state_dir):
        sh.set_enabled("telegram", False, reason="first reason")
        sh.set_enabled("telegram", False, reason="second reason")

        assert sh.read_state()["telegram"]["reason"] == "second reason"

    def test_flipping_the_value_drops_a_reason_that_no_longer_applies(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")
        sh.set_enabled("telegram", True)

        assert "reason" not in sh.read_state()["telegram"]

    def test_changed_only_moves_when_the_value_moves(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")
        first = sh.read_state()["telegram"]["changed"]

        sh.set_enabled("telegram", False)
        assert sh.read_state()["telegram"]["changed"] == first

        sh.set_enabled("telegram", True)
        assert sh.read_state()["telegram"]["changed"] != first

    def test_a_write_leaves_no_partial_document_behind(self, state_dir):
        sh.set_enabled("telegram", False)
        leftovers = [p.name for p in state_dir.iterdir() if p.suffix == ".tmp"]
        assert leftovers == []


# Fails CLOSED: reading an unreadable document as "all on" resurrects the processes the operator killed.
class TestUnreadableStateFailsClosed:
    """An unreadable toggle must never read as 'everything is on'."""

    def test_corrupt_state_raises_rather_than_defaulting_to_on(self, state_dir):
        (state_dir / "switch_state.json").write_text("{not json at all", encoding="utf-8")

        with pytest.raises(sh.SwitchStateUnreadable):
            sh.is_enabled("telegram")

    def test_the_refusal_names_the_file_and_the_fix(self, state_dir):
        (state_dir / "switch_state.json").write_text("{not json at all", encoding="utf-8")

        with pytest.raises(sh.SwitchStateUnreadable) as caught:
            sh.read_state()

        message = str(caught.value)
        assert "switch_state.json" in message
        assert "delete" in message.lower()

    def test_wrong_shape_is_unreadable_too(self, state_dir):
        (state_dir / "switch_state.json").write_text('["not", "a", "map"]', encoding="utf-8")

        with pytest.raises(sh.SwitchStateUnreadable):
            sh.is_enabled("telegram")

    def test_a_missing_file_is_not_corrupt(self, state_dir):
        # Missing means nobody has toggled anything: every skill is on.
        assert not (state_dir / "switch_state.json").exists()
        assert sh.read_state() == {}


class TestTurnOff:
    """OFF stops the declared processes and blocks anything from restarting them."""

    def test_off_stops_every_declared_unit(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        result = sh.turn_off("telegram", reason="retired")

        assert result["success"] is True
        assert fake.active == set()

    def test_off_masks_so_nothing_can_respawn(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        sh.turn_off("telegram")

        # Disable only stops the BOOT path; mask refuses a manual start or a dependency pull.
        for unit in ("fake-bot@one", "fake-bot@two"):
            assert unit in fake.masked
            assert unit not in fake.enabled

    def test_a_masked_unit_refuses_to_start(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        sh.turn_off("telegram")
        code, _, err = fake("start", "fake-bot@one")

        assert code != 0
        assert "masked" in err
        assert "fake-bot@one" not in fake.active

    def test_off_records_the_state_before_touching_systemd(self, state_dir, fake_units, monkeypatch):
        # Intent lands on disk FIRST: a crash mid-actuation must not leave no record of why.
        seen = {}

        def recording_systemctl(*args, timeout=15):
            seen.setdefault("enabled_at_first_call", sh.is_enabled("telegram"))
            return (0, "inactive", "")

        monkeypatch.setattr(sh, "_systemctl", recording_systemctl)
        sh.turn_off("telegram")

        assert seen["enabled_at_first_call"] is False

    def test_a_unit_that_survives_the_stop_is_reported_not_swallowed(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"], stubborn=["fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        result = sh.turn_off("telegram")

        assert result["success"] is False
        assert "fake-bot@two" in result["error"]

    def test_a_skill_with_no_declared_units_never_calls_systemctl(self, state_dir, monkeypatch):
        monkeypatch.setattr(sh, "declared_units", lambda name: [])
        fake = FakeSystemctl()
        monkeypatch.setattr(sh, "_systemctl", fake)

        result = sh.turn_off("github")

        assert result["success"] is True
        assert fake.calls == []
        assert sh.is_enabled("github") is False


class TestTurnOn:
    """ON reconnects the skill and its processes."""

    def test_on_restores_a_switched_off_skill(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        sh.turn_off("telegram")
        assert fake.active == set()

        result = sh.turn_on("telegram")

        assert result["success"] is True
        assert fake.active == {"fake-bot@one", "fake-bot@two"}
        assert sh.is_enabled("telegram") is True

    def test_on_unmasks_before_it_starts(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one"])
        monkeypatch.setattr(sh, "declared_units", lambda name: ["fake-bot@one"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        sh.turn_off("telegram")
        fake.calls.clear()
        sh.turn_on("telegram")

        verbs = fake.verbs_for("fake-bot@one")
        # systemd refuses a start issued before the unmask: the order is the contract.
        assert verbs.index("unmask") < verbs.index("start")

    def test_on_enables_so_the_unit_survives_a_reboot(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl(active=["fake-bot@one", "fake-bot@two"])
        monkeypatch.setattr(sh, "_systemctl", fake)

        sh.turn_off("telegram")
        sh.turn_on("telegram")

        assert fake.enabled == {"fake-bot@one", "fake-bot@two"}

    def test_a_unit_that_will_not_start_is_reported(self, state_dir, fake_units, monkeypatch):
        fake = FakeSystemctl()

        def refuses_to_start(*args, timeout=15):
            if args[0] == "start":
                return (1, "", "Job failed")
            if args[0] == "is-active":
                return (3, "inactive", "")
            return fake(*args, timeout=timeout)

        monkeypatch.setattr(sh, "_systemctl", refuses_to_start)
        result = sh.turn_on("telegram")

        assert result["success"] is False
        assert "fake-bot@one" in result["error"]


class TestRunnerGate:
    """The second door: AIPass must not start a skill it has switched off."""

    def test_run_skill_refuses_a_switched_off_skill(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")

        # Stubbed so a regressed gate fails here instead of running the skill's handler.
        with patch.object(runner, "run_handler") as ran_handler, patch.object(runner, "run_markdown") as ran_markdown:
            result = runner.run_skill("telegram", action="start", args={"arg0": "base"})

        assert result["success"] is False
        assert result["error"] == (
            "Skill 'telegram' is switched OFF and will not run (retired 08-18). "
            "Turn it back on with: drone @skills on telegram"
        )
        ran_handler.assert_not_called()
        ran_markdown.assert_not_called()

    def test_the_gate_runs_before_the_handler_is_even_loaded(self, state_dir):
        # A handler can start work IN-PROCESS on import: the gate bites before the load.
        sh.set_enabled("telegram", False)
        with patch.object(runner, "load_skill") as loader:
            result = runner.run_skill("telegram", action="start")

        assert result["success"] is False
        assert result["error"] == (
            "Skill 'telegram' is switched OFF and will not run. Turn it back on with: drone @skills on telegram"
        )
        loader.assert_not_called()

    def test_an_unreadable_state_document_refuses_to_run_anything(self, state_dir):
        (state_dir / "switch_state.json").write_text("{corrupt", encoding="utf-8")
        result = runner.run_skill("github", action="anything")

        assert result["success"] is False
        assert "switch_state.json" in result["error"]

    def test_an_on_skill_passes_through_the_gate(self, state_dir):
        sh.set_enabled("telegram", True)
        with patch.object(runner, "load_skill") as loader:
            loader.return_value = {
                "success": False,
                "error": "reached the loader",
                "metadata": None,
                "body": None,
                "handler": None,
                "path": None,
            }
            result = runner.run_skill("telegram", action="status")

        loader.assert_called_once()
        assert result["error"] == "reached the loader"


class TestDeclaredUnits:
    """A skill declares its own processes in SKILL.md frontmatter."""

    def test_a_skill_that_declares_nothing_gets_an_empty_list(self):
        assert sh.declared_units("github") == []

    def test_an_unknown_skill_declares_nothing(self):
        assert sh.declared_units("no_such_skill_anywhere") == []


class TestSwitchRows:
    """Status has to show a dark skill, and has to show a lying one."""

    def test_rows_carry_every_discovered_skill(self, state_dir):
        names = [row["name"] for row in sh.switch_rows()]
        assert "screen_lock" in names
        assert "github" in names

    def test_an_off_skill_is_marked_off(self, state_dir, monkeypatch):
        monkeypatch.setattr(sh, "_systemctl", FakeSystemctl())
        sh.set_enabled("screen_lock", False, reason="retired 08-18")

        row = next(r for r in sh.switch_rows() if r["name"] == "screen_lock")
        assert row["enabled"] is False
        assert row["reason"] == "retired 08-18"

    def test_a_skill_that_is_off_but_still_running_is_flagged(self, state_dir, monkeypatch):
        monkeypatch.setattr(sh, "declared_units", lambda name: ["fake-bot@one"])
        monkeypatch.setattr(sh, "_systemctl", FakeSystemctl(active=["fake-bot@one"]))
        sh.set_enabled("screen_lock", False)

        row = next(r for r in sh.switch_rows() if r["name"] == "screen_lock")
        assert row["enabled"] is False
        assert row["live_units"] == ["fake-bot@one"]
