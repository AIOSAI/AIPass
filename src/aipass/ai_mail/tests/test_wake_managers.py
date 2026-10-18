# =================== AIPass ====================
# Name: test_wake_managers.py
# Description: Tests for the wake's manager lanes, the wake-back opt-out, the Fable grant read and the dashboard refresh
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/dispatch/wake.py's manager lanes, wake-back and wake_dashboard.py's refresh."""

# Who may be woken and how, and what the wake promises other branches.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — wake_branch()'s spawn, session pointer and model: tests/test_wake.py

import json
import sys
import threading
import pytest
from pathlib import Path as _Path
from unittest.mock import MagicMock

import aipass.ai_mail.apps.handlers.dispatch.wake as wake_mod
import aipass.ai_mail.apps.handlers.dispatch.wake_dashboard as wake_dashboard_mod
import aipass.prax.apps.modules.dashboard as prax_dashboard_mod
from aipass.ai_mail.apps.handlers.dispatch import register as register_mod
from aipass.ai_mail.apps.handlers.dispatch.wake_dashboard import refresh_recipient_dashboard
from aipass.ai_mail.apps.handlers.dispatch.wake import (
    DEFAULT_MODEL,
    wake_branch,
)
from aipass.ai_mail.tests.support_wake import (
    _FakeProc,
    _make_scheduled_fixtures,
    _make_wake_fixtures,
    _patch_wake_deps,
    _record_spawn_routes,
)

pytestmark = pytest.mark.usefixtures("wake_log_operation_suppressed")


class TestScheduledManagerLane:
    """The opt-in scheduled lane: manager wakes run headless with the 350k pin.

    The pin lives in dispatch_monitor, so what wake can prove is the route to the monitor.
    """

    def test_daemon_manager_wake_is_interactive_tmux_with_no_pin(self, tmp_path, monkeypatch):
        """The hole this lane closes: a @daemon-sender manager wake spawns tmux, which sets no pin."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon")

        assert ok is True
        assert [c[:2] for c in calls["tmux"]] == [
            ["tmux", "new-session"],
            ["tmux", "set-option"],
            ["tmux", "send-keys"],
        ]
        assert calls["popen"] == [], "interactive manager wake must not reach the monitor pipeline"
        # No monitor process means no pin site at all.
        assert not any(str(wake_mod.MONITOR_SCRIPT) in " ".join(c) for c in calls["tmux"])

    def test_scheduled_manager_wake_routes_headless_through_monitor(self, tmp_path, monkeypatch):
        """scheduled=True on a manager routes to dispatch_monitor, not tmux."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=True)

        assert ok is True
        assert calls["tmux"] == [], "scheduled manager wake must not spawn an interactive session"
        assert len(calls["popen"]) == 1
        assert str(wake_mod.MONITOR_SCRIPT) in calls["popen"][0]["cmd"]
        assert any(s[0] == "ok" and s[1] == "scheduled" for s in status.steps)

    def test_scheduled_wake_with_an_unreadable_passport_still_runs(self, tmp_path, monkeypatch):
        """The fail-closed skip is the default lane's alone: the scheduled lane wakes managers too."""
        branch_path = _make_scheduled_fixtures(tmp_path, monkeypatch)
        (branch_path / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@flow", scheduled=True)

        assert ok is True
        assert status.find_step("manager") is None
        assert len(calls["popen"]) == 1

    def test_an_unreadable_safety_config_refuses_the_wake(self, tmp_path, monkeypatch):
        """No spawn on an unreadable safety config: its max_turns may be under the default 100."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        (tmp_path / "safety_config.json").write_text("{max_turns", encoding="utf-8")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@flow", scheduled=True)

        assert ok is False
        config = status.find_step("config")
        assert config is not None
        assert config[0] == "fail"
        assert config[2].startswith("safety_config.json could not be read")
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_scheduled_manager_wake_hands_the_pin_site_the_spawn(self, tmp_path, monkeypatch):
        """The monitor is argv[1] and wake's own env carries no CLAUDE_* leak.

        A parent CLAUDE_* window in the env could be read as the effective pin.
        """
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        monkeypatch.setenv("CLAUDE_CODE_AUTO_COMPACT_WINDOW", "999999")
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=True)

        assert ok is True
        spawned = calls["popen"][0]
        assert spawned["cmd"][1] == str(wake_mod.MONITOR_SCRIPT)
        assert not any(k.startswith("CLAUDE") for k in spawned["env"])

    def test_scheduled_wake_refuses_blocklisted_target_with_named_reason(self, tmp_path, monkeypatch):
        """@devpulse stays refused in the scheduled lane — named reason, no spawn."""
        _make_scheduled_fixtures(tmp_path, monkeypatch, email="@devpulse")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@devpulse", sender="@daemon", scheduled=True)

        assert ok is False
        blocked = status.find_step("blocklist")
        assert blocked is not None, "refusal must be a named step, not a silent False"
        assert blocked[0] == "fail"
        assert "@devpulse" in blocked[2]
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_scheduled_blocklist_refusal_survives_an_unreadable_passport(self, tmp_path, monkeypatch):
        """The refusal is checked before the passport read, so a missing or
        corrupt passport can never be the reason a blocked target gets spawned."""
        branch_path = _make_scheduled_fixtures(tmp_path, monkeypatch, email="@devpulse")
        (branch_path / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@devpulse", sender="@daemon", scheduled=True)

        assert ok is False
        assert status.find_step("blocklist") is not None
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_scheduled_defaults_false_and_is_keyword_only(self, tmp_path, monkeypatch):
        """The param cannot be set positionally — existing call sites keep their meaning."""
        import inspect

        param = inspect.signature(wake_branch).parameters["scheduled"]
        assert param.default is False
        assert param.kind is inspect.Parameter.KEYWORD_ONLY

    def test_scheduled_false_keeps_manager_wake_interactive(self, tmp_path, monkeypatch):
        """Explicit scheduled=False on a manager is the tmux path, unchanged."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=False)

        assert ok is True
        assert [c[:2] for c in calls["tmux"]] == [
            ["tmux", "new-session"],
            ["tmux", "set-option"],
            ["tmux", "send-keys"],
        ]
        assert calls["popen"] == []

    def test_scheduled_non_manager_spawn_is_byte_identical(self, tmp_path, monkeypatch):
        """Non-manager target: scheduled=True changes nothing about the spawn."""
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        _, ok_default = wake_branch("@testbranch", custom_message="nightly sweep", sender="@daemon")
        _, ok_scheduled = wake_branch("@testbranch", custom_message="nightly sweep", sender="@daemon", scheduled=True)

        assert ok_default is True and ok_scheduled is True
        assert len(calls["popen"]) == 2
        assert calls["popen"][0]["cmd"] == calls["popen"][1]["cmd"]
        assert calls["tmux"] == []


class TestAdminManagerLane:
    """The admin lane: a verified admin dispatch wakes a
    manager-class target headless, like any citizen dispatch.

    These pin what the flag ROUTES; what earns it is test_admin_lane.py.
    """

    def test_admin_manager_wake_routes_headless_through_monitor(self, tmp_path, monkeypatch):
        """admin=True on a manager reaches dispatch_monitor, not tmux, not the skip."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@devpulse", admin=True)

        assert ok is True
        assert calls["tmux"] == []
        assert len(calls["popen"]) == 1
        assert str(wake_mod.MONITOR_SCRIPT) in calls["popen"][0]["cmd"]

    def test_admin_lane_records_a_named_status_step(self, tmp_path, monkeypatch):
        """A caller can see WHICH lane fired, not just that something spawned."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@devpulse", admin=True)

        admin_step = status.find_step("admin")
        assert admin_step is not None and admin_step[0] == "ok"
        manager_step = status.find_step("manager")
        assert manager_step is not None and manager_step[0] == "ok"
        # The scheduled lane did not fire — the two must stay distinguishable.
        assert status.find_step("scheduled") is None

    def test_admin_false_leaves_the_manager_gate_exactly_as_it_was(self, tmp_path, monkeypatch):
        """Default: mail only, wake skipped, nothing spawned."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@devpulse")

        assert ok is True
        assert calls["popen"] == [] and calls["tmux"] == []
        manager_step = status.find_step("manager")
        assert manager_step is not None and manager_step[0] == "info"
        assert status.find_step("admin") is None

    def test_admin_wake_still_refuses_a_blocklisted_target(self, tmp_path, monkeypatch):
        """@devpulse stays undispatchable — admin raises the stakes, not the fence."""
        _make_scheduled_fixtures(tmp_path, monkeypatch, email="@devpulse")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@devpulse", sender="@devpulse", admin=True)

        assert ok is False
        blocked = status.find_step("blocklist")
        assert blocked is not None and blocked[0] == "fail"
        assert "@devpulse" in blocked[2]
        assert calls["popen"] == [] and calls["tmux"] == []

    def test_admin_non_manager_spawn_is_byte_identical(self, tmp_path, monkeypatch):
        """Non-manager target: admin=True changes nothing about the spawn."""
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        _, ok_default = wake_branch("@testbranch", custom_message="work", sender="@devpulse")
        _, ok_admin = wake_branch("@testbranch", custom_message="work", sender="@devpulse", admin=True)

        assert ok_default is True and ok_admin is True
        assert len(calls["popen"]) == 2
        assert calls["popen"][0]["cmd"] == calls["popen"][1]["cmd"]

    def test_admin_is_keyword_only_and_defaults_false(self):
        """No positional path to privilege — every existing call site keeps its meaning."""
        import inspect

        param = inspect.signature(wake_branch).parameters["admin"]
        assert param.default is False
        assert param.kind is inspect.Parameter.KEYWORD_ONLY

    def test_scheduled_lane_wins_when_both_flags_are_set(self, tmp_path, monkeypatch):
        """Both route headless; the status names the scheduled lane, so a 5am
        rotation is never reported as an admin dispatch."""
        _make_scheduled_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", sender="@daemon", scheduled=True, admin=True)

        assert ok is True
        assert len(calls["popen"]) == 1
        assert status.find_step("scheduled") is not None
        assert status.find_step("admin") is None


class TestWakeBackOptOut:
    """wake_back=False: a library caller (@daemon's scheduled nudges) declines
    the completion wake-back.

    It travels as an ARGV flag, never an env var: spawn_env leaks into the agent's own dispatches.
    """

    def test_wake_back_is_keyword_only_and_defaults_true(self):
        """Every existing call site keeps the wake-back without saying so."""
        import inspect

        param = inspect.signature(wake_branch).parameters["wake_back"]
        assert param.default is True
        assert param.kind is inspect.Parameter.KEYWORD_ONLY

    def test_declining_puts_the_flag_before_the_separator(self, tmp_path, monkeypatch):
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", custom_message="nudge", sender="@daemon", wake_back=False)

        assert ok is True
        spawned = calls["popen"][0]
        cmd = spawned["cmd"]
        sep = cmd.index("--")
        assert sep == 7, "the flag sits between the four positionals and '--'"
        assert cmd[2] == "@testbranch" and cmd[4] == "@daemon", "sender passes through unchanged"
        assert cmd[sep - 1] == "--no-wake-back"
        assert "--no-wake-back" not in cmd[sep + 1 :], "the flag must not reach claude's argv"
        assert not any("WAKE_BACK" in key for key in spawned["env"]), "carried by argv, never by env"

    def test_the_default_argv_keeps_the_separator_right_after_the_positionals(self, tmp_path, monkeypatch):
        """Byte-identical to the shape before the option existed."""
        branch_path = _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        status, ok = wake_branch("@testbranch", custom_message="work", sender="@devpulse")

        assert ok is True
        cmd = calls["popen"][0]["cmd"]
        assert cmd[:7] == [
            sys.executable,
            str(wake_mod.MONITOR_SCRIPT),
            "@testbranch",
            str(branch_path / ".ai_mail.local" / ".dispatch.lock"),
            "@devpulse",
            str(branch_path / "logs" / "dispatch_stderr.log"),
            "--",
        ]
        assert "--no-wake-back" not in cmd

    def test_the_flag_is_the_only_difference_a_decline_makes(self, tmp_path, monkeypatch):
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        calls = _record_spawn_routes(monkeypatch)

        wake_branch("@testbranch", custom_message="work", sender="@daemon")
        wake_branch("@testbranch", custom_message="work", sender="@daemon", wake_back=True)
        wake_branch("@testbranch", custom_message="work", sender="@daemon", wake_back=False)

        default_cmd, explicit_cmd, declined_cmd = (c["cmd"] for c in calls["popen"])
        assert explicit_cmd == default_cmd
        assert declined_cmd != default_cmd
        assert [a for a in declined_cmd if a != "--no-wake-back"] == default_cmd

    def test_a_declined_wake_back_is_written_on_the_register_row(self, tmp_path, monkeypatch):
        """A reader of the register can tell a declined wake-back from a lost one."""
        _make_scheduled_fixtures(tmp_path, monkeypatch, citizen_class="aipass_framework")
        _patch_wake_deps(monkeypatch)
        _record_spawn_routes(monkeypatch)

        wake_branch("@testbranch", custom_message="nudge", sender="@daemon", wake_back=False)

        rows = register_mod.outstanding()
        assert len(rows) == 1
        assert rows[0]["wake_back"] is False


class TestIsManager:
    """is_manager() — the promise at dispatch time must match the delivery."""

    def _passport(self, tmp_path, name, citizen_class):
        branch = tmp_path / name
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"identity": {"citizen_class": citizen_class}}), encoding="utf-8"
        )
        return branch

    def test_manager_passport_is_manager(self, tmp_path, monkeypatch):
        branch = self._passport(tmp_path, "devpulse", "manager")
        monkeypatch.setattr(wake_mod, "resolve_branch", lambda e, admin=False: (branch, e))
        assert wake_mod.is_manager("@devpulse") is True

    def test_ordinary_citizen_is_not(self, tmp_path, monkeypatch):
        branch = self._passport(tmp_path, "prax", "aipass_framework")
        monkeypatch.setattr(wake_mod, "resolve_branch", lambda e, admin=False: (branch, e))
        assert wake_mod.is_manager("@prax") is False

    def test_unreadable_passport_is_not_a_manager(self, tmp_path, monkeypatch):
        """Fail toward the ordinary path: an unknown citizen is woken, which is
        the behaviour that existed before this helper. Never invent a manager."""
        monkeypatch.setattr(wake_mod, "resolve_branch", lambda e, admin=False: (tmp_path / "nope", e))
        assert wake_mod.is_manager("@ghost") is False

    def test_a_passport_that_cannot_be_read_is_treated_as_a_manager(self, tmp_path, monkeypatch):
        """Fail closed: an unreadable passport answers True, the same as the wake gate.

        A missing passport (above) stays False: no class was ever declared.
        """
        branch = tmp_path / "corrupt"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{not json", encoding="utf-8")
        monkeypatch.setattr(wake_mod, "resolve_branch", lambda e, admin=False: (branch, e))
        assert wake_mod.is_manager("@corrupt") is True

    def test_an_unreadable_registry_is_treated_as_a_manager(self, repo_root):
        """Fail closed: a seat that cannot be resolved has an unknown class, so True."""
        (repo_root / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")
        assert wake_mod.is_manager("@corrupt") is True

    def test_manager_gate_log_does_not_claim_mail_it_did_not_send(self):
        """wake_branch's manager gate sends NO mail — the caller does — so its log must not claim one."""
        src = _Path(wake_mod.__file__).read_text(encoding="utf-8")
        assert "wake skipped, mail delivered" not in src


class TestTheGrantIsReadFromTheUntrackedConfig:
    """fable_allowed() — The owner edits the grant, the repo does not ship it.

    Every fallback fails toward the written default, never toward an empty grant (a silent demotion).
    """

    def test_a_missing_config_falls_back_to_the_written_default(self, monkeypatch, tmp_path):
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", tmp_path / "nothing_here.json")

        assert wake_mod.fable_allowed() == wake_mod.FABLE_GRANT_DEFAULT
        assert "@devpulse" in wake_mod.fable_allowed()

    def test_an_unparseable_config_falls_back_to_the_default(self, monkeypatch, tmp_path):
        config = tmp_path / "safety_config.json"
        config.write_text("{not json{{{", encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == wake_mod.FABLE_GRANT_DEFAULT

    def test_a_config_without_the_key_falls_back_to_the_default(self, monkeypatch, tmp_path):
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"max_turns_per_wake": 100}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == wake_mod.FABLE_GRANT_DEFAULT

    def test_a_grant_that_is_not_a_list_falls_back_to_the_default(self, monkeypatch, tmp_path):
        """The typo shape: a bare string instead of a list. Iterating it would
        grant '@', '@d', '@e' — a frozenset of letters that matches nobody, i.e.
        a silent revocation dressed as a config."""
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"fable_allowed": "@devpulse"}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == wake_mod.FABLE_GRANT_DEFAULT

    def test_a_written_grant_replaces_the_default_entirely(self, monkeypatch, tmp_path):
        """The owner moving the seat means the default no longer applies — this is
        a replacement, not an addition, or a revoked seat could never be revoked."""
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"fable_allowed": ["@someone_else"]}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == frozenset({"@someone_else"})
        assert "@devpulse" not in wake_mod.fable_allowed()

    def test_an_explicit_empty_list_revokes_the_grant_from_everyone(self, monkeypatch, tmp_path):
        """A decision, not an accident, and distinguishable from the key being
        absent. It is the spelling for turning Fable off fleet-wide."""
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"fable_allowed": []}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == frozenset()
        assert wake_mod.resolve_wake_model("@devpulse", "fable").model == DEFAULT_MODEL

    def test_written_entries_are_normalised_like_every_other_address(self, monkeypatch, tmp_path):
        config = tmp_path / "safety_config.json"
        config.write_text(json.dumps({"fable_allowed": ["DevPulse", "@Vera"]}), encoding="utf-8")
        monkeypatch.setattr(wake_mod, "CONFIG_FILE", config)

        assert wake_mod.fable_allowed() == frozenset({"@devpulse", "@vera"})

    def test_the_grant_lives_where_the_repo_does_not_ship_it(self):
        """The config path is inside .ai_mail.local/, which is gitignored."""
        assert wake_mod.CONFIG_FILE.parent.name == ".ai_mail.local"


