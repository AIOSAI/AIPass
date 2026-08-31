# =================== AIPass ====================
# Name: test_declared_roots.py
# Description: Pins the declared-roots anchor and the external tier it opens
# Version: 1.0.0
# Created: 2026-08-30
# Modified: 2026-08-30
# =============================================

"""Repos outside this one join the fleet by DECLARATION, never by being nearby.

FPLAN-0460 phase 2. Patrick's ruling, verbatim: "if .daemon is present anywhere
on the machine and an agent exists there, daemon should be available - its really
that simple." @devpulse gave the GO on the mechanism @drone and I reached
independently: AIPass home declares which repo roots participate.

WHAT THE GO CHANGED ABOUT MY OWN EARLIER RULING. I ruled that passport 2.0 needed
a third ``citizenship.residency`` value before external citizens could be seen.
That ruling made a schema migration and a six-owner declaration campaign into a
PRECONDITION for a working feature, and the GO retired it as one. So membership
here is PRESENCE, not declaration: a branch in a declared root is a citizen if
``.trinity/passport.json`` exists. None of the six live external citizens has a
residency field, and gating on one would have shipped nothing.

WHAT DID NOT CHANGE, and it is the law this module was built on: DECLARED roots
only, never a walk, at any depth. The reason is measured rather than asserted - a
passport walk of our own ``projects/`` returns eight passports for four
residents, because @baud carries copies under ``.backup/``. The same walk across
a machine would count every snapshot of every repo.

The two candidate anchors that were REJECTED, both because they had already
failed in production: ``ai_mail``'s contacts.json accretes by last_seen, carries
dead April entries and does not contain @wren at all; and my own
``known_registries.json`` persisted a deleted /tmp scratchpad probe while missing
Vera-Studio's real registry. An anchor that has to be right cannot be one that
accumulates by accident.
"""

import json
from pathlib import Path

import pytest

from aipass.memory.apps.handlers.monitor import registry_scope as rs


