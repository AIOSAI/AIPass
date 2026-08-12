# =================== AIPass ====================
# Name: test_rotation.py
# Description: Tests for the steward rotation handler and module
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for the nightly steward rotation (DPLAN-0287)."""

from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule.rotation import (
    ALWAYS_EXCLUDED,
    HISTORY_LIMIT,
    OUTCOME_FAILED,
    OUTCOME_MISSED,
    OUTCOME_SKIPPED,
    OUTCOME_WOKEN,
    ROTATION_STATE_KEY,
    STEWARD_PROMPT_TEMPLATE,
    build_roster,
    get_rotation_state,
    next_target,
    record_rotation,
    render_prompt,
)
from aipass.daemon.apps.modules import rotation as rotation_module

HANDLER = "aipass.daemon.apps.handlers.schedule.rotation"
MODULE = "aipass.daemon.apps.modules.rotation"


# ── Fixtures ──────────────────────────────────────────


def citizen(email: str, source: str = "aipass") -> dict:
    """Build a citizen record as discovery.active_citizens() returns them."""
    name = email.lstrip("@")
    return {
        "name": name.upper(),
        "email": email,
        "dir_name": name,
        "path": Path(f"/repo/src/aipass/{name}"),
        "source": source,
    }


@pytest.fixture
def fleet():
    """A small fleet: two framework citizens, devpulse, and a project manager."""
    return [
        citizen("@backup"),
        citizen("@devpulse"),
        citizen("@commons"),
        citizen("@baud", source="projects/baud"),
    ]


@pytest.fixture
def classes():
    """citizen_class per email for the `fleet` fixture."""
    return {
        "@backup": "aipass_framework",
        "@devpulse": "manager",
        "@commons": "aipass_framework",
        "@baud": "manager",
    }


@pytest.fixture
def roster(fleet, classes):
    """The default roster built from the fleet fixture (managers excluded)."""
    with (
        patch(f"{HANDLER}.active_citizens", return_value=fleet),
        patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
    ):
        return build_roster()


def rotation_job(**overrides) -> dict:
    """A discovered rotation job dict."""
    job = {
        "owner": "@daemon",
        "id": "fleet-steward",
        "enabled": True,
        "schedule": {"type": "rotation", "time": "05:00"},
        "wake": {"fresh": True, "model": "sonnet"},
        "config": {"include_managers": False},
        "prompt": "STEWARD NIGHT for {branch}. Do the work, then STOP.",
    }
    job.update(overrides)
    return job


class FakeStatus:
    """Stand-in for ai_mail's DispatchStatus."""

    def __init__(self, summary: str):
        self.summary = summary


# ── build_roster ──────────────────────────────────────


