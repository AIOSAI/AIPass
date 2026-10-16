# =================== AIPass ====================
# Name: test_host_backup.py
# Description: Tests for the host API's backup door — runs, cancels, jobs and status (DPLAN-0411, DPLAN-0412)
# Version: 1.1.0
# Created: 2026-10-16
# Modified: 2026-10-16
# =============================================

"""Tests for apps/handlers/host/backup.py."""

# A file of its own for this build (DPLAN-0411): the job table, the lane argv,
# the hour and the status pass-through are the handler's logic and are reached
# through its public functions. The routes' wiring is test_host_api_routes.py's.
# @backup is never run: drone's router is replaced at this handler's reference
# to it, and its status --json is always an answer written here.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that backup.py parses and imports
# seedgo: no-test-needed(external) — route_command, patched at backup.py's reference so no lane runs
# seedgo: no-test-needed(covered_elsewhere) — answer(), tests/test_host_api_routes.py

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

PATCH_BACKUP_DRONE = "aipass.api.apps.handlers.host.backup.drone"
PATCH_BACKUP_LOGGER = "aipass.api.apps.handlers.host.backup.logger"
PATCH_BACKUP_JSON = "aipass.api.apps.handlers.host.backup.json_handler"
PATCH_DENIALS_LOGGER = "aipass.api.apps.handlers.host.denials.logger"
PATCH_DENIALS_JSON = "aipass.api.apps.handlers.host.denials.json_handler"

STATUS = {
    "registered": True,
    "mode": "snapshot",
    "drive_sync": False,
    "runs": 64,
    "lanes": {
        "snapshot": {"last": "2026-10-16T07:09:50+00:00", "files": 15414},
        "versioned": {"last": None, "files": None},
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


def _result(stdout: str = "", exit_code: int = 0, stderr: str = "", command: str = "snapshot") -> Any:
    return drone.CommandResult(stdout=stdout, stderr=stderr, exit_code=exit_code, branch="backup", command=command)


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def starter() -> Starter:
    return Starter()


@pytest.fixture
def door(seated: Path, clock: FakeClock, starter: Starter, monkeypatch: Any):
    """A fresh job table, a hermetic seat, and drone's router replaced at the handler's reference."""
    monkeypatch.setattr(host_backup, "JOBS", host_backup.JobTable(clock=clock, start=starter))
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
        ("lane", "flags"),
        [("snapshot", ["--quiet"]), ("versioned", ["--quiet"]), ("all", ["--quiet"]), ("drive_sync", [])],
    )
    def test_each_lane_runs_its_contract_argv_and_drive_sync_takes_no_quiet(
        self, door: Any, starter: Starter, seated: Path, lane: str, flags: List[str]
    ) -> None:
        host_backup.start_run("AIPASS", lane)
        starter.run_all()

        target, verb, argv = door.route_command.call_args.args
        assert (target, verb) == ("@backup", lane)
        assert Path(argv[0]) == seated.resolve()
        assert argv[1:] == flags
        assert door.route_command.call_args.kwargs == {"timeout": 1800}

    def test_a_second_run_of_the_same_lane_is_refused_with_the_contract_sentence(
        self, door: Any, starter: Starter
    ) -> None:
        first = host_backup.start_run("AIPASS", "snapshot")

        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("AIPASS", "snapshot")

        assert str(refused.value) == f"snapshot already running for AIPASS since {first['started_at']}"
        assert len(starter.pending) == 1

    def test_the_seat_in_another_case_is_the_same_slot(self, door: Any) -> None:
        host_backup.start_run("AIPASS", "versioned")

        with pytest.raises(host_backup.VerbRefused):
            host_backup.start_run("aipass", "versioned")

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

    @pytest.mark.parametrize("lane", ["", "nightly", "SNAPSHOT"])
    def test_a_missing_or_unknown_lane_is_refused_before_anything_runs(
        self, door: Any, starter: Starter, lane: str
    ) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.start_run("AIPASS", lane)

        assert "snapshot, versioned, all, drive_sync" in str(refused.value)
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
        ("stdout", "stderr"),
        [("drive_sync is not running for AIPass\n", ""), ("", "drive_sync is not running for AIPass\n")],
    )
    def test_a_stop_that_exits_non_zero_is_not_running_with_its_line_verbatim(
        self, door: Any, stdout: str, stderr: str
    ) -> None:
        door.route_command.return_value = _result(stdout, exit_code=1, stderr=stderr, command="stop")

        with pytest.raises(host_backup.NotRunning) as not_running:
            host_backup.stop_run("AIPASS", "drive_sync")

        assert str(not_running.value) == "drive_sync is not running for AIPass"

    def test_backup_unreachable_on_stop_is_unavailable(self, door: Any) -> None:
        door.route_command.side_effect = drone.RoutingError("Branch not found: @backup")

        with pytest.raises(host_backup.VerbUnavailable):
            host_backup.stop_run("AIPASS", "snapshot")

    @pytest.mark.parametrize("lane", ["", "nightly"])
    def test_a_missing_or_unknown_lane_is_refused_before_backup_is_asked(self, door: Any, lane: str) -> None:
        with pytest.raises(host_backup.VerbRefused) as refused:
            host_backup.stop_run("AIPASS", lane)

        assert "snapshot, versioned, all, drive_sync" in str(refused.value)
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
        finished = host_backup.start_run("AIPASS", "versioned")
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
            {"verb": "all", "lane": "versioned", "pid": 4242, "started_at": since, "progress": progress},
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
