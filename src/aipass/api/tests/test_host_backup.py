# =================== AIPass ====================
# Name: test_host_backup.py
# Description: Tests for the host API's backup door — runs, cancels, jobs, status and schedule
# Version: 1.3.0
# Created: 2026-10-16
# Modified: 2026-11-15
# =============================================

"""Tests for apps/handlers/host/backup.py."""

# A file of its own for this build (DPLAN-0411): the job table, the lane argv,
# the hour and the status pass-through are the handler's logic and are reached
# through its public functions. The routes' wiring is test_host_api_routes.py's.
# @backup is never run: drone's router is replaced at this handler's reference
# to it, and its status --json is always an answer written here.

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that backup.py parses and imports
# sentry: no-test-needed(external) — route_command, patched at backup.py's reference so no lane runs
# sentry: no-test-needed(covered_elsewhere) — answer(), tests/test_host_api_routes.py

import json
import threading
import types
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, List, Tuple
from unittest.mock import MagicMock, patch

import pytest

import aipass.drone as drone
from aipass.api.apps.handlers.host import backup as host_backup
from aipass.api.apps.handlers.host import fleet as host_fleet
from aipass.api.apps.handlers.host import server as host_server
from aipass.api.apps.handlers.host import tokens as host_tokens

PATCH_BACKUP_DRONE = "aipass.api.apps.handlers.host.backup.drone"
PATCH_BACKUP_LOGGER = "aipass.api.apps.handlers.host.backup.logger"
PATCH_BACKUP_JSON = "aipass.api.apps.handlers.host.backup.json_handler"
PATCH_DENIALS_LOGGER = "aipass.api.apps.handlers.host.denials.logger"
PATCH_SERVER_LOGGER = "aipass.api.apps.handlers.host.server.logger"
PATCH_DENIALS_JSON = "aipass.api.apps.handlers.host.denials.json_handler"

STATUS = {
    "registered": True,
    "mode": "snapshot",
    "drive_sync": False,
    "runs": 64,
    "lanes": {
        "snapshot": {"last": "2026-10-16T07:09:50+00:00", "files": 15414},
        "drive_sync": {"last": None, "files": None},
    },
    "drive": {"tracked_files": 12},
}


class FakeClock:
    """The table's clock, moved by hand."""

    def __init__(self) -> None:
        self.now = datetime(2026, 10, 16, 7, 30, tzinfo=timezone.utc)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += timedelta(seconds=seconds)


class Starter:
    """Records each worker the table starts; the test runs them in step."""

    def __init__(self) -> None:
        self.pending: List[Tuple[Callable[..., None], Tuple[Any, ...]]] = []

    def __call__(self, target: Callable[..., None], args: Tuple[Any, ...]) -> None:
        self.pending.append((target, args))

    def run_all(self) -> None:
        while self.pending:
            target, args = self.pending.pop(0)
            target(*args)


class Alarms:
    """Records each limit the table sets; a test fires one by hand."""

    def __init__(self) -> None:
        self.set: List[Tuple[float, Callable[[], None]]] = []
        self.cancelled = 0

    def __call__(self, seconds: float, action: Callable[[], None]) -> Any:
        self.set.append((seconds, action))
        alarm = MagicMock()
        alarm.cancel.side_effect = lambda: setattr(self, "cancelled", self.cancelled + 1)
        return alarm


def _result(stdout: str = "", exit_code: int = 0, stderr: str = "", command: str = "snapshot") -> Any:
    return drone.CommandResult(stdout=stdout, stderr=stderr, exit_code=exit_code, branch="backup", command=command)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def starter() -> Starter:
    return Starter()


@pytest.fixture
def alarms() -> Alarms:
    return Alarms()


@pytest.fixture
def door(seated: Path, clock: FakeClock, starter: Starter, alarms: Alarms, monkeypatch: Any):
    """A fresh job table, a hermetic seat, and drone's router replaced at the handler's reference."""
    monkeypatch.setattr(host_backup, "JOBS", host_backup.JobTable(clock=clock, start=starter, after=alarms))
    router = MagicMock()
    router.RoutingError = drone.RoutingError
    router.route_command.return_value = _result("snapshot=15414 files, 2.9 GB, 30.1s")
    with (
        patch(PATCH_BACKUP_DRONE, router),
        patch(PATCH_BACKUP_LOGGER),
        patch(PATCH_BACKUP_JSON),
        patch(PATCH_DENIALS_LOGGER),
        patch(PATCH_DENIALS_JSON),
    ):
        yield router


@pytest.fixture
def backup_log(door: Any):
    """The handler's logger, read by a test. Patched inside the door, so it unwinds first."""
    with patch(PATCH_BACKUP_LOGGER) as log:
        yield log


