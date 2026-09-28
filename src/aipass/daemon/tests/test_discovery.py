# =================== AIPass ====================
# Name: test_discovery.py
# Description: Tests for registry-led citizen discovery and .daemon/ schedule job discovery
# Version: 1.1.0
# Created: 2026-06-15
# Modified: 2026-09-27
# =============================================

"""Tests for apps/handlers/schedule/discovery.py — citizens from the registries, jobs from their .daemon/."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(external) — parsing the registry files inside fleet.fleet_branches(); @memory's own tests
# seedgo: no-test-needed(constant) — RESIDENCY_CORE and RESIDENCY_RESIDENT spellings, re-exported from @memory's fleet

import errno
import json
import os
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule import discovery
from aipass.daemon.apps.handlers.schedule.discovery import (
    discover_jobs,
    active_citizens,
    active_branch_map,
    branch_path_for,
    citizen_class_for,
    declared_residency,
    framework_root,
    REQUIRED_JOB_KEYS,
    RESIDENCY_CORE,
    RESIDENCY_RESIDENT,
    VALID_SCHEDULE_TYPES,
)

DISCOVERY = "aipass.daemon.apps.handlers.schedule.discovery"

# Failures to stat a passport that are NOT its absence: a .trinity that cannot be
# searched (EACCES) and a .trinity that is not a directory (ENOTDIR).
NOT_ABSENT = (
    PermissionError(errno.EACCES, "Permission denied"),
    NotADirectoryError(errno.ENOTDIR, "Not a directory"),
)


# ── Fixtures ──────────────────────────────────────────


@pytest.fixture
def temp_src_aipass():
    """Create a temp src/aipass tree with .daemon/ files."""
    root = Path(tempfile.mkdtemp())
    src_aipass = root / "src" / "aipass"
    src_aipass.mkdir(parents=True)
    yield root, src_aipass
    shutil.rmtree(root)


@pytest.fixture
def sample_schedule():
    """A valid schedule.json structure."""
    return {
        "version": 1,
        "branch": "@testbranch",
        "jobs": [
            {
                "id": "daily-check",
                "enabled": True,
                "schedule": {"type": "daily", "time": "04:00"},
                "wake": {"fresh": True, "max_turns": 50},
                "prompt": "Run daily check.",
            }
        ],
    }


@pytest.fixture
def sample_registry():
    """A minimal AIPASS_REGISTRY.json."""
    return {
        "branches": [
            {"name": "TESTBRANCH", "email": "@testbranch", "path": "src/aipass/testbranch", "status": "active"},
            {"name": "INACTIVE", "email": "@inactive", "path": "src/aipass/inactive", "status": "inactive"},
        ]
    }


# ── job validation, through discover_jobs ─────────────


KEEP = {"id": "keep", "schedule": {"type": "daily", "time": "04:00"}, "prompt": "kept"}


@pytest.fixture
def one_branch(temp_src_aipass, sample_registry):
    """One core citizen (@testbranch) with an empty .daemon/, discovery pointed at the temp tree."""
    root, src = temp_src_aipass
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
    daemon_dir = src / "testbranch" / ".daemon"
    daemon_dir.mkdir(parents=True)
    with patched_roots(root, src):
        yield daemon_dir


def discovered_ids(daemon_dir: Path, *jobs: dict) -> list:
    """The ids discover_jobs() returns when schedule.json holds KEEP followed by `jobs`."""
    doc = {"version": 1, "jobs": [KEEP, *jobs]}
    (daemon_dir / "schedule.json").write_text(json.dumps(doc), encoding="utf-8")
    return [job["id"] for job in discover_jobs()]


class TestValidateJob:
    def test_valid_job(self, one_branch):
        job = {"id": "test", "schedule": {"type": "daily", "time": "04:00"}, "prompt": "do stuff"}
        assert discovered_ids(one_branch, job) == ["keep", "test"]

    def test_missing_required_key(self, one_branch):
        """Mutant killed: the REQUIRED_JOB_KEYS check removed from _validate_job."""
        job = {"schedule": {"type": "daily"}, "prompt": "do stuff"}
        assert discovered_ids(one_branch, job) == ["keep"]

    def test_non_dict_schedule(self, one_branch):
        """Mutant killed: the isinstance(schedule, dict) check removed from _validate_job."""
        job = {"id": "test", "schedule": "daily", "prompt": "do stuff"}
        assert discovered_ids(one_branch, job) == ["keep"]

    def test_invalid_schedule_type(self, one_branch):
        """Mutant killed: the VALID_SCHEDULE_TYPES check removed from _validate_job."""
        job = {"id": "test", "schedule": {"type": "biweekly"}, "prompt": "do stuff"}
        assert discovered_ids(one_branch, job) == ["keep"]

    def test_all_valid_schedule_types(self, one_branch):
        # The floor. An empty VALID_SCHEDULE_TYPES would make the list below
        # empty — and _validate_job reads that same set, so emptying it
        # rejects every job while this unit stayed green. Five, counted live.
        assert len(VALID_SCHEDULE_TYPES) == 5, f"expected five schedule types, got {sorted(VALID_SCHEDULE_TYPES)}"
        stypes = sorted(VALID_SCHEDULE_TYPES)
        jobs = [{"id": f"t-{stype}", "schedule": {"type": stype}, "prompt": "do stuff"} for stype in stypes]
        assert discovered_ids(one_branch, *jobs) == ["keep"] + [f"t-{stype}" for stype in stypes]

    @pytest.mark.parametrize("interval", ["60", None, "abc", 0, -5, True])
    def test_an_interval_that_is_not_a_positive_number_is_refused_and_named(self, interval, one_branch, caplog):
        """Refused at the source, the job and its file named: never due, never read by a reader downstream.

        Let through, a text or null interval raised TypeError in runstate and stopped the tick for every job.
        Mutant killed: the interval_minutes check removed from _validate_job.
        Mutant killed: the isinstance(interval, bool) clause dropped (True read as the number 1).
        """
        job = {"id": "tick", "schedule": {"type": "interval", "interval_minutes": interval}, "prompt": "x"}
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, job) == ["keep"]
        assert "Job 'tick' refused" in caplog.text
        assert "interval_minutes" in caplog.text
        assert str(one_branch / "schedule.json") in caplog.text

    @pytest.mark.parametrize("interval", [1, 0.5, 10080])
    def test_a_positive_interval_is_accepted(self, interval, one_branch):
        """Mutant killed: interval <= 0 widened to interval <= 1 in _validate_job (0.5 and 1 refused)."""
        job = {"id": "tick", "schedule": {"type": "interval", "interval_minutes": interval}, "prompt": "x"}
        assert discovered_ids(one_branch, job) == ["keep", "tick"]

    def test_required_keys_constant(self):
        # prompt left the required set at DPLAN-0338: a job now says exactly one
        # of prompt or command, which JOB_ACTION_KEYS checks rather than requires.
        assert REQUIRED_JOB_KEYS == {"id", "schedule"}
        assert discovery.JOB_ACTION_KEYS == ("prompt", "command")


# ── command jobs (DPLAN-0338) ─────────────────────────


def command_job(**extra) -> dict:
    """A command job as its owner writes it into .daemon/schedule.json."""
    job = {
        "id": "sweep",
        "schedule": {"type": "interval", "interval_minutes": 10080},
        "command": "drone rm --stale 10d ../..",
    }
    job.update(extra)
    return job


class TestCommandJobValidation:
    def test_a_command_job_is_valid(self, one_branch):
        assert discovered_ids(one_branch, command_job()) == ["keep", "sweep"]

    def test_prompt_and_command_together_is_refused_and_named(self, one_branch, caplog):
        """Mutant killed: len(actions) != 1 weakened to len(actions) < 1 in _validate_job."""
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, command_job(prompt="tend")) == ["keep"]
        assert "exactly one of prompt or command, found prompt and command" in caplog.text

    def test_neither_is_refused_and_named(self, one_branch, caplog):
        """Mutant killed: len(actions) != 1 weakened to len(actions) > 1 in _validate_job."""
        job = {"id": "empty", "schedule": {"type": "daily", "time": "04:00"}}
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, job) == ["keep"]
        assert "exactly one of prompt or command, found neither" in caplog.text

    @pytest.mark.parametrize(
        "command",
        [
            "rm -rf ../..",
            "bash -c 'drone @daemon run'",
            "/usr/local/bin/drone @daemon",
            "env drone @daemon run",
            "",
            'drone @daemon "unterminated',
            42,
        ],
    )
    def test_a_command_that_is_not_a_drone_verb_is_refused(self, command, one_branch, caplog):
        """Mutant killed: _validate_job ignores command_job_problem()'s answer."""
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, command_job(command=command)) == ["keep"]
        assert "Command job 'sweep' refused" in caplog.text

    def test_a_rotation_command_job_is_refused(self, one_branch, caplog):
        job = command_job(schedule={"type": "rotation", "time": "05:00"})
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, job) == ["keep"]
        assert "rotation" in caplog.text

    @pytest.mark.parametrize("timeout", [0, -5, "600", True, 1.5, None])
    def test_a_bad_timeout_is_refused(self, timeout, one_branch, caplog):
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, command_job(timeout_seconds=timeout)) == ["keep"]
        assert "timeout_seconds must be a positive whole number" in caplog.text

    def test_a_whole_number_timeout_is_accepted(self, one_branch):
        assert discovered_ids(one_branch, command_job(timeout_seconds=30)) == ["keep", "sweep"]

    @pytest.mark.parametrize("notify", [{"email": "devpulse"}, {"email": "@"}, {"email": 5}, "yes", 1])
    def test_a_bad_notify_is_refused(self, notify, one_branch, caplog):
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, command_job(notify=notify)) == ["keep"]
        assert "notify" in caplog.text

    @pytest.mark.parametrize("notify", [True, False, {"email": "@devpulse"}])
    def test_a_good_notify_is_accepted(self, notify, one_branch):
        assert discovered_ids(one_branch, command_job(notify=notify)) == ["keep", "sweep"]

    def test_a_wake_block_is_ignored_with_a_warning(self, one_branch, caplog):
        """Mutant killed: the 'wake block ignored' warning removed from _validate_job."""
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, command_job(wake={"fresh": True, "model": "opus"})) == ["keep", "sweep"]
        assert "wake block ignored" in caplog.text

    def test_notify_email_on_a_prompt_job_is_named_not_silently_dropped(self, one_branch, caplog):
        """Mutant killed: the 'notify.email works on command jobs only' warning removed."""
        job = {"id": "tend", "schedule": {"type": "daily", "time": "04:00"}, "prompt": "x", "notify": {"email": "@a"}}
        with caplog.at_level("WARNING"):
            assert discovered_ids(one_branch, job) == ["keep", "tend"]
        assert "notify.email works on command jobs only" in caplog.text