class TestBuildRoster:
    def test_devpulse_is_never_on_the_roster(self, roster):
        assert "@devpulse" not in [c["email"] for c in roster]

    def test_devpulse_excluded_even_with_managers_included(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            included = build_roster(include_managers=True)
        assert "@devpulse" not in [c["email"] for c in included]
        assert "@devpulse" in ALWAYS_EXCLUDED

    def test_managers_excluded_when_knob_off(self, roster):
        assert [c["email"] for c in roster] == ["@backup", "@commons"]

    def test_managers_included_when_knob_on(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            included = build_roster(include_managers=True)
        assert [c["email"] for c in included] == ["@backup", "@commons", "@baud"]

    def test_roster_keeps_registry_order_and_source(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            included = build_roster(include_managers=True)
        assert included[-1]["source"] == "projects/baud"
        assert included[-1]["citizen_class"] == "manager"

    def test_empty_fleet_gives_empty_roster(self):
        with patch(f"{HANDLER}.active_citizens", return_value=[]):
            assert build_roster() == []


# ── next_target ───────────────────────────────────────


def whose_turn(roster: list, last_target) -> str:
    """Email of the citizen next_target picks — fails loudly on an empty pick."""
    entry = next_target(roster, last_target)
    assert entry is not None
    return entry["email"]


class TestNextTarget:
    def test_empty_roster_returns_none(self):
        assert next_target([], None) is None

    def test_first_run_starts_at_top(self, roster):
        assert whose_turn(roster, None) == "@backup"

    def test_advances_one_step(self, roster):
        assert whose_turn(roster, "@backup") == "@commons"

    def test_wraps_at_the_end(self, roster):
        assert whose_turn(roster, "@commons") == "@backup"

    def test_unknown_last_target_restarts_cycle(self, roster):
        assert whose_turn(roster, "@retired") == "@backup"


# ── rotation state ────────────────────────────────────


class TestRecordRotation:
    def test_pointer_advances_to_target(self):
        runstate = {}
        record_rotation(runstate, "@daemon/fleet-steward", "@backup", OUTCOME_WOKEN)
        state = get_rotation_state(runstate, "@daemon/fleet-steward")
        assert state["last_target"] == "@backup"
        assert state["history"][0]["outcome"] == OUTCOME_WOKEN

    def test_history_is_newest_first(self):
        runstate = {}
        for target in ("@backup", "@commons", "@daemon"):
            record_rotation(runstate, "k", target, OUTCOME_WOKEN)
        history = get_rotation_state(runstate, "k")["history"]
        assert [h["target"] for h in history] == ["@daemon", "@commons", "@backup"]

    def test_history_is_capped(self):
        runstate = {}
        for index in range(HISTORY_LIMIT + 5):
            record_rotation(runstate, "k", f"@b{index}", OUTCOME_WOKEN)
        assert len(get_rotation_state(runstate, "k")["history"]) == HISTORY_LIMIT

    def test_state_lives_outside_the_jobs_map(self):
        runstate = {"jobs": {}}
        record_rotation(runstate, "k", "@backup", OUTCOME_MISSED)
        assert runstate["jobs"] == {}
        assert ROTATION_STATE_KEY in runstate

    def test_unknown_key_returns_empty_state(self):
        assert get_rotation_state({}, "nope") == {}


# ── render_prompt ─────────────────────────────────────


class TestRenderPrompt:
    def test_branch_is_substituted(self):
        assert render_prompt("STEWARD NIGHT for {branch}.", "@flow") == "STEWARD NIGHT for @flow."

    def test_empty_prompt_falls_back_to_builtin(self):
        rendered = render_prompt("", "@flow")
        assert "@flow" in rendered
        assert rendered == STEWARD_PROMPT_TEMPLATE.replace("{branch}", "@flow")

    def test_prompt_without_placeholder_passes_through(self):
        assert render_prompt("Just do the audit.", "@flow") == "Just do the audit."


# ── fire_rotation ─────────────────────────────────────


class TestFireRotation:
    def _fire(self, roster, runstate, wake_result, job=None, lane=True):
        with (
            patch(f"{MODULE}.build_roster", return_value=roster),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._scheduled_lane_available", return_value=lane),
            patch(f"{MODULE}._wake_steward", return_value=wake_result) as mock_wake,
        ):
            ok, detail = rotation_module.fire_rotation(job or rotation_job(), runstate)
        return ok, detail, mock_wake

    def test_woken_target_advances_pointer(self, roster):
        runstate = {}
        ok, _detail, mock_wake = self._fire(roster, runstate, (True, "session started", False))
        assert ok is True
        mock_wake.assert_called_once()
        state = get_rotation_state(runstate, "@daemon/fleet-steward")
        assert state["last_target"] == "@backup"
        assert state["history"][0]["outcome"] == OUTCOME_WOKEN

    def test_second_night_serves_the_next_citizen(self, roster):
        runstate = {}
        self._fire(roster, runstate, (True, "ok", False))
        self._fire(roster, runstate, (True, "ok", False))
        state = get_rotation_state(runstate, "@daemon/fleet-steward")
        assert state["last_target"] == "@commons"
        assert [h["target"] for h in state["history"]] == ["@commons", "@backup"]

    def test_busy_target_is_a_miss_and_pointer_still_advances(self, roster):
        runstate = {}
        ok, detail, _mock = self._fire(roster, runstate, (False, "branch is already awake", False))
        # The rotation did its job — the miss is recorded, not a job failure.
        assert ok is True
        assert "@backup" in detail
        state = get_rotation_state(runstate, "@daemon/fleet-steward")
        assert state["last_target"] == "@backup"
        assert state["history"][0]["outcome"] == OUTCOME_MISSED

    def test_miss_does_not_stall_the_cycle(self, roster):
        runstate = {}
        self._fire(roster, runstate, (False, "already awake", False))
        ok, _detail, mock_wake = self._fire(roster, runstate, (True, "ok", False))
        assert ok is True
        assert mock_wake.call_args[0][0]["email"] == "@commons"

    def test_wake_exception_is_recorded_as_failure(self, roster):
        runstate = {}
        ok, _detail, _mock = self._fire(roster, runstate, (False, "boom", True))
        assert ok is False
        assert get_rotation_state(runstate, "@daemon/fleet-steward")["history"][0]["outcome"] == OUTCOME_FAILED

    def test_empty_roster_fails_the_job(self):
        runstate = {}
        ok, detail, mock_wake = self._fire([], runstate, (True, "", False))
        assert ok is False
        assert "empty" in detail
        mock_wake.assert_not_called()

    def test_manager_skipped_by_name_when_lane_missing(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            with_managers = build_roster(include_managers=True)

        runstate = {ROTATION_STATE_KEY: {"@daemon/fleet-steward": {"last_target": "@commons"}}}
        job = rotation_job(config={"include_managers": True})
        ok, detail, mock_wake = self._fire(with_managers, runstate, (True, "", False), job=job, lane=False)

        assert ok is True
        assert "@baud" in detail
        mock_wake.assert_not_called()
        state = get_rotation_state(runstate, "@daemon/fleet-steward")
        assert state["last_target"] == "@baud"
        assert state["history"][0]["outcome"] == OUTCOME_SKIPPED

    def test_manager_woken_when_lane_available(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            with_managers = build_roster(include_managers=True)

        runstate = {ROTATION_STATE_KEY: {"@daemon/fleet-steward": {"last_target": "@commons"}}}
        job = rotation_job(config={"include_managers": True})
        ok, _detail, mock_wake = self._fire(with_managers, runstate, (True, "ok", False), job=job, lane=True)

        assert ok is True
        mock_wake.assert_called_once()
        assert get_rotation_state(runstate, "@daemon/fleet-steward")["history"][0]["outcome"] == OUTCOME_WOKEN

    def test_knob_defaults_to_managers_excluded(self, fleet, classes):
        runstate = {}
        job = rotation_job()
        job.pop("config")
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._wake_steward", return_value=(True, "ok", False)) as mock_wake,
        ):
            rotation_module.fire_rotation(job, runstate)
        assert mock_wake.call_args[0][0]["email"] == "@backup"


# ── the manager lane contract ─────────────────────────


class TestManagerLane:
    def test_manager_target_asks_for_the_scheduled_lane(self):
        target = {"email": "@baud", "citizen_class": "manager"}
        fake = FakeStatus("woken")
        with patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", return_value=(fake, True)) as mock_wake:
            ok, _detail, errored = rotation_module._wake_steward(target, "prompt", "sonnet", True)
        assert ok is True
        assert errored is False
        assert mock_wake.call_args.kwargs["scheduled"] is True

    def test_non_manager_target_uses_the_ordinary_path(self):
        target = {"email": "@commons", "citizen_class": "aipass_framework"}
        fake = FakeStatus("woken")
        with patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", return_value=(fake, True)) as mock_wake:
            rotation_module._wake_steward(target, "prompt", "sonnet", True)
        assert "scheduled" not in mock_wake.call_args.kwargs

    def test_wake_exception_is_reported_not_raised(self):
        target = {"email": "@commons", "citizen_class": "aipass_framework"}
        with patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", side_effect=RuntimeError("boom")):
            ok, detail, errored = rotation_module._wake_steward(target, "prompt", "sonnet", True)
        assert ok is False
        assert errored is True
        assert "boom" in detail

    def test_lane_probe_reads_the_live_signature(self):
        assert rotation_module._scheduled_lane_available() in (True, False)


# ── CLI surface ───────────────────────────────────────


class TestRotationCommand:
    def test_handles_rotation(self):
        assert "rotation" in rotation_module.HANDLED_COMMANDS

    def test_rejects_unknown(self):
        assert rotation_module.handle_command("unknown", []) is False

    def test_help_flag(self):
        assert rotation_module.handle_command("rotation", ["--help"]) is True

    def test_status_reports_next_target(self, roster):
        runstate = {ROTATION_STATE_KEY: {"@daemon/fleet-steward": {"last_target": "@backup", "history": []}}}
        with (
            patch(f"{MODULE}.build_roster", return_value=roster),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._scheduled_lane_available", return_value=False),
        ):
            status = rotation_module._build_status(rotation_job(), runstate)
        assert status["next_target"] == "@commons"
        assert status["last_target"] == "@backup"
        assert status["roster_size"] == 2
        assert status["manager_lane_available"] is False

    def test_status_without_a_rotation_job(self, roster):
        with (
            patch(f"{MODULE}.build_roster", return_value=roster),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._scheduled_lane_available", return_value=True),
        ):
            status = rotation_module._build_status(None, {})
        assert status["job_id"] is None
        assert status["enabled"] is False
        assert status["next_target"] == "@backup"

    def test_json_output_is_parseable(self, roster, capsys):
        import json

        with (
            patch(f"{MODULE}.find_rotation_jobs", return_value=[rotation_job()]),
            patch(f"{MODULE}.load_runstate", return_value={}),
            patch(f"{MODULE}.build_roster", return_value=roster),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._scheduled_lane_available", return_value=True),
        ):
            assert rotation_module.handle_command("rotation", ["--json"]) is True
        payload = json.loads(capsys.readouterr().out)
        assert payload["job_id"] == "fleet-steward"
        assert payload["next_target"] == "@backup"

    def test_blocklist_filter_drops_blocked_branches(self, roster):
        with patch("aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked", side_effect=lambda e: e == "@backup"):
            kept = rotation_module._apply_wake_blocklist(roster)
        assert [c["email"] for c in kept] == ["@commons"]

    def test_find_rotation_jobs_filters_by_type(self):
        jobs = [rotation_job(), {"id": "x", "owner": "@a", "schedule": {"type": "daily"}, "prompt": "p"}]
        with patch(f"{MODULE}.discover_jobs", return_value=jobs):
            found = rotation_module.find_rotation_jobs()
        assert [j["id"] for j in found] == ["fleet-steward"]
