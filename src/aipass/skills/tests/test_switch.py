# ===================AIPASS====================
# META DATA HEADER
# Name: test_switch.py - Skill off-switch tests
# Date: 2026-08-18
# Version: 1.0.0
# Category: skills/tests
#
# CHANGELOG (Max 5 entries):
#   - v1.0.0 (2026-08-18): Initial creation - DPLAN-0306 per-skill off-switch
#
# CODE STANDARDS:
#   - Pytest conventions
#   - Temp dir isolation via tmp_path - NEVER the live skills_json/ directory
#   - systemctl is ALWAYS faked - a test must never touch this machine's units
# =============================================

"""Tests for the per-skill off-switch (DPLAN-0306).

The switch has one job: OFF means the skill is disconnected. These tests pin
the four properties that make that claim true rather than hopeful:

  1. The toggle persists across a process restart (state is on disk, not in RAM).
  2. OFF stops every declared process AND blocks respawn AND gates the runner.
  3. ON restores.
  4. An unreadable state document fails CLOSED - it never reads as "all on",
     because reading it as "all on" resurrects the processes the operator killed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.skills.apps.handlers import switch_handler as sh
from aipass.skills.apps.handlers.json import json_handler as jh


# =============================================
# FAKE SYSTEMCTL
# =============================================


class FakeSystemctl:
    """Models `systemctl --user` over a set of units.

    Records every argv it is handed and answers is-active from modelled state,
    so a test can assert both what was ASKED and what the machine would SAY.
    """

    def __init__(self, active=(), masked=(), stubborn=()):
        self.active = set(active)
        self.masked = set(masked)
        self.enabled = set(active)
        # Units that refuse to die - models a stop that does not take.
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

    The redirect is the AIPASS_TEST_LOG_DIR seam the fleet json service reads
    per call (DPLAN-0325) - the shim has no attribute left to patch. The
    directory is then MEASURED off the service rather than spelled out, so this
    fixture cannot claim a sandbox the switch does not actually write into.
    """
    monkeypatch.setenv("AIPASS_TEST_LOG_DIR", str(tmp_path / "_aipass_json_seam"))
    target = jh.get_json_path("switch", "data").parent
    target.mkdir(parents=True, exist_ok=True)
    return target


@pytest.fixture
def fake_units(monkeypatch):
    """Every declared-unit lookup answers with two fake units."""
    monkeypatch.setattr(sh, "declared_units", lambda name: ["fake-bot@one", "fake-bot@two"])


# =============================================
# STATE: PERSISTENCE
# =============================================


class TestStatePersistence:
    """The toggle's last value is what holds after a restart."""

    def test_state_path_follows_the_branch_json_dir(self, state_dir):
        # Resolved at call time, not import time - else test isolation (and any
        # relocation of skills_json/) silently writes to the wrong place.
        assert sh.get_state_path() == state_dir / "switch_state.json"

    def test_a_skill_with_no_entry_is_on(self, state_dir):
        # Fresh checkout: nothing has ever been toggled, so nothing is dark.
        assert sh.is_enabled("telegram") is True

    def test_off_survives_a_process_restart(self, state_dir):
        sh.set_enabled("telegram", False, reason="retired 08-18")

        # A REAL restart: a fresh interpreter reading the same disk. An
        # in-process importlib.reload() was tried first and rejected — it
        # rebinds the module's globals, so SwitchStateUnreadable becomes a new
        # class object while runner.py still holds the old one by value, and a
        # LATER test in the same session stopped catching it. A restart test
        # that corrupts the session it runs in is not modelling a restart.
        #
        # The child is aimed at the same disk through the seam, spelled out in
        # its env rather than inherited: a pin that relies on inheritance is
        # green for a reason it never states, and would stay green if the
        # fixture stopped redirecting at all.
        probe = (
            "import sys;"
            "from aipass.skills.apps.handlers import switch_handler as s;"
            "sys.stdout.write(str(s.get_state_path()) + '|' + repr(s.is_enabled('telegram')))"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe],
            capture_output=True,
            text=True,
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
        # Found live: `off telegram "<why>"` then a bare `off telegram` wiped the
        # reason. The reason IS the record of why a skill is dark — a repeat of
        # the same instruction must not erase it.
        sh.set_enabled("telegram", False, reason="retired 08-18 by ruling")
        sh.set_enabled("telegram", False)

        entry = sh.read_state()["telegram"]
        assert entry["reason"] == "retired 08-18 by ruling"

    def test_a_new_reason_replaces_the_old_one(self, state_dir):
        sh.set_enabled("telegram", False, reason="first reason")
        sh.set_enabled("telegram", False, reason="second reason")

        assert sh.read_state()["telegram"]["reason"] == "second reason"

    def test_flipping_the_value_drops_a_reason_that_no_longer_applies(self, state_dir):
        # "retired" describes an OFF skill. Carrying it onto ON would misdescribe
        # the state it is attached to.
        sh.set_enabled("telegram", False, reason="retired 08-18")
        sh.set_enabled("telegram", True)

        assert "reason" not in sh.read_state()["telegram"]

    def test_changed_only_moves_when_the_value_moves(self, state_dir):
        # A "changed" stamp that advances on a no-op reports a change that never
        # happened, in the one document meant to be the durable truth.
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


