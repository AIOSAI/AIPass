# =================== AIPass ====================
# Name: test_run_module.py
# Description: Tests for the drone @daemon run module
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-06-25
# =============================================

"""Tests for the drone @daemon run module (decentralized scheduler tick)."""

from unittest.mock import patch

from aipass.daemon.apps.handlers.schedule import runstate as runstate_mod
from aipass.daemon.apps.modules.run import (
    run_tick,
    handle_command,
    OUTCOME_FAILED,
    OUTCOME_FIRED,
    _fire_job,
    HANDLED_COMMANDS,
)


class TestHandleCommand:
    def test_handles_run(self):
        assert "run" in HANDLED_COMMANDS

    def test_rejects_unknown(self):
        result = handle_command("unknown", [])
        assert result is False
        # The return TYPE, pinned where the command actually runs. It used to
        # be asserted in tests/test_contracts.py, one of the DPLAN-0059 stamp
        # files — which had stopped RUNNING (it skipped module-wide on a
        # JSON_DIR the shim does not have) while still reading as covered to a
        # text scan. Archived with the sweep; the claim moves here, to a test
        # that executes. A truthy int would satisfy `is False` nowhere, but it
        # would satisfy `== False`, and callers branch on this.
        assert isinstance(result, bool), f"handle_command answered {type(result).__name__}, not bool"

    def test_help_flag(self, capsys):
        result = handle_command("run", ["--help"])
        out = capsys.readouterr().out
        assert result is True
        assert isinstance(result, bool), f"handle_command answered {type(result).__name__}, not bool"
        # The capture was requested and never read: a True receipt says the call
        # returned, not that anything was printed. run's help is its own — the
        # heading names this verb, so a router that answered with some other
        # module's help would fail here instead of passing on the receipt.
        assert "run — Decentralized Scheduler Tick" in out, f"run --help printed: {out[:200]!r}"
        assert "USAGE:" in out, "run --help must print a USAGE: block"


class TestRunTick:
    @patch("aipass.daemon.apps.modules.run.discover_jobs", return_value=[])
    def test_no_jobs(self, mock_discover):
        results = run_tick(dry_run=True)
        assert results["discovered"] == 0
        assert results["fired"] == 0

    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_dry_run_does_not_fire(self, mock_rs, mock_discover):
        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": {"type": "interval", "interval_minutes": 1},
                "wake": {"fresh": True},
                "prompt": "test prompt",
            }
        ]
        results = run_tick(dry_run=True)
        assert results["due"] == 1
        assert results["fired"] == 0

    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_disabled_jobs_skipped(self, mock_rs, mock_discover):
        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "off",
                "enabled": False,
                "schedule": {"type": "interval", "interval_minutes": 1},
                "wake": {},
                "prompt": "disabled",
            }
        ]
        results = run_tick(dry_run=True)
        assert results["enabled"] == 0
        assert results["due"] == 0

    @patch("aipass.daemon.apps.modules.run.save_runstate")
    @patch("aipass.daemon.apps.modules.run._fire_job", return_value=(OUTCOME_FIRED, ""))
    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_fires_due_job(self, mock_rs, mock_discover, mock_fire, mock_save):
        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": {"type": "interval", "interval_minutes": 1},
                "wake": {"fresh": True},
                "prompt": "test",
            }
        ]
        results = run_tick()
        assert results["fired"] == 1
        assert results["failed"] == 0
        mock_fire.assert_called_once()
        mock_save.assert_called()

    @patch("aipass.daemon.apps.modules.run.save_runstate")
    @patch("aipass.daemon.apps.modules.run._fire_job", return_value=(OUTCOME_FAILED, "wake failed"))
    @patch("aipass.daemon.apps.modules.run.discover_jobs")
    @patch("aipass.daemon.apps.modules.run.load_runstate", return_value={"jobs": {}})
    def test_failed_fire_counted(self, mock_rs, mock_discover, mock_fire, mock_save):
        mock_discover.return_value = [
            {
                "owner": "@commons",
                "id": "test",
                "enabled": True,
                "schedule": {"type": "interval", "interval_minutes": 1},
                "wake": {},
                "prompt": "test",
            }
        ]
        results = run_tick()
        assert results["failed"] == 1
        assert results["fired"] == 0


# ── orphan prune persistence (DPLAN-0287 piece 3) ────

RUN = "aipass.daemon.apps.modules.run"


def live_job(owner: str = "@commons", job_id: str = "live") -> dict:
    """A discovered job that is never due, so no tick ever fires."""
    return {
        "owner": owner,
        "id": job_id,
        "enabled": True,
        "schedule": {"type": "daily", "time": "04:00"},
        "wake": {},
        "prompt": "x",
    }


