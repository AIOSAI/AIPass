# =================== AIPass ====================
# Name: test_run_module.py
# Description: Tests for the drone @daemon run module
# Version: 1.2.0
# Created: 2026-06-15
# Modified: 2026-09-11
# =============================================

"""Tests for the drone @daemon run module (decentralized scheduler tick)."""

import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Optional
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule import command_job
from aipass.daemon.apps.handlers.schedule import runstate as runstate_mod
from aipass.daemon.apps.modules import run as run_mod
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


def interval_job_with_slot(slot: Optional[str] = "2026-09-06T03:00:00", minutes=10080):
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


# ── command jobs (DPLAN-0338) ────────────────────────


def fake_drone(tmp_path, program: str = "", mail_exit: int = 0) -> tuple:
    """A stand-in for drone: the interpreter running a one-liner, so the tokens after "drone" arrive as sys.argv[1:].

    Every launch first appends its argv and cwd to a journal, so a test reads back
    exactly what ran and where. A launch whose first argument is @ai_mail is the
    notify mail and answers ``mail_exit``; anything else runs ``program``.
    """
    journal = tmp_path / "launches.jsonl"
    prelude = (
        "import json, os, subprocess, sys, time\n"
        f"with open({str(journal)!r}, 'a', encoding='utf-8') as f:\n"
        "    f.write(json.dumps({'argv': sys.argv[1:], 'cwd': os.getcwd()}) + '\\n')\n"
        f"if sys.argv[1:2] == ['@ai_mail']:\n    sys.exit({mail_exit})\n"
    )
    return (sys.executable, "-c", prelude + program), journal


def launches(journal) -> list:
    """Every launch the fake recorded, in order."""
    if not journal.exists():
        return []
    return [json.loads(line) for line in journal.read_text(encoding="utf-8").splitlines()]


def same_dir(a, b) -> bool:
    return os.path.realpath(str(a)) == os.path.realpath(str(b))


def command_job_dict(branch_dir, command="drone @daemon --help", **extra) -> dict:
    """A discovered command job, in the shape discovery hands the tick."""
    job = {
        "owner": "@commons",
        "id": "sweep",
        "enabled": True,
        "schedule": {"type": "once", "due_date": "2020-01-01"},
        "wake": {},
        "config": {},
        "command": command,
        "branch_path": str(branch_dir),
    }
    job.update(extra)
    return job


def pid_gone(pid: int, within: float = 5.0) -> bool:
    """True once *pid* is dead. A zombie waiting for its new parent to reap it counts as dead.

    POSIX only, and its one caller is skipped elsewhere: signal 0 probes a process
    on POSIX, but on Windows os.kill TERMINATES it, so the probe is guarded.
    """
    deadline = time.monotonic() + within
    while time.monotonic() < deadline:
        if os.name == "posix":
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True
        stat = f"/proc/{pid}/stat"
        if os.path.exists(stat):
            with open(stat, encoding="utf-8") as f:
                if f.read().rsplit(")", 1)[-1].split()[0] == "Z":
                    return True
        time.sleep(0.1)
    return False


def kill_quietly(pid: int) -> None:
    """Teardown for a test that started a background process. Already gone is fine, and said."""
    try:
        os.kill(pid, signal.SIGTERM)  # TerminateProcess on Windows, SIGTERM on POSIX
    except OSError as e:
        print(f"background pid {pid} already gone at teardown: {e}")


@pytest.fixture
def telegram():
    """The three telegram seams, mocked, so no test here pings a real chat."""
    base = "aipass.daemon.apps.handlers.schedule.telegram_notifier"
    with (
        patch(f"{base}.notify_triggered") as triggered,
        patch(f"{base}.notify_complete") as complete,
        patch(f"{base}.notify_error") as error,
    ):
        yield {"triggered": triggered, "complete": complete, "error": error}


@pytest.fixture
def no_wake():
    """wake_branch, wired to fail loudly if a command job ever reaches it."""
    wake = "aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch"
    with patch(wake, side_effect=AssertionError("a command job woke someone")) as mock_wake:
        yield mock_wake