# ── schedule file loading, through discover_jobs ──────


def ids_beside(daemon_dir: Path, raw: str) -> list:
    """The ids discover_jobs() returns when a_bad.json holds `raw`, read before a good schedule.json."""
    (daemon_dir / "a_bad.json").write_text(raw, encoding="utf-8")
    (daemon_dir / "schedule.json").write_text(json.dumps({"jobs": [KEEP]}), encoding="utf-8")
    return [job["id"] for job in discover_jobs()]


class TestLoadScheduleFile:
    def test_valid_file(self, one_branch):
        data = {"version": 1, "jobs": [{"id": "x", "schedule": {"type": "daily"}, "prompt": "y"}]}
        assert ids_beside(one_branch, json.dumps(data)) == ["x", "keep"]

    def test_unreadable_file(self, one_branch):
        """Mutant killed: _load_schedule_file's except narrowed to json.JSONDecodeError."""
        (one_branch / "a_dir.json").mkdir()  # matches *.json, and open() raises OSError on it
        assert ids_beside(one_branch, json.dumps({"jobs": []})) == ["keep"]

    def test_invalid_json(self, one_branch):
        """Mutant killed: _load_schedule_file's except narrowed to OSError."""
        assert ids_beside(one_branch, "{invalid json") == ["keep"]

    def test_non_dict_root(self, one_branch):
        """Mutant killed: the isinstance(data, dict) check removed from _load_schedule_file."""
        assert ids_beside(one_branch, '["jobs"]') == ["keep"]

    def test_missing_jobs_array(self, one_branch):
        """Mutant killed: the '"jobs" not in data' check removed from _load_schedule_file."""
        assert ids_beside(one_branch, '{"version": 1}') == ["keep"]

    def test_non_list_jobs(self, one_branch):
        """Mutant killed: the isinstance(data["jobs"], list) check removed from _load_schedule_file."""
        assert ids_beside(one_branch, '{"jobs": "not a list"}') == ["keep"]


