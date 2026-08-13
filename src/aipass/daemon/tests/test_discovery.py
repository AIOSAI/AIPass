"""Tests for decentralized .daemon/ schedule discovery."""

import json
import shutil
import tempfile
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import pytest

from aipass.daemon.apps.handlers.schedule.discovery import (
    discover_jobs,
    active_citizens,
    branch_path_for,
    citizen_class_for,
    _validate_job,
    _load_schedule_file,
    _citizen_records,
    REQUIRED_JOB_KEYS,
    VALID_SCHEDULE_TYPES,
)

DISCOVERY = "aipass.daemon.apps.handlers.schedule.discovery"


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


# ── _validate_job ─────────────────────────────────────


class TestValidateJob:
    def test_valid_job(self):
        job = {"id": "test", "schedule": {"type": "daily", "time": "04:00"}, "prompt": "do stuff"}
        assert _validate_job(job, Path("test.json")) is True

    def test_missing_required_key(self):
        job = {"id": "test", "schedule": {"type": "daily"}}
        assert _validate_job(job, Path("test.json")) is False

    def test_non_dict_schedule(self):
        job = {"id": "test", "schedule": "daily", "prompt": "do stuff"}
        assert _validate_job(job, Path("test.json")) is False

    def test_invalid_schedule_type(self):
        job = {"id": "test", "schedule": {"type": "biweekly"}, "prompt": "do stuff"}
        assert _validate_job(job, Path("test.json")) is False

    def test_all_valid_schedule_types(self):
        for stype in VALID_SCHEDULE_TYPES:
            job = {"id": "test", "schedule": {"type": stype}, "prompt": "do stuff"}
            assert _validate_job(job, Path("test.json")) is True

    def test_required_keys_constant(self):
        assert REQUIRED_JOB_KEYS == {"id", "schedule", "prompt"}


# ── _load_schedule_file ──────────────────────────────


class TestLoadScheduleFile:
    def test_valid_file(self, tmp_path):
        f = tmp_path / "schedule.json"
        data = {"version": 1, "jobs": [{"id": "x", "schedule": {"type": "daily"}, "prompt": "y"}]}
        f.write_text(json.dumps(data))
        result = _load_schedule_file(f)
        assert result is not None
        assert len(result["jobs"]) == 1

    def test_missing_file(self, tmp_path):
        result = _load_schedule_file(tmp_path / "nonexistent.json")
        assert result is None

    def test_invalid_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{invalid json")
        result = _load_schedule_file(f)
        assert result is None

    def test_non_dict_root(self, tmp_path):
        f = tmp_path / "list.json"
        f.write_text("[]")
        result = _load_schedule_file(f)
        assert result is None

    def test_missing_jobs_array(self, tmp_path):
        f = tmp_path / "nojobs.json"
        f.write_text('{"version": 1}')
        result = _load_schedule_file(f)
        assert result is None

    def test_non_list_jobs(self, tmp_path):
        f = tmp_path / "badjobs.json"
        f.write_text('{"jobs": "not a list"}')
        result = _load_schedule_file(f)
        assert result is None


# ── _build_branch_map ────────────────────────────────


class TestCitizenRecords:
    def _emails(self, registry, root):
        with patch(f"{DISCOVERY}._REPO_ROOT", root):
            return [c["email"] for c in _citizen_records(registry, root, "aipass")]

    def test_active_branches_only(self, sample_registry, temp_src_aipass):
        root, src = temp_src_aipass
        (src / "testbranch").mkdir()
        (src / "inactive").mkdir()
        emails = self._emails(sample_registry, root)
        assert emails == ["@testbranch"]

    def test_empty_registry(self, temp_src_aipass):
        root, _src = temp_src_aipass
        assert _citizen_records({}, root, "aipass") == []
        assert _citizen_records({"branches": []}, root, "aipass") == []

    def test_missing_path_skipped(self, sample_registry, temp_src_aipass):
        root, _src = temp_src_aipass
        assert self._emails(sample_registry, root) == []

    def test_record_carries_dir_name_and_source(self, sample_registry, temp_src_aipass):
        root, src = temp_src_aipass
        (src / "testbranch").mkdir()
        with patch(f"{DISCOVERY}._REPO_ROOT", root):
            record = _citizen_records(sample_registry, root, "aipass")[0]
        assert record["dir_name"] == "testbranch"
        assert record["source"] == "aipass"
        assert record["path"] == src / "testbranch"


# ── discover_jobs (integration) ──────────────────────


class TestDiscoverJobs:
    def test_discovers_valid_jobs(self, temp_src_aipass, sample_schedule, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule))

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

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
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule))

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

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
            (d / "schedule.json").write_text('{"jobs":[]}')

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

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
        (daemon_dir / "schedule.json").write_text(json.dumps(bad_data))

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

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
                    "id": "fleet-steward",
                    "schedule": {"type": "rotation", "time": "05:00"},
                    "config": {"include_managers": True},
                    "prompt": "STEWARD NIGHT for {branch}.",
                }
            ],
        }
        (daemon_dir / "schedule.json").write_text(json.dumps(data))

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

        with (
            patch(f"{DISCOVERY}._REPO_ROOT", root),
            patch(f"{DISCOVERY}._SRC_AIPASS", src),
            patch(f"{DISCOVERY}._REGISTRY_FILE", reg_file),
        ):
            jobs = discover_jobs()

        assert len(jobs) == 1
        assert jobs[0]["schedule"]["type"] == "rotation"
        assert jobs[0]["config"] == {"include_managers": True}

    def test_disabled_jobs_still_discovered(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        branch_dir = src / "testbranch"
        daemon_dir = branch_dir / ".daemon"
        daemon_dir.mkdir(parents=True)
        data = {
            "version": 1,
            "jobs": [{"id": "off", "enabled": False, "schedule": {"type": "daily", "time": "04:00"}, "prompt": "x"}],
        }
        (daemon_dir / "schedule.json").write_text(json.dumps(data))

        reg_file = root / "AIPASS_REGISTRY.json"
        reg_file.write_text(json.dumps(sample_registry))

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
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
    (src / "testbranch").mkdir()

    decoy = root / "src" / "proj" / "proj"
    decoy.mkdir(parents=True)

    project_root = root / "projects" / "proj"
    citizen = project_root / "src" / "proj" / "proj"
    citizen.mkdir(parents=True)
    (project_root / "PROJ_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": "src/proj/proj", "status": "active"}]})
    )
    return root, src, citizen, decoy