def _write(path: Path, document: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8")


def _registry(*branches: dict) -> dict:
    return {"metadata": {"name": "TEST"}, "branches": list(branches)}


def _branch(name: str, path: str, status: str = "active") -> dict:
    return {"name": name.upper(), "path": path, "email": f"@{name}", "status": status}


def _roots(*rows: dict) -> dict:
    return {"metadata": {"version": "1.0.0"}, "roots": list(rows)}


def _root_row(path: str, label: str = "x", status: str = "active") -> dict:
    return {"path": path, "label": label, "status": status}


@pytest.fixture
def machine(tmp_path):
    """A synthetic machine: one AIPass repo and three siblings beside it.

    Built on disk rather than mocked, for the same reason the residency fixture
    is: this module's entire job is reading real files in a particular
    relationship to each other, and a mock of that relationship tests the mock.
    """
    home = tmp_path / "AIPass"
    _write(home / "AIPASS_REGISTRY.json", _registry(_branch("alpha", "src/aipass/alpha")))
    _write(home / "src/aipass/alpha/.trinity/passport.json", {"citizenship": {"residency": "core"}})

    # A genuine external repo: own sealed registry, two citizens, one of which
    # opts in to the scheduler. NEITHER declares a residency -- that is the
    # point of the GO.
    wren = tmp_path / "wren"
    _write(wren / "WREN_REGISTRY.json", _registry(_branch("wren", "src/wren"), _branch("quiet", "src/quiet")))
    _write(wren / "src/wren/.trinity/passport.json", {"citizenship": {"registered": True}})
    _write(wren / "src/wren/.daemon/schedule.json", {"jobs": []})
    _write(wren / "src/quiet/.trinity/passport.json", {"citizenship": {"registered": True}})

    # Listed active in its registry and has NO passport: not a citizen.
    _write(
        wren / "WREN_REGISTRY.json",
        _registry(_branch("wren", "src/wren"), _branch("quiet", "src/quiet"), _branch("ghost", "src/ghost")),
    )

    # A second external repo, to prove roots are independent of each other.
    demo = tmp_path / "Demo"
    _write(demo / "DEMO_REGISTRY.json", _registry(_branch("solo", "src/solo")))
    _write(demo / "src/solo/.trinity/passport.json", {"citizenship": {}})

    # Never declared. Exists, is a valid repo, and must stay invisible.
    undeclared = tmp_path / "Undeclared"
    _write(undeclared / "UNDECLARED_REGISTRY.json", _registry(_branch("nobody", "src/nobody")))
    _write(undeclared / "src/nobody/.trinity/passport.json", {"citizenship": {}})

    return home


class TestTheAnchorIsADeclarationNotADiscovery:
    """Zero roots is a legal state. A root nobody declared is not a root."""

    def test_no_roots_file_is_not_an_error(self, machine):
        assert rs.declared_roots(machine) == []

    def test_an_undeclared_sibling_stays_invisible(self, machine):
        """The whole point, stated as a test: proximity is not membership."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        found = {path.name for path in rs.declared_roots(machine)}
        assert found == {"wren"}
        assert (machine.parent / "Undeclared").is_dir(), "the negative case is not on disk to be proven"

    def test_relative_paths_resolve_against_the_repo_root(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        assert sorted(path.name for path in rs.declared_roots(machine)) == ["Demo", "wren"]

    def test_an_absolute_path_is_accepted(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row(str(machine.parent / "wren"))))
        assert [path.name for path in rs.declared_roots(machine)] == ["wren"]

    def test_a_root_inside_this_repo_is_refused(self, machine):
        """The double-count guard, and it is not hypothetical.

        Declaring our own tree as an external root would return every core
        citizen and every resident a second time under a different tier. @baud
        would appear three times: once as a resident, once here, and once more
        through the backup copy the walk law already refuses.
        """
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("."), _root_row("src"), _root_row("../wren")))
        assert [path.name for path in rs.declared_roots(machine)] == ["wren"]

    def test_the_same_root_declared_twice_is_one_root(self, machine):
        _write(
            machine / rs.DECLARED_ROOTS,
            _roots(_root_row("../wren"), _root_row(str(machine.parent / "wren")), _root_row("../wren/")),
        )
        assert len(rs.declared_roots(machine)) == 1

    @pytest.mark.parametrize(
        "label, row",
        [
            ("retired", {"path": "../wren", "status": "retired"}),
            ("no status", {"path": "../wren"}),
            ("missing directory", {"path": "../nowhere", "status": "active"}),
            ("path is a file", {"path": "../AIPass/AIPASS_REGISTRY.json", "status": "active"}),
            ("path is empty", {"path": "", "status": "active"}),
            ("path is not a string", {"path": 7, "status": "active"}),
            ("row is not an object", "../wren"),
        ],
    )
    def test_every_unusable_row_is_skipped_and_the_good_one_survives(self, machine, label, row):
        """One bad row costs one row. Never the whole file.

        Parametrised with a GOOD row alongside each bad one on purpose: a
        reader that returned [] on any defect would pass a test that only
        checked the bad row was absent.
        """
        _write(machine / rs.DECLARED_ROOTS, _roots(row, _root_row("../Demo")))
        assert [path.name for path in rs.declared_roots(machine)] == ["Demo"]


class TestDeclarationOrderSurvivesToTheDoor:
    """@ai_mail's abe8141b, answered in code.

    The fleet ruling says an N-root tie is broken by DECLARATION order, but
    this reader used to hand back ``sorted(found)`` — alphabetical by resolved
    path. @ai_mail found the gap the honest way: they reported that the order
    reaching their door could not be the order the ruling names, and refused to
    guess at it. They were right, and the reader was wrong.

    Alphabetical-by-resolved-path is an accident of what someone named a
    directory. The row order in the anchor is a statement: a human wrote these
    rows in this sequence. Both are deterministic — only one carries intent, so
    only one can break a tie the ruling says intent breaks.
    """

    def test_roots_come_back_in_the_order_they_were_declared(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        assert [path.name for path in rs.declared_roots(machine)] == ["wren", "Demo"]

    def test_the_reverse_declaration_gives_the_reverse_order(self, machine):
        """Paired with the above so alphabetical order cannot pass both."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../Demo"), _root_row("../wren")))
        assert [path.name for path in rs.declared_roots(machine)] == ["Demo", "wren"]

    def test_a_skipped_row_does_not_reorder_the_rows_that_survive(self, machine):
        """Refusals close the gap in place; they never shuffle the remainder."""
        _write(
            machine / rs.DECLARED_ROOTS,
            _roots(_root_row("../wren"), _root_row("../nowhere"), _root_row("../Demo")),
        )
        assert [path.name for path in rs.declared_roots(machine)] == ["wren", "Demo"]

    def test_a_root_declared_twice_keeps_its_FIRST_position(self, machine):
        """Dedup by first occurrence — a later duplicate cannot promote a root."""
        _write(
            machine / rs.DECLARED_ROOTS,
            _roots(_root_row("../wren"), _root_row("../Demo"), _root_row("../wren/")),
        )
        assert [path.name for path in rs.declared_roots(machine)] == ["wren", "Demo"]

    def test_the_external_walk_visits_roots_in_declaration_order(self, machine):
        """The order has to survive the caller too, or the fix stops at the reader."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        visited = [Path(item["path"]) for item in rs.external_branches(machine)]
        # Path.parts, never a string split. A separator is an OS detail, and
        # asking "/wren/" of a path spelled with backslashes answers no on
        # Windows for every root — which read as "no citizens" rather than as
        # "the test cannot see them".
        roots = [next((name for name in ("wren", "Demo") if name in path.parts), None) for path in visited]
        assert {"wren", "Demo"} <= set(roots), f"both roots must contribute citizens, got {visited}"
        assert roots.index("wren") < roots.index("Demo")


class TestARetiredCitizenStaysRetired:
    """@spawn's archive hazard, measured on the real machine and pinned here.

    Preparing their external migration, @spawn checked the obvious extension of
    their resident glob -- ``src/*/*/.trinity/passport.json`` -- against the live
    fleet and found FIVE archived passports under Vera-Studio's
    ``src/.archive/``. A passport walk would have "found" 11 external citizens
    where the fleet has 6, and offered to write into five directories somebody
    deliberately retired.

    Measured against the live machine at the time of writing: the passport walk
    returns 9 Vera-Studio branches, the registry-led walk returns 4. That gap is
    the whole argument. A passport on disk cannot tell you whether its citizen
    is live -- retiring is a REGISTRY act, so only the registry knows. This is
    why the walk law is a law and not a preference, and it is pinned
    synthetically here so the rule survives without depending on anyone's
    machine still having that .archive directory.
    """

    def test_an_archived_passport_is_not_a_citizen(self, machine):
        _write(machine.parent / "wren/src/.archive/ghosttown/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        names = [item["name"] for item in rs.external_branches(machine)]
        assert "ghosttown" not in [n.lower() for n in names], names
        assert names, "the live citizens must still be found -- an empty result would pass vacuously"

    def test_a_registry_that_retired_a_branch_does_not_return_it(self, machine):
        """The registry is the authority on liveness, and it is consulted."""
        root = machine.parent / "wren"
        _write(
            root / "WREN_REGISTRY.json",
            _registry(_branch("live", "src/live"), _branch("gone", "src/gone", status="retired")),
        )
        for who in ("live", "gone"):
            _write(root / f"src/{who}/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        names = [item["name"].lower() for item in rs.external_branches(machine)]
        assert "live" in names and "gone" not in names, names


class TestAMalformedAnchorRefusesInsteadOfCrashing:
    """Same discipline as the registry reader: the anchor must never take a lane down."""

    @pytest.mark.parametrize(
        "document",
        [
            "[]",
            '"roots"',
            "7",
            "null",
            "true",
            '{"roots": {"a": 1}}',
            '{"roots": "x"}',
            '{"roots": 7}',
            '{"roots": null}',
            "not json at all",
        ],
    )
    def test_a_malformed_roots_file_declares_nothing(self, machine, document):
        (machine / rs.DECLARED_ROOTS).write_text(document, encoding="utf-8")
        assert rs.declared_roots(machine) == []


class TestMembershipIsPresenceNotDeclaration:
    """The GO's ruling, pinned: a passport on disk makes a citizen. No field required."""

    def test_a_citizen_with_no_residency_field_is_included(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        names = {item["name"] for item in rs.external_branches(machine)}
        assert names == {"wren", "quiet"}

    def test_a_listed_branch_without_a_passport_is_not_a_citizen(self, machine):
        """`ghost` is active in wren's registry and has no .trinity/ at all."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        assert "ghost" not in {item["name"] for item in rs.external_branches(machine)}

    def test_every_external_record_is_labelled_external(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        found = rs.external_branches(machine)
        assert found, "nothing was discovered, so the label was never exercised"
        assert {item["residency"] for item in found} == {rs.RESIDENCY_EXTERNAL}

    def test_the_record_carries_no_scheduler_flag(self, machine):
        """Withdrawn 2026-08-30 at the request of the only branch that asked for it.

        The field reported ONE FILENAME -- whether `.daemon/schedule.json`
        exists. @daemon reads `.daemon/*.json`, every file in there. So a
        consumer using this as a pre-filter would silently drop every job
        living in a differently-named file, and it would read as "this citizen
        has no jobs" rather than as a bug. @daemon's words: a field that is
        nearly right is worse than no field.

        It bought nothing either -- their discovery opens what it globs
        regardless, so a bool cannot save a stat they have to do anyway.

        This pin is the shape, not the absence of one key: a record that grows
        a field nobody consumes should have to come past a test.
        """
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        found = rs.external_branches(machine)
        assert found, "nothing was discovered, so the record shape was never exercised"
        for item in found:
            assert set(item) == {"name", "path", "registry", "email", "residency"}, item

    def test_roots_are_independent_of_each_other(self, machine):
        """A broken root must cost its own citizens and nobody else's."""
        (machine.parent / "Demo" / "DEMO_REGISTRY.json").write_text("[]", encoding="utf-8")
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        assert {item["name"] for item in rs.external_branches(machine)} == {"wren", "quiet"}

    def test_a_refusal_names_the_tier_it_refused_from(self, machine, caplog):
        """A log line is the whole product of a refusal, so its words are behaviour.

        Found by mutation: swapping the tier word in the refusal survived every
        other test here, because nothing read the line. An external citizen
        logged as a REFUSED resident sends whoever greps for it into
        ``projects/``, looking for a branch that lives in another repository.
        """
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        with caplog.at_level("ERROR"):
            rs.external_branches(machine)
        refusals = [record.getMessage() for record in caplog.records if "REFUSED" in record.getMessage()]
        assert refusals, "the passportless branch was refused silently"
        assert any(f"REFUSED {rs.RESIDENCY_EXTERNAL} 'ghost'" in line for line in refusals), refusals

    def test_two_registries_in_one_root_is_a_refusal_not_a_pick(self, machine):
        """Ambiguity is refused by name, never resolved alphabetically.

        Raised by @drone (mail f94e63af) against their own code: their
        ``_first_registry_in`` does ``sorted(glob)[0]``, which they called a
        fallback wearing a determinism costume — a second registry in a root
        would be silently ignored and nobody would ever learn which one lost.
        They recommended I not copy it.

        Merging the two would be worse than picking: it invents a union nobody
        declared and makes the root's own fleet a thing only this reader knows.
        So the ROOT contributes nothing and says so, and the other roots are
        unaffected — one ambiguous root costs one root.

        Measured before pinning: all three live roots hold exactly one registry,
        so this is the shape of a future defect, not today's.
        """
        _write(machine.parent / "wren" / "EXTRA_REGISTRY.json", _registry(_branch("extra", "src/extra")))
        _write(machine.parent / "wren/src/extra/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren"), _root_row("../Demo")))
        assert {item["name"] for item in rs.external_branches(machine)} == {"solo"}

    def test_a_root_with_no_registry_is_named_not_guessed(self, machine):
        """No registry means no citizens -- never a passport walk to find some."""
        bare = machine.parent / "Bare"
        _write(bare / "src/someone/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../Bare")))
        assert rs.external_branches(machine) == []


