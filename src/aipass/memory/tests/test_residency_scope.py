# =================== AIPass ====================
# Name: test_residency_scope.py
# Description: Red-first pins for passport-declared residency as the fleet classifier (DPLAN-0319)
# Version: 1.1.0
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/monitor/registry_scope.py and the callers that classify through it."""

# Residency is DECLARED in a passport and ANCHORED in a registry. Both, or out. Discovery
# never walks passports: a backup copy of a passport is a real passport declaring.

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — registry_scope.external_branches(); tests/test_declared_roots.py
# seedgo: no-test-needed(covered_elsewhere) — registry_scope.overlaps_home(); tests/test_roots_lifecycle.py

import json
import logging
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.monitor import detector
from aipass.memory.apps.handlers.monitor import registry_scope as rs
from aipass.memory.apps.handlers.rollover import todo_roll
from aipass.memory.apps.handlers.templates import trinity_push
from aipass.memory.tests.dead_cwd import DEAD_CWD_WORLD

# Judged by the parts BELOW the walk's root: a checkout under a directory named dropbox must not hide.
_SKIPPED_DIRS = frozenset({"dropbox", ".archive", "__pycache__"})


def _walk(root: Path, pattern: str = "*.py") -> list[Path]:
    """Every file under *root* matching *pattern*, outside the skipped directories."""
    return sorted(path for path in root.rglob(pattern) if not _SKIPPED_DIRS.intersection(path.relative_to(root).parts))


def test_the_walk_skips_dropbox_archive_and_caches_below_its_root_only(tmp_path: Path) -> None:
    """Red first against a bare rglob. The root stands inside a directory named dropbox; live/ is the control."""
    root = tmp_path / "dropbox" / "checkout"
    for name in (*sorted(_SKIPPED_DIRS), "live"):
        (root / name).mkdir(parents=True)
        (root / name / "test_x.py").write_text("", encoding="utf-8")
    assert _walk(root) == [root / "live" / "test_x.py"]


def _write(path: Path, data: dict) -> None:
    """Create parents and write *data* as JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _registry(*branches: dict) -> dict:
    """A registry document holding *branches*."""
    return {"metadata": {"name": "TEST"}, "branches": list(branches)}


def _branch(name: str, path: str, status: str = "active") -> dict:
    """One registry branch entry."""
    return {"name": name.upper(), "path": path, "email": f"@{name}", "status": status}


def _passport(residency: str | None) -> dict:
    """A passport declaring *residency*, or carrying no residency field at all."""
    citizenship: dict = {"registered": True}
    if residency is not None:
        citizenship["residency"] = residency
    return {"branch_info": {"branch_name": "test"}, "citizenship": citizenship}