class TestCommandArgv:
    def test_splits_quoted_arguments_without_a_shell(self):
        argv = command_job.command_argv('drone @ai_mail email @x "two words"')
        assert argv == ["drone", "@ai_mail", "email", "@x", "two words"]

    def test_shell_syntax_arrives_as_plain_arguments(self):
        # No shell: a glob, a pipe and a ; are characters in argv, never operators.
        argv = command_job.command_argv("drone rm *.tmp | tee x ; echo y")
        assert argv == ["drone", "rm", "*.tmp", "|", "tee", "x", ";", "echo", "y"]

    @pytest.mark.parametrize(
        "command",
        ["rm -rf ../..", "bash -c 'drone @daemon run'", "/usr/local/bin/drone @daemon", "env drone @daemon run"],
    )
    def test_anything_but_drone_first_is_refused(self, command):
        with pytest.raises(ValueError, match="first token must be 'drone'"):
            command_job.command_argv(command)

    @pytest.mark.parametrize("command", ["", "   ", None, 42, ["drone", "@daemon"]])
    def test_an_empty_or_non_string_command_is_refused(self, command):
        with pytest.raises(ValueError, match="non-empty string"):
            command_job.command_argv(command)

    def test_an_unbalanced_quote_is_refused_not_guessed(self):
        with pytest.raises(ValueError, match="does not parse"):
            command_job.command_argv('drone @daemon "unterminated')


class TestOutputTail:
    def test_keeps_the_last_lines_and_drops_blank_ones(self):
        assert command_job.output_tail("a\n\nb\nc\n  \nd\ne\nf\n") == "b\nc\nd\ne\nf"

    def test_caps_from_the_front_so_the_ending_survives(self):
        tail = command_job.output_tail("x" * 1000 + "\nTHE END", lines=5, max_chars=50)
        assert len(tail) == 50
        assert tail.startswith("...")
        assert tail.endswith("THE END")