class TestDispatchStatusLabelsAreACrossBranchContract:
    """@daemon's scheduler classifies BLOCKED-vs-FAILED by these four step
    LABELS plus a fail status, never by ``status.summary``.

    A lost label makes their scheduler read "never started" as "ran and failed". Tell @daemon before renaming one.
    """

    CONTRACT = ("pause", "lock", "blocked", "lock-acquire")

    def test_every_contracted_label_still_exists_in_the_wake_lane(self):
        """Cheap and total: the four strings @daemon reads must still be emitted
        somewhere in wake.py (a grep survives refactors of which path emits one)."""
        src = _Path(wake_mod.__file__).read_text(encoding="utf-8")
        missing = [label for label in self.CONTRACT if f'"{label}"' not in src]
        assert missing == [], (
            f"@daemon's scheduler reads these step labels: {missing} no longer exist. "
            "Tell them before moving one — their block-vs-fail classification depends on it."
        )

    @staticmethod
    def _kind(status, label):
        """The step's kind ("ok", "fail", ...), or None when the label is absent."""
        step = status.find_step(label)
        return step[0] if step is not None else None

    def test_pause_is_a_named_fail_step(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        pause = tmp_path / ".aipass" / "autonomous_pause"
        pause.parent.mkdir(parents=True, exist_ok=True)
        pause.touch()

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is False
        assert self._kind(status, "pause") == "fail"

    def test_an_active_lock_is_a_named_fail_step_under_auto(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, check_lock=lambda p: {"pid": 999, "timestamp": "now"})

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is False
        assert self._kind(status, "lock") == "fail"

    def test_occupancy_is_the_blocked_step(self, tmp_path, monkeypatch):
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        occupied = MagicMock(return_value=True)
        _patch_wake_deps(monkeypatch, is_branch_occupied=occupied)

        status, ok = wake_branch("@testbranch", auto=True)

        occupied.assert_called_once_with(branch_path)
        assert ok is False
        assert self._kind(status, "blocked") == "fail"

    def test_a_refused_lock_acquire_is_its_own_named_step(self, tmp_path, monkeypatch):
        _make_wake_fixtures(tmp_path, monkeypatch)
        _patch_wake_deps(monkeypatch, acquire_lock=lambda p, pid: (False, "held by 4242"))
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())

        status, ok = wake_branch("@testbranch", auto=True)

        assert self._kind(status, "lock-acquire") == "fail"

    def test_resolve_and_blocklist_stay_failures_on_purpose(self, tmp_path, monkeypatch):
        """The other half of their rule, pinned so it is not "fixed" into
        consistency later: neither is transient, so nothing about waiting two
        more minutes changes the answer. They must NOT join the blocked set."""
        _make_wake_fixtures(tmp_path, monkeypatch)

        status, ok = wake_branch("@nonexistent")

        assert ok is False
        assert self._kind(status, "resolve") == "fail"
        assert status.find_step("blocked") is None, "a missing branch is not a transient block"