class TestPrunePersistence:
    def _quiet_tick(self, runstate, dry_run=False):
        """Run a tick where nothing is due, returning the save mock.

        ``missed_window`` is pinned False because these tests are about PRUNE
        persistence and nothing else. live_job() is a daily 04:00 job, so from
        04:16 until midnight its window is genuinely closed-and-unrun and the
        MISSED pass writes its once-per-day marker - a real write, covered by
        TestMissedWindowLine, that would otherwise make the assertions here
        pass or fail on the wall clock the suite happened to run at.
        """
        with (
            patch(f"{RUN}.discover_jobs", return_value=[live_job()]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.is_job_due", return_value=False),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            run_tick(dry_run=dry_run)
        return mock_save

    def test_prune_is_saved_even_when_nothing_fires(self):
        runstate = {"jobs": {"@ghost/retired": {"last_run": "2026-06-25T08:11:05"}, "@commons/live": {}}}
        mock_save = self._quiet_tick(runstate)
        # The bug: pruning mutated memory every tick but only ever saved inside
        # the fire loop, so a quiet tick threw the prune away.
        #
        # Was assert_called_once. Since DPLAN-0332 every tick also stamps
        # last_tick, so a quiet tick writes twice and the count no longer
        # identifies the prune. The claim never was "exactly one write" — it is
        # "the prune reaches disk", so that is what this now asserts.
        assert mock_save.called, "a quiet tick must still persist its prune"
        assert all("@ghost/retired" not in call[0][0]["jobs"] for call in mock_save.call_args_list)
        assert "@ghost/retired" not in runstate["jobs"]

    def test_a_clean_quiet_tick_writes_only_its_tick_stamp(self):
        """DPLAN-0332 superseded the old claim, and this is the honest remainder.

        Was test_clean_runstate_is_not_rewritten / assert_not_called: a tick
        with nothing to prune and nothing to fire wrote nothing at all. It now
        writes exactly once, because recording last_tick IS the tick's product —
        gap detection reads it, and a tick that saved nothing would be
        indistinguishable from a tick that never happened.

        What the original pin was really protecting — no gratuitous rewrite for
        work that was not done — survives as the count: one write, and its only
        content is the stamp.
        """
        runstate = {"jobs": {"@commons/live": {}}}
        mock_save = self._quiet_tick(runstate)
        mock_save.assert_called_once()
        saved = mock_save.call_args[0][0]
        assert saved["last_tick"], "the one write must be the tick stamp"
        assert saved["jobs"] == {"@commons/live": {}}, "nothing else may change on a clean quiet tick"

    def test_dry_run_never_writes(self):
        runstate = {"jobs": {"@ghost/retired": {}, "@commons/live": {}}}
        mock_save = self._quiet_tick(runstate, dry_run=True)
        mock_save.assert_not_called()

    def test_discovery_failure_does_not_wipe_runstate(self):
        """Discovery returning nothing must never be read as "the fleet is empty".

        The tick stamp is still written — the scheduler DID tick, and swallowing
        that would make the next tick report a gap that never happened and queue
        catch-ups for windows nobody missed. What must survive is the jobs dict:
        an empty discovery is a discovery failure, not a fleet that retired.
        """
        runstate = {"jobs": {"@commons/live": {}}}
        with (
            patch(f"{RUN}.discover_jobs", return_value=[]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            run_tick()
        assert runstate["jobs"] == {"@commons/live": {}}
        for call in mock_save.call_args_list:
            assert call[0][0]["jobs"] == {"@commons/live": {}}, "a save must never carry a wiped roster"


# ── rotation delegation (DPLAN-0287 piece 1) ─────────


class TestRotationDelegation:
    def test_rotation_job_goes_to_the_rotation_module(self):
        job = {
            "owner": "@daemon",
            "id": "rounds",
            "enabled": True,
            "schedule": {"type": "rotation", "time": "05:00"},
            "wake": {},
            "prompt": "ROUNDS for {branch}.",
        }
        runstate = {"jobs": {}}
        # fire_rotation keeps its own (ok, detail) answer; _fire_job maps it onto
        # the three-state outcome the tick loop now reads.
        with patch(f"{RUN}.fire_rotation", return_value=(True, "woke @backup")) as mock_rotation:
            outcome, detail = _fire_job(job, runstate)
        assert outcome == OUTCOME_FIRED
        assert detail == "woke @backup"
        mock_rotation.assert_called_once_with(job, runstate, header="")

    def test_ordinary_job_never_touches_the_rotation(self):
        with (
            patch(f"{RUN}.fire_rotation") as mock_rotation,
            patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", side_effect=RuntimeError("no wake")),
        ):
            outcome, _detail = _fire_job(live_job(), {"jobs": {}})
        assert outcome == OUTCOME_FAILED
        mock_rotation.assert_not_called()


# ── closed windows and interval slots (FPLAN-0492 ruling 6) ──


def flat(text: str) -> str:
    """Collapse whitespace so Rich's line wrapping cannot break a substring check.

    Measured: at the suite's terminal width the tick summary arrives as
    "0 \nseeded", which fails `"0 seeded" in out` for a reason that has nothing
    to do with the behaviour under test.
    """
    return " ".join(text.split())


def interval_job_with_slot(slot="2026-09-06T03:00:00", minutes=10080):
    """@seedgo's weekly cycle, in the shape that caused the lesson."""
    schedule = {"type": "interval", "interval_minutes": minutes}
    if slot is not None:
        schedule["slot"] = slot
    return {
        "owner": "@seedgo",
        "id": "shadow-cycle-weekly",
        "enabled": True,
        "schedule": schedule,
        "wake": {},
        "prompt": "x",
    }


class TestMissedWindowLine:
    def _tick(self, runstate, dry_run=False, catch_up=None):
        job = live_job()
        if catch_up is not None:
            job["schedule"]["catch_up"] = catch_up
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.missed_window", return_value=True),
            patch(f"{RUN}.is_job_due", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            results = run_tick(dry_run=dry_run)
        return results, mock_save

    def test_a_closed_window_is_reported_once(self, capsys):
        runstate = {"jobs": {}}
        results, _save = self._tick(runstate)
        out = capsys.readouterr().out
        assert results["missed"] == 1
        assert "MISSED: @commons/live" in flat(out)
        assert "04:00 +/-15m" in flat(out)

    def test_the_same_miss_is_not_repeated_on_the_next_tick(self):
        # The scheduler ticks about every two minutes; an unguarded line would
        # repeat ~500 times between a closed window and midnight.
        runstate = {"jobs": {}}
        first, _ = self._tick(runstate)
        second, _ = self._tick(runstate)
        assert (first["missed"], second["missed"]) == (1, 0)

    def test_the_marker_is_persisted(self):
        # Was assert_called_once; since DPLAN-0332 the tick also stamps
        # last_tick, so the count no longer identifies this write. The claim is
        # that the marker reaches disk, and that is asserted directly.
        runstate = {"jobs": {}}
        _results, mock_save = self._tick(runstate)
        assert mock_save.called
        assert runstate["jobs"]["@commons/live"]["missed_logged_for"]
        assert any(
            call[0][0]["jobs"].get("@commons/live", {}).get("missed_logged_for") for call in mock_save.call_args_list
        ), "the MISSED marker never reached a save"

    def test_a_job_that_opts_out_is_told_it_is_not_firing(self, capsys):
        # SUPERSEDED SHAPE, SAME DEFECT. This pin used to pass no catch_up field
        # at all, because under ruling 6 (2026-09-07) absent meant off. DPLAN-0332
        # reversed the default on 2026-09-08, so absent now means ON and only an
        # explicit false opts out — the opt-out is what has to be stated here.
        #
        # The defect is unchanged and is the reason the pin survives the reversal:
        # on 2026-09-08 at 11:37:52 this line read "catch_up is off — not firing"
        # and the same tick fired the job three seconds later, because the line
        # read the raw field while is_job_due() read catch_up_on(). One predicate
        # now answers both.
        self._tick({"jobs": {}}, catch_up=False)
        assert "catch_up is off — not firing" in flat(capsys.readouterr().out)

    def test_an_unset_catch_up_is_told_it_is_firing_late(self, capsys):
        # The flip itself: a job that states nothing is caught up, and the line
        # says so. Every enabled job in the fleet left this field unset, which is
        # exactly why nothing recovered from the 23-hour gap on 2026-09-08.
        self._tick({"jobs": {}})
        # Reads the flag: the lane is gated while @devpulse and Patrick run the
        # controlled live proof, and the line must tell the truth in BOTH worlds.
        expected = "on — firing late this tick" if runstate_mod.RECOVERY_LANE_LIVE else "off — not firing"
        assert f"catch_up is {expected}" in flat(capsys.readouterr().out)

    def test_a_job_with_catch_up_is_told_it_is_firing_late(self, capsys):
        self._tick({"jobs": {}}, catch_up=True)
        assert "catch_up is on — firing late this tick" in flat(capsys.readouterr().out)

    def test_dry_run_reports_without_writing(self, capsys):
        runstate = {"jobs": {}}
        results, mock_save = self._tick(runstate, dry_run=True)
        assert results["missed"] == 0
        assert "DRY RUN — would record MISSED" in flat(capsys.readouterr().out)
        mock_save.assert_not_called()
        assert runstate["jobs"] == {}


class TestSlotSeeding:
    def _tick(self, job, runstate, dry_run=False):
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}._fire_job", return_value=(OUTCOME_FIRED, "")),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            results = run_tick(dry_run=dry_run)
        return results, mock_save

    def test_a_slotted_job_is_seeded_before_it_can_fire(self, capsys):
        # The whole point: seeding runs BEFORE the due check, so the job never
        # fires at the arbitrary minute the daemon happened to tick.
        runstate = {"jobs": {}}
        results, _save = self._tick(interval_job_with_slot(), runstate)
        out = capsys.readouterr().out
        assert results["seeded"] == 1
        assert results["fired"] == 0
        assert "SEED: @seedgo/shadow-cycle-weekly" in flat(out)
        assert runstate["jobs"]["@seedgo/shadow-cycle-weekly"]["last_run"] == "2026-09-06T03:00:00"

    def test_a_slotless_job_warns_and_still_fires(self, caplog):
        # Asserted on the LOGGER, not the console: this is the line that lands
        # in logs/run.log, which is the artifact an owner actually reads.
        runstate = {"jobs": {}}
        with caplog.at_level("WARNING"):
            results, _save = self._tick(interval_job_with_slot(slot=None), runstate)
        assert results["seeded"] == 0
        assert results["fired"] == 1
        assert "declares no 'slot'" in caplog.text
        assert "@seedgo/shadow-cycle-weekly" in caplog.text
        assert "IMMEDIATE" in caplog.text

    def test_a_blocked_job_is_still_seedable(self, capsys):
        # record_job_blocked leaves a row with no last_run. Keying the seed on
        # the ROW would strand exactly the job the lesson came from.
        runstate = {
            "jobs": {
                "@seedgo/shadow-cycle-weekly": {"last_status": "blocked", "last_blocked_at": "2026-09-07T01:34:52"}
            }
        }
        results, _save = self._tick(interval_job_with_slot(), runstate)
        assert results["seeded"] == 1
        assert "SEED: @seedgo/shadow-cycle-weekly" in flat(capsys.readouterr().out)

    def test_an_already_running_job_is_left_alone(self):
        runstate = {"jobs": {"@seedgo/shadow-cycle-weekly": {"last_run": "2026-09-06T03:00:00"}}}
        results, _save = self._tick(interval_job_with_slot(), runstate)
        assert results["seeded"] == 0

    def test_dry_run_seeds_nothing(self, capsys):
        runstate = {"jobs": {}}
        results, mock_save = self._tick(interval_job_with_slot(), runstate, dry_run=True)
        assert results["seeded"] == 0
        assert "DRY RUN — would seed" in flat(capsys.readouterr().out)
        mock_save.assert_not_called()
        assert runstate["jobs"] == {}


class TestCaughtUpTick:
    def test_a_late_run_is_counted_and_stamped(self, capsys):
        job = live_job()
        job["schedule"]["catch_up"] = True
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value={"jobs": {}}),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.is_job_due", return_value=True),
            patch(f"{RUN}.is_catch_up_fire", return_value=True),
            patch(f"{RUN}._fire_job", return_value=(OUTCOME_FIRED, "")),
            patch(f"{RUN}.update_job_runstate") as mock_update,
            patch(f"{RUN}.save_runstate", return_value=True),
        ):
            results = run_tick()
        assert results["caught_up"] == 1
        assert "CAUGHT UP: @commons/live" in flat(capsys.readouterr().out)
        assert mock_update.call_args.kwargs["caught_up"] is True

    def test_an_ordinary_run_is_not_stamped(self):
        with (
            patch(f"{RUN}.discover_jobs", return_value=[live_job()]),
            patch(f"{RUN}.load_runstate", return_value={"jobs": {}}),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.is_job_due", return_value=True),
            patch(f"{RUN}.is_catch_up_fire", return_value=False),
            patch(f"{RUN}._fire_job", return_value=(OUTCOME_FIRED, "")),
            patch(f"{RUN}.update_job_runstate") as mock_update,
            patch(f"{RUN}.save_runstate", return_value=True),
        ):
            results = run_tick()
        assert results["caught_up"] == 0
        assert mock_update.call_args.kwargs["caught_up"] is False