@pytest.fixture
def census(tmp_path: Path):
    """@baud's census naming one foreign project, BAUD, at a directory of its own."""
    root = tmp_path / "baud_project"
    root.mkdir()
    rows = {"projects": [{"name": "BAUD", "root": str(root)}]}
    with patch.object(host_fleet, "list_projects", return_value=rows):
        yield root


class TestStartRun:
    """POST /v1/backup/run's logic: one job per project and lane, answered at once."""

    def test_a_run_answers_the_running_job_without_waiting_for_the_lane(self, door: Any, starter: Starter) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")

        assert set(job) == {"job", "project", "lane", "state", "started_at"}
        assert job["project"] == "AIPASS"
        assert job["lane"] == "snapshot"
        assert job["state"] == "running"
        assert job["started_at"] == "2026-10-16T07:30:00+00:00"
        assert len(starter.pending) == 1
        door.route_command.assert_not_called()

    @pytest.mark.parametrize(
        ("lane", "flags", "limit"),
        [("snapshot", ["--quiet"], 1800), ("all", ["--quiet"], 86400)],
    )
    def test_each_limited_lane_runs_its_contract_argv_under_its_own_limit(
        self, door: Any, starter: Starter, alarms: Alarms, seated: Path, lane: str, flags: List[str], limit: int
    ) -> None:
        host_backup.start_run("AIPASS", lane)
        starter.run_all()

        target, verb, argv = door.route_command.call_args.args
        assert (target, verb) == ("@backup", lane)
        assert Path(argv[0]) == seated.resolve()
        assert argv[1:] == flags
        assert [seconds for seconds, _ in alarms.set] == [limit]
        assert door.route_command.call_args.kwargs == {"timeout": limit + host_backup.LIMIT_GRACE_SECONDS}

    def test_drive_sync_runs_without_quiet_and_with_no_limit_of_ours(
        self, door: Any, starter: Starter, alarms: Alarms, seated: Path
    ) -> None:
        host_backup.start_run("AIPASS", "drive_sync")
        starter.run_all()

        target, verb, argv = door.route_command.call_args.args
        assert (target, verb, argv[1:]) == ("@backup", "drive_sync", [])
        assert alarms.set == []
        assert door.route_command.call_args.kwargs["timeout"] >= 10 * 365 * 86400

    def test_a_lane_at_its_limit_is_ended_through_backups_stop_and_reads_stopped(
        self, door: Any, starter: Starter, alarms: Alarms, seated: Path
    ) -> None:
        def lane_or_stop(target: str, verb: str, argv: List[str], timeout: int) -> Any:
            if verb == "stop":
                return _result("stopped snapshot (pid 4242)", command="stop")
            alarms.set[0][1]()
            return _result("", exit_code=130, command=verb)

        door.route_command.side_effect = lane_or_stop
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        stop = door.route_command.call_args_list[1]
        assert stop.args[:2] == ("@backup", "stop")
        assert (Path(stop.args[2][0]), stop.args[2][1]) == (seated.resolve(), "snapshot")
        assert stop.kwargs == {"timeout": host_backup.CANCEL_TIMEOUT_SECONDS}
        assert host_backup.read_job(job["job"])["state"] == "stopped"

    def test_a_lane_that_finishes_in_time_cancels_its_limit_and_stops_nothing(
        self, door: Any, starter: Starter, alarms: Alarms
    ) -> None:
        host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        assert alarms.cancelled == 1
        assert [c.args[1] for c in door.route_command.call_args_list] == ["snapshot"]

    def test_a_limit_whose_stop_cannot_be_routed_is_logged_never_raised(
        self, door: Any, starter: Starter, alarms: Alarms, backup_log: Any
    ) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()
        refusal = drone.RoutingError("Branch not found: @backup")
        door.route_command.side_effect = refusal

        alarms.set[0][1]()

        backup_log.error.assert_called_once()
        message, lane, job_id, error = backup_log.error.call_args.args
        assert "could not be stopped at its limit" in message
        assert (lane, job_id, error) == ("snapshot", job["job"], refusal)
        assert backup_log.error.call_args.kwargs == {"exc_info": refusal}

    def test_a_second_run_of_the_same_lane_is_refused_with_the_contract_sentence(
        self, door: Any, starter: Starter
    ) -> None:
        first = host_backup.start_run("AIPASS", "snapshot")

        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("AIPASS", "snapshot")

        assert str(refused.value) == f"snapshot already running for AIPASS since {first['started_at']}"
        assert len(starter.pending) == 1

    def test_the_seat_in_another_case_is_the_same_slot(self, door: Any) -> None:
        host_backup.start_run("AIPASS", "snapshot")

        with pytest.raises(host_backup.VerbRefused):
            host_backup.start_run("aipass", "snapshot")

    def test_different_lanes_on_one_project_overlap(self, door: Any, starter: Starter) -> None:
        snapshot = host_backup.start_run("AIPASS", "snapshot")
        drive = host_backup.start_run("AIPASS", "drive_sync")

        assert snapshot["job"] != drive["job"]
        assert len(starter.pending) == 2

    def test_a_finished_lane_runs_again(self, door: Any, starter: Starter) -> None:
        host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        again = host_backup.start_run("AIPASS", "snapshot")

        assert again["state"] == "running"

    @pytest.mark.parametrize("lane", ["", "nightly", "SNAPSHOT", "versioned"])
    def test_a_missing_or_unknown_lane_is_refused_before_anything_runs(
        self, door: Any, starter: Starter, lane: str
    ) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("AIPASS", lane)

        assert "snapshot, all, drive_sync" in str(refused.value)
        assert starter.pending == []

    def test_a_missing_project_is_refused(self, door: Any, starter: Starter) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("  ", "snapshot")

        assert "project is required" in str(refused.value)
        assert starter.pending == []

    def test_an_unknown_project_is_refused_in_the_census_words(self, door: Any, starter: Starter, census: Path) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("VERA", "snapshot")

        assert "No project named 'VERA'" in str(refused.value)
        assert starter.pending == []

    def test_a_foreign_project_runs_at_its_census_root(self, door: Any, starter: Starter, census: Path) -> None:
        host_backup.start_run("BAUD", "snapshot")
        starter.run_all()

        assert Path(door.route_command.call_args.args[2][0]) == census.resolve()

    def test_backup_unreachable_before_start_is_unavailable_and_opens_no_job(self, door: Any, starter: Starter) -> None:
        door.resolve_branch.side_effect = drone.RoutingError("Branch not found: @backup")

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.start_run("AIPASS", "snapshot")

        assert starter.pending == []
        door.resolve_branch.side_effect = None
        assert host_backup.start_run("AIPASS", "snapshot")["state"] == "running"

    def test_a_worker_that_cannot_start_leaves_no_job_behind(self, door: Any, monkeypatch: Any) -> None:
        def refuse(target: Callable[..., None], args: Tuple[Any, ...]) -> None:
            raise RuntimeError("can't start new thread")

        monkeypatch.setattr(host_backup, "JOBS", host_backup.JobTable(start=refuse))
        door.route_command.return_value = _result(json.dumps(STATUS))

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.start_run("AIPASS", "snapshot")

        assert host_backup.read_status("AIPASS")["running"] == []