@pytest.fixture
def fleet(tmp_path):
    """A synthetic repo root holding every case this module has to judge.

    Built rather than mocked: a mock of the two-file relationship would test the mock.
    """
    root = tmp_path / "repo"

    # beta declares nothing: the "never drop a core citizen" case.
    _write(
        root / "AIPASS_REGISTRY.json",
        _registry(_branch("alpha", "src/aipass/alpha"), _branch("beta", "src/aipass/beta")),
    )
    _write(root / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
    _write(root / "src/aipass/beta/.trinity/passport.json", _passport(None))

    _write(root / "projects/live/LIVE_REGISTRY.json", _registry(_branch("live", "src/live/live")))
    _write(root / "projects/live/src/live/live/.trinity/passport.json", _passport("resident"))

    # A backup copy declaring resident: registry-led discovery must never reach it.
    _write(root / "projects/live/.backup/versioned/src/live/live/.trinity/passport.json", _passport("resident"))
    _write(root / "projects/live/.backup/LIVE_REGISTRY.json", _registry(_branch("live", "src/live/live")))

    _write(root / "projects/mute/MUTE_REGISTRY.json", _registry(_branch("mute", "src/mute/mute")))
    _write(root / "projects/mute/src/mute/mute/.trinity/passport.json", _passport(None))

    _write(root / "projects/impostor/IMPOSTOR_REGISTRY.json", _registry(_branch("impostor", "src/impostor/impostor")))
    _write(root / "projects/impostor/src/impostor/impostor/.trinity/passport.json", _passport("core"))

    _write(root / "projects/ghost/GHOST_REGISTRY.json", _registry(_branch("ghost", "src/ghost/ghost")))

    _write(root / "projects/martian/MARTIAN_REGISTRY.json", _registry(_branch("martian", "src/martian/martian")))
    _write(root / "projects/martian/src/martian/martian/.trinity/passport.json", _passport("visitor"))

    # The marketstand shape: archived, registry says active, passport declares resident.
    _write(root / "projects/.archive/stale/STALE_REGISTRY.json", _registry(_branch("stale", "src/stale/stale")))
    _write(root / "projects/.archive/stale/src/stale/stale/.trinity/passport.json", _passport("resident"))

    # Two single-layer cases: defence in depth hides a one-layer regression otherwise.
    # Dot-prefixed AT depth one: only the dot filter keeps it out.
    _write(root / "projects/.hidden/HIDDEN_REGISTRY.json", _registry(_branch("hidden", "src/hidden/hidden")))
    _write(root / "projects/.hidden/src/hidden/hidden/.trinity/passport.json", _passport("resident"))

    # Nested too deep with no dot: only the shallow glob keeps it out.
    _write(root / "projects/live/nested/NESTED_REGISTRY.json", _registry(_branch("nested", "src/nested/nested")))
    _write(root / "projects/live/nested/src/nested/nested/.trinity/passport.json", _passport("resident"))

    return root


class TestDiscoveryIsRegistryLedAndShallow:
    """Finding candidates is a separate job from judging them."""

    def test_discovery_finds_the_live_project_registries(self, fleet):
        found = {path.parent.name for path in rs.resident_registry_paths(fleet)}
        assert found == {"live", "mute", "impostor", "ghost", "martian"}

    def test_discovery_refuses_every_dot_directory(self, fleet):
        """``.archive`` is the one that matters; the rule is written for all of them."""
        found = [str(path) for path in rs.resident_registry_paths(fleet)]
        assert not [path for path in found if "/.archive/" in path], f"archived registry discovered: {found}"
        assert not [path for path in found if "/.backup/" in path], f"backup registry discovered: {found}"

    def test_discovery_does_not_descend_past_one_level(self, fleet):
        """A registry two levels down is not a project — it is a copy of one.

        The non-empty guard is the whole test: an empty discovery would pass a loop vacuously.
        """
        found = rs.resident_registry_paths(fleet)
        relative = sorted(path.relative_to(fleet / "projects").as_posix() for path in found)
        assert relative == [
            "ghost/GHOST_REGISTRY.json",
            "impostor/IMPOSTOR_REGISTRY.json",
            "live/LIVE_REGISTRY.json",
            "martian/MARTIAN_REGISTRY.json",
            "mute/MUTE_REGISTRY.json",
        ], f"discovered below depth one, or missed a project: {relative}"

    def test_a_missing_projects_directory_is_not_an_error(self, tmp_path):
        """A clean checkout carries no ``projects/`` and must not raise."""
        _write(tmp_path / "AIPASS_REGISTRY.json", _registry())
        assert rs.resident_registry_paths(tmp_path) == []


class TestClassificationReadsThePassport:
    """The named list stops deciding; the declaration starts."""

    def test_the_declared_resident_is_in_the_fleet(self, fleet):
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "live" in names

    @pytest.mark.parametrize(
        "name,why",
        [
            ("mute", "listed active but declares no residency"),
            ("impostor", "declares core from inside projects/"),
            ("ghost", "listed active with no passport on disk"),
            ("martian", "declares a residency value nobody defined"),
        ],
    )
    def test_an_undeclared_or_wrongly_declared_branch_is_refused(self, fleet, name, why):
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert name not in names, f"{name} was included despite: {why}"

    def test_the_refusal_is_loud(self, fleet, caplog):
        """Refused silently is the same as never checked."""
        with caplog.at_level("ERROR"):
            rs.fleet_branches(fleet)
        logged = caplog.text
        for name in ("mute", "impostor", "ghost", "martian"):
            assert name in logged, f"{name} was refused without saying so"

    def test_a_core_citizen_is_never_dropped_for_a_missing_declaration(self, fleet):
        """``beta``'s passport declares nothing. The sealed registry still wins.

        Otherwise an agent could leave the maintenance fleet by editing its own passport.
        """
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert {"alpha", "beta"} <= names

    def test_the_core_count_and_the_resident_count_are_both_right(self, fleet):
        branches = rs.fleet_branches(fleet)
        assert len(branches) == 3, [item["name"] for item in branches]


class TestTheArchiveExclusionHoldsThreeDeep:
    """Each layer alone keeps the stale project out. Pinned one at a time."""

    def test_the_stale_project_is_absent_from_the_fleet(self, fleet):
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "stale" not in names

    def test_layer_one_the_dot_directory_is_never_discovered(self, fleet):
        assert not [path for path in rs.resident_registry_paths(fleet) if ".archive" in str(path)]

    def test_layer_one_alone_the_dot_filter_excludes_a_shallow_hidden_project(self, fleet):
        """``projects/.hidden/`` sits at depth one, so the glob would take it.

        Only the dot-prefix filter stops it; the marketstand shape is refused by depth anyway.
        """
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "hidden" not in names, "a dot-prefixed project at depth one was swept in"

    def test_layer_two_alone_the_shallow_glob_excludes_a_nested_project(self, fleet):
        """``projects/live/nested/`` carries no dot, so only the depth rule refuses it."""
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "nested" not in names, "discovery descended past one level"

    def test_layer_three_the_registry_status_field_is_not_trusted_alone(self, fleet):
        """The stale registry says ``active``. That is the field that lied.

        Pins the FIXTURE's honesty: if it stops saying active, the exclusion tests prove nothing.
        """
        data = json.loads((fleet / "projects/.archive/stale/STALE_REGISTRY.json").read_text(encoding="utf-8"))
        assert data["branches"][0]["status"] == "active"


class TestDeclaredResidency:
    """The single reader every other lane can copy."""

    def test_it_reads_the_declared_value(self, fleet):
        assert rs.declared_residency(fleet / "projects/live/src/live/live") == "resident"

    def test_a_missing_passport_declares_nothing(self, fleet):
        assert rs.declared_residency(fleet / "projects/ghost/src/ghost/ghost") is None

    def test_an_unreadable_passport_declares_nothing_and_does_not_raise(self, tmp_path):
        branch = tmp_path / "broken"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text("{ not json", encoding="utf-8")
        assert rs.declared_residency(branch) is None


class TestEveryLaneReadsTheOneDefinition:
    """Convergence pinned, because a split definition is how this started."""

    _APPS = Path(__file__).resolve().parents[1] / "apps"

    def test_the_named_resident_tuple_is_gone_from_the_branch(self):
        """It decided nothing for a wave; now it does not exist."""
        offenders = []
        for path in _walk(self._APPS):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "RESIDENT_REGISTRIES" in line:
                    offenders.append(f"{path.relative_to(self._APPS)}:{number}: {line.strip()}")
        assert offenders == [], "the retired resident tuple is back:\n  " + "\n  ".join(offenders)

    def test_the_push_lane_resolves_through_registry_scope(self):
        source = (self._APPS / "handlers" / "templates" / "trinity_push.py").read_text(encoding="utf-8")
        body = source[source.index("def resolve_scope(") :]
        assert "registry_scope.fleet_branches(" in body, "the push lane has its own scope resolution again"

    def test_the_detector_filters_residents_through_the_classifier(self, fleet, monkeypatch):
        """BEHAVIOURAL: the detector's scope holds only the declared resident.

        A grep-shaped pin survived a mutant that dropped the filter but kept the words.
        """
        monkeypatch.setattr(detector, "_REPO_ROOT", fleet)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        names = {Path(branch["path"]).name for branch in detector.read_scope()}

        assert "live" in names, "the declared resident never reached the detector lane"
        for refused in ("mute", "impostor", "ghost", "martian", "stale", "hidden", "nested"):
            assert refused not in names, f"the detector lane swept in {refused}"

    def test_accepted_resident_paths_holds_only_the_declared(self, fleet):
        """The shared classifier, exercised directly rather than through a caller."""
        accepted = rs.accepted_resident_paths(fleet)
        assert accepted == {str(fleet / "projects/live/src/live/live")}

    def test_the_read_scope_names_a_declared_external_the_write_scope_does_not(self, fleet, monkeypatch, tmp_path):
        """The read scope names a declared external; the write scope does not.

        Reads see the declared fleet through the declared roots, never cwd; writes stop at the repo edge.
        """
        outside = tmp_path / "outside"
        _write(outside / "OUTSIDE_REGISTRY.json", _registry(_branch("ext", "src/ext/ext")))
        _write(outside / "src/ext/ext/.trinity/passport.json", _passport(None))
        _write(
            fleet / "AIPASS_ROOTS.json",
            {"roots": [{"path": str(outside), "label": "outside", "status": "active"}]},
        )

        monkeypatch.setattr(detector, "_REPO_ROOT", fleet)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])

        write_names = {Path(branch["path"]).name for branch in detector._read_registry()}
        read_names = {Path(branch["path"]).name for branch in detector.read_scope()}

        assert "ext" not in write_names, "the write scope reached a branch outside the repo"
        assert "ext" in read_names, "a declared external branch cannot be named for a read"
        assert write_names <= read_names, "the read scope dropped a branch the write scope holds"

    def test_the_caller_lane_is_deliberately_not_classified(self):
        """External callers are a different mechanism — pinned so it stays a choice."""
        source = (self._APPS / "handlers" / "monitor" / "detector.py").read_text(encoding="utf-8")
        caller_loop = source[source.index("for reg_path in _find_caller_registries():") :]
        assert "accepted" not in caller_loop.split("return branches")[0]