# =============================================
# STATE: FAIL CLOSED
# =============================================


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
        # Parses as JSON, carries no skills map - we still cannot tell what is off.
        (state_dir / "switch_state.json").write_text('["not", "a", "map"]', encoding="utf-8")

        with pytest.raises(sh.SwitchStateUnreadable):
            sh.is_enabled("telegram")

    def test_a_missing_file_is_not_corrupt(self, state_dir):
        # Missing and unreadable are different worlds: missing means nobody has
        # toggled anything, and every skill is on.
        assert not (state_dir / "switch_state.json").exists()
        assert sh.read_state() == {}


# =============================================
# OFF: STOPS AND STAYS STOPPED
# =============================================


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

        # Disabled alone only stops the BOOT path; mask is what refuses a
        # manual start, a dependency pull, or a script that knows better.
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
        # Intent lands on disk FIRST: a crash mid-actuation must not leave a
        # machine going dark with no record of why.
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

        # Never print "dark" over a live process.
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


# =============================================
# ON: RESTORES
# =============================================


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
        # A start issued before the unmask is refused by systemd - order is the
        # whole contract here, not a stylistic preference.
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


# =============================================
# THE RUNNER GATE
# =============================================


class TestRunnerGate:
    """The second door: AIPass must not start a skill it has switched off."""

    def test_run_skill_refuses_a_switched_off_skill(self, state_dir):
        from aipass.skills.apps.modules import runner

        sh.set_enabled("telegram", False, reason="retired 08-18")

        # run_handler/run_markdown are stubbed so that a REGRESSION of the gate
        # fails this test instead of executing the skill. Proven necessary: with
        # the gate mutated out and these unstubbed, this call reached
        # bot_operations.start_bot() and hung for 300s trying to bring up a real
        # Telegram bot. A test for an off-switch must not be able to start the
        # thing it is switching off.
        with patch.object(runner, "run_handler") as ran_handler, patch.object(runner, "run_markdown") as ran_markdown:
            result = runner.run_skill("telegram", action="start", args={"arg0": "base"})

        assert result["success"] is False
        assert "off" in result["error"].lower()
        ran_handler.assert_not_called()
        ran_markdown.assert_not_called()

    def test_the_gate_runs_before_the_handler_is_even_loaded(self, state_dir):
        # Stopping systemd units is not enough: `run telegram start base` spawns
        # a bot IN-PROCESS. The gate has to bite before the handler is imported.
        from aipass.skills.apps.modules import runner

        sh.set_enabled("telegram", False)
        with patch.object(runner, "load_skill") as loader:
            result = runner.run_skill("telegram", action="start")

        assert result["success"] is False
        loader.assert_not_called()

    def test_an_unreadable_state_document_refuses_to_run_anything(self, state_dir):
        from aipass.skills.apps.modules import runner

        (state_dir / "switch_state.json").write_text("{corrupt", encoding="utf-8")
        result = runner.run_skill("github", action="anything")

        assert result["success"] is False
        assert "switch_state.json" in result["error"]

    def test_an_on_skill_passes_through_the_gate(self, state_dir):
        from aipass.skills.apps.modules import runner

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