class TestStopRun:
    """POST /v1/backup/cancel's logic: @backup's stop on the request thread, its line verbatim."""

    def test_a_cancel_routes_stop_with_root_and_lane_and_answers_its_line_verbatim(
        self, door: Any, seated: Path
    ) -> None:
        door.route_command.return_value = _result("stopped drive_sync (pid 175450)\n", command="stop")

        answered = host_backup.stop_run("AIPASS", "drive_sync")

        assert answered == {
            "project": "AIPASS",
            "lane": "drive_sync",
            "stopped": True,
            "message": "stopped drive_sync (pid 175450)",
        }
        target, verb, argv = door.route_command.call_args.args
        assert (target, verb) == ("@backup", "stop")
        assert len(argv) == 2
        assert Path(argv[0]) == seated.resolve()
        assert argv[1] == "drive_sync"
        assert door.route_command.call_args.kwargs == {"timeout": host_backup.CANCEL_TIMEOUT_SECONDS}

    @pytest.mark.parametrize(
        "stdout", ["drive_sync is not running for AIPass\n", "drive_sync is not running for AIPass\nsecond line\n"]
    )
    def test_a_stop_that_exits_non_zero_is_not_running_with_its_first_stdout_line(self, door: Any, stdout: str) -> None:
        door.route_command.return_value = _result(
            stdout, exit_code=1, stderr="Traceback (most recent call last):\n", command="stop"
        )

        with pytest.raises(host_backup.NotRunning) as not_running:
            host_backup.stop_run("AIPASS", "drive_sync")

        assert str(not_running.value) == "drive_sync is not running for AIPass"

    def test_a_not_running_line_is_capped(self, door: Any) -> None:
        door.route_command.return_value = _result("x" * 5000, exit_code=1, command="stop")

        with pytest.raises(host_backup.NotRunning) as not_running:
            host_backup.stop_run("AIPASS", "drive_sync")

        assert str(not_running.value) == "x" * host_backup.MAX_LINE_CHARS

    def test_a_failed_stop_with_only_stderr_is_unavailable_never_not_running(self, door: Any) -> None:
        crash = 'Traceback (most recent call last):\n  File "/home/x/stop.py", line 9\nKeyError: pid\n'
        door.route_command.return_value = _result("", exit_code=1, stderr=crash, command="stop")

        with pytest.raises(host_backup.VerbUnavailable) as unavailable:
            host_backup.stop_run("AIPASS", "drive_sync")

        assert "Traceback" not in str(unavailable.value)

    def test_backup_unreachable_on_stop_is_unavailable(self, door: Any) -> None:
        door.route_command.side_effect = drone.RoutingError("Branch not found: @backup")

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.stop_run("AIPASS", "snapshot")

    @pytest.mark.parametrize("lane", ["", "nightly", "versioned"])
    def test_a_missing_or_unknown_lane_is_refused_before_backup_is_asked(self, door: Any, lane: str) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.stop_run("AIPASS", lane)

        assert "snapshot, all, drive_sync" in str(refused.value)
        door.route_command.assert_not_called()

    def test_a_missing_project_is_refused(self, door: Any) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.stop_run("", "snapshot")

        assert "project is required" in str(refused.value)
        door.route_command.assert_not_called()

    def test_an_unknown_project_is_refused_in_the_census_words(self, door: Any, census: Path) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.stop_run("VERA", "snapshot")

        assert "No project named 'VERA'" in str(refused.value)
        door.route_command.assert_not_called()

    def test_a_cancel_leaves_the_job_table_untouched(self, door: Any, starter: Starter) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")
        door.route_command.return_value = _result("stopped snapshot (pid 1234)\n", command="stop")

        host_backup.stop_run("AIPASS", "snapshot")

        assert host_backup.read_job(job["job"]) == job
        assert len(starter.pending) == 1