class TestTheLiveFleetStillCountsTwentyTwo:
    """The receipt the dispatch asked for, measured rather than asserted."""

    def test_discovery_names_exactly_the_four_resident_projects(self, live_residents):
        """What the deleted anchor used to be compared against, measured directly."""
        found = {path.parent.name for path in rs.resident_registry_paths(live_residents)}
        assert found == {"baud", "earmark", "finch", "aipass-site"}

    def test_the_live_fleet_is_eighteen_core_and_four_residents(self, live_residents):
        """Counted BY TIER now, not by total — and the change is the point."""
        branches = rs.fleet_branches(live_residents)
        tiers = Counter(item["residency"] for item in branches)
        assert (tiers[rs.RESIDENCY_CORE], tiers[rs.RESIDENCY_RESIDENT]) == (18, 4), [item["name"] for item in branches]
        externals = [item for item in branches if item["residency"] == rs.RESIDENCY_EXTERNAL]
        assert len(externals) == tiers[rs.RESIDENCY_EXTERNAL]
        assert bool(externals) == bool(rs.declared_roots(live_residents)), (
            "external citizens appeared without a declared root, or a declared root produced none"
        )

    def test_every_live_resident_declares_itself_one(self, live_residents):
        """The declaration is the classifier now — so it had better be there.

        Counted, so a discovery that reads no branches cannot read as agreement.
        """
        checked = 0
        for registry_path in rs.resident_registry_paths(live_residents):
            for item in rs.read_registry_branches(registry_path):
                checked += 1
                assert rs.declared_residency(item["path"]) == rs.RESIDENCY_RESIDENT, (
                    f"{item['name']} is in fleet scope but its passport does not declare it"
                )
        assert checked, "no live resident branch was read, so nothing was proven about any declaration"

    def test_the_archived_projects_are_still_on_disk_and_still_out(self, live_fleet):
        """The exclusion is only proven where the thing being excluded exists."""
        archive = live_fleet / rs.RESIDENT_PROJECTS_DIR / ".archive"
        if not archive.is_dir():
            pytest.skip(f"no {archive} on this machine -- live-state guard skipped")
        stale = [path for path in archive.glob("*/*_REGISTRY.json")]
        assert stale, "the archive carries no registries, so it cannot prove the exclusion"
        names = {item["name"] for item in rs.fleet_branches(live_fleet)}
        assert "marketstand" not in names and "speakeasy" not in names