class TestRecipientDashboardRefresh:
    """The recipient's dashboard is refreshed BEFORE their session spawns.

    One branch, never the fleet, and FAIL-OPEN: every failure mode below still spawns.
    """

    @staticmethod
    def _prax(monkeypatch, fake=None, fleet_guard=True):
        """Patch the prax entry point where the wake imports it from — the
        MODULE door (apps/modules/dashboard.py), prax's published surface."""
        prax_refresh = prax_dashboard_mod

        if fake is not None:
            monkeypatch.setattr(prax_refresh, "refresh_single_dashboard", fake)
        if fleet_guard:

            def _refused_fleet():
                raise AssertionError("the wake must never refresh all 18 branches")

            monkeypatch.setattr(prax_refresh, "refresh_all_dashboards", _refused_fleet)
        return prax_refresh

    @staticmethod
    def _real_refresh(monkeypatch, **overrides):
        """_patch_wake_deps, but with the REAL refresh hook left in place."""
        _patch_wake_deps(
            monkeypatch,
            _refresh_recipient_dashboard=refresh_recipient_dashboard,
            **overrides,
        )

    def test_the_recipient_dashboard_is_refreshed_before_the_spawn(self, tmp_path, monkeypatch):
        """Order is the whole claim: refresh, THEN the process that reads it."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)
        order = []

        def _fake_refresh(path):
            order.append(("refresh", path))
            return {"status": "success", "branch": path.name.upper()}

        self._prax(monkeypatch, _fake_refresh)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: order.append(("spawn", None)) or _FakeProc())

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is True
        assert [step for step, _ in order] == ["refresh", "spawn"]
        assert order[0][1] == branch_path, "the RECIPIENT's branch, not the caller's"
        dashboard_step = status.find_step("dashboard")
        assert dashboard_step is not None, "the dashboard gate must record its own verdict"
        assert dashboard_step[0] == "ok"

    def test_the_refresh_is_one_branch_never_the_fleet(self, tmp_path, monkeypatch):
        """--all is 18 branches and 18x the cost; the recipient is one."""
        branch_path = _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)
        refreshed = []

        self._prax(monkeypatch, lambda path: refreshed.append(path) or {"status": "success", "branch": "X"})
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is True
        assert refreshed == [branch_path]

    def test_a_raising_refresh_does_not_cost_the_wake(self, tmp_path, monkeypatch):
        """Fail-open, named: the warning carries the branch and the reason."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)
        spawned = []

        def _boom(path):
            raise RuntimeError("AIPASS_REGISTRY.json is unreadable")

        self._prax(monkeypatch, _boom)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: spawned.append(1) or _FakeProc())

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is True, "a wake must never die on a dashboard"
        assert spawned == [1]
        dashboard_step = status.find_step("dashboard")
        assert dashboard_step is not None, "the dashboard gate must record its own verdict"
        kind, _, detail = dashboard_step
        assert kind == "warn"
        assert "@testbranch" in detail and "unreadable" in detail

    def test_a_refresh_over_the_bound_does_not_cost_the_wake(self, tmp_path, monkeypatch):
        """A refresh that hangs is overtaken, not waited on."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)
        # Patched where it is READ: the bound lives beside the function now.
        monkeypatch.setattr(wake_dashboard_mod, "DASHBOARD_REFRESH_TIMEOUT", 0.05)
        spawned = []
        release = threading.Event()

        def _hang(path):
            release.wait(30)
            return {"status": "success", "branch": "X"}

        self._prax(monkeypatch, _hang)
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: spawned.append(1) or _FakeProc())

        try:
            status, ok = wake_branch("@testbranch", auto=True)
        finally:
            release.set()

        assert ok is True
        assert spawned == [1]
        dashboard_step = status.find_step("dashboard")
        assert dashboard_step is not None, "the dashboard gate must record its own verdict"
        kind, _, detail = dashboard_step
        assert kind == "warn"
        assert "@testbranch" in detail

    def test_an_error_status_from_prax_is_a_warning_not_an_ok(self, tmp_path, monkeypatch):
        """prax swallows its own exception and RETURNS the failure — read it."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)

        self._prax(monkeypatch, lambda path: {"status": "error", "branch": "TESTBRANCH", "error": "no centrals"})
        monkeypatch.setattr("subprocess.Popen", lambda *a, **kw: _FakeProc())

        status, ok = wake_branch("@testbranch", auto=True)

        assert ok is True
        dashboard_step = status.find_step("dashboard")
        assert dashboard_step is not None, "the dashboard gate must record its own verdict"
        kind, _, detail = dashboard_step
        assert kind == "warn"
        assert "no centrals" in detail

    def test_the_interactive_manager_lane_refreshes_too(self, tmp_path, monkeypatch):
        """Placed above the tmux branch, so all three spawn lanes inherit it."""
        _make_wake_fixtures(tmp_path, monkeypatch)
        self._real_refresh(monkeypatch)
        order = []

        def _fake_run(cmd, **kwargs):
            order.append(("tmux", list(cmd)[:2]))

            class _Done:
                returncode = 0
                stderr = ""

            return _Done()

        self._prax(monkeypatch, lambda path: order.append(("refresh", path)) or {"status": "success", "branch": "X"})
        monkeypatch.setattr(wake_mod.shutil, "which", lambda name: "/usr/bin/tmux")
        monkeypatch.setattr(wake_mod.subprocess, "run", _fake_run)

        status, ok = wake_branch("@testbranch", custom_message="go", sender="@daemon")

        assert ok is True
        assert order[0][0] == "refresh"
        dashboard_step = status.find_step("dashboard")
        assert dashboard_step is not None, "the dashboard gate must record its own verdict"
        assert dashboard_step[0] == "ok"