class TestRunCommand:
    def test_exit_zero_is_ok_with_the_output_tail(self, tmp_path, monkeypatch):
        launcher, journal = fake_drone(tmp_path, "for i in range(8): print(f'line {i}')\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", tmp_path, 30)
        assert result.ok
        assert (result.exit_code, result.timed_out, result.error) == (0, False, "")
        assert result.tail.splitlines() == ["line 3", "line 4", "line 5", "line 6", "line 7"]
        assert [entry["argv"] for entry in launches(journal)] == [["@daemon", "--help"]]

    def test_a_non_zero_exit_fails_and_keeps_stderr_in_order(self, tmp_path, monkeypatch):
        program = "print('scanned 4', flush=True)\nsys.stderr.write('refused: fence\\n')\nsys.exit(3)\n"
        launcher, _ = fake_drone(tmp_path, program)
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone rm --stale 10d .", tmp_path, 30)
        assert not result.ok
        assert result.exit_code == 3
        assert result.tail.splitlines() == ["scanned 4", "refused: fence"]

    def test_an_overrun_is_stopped_and_named(self, tmp_path, monkeypatch):
        launcher, _ = fake_drone(tmp_path, "print('started', flush=True)\ntime.sleep(30)\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", tmp_path, 1)
        assert not result.ok
        assert result.timed_out is True
        assert result.exit_code is None
        assert result.duration < 10, f"a 1s timeout took {result.duration:.1f}s to come back"
        assert result.tail == "started", "output written before the overrun must survive into the tail"

    @pytest.mark.skipif(os.name != "posix", reason="process groups are POSIX; Windows stops the direct child only")
    def test_an_overrun_stops_the_grandchild_too(self, tmp_path, monkeypatch):
        # Drone runs every @branch verb in a child of its own, so killing drone
        # alone would orphan exactly the work that overran.
        pidfile = tmp_path / "grandchild.pid"
        program = (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
            "print('spawned', flush=True)\ntime.sleep(30)\n"
        )
        launcher, _ = fake_drone(tmp_path, program)
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", tmp_path, 1)
        grandchild = int(pidfile.read_text())
        try:
            assert result.timed_out is True
            assert pid_gone(grandchild), f"grandchild {grandchild} outlived the timeout"
        finally:
            kill_quietly(grandchild)

    def test_a_background_child_holding_the_output_is_not_a_timeout(self, tmp_path, monkeypatch):
        # Through a pipe, the read waits for EVERY holder of the write end, so a
        # command that exited 0 at once would be reported as an overrun.
        pidfile = tmp_path / "background.pid"
        program = (
            "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(20)'])\n"
            f"open({str(pidfile)!r}, 'w').write(str(child.pid))\n"
            "print('done', flush=True)\n"
        )
        launcher, _ = fake_drone(tmp_path, program)
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", tmp_path, 10)
        background = int(pidfile.read_text())
        try:
            assert result.ok, f"exit 0 reported as {result}"
            assert result.duration < 5, f"returned after {result.duration:.1f}s — it waited on the background child"
        finally:
            kill_quietly(background)

    def test_the_command_runs_in_the_owner_branch(self, tmp_path, monkeypatch):
        branch = tmp_path / "owner_branch"
        branch.mkdir()
        launcher, journal = fake_drone(tmp_path, "print(os.getcwd())\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", branch, 30)
        assert same_dir(result.tail, branch)
        assert same_dir(launches(journal)[0]["cwd"], branch)

    def test_no_shell_reads_the_command(self, tmp_path, monkeypatch):
        (tmp_path / "a.tmp").write_text("x", encoding="utf-8")
        launcher, _ = fake_drone(tmp_path, "print(json.dumps(sys.argv[1:]))\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone rm *.tmp ; echo pwned", tmp_path, 30)
        assert json.loads(result.tail) == ["rm", "*.tmp", ";", "echo", "pwned"]

    def test_no_branch_directory_is_refused_never_run_from_here(self, tmp_path, monkeypatch):
        launcher, journal = fake_drone(tmp_path, "")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", None)
        assert not result.ok
        assert "no branch directory" in result.error
        assert launches(journal) == [], "nothing may start from the tick's own cwd"

    def test_a_missing_branch_directory_fails_to_start(self, tmp_path, monkeypatch):
        launcher, journal = fake_drone(tmp_path, "")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("drone @daemon --help", tmp_path / "gone", 30)
        assert not result.ok
        assert result.error.startswith("could not start")
        assert launches(journal) == []

    def test_a_non_drone_command_never_starts(self, tmp_path, monkeypatch):
        launcher, journal = fake_drone(tmp_path, "")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        result = command_job.run_command("rm -rf ../..", tmp_path, 30)
        assert result.error.startswith("refused: the first token must be 'drone'")
        assert launches(journal) == []

    def test_the_suite_seal_answers_any_test_that_forgot_its_fake(self, tmp_path):
        # conftest's _seal_command_launcher: no test reaches the real drone.
        result = command_job.run_command("drone @daemon --help", tmp_path, 30)
        assert result.exit_code == 1
        assert "sealed: a test reached the real drone launcher" in result.tail


