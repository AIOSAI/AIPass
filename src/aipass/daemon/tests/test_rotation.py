# =================== AIPass ====================
# Name: test_rotation.py
# Description: Tests for the steward rotation handler and module
# Version: 1.2.0
# Created: 2026-08-12
# Modified: 2026-09-10
# =============================================

"""Tests for the nightly rounds (DPLAN-0287, switched on by DPLAN-0337 R2)."""

import inspect
import json
from datetime import date, datetime, time, timedelta
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
    ROUNDS_PROMPT_TEMPLATE,
    ROSTER_SCOPE,
    build_roster,
    get_rotation_state,
    next_target,
    record_rotation,
    render_prompt,
)
from aipass.daemon.apps.handlers.schedule import runstate as runstate_mod
from aipass.daemon.apps.handlers.schedule.discovery import active_citizens, framework_root
from aipass.daemon.apps.modules import rotation as rotation_module
from aipass.daemon.apps.modules import run as run_module

HANDLER = "aipass.daemon.apps.handlers.schedule.rotation"
MODULE = "aipass.daemon.apps.modules.rotation"
RUN = "aipass.daemon.apps.modules.run"
WAKE_SEAM = "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch"
SCHEDULE_FILE = Path(__file__).resolve().parents[1] / ".daemon" / "schedule.json"


# ── Fixtures ──────────────────────────────────────────


FRAMEWORK = framework_root()
INSTALL = FRAMEWORK.parents[1]
OUTSIDE = INSTALL.parent / "EXTERNAL-ROOT"


def citizen(email: str, source: str = "aipass") -> dict:
    """Build a citizen record as discovery.active_citizens() returns them.

    The path follows the tier the source names. The scope rule reads the path,
    so a fixture whose label and path disagree — every fixture here lived under
    src/aipass until 2026-09-10, "projects/baud" included — would pin nothing.
    """
    name = email.lstrip("@")
    if source == "aipass":
        path = FRAMEWORK / name
    elif source.startswith("projects/"):
        path = INSTALL / source
    else:
        path = OUTSIDE / source.split("/", 1)[-1] / name
    return {"name": name.upper(), "email": email, "dir_name": name, "path": path, "source": source}


@pytest.fixture
def fleet():
    """Two framework citizens, a framework manager, devpulse, and a project manager.

    @bastion carries the manager-knob tests: since the scope ruling a projects/*
    manager like @baud is never served, knob or no knob.
    """
    return [
        citizen("@backup"),
        citizen("@devpulse"),
        citizen("@commons"),
        citizen("@bastion"),
        citizen("@baud", source="projects/baud"),
    ]


