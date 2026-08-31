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
import logging
import subprocess
import sys
from collections import Counter
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

        The non-empty guard is the whole test. A depth rule asserted inside a
        loop is proven by the paths that ENTER it, so a discovery returning
        nothing passes this green while checking nothing at all.
        """
        found = rs.resident_registry_paths(fleet)
        assert found, "discovery returned nothing, so the depth rule was never exercised"
        for path in found:
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

    def test_the_named_resident_tuple_is_gone_from_the_branch(self):
        """It decided nothing for a wave; now it does not exist.

        The constant survived DPLAN-0319 only because @ai_mail's mirror
        AST-parsed the assignment. That mirror landed on 2026-08-28, so the
        anchor went with it. This is the pin that used to say "no lane may
        SELECT on it" — with the tuple deleted the honest claim is stronger and
        simpler: the name appears nowhere, so nothing can quietly grow a second
        definition out of it again.
        """
        offenders = []
        for path in sorted(self._APPS.rglob("*.py")):
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
                if "RESIDENT_REGISTRIES" in line:
                    offenders.append(f"{path.relative_to(self._APPS)}:{number}: {line.strip()}")
        assert not offenders, "the retired resident tuple is back:\n  " + "\n  ".join(offenders)

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

    def test_discovery_names_exactly_the_four_resident_projects(self, live_residents):
        """What the deleted anchor used to be compared against, measured directly.

        The old version diffed discovery against the demoted tuple, which made
        it a test of two constants agreeing. With the tuple gone the claim is
        about the machine: these four projects, no more, no fewer.
        """
        found = {path.parent.name for path in rs.resident_registry_paths(live_residents)}
        assert found == {"baud", "earmark", "finch", "aipass-site"}

    def test_the_live_fleet_is_eighteen_core_and_four_residents(self, live_residents):
        """Counted BY TIER now, not by total — and the change is the point.

        This asserted a flat 22 until the external tier landed, and it went red
        on the first run afterwards because the fleet legitimately grew. Pinning
        a total made the guard a tripwire for its own feature: the two numbers it
        was written to protect (18 core, 4 residents) were never what it read.

        So it counts what it means, and the external tier is asserted against
        the DECLARATION rather than a number — this machine happens to declare
        four roots today and that is Patrick's to change without breaking a test
        in my branch.
        """
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

        Counted, not just iterated: two nested loops over live discovery mean
        two chances to check nothing. The fixture already skips when the
        registries are missing, so reaching here with a count of zero is a
        different failure — discovery found the files and read no branches out
        of them — and it must not read as agreement.
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

    Asked for by @daemon (dispatch 16fbf1c0) and ruled in their favour: the row
    is already read and the field already thrown away, so resolving it anywhere
    else would mean a second reader of the same registry rows — the exact defect
    this module exists to end.  @ai_mail is email-addressed too, so shipping the
    record without it would strand both of the lanes 2.0.0 was meant to converge.

    Pass-through, never derived.  ``name`` may come from the directory, and an
    address guessed from a directory name is a wrong answer that looks right.
    """

    def test_every_record_carries_an_email_key(self, fleet):
        records = rs.fleet_branches(fleet)
        assert records, "nothing was discovered, so the record shape was never exercised"
        addressless = [r["name"] for r in records if "email" not in r]
        assert not addressless, f"records with no email key: {addressless}"

    def test_the_email_is_the_registrys_verbatim_not_derived_from_the_name(self, tmp_path):
        """A row whose address looks nothing like its name or its directory.

        ``@daemon`` asked for the field; this pins WHERE it comes from. Both
        plausible derivations — lowercase the name, or read the directory —
        produce a different string here, so either one fails this outright.
        """
        _write(
            tmp_path / "AIPASS_REGISTRY.json",
            _registry({"name": "ALPHA", "path": "src/aipass/alpha", "email": "@not-the-name", "status": "active"}),
        )
        _write(tmp_path / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
        (record,) = rs.fleet_branches(tmp_path)
        assert record["email"] == "@not-the-name"

    def test_a_row_with_no_email_keeps_the_branch_and_reports_none(self, tmp_path):
        """Addressless is a condition to hand on, not a reason to drop a citizen.

        Path-based lanes (trinity_push, rollover) never touch the address, so
        dropping the branch here would break them to protect a caller that has
        not asked yet.  The record reports ``None`` and the caller refuses on
        its own terms.  Measured on the live fleet at 22 of 22 rows carrying an
        address, so this is the shape of a future defect, not today's.
        """
        _write(
            tmp_path / "AIPASS_REGISTRY.json",
            _registry({"name": "ALPHA", "path": "src/aipass/alpha", "status": "active"}),
        )
        _write(tmp_path / "src/aipass/alpha/.trinity/passport.json", _passport("core"))
        (record,) = rs.fleet_branches(tmp_path)
        assert record["name"] == "alpha"
        assert record["email"] is None

    def test_the_live_fleet_is_addressable_end_to_end(self, live_fleet):
        """The guard that would have caught this before @daemon had to ask."""
        records = rs.fleet_branches(live_fleet)
        assert records, "live discovery returned nothing -- this proved nothing"
        unaddressed = [r["name"] for r in records if not r.get("email")]
        assert not unaddressed, f"live citizens with no address in their registry row: {unaddressed}"

    def test_each_record_gets_its_OWN_rows_address_not_a_neighbours(self, tmp_path):
        """Three rows, three addresses, none guessable from its own name.

        Found by mutation: a version handing every record the FIRST row's email
        survived every other test in this class, because the single-row
        registries above cannot see a cross-row mixup and the live guard only
        asks whether an address is present. For an email-addressed scheduler
        that mutant is the worst available failure — every job would wake a real
        citizen, just never the right one — so it is pinned by pairing, not by
        presence.
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

    Reported by @daemon (dispatch 5031a591) against declared_residency, and the
    provenance is the point: their deleted reader had an explicit isinstance
    guard that mine never had. Removing the duplicate removed the stricter of
    two implementations, and nobody knew which one was stricter.

    Why it is fleet-wide rather than branch-local: declared_residency is called
    once per core citizen by fleet_branches and once per candidate by
    _accepted_residents, and read_registry_branches is called for every registry
    in scope. An uncaught raise in either does not refuse ONE branch -- it takes
    out rollover, lint, health, trinity_push and @daemon's scheduler together,
    with a traceback naming this module rather than the file that is wrong.

    The module docstring is the specification being broken: an unreadable
    passport "declares NOTHING and does not raise". A non-dict root is
    unreadable in every sense that matters.

    Every root is pinned separately. @daemon's own suite pinned only "[]", and a
    fix tested against a list alone would have let a string root through -- so
    the parametrisation is the test, not decoration.
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
        """The second `.get` on the same line had the same defect.

        `data.get("citizenship", {}).get("residency")` guards an ABSENT block
        with its default and a PRESENT-but-wrong one not at all, so fixing only
        the root would have left the identical crash one key deeper. Not in
        @daemon's report -- found by reading the line that was reported.
        """
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
            # The three NON-ITERABLE values. Found by mutation: with only the
            # mapping and string cases above, deleting the `branches` list guard
            # SURVIVED, because iterating a dict or a string still yields items
            # and the row guard below catches every one of them. A number, a
            # bool or an explicit null raises TypeError at the `for` itself,
            # where no row guard can ever reach. `null` is the live shape of the
            # three: `data.get("branches", [])` returns None when the key is
            # PRESENT and null, so the default never fires.
            ("branches is a number", '{"branches": 7}'),
            ("branches is a bool", '{"branches": true}'),
            ("branches is null", '{"branches": null}'),
            ("a branch is a string", '{"branches": ["alpha"]}'),
            ("a branch is a list", '{"branches": [[]]}'),
        ],
    )
    def test_a_malformed_registry_yields_no_branches(self, tmp_path, label, document):
        """The registry reader has the same defect and nobody had tested it.

        Worse than the passport case, because a registry is the SEALED ANCHOR:
        the passport is agent-written and expected to be wrong sometimes, while
        every lane trusts the registry to be the thing a passport cannot forge.
        A registry that crashes the reader takes the anchor with it.
        """
        registry = tmp_path / f"{label.replace(' ', '_')}_REGISTRY.json"
        registry.write_text(document, encoding="utf-8")
        assert rs.read_registry_branches(registry) == []

    def test_a_malformed_row_is_skipped_and_the_good_rows_survive(self, tmp_path):
        """One bad row must cost one row, not the whole registry.

        This is the difference between refusing and crashing, stated as a test:
        a fleet where one typo hides every other citizen is not failing honestly,
        it is failing loudly in the wrong place.
        """
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
        """Wrong TYPE is a wrong answer, not a crash -- and it is still wrong.

        Neither of these raises, so they would have survived the guard above.
        An int name breaks any caller that formats it, and a non-string address
        is unmailable; @daemon consumes both. Name falls back to the directory,
        which is a real answer; an address has no honest fallback, so it is None
        and the caller refuses on its own terms.
        """
        registry = tmp_path / "TYPES_REGISTRY.json"
        registry.write_text(
            json.dumps({"branches": [{"name": 42, "path": "src/alpha", "email": ["@a"], "status": "active"}]}),
            encoding="utf-8",
        )
        (record,) = rs.read_registry_branches(registry, name_from="name")
        assert record["name"] == "alpha"
        assert record["email"] is None


# ===========================================================================
# THE MODULE-LEVEL CWD FALLBACK (2026-08-31)
# ===========================================================================
#
# @drone, routed by @devpulse with an isolated repro: `find_repo_root` ends
# `return Path.cwd()` when the walk up from `__file__` finds no
# AIPASS_REGISTRY.json, and `REPO_ROOT = find_repo_root()` runs at MODULE
# level. A clean checkout has no registry — it is gitignored and machine-local
# — so a bare CI runner takes that fallback on every import, and a process
# whose working directory has been deleted raises FileNotFoundError while
# merely IMPORTING this module.
#
# It took down every import of drone on CI — router, `drone rm`, `drone
# systems` — because their registry_handler imported the gateway at module
# level. They contained their half honestly (the import moved inside the guard
# that already promised the gateway could not take routing down) and reported
# the line as mine rather than patching my tree. It is mine, and it was latent
# for every other consumer.
#
# TWO DEFECTS IN ONE LINE. The crash is the loud one. The quiet one is that
# `Path.cwd()` is a GUESS: the directory a process happened to start in has
# nothing to do with where this source file lives, so on a registry-less tree
# every fleet lane would silently resolve against whatever the caller's shell
# was pointing at. That is the fallback species Patrick outlawed — the same
# ruling as `_first_registry_in`, "a fallback wearing a determinism costume".
#
# THE ANSWER: the root is derived from THIS FILE's own location, never from the
# process. `src/` is the layout's own marker, so a registry-less checkout
# resolves to the checkout — which is the true answer there, not a guess — and
# the absence is said out loud at WARNING rather than passed over.


class TestRepoRootNeverReadsTheProcessDirectory:
    """A registry-less world must resolve, deterministically, without cwd."""

    _PROBE = (
        "import os, sys, tempfile, pathlib\n"
        "sys.path.insert(0, {src!r})\n"
        "d = tempfile.mkdtemp()\n"
        "os.chdir(d); os.rmdir(d)\n"  # the working directory is now gone
        "{body}\n"
    )

    @classmethod
    def _in_a_dead_cwd(cls, body):
        """Run *body* in a subprocess whose working directory has been deleted.

        A subprocess because the condition is process-wide and unfixable from
        inside: once cwd is gone, every `Path.cwd()` in the interpreter raises,
        including pytest's own. Deleting the test runner's cwd would take the
        suite with it.
        """
        src = str(Path(rs.__file__).resolve().parents[6])
        return subprocess.run(
            [sys.executable, "-c", cls._PROBE.format(src=src, body=body)],
            capture_output=True,
            text=True,
        )

    def test_find_repo_root_survives_a_deleted_working_directory(self, tmp_path):
        """@drone's isolated repro, exactly: no registry above, no cwd beneath."""
        bare = tmp_path / "bare"
        bare.mkdir()
        result = self._in_a_dead_cwd(
            "from aipass.memory.apps.handlers.monitor import registry_scope as rs\n"
            f"print('OK', rs.find_repo_root(pathlib.Path({str(bare)!r})))"
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout, result.stdout

    def test_importing_the_module_survives_a_deleted_working_directory(self):
        """The CI chain: REPO_ROOT is resolved at import, so import is the crash site.

        Honest about its own reach: on a machine that HAS a registry above this
        file the walk succeeds and the fallback is never taken, so this pin
        cannot go red here. It is the CI shape, kept because that is the
        environment the defect lives in and a test that only runs where the bug
        cannot happen is the one nobody writes until after the outage.
        """
        result = self._in_a_dead_cwd(
            "from aipass.memory.apps.handlers.monitor import registry_scope as rs\nprint('OK', rs.REPO_ROOT)"
        )
        assert result.returncode == 0, result.stderr

    def test_a_registryless_world_resolves_to_the_source_tree_not_the_caller(self, tmp_path, monkeypatch):
        """The QUIET defect: cwd is a guess about where the code lives.

        Stand in a directory that is not the repo and ask about a tree with no
        registry. The old answer was "wherever you happen to be standing".
        """
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
