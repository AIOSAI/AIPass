# =================== AIPass ====================
# Name: test_residency_scope.py
# Description: Red-first pins for passport-declared residency as the fleet classifier (DPLAN-0319)
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Residency is DECLARED in a passport and ANCHORED in a registry. Both, or out.

DPLAN-0318 defined the fleet with a named 4-tuple of resident registries. That
constant did one job the passport field cannot do on its own: it kept
``marketstand`` out. ``marketstand``'s registry still marks its branch
``active`` while the project itself is parked, so anything that trusted a
registry status field alone would sweep a held project into every rollover,
lint and push in the system.

Wave 3 replaces the constant as the CLASSIFIER, not as the exclusion. The
semantics these tests pin:

DISCOVERY is registry-led and shallow. Candidates are exactly
``projects/<project>/<NAME>_REGISTRY.json`` — one level under ``projects/``,
with any dot-prefixed path component refused. Never a passport walk.

    That is not a stylistic preference. On this machine a passport walk under
    ``projects/`` returns EIGHT passports for FOUR residents: ``baud`` alone
    carries two more under ``.backup/versioned/`` and ``.backup/snapshots/``,
    each a byte-identical copy declaring ``residency: resident``. A backup copy
    of a passport is a real passport making a real declaration. Discovery that
    starts from passports counts baud three times; discovery that starts from
    registries reads a passport only at a path a registry declared.

CLASSIFICATION reads ``citizenship.residency`` off the passport at that
registry-declared path. ``resident`` is included; anything else is refused and
named — missing passport, unreadable passport, absent field, ``core`` (a core
citizen cannot also be a resident), or a value nobody defined.

THE TRUST MODEL, which decides who wins when they disagree. A passport is
agent-writable; a registry is not. So the passport can never ADD scope on its
own — a declared resident that no discovered registry lists is not reachable by
construction, because nothing walks passports. And for core citizens the sealed
registry is the anchor: a core citizen missing the field is LOGGED, never
dropped, because letting an agent edit its own passport to leave the
maintenance fleet is the same defect pointed the other way.