@pytest.fixture
def classes():
    """citizen_class per email for the `fleet` fixture."""
    return {
        "@backup": "aipass_framework",
        "@devpulse": "manager",
        "@commons": "aipass_framework",
        "@bastion": "manager",
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
        "id": "rounds",
        "enabled": True,
        "schedule": {"type": "rotation", "time": "05:00"},
        "wake": {"fresh": True, "model": "opus"},
        "config": {"include_managers": False},
        "prompt": "ROUNDS for {branch}. Do the work, then STOP.",
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
        assert [c["email"] for c in included] == ["@backup", "@bastion", "@commons"]
        assert "@baud" not in [c["email"] for c in included], "the knob admits managers, never a projects/* one"

    def test_roster_is_alphabetical_whatever_the_registry_order(self):
        """Registry order was the walk until 2026-09-10; alphabetical is the walk now.

        The fleet arrives reverse-sorted, so a roster that kept registry order reads
        red here. The other fixtures happen to be sorted already and cannot tell
        the two apart.
        """
        fleet = [citizen("@seedgo"), citizen("@flow"), citizen("@drone"), citizen("@ai_mail")]
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", return_value="aipass_framework"),
        ):
            roster = build_roster()
        assert [c["email"] for c in roster] == ["@ai_mail", "@drone", "@flow", "@seedgo"]
        assert roster[1]["path"] == FRAMEWORK / "drone", "sorting must carry each record whole"

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
        record_rotation(runstate, "@daemon/rounds", "@backup", OUTCOME_WOKEN)
        state = get_rotation_state(runstate, "@daemon/rounds")
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
        assert render_prompt("ROUNDS for {branch}.", "@flow") == "ROUNDS for @flow."

    def test_empty_prompt_falls_back_to_builtin(self):
        rendered = render_prompt("", "@flow")
        assert "@flow" in rendered
        assert rendered == ROUNDS_PROMPT_TEMPLATE.replace("{branch}", "@flow")

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
        state = get_rotation_state(runstate, "@daemon/rounds")
        assert state["last_target"] == "@backup"
        assert state["history"][0]["outcome"] == OUTCOME_WOKEN

    def test_second_night_serves_the_next_citizen(self, roster):
        runstate = {}
        self._fire(roster, runstate, (True, "ok", False))
        self._fire(roster, runstate, (True, "ok", False))
        state = get_rotation_state(runstate, "@daemon/rounds")
        assert state["last_target"] == "@commons"
        assert [h["target"] for h in state["history"]] == ["@commons", "@backup"]

    def test_busy_target_is_a_miss_and_pointer_still_advances(self, roster):
        runstate = {}
        ok, detail, _mock = self._fire(roster, runstate, (False, "branch is already awake", False))
        # The rotation did its job — the miss is recorded, not a job failure.
        assert ok is True
        assert "@backup" in detail
        state = get_rotation_state(runstate, "@daemon/rounds")
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
        assert get_rotation_state(runstate, "@daemon/rounds")["history"][0]["outcome"] == OUTCOME_FAILED

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

        # Alphabetical: @backup, @bastion, @commons - the manager follows @backup.
        runstate = {ROTATION_STATE_KEY: {"@daemon/rounds": {"last_target": "@backup"}}}
        job = rotation_job(config={"include_managers": True})
        ok, detail, mock_wake = self._fire(with_managers, runstate, (True, "", False), job=job, lane=False)

        assert ok is True
        assert "@bastion" in detail
        mock_wake.assert_not_called()
        state = get_rotation_state(runstate, "@daemon/rounds")
        assert state["last_target"] == "@bastion"
        assert state["history"][0]["outcome"] == OUTCOME_SKIPPED

    def test_manager_woken_when_lane_available(self, fleet, classes):
        with (
            patch(f"{HANDLER}.active_citizens", return_value=fleet),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: classes[f"@{p.name}"]),
        ):
            with_managers = build_roster(include_managers=True)

        runstate = {ROTATION_STATE_KEY: {"@daemon/rounds": {"last_target": "@backup"}}}
        job = rotation_job(config={"include_managers": True})
        ok, _detail, mock_wake = self._fire(with_managers, runstate, (True, "ok", False), job=job, lane=True)

        assert ok is True
        mock_wake.assert_called_once()
        assert get_rotation_state(runstate, "@daemon/rounds")["history"][0]["outcome"] == OUTCOME_WOKEN

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
        assert mock_wake.call_args.kwargs["wake_back"] is False, "the manager lane declines the wake-back too"

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
        """The probe answers True because ai_mail's wake_branch really takes `scheduled`.

        Was `in (True, False)` — true of every bool, so it survived any
        implementation that returns one. The probe exists to notice the day
        ai_mail's lane appears or disappears, so it pins the live answer and the
        parameter that produces it. If wake_branch loses `scheduled`, rotation
        starts skipping every manager steward by name (rotation.py line 203) and
        both halves of this go red together.
        """
        from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

        assert "scheduled" in inspect.signature(wake_branch).parameters
        assert rotation_module._scheduled_lane_available() is True

    def test_wake_back_is_a_live_keyword_of_wake_branch(self):
        """Our wake_back=False is only safe while ai_mail's wake_branch takes it.

        Dropped or renamed there, every rounds night becomes a TypeError caught in
        _wake_steward and recorded as a failed turn at 05:00. This pin makes the
        suite say so first. Keyword-only with a True default is FPLAN-0541's shape.
        """
        from aipass.ai_mail.apps.handlers.dispatch.wake import wake_branch

        param = inspect.signature(wake_branch).parameters["wake_back"]
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default is True