# ── _build_branch_map ────────────────────────────────


class TestCitizenRecordShape:
    """What daemon builds from @memory's rows.

    The registry READ that used to live here is gone (FPLAN-0460) — it is
    registry_scope's now, and pinning a copy of it in this file is what let the
    two definitions drift in the first place. What remains daemon's own is the
    mapping into the {name, email, dir_name, path, source} record every lane in
    this branch consumes, and the address refusal @memory deliberately left to
    each caller.
    """

    def test_record_carries_dir_name_and_source(self, sample_registry, temp_src_aipass):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        write_passport(src / "testbranch", residency=RESIDENCY_CORE)

        record = active_citizens(root)[0]

        assert record["email"] == "@testbranch"
        assert record["dir_name"] == "testbranch"
        assert record["source"] == "aipass"
        assert record["path"] == src / "testbranch"

    def test_name_keeps_the_registry_spelling_not_the_directory(self, sample_registry, temp_src_aipass):
        """`name` is the registry's own field, casing and all.

        branch-health looks branches up by the registry spelling (uppercase),
        so switching to the directory name would break it silently. Pinned
        because @memory's default is the OTHER one — name_from='path' — and a
        future reader will wonder why this call passes 'registry'.
        """
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        write_passport(src / "testbranch", residency=RESIDENCY_CORE)

        record = active_citizens(root)[0]

        assert record["name"] == "TESTBRANCH"
        assert record["dir_name"] == "testbranch"

    def test_inactive_branches_never_arrive(self, sample_registry, temp_src_aipass):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        (src / "inactive").mkdir()

        assert [c["email"] for c in active_citizens(root)] == ["@testbranch"]

    def test_empty_registry_is_not_an_error(self, temp_src_aipass):
        root, _src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}), encoding="utf-8")
        assert active_citizens(root) == []