EXCLUSION holds three deep, and each layer alone is enough to keep
``marketstand`` out: it lives under a dot-directory, its passport declares no
residency, and its registry is not at glob depth one. The tests below assert
each layer independently, so removing one cannot quietly open the door on the
strength of another still standing.
"""

import json
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.monitor import registry_scope as rs


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

    Built rather than mocked: the classifier's whole job is reading two files
    off disk in a particular relationship, and a mock of that relationship
    would test the mock.
    """
    root = tmp_path / "repo"

    # Core: the sealed registry, one citizen declaring core and one declaring
    # nothing — the second is the "never drop a core citizen" case.
    _write(
        root / "AIPASS_REGISTRY.json",
        _registry(_branch("alpha", "src/aipass/alpha"), _branch("beta", "src/aipass/beta")),
    )
    _write(root / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
    _write(root / "src/aipass/beta/.trinity/passport.json", _passport(None))

    # A genuine resident: registry lists it, passport declares it.
    _write(root / "projects/live/LIVE_REGISTRY.json", _registry(_branch("live", "src/live/live")))
    _write(root / "projects/live/src/live/live/.trinity/passport.json", _passport("resident"))

    # A backup copy of that same passport, declaring resident, exactly as baud
    # carries on the live machine. Registry-led discovery must never reach it.
    _write(root / "projects/live/.backup/versioned/src/live/live/.trinity/passport.json", _passport("resident"))
    _write(root / "projects/live/.backup/LIVE_REGISTRY.json", _registry(_branch("live", "src/live/live")))

    # Listed active, declares nothing — the undeclared case.
    _write(root / "projects/mute/MUTE_REGISTRY.json", _registry(_branch("mute", "src/mute/mute")))
    _write(root / "projects/mute/src/mute/mute/.trinity/passport.json", _passport(None))

    # Listed active, claims to be a core citizen from inside projects/.
    _write(root / "projects/impostor/IMPOSTOR_REGISTRY.json", _registry(_branch("impostor", "src/impostor/impostor")))
    _write(root / "projects/impostor/src/impostor/impostor/.trinity/passport.json", _passport("core"))

    # Listed active, no passport on disk at all.
    _write(root / "projects/ghost/GHOST_REGISTRY.json", _registry(_branch("ghost", "src/ghost/ghost")))

    # Listed active, passport declares a value nobody defined.
    _write(root / "projects/martian/MARTIAN_REGISTRY.json", _registry(_branch("martian", "src/martian/martian")))
    _write(root / "projects/martian/src/martian/martian/.trinity/passport.json", _passport("visitor"))

    # THE MARKETSTAND SHAPE: archived, registry still says active, and — worse
    # than the real one — its passport DOES declare resident. If the dot-dir
    # rule ever stops holding, this is what walks in.
    _write(root / "projects/.archive/stale/STALE_REGISTRY.json", _registry(_branch("stale", "src/stale/stale")))
    _write(root / "projects/.archive/stale/src/stale/stale/.trinity/passport.json", _passport("resident"))

    # TWO SINGLE-LAYER CASES, and they exist because the first mutation run on
    # this file proved the marketstand shape needs BOTH layers gone before
    # anything changes. Deleting the dot-prefix filter left every test green,
    # and so did widening the glob to `**`, because each mutation was masked by
    # the layer the fixture still tripped. Defence in depth hides single-layer
    # regressions unless something is excluded by exactly one layer.

    # Dot-prefixed AT depth one: matches the `*/*` glob, so only the dot filter
    # keeps it out.
    _write(root / "projects/.hidden/HIDDEN_REGISTRY.json", _registry(_branch("hidden", "src/hidden/hidden")))
    _write(root / "projects/.hidden/src/hidden/hidden/.trinity/passport.json", _passport("resident"))

    # Nested one level too deep with no dot anywhere: only the shallow glob
    # keeps it out.
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

        ``projects/live/.backup/LIVE_REGISTRY.json`` is excluded twice over, by
        depth and by dot-directory. Asserted on depth alone here so the two
        rules cannot be mistaken for one.
        """
        for path in rs.resident_registry_paths(fleet):
            assert len(path.relative_to(fleet / "projects").parts) == 2, f"discovered below depth one: {path}"

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

        The passport is agent-writable. If an absent field could remove a
        citizen from the maintenance fleet, an agent could stop its own
        memories being rolled over by deleting one line of its own file.
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

        Only the dot-prefix filter stops it, which makes this the test that
        actually holds that filter. The marketstand shape does not: it is three
        parts deep, so the shallow glob refuses it whether the filter exists or
        not — and a mutation run proved exactly that by deleting the filter and
        watching every test stay green.
        """
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "hidden" not in names, "a dot-prefixed project at depth one was swept in"

    def test_layer_two_alone_the_shallow_glob_excludes_a_nested_project(self, fleet):
        """``projects/live/nested/`` carries no dot, so only the depth rule refuses it."""
        names = {item["name"] for item in rs.fleet_branches(fleet)}
        assert "nested" not in names, "discovery descended past one level"

    def test_layer_three_the_registry_status_field_is_not_trusted_alone(self, fleet):
        """The stale registry says ``active``. That is the field that lied.

        Read directly so the claim is about the FIXTURE's honesty: if this ever
        stops saying active, the exclusion tests above stop proving anything.
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
    """Convergence pinned, because a split definition is how this started.

    Before DPLAN-0318 the push resolved its own scope and the registry lane
    resolved another, and they disagreed by three citizens for months without
    anything saying so. Both had a defensible implementation; neither was
    wrong on its own terms. That is what makes duplicate policy dangerous —
    it does not look like a bug until you count.
    """

    _APPS = Path(__file__).resolve().parents[1] / "apps"

    def test_no_lane_selects_on_the_demoted_constant(self):
        """It may be re-exported and compared. It may not decide anything.

        ``RESIDENT_REGISTRIES`` survives only as a drift anchor for @ai_mail's
        mirror. The moment a LANE iterates it again, classification has been
        quietly reverted there while every other lane reads passports — the
        two-implementations-that-agree-by-coincidence state, restored.

        ``registry_scope.py`` is exempt and checked separately below: it owns
        the constant, and one function in it is supposed to read the thing.
        """
        offenders = []
        for path in sorted(self._APPS.rglob("*.py")):
            if path.name == "registry_scope.py":
                continue
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "RESIDENT_REGISTRIES" not in line:
                    continue
                if line.lstrip().startswith(("#", "*", '"')) or "= registry_scope." in line:
                    continue
                offenders.append(f"{path.name}:{number}: {line.strip()}")
        assert not offenders, "a lane is selecting on the demoted constant again:\n  " + "\n  ".join(offenders)

    def test_only_the_drift_reporter_reads_it_inside_the_definition_module(self):
        """The exemption above, bounded — otherwise it is a hole rather than a rule.

        Exactly one function may mention the constant: ``_report_drift``, whose
        whole job is to compare it against what discovery found and say so when
        they disagree. Anything else reading it there is selection wearing a
        comparison's clothes.
        """
        source = (self._APPS / "handlers" / "monitor" / "registry_scope.py").read_text(encoding="utf-8")
        body = source[source.index("RESIDENT_REGISTRIES = (") :]
        readers = []
        current = "<module level>"
        for line in body.splitlines():
            if line.startswith("def "):
                current = line[4:].split("(")[0]
            if "RESIDENT_REGISTRIES" in line and not line.lstrip().startswith("#"):
                readers.append(current)
        assert set(readers) <= {"<module level>", "_report_drift"}, f"unexpected readers: {sorted(set(readers))}"

    def test_the_push_lane_resolves_through_registry_scope(self):
        source = (self._APPS / "handlers" / "templates" / "trinity_push.py").read_text(encoding="utf-8")
        body = source[source.index("def resolve_scope(") :]
        assert "registry_scope.fleet_branches(" in body, "the push lane has its own scope resolution again"

    def test_the_detector_filters_residents_through_the_classifier(self, fleet, monkeypatch):
        """BEHAVIOURAL, and it started as a source pin that proved nothing.

        The first version asserted ``accepted_resident_paths(`` appeared in the
        function. A mutation that deleted the FILTER but kept the assignment
        line sailed straight through it — the string was still there, the
        classification was gone, 29 tests green. Reading the code under test
        is not the same as running it, and grep-shaped pins fail exactly where
        it matters: on a change that keeps the words and drops the behaviour.
        """
        from aipass.memory.apps.handlers.monitor import detector

        monkeypatch.setattr(detector, "_REPO_ROOT", fleet)
        monkeypatch.setattr(detector, "_find_caller_registries", lambda: [])
        names = {Path(branch["path"]).name for branch in detector._read_registry()}

        assert "live" in names, "the declared resident never reached the detector lane"
        for refused in ("mute", "impostor", "ghost", "martian", "stale", "hidden", "nested"):
            assert refused not in names, f"the detector lane swept in {refused}"

    def test_accepted_resident_paths_holds_only_the_declared(self, fleet):
        """The shared classifier, exercised directly rather than through a caller."""
        accepted = rs.accepted_resident_paths(fleet)
        assert accepted == {str(fleet / "projects/live/src/live/live")}

    def test_the_caller_lane_is_deliberately_not_classified(self):
        """External callers are a different mechanism — pinned so it stays a choice.

        A future reader tightening "everything must declare residency" would
        break an external project calling in from its own tree, which never had
        a passport in this fleet to declare anything with.
        """
        source = (self._APPS / "handlers" / "monitor" / "detector.py").read_text(encoding="utf-8")
        caller_loop = source[source.index("for reg_path in _find_caller_registries():") :]
        assert "accepted" not in caller_loop.split("return branches")[0]


class TestTheLiveFleetStillCountsTwentyTwo:
    """The receipt the dispatch asked for, measured rather than asserted."""

    def test_discovery_and_the_demoted_anchor_still_agree(self, live_residents):
        """If these ever diverge, the transition changed the fleet — say so here."""
        discovered = {str(path) for path in rs.resident_registry_paths(live_residents)}
        anchored = {str(live_residents / relative) for relative in rs.RESIDENT_REGISTRIES}
        assert discovered == anchored

    def test_the_live_fleet_is_eighteen_core_and_four_residents(self, live_residents):
        branches = rs.fleet_branches(live_residents)
        residents = [item for item in branches if f"/{rs.RESIDENT_PROJECTS_DIR}/" in str(item["path"])]
        assert (len(branches), len(residents)) == (22, 4), [item["name"] for item in branches]

    def test_every_live_resident_declares_itself_one(self, live_residents):
        """The declaration is the classifier now — so it had better be there."""
        for registry_path in rs.resident_registry_paths(live_residents):
            for item in rs.read_registry_branches(registry_path):
                assert rs.declared_residency(item["path"]) == rs.RESIDENCY_RESIDENT, (
                    f"{item['name']} is in fleet scope but its passport does not declare it"
                )

    def test_the_archived_projects_are_still_on_disk_and_still_out(self, live_fleet):
        """The exclusion is only proven where the thing being excluded exists."""
        archive = live_fleet / rs.RESIDENT_PROJECTS_DIR / ".archive"
        if not archive.is_dir():
            pytest.skip(f"no {archive} on this machine -- live-state guard skipped")
        stale = [path for path in archive.glob("*/*_REGISTRY.json")]
        assert stale, "the archive carries no registries, so it cannot prove the exclusion"
        names = {item["name"] for item in rs.fleet_branches(live_fleet)}
        assert "marketstand" not in names and "speakeasy" not in names
