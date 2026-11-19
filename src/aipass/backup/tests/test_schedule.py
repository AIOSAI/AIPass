# =================== AIPass ====================
# Name: test_schedule.py
# Description: Tests for the schedule verb and the @daemon job it writes, and for register --remove dropping it
# Version: 1.0.0
# Created: 2026-11-15
# Modified: 2026-11-17
# =============================================

"""Tests for apps/modules/schedule.py and the handlers/schedule/jobs.py job it writes."""

# register --remove is pinned here for one behaviour only, removing the project's job:
# that job is this verb's, and the schedule file is the thing asserted. The help gate,
# introspection and COMMANDS row are pinned in test_cli_routing.py with every verb.
#
# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(stdlib) — calendar.monthrange's month lengths, which the monthly clamp rides

import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Iterator
from unittest.mock import patch

import pytest

import aipass.drone as drone
from aipass.backup.apps import backup as entry
from aipass.backup.apps.handlers.project import registry
from aipass.backup.apps.modules import schedule

DAEMON_ROW = {"owner": "@backup", "id": "backup-proj", "last_run": "2026-11-15T05:00:40", "last_status": "success"}


def _main(*args: str) -> int:
    """Run the real entry point with argv ``backup <args>``."""
    with patch("sys.argv", ["backup", *args]):
        return entry.main()


def _jobs(schedule_file: Path) -> list[dict]:
    return json.loads(schedule_file.read_text(encoding="utf-8"))["jobs"]


def _view(capsys: pytest.CaptureFixture[str]) -> dict:
    """The schedule --json object for @proj; the exit code is part of the claim."""
    capsys.readouterr()
    code = _main("schedule", "@proj", "--json")
    assert code == 0
    return json.loads(capsys.readouterr().out)


@pytest.fixture
def project(tmp_path: Path, tmp_registry: Path) -> Path:
    """A registered project named proj, drive_sync off."""
    root = tmp_path / "proj"
    (root / ".backup").mkdir(parents=True)
    (root / ".backup" / "config.json").write_text(json.dumps({"drive_sync": False}), encoding="utf-8")
    registry.register_project("proj", str(root))
    return root


@pytest.fixture
def daemon() -> Iterator[SimpleNamespace]:
    """@daemon's queue door: a test sets ``answer`` to what route_command returns, or raises."""
    door = SimpleNamespace(answer=SimpleNamespace(exit_code=0, stdout=json.dumps({"jobs": [DAEMON_ROW]})), calls=[])

    def route(target: str, command: str, args: list, timeout: int) -> SimpleNamespace:
        door.calls.append((target, command, args))
        if isinstance(door.answer, Exception):
            raise door.answer
        return door.answer

    # patch, not monkeypatch.setattr: its undo would store the name on drone's package for the whole run.
    with patch.object(schedule.drone, "route_command", route):
        yield door