class TestReadJob:
    """GET /v1/backup/job's logic: running, done or failed, then forgotten."""

    def test_a_job_reads_running_until_its_lane_answers(self, door: Any) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")

        assert host_backup.read_job(job["job"]) == job

    def test_a_lane_that_exits_zero_is_done_with_its_output_as_summary(
        self, door: Any, starter: Starter, clock: FakeClock
    ) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")
        clock.advance(30)
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert read["state"] == "done"
        assert read["exit"] == 0
        assert read["summary"] == "snapshot=15414 files, 2.9 GB, 30.1s"
        assert read["error"] is None
        assert read["finished_at"] == "2026-10-16T07:30:30+00:00"

    def test_a_lane_that_exits_non_zero_is_failed_with_its_words_in_summary(self, door: Any, starter: Starter) -> None:
        door.route_command.return_value = _result("copied 3 files\n", exit_code=2, stderr="store is locked\n")
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert read["state"] == "failed"
        assert read["exit"] == 2
        assert read["summary"] == "copied 3 files\nstore is locked"
        assert read["error"] is None

    def test_a_lane_that_exits_130_is_stopped_with_its_words_in_summary(self, door: Any, starter: Starter) -> None:
        door.route_command.return_value = _result(
            "copied 1204 files\nstopped by request: 1,204 of 15,414 files, 310 MB\n", exit_code=130
        )
        job = host_backup.start_run("AIPASS", "drive_sync")
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert read["state"] == "stopped"
        assert read["exit"] == 130
        assert read["summary"] == "copied 1204 files\nstopped by request: 1,204 of 15,414 files, 310 MB"
        assert read["error"] is None

    @pytest.mark.parametrize("exit_code", [-15, 1])
    def test_a_killed_or_failing_lane_stays_failed_not_stopped(
        self, door: Any, starter: Starter, exit_code: int
    ) -> None:
        door.route_command.return_value = _result("copied 3 files\n", exit_code=exit_code)
        job = host_backup.start_run("AIPASS", "drive_sync")
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert (read["state"], read["exit"]) == ("failed", exit_code)

    def test_the_summary_is_the_last_600_characters_verbatim(self, door: Any, starter: Starter) -> None:
        output = "".join(f"line {n}\n" for n in range(400)) + "snapshot=15414 files"
        door.route_command.return_value = _result(output)
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        summary = host_backup.read_job(job["job"])["summary"]

        assert summary == output[-600:]
        assert len(summary) == 600

    def test_a_routing_error_mid_run_fails_the_job_with_its_sentence(self, door: Any, starter: Starter) -> None:
        door.route_command.side_effect = drone.RoutingError("@backup snapshot timed out after 1800s")
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert read["state"] == "failed"
        assert read["error"] == "@backup snapshot timed out after 1800s"
        assert read["exit"] is None

    def test_a_worker_that_breaks_fails_the_job_rather_than_holding_the_lane(self, door: Any, starter: Starter) -> None:
        door.route_command.side_effect = ValueError("unexpected")
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        read = host_backup.read_job(job["job"])

        assert read["state"] == "failed"
        assert read["error"] == host_backup.WORKER_DIED
        assert host_backup.start_run("AIPASS", "snapshot")["state"] == "running"

    def test_an_unknown_id_is_job_unknown(self, door: Any) -> None:
        with pytest.raises(host_backup.JobUnknown) as unknown:
            host_backup.read_job("b7f3c2")

        assert "/v1/backup/status" in str(unknown.value)

    def test_a_finished_job_is_kept_an_hour_then_dropped(self, door: Any, starter: Starter, clock: FakeClock) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")
        starter.run_all()

        clock.advance(3600)
        assert host_backup.read_job(job["job"])["state"] == "done"

        clock.advance(1)
        with pytest.raises(host_backup.JobUnknown):
            host_backup.read_job(job["job"])

    def test_a_running_job_is_never_dropped_by_the_hour(self, door: Any, clock: FakeClock) -> None:
        job = host_backup.start_run("AIPASS", "snapshot")

        clock.advance(7200)

        assert host_backup.read_job(job["job"])["state"] == "running"