class TestCommandJobFire:
    def _fire(self, tmp_path, monkeypatch, program, mail_exit=0, **extra):
        launcher, journal = fake_drone(tmp_path, program, mail_exit=mail_exit)
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        branch = tmp_path / "branch"
        branch.mkdir()
        job = command_job_dict(branch, **extra)
        outcome, detail = _fire_job(job, {"jobs": {}}, header="Scheduled wake: sweep")
        return outcome, detail, launches(journal), branch

    def test_exit_zero_is_fired_and_nobody_is_woken(
        self, tmp_path, monkeypatch, telegram, no_wake, capsys, caplog, _seal_branch_wake_prompt
    ):
        with caplog.at_level("INFO"):
            outcome, detail, runs, _ = self._fire(tmp_path, monkeypatch, "print('4 files deleted')\n")
        assert outcome == OUTCOME_FIRED
        assert detail.startswith("exit 0, ")
        assert detail.endswith("— 4 files deleted")
        no_wake.assert_not_called()
        assert [entry["argv"] for entry in runs] == [["@daemon", "--help"]]
        assert not (_seal_branch_wake_prompt / "last_wake_prompt.txt").exists(), "a command job files no wake prompt"

        out = flat(capsys.readouterr().out)
        assert "FIRE: @commons/sweep -> command: drone @daemon --help" in out
        assert "DONE: @commons/sweep — exit 0, " in out
        # logs/run.log is the logger, not the console: both lines land there too.
        assert "[run] FIRE @commons/sweep command: drone @daemon --help" in caplog.text
        assert "[run] DONE @commons/sweep exit 0, " in caplog.text
        assert "4 files deleted" in caplog.text

    def test_a_non_zero_exit_is_failed_with_the_tail(self, tmp_path, monkeypatch, telegram, no_wake, caplog):
        with caplog.at_level("WARNING"):
            outcome, detail, _, _ = self._fire(
                tmp_path, monkeypatch, "print('refused: fence', flush=True)\nsys.exit(2)\n"
            )
        assert outcome == OUTCOME_FAILED
        assert detail.startswith("exit 2, ")
        assert detail.endswith("— refused: fence")
        assert "[run] DONE @commons/sweep exit 2, " in caplog.text
        no_wake.assert_not_called()

    def test_an_overrun_is_failed_and_named(self, tmp_path, monkeypatch, telegram, no_wake):
        outcome, detail, _, _ = self._fire(tmp_path, monkeypatch, "time.sleep(30)\n", timeout_seconds=1)
        assert outcome == OUTCOME_FAILED
        assert detail.startswith("timed out after 1s, process tree stopped")
        no_wake.assert_not_called()

    def test_a_wake_block_is_ignored_at_fire(self, tmp_path, monkeypatch, telegram, no_wake):
        outcome, _, runs, _ = self._fire(tmp_path, monkeypatch, "", wake={"fresh": True, "model": "opus"})
        assert outcome == OUTCOME_FIRED
        assert len(runs) == 1
        no_wake.assert_not_called()

    def test_telegram_pings_on_start_and_on_finish(self, tmp_path, monkeypatch, telegram, no_wake):
        _, detail, _, _ = self._fire(tmp_path, monkeypatch, "print('ok')\n")
        telegram["triggered"].assert_called_once_with("@commons", "sweep")
        telegram["complete"].assert_called_once_with("@commons", "sweep", detail)
        telegram["error"].assert_not_called()

    def test_telegram_names_a_failure(self, tmp_path, monkeypatch, telegram, no_wake):
        _, detail, _, _ = self._fire(tmp_path, monkeypatch, "sys.exit(4)\n")
        telegram["triggered"].assert_called_once_with("@commons", "sweep")
        telegram["error"].assert_called_once_with("@commons", "sweep", detail)
        telegram["complete"].assert_not_called()

    def test_notify_false_keeps_telegram_quiet(self, tmp_path, monkeypatch, telegram, no_wake):
        self._fire(tmp_path, monkeypatch, "print('ok')\n", notify=False)
        for seam in telegram.values():
            seam.assert_not_called()

    def test_notify_email_mails_start_and_finish_signed_daemon(self, tmp_path, monkeypatch, telegram, no_wake):
        notify = {"email": "@devpulse"}
        outcome, _, runs, branch = self._fire(tmp_path, monkeypatch, "print('4 deleted')\n", notify=notify)
        assert outcome == OUTCOME_FIRED
        assert [entry["argv"][:3] for entry in runs] == [
            ["@ai_mail", "email", "@devpulse"],
            ["@daemon", "--help"],
            ["@ai_mail", "email", "@devpulse"],
        ], "start mail, then the command, then the finish mail"

        start_subject, start_body = runs[0]["argv"][3:]
        assert start_subject == "Command job started: @commons/sweep"
        assert "Command: drone @daemon --help" in start_body
        assert "Timeout: 600s" in start_body

        finish_subject, finish_body = runs[2]["argv"][3:]
        assert finish_subject.startswith("Command job passed: @commons/sweep (exit 0, ")
        assert "Exit code: 0" in finish_body
        assert "Duration: " in finish_body
        assert finish_body.endswith("Output tail:\n4 deleted")

        # cwd is identity: the mails are signed @daemon, the command runs as its owner.
        assert same_dir(runs[0]["cwd"], run_mod._DAEMON_ROOT)
        assert same_dir(runs[2]["cwd"], run_mod._DAEMON_ROOT)
        assert same_dir(runs[1]["cwd"], branch)
        # A notify BLOCK is not a no: telegram keeps pinging under the same rule.
        telegram["triggered"].assert_called_once()

    def test_the_finish_mail_says_failed(self, tmp_path, monkeypatch, telegram, no_wake):
        _, _, runs, _ = self._fire(tmp_path, monkeypatch, "sys.exit(2)\n", notify={"email": "@devpulse"})
        finish_subject, finish_body = runs[-1]["argv"][3:]
        assert finish_subject.startswith("Command job FAILED: @commons/sweep (exit 2, ")
        assert "Exit code: 2" in finish_body

    def test_a_mail_that_fails_never_changes_the_answer(self, tmp_path, monkeypatch, telegram, no_wake, caplog):
        with caplog.at_level("WARNING"):
            outcome, _, runs, _ = self._fire(
                tmp_path, monkeypatch, "print('ok')\n", mail_exit=1, notify={"email": "@devpulse"}
            )
        assert outcome == OUTCOME_FIRED
        assert len(runs) == 3, "both mails were attempted"
        assert caplog.text.count("[run] notify mail to @devpulse not sent") == 2