@contextmanager
def patched_roots(root: Path, src: Path):
    """Point discovery at a temp repo tree (both registries and both trees)."""
    with (
        patch(f"{DISCOVERY}._REPO_ROOT", root),
        patch(f"{DISCOVERY}._SRC_AIPASS", src),
        patch(f"{DISCOVERY}._REGISTRY_FILE", root / "AIPASS_REGISTRY.json"),
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
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule))

        with patched_roots(root, src):
            jobs = discover_jobs()

        assert [j["owner"] for j in jobs] == ["@proj"]

    def test_missing_projects_dir_is_not_an_error(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
        (src / "testbranch").mkdir()
        with patched_roots(root, src):
            citizens = active_citizens()
        assert [c["email"] for c in citizens] == ["@testbranch"]

    def test_duplicate_email_keeps_the_first_registry(self, projects_tree):
        root, src, _citizen, _decoy = projects_tree
        dupe_root = root / "projects" / "dupe"
        (dupe_root / "src" / "testbranch").mkdir(parents=True)
        dupe_entry = {"name": "TESTBRANCH", "email": "@testbranch", "path": "src/testbranch", "status": "active"}
        (dupe_root / "DUPE_REGISTRY.json").write_text(json.dumps({"branches": [dupe_entry]}))

        with patched_roots(root, src):
            citizens = active_citizens()

        assert [c["email"] for c in citizens].count("@testbranch") == 1
        assert citizens[0]["source"] == "aipass"


class TestCitizenClass:
    def test_reads_class_from_passport(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text(json.dumps({"identity": {"citizen_class": "manager"}}))
        assert citizen_class_for(tmp_path) == "manager"

    def test_missing_passport_returns_empty(self, tmp_path):
        assert citizen_class_for(tmp_path) == ""

    def test_malformed_passport_returns_empty(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text("{not json")
        assert citizen_class_for(tmp_path) == ""

    def test_non_dict_passport_returns_empty(self, tmp_path):
        trinity = tmp_path / ".trinity"
        trinity.mkdir()
        (trinity / "passport.json").write_text("[]")
        assert citizen_class_for(tmp_path) == ""