class TestReadStatus:
    """GET /v1/backup/status's logic: @backup's JSON, passed through, plus this server's running jobs."""

    def test_status_passes_backup_through_with_project_root_and_running_added(self, door: Any, seated: Path) -> None:
        door.route_command.return_value = _result(json.dumps({**STATUS, "project": "AIPass", "root": "elsewhere"}))

        answered = host_backup.read_status("AIPASS")

        target, verb, argv = door.route_command.call_args.args
        assert (target, verb) == ("@backup", "status")
        assert Path(argv[0]) == seated.resolve()
        assert argv[1:] == ["--json"]
        assert Path(answered.pop("root")) == seated.resolve()
        assert answered == {**STATUS, "project": "AIPASS", "running": []}

    def test_sizes_adds_the_sizes_flag(self, door: Any) -> None:
        door.route_command.return_value = _result(json.dumps(STATUS))

        host_backup.read_status("AIPASS", sizes=True)

        assert door.route_command.call_args.args[2][1:] == ["--json", "--sizes"]

    def test_running_lists_only_this_projects_in_flight_jobs(self, door: Any, starter: Starter, census: Path) -> None:
        door.route_command.return_value = _result(json.dumps(STATUS))
        finished = host_backup.start_run("AIPASS", "all")
        starter.run_all()
        running = host_backup.start_run("AIPASS", "snapshot")
        host_backup.start_run("BAUD", "snapshot")

        answered = host_backup.read_status("aipass")

        assert finished["job"] != running["job"]
        assert answered["running"] == [{"job": running["job"], "lane": "snapshot", "started_at": running["started_at"]}]

    def test_a_status_with_no_running_key_falls_back_to_the_table_and_says_so(self, door: Any, backup_log: Any) -> None:
        door.route_command.return_value = _result(json.dumps(STATUS))
        job = host_backup.start_run("AIPASS", "snapshot")

        answered = host_backup.read_status("AIPASS")

        assert answered["running"] == [{"job": job["job"], "lane": "snapshot", "started_at": job["started_at"]}]
        said = [call.args[0] % call.args[1:] for call in backup_log.info.call_args_list]
        assert "[host_api] @backup status has no running list (older @backup); listing this server's jobs" in said

    def test_running_is_backups_list_entry_for_entry_with_this_servers_job_matched_on_verb(
        self, door: Any, census: Path
    ) -> None:
        full = host_backup.start_run("AIPASS", "all")
        host_backup.start_run("AIPASS", "snapshot")
        host_backup.start_run("BAUD", "drive_sync")
        progress = {"done": 300, "total": 15491, "failed": 0, "bytes_done": 1024, "bytes_total": None}
        since = "2026-10-16T07:30:00+00:00"
        entries = [
            {"verb": "all", "lane": "snapshot", "pid": 4242, "started_at": since, "progress": None},
            {"verb": "all", "lane": "drive_sync", "pid": 4242, "started_at": since, "progress": progress},
            {"verb": "drive_sync", "lane": "drive_sync", "pid": 175450, "started_at": since, "progress": None},
        ]
        door.route_command.return_value = _result(json.dumps({**STATUS, "running": entries}))

        answered = host_backup.read_status("AIPASS")

        assert answered["running"] == [
            {**entries[0], "job": full["job"]},
            {**entries[1], "job": full["job"]},
            {**entries[2], "job": None},
        ]

    def test_an_empty_running_list_stays_empty_even_with_a_job_in_flight(self, door: Any) -> None:
        host_backup.start_run("AIPASS", "snapshot")
        door.route_command.return_value = _result(json.dumps({**STATUS, "running": []}))

        assert host_backup.read_status("AIPASS")["running"] == []

    @pytest.mark.parametrize("running", [{"verb": "all"}, None, "snapshot", ["snapshot"]])
    def test_a_running_that_is_not_a_list_of_objects_is_unavailable(self, door: Any, running: Any) -> None:
        door.route_command.return_value = _result(json.dumps({**STATUS, "running": running}))

        with pytest.raises(host_backup.VerbUnavailable) as unavailable:
            host_backup.read_status("AIPASS")

        assert not isinstance(unavailable.value, host_backup.StatusJsonMissing)

    @pytest.mark.parametrize("stdout", ["╭─ Backup status ─╮", '{"runs": 1}{"runs": 2}', "[]", ""])
    def test_an_answer_that_is_not_one_json_object_is_status_json_missing(self, door: Any, stdout: str) -> None:
        door.route_command.return_value = _result(stdout)

        with pytest.raises(host_backup.StatusJsonMissing) as missing:
            host_backup.read_status("AIPASS")

        assert str(missing.value) == host_backup.STATUS_JSON_MISSING

    def test_a_non_zero_status_is_unavailable_not_a_missing_flag(self, door: Any) -> None:
        door.route_command.return_value = _result("", exit_code=1, stderr="root does not exist")

        with pytest.raises(host_backup.VerbUnavailable) as unavailable:
            host_backup.read_status("AIPASS")

        assert not isinstance(unavailable.value, host_backup.StatusJsonMissing)

    def test_a_routing_error_on_status_is_unavailable(self, door: Any) -> None:
        door.route_command.side_effect = drone.RoutingError("Branch not found: @backup")

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.read_status("AIPASS")

    def test_an_unknown_project_is_refused(self, door: Any, census: Path) -> None:
        with pytest.raises(host_backup.VerbRefused):
            host_backup.read_status("VERA")

        door.route_command.assert_not_called()


