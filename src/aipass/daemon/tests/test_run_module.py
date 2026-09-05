# =================== AIPass ====================
# Name: test_run_module.py
# Description: Tests for the drone @daemon run module
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-06-25
# =============================================

"""Tests for the drone @daemon run module (decentralized scheduler tick)."""

from unittest.mock import patch

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
        assert result is True
        assert isinstance(result, bool), f"handle_command answered {type(result).__name__}, not bool"


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
        """Run a tick where nothing is due, returning the save mock."""
        with (
            patch(f"{RUN}.discover_jobs", return_value=[live_job()]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.is_job_due", return_value=False),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            run_tick(dry_run=dry_run)
        return mock_save

    def test_prune_is_saved_even_when_nothing_fires(self):
        runstate = {"jobs": {"@ghost/retired": {"last_run": "2026-06-25T08:11:05"}, "@commons/live": {}}}
        mock_save = self._quiet_tick(runstate)
        # The bug: pruning mutated memory every tick but only ever saved inside
        # the fire loop, so a quiet tick threw the prune away.
        mock_save.assert_called_once()
        assert "@ghost/retired" not in mock_save.call_args[0][0]["jobs"]

    def test_clean_runstate_is_not_rewritten(self):
        mock_save = self._quiet_tick({"jobs": {"@commons/live": {}}})
        mock_save.assert_not_called()

    def test_dry_run_never_writes(self):
        runstate = {"jobs": {"@ghost/retired": {}, "@commons/live": {}}}
        mock_save = self._quiet_tick(runstate, dry_run=True)
        mock_save.assert_not_called()

    def test_discovery_failure_does_not_wipe_runstate(self):
        runstate = {"jobs": {"@commons/live": {}}}
        with (
            patch(f"{RUN}.discover_jobs", return_value=[]),
            patch(f"{RUN}.load_runstate", return_value=runstate),
            patch(f"{RUN}.save_runstate", return_value=True) as mock_save,
        ):
            run_tick()
        mock_save.assert_not_called()
        assert runstate["jobs"] == {"@commons/live": {}}


# ── rotation delegation (DPLAN-0287 piece 1) ─────────


class TestRotationDelegation:
    def test_rotation_job_goes_to_the_rotation_module(self):
        job = {
            "owner": "@daemon",
            "id": "fleet-steward",
            "enabled": True,
            "schedule": {"type": "rotation", "time": "05:00"},
            "wake": {},
            "prompt": "STEWARD NIGHT for {branch}.",
        }
        runstate = {"jobs": {}}
        # fire_rotation keeps its own (ok, detail) answer; _fire_job maps it onto
        # the three-state outcome the tick loop now reads.
        with patch(f"{RUN}.fire_rotation", return_value=(True, "woke @backup")) as mock_rotation:
            outcome, detail = _fire_job(job, runstate)
        assert outcome == OUTCOME_FIRED
        assert detail == "woke @backup"
        mock_rotation.assert_called_once_with(job, runstate)

    def test_ordinary_job_never_touches_the_rotation(self):
        with (
            patch(f"{RUN}.fire_rotation") as mock_rotation,
            patch("aipass.ai_mail.apps.handlers.dispatch.wake.wake_branch", side_effect=RuntimeError("no wake")),
        ):
            outcome, _detail = _fire_job(live_job(), {"jobs": {}})
        assert outcome == OUTCOME_FAILED
        mock_rotation.assert_not_called()