# ── CLI surface ───────────────────────────────────────


class TestRotationCommand:
    def test_handles_rotation(self):
        assert "rotation" in rotation_module.HANDLED_COMMANDS

    def test_rejects_unknown(self):
        assert rotation_module.handle_command("unknown", []) is False

    def test_help_flag(self):
        assert rotation_module.handle_command("rotation", ["--help"]) is True

    def test_status_reports_next_target(self, roster):
        runstate = {ROTATION_STATE_KEY: {"@daemon/rounds": {"last_target": "@backup", "history": []}}}
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
        assert payload["job_id"] == "rounds"
        assert payload["next_target"] == "@backup"

    def test_blocklist_filter_drops_blocked_branches(self, roster):
        with patch("aipass.ai_mail.apps.handlers.dispatch.wake.is_wake_blocked", side_effect=lambda e: e == "@backup"):
            kept = rotation_module._apply_wake_blocklist(roster)
        assert [c["email"] for c in kept] == ["@commons"]

    def test_find_rotation_jobs_filters_by_type(self):
        jobs = [rotation_job(), {"id": "x", "owner": "@a", "schedule": {"type": "daily"}, "prompt": "p"}]
        with patch(f"{MODULE}.discover_jobs", return_value=jobs):
            found = rotation_module.find_rotation_jobs()
        assert [j["id"] for j in found] == ["rounds"]


# ── the shipped rounds job (DPLAN-0337 R2) ────────────


def shipped_rounds_job() -> dict:
    """The rounds stanza as daemon ships it — read, never written — owner stamped as discovery does."""
    data = json.loads(SCHEDULE_FILE.read_text(encoding="utf-8"))
    rounds = [j for j in data["jobs"] if j.get("schedule", {}).get("type") == "rotation"]
    assert len(rounds) == 1, "daemon ships exactly one rotation job"
    return {**rounds[0], "owner": data["branch"]}


BUDGET_RULES = (
    "ROUNDS for {branch}",
    "inbox to zero",
    "never dispatch or wake another citizen",
    "at most 2 sub-agents, sonnet or lower",
    "never edit another branch",
    "no fleet-wide investigations",
    "write it down for devpulse and stop",
    "drone @ai_mail email @devpulse",
    "health verdict, what you did, what you noticed, what you need",
)


class TestShippedRoundsJob:
    """Patrick's ruling of 2026-09-10, read off the same file the tick reads."""

    def test_the_job_is_rounds_and_it_is_on(self):
        job = shipped_rounds_job()
        assert job["id"] == "rounds"
        assert job["enabled"] is True
        assert job["schedule"] == {"type": "rotation", "time": "05:00"}

    def test_opus_fresh_and_no_managers(self):
        job = shipped_rounds_job()
        assert job["wake"] == {"fresh": True, "model": "opus"}
        assert job["config"] == {"include_managers": False}

    def test_the_job_passes_discovery_validation(self):
        from aipass.daemon.apps.handlers.schedule.discovery import _validate_job

        assert _validate_job(shipped_rounds_job(), SCHEDULE_FILE) is True

    @pytest.mark.parametrize("source", ["shipped stanza", "fallback template"])
    def test_the_prompt_carries_the_budget(self, source):
        prompt = shipped_rounds_job()["prompt"] if source == "shipped stanza" else ROUNDS_PROMPT_TEMPLATE
        missing = [rule for rule in BUDGET_RULES if rule not in prompt]
        assert missing == [], f"{source} lost: {missing}"

    @pytest.mark.parametrize("source", ["shipped stanza", "fallback template"])
    def test_the_prompt_asks_for_nothing_that_cannot_happen(self, source):
        """A rounds wake is a session prompt, not a mail: there is no dispatch to reply to.

        Same seam as the false wake-backs of 2026-09-10 08:50-08:57, when @daemon was
        told five times to read a reply that a nudge never owes. The APLAN step is
        gone by ruling — the @devpulse mail is the night's one artefact.
        """
        prompt = (shipped_rounds_job()["prompt"] if source == "shipped stanza" else ROUNDS_PROMPT_TEMPLATE).lower()
        assert "reply to this dispatch" not in prompt
        assert "aplan" not in prompt