SCHEDULE = {
    "project": "aipass",
    "root": "/srv/aipass",
    "job_id": "backup-aipass",
    "scheduled": True,
    "on": True,
    "frequency": "daily",
    "time": "05:00",
    "weekday": None,
    "day": None,
    "steps": ["snapshot", "drive_sync"],
    "last_run": None,
    "last_status": None,
    "last_error": None,
    "next_run": "2026-11-16T05:00:00",
}

# @backup's error() as drone captures it: the sentence, then a hint Rich wraps at 80 columns.
NO_SCHEDULE_YET = (
    "❌ Schedule: No schedule for aipass yet: set a time first\n(daily HH:MM)\n"
    "   → Try: schedule <project_path|@name> [--json] | schedule <project_path|@name>\non|off|daily HH:MM\n"
)


def _schedule_calls(door: Any) -> List[List[str]]:
    return [c.args[2][1:] for c in door.route_command.call_args_list]


class TestReadSchedule:
    """GET /v1/backup/schedule's logic: @backup's schedule --json, passed through untouched."""

    def test_the_schedule_passes_through_with_every_key_unchanged(self, door: Any, seated: Path) -> None:
        door.route_command.return_value = _result(json.dumps(SCHEDULE))

        answered = host_backup.read_schedule("AIPASS")

        target, verb, argv = door.route_command.call_args.args
        assert (target, verb) == ("@backup", "schedule")
        assert Path(argv[0]) == seated.resolve()
        assert argv[1:] == ["--json"]
        assert door.route_command.call_args.kwargs == {"timeout": host_backup.SCHEDULE_TIMEOUT_SECONDS}
        assert answered == SCHEDULE

    def test_exit_2_with_a_sentence_is_refused_in_backups_words_without_the_hint(self, door: Any) -> None:
        door.route_command.return_value = _result(stderr=NO_SCHEDULE_YET, exit_code=2)

        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.read_schedule("AIPASS")

        assert str(refused.value) == "Schedule: No schedule for aipass yet: set a time first (daily HH:MM)"

    @pytest.mark.parametrize(("exit_code", "stderr"), [(2, ""), (2, "\n  \n"), (1, NO_SCHEDULE_YET)])
    def test_exit_2_with_no_sentence_or_any_other_exit_is_unavailable_never_refused(
        self, door: Any, exit_code: int, stderr: str
    ) -> None:
        door.route_command.return_value = _result(stderr=stderr, exit_code=exit_code)

        with pytest.raises(host_backup.VerbUnavailable) as failed:
            host_backup.read_schedule("AIPASS")

        assert not isinstance(failed.value, host_backup.VerbRefused)

    @pytest.mark.parametrize("stdout", ["", "Scheduled: daily 05:00", "[1, 2]"])
    def test_an_answer_that_is_not_one_json_object_is_unavailable(self, door: Any, stdout: str) -> None:
        door.route_command.return_value = _result(stdout)

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.read_schedule("AIPASS")

    def test_a_routing_error_is_unavailable(self, door: Any) -> None:
        door.route_command.side_effect = drone.RoutingError("Branch not found: @backup")

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.read_schedule("AIPASS")

    def test_an_unknown_project_is_refused_before_backup_is_asked(self, door: Any, census: Path) -> None:
        with pytest.raises(host_backup.VerbRefused):
            host_backup.read_schedule("VERA")

        door.route_command.assert_not_called()