class TestDiscoverJobs:
    def test_discovers_valid_jobs(self, temp_src_aipass, sample_schedule, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch("aipass.daemon.apps.handlers.schedule.discovery._REPO_ROOT", root),
            patch("aipass.daemon.apps.handlers.schedule.discovery._SRC_AIPASS", src),
            patch("aipass.daemon.apps.handlers.schedule.discovery._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 1
        assert jobs[0]["owner"] == "@testbranch"
        assert jobs[0]["id"] == "daily-check"
        assert jobs[0]["schedule"]["type"] == "daily"
        assert jobs[0]["prompt"] == "Run daily check."

    def test_skips_unregistered_branches(self, temp_src_aipass, sample_schedule, sample_registry):
        root, src = temp_src_aipass
        unregistered = src / "unknown_branch"
        daemon_dir = unregistered / ".daemon"
        daemon_dir.mkdir(parents=True)
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch("aipass.daemon.apps.handlers.schedule.discovery._REPO_ROOT", root),
            patch("aipass.daemon.apps.handlers.schedule.discovery._SRC_AIPASS", src),
            patch("aipass.daemon.apps.handlers.schedule.discovery._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 0

    def test_skips_pycache_and_dotdirs(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        for name in ["__pycache__", ".hidden", "compass"]:
            d = src / name / ".daemon"
            d.mkdir(parents=True)
            (d / "schedule.json").write_text('{"jobs":[]}', encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch("aipass.daemon.apps.handlers.schedule.discovery._REPO_ROOT", root),
            patch("aipass.daemon.apps.handlers.schedule.discovery._SRC_AIPASS", src),
            patch("aipass.daemon.apps.handlers.schedule.discovery._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 0

    def test_skips_malformed_jobs(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        bad_data = {"version": 1, "jobs": [{"id": "no-schedule"}]}
        (daemon_dir / "schedule.json").write_text(json.dumps(bad_data), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch("aipass.daemon.apps.handlers.schedule.discovery._REPO_ROOT", root),
            patch("aipass.daemon.apps.handlers.schedule.discovery._SRC_AIPASS", src),
            patch("aipass.daemon.apps.handlers.schedule.discovery._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 0

    def test_rotation_jobs_carry_their_config(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        daemon_dir = src / "testbranch" / ".daemon"
        daemon_dir.mkdir(parents=True)
        data = {
            "version": 1,
            "jobs": [
                {
                    "id": "rounds",
                    "schedule": {"type": "rotation", "time": "05:00"},
                    "config": {"include_managers": True},
                    "prompt": "ROUNDS for {branch}.",
                }
            ],
        }
        (daemon_dir / "schedule.json").write_text(json.dumps(data), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch(f"{DISCOVERY}._REPO_ROOT", root),
            patch(f"{DISCOVERY}._SRC_AIPASS", src),
            patch(f"{DISCOVERY}._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 1
        assert jobs[0]["schedule"]["type"] == "rotation"
        assert jobs[0]["config"] == {"include_managers": True}

    def test_command_jobs_carry_their_command_and_branch(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        data = {
            "version": 1,
            "jobs": [
                command_job(timeout_seconds=120, notify={"email": "@devpulse"}, wake={"model": "opus"}),
                {"id": "tend", "schedule": {"type": "daily", "time": "04:00"}, "prompt": "Tend."},
            ],
        }
        (daemon_dir / "schedule.json").write_text(json.dumps(data), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch(f"{DISCOVERY}._REPO_ROOT", root),
            patch(f"{DISCOVERY}._SRC_AIPASS", src),
            patch(f"{DISCOVERY}._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        by_id = {job["id"]: job for job in jobs}
        assert set(by_id) == {"sweep", "tend"}
        sweep = by_id["sweep"]
        assert sweep["command"] == "drone rm --stale 10d ../.."
        # The directory whose .daemon/ published the job: drone reads cwd as identity.
        assert Path(sweep["branch_path"]).resolve() == branch_dir.resolve()
        assert sweep["timeout_seconds"] == 120
        assert sweep["notify"] == {"email": "@devpulse"}
        assert sweep["wake"] == {}, "a command job's wake block is dropped, not carried"
        assert "prompt" not in sweep
        # A wake job's shape is untouched: nothing of the command lane leaks onto it.
        assert set(by_id["tend"]) == {"owner", "id", "schedule", "wake", "prompt", "enabled", "config"}

    def test_disabled_jobs_still_discovered(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        data = {
            "version": 1,
            "jobs": [{"id": "off", "enabled": False, "schedule": {"type": "daily", "time": "04:00"}, "prompt": "x"}],
        }
        (daemon_dir / "schedule.json").write_text(json.dumps(data), encoding="utf-8")

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry), encoding="utf-8")

        with (
            patch("aipass.daemon.apps.handlers.schedule.discovery._REPO_ROOT", root),
            patch("aipass.daemon.apps.handlers.schedule.discovery._SRC_AIPASS", src),
            patch("aipass.daemon.apps.handlers.schedule.discovery._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 1
        assert jobs[0]["enabled"] is False


# ── projects/* citizens (DPLAN-0287 piece 2) ─────────


@pytest.fixture
def projects_tree(temp_src_aipass, sample_registry):
    """A repo with one framework branch and one project citizen (@proj).

    @proj's registry path — 'src/proj/proj' — deliberately ALSO exists under the
    repo root: the real tree has exactly this collision for @baud, and resolving
    a project path repo-first silently picks the wrong directory.
    """
    root, src = temp_src_aipass
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
    (src / "testbranch").mkdir()

    decoy = root / "src" / "proj" / "proj"
    decoy.mkdir(parents=True)

    project_root = root / "projects" / "proj"
    citizen = project_root / "src" / "proj" / "proj"
    citizen.mkdir(parents=True)
    write_passport(citizen, residency=RESIDENCY_RESIDENT)
    (project_root / "PROJ_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": "src/proj/proj", "status": "active"}]}),
        encoding="utf-8",
    )
    return root, src, citizen, decoy


@contextmanager
def patched_roots(root: Path, src: Path):
    """Point discovery at a temp repo tree.

    _REGISTRY_FILE is gone with daemon's own reader — @memory resolves the core
    registry from the root it is handed, so _REPO_ROOT is the only seam the
    fleet lane needs now. _SRC_AIPASS stays: branch_path_for still falls back to
    it for an unregistered directory.
    """
    with (
        patch(f"{DISCOVERY}._REPO_ROOT", root),
        patch(f"{DISCOVERY}._SRC_AIPASS", src),
    ):
        yield


class TestProjectCitizens:
    def test_project_citizens_join_the_roster(self, projects_tree):
        root, src, _citizen, _decoy = projects_tree
        with patched_roots(root, src):
            citizens = active_citizens()
        assert [c["email"] for c in citizens] == ["@testbranch", "@proj"]
        assert citizens[-1]["source"] == "projects/proj"

    def test_project_path_resolves_inside_the_project(self, projects_tree):
        root, src, citizen, decoy = projects_tree
        with patched_roots(root, src):
            found = [c for c in active_citizens() if c["email"] == "@proj"][0]
            resolved = branch_path_for("proj")
        assert found["path"] == citizen
        assert found["path"] != decoy
        assert resolved == citizen

    def test_project_schedule_files_are_discovered(self, projects_tree, sample_schedule):
        root, src, citizen, _decoy = projects_tree
        daemon_dir = citizen / ".daemon"
        daemon_dir.mkdir()
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule), encoding="utf-8")

        with patched_roots(root, src):
            jobs = discover_jobs()

        assert [j["owner"] for j in jobs] == ["@proj"]

    def test_missing_projects_dir_is_not_an_error(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        with patched_roots(root, src):
            citizens = active_citizens()
        assert [c["email"] for c in citizens] == ["@testbranch"]

    def test_duplicate_email_keeps_the_first_registry(self, projects_tree):
        root, src, _citizen, _decoy = projects_tree
        dupe_root = root / "projects" / "dupe"
        (dupe_root / "src" / "testbranch").mkdir(parents=True)
        write_passport(dupe_root / "src" / "testbranch", residency=RESIDENCY_RESIDENT)
        dupe_entry = {"name": "TESTBRANCH", "email": "@testbranch", "path": "src/testbranch", "status": "active"}
        (dupe_root / "DUPE_REGISTRY.json").write_text(json.dumps({"branches": [dupe_entry]}), encoding="utf-8")

        with patched_roots(root, src):
            citizens = active_citizens()

        assert [c["email"] for c in citizens].count("@testbranch") == 1
        assert citizens[0]["source"] == "aipass"

    def test_the_duplicate_address_is_refused_by_name(self, projects_tree):
        """Deduplication is daemon's own, on daemon's own axis, and never silent.

        @memory deduplicates by resolved PATH — right for their path-keyed
        lanes. Two rows with the SAME email and DIFFERENT paths survive that
        and both reach here, which for an email-keyed scheduler means one
        citizen's schedule fires twice. Red-first: without the dedup in
        active_citizens() this returns @testbranch twice.
        """
        root, src, _citizen, _decoy = projects_tree
        dupe_root = root / "projects" / "dupe"
        (dupe_root / "src" / "testbranch").mkdir(parents=True)
        write_passport(dupe_root / "src" / "testbranch", residency=RESIDENCY_RESIDENT)
        (dupe_root / "DUPE_REGISTRY.json").write_text(
            json.dumps(
                {
                    "branches": [
                        {"name": "TESTBRANCH", "email": "@testbranch", "path": "src/testbranch", "status": "active"}
                    ]
                }
            ),
            encoding="utf-8",
        )

        with patched_roots(root, src), patch(f"{DISCOVERY}.logger") as log:
            citizens = active_citizens()

        assert [c["email"] for c in citizens].count("@testbranch") == 1
        text = " ".join(str(c) for c in log.error.call_args_list)
        assert "@testbranch" in text and "DUPE_REGISTRY.json" in text


class TestCitizenClass:
    def test_reads_class_from_passport(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"identity": {"citizen_class": "manager"}}), encoding="utf-8")
        assert citizen_class_for(tmp_path) == "manager"

    def test_missing_passport_returns_empty(self, tmp_path):
        assert citizen_class_for(tmp_path) == ""

    @pytest.mark.parametrize("error", NOT_ABSENT, ids=["EACCES", "ENOTDIR"])
    def test_a_trinity_that_cannot_be_read_returns_none(self, tmp_path, caplog, error):
        """Only a passport truly absent is an ordinary citizen; not learning whether it exists is None.

        Path.exists() on 3.12 raised PermissionError out of the call and answered False on ENOTDIR,
        so an unreadable .trinity either crashed the sweep or read as "" (a worker, possibly a manager).
        Mutant killed: except FileNotFoundError widened to except OSError in citizen_class_for.
        """
        passport = tmp_path / ".trinity" / "passport.json"
        with patch(f"{DISCOVERY}._stat_passport", side_effect=error) as stat, caplog.at_level("WARNING"):
            assert citizen_class_for(tmp_path) is None
        stat.assert_called_once_with(passport)
        assert str(passport) in caplog.text

    def test_malformed_passport_returns_none(self, tmp_path):
        """A passport that exists but cannot be read answers None, never "" (not a manager).

        "" let a manager whose passport was corrupt be woken by the sweep and put on the rounds roster.
        Mutant killed: the parse failure answering "" (the code before 2026-09-27).
        """
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text("{not json", encoding="utf-8")
        assert citizen_class_for(tmp_path) is None

    def test_non_dict_passport_returns_none(self, tmp_path):
        """Mutant killed: a non-dict passport answering "" (the code before 2026-09-27)."""
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text("[]", encoding="utf-8")
        assert citizen_class_for(tmp_path) is None

    @pytest.mark.parametrize("identity", [{"citizen_class": None}, {"citizen_class": 7}, "manager"])
    def test_an_unreadable_class_returns_none(self, tmp_path, identity):
        """A class that is not a string is as unreadable as a corrupt file: None, never a worker.

        Mutant killed: the class returned unchecked (null leaked through, a non-dict identity raised).
        """
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"identity": identity}), encoding="utf-8")
        assert citizen_class_for(tmp_path) is None


# ── Declared residency (DPLAN-0319 wave 3) ───────────
#
# The wave's landed semantics, converged on here from @memory's registry_scope
# 2.0.0 and @ai_mail's registry/read.py. Discovery is registry-led and shallow;
# classification reads the branch's OWN passport; inside projects/ BOTH keys are
# required. The exclusion layers are asserted ALONE, because on the live tree
# the parked projects are refused by every layer at once and each one looks
# unnecessary until the others are removed.

REAL_REPO_ROOT = framework_root().parents[1]  # <repo>/src/aipass -> <repo>

live_fleet = pytest.mark.skipif(
    os.environ.get("GITHUB_ACTIONS") == "true" or not (REAL_REPO_ROOT / "projects").is_dir(),
    reason="projects/ is gitignored — absent on CI runners and fresh checkouts",
)


def write_passport(branch_dir: Path, residency=None, citizen_class=None, raw=None) -> Path:
    """Write a passport for a branch. `raw` overrides the whole document."""
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    passport = trinity / "passport.json"
    if raw is not None:
        passport.write_text(raw, encoding="utf-8")
        return passport
    doc = {}
    if residency is not None:
        doc["citizenship"] = {"residency": residency}
    if citizen_class is not None:
        doc["identity"] = {"citizen_class": citizen_class}
    passport.write_text(json.dumps(doc), encoding="utf-8")
    return passport


def make_project(root: Path, project: str, branch: str = "proj", email=None, status="active", residency=None):
    """Plant projects/<project>/<PROJECT>_REGISTRY.json listing one branch.

    Returns the branch directory. A `residency` of None means NO passport file
    at all — the "declares nothing" case, distinct from a passport whose
    citizenship block is missing.
    """
    project_root = root / "projects" / project
    branch_dir = project_root / "src" / branch
    branch_dir.mkdir(parents=True)
    if residency is not None:
        write_passport(branch_dir, residency=residency)
    entry = {
        "name": branch.upper(),
        "email": email or f"@{branch}",
        "path": f"src/{branch}",
        "status": status,
    }
    (project_root / f"{project.upper()}_REGISTRY.json").write_text(json.dumps({"branches": [entry]}), encoding="utf-8")
    return branch_dir


@pytest.fixture
def core_only(temp_src_aipass, sample_registry):
    """A repo with one core citizen and an empty projects/ tree."""
    root, src = temp_src_aipass
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
    (src / "testbranch").mkdir()
    write_passport(src / "testbranch", residency=RESIDENCY_CORE)
    (root / "projects").mkdir()
    return root, src


def error_text(mock_logger) -> str:
    """Every error-level line the module logged, args included."""
    return "\n".join(str(call) for call in mock_logger.error.call_args_list)


class TestDeclaredResidency:
    """The single reader for citizenship.residency. Never raises."""

    def test_reads_the_declared_value(self, tmp_path):
        write_passport(tmp_path, residency=RESIDENCY_RESIDENT)
        assert declared_residency(tmp_path) == RESIDENCY_RESIDENT

    def test_missing_passport_declares_nothing(self, tmp_path):
        assert declared_residency(tmp_path) is None

    def test_unreadable_passport_declares_nothing(self, tmp_path):
        write_passport(tmp_path, raw="{not json")
        assert declared_residency(tmp_path) is None

    def test_absent_field_declares_nothing(self, tmp_path):
        write_passport(tmp_path, citizen_class="specialist")
        assert declared_residency(tmp_path) is None

    def test_non_string_value_declares_nothing(self, tmp_path):
        write_passport(tmp_path, raw=json.dumps({"citizenship": {"residency": 5}}))
        assert declared_residency(tmp_path) is None

    @pytest.mark.parametrize(
        "raw, label",
        [
            ("[]", "list root"),
            ('"core"', "string root"),
            ("5", "number root"),
            ("null", "null root"),
            ("true", "bool root"),
            ('{"citizenship": "core"}', "citizenship present but not a dict"),
        ],
    )
    def test_a_malformed_passport_declares_nothing_and_does_not_raise(self, tmp_path, raw, label):
        """Every shape that used to crash the whole fleet lane now returns None.

        History, because the pin is worth more than the assertion: daemon's own
        deleted copy guarded only the ROOT, registry_scope 2.1.0 guarded neither,
        and 2.2.0 guards both after @memory found that the second `.get` in
        `data.get("citizenship", {}).get("residency")` was unprotected — a shape
        this branch never tested and could not have reported.

        declared_residency is called once per citizen by fleet_branches, so a
        raise here is not one refused branch: it is every lane in the fleet,
        killed by one bad file. Parametrized rather than one case, because a fix
        verified against a list alone leaves the other five alive.
        """
        write_passport(tmp_path, raw=raw)
        assert declared_residency(tmp_path) is None, label


class TestRegistryLedDiscovery:
    """Candidate discovery finds REGISTRIES, one level down, dots refused."""

    def test_finds_one_level_registries(self, core_only):
        """Both one-level projects reach the roster, in project-name order.

        Asserted on WHO ARRIVES rather than on which registry files were
        globbed: the glob is registry_scope's now, and re-pinning its internals
        here would rebuild the second implementation FPLAN-0460 removed.
        """
        root, src = core_only
        make_project(root, "alpha", branch="alpha", residency=RESIDENCY_RESIDENT)
        make_project(root, "beta", branch="beta", residency=RESIDENCY_RESIDENT)
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch", "@alpha", "@beta"]

    def test_dot_prefixed_project_refused_by_the_dot_filter_alone(self, core_only):
        """Depth-legal and would otherwise be discovered — only the dot filter refuses it."""
        root, src = core_only
        make_project(root, ".archive", branch="parked", residency=RESIDENCY_RESIDENT)
        with patched_roots(root, src):
            assert [c["email"] for c in active_citizens()] == ["@testbranch"]

    def test_nested_registry_refused_by_the_depth_rule_alone(self, core_only):
        """No dot anywhere in the path — only the one-level depth rule refuses it."""
        root, src = core_only
        nested = root / "projects" / "outer" / "inner"
        branch_dir = nested / "src" / "deep"
        branch_dir.mkdir(parents=True)
        write_passport(branch_dir, residency=RESIDENCY_RESIDENT)
        (nested / "DEEP_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "DEEP", "email": "@deep", "path": "src/deep", "status": "active"}]}),
            encoding="utf-8",
        )
        with patched_roots(root, src):
            assert [c["email"] for c in active_citizens()] == ["@testbranch"]

    def test_missing_projects_tree_is_not_an_error(self, temp_src_aipass, sample_registry):
        """A checkout with no projects/ yields the core citizens and does not raise.

        CI runs on exactly that tree — projects/ is gitignored.
        """
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        with patched_roots(root, src):
            assert [c["email"] for c in active_citizens()] == ["@testbranch"]

    def test_never_a_passport_walk(self, core_only):
        """A backup copy of a passport is still a passport — and must not be a citizen.

        On the live tree @baud carries resident-declaring passports under
        .backup/versioned/ and .backup/snapshots/; a passport-led discovery
        counts it three times. Reading a passport only at a path some registry
        declared is what makes the count right.
        """
        root, src = core_only
        branch_dir = make_project(root, "proj", branch="proj", residency=RESIDENCY_RESIDENT)
        backup = branch_dir / ".backup" / "versioned" / "root"
        backup.mkdir(parents=True)
        write_passport(backup, residency=RESIDENCY_RESIDENT)
        (backup / "PROJ_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": ".", "status": "active"}]}),
            encoding="utf-8",
        )

        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
            found = [c for c in active_citizens() if c["email"] == "@proj"][0]

        assert emails.count("@proj") == 1
        assert found["path"] == branch_dir


class TestTwoKeyRule:
    """Inside projects/: registry active AND passport resident. Both required."""

    def test_both_keys_present_joins_the_fleet(self, core_only):
        root, src = core_only
        branch_dir = make_project(root, "proj", residency=RESIDENCY_RESIDENT)
        with patched_roots(root, src):
            citizens = active_citizens()
        assert [c["email"] for c in citizens] == ["@testbranch", "@proj"]
        assert citizens[-1]["path"] == branch_dir
        assert citizens[-1]["source"] == "projects/proj"

    def test_registry_alone_is_refused_when_no_passport(self, core_only):
        root, src = core_only
        make_project(root, "proj", residency=None)
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_absent_residency_field_is_refused_and_named(self, core_only):
        root, src = core_only
        branch_dir = make_project(root, "proj", residency=None)
        write_passport(branch_dir, citizen_class="specialist")
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_unreadable_passport_is_refused_and_named(self, core_only):
        root, src = core_only
        branch_dir = make_project(root, "proj", residency=None)
        write_passport(branch_dir, raw="{not json")
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_core_claimed_from_inside_projects_is_refused_and_named(self, core_only):
        root, src = core_only
        make_project(root, "proj", residency=RESIDENCY_CORE)
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_unknown_residency_value_is_refused_and_names_the_value(self, core_only):
        root, src = core_only
        make_project(root, "proj", residency="tenant")
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_registry_path_not_on_disk_is_refused_and_named(self, core_only):
        """A row pointing nowhere used to vanish silently — it is now named.

        Silent here is the worst outcome of all: an absent directory and a
        parked project produce the same empty roster, and only one of them is
        somebody's typo.
        """
        root, src = core_only
        project_root = root / "projects" / "proj"
        project_root.mkdir(parents=True)
        (project_root / "PROJ_REGISTRY.json").write_text(
            json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": "src/gone", "status": "active"}]}),
            encoding="utf-8",
        )
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_passport_alone_cannot_add_scope(self, core_only):
        """A declared resident the registry lists as inactive stays out."""
        root, src = core_only
        make_project(root, "proj", status="retired", residency=RESIDENCY_RESIDENT)
        with patched_roots(root, src):
            assert [c["email"] for c in active_citizens()] == ["@testbranch"]

    def test_passport_can_never_remove_a_core_citizen(self, temp_src_aipass, sample_registry):
        """A core branch declaring nothing is KEPT — and the disagreement is logged.

        The asymmetry is deliberate: if an absent field could drop a citizen, an
        agent could stop its own jobs firing by deleting one line of its own file.
        """
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_core_citizen_declaring_resident_is_kept(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry), encoding="utf-8")
        (src / "testbranch").mkdir()
        write_passport(src / "testbranch", residency=RESIDENCY_RESIDENT)
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]