class TestRoundsNight:
    """One night end to end through the real tick, nobody woken.

    The shipped stanza, a runstate copy that has never seen the job but still
    carries the deleted inbox-sweep row, the clock moved to 05:01, and the wake
    caught at ai_mail's wake_branch seam — so the kwargs pinned are the ones a
    real 05:00 fire hands ai_mail. Nights are dated from tomorrow: last_run is
    stamped by the real clock, and a fixed date would go red once the wall
    clock passed it.
    """

    # Registry order on purpose, and two outsiders that sort AHEAD of @ai_mail:
    # a projects/* resident and an external-root citizen, both declaring the
    # framework class, so only the scope rule keeps them off the first night.
    FLEET = [
        citizen("@seedgo"),
        citizen("@devpulse"),
        citizen("@aardvark", source="projects/aardvark"),
        citizen("@ai_mail"),
        citizen("@abacus", source="external/DEMO"),
        citizen("@baud", source="projects/baud"),
        citizen("@backup"),
    ]
    CLASSES = {
        "@seedgo": "aipass_framework",
        "@devpulse": "manager",
        "@aardvark": "aipass_framework",
        "@ai_mail": "aipass_framework",
        "@abacus": "aipass_framework",
        "@baud": "manager",
        "@backup": "aipass_framework",
    }

    @staticmethod
    def night(offset_days: int) -> datetime:
        return datetime.combine(date.today() + timedelta(days=offset_days), time(5, 1))

    def _tick(self, runstate: dict, at: datetime):
        real_is_due = runstate_mod.is_job_due
        with (
            patch(f"{RUN}.discover_jobs", return_value=[shipped_rounds_job()]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
            patch(f"{RUN}.is_job_due", side_effect=lambda j, rs: real_is_due(j, rs, now=at)),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{HANDLER}.active_citizens", return_value=self.FLEET),
            patch(f"{HANDLER}.citizen_class_for", side_effect=lambda p: self.CLASSES[f"@{p.name}"]),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(WAKE_SEAM, return_value=(FakeStatus("woken"), True)) as mock_wake,
        ):
            results = run_module.run_tick()
        return results, mock_wake, mock_save

    def test_first_night_wakes_the_first_citizen_alphabetically(self):
        runstate = {"jobs": {"@daemon/inbox-sweep": {"last_run": "2026-09-10T08:47:36"}}}
        results, mock_wake, mock_save = self._tick(runstate, self.night(1))

        assert results["fired"] == 1
        mock_wake.assert_called_once()
        assert mock_wake.call_args.args[0] == "@ai_mail", "@aardvark/@abacus sort first; registry order picks @seedgo"
        assert mock_save.called

    def test_the_wake_carries_patricks_ruling(self):
        _results, mock_wake, _save = self._tick({}, self.night(1))
        kwargs = mock_wake.call_args.kwargs

        assert kwargs["model"] == "opus"
        assert kwargs["fresh"] is True
        assert kwargs["auto"] is True
        assert kwargs["sender"] == "@daemon"
        assert "scheduled" not in kwargs, "a framework citizen takes the ordinary lane"
        assert "ROUNDS for @ai_mail." in kwargs["custom_message"]
        assert "{branch}" not in kwargs["custom_message"]
        assert kwargs["wake_back"] is False, "the daemon is never woken back after a rounds night"

    def test_the_pointer_advances_and_the_next_night_serves_the_next_citizen(self):
        runstate = {}
        self._tick(runstate, self.night(1))
        state = get_rotation_state(runstate, "@daemon/rounds")
        assert state["last_target"] == "@ai_mail"
        assert state["history"][0]["outcome"] == OUTCOME_WOKEN

        _results, mock_wake, _save = self._tick(runstate, self.night(2))
        assert mock_wake.call_args.args[0] == "@backup"
        assert get_rotation_state(runstate, "@daemon/rounds")["last_target"] == "@backup"

    def test_the_deleted_sweep_row_is_pruned_on_the_same_tick(self):
        runstate = {"jobs": {"@daemon/inbox-sweep": {"last_run": "2026-09-10T08:47:36"}}}
        self._tick(runstate, self.night(1))
        assert "@daemon/inbox-sweep" not in runstate["jobs"]

    def test_nothing_fires_outside_the_window(self):
        """21:15 tonight — the minute this was switched on — must wake nobody."""
        at = datetime.combine(date.today() + timedelta(days=1), time(21, 15))
        results, mock_wake, _save = self._tick({}, at)
        assert results["fired"] == 0
        mock_wake.assert_not_called()


# ── the scope ruling (Patrick, 2026-09-10 21:47) ──────


class TestRoundsScope:
    """The rounds serve src/aipass/* only — marked very important.

    Driven through discovery's real active_citizens() on a temp install, with
    @memory's fleet stubbed at its seam as the sweep's scope pins do: one
    framework branch, one projects/* resident, one citizen under an external
    root. All three declare the same trusted class, so only the path can tell
    them apart — which is the rule.
    """

    FLEET = "aipass.daemon.apps.handlers.schedule.discovery.fleet"

    @pytest.fixture
    def install(self, tmp_path):
        repo = tmp_path / "install"
        framework = repo / "src" / "aipass" / "flow"
        resident = repo / "projects" / "earmark"
        external = tmp_path / "VERA-STUDIO" / "research"
        for branch in (framework, resident, external):
            branch.mkdir(parents=True)
        rows = [
            {"name": "flow", "path": framework, "registry": "AIPASS_REGISTRY.json", "email": "@flow"},
            {"name": "earmark", "path": resident, "registry": "EARMARK_REGISTRY.json", "email": "@earmark"},
            {"name": "research", "path": external, "registry": "VERA-STUDIO_REGISTRY.json", "email": "@research"},
        ]
        return repo, rows

    def _roster(self, repo, rows, **kwargs):
        with (
            patch(f"{self.FLEET}.fleet_branches", return_value=rows),
            patch(f"{HANDLER}.citizen_class_for", return_value="aipass_framework"),
        ):
            return build_roster(repo_root=repo, **kwargs)

    def test_discovery_sees_all_three_tiers(self, install):
        """Without this, the next pin could pass because the stub never reached discovery."""
        repo, rows = install
        with patch(f"{self.FLEET}.fleet_branches", return_value=rows):
            seen = active_citizens(repo)
        assert [(c["email"], c["source"]) for c in seen] == [
            ("@flow", "aipass"),
            ("@earmark", "projects/earmark"),
            ("@research", "external/VERA-STUDIO"),
        ]

    def test_only_the_framework_branch_is_served(self, install):
        repo, rows = install
        assert [c["email"] for c in self._roster(repo, rows)] == ["@flow"]

    def test_the_manager_knob_cannot_widen_the_scope(self, install):
        repo, rows = install
        assert [c["email"] for c in self._roster(repo, rows, include_managers=True)] == ["@flow"]

    def test_status_names_the_scope(self, roster, capsys):
        with (
            patch(f"{MODULE}.find_rotation_jobs", return_value=[rotation_job()]),
            patch(f"{MODULE}.load_runstate", return_value={}),
            patch(f"{MODULE}.build_roster", return_value=roster),
            patch(f"{MODULE}._apply_wake_blocklist", side_effect=lambda r: r),
            patch(f"{MODULE}._scheduled_lane_available", return_value=True),
        ):
            rotation_module.handle_command("rotation", [])
            status = rotation_module._build_status(rotation_job(), {})
        assert f"Scope:    {ROSTER_SCOPE}" in capsys.readouterr().out
        assert status["scope"] == ROSTER_SCOPE
        assert "projects and externals excluded by ruling" in ROSTER_SCOPE