class TestSetRefusesBadValues:
    """A bad frequency, weekday, day or time is refused on stderr, exit 2, and nothing is written."""

    @pytest.mark.parametrize(
        "words",
        [
            ["daily", "5:00"],
            ["daily", "24:00"],
            ["daily", "05:60"],
            ["weekly", "mon", "05:00"],
            ["weekly", "Monday", "05:00"],
            ["weekly", "monday"],
            ["monthly", "0", "05:00"],
            ["monthly", "32", "05:00"],
            ["monthly", "07", "05:00"],
            ["monthly", "1", "25:00"],
            ["hourly", "05:00"],
            ["daily", "05:00", "extra"],
        ],
    )
    def test_a_bad_set_form_exits_2_naming_it_and_writes_nothing(
        self, words: list[str], project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = schedule_file.read_bytes()

        code = _main("schedule", "@proj", *words)

        assert code == 2
        assert words[-1] in capsys.readouterr().err
        assert schedule_file.read_bytes() == before

    def test_on_before_any_schedule_is_refused_and_writes_nothing(
        self, project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = schedule_file.read_bytes()

        code = _main("schedule", "@proj", "on")

        assert code == 2
        assert "No schedule for proj yet" in capsys.readouterr().err
        assert schedule_file.read_bytes() == before


class TestANewScheduleStartsOff:
    """Choosing when a project runs never turns it on; the job runs the all lane and leaves other jobs alone."""

    def test_a_new_daily_job_is_off_and_runs_all_quiet_for_the_project(
        self, project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        others = _jobs(schedule_file)

        code = _main("schedule", "@proj", "daily", "05:00")

        assert code == 0
        assert "proj: daily 05:00, off" in capsys.readouterr().out
        *other, job = _jobs(schedule_file)
        assert other == others
        assert job["id"] == "backup-proj"
        assert job["enabled"] is False
        assert job["schedule"] == {"type": "daily", "time": "05:00"}
        assert job["command"] == "drone @backup all @proj --quiet"
        assert job["timeout_seconds"] == 28800
        assert job["notify"] == {"email": "@devpulse"}


class TestRoundTrips:
    """Each frequency set and turned on reads back in --json with a next_run on a day it runs."""

    @pytest.mark.parametrize(
        ("words", "fields", "written"),
        [
            (["daily", "05:00"], {"frequency": "daily", "weekday": None, "day": None}, {"type": "daily"}),
            (
                ["weekly", "monday", "05:00"],
                {"frequency": "weekly", "weekday": "monday", "day": None},
                {"type": "weekly", "weekday": "monday"},
            ),
            (
                ["monthly", "31", "05:00"],
                {"frequency": "monthly", "weekday": None, "day": 31},
                {"type": "monthly", "day": 31},
            ),
        ],
    )
    def test_set_on_then_read_returns_the_schedule(
        self,
        words: list[str],
        fields: dict,
        written: dict,
        project: Path,
        schedule_file: Path,
        daemon: SimpleNamespace,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        set_code = _main("schedule", "@proj", *words)
        on_code = _main("schedule", "@proj", "on")
        view = _view(capsys)

        assert (set_code, on_code) == (0, 0)
        assert _jobs(schedule_file)[1]["schedule"] == {**written, "time": "05:00"}
        assert view == {
            "project": "proj",
            "root": str(project),
            "job_id": "backup-proj",
            "scheduled": True,
            "on": True,
            "time": "05:00",
            **fields,
            "steps": ["snapshot"],
            "last_run": "2026-11-15T05:00:40",
            "last_status": "success",
            "last_error": None,
            "next_run": view["next_run"],
        }
        due = datetime.datetime.fromisoformat(view["next_run"])
        assert due > datetime.datetime.now()
        assert (due.hour, due.minute) == (5, 0)
        assert daemon.calls == [("@daemon", "queue", ["--json"])]

    def test_switching_frequency_keeps_on(
        self, project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main("schedule", "@proj", "daily", "05:00")
        _main("schedule", "@proj", "on")

        code = _main("schedule", "@proj", "monthly", "1", "06:30")

        assert code == 0
        assert "proj: monthly day 1 06:30, on" in capsys.readouterr().out
        assert _jobs(schedule_file)[1]["enabled"] is True

    def test_off_keeps_the_schedule_and_has_no_next_run(
        self, project: Path, daemon: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main("schedule", "@proj", "weekly", "friday", "22:00")

        view = _view(capsys)

        assert (view["scheduled"], view["on"], view["weekday"], view["next_run"]) == (True, False, "friday", None)

    def test_a_project_with_no_schedule_reads_as_unscheduled_without_asking_daemon(
        self, project: Path, daemon: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        view = _view(capsys)

        assert (view["scheduled"], view["on"], view["frequency"], view["next_run"]) == (False, False, None, None)
        assert daemon.calls == []


class TestNextRun:
    """next_run is the first run after now on a day the schedule runs."""

    NOW = datetime.datetime(2026, 11, 15, 23, 0)  # a Sunday

    @pytest.mark.parametrize(
        ("parsed", "expected"),
        [
            ({"frequency": "daily", "time": "05:00", "weekday": None, "day": None}, "2026-11-16T05:00:00"),
            ({"frequency": "daily", "time": "23:30", "weekday": None, "day": None}, "2026-11-15T23:30:00"),
            ({"frequency": "weekly", "time": "05:00", "weekday": "sunday", "day": None}, "2026-11-22T05:00:00"),
            ({"frequency": "weekly", "time": "05:00", "weekday": "monday", "day": None}, "2026-11-16T05:00:00"),
            ({"frequency": "monthly", "time": "05:00", "weekday": None, "day": 31}, "2026-11-30T05:00:00"),
            ({"frequency": "monthly", "time": "05:00", "weekday": None, "day": 15}, "2026-12-15T05:00:00"),
        ],
    )
    def test_the_next_run_lands_on_the_right_day(self, parsed: dict, expected: str) -> None:
        assert schedule.next_run(parsed, now=self.NOW) == expected

    def test_a_day_past_february_runs_on_its_last_day(self) -> None:
        parsed = {"frequency": "monthly", "time": "05:00", "weekday": None, "day": 31}

        assert schedule.next_run(parsed, now=datetime.datetime(2027, 2, 1)) == "2027-02-28T05:00:00"


class TestStepsFollowDriveSync:
    """steps names what a run does, in order: Drive only when the project's drive_sync is on."""

    @pytest.mark.parametrize(("drive_sync", "steps"), [(True, ["snapshot", "drive_sync"]), (False, ["snapshot"])])
    def test_steps_read_the_project_setting(
        self,
        drive_sync: bool,
        steps: list[str],
        project: Path,
        daemon: SimpleNamespace,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        (project / ".backup" / "config.json").write_text(json.dumps({"drive_sync": drive_sync}), encoding="utf-8")
        _main("schedule", "@proj", "daily", "05:00")

        assert _view(capsys)["steps"] == steps


class TestRegisteredOnly:
    """A scheduled run is 'all @name', so a project the registry does not name is refused."""

    def test_an_unregistered_directory_is_refused_and_nothing_is_written(
        self, tmp_path: Path, tmp_registry: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        before = schedule_file.read_bytes()

        code = _main("schedule", str(tmp_path), "daily", "05:00")

        assert code == 2
        assert "is not registered" in capsys.readouterr().err
        assert schedule_file.read_bytes() == before


class TestDaemonErrors:
    """When @daemon's queue cannot answer for the job, the read is an error with no JSON."""

    @pytest.mark.parametrize(
        ("answer", "named"),
        [
            (drone.RoutingError("no route"), "unreachable"),
            (SimpleNamespace(exit_code=1, stdout=""), "exited 1"),
            (SimpleNamespace(exit_code=0, stdout="not json"), "not JSON"),
            (SimpleNamespace(exit_code=0, stdout=json.dumps({"jobs": [], "refused": ["backup-proj: bad"]})), "refuses"),
        ],
    )
    def test_a_daemon_failure_exits_2_naming_it_with_nothing_on_stdout(
        self, answer: object, named: str, project: Path, daemon: SimpleNamespace, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _main("schedule", "@proj", "daily", "05:00")
        daemon.answer = answer
        capsys.readouterr()

        code = _main("schedule", "@proj", "--json")

        captured = capsys.readouterr()
        assert code == 2
        assert named in captured.err
        assert captured.out == ""

    @pytest.mark.parametrize(
        "written",
        [
            {"type": "interval", "interval_minutes": 5},
            {"type": "monthly", "day": 32, "time": "05:00"},
            {"type": "monthly", "day": 0, "time": "05:00"},
            {"type": "monthly", "day": "5", "time": "05:00"},
            {"type": "weekly", "weekday": "mon", "time": "05:00"},
        ],
    )
    def test_a_job_in_a_shape_this_verb_does_not_write_is_an_error(
        self,
        written: dict,
        project: Path,
        schedule_file: Path,
        daemon: SimpleNamespace,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        jobs = _jobs(schedule_file) + [{"id": "backup-proj", "enabled": True, "schedule": written}]
        schedule_file.write_text(json.dumps({"jobs": jobs}), encoding="utf-8")

        code = _main("schedule", "@proj", "--json")

        assert code == 2
        assert "does not write" in capsys.readouterr().err


class TestUnregisterRemovesTheJob:
    """register --remove drops the project's job, so none is left to fail each night."""

    def test_removing_a_scheduled_project_removes_its_job_and_keeps_the_others(
        self, project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        others = _jobs(schedule_file)
        _main("schedule", "@proj", "daily", "05:00")

        code = _main("register", "--remove", "proj")

        assert code == 0
        assert "its scheduled backup job removed" in capsys.readouterr().out
        assert _jobs(schedule_file) == others
        assert registry.lookup_project("proj") is None

    def test_an_unreadable_schedule_file_keeps_the_project_registered(
        self, project: Path, schedule_file: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        schedule_file.write_text("{", encoding="utf-8")

        code = _main("register", "--remove", "proj")

        assert code == 2
        assert "could not be removed" in capsys.readouterr().err
        assert registry.lookup_project("proj") == str(project)