class TestSetSchedule:
    """POST /v1/backup/schedule's logic: a frequency with its fields, then on or off, then the read-back."""

    def test_a_time_and_on_are_set_in_that_order_and_answered_as_read_back(self, door: Any, seated: Path) -> None:
        door.route_command.side_effect = [_result(), _result(), _result(json.dumps(SCHEDULE))]

        answered = host_backup.set_schedule("AIPASS", True, "daily", "05:00")

        assert _schedule_calls(door) == [["daily", "05:00"], ["on"], ["--json"]]
        assert all(Path(c.args[2][0]) == seated.resolve() for c in door.route_command.call_args_list)
        assert answered == SCHEDULE

    def test_off_alone_sends_off_and_no_time(self, door: Any) -> None:
        door.route_command.side_effect = [_result(), _result(json.dumps({**SCHEDULE, "on": False}))]

        answered = host_backup.set_schedule("AIPASS", False)

        assert door.route_command.call_count == 2
        assert _schedule_calls(door) == [["off"], ["--json"]]
        assert answered["on"] is False

    @pytest.mark.parametrize(
        ("fields", "words"),
        [
            ({"frequency": "daily", "time": "00:00"}, ["daily", "00:00"]),
            ({"frequency": "weekly", "weekday": "monday", "time": "05:00"}, ["weekly", "monday", "05:00"]),
            ({"frequency": "weekly", "weekday": "sunday", "time": "23:59"}, ["weekly", "sunday", "23:59"]),
            ({"frequency": "monthly", "day": 1, "time": "05:00"}, ["monthly", "1", "05:00"]),
            ({"frequency": "monthly", "day": 31, "time": "05:00"}, ["monthly", "31", "05:00"]),
        ],
    )
    def test_each_frequency_sends_backups_set_form_in_its_word_order(
        self, door: Any, fields: dict, words: List[str]
    ) -> None:
        door.route_command.side_effect = [_result(), _result(json.dumps(SCHEDULE))]

        host_backup.set_schedule("AIPASS", **fields)

        assert door.route_command.call_count == 2
        assert _schedule_calls(door) == [words, ["--json"]]

    @pytest.mark.parametrize(
        ("fields", "words"),
        [
            ({}, "Nothing to set"),
            (
                {"frequency": "yearly", "time": "05:00"},
                "Unknown frequency 'yearly' — the schedule takes daily, weekly, monthly",
            ),
            ({"time": "05:00"}, "A frequency is required with its fields"),
            ({"on": True, "weekday": "monday"}, "A frequency is required with its fields"),
            ({"frequency": "daily"}, "Not a 24-hour HH:MM time: None"),
            ({"frequency": "daily", "time": "5:00"}, "Not a 24-hour HH:MM time: '5:00'"),
            ({"frequency": "daily", "time": "24:00"}, "Not a 24-hour HH:MM time: '24:00'"),
            ({"frequency": "daily", "time": "05:00x"}, "Not a 24-hour HH:MM time: '05:00x'"),
            ({"frequency": "daily", "time": "05:00", "weekday": "monday"}, "daily takes no weekday"),
            ({"frequency": "daily", "time": "05:00", "day": 1}, "daily takes no day"),
            ({"frequency": "weekly", "weekday": "monday", "time": "05:00", "day": 1}, "weekly takes no day"),
            ({"frequency": "monthly", "day": 1, "time": "05:00", "weekday": "monday"}, "monthly takes no weekday"),
            ({"frequency": "weekly", "time": "05:00"}, "Not a weekday: None"),
            ({"frequency": "weekly", "weekday": "Monday", "time": "05:00"}, "Not a weekday: 'Monday'"),
            ({"frequency": "weekly", "weekday": "mon", "time": "05:00"}, "Not a weekday: 'mon'"),
            ({"frequency": "weekly", "weekday": "monday"}, "Not a 24-hour HH:MM time: None"),
            ({"frequency": "monthly", "time": "05:00"}, "Not a day of the month: None"),
            ({"frequency": "monthly", "day": 0, "time": "05:00"}, "Not a day of the month: 0"),
            ({"frequency": "monthly", "day": 32, "time": "05:00"}, "Not a day of the month: 32"),
            ({"frequency": "monthly", "day": "5", "time": "05:00"}, "Not a day of the month: '5'"),
            ({"frequency": "monthly", "day": True, "time": "05:00"}, "Not a day of the month: True"),
            ({"frequency": "monthly", "day": 5.0, "time": "05:00"}, "Not a day of the month: 5.0"),
            ({"frequency": "monthly", "day": 5}, "Not a 24-hour HH:MM time: None"),
            ({"on": "true"}, "on is true or false, not 'true'"),
        ],
    )
    def test_a_body_backup_would_refuse_is_refused_here_and_nothing_is_written(
        self, door: Any, fields: dict, words: str
    ) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.set_schedule("AIPASS", **fields)

        assert words in str(refused.value)
        door.route_command.assert_not_called()

    def test_backups_refusal_stops_the_set_with_its_sentence_and_reads_nothing_back(self, door: Any) -> None:
        door.route_command.return_value = _result(stderr=NO_SCHEDULE_YET, exit_code=2)

        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.set_schedule("AIPASS", True)

        assert "No schedule for aipass yet" in str(refused.value)
        assert _schedule_calls(door) == [["on"]]