class TestTheRecordCarriesTheAddress:
    """A fleet record without an email is unusable by every email-addressed lane.

    Pass-through, never derived: an address guessed from a directory name looks right and is wrong.
    """

    def test_every_record_carries_an_email_key(self, fleet):
        """Mutant (2026-09-27, killed): the `"email"` key dropped from the record."""
        records = rs.fleet_branches(fleet)
        assert len(records) >= 3, f"too few records to exercise the record shape: {records}"
        addressless = [r["name"] for r in records if "email" not in r]
        assert addressless == [], f"records with no email key: {addressless}"

    def test_the_email_is_the_registrys_verbatim_not_derived_from_the_name(self, tmp_path):
        """A row whose address looks nothing like its name or its directory."""
        _write(
            tmp_path / "AIPASS_REGISTRY.json",
            _registry({"name": "ALPHA", "path": "src/aipass/alpha", "email": "@not-the-name", "status": "active"}),
        )
        _write(tmp_path / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
        (record,) = rs.fleet_branches(tmp_path)
        assert record["email"] == "@not-the-name"

    def test_a_row_with_no_email_keeps_the_branch_and_reports_none(self, tmp_path):
        """Addressless is a condition to hand on, not a reason to drop a citizen."""
        _write(
            tmp_path / "AIPASS_REGISTRY.json",
            _registry({"name": "ALPHA", "path": "src/aipass/alpha", "status": "active"}),
        )
        _write(tmp_path / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
        (record,) = rs.fleet_branches(tmp_path)
        assert record["name"] == "alpha"
        assert record["email"] is None

    def test_the_live_fleet_is_addressable_end_to_end(self, live_fleet):
        """Every live citizen's registry row carries an address."""
        records = rs.fleet_branches(live_fleet)
        assert "memory" in {r["name"] for r in records}, "live discovery missed this branch -- this proved nothing"
        unaddressed = [r["name"] for r in records if not r.get("email")]
        assert unaddressed == [], f"live citizens with no address in their registry row: {unaddressed}"

    def test_each_record_gets_its_own_rows_address_not_a_neighbours(self, tmp_path):
        """Three rows, three addresses, none guessable from its own name.

        Pinned by pairing, not presence: a mutant handing every record the first row's email survived.
        """
        rows = [
            {"name": "ALPHA", "path": "src/aipass/alpha", "email": "@third", "status": "active"},
            {"name": "BETA", "path": "src/aipass/beta", "email": "@first", "status": "active"},
            {"name": "GAMMA", "path": "src/aipass/gamma", "email": "@second", "status": "active"},
        ]
        _write(tmp_path / "AIPASS_REGISTRY.json", _registry(*rows))
        for row in rows:
            _write(tmp_path / row["path"] / ".trinity" / "passport.json", _passport("core"))
        found = {record["name"]: record["email"] for record in rs.fleet_branches(tmp_path)}
        assert found == {"alpha": "@third", "beta": "@first", "gamma": "@second"}


class TestMalformedJsonDeclaresNothingAndNeverRaises:
    """A file that parses as JSON but is the wrong SHAPE must refuse, not crash.

    An uncaught raise here takes out every fleet lane at once, not one branch.
    Every root is pinned separately: a fix tested against a list alone lets a string through.
    """

    @pytest.mark.parametrize(
        "label, document",
        [
            ("list", "[]"),
            ("string", '"resident"'),
            ("number", "7"),
            ("null", "null"),
            ("bool", "true"),
        ],
    )
    def test_a_non_dict_passport_root_declares_nothing(self, tmp_path, label, document):
        """Five roots, not the three reported: null and bool raise too."""
        branch = tmp_path / f"branch_{label}"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(document, encoding="utf-8")
        assert rs.declared_residency(branch) is None

    @pytest.mark.parametrize(
        "label, document",
        [
            ("string", '{"citizenship": "core"}'),
            ("list", '{"citizenship": []}'),
            ("number", '{"citizenship": 1}'),
        ],
    )
    def test_a_non_dict_citizenship_block_declares_nothing(self, tmp_path, label, document):
        """The second `.get` on the same line had the same defect."""
        branch = tmp_path / f"branch_cz_{label}"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(document, encoding="utf-8")
        assert rs.declared_residency(branch) is None

    @pytest.mark.parametrize(
        "label, document",
        [
            ("list root", "[]"),
            ("string root", '"whatever"'),
            ("number root", "7"),
            ("null root", "null"),
            ("branches is a mapping", '{"branches": {"alpha": 1}}'),
            ("branches is a string", '{"branches": "alpha"}'),
            # Non-iterable values raise at the `for` itself, where no row guard reaches;
            # without them a mutant dropping the list guard survived. A present null skips the default.
            ("branches is a number", '{"branches": 7}'),
            ("branches is a bool", '{"branches": true}'),
            ("branches is null", '{"branches": null}'),
            ("a branch is a string", '{"branches": ["alpha"]}'),
            ("a branch is a list", '{"branches": [[]]}'),
        ],
    )
    def test_a_malformed_registry_yields_no_branches(self, tmp_path, label, document):
        """The registry reader has the same defect and nobody had tested it.

        The registry is the sealed anchor; a registry that crashes the reader takes the anchor with it.
        """
        registry = tmp_path / f"{label.replace(' ', '_')}_REGISTRY.json"
        registry.write_text(document, encoding="utf-8")
        assert rs.read_registry_branches(registry) == []

    def test_a_malformed_row_is_skipped_and_the_good_rows_survive(self, tmp_path):
        """One bad row must cost one row, not the whole registry."""
        registry = tmp_path / "MIXED_REGISTRY.json"
        registry.write_text(
            json.dumps(
                {
                    "branches": [
                        "not-a-dict-at-all",
                        {"name": "GOOD", "path": "src/good", "email": "@good", "status": "active"},
                        {"name": "BADPATH", "path": 123, "email": "@badpath", "status": "active"},
                        {"name": "INACTIVE", "path": "src/inactive", "status": "retired"},
                    ]
                }
            ),
            encoding="utf-8",
        )
        found = rs.read_registry_branches(registry, name_from="name")
        assert [record["name"] for record in found] == ["GOOD"]

    def test_a_non_string_name_or_address_never_reaches_the_record(self, tmp_path):
        """Wrong TYPE is a wrong answer, not a crash -- and it is still wrong."""
        registry = tmp_path / "TYPES_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": 42, "path": "src/alpha", "email": ["@a"], "status": "active"}]}),
            encoding="utf-8",
        )
        (record,) = rs.read_registry_branches(registry, name_from="name")
        assert record["name"] == "alpha"
        assert record["email"] is None