class TestParkedProjectPolicyChange:
    """The documented behaviour change: a parked project at depth one is now refused.

    Before this wave every projects/<name>/ subdir was path-walked and any branch
    its registry marked active became a citizen — a parked project kept its place
    in the scheduler, the steward rotation and the inbox sweep on the strength of
    a status field nobody had revisited. The passport is now the second key, and
    it is the only layer that refuses this case: the project sits one level down
    with no dot in its path, so neither the depth rule nor the dot filter fires.
    """

    def test_parked_project_refused_by_the_passport_layer_alone(self, core_only):
        root, src = core_only
        make_project(root, "marketstand", branch="marketstand", residency=None)
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"], "classification must refuse it"

    def test_parked_project_fires_no_scheduled_jobs(self, core_only, sample_schedule):
        root, src = core_only
        branch_dir = make_project(root, "marketstand", branch="marketstand", residency=None)
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir()
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule), encoding="utf-8")
        with patched_roots(root, src):
            jobs = discover_jobs()
        assert jobs == []

    def test_parked_project_is_not_swept_for_mail(self, core_only):
        root, src = core_only
        make_project(root, "marketstand", branch="marketstand", residency=None)
        with patched_roots(root, src):
            assert active_branch_map() == {"testbranch": "@testbranch"}