class TestCommandJobTick:
    """The runstate row a command job leaves is the row a wake job leaves."""

    def _tick(self, tmp_path, monkeypatch, program, job):
        launcher, journal = fake_drone(tmp_path, program)
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        runstate = {"jobs": {}}
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True),
        ):
            results = run_tick()
        return results, runstate, journal

    def test_a_pass_writes_the_row_a_wake_would(self, tmp_path, monkeypatch, telegram, no_wake):
        job = command_job_dict(tmp_path)
        results, runstate, _ = self._tick(tmp_path, monkeypatch, "print('ok')\n", job)
        assert (results["fired"], results["failed"], results["blocked"]) == (1, 0, 0)
        row = runstate["jobs"]["@commons/sweep"]
        assert row["last_status"] == "success"
        assert row["last_success_at"] == row["last_run"]
        assert row["last_error"] is None
        assert row["completed"] == row["last_run"], "a once job completes exactly as a wake job does"

        wake_row = {"jobs": {}}
        runstate_mod.update_job_runstate(wake_row, "@commons", "sweep", job["schedule"])
        assert set(row) == set(wake_row["jobs"]["@commons/sweep"]), "no new fields: the row is a wake job's row"

    def test_a_failure_writes_the_row_a_wake_would(self, tmp_path, monkeypatch, telegram, no_wake):
        job = command_job_dict(tmp_path)
        results, runstate, _ = self._tick(tmp_path, monkeypatch, "print('refused', flush=True)\nsys.exit(2)\n", job)
        assert (results["fired"], results["failed"], results["blocked"]) == (0, 1, 0)
        row = runstate["jobs"]["@commons/sweep"]
        assert row["last_status"] == "failed"
        assert row["last_failure_at"] == row["last_run"]
        assert row["last_error"].startswith("exit 2, ")
        assert row["last_error"].endswith("— refused")
        assert "completed" not in row, "a failed once job is not done; it retries after the backoff"

    def test_a_completed_once_job_does_not_run_again(self, tmp_path, monkeypatch, telegram, no_wake):
        job = command_job_dict(tmp_path)
        launcher, journal = fake_drone(tmp_path, "print('ok')\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        runstate = {"jobs": {}}
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True),
        ):
            first, second = run_tick(), run_tick()
        assert (first["fired"], second["fired"]) == (1, 0)
        assert len(launches(journal)) == 1

    def test_a_late_daily_command_job_is_caught_up_like_any_other(self, tmp_path, monkeypatch, telegram, no_wake):
        # catch_up is opt-in while RECOVERY_LANE_LIVE is False; opted in, the
        # window closed unrun two days ago, so the real predicates say "late".
        job = command_job_dict(tmp_path, schedule={"type": "daily", "time": "00:01", "catch_up": True})
        launcher, _ = fake_drone(tmp_path, "print('ok')\n")
        monkeypatch.setattr(command_job, "LAUNCHER", launcher)
        runstate = {
            "jobs": {"@commons/sweep": {"last_run": "2020-01-01T00:01:00", "last_success_at": "2020-01-01T00:01:00"}}
        }
        with (
            patch(f"{RUN}.discover_jobs", return_value=[job]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.missed_window", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True),
        ):
            results = run_tick()
        assert (results["fired"], results["caught_up"]) == (1, 1)
        assert runstate["jobs"]["@commons/sweep"]["caught_up"] == runstate["jobs"]["@commons/sweep"]["last_run"]


# (schedule, runstate row, now, due) — due-ness never reads what a job DOES, so a
# command job inherits every rule a wake job has: windows, catch-up, backoff, once.
_DUE_CASES = [
    ({"type": "daily", "time": "04:00"}, {}, "2026-09-11T04:05:00", True),
    ({"type": "daily", "time": "04:00"}, {"last_success_at": "2026-09-11T04:01:00"}, "2026-09-11T04:10:00", False),
    (
        {"type": "daily", "time": "04:00", "catch_up": True},
        {"last_run": "2026-09-09T04:01:00"},
        "2026-09-11T09:00:00",
        True,
    ),
    (
        {"type": "daily", "time": "04:00", "catch_up": False},
        {"last_run": "2026-09-09T04:01:00"},
        "2026-09-11T09:00:00",
        False,
    ),
    ({"type": "interval", "interval_minutes": 10080}, {"last_run": "2026-09-01T04:00:00"}, "2026-09-11T09:00:00", True),
    (
        {"type": "interval", "interval_minutes": 10080},
        {"last_run": "2026-09-10T04:00:00"},
        "2026-09-11T09:00:00",
        False,
    ),
    ({"type": "hourly", "time": "30"}, {}, "2026-09-11T09:31:00", True),
    ({"type": "once", "due_date": "2026-09-11"}, {}, "2026-09-11T09:00:00", True),
    ({"type": "once", "due_date": "2026-09-11"}, {"completed": "2026-09-11T08:00:00"}, "2026-09-11T09:00:00", False),
    (
        {"type": "daily", "time": "09:00"},
        {"last_run": "2026-09-11T08:58:00", "last_status": "failed", "last_failure_at": "2026-09-11T08:58:00"},
        "2026-09-11T09:00:00",
        False,
    ),
]


class TestCatchUpUntouched:
    @pytest.mark.parametrize("schedule,row,now,due", _DUE_CASES)
    def test_a_command_job_is_due_exactly_when_a_wake_job_is(self, schedule, row, now, due):
        at = datetime.fromisoformat(now)
        runstate = {"jobs": {"@commons/live": dict(row)}}
        wake_job = {**live_job(), "schedule": schedule}
        cmd_job = command_job_dict("/unused", id="live", schedule=schedule)
        assert runstate_mod.is_job_due(wake_job, runstate, at) is due
        assert runstate_mod.is_job_due(cmd_job, runstate, at) is due
        assert runstate_mod.is_catch_up_fire(cmd_job, runstate, at) == runstate_mod.is_catch_up_fire(
            wake_job, runstate, at
        )
        assert runstate_mod.missed_window(cmd_job, runstate, at) == runstate_mod.missed_window(wake_job, runstate, at)

    def test_the_cases_are_not_vacuous(self):
        verdicts = [case[3] for case in _DUE_CASES]
        assert verdicts.count(True) >= 4 and verdicts.count(False) >= 4, verdicts

    def test_an_interval_command_job_is_slot_seeded_like_any_other(self):
        schedule = {"type": "interval", "interval_minutes": 10080, "slot": "2026-09-14T04:00:00"}
        cmd_job = command_job_dict("/unused", schedule=schedule)
        runstate = {"jobs": {}}
        assert runstate_mod.needs_slot_seed(cmd_job, runstate) is True
        assert runstate_mod.seed_interval_slot(runstate, cmd_job, datetime(2026, 9, 11, 13, 0)) is not None
        assert runstate["jobs"]["@commons/sweep"]["next_run"].startswith("2026-09-14T04:00")


class TestHelpNamesCommandJobs:
    def test_run_help_shows_the_command_job_shape(self, capsys):
        handle_command("run", ["--help"])
        out = flat(capsys.readouterr().out)
        assert '"command": "drone rm --stale 10d ../.."' in out
        assert "drone must be the first token" in out
        assert '"notify": { "email": "@devpulse" }' in out