# REPO_ROOT resolves at import, so a registry-less tree in a dead cwd must not crash or
# guess: the root derives from this file's location, never the process, and says so at WARNING.


class TestRepoRootNeverReadsTheProcessDirectory:
    """A registry-less world must resolve, deterministically, without cwd.

    Runs on every platform, Windows included — see ``_PROBE`` for why the world
    is built by denying ``getcwd`` rather than by deleting a directory.
    """

    # Denying getcwd, not deleting the cwd: Windows locks a process's directory against rmdir.
    # The world is imported from tests/dead_cwd.py and goes BEFORE `import pathlib` (3.10 captures getcwd).
    _PROBE = "{world}import sys, pathlib\nsys.path.insert(0, {src!r})\n{body}\n"

    @classmethod
    def _in_a_dead_cwd(cls, body):
        """Run *body* in a subprocess that cannot read its working directory."""
        src = str(Path(rs.__file__).resolve().parents[6])
        return subprocess.run(
            [sys.executable, "-c", cls._PROBE.format(world=DEAD_CWD_WORLD, src=src, body=body)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )

    def test_find_repo_root_survives_a_deleted_working_directory(self, tmp_path):
        """@drone's isolated repro, exactly: no registry above, no cwd beneath."""
        bare = tmp_path / "bare"
        bare.mkdir()
        result = self._in_a_dead_cwd(
            "from aipass.memory.apps.handlers.monitor import registry_scope as rs\n"
            f"print('OK', rs.find_repo_root(pathlib.Path({str(bare)!r})))"
        )
        assert result.returncode == 0, (
            "find_repo_root died in a dead cwd. "
            + (
                "THE CRASH IS IN @prax, not here — cured 2026-08-31, so this is a regression "
                "in their tree. Route it there.\n"
                if "/aipass/prax/" in result.stderr
                else ""
            )
            + result.stderr
        )
        assert "OK" in result.stdout, result.stdout

    def test_importing_the_module_survives_a_deleted_working_directory(self):
        """The CI chain: REPO_ROOT is resolved at import, so import is the crash site.

        Cannot go red on a machine with a registry above this file; it is the CI shape, kept hard (no xfail).
        """
        result = self._in_a_dead_cwd(
            "from aipass.memory.apps.handlers.monitor import registry_scope as rs\nprint('OK', rs.REPO_ROOT)"
        )
        assert result.returncode == 0, (
            "importing registry_scope died in a dead cwd. "
            + (
                "THE CRASH IS IN @prax, not here — cured 2026-08-31, so this is a regression "
                "in their tree. Route it there.\n"
                if "/aipass/prax/" in result.stderr
                else ""
            )
            + result.stderr
        )

    def test_a_registryless_world_resolves_to_the_source_tree_not_the_caller(self, tmp_path, monkeypatch):
        """The QUIET defect: cwd is a guess about where the code lives."""
        bare = tmp_path / "bare"
        bare.mkdir()
        monkeypatch.chdir(tmp_path)

        resolved = rs.find_repo_root(bare)

        assert resolved != tmp_path, "the caller's directory is not a repo root"
        assert resolved == Path(rs.__file__).resolve().parents[6], (
            "a registry-less world must resolve from this file's own location"
        )

    def test_the_missing_registry_is_said_out_loud(self, tmp_path, caplog):
        """A fallback nobody can see is the species this whole sweep is about."""
        bare = tmp_path / "bare"
        bare.mkdir()

        with caplog.at_level(logging.WARNING):
            rs.find_repo_root(bare)

        assert rs.CORE_REGISTRY in caplog.text, "the walk failed silently"

    def test_a_real_registry_still_wins(self, tmp_path):
        """The fallback must not shadow an answer the walk can actually find."""
        root = tmp_path / "repo"
        (root / "src" / "aipass").mkdir(parents=True)
        (root / rs.CORE_REGISTRY).write_text("{}", encoding="utf-8")

        assert rs.find_repo_root(root / "src" / "aipass") == root


class TestTheResidentWalkReadsNamesNotSpellings:
    """A case-insensitive filesystem must not widen the resident registry glob.

    A case-insensitive glob is wider than the rule it spells, and here it ADMITS a resident.
    See ``case_insensitive_filesystem`` in conftest for why this is injected rather than skipped.
    """

    def test_the_injected_world_really_widens(self, fleet, case_insensitive_filesystem):
        """Positive control: a blinded emulation reports green exactly like a cure."""
        _write(fleet / "projects/live/flow_json_registry.json", _registry(_branch("mirage", "src/mirage/mirage")))

        matched = sorted(path.name for path in (fleet / "projects").glob(rs.RESIDENT_REGISTRY_GLOB))

        assert "flow_json_registry.json" in matched and "LIVE_REGISTRY.json" in matched

    def test_a_lowercase_registry_is_not_discovered(self, fleet, case_insensitive_filesystem):
        _write(fleet / "projects/live/flow_json_registry.json", _registry(_branch("mirage", "src/mirage/mirage")))

        found = [path.name for path in rs.resident_registry_paths(fleet)]

        assert "flow_json_registry.json" not in found
        assert "LIVE_REGISTRY.json" in found

    def test_a_lowercase_registry_never_mints_a_resident(self, fleet, case_insensitive_filesystem):
        """The end-to-end shape: presence in the wrong file must not reach the fleet."""
        _write(fleet / "projects/live/flow_json_registry.json", _registry(_branch("mirage", "src/mirage/mirage")))
        _write(fleet / "projects/live/src/mirage/mirage/.trinity/passport.json", _passport("resident"))

        names = {Path(path).name for path in rs.accepted_resident_paths(fleet)}

        assert "mirage" not in names
        assert "live" in names, "the real resident was lost while excluding the impostor"


class TestAnUnreadableCoreRegistryNeverHandsOverANamesake:
    """The name-keyed write lanes refuse when the core registry cannot be read.

    A resident ``alpha`` must never become the only answer for the core citizen ``alpha``'s backlog.
    """

    @staticmethod
    def _namesake_world(fleet: Path) -> Path:
        """The fixture's repo with a resident ``alpha`` and an unreadable core registry; returns that registry."""
        _write(fleet / "projects/twin/TWIN_REGISTRY.json", _registry(_branch("alpha", "src/twin/alpha")))
        _write(fleet / "projects/twin/src/twin/alpha/.trinity/passport.json", _passport("resident"))
        core = fleet / "AIPASS_REGISTRY.json"
        core.write_text("{not json", encoding="utf-8")
        return core

    def test_the_todo_lane_refuses_rather_than_resolve_the_namesake(self, fleet, monkeypatch):
        core = self._namesake_world(fleet)
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: fleet)

        target = todo_roll.resolve_target("alpha")

        assert (target["name"], target["path"], target["backlog"]) == (None, None, None)
        assert target["error"].startswith(f"REFUSED: Unreadable registry {core}: ")

    def test_the_push_lane_refuses_rather_than_resolve_the_namesake(self, fleet, monkeypatch):
        core = self._namesake_world(fleet)
        monkeypatch.setattr(trinity_push, "_REPO_ROOT", fleet)

        scope = trinity_push.resolve_scope("alpha")

        assert scope["branches"] == []
        assert scope["error"].startswith(f"REFUSED: Unreadable registry {core}: ")

    def test_control_a_readable_core_registry_still_resolves(self, fleet, monkeypatch):
        """The control: the same lanes answer the core citizen when its registry reads."""
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: fleet)
        monkeypatch.setattr(trinity_push, "_REPO_ROOT", fleet)

        assert todo_roll.resolve_target("alpha")["path"] == fleet / "src/aipass/alpha"
        assert [item["path"] for item in trinity_push.resolve_scope("alpha")["branches"]] == [
            fleet / "src/aipass/alpha"
        ]

    def test_an_absent_core_registry_is_no_refusal(self, fleet, monkeypatch):
        """A fresh clone has no core registry: the residents still resolve."""
        (fleet / "AIPASS_REGISTRY.json").unlink()
        monkeypatch.setattr(todo_roll, "_find_repo_root", lambda: fleet)
        monkeypatch.setattr(trinity_push, "_REPO_ROOT", fleet)

        assert todo_roll.resolve_target("live")["path"] == fleet / "projects/live/src/live/live"
        assert [item["path"] for item in trinity_push.resolve_scope("live")["branches"]] == [
            fleet / "projects/live/src/live/live"
        ]