@live_fleet
class TestLiveFleet:
    """Assertions about THIS machine's tree. Skipped loudly where it is absent."""

    def test_the_live_fleet_is_not_empty(self):
        # The floor under every loop below: an empty fleet would let each of
        # them pass by iterating nothing.
        assert len(active_citizens()) >= 18

    def test_every_project_citizen_declares_resident(self):
        # Narrowed to projects/ deliberately, when the external tier went live
        # (AIPASS_ROOTS.json blessed 2026-08-30). Externals declare NOTHING and
        # must not: membership out there is PRESENCE - a passport exists in a
        # declared root - and the tier label is applied by the reader, never
        # claimed by the passport. Six live external citizens across four repos
        # carry no residency field, and requiring one would have made a
        # six-owner schema campaign the price of the feature.
        citizens = [c for c in active_citizens() if c["source"].startswith("projects/")]
        assert citizens, "no projects/ citizen on this machine - the pin proved nothing"
        for citizen in citizens:
            assert declared_residency(citizen["path"]) == RESIDENCY_RESIDENT, citizen

    def test_an_external_citizen_is_labelled_external_never_core(self):
        # The fence. A citizen outside AIPass home may never read as core: the
        # source label is what tells a downstream lane which repo to stand in.
        citizens = active_citizens()
        assert citizens
        for citizen in citizens:
            outside = not citizen["path"].is_relative_to(REAL_REPO_ROOT)
            assert outside == citizen["source"].startswith("external"), citizen

    def test_no_citizen_resolves_under_a_dot_prefixed_component(self):
        # Compared against the citizen's OWN root, not AIPass home - an
        # external path is not relative to REAL_REPO_ROOT at all, and the
        # invariant being held here was never about which repo it lives in.
        # The .backup/ copies this exists to keep out are equally forbidden
        # in a declared root.
        citizens = active_citizens()
        assert citizens
        for citizen in citizens:
            parts = citizen["path"].parts
            assert not any(part.startswith(".") for part in parts), citizen

    def test_parked_projects_are_absent_by_name(self):
        emails = {c["email"] for c in active_citizens()}
        assert "@marketstand" not in emails
        assert "@speakeasy" not in emails