@pytest.mark.skipif(not host_server.is_available(), reason="the [host] extra is not installed")
class TestTheScheduleRoutesThroughTheRealApp:
    """GET and POST /v1/backup/schedule, wired: scopes, the 400 envelope, the read-back."""

    @pytest.fixture
    def api(self, store: Path, door: Any, host_app: Any):
        from fastapi.testclient import TestClient

        with patch(PATCH_SERVER_LOGGER):
            _, read_raw = host_tokens.issue_token("phone", "read")
            _, operate_raw = host_tokens.issue_token("ops-phone", "operate")
            yield (
                TestClient(host_app, raise_server_exceptions=False),
                {"Authorization": f"Bearer {read_raw}"},
                {"Authorization": f"Bearer {operate_raw}"},
            )

    def test_a_read_token_reads_the_schedule_unchanged(self, api: Any, door: Any) -> None:
        client, read, _ = api
        door.route_command.return_value = _result(json.dumps(SCHEDULE))

        response = client.get("/v1/backup/schedule", params={"project": "AIPASS"}, headers=read)

        assert (response.status_code, response.json()) == (200, SCHEDULE)

    def test_a_read_token_is_refused_on_set_and_backup_is_never_asked(self, api: Any, door: Any) -> None:
        client, read, _ = api

        response = client.post("/v1/backup/schedule", json={"project": "AIPASS", "on": True}, headers=read)

        assert response.status_code == 403
        door.route_command.assert_not_called()

    def test_a_set_answers_200_with_the_schedule_read_back(self, api: Any, door: Any) -> None:
        client, _, operate = api
        door.route_command.side_effect = [_result(), _result(), _result(json.dumps(SCHEDULE))]
        body = {"project": "AIPASS", "frequency": "daily", "time": "05:00", "on": True}

        response = client.post("/v1/backup/schedule", json=body, headers=operate)

        assert (response.status_code, response.json()) == (200, SCHEDULE)
        assert door.route_command.call_count == 3
        assert _schedule_calls(door) == [["daily", "05:00"], ["on"], ["--json"]]

    def test_a_refusal_is_400_verb_refused_with_its_sentence(self, api: Any, door: Any) -> None:
        client, _, operate = api
        door.route_command.return_value = _result(stderr=NO_SCHEDULE_YET, exit_code=2)

        response = client.post("/v1/backup/schedule", json={"project": "AIPASS", "on": True}, headers=operate)

        assert response.status_code == 400
        assert response.json()["error"]["code"] == "verb_refused"
        assert "No schedule for aipass yet" in response.json()["error"]["message"]


class TestTheDoorOwnsNoMechanism:
    """backup.py reaches @backup only through drone: no process, signal or shell machinery of its own."""

    def test_backup_holds_nothing_from_a_process_or_signal_module(self) -> None:
        owners = set()
        for value in vars(host_backup).values():
            if isinstance(value, types.ModuleType):
                owners.add(value.__name__.split(".")[0])
            else:
                owners.add(str(getattr(value, "__module__", None) or type(value).__module__).split(".")[0])

        assert "aipass" in owners
        # os's process calls report their owner as posix or nt, by platform.
        banned = {"subprocess", "os", "posix", "nt", "pty", "signal", "multiprocessing", "asyncio", "shutil"}
        assert owners.isdisjoint(banned)


class TestStartWorker:
    """The table's default starter: a daemon thread, joined here."""

    def test_the_worker_runs_its_target_on_a_daemon_thread(self) -> None:
        ran = threading.Event()

        worker = host_backup.start_worker(ran.set, ())
        worker.join(timeout=5)

        assert ran.is_set()
        assert worker.daemon
        assert not worker.is_alive()

    def test_the_alarm_fires_once_on_a_daemon_timer_and_a_cancel_holds_it(self) -> None:
        fired = threading.Event()
        held = threading.Event()

        alarm = host_backup.start_alarm(0.01, fired.set)
        alarm.join(timeout=5)
        cancelled = host_backup.start_alarm(5, held.set)
        cancelled.cancel()
        cancelled.join(timeout=5)

        assert fired.is_set() and alarm.daemon
        assert not held.is_set()
