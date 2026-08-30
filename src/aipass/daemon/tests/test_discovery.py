"""Tests for decentralized .daemon/ schedule discovery."""

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
    _validate_job,
    _load_schedule_file,
    REQUIRED_JOB_KEYS,
    RESIDENCY_CORE,
    RESIDENCY_RESIDENT,
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
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
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
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
        (src / "testbranch").mkdir()
        write_passport(src / "testbranch", residency=RESIDENCY_CORE)

        record = active_citizens(root)[0]

        assert record["name"] == "TESTBRANCH"
        assert record["dir_name"] == "testbranch"

    def test_inactive_branches_never_arrive(self, sample_registry, temp_src_aipass):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
        (src / "testbranch").mkdir()
        (src / "inactive").mkdir()

        assert [c["email"] for c in active_citizens(root)] == ["@testbranch"]

    def test_empty_registry_is_not_an_error(self, temp_src_aipass):
        root, _src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps({"branches": []}))
        assert active_citizens(root) == []


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
    write_passport(citizen, residency=RESIDENCY_RESIDENT)
    (project_root / "PROJ_REGISTRY.json").write_text(
        json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": "src/proj/proj", "status": "active"}]})
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
        write_passport(dupe_root / "src" / "testbranch", residency=RESIDENCY_RESIDENT)
        dupe_entry = {"name": "TESTBRANCH", "email": "@testbranch", "path": "src/testbranch", "status": "active"}
        (dupe_root / "DUPE_REGISTRY.json").write_text(json.dumps({"branches": [dupe_entry]}))

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
            )
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


# ── Declared residency (DPLAN-0319 wave 3) ───────────
#
# The wave's landed semantics, converged on here from @memory's registry_scope
# 2.0.0 and @ai_mail's registry/read.py. Discovery is registry-led and shallow;
# classification reads the branch's OWN passport; inside projects/ BOTH keys are
# required. The exclusion layers are asserted ALONE, because on the live tree
# the parked projects are refused by every layer at once and each one looks
# unnecessary until the others are removed.

REAL_REPO_ROOT = discovery._REPO_ROOT

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
        passport.write_text(raw)
        return passport
    doc = {}
    if residency is not None:
        doc["citizenship"] = {"residency": residency}
    if citizen_class is not None:
        doc["identity"] = {"citizen_class": citizen_class}
    passport.write_text(json.dumps(doc))
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
    (project_root / f"{project.upper()}_REGISTRY.json").write_text(json.dumps({"branches": [entry]}))
    return branch_dir


@pytest.fixture
def core_only(temp_src_aipass, sample_registry):
    """A repo with one core citizen and an empty projects/ tree."""
    root, src = temp_src_aipass
    (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
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
            json.dumps({"branches": [{"name": "DEEP", "email": "@deep", "path": "src/deep", "status": "active"}]})
        )
        with patched_roots(root, src):
            assert [c["email"] for c in active_citizens()] == ["@testbranch"]

    def test_missing_projects_tree_is_not_an_error(self, temp_src_aipass, sample_registry):
        """A checkout with no projects/ yields the core citizens and does not raise.

        CI runs on exactly that tree — projects/ is gitignored.
        """
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
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
            json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": ".", "status": "active"}]})
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
            json.dumps({"branches": [{"name": "PROJ", "email": "@proj", "path": "src/gone", "status": "active"}]})
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
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
        (src / "testbranch").mkdir()
        with patched_roots(root, src):
            emails = [c["email"] for c in active_citizens()]
        assert emails == ["@testbranch"]

    def test_core_citizen_declaring_resident_is_kept(self, temp_src_aipass, sample_registry):
        root, src = temp_src_aipass
        (root / "AIPASS_REGISTRY.json").write_text(json.dumps(sample_registry))
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
        (daemon_dir / "schedule.json").write_text(json.dumps(sample_schedule))
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

    def test_every_project_citizen_declares_resident(self):
        for citizen in active_citizens():
            if citizen["source"] != "aipass":
                assert declared_residency(citizen["path"]) == RESIDENCY_RESIDENT, citizen

    def test_no_citizen_resolves_under_a_dot_prefixed_component(self):
        for citizen in active_citizens():
            relative = citizen["path"].relative_to(REAL_REPO_ROOT)
            assert not any(part.startswith(".") for part in relative.parts), citizen

    def test_parked_projects_are_absent_by_name(self):
        emails = {c["email"] for c in active_citizens()}
        assert "@marketstand" not in emails
        assert "@speakeasy" not in emails