class TestDiscoveryInsideARootIsShallowAndRegistryLed:
    """The walk law, carried across the repo boundary unchanged."""

    def test_a_registry_one_level_down_is_not_found(self, machine):
        """Depth zero only. A registry under a subdirectory is somebody's copy."""
        nested = machine.parent / "Nested"
        _write(nested / "sub" / "NESTED_REGISTRY.json", _registry(_branch("deep", "src/deep")))
        _write(nested / "sub/src/deep/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../Nested")))
        assert rs.external_branches(machine) == []

    def test_a_backup_copy_of_a_passport_is_never_reached(self, machine):
        """@baud's shape, one repo over. Registry-led means the copy is unreachable."""
        _write(machine.parent / "wren/.backup/src/wren/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        paths = [str(item["path"]) for item in rs.external_branches(machine)]
        assert not any(".backup" in path for path in paths)


class TestTheFleetGrowsWithoutMovingUnderneathAnyone:
    """Adding a tier must not change what the existing tiers answer."""

    def test_with_no_roots_file_the_fleet_is_exactly_what_it_was(self, machine):
        before = rs.fleet_branches(machine)
        _write(machine / rs.DECLARED_ROOTS, _roots())
        assert rs.fleet_branches(machine) == before

    def test_externals_join_the_fleet(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        names = {item["name"] for item in rs.fleet_branches(machine)}
        assert names == {"alpha", "wren", "quiet"}

    def test_every_record_carries_its_tier(self, machine):
        """@daemon asked for source labels so external never silently reads as core."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        tiers = {item["name"]: item["residency"] for item in rs.fleet_branches(machine)}
        assert tiers == {"alpha": rs.RESIDENCY_CORE, "wren": rs.RESIDENCY_EXTERNAL, "quiet": rs.RESIDENCY_EXTERNAL}

    def test_an_external_root_that_is_this_repo_cannot_double_count(self, machine):
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row(".")))
        assert [item["name"] for item in rs.fleet_branches(machine)] == ["alpha"]


class TestTheGatewayCarriesTheNewSurface:
    """@daemon consumes through modules/fleet.py and must not need a second import."""

    def test_the_new_names_are_on_the_public_gateway(self):
        from aipass.memory.apps.modules import fleet

        for name in ("declared_roots", "external_branches", "RESIDENCY_EXTERNAL", "DECLARED_ROOTS"):
            assert getattr(fleet, name) is getattr(rs, name), f"{name} is not the handler's own object"


class TestTheLiveMachineIsReachable:
    """The acceptance case, driven against the REAL sibling repos on this disk.

    Deliberately does not write ``AIPASS_ROOTS.json`` into the repo: that file is
    Patrick's to bless and populate, and a test that creates it would both
    pre-empt him and make the anchor look self-installing. So the roots file is
    written to a throwaway copy of the repo root instead, pointed at the real
    external repos, which proves the reader against real registries and real
    passports without putting anything in the tree.
    """

    def test_wren_and_vera_studio_are_reachable_when_declared(self, tmp_path):
        live_home = rs.find_repo_root()
        projects = live_home.parent
        wanted = {"wren": projects / "wren", "Vera-Studio": projects / "Vera-Studio"}
        missing = [name for name, path in wanted.items() if not path.is_dir()]
        if missing:
            pytest.skip(f"external repos not installed on this machine: {missing} -- live guard skipped")

        stand_in = tmp_path / "AIPass"
        stand_in.mkdir()
        (stand_in / "AIPASS_REGISTRY.json").write_text(
            (live_home / "AIPASS_REGISTRY.json").read_text(encoding="utf-8"), encoding="utf-8"
        )
        _write(
            stand_in / rs.DECLARED_ROOTS,
            _roots(
                {"path": str(wanted["wren"]), "label": "wren", "status": "active"},
                {"path": str(wanted["Vera-Studio"]), "label": "vera-studio", "status": "active"},
            ),
        )

        found = {item["name"]: item for item in rs.external_branches(stand_in)}
        assert "wren" in found, f"@wren is the fence citizen and must be reachable; got {sorted(found)}"
        assert "vera" in found, f"@vera must be reachable; got {sorted(found)}"
        assert all(item["residency"] == rs.RESIDENCY_EXTERNAL for item in found.values())
        assert all(item["email"] for item in found.values()), "external citizens must be addressable"

    def test_no_live_external_citizen_declares_a_residency(self):
        """The measurement the GO acted on, kept as a live guard.

        If this ever goes red it means the schema campaign happened after all,
        and the presence rule can be revisited on evidence rather than memory.
        """
        projects = rs.find_repo_root().parent
        declared = []
        for repo in ("wren", "Vera-Studio", "Demo", "feel_good_app"):
            root = projects / repo
            if not root.is_dir():
                continue
            for registry in root.glob("*_REGISTRY.json"):
                for item in rs.read_registry_branches(registry, name_from="name"):
                    if rs.declared_residency(item["path"]) is not None:
                        declared.append(item["name"])
        assert not declared, (
            f"external citizens now declare a residency: {declared} -- the presence rule can be revisited"
        )


class TestACaseInsensitiveFilesystemCannotWidenTheWalk:
    """``*_REGISTRY.json`` is a rule about names, and a glob is not that rule.

    @drone hit this on the Windows CI leg: their own tree carries a real
    lowercase ``..._registry.json``, and Windows globs case-insensitively, so
    the pattern matched a file the rule excludes. @devpulse routed the question
    to every walk owner. Both of mine were exposed.

    IT IS NOT A COSMETIC WIDENING HERE, which is why it earns pins rather than
    a note. Both walks read the match COUNT as meaning: zero registries at a
    declared root is an error, and more than one is a named refusal rather than
    a ``sorted()[0]`` pick. So a spurious lowercase neighbour does not add a
    stray citizen — it silently turns a root that works on Linux into a root
    that refuses on Windows, and every citizen behind it vanishes from the
    fleet with a message blaming the repo owner for a file they never wrote.
    """

    def test_the_injected_world_really_widens(self, machine, case_insensitive_filesystem):
        """The positive control: prove the fixture has teeth before trusting it.

        A blinded instrument reports green for the same reason a cured defect
        does. This asserts the raw glob — no filter — genuinely returns the
        lowercase neighbour, so the pins below are testing a real widening and
        not an emulation that quietly does nothing.
        """
        wren = machine.parent / "wren"
        _write(wren / "wren_registry.json", _registry(_branch("mirage", "src/mirage")))

        matched = sorted(path.name for path in wren.glob(rs.EXTERNAL_REGISTRY_GLOB))

        assert matched == ["WREN_REGISTRY.json", "wren_registry.json"]

    def test_a_lowercase_neighbour_does_not_make_a_root_ambiguous(self, machine, case_insensitive_filesystem):
        """The defect: one stray filename, and every citizen behind it is gone."""
        wren = machine.parent / "wren"
        _write(wren / "wren_registry.json", _registry(_branch("mirage", "src/mirage")))
        _write(wren / "src/mirage/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))

        names = {item["name"] for item in rs.external_branches(machine)}

        assert "wren" in names, "the declared root refused itself over a file it does not declare"
        assert "mirage" not in names, "a lowercase registry was read as though it spelled the rule"

    def test_a_lowercase_registry_is_not_a_root_s_only_registry(self, machine, case_insensitive_filesystem):
        """A root carrying ONLY a lowercase name carries none: absence, said out loud.

        The complement of the case above, and the one that would look like a
        fix if the filter were written as "drop the extras". There is nothing
        to keep here, and the walk has to reach the no-registry error rather
        than read the file.
        """
        lonely = machine.parent / "Lonely"
        _write(lonely / "lonely_registry.json", _registry(_branch("nobody", "src/nobody")))
        _write(lonely / "src/nobody/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../Lonely")))

        assert rs.external_branches(machine) == []


class TestTheExactCaseFilterIsAboutNamesNotPlatforms:
    """The predicate on its own, on every platform, with no filesystem at all."""

    def test_it_keeps_the_exact_case_and_drops_every_other_spelling(self):
        candidates = [
            Path("/x/AIPASS_REGISTRY.json"),
            Path("/x/WREN_REGISTRY.json"),
            Path("/x/wren_registry.json"),
            Path("/x/Wren_Registry.Json"),
            Path("/x/WREN_REGISTRY.JSON"),
        ]

        kept = rs._exactly_named(candidates, rs.CORE_REGISTRY_SUFFIX)

        assert [path.name for path in kept] == ["AIPASS_REGISTRY.json", "WREN_REGISTRY.json"]

    def test_the_suffix_has_to_END_the_name_not_merely_appear_in_it(self):
        """A backup beside the registry is not a registry.

        ``in`` instead of ``endswith`` reads ``AIPASS_REGISTRY.json.bak`` as the
        fleet and hands a stale document to every lane behind this walk. It is
        the one substitution in this predicate a test can actually see.

        AN EQUIVALENT MUTANT, recorded because a mutation run that reports it as
        killed is lying and the next reader deserves the reason. Swapping
        ``path.name.endswith(suffix)`` for ``str(path).endswith(suffix)``
        SURVIVES every test in this class, and no test can kill it: the suffix
        contains no separator, so a full path can only end with it when its last
        component does. The two are the same function on any input. ``.name`` is
        written anyway because it says what the rule IS — a rule about
        filenames — and the equivalence is a property of this suffix rather than
        a promise the next one will keep.
        """
        kept = rs._exactly_named(
            [Path("/x/AIPASS_REGISTRY.json.bak"), Path("/x/AIPASS_REGISTRY.json")], rs.CORE_REGISTRY_SUFFIX
        )

        assert [path.name for path in kept] == ["AIPASS_REGISTRY.json"]

    def test_it_narrows_and_never_reorders(self):
        """The walk sorts before filtering; the filter must not undo that.

        The sample is deliberately one a case-folding re-sort would reverse
        (``B`` before ``aa`` by ASCII, after it by ``lower()``). A first draft
        used ``A``/``C`` and a re-sorting mutant survived it — any order-blind
        sample makes an order claim that cannot fail.
        """
        candidates = [Path("/x/B_REGISTRY.json"), Path("/x/skip_registry.json"), Path("/x/aa_REGISTRY.json")]

        kept = rs._exactly_named(candidates, rs.CORE_REGISTRY_SUFFIX)

        assert kept == [Path("/x/B_REGISTRY.json"), Path("/x/aa_REGISTRY.json")]