# =============================================
# DECLARATION
# =============================================


class TestDeclaredUnits:
    """A skill declares its own processes in SKILL.md frontmatter."""

    EXPECTED_TELEGRAM_UNITS = [
        "telegram-bot@api",
        "telegram-bot@base",
        "telegram-bot@devpulse",
        "telegram-bot@prax_monitor",
        "telegram-bot@scheduler",
    ]

    def test_telegram_declares_its_five_bots(self):
        assert sorted(sh.declared_units("telegram")) == self.EXPECTED_TELEGRAM_UNITS

    def test_the_declaration_reads_the_same_without_pyyaml(self):
        # THE CI RED OF 2026-08-19 (run 32222871212). This assertion passed on
        # a developer machine and failed on every runner, and the difference was
        # never machine-local STATE — every file it reads is tracked. PyYAML is
        # not declared in pyproject.toml, so a runner falls back to the parser
        # in discovery_handler, which silently answered "" for a block list.
        # An environment-dependent pin proves nothing; this one names the
        # environment and asserts both halves of it.
        from aipass.skills.apps.handlers import discovery_handler as dh

        with patch.object(dh, "yaml", None):
            without_yaml = sh.declared_units("telegram")

        assert sorted(without_yaml) == self.EXPECTED_TELEGRAM_UNITS
        assert sorted(without_yaml) == sorted(sh.declared_units("telegram"))

    def test_every_file_the_declaration_reads_is_tracked(self):
        # The other half of the same lesson: if this skill's SKILL.md ever stops
        # shipping, the pin above must fail LOUDLY here rather than quietly
        # asserting against a file only this machine has.
        from aipass.skills.apps.handlers.discovery_handler import get_search_paths

        builtin = [path for path, source in get_search_paths() if source == "builtin"][0]
        assert (builtin / "telegram" / "SKILL.md").exists(), (
            "telegram's SKILL.md is missing from the built-in lib — the declaration "
            "test above would be asserting against nothing"
        )

    def test_a_skill_that_declares_nothing_gets_an_empty_list(self):
        # github is markdown-only - it owns no processes and must not fabricate any.
        assert sh.declared_units("github") == []

    def test_an_unknown_skill_declares_nothing(self):
        assert sh.declared_units("no_such_skill_anywhere") == []


# =============================================
# STATUS REPORTING
# =============================================


class TestSwitchRows:
    """Status has to show a dark skill, and has to show a lying one."""

    def test_rows_carry_every_discovered_skill(self, state_dir):
        names = [row["name"] for row in sh.switch_rows()]
        assert "telegram" in names
        assert "github" in names

    def test_an_off_skill_is_marked_off(self, state_dir, monkeypatch):
        monkeypatch.setattr(sh, "_systemctl", FakeSystemctl())
        sh.set_enabled("telegram", False, reason="retired 08-18")

        row = next(r for r in sh.switch_rows() if r["name"] == "telegram")
        assert row["enabled"] is False
        assert row["reason"] == "retired 08-18"

    def test_a_skill_that_is_off_but_still_running_is_flagged(self, state_dir, monkeypatch):
        # State says dark, machine says alive. Status must not repeat the state's
        # claim - that discrepancy is the whole reason to look.
        monkeypatch.setattr(sh, "declared_units", lambda name: ["fake-bot@one"])
        monkeypatch.setattr(sh, "_systemctl", FakeSystemctl(active=["fake-bot@one"]))
        sh.set_enabled("telegram", False)

        row = next(r for r in sh.switch_rows() if r["name"] == "telegram")
        assert row["enabled"] is False
        assert row["live_units"] == ["fake-bot@one"]
