# =================== AIPass ====================
# Name: test_declared_roots.py
# Description: Pins the declared-roots anchor and the external tier it opens
# Version: 1.0.2
# Created: 2026-08-30
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/monitor/registry_scope.py — the declared-roots anchor and the external tier."""

# Repos outside this one join the fleet by DECLARATION, never by being nearby. Membership is
# PRESENCE (a passport in a declared root's registry), never a residency field. Declared roots
# only, never a walk at any depth: a walk counts every backup copy of every passport.
# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(covered_elsewhere) — registry_scope.resident_registry_paths(); tests/test_residency_scope.py
# seedgo: no-test-needed(covered_elsewhere) — registry_scope.overlaps_home(); tests/test_roots_lifecycle.py

import json
from pathlib import Path

import pytest

from aipass.memory.apps.handlers import repo_root
from aipass.memory.apps.handlers.monitor import registry_scope as rs
from aipass.memory.apps.modules import fleet


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
    """A synthetic machine: one AIPass repo and three siblings beside it, built on disk, never mocked."""
    home = tmp_path / "AIPass"
    _write(home / "AIPASS_REGISTRY.json", _registry(_branch("alpha", "src/aipass/alpha")))
    _write(home / "src/aipass/alpha/.trinity/passport.json", {"citizenship": {"residency": "core"}})

    # A genuine external repo; NEITHER citizen declares a residency.
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
        """The double-count guard: our own tree as an external root would return every citizen twice."""
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
        """One bad row costs one row, never the whole file (a GOOD row rides alongside each bad one)."""
        _write(machine / rs.DECLARED_ROOTS, _roots(row, _root_row("../Demo")))
        assert [path.name for path in rs.declared_roots(machine)] == ["Demo"]


class TestDeclarationOrderSurvivesToTheDoor:
    """An N-root tie is broken by DECLARATION order, never alphabetical by resolved path."""

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

    def test_a_root_declared_twice_keeps_its_first_position(self, machine):
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
        # Path.parts, never a string split: separators are an OS detail (Windows).
        roots = [next((name for name in ("wren", "Demo") if name in path.parts), None) for path in visited]
        assert {"wren", "Demo"} <= set(roots), f"both roots must contribute citizens, got {visited}"
        assert roots.index("wren") < roots.index("Demo")


class TestARetiredCitizenStaysRetired:
    """Retiring is a REGISTRY act: a passport on disk (e.g. under .archive/) cannot say its citizen is live."""

    def test_an_archived_passport_is_not_a_citizen(self, machine):
        """An archived passport under a declared root is never a citizen."""
        _write(machine.parent / "wren/src/.archive/ghosttown/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        names = sorted(item["name"].lower() for item in rs.external_branches(machine))
        assert names == ["quiet", "wren"], "only the registry's live citizens, and never the archived passport"

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
        """The external record's shape is pinned: no scheduler flag, and no field nobody consumes."""
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
        """A refusal's log line names the tier it refused from; its words are behaviour."""
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))
        with caplog.at_level("ERROR"):
            rs.external_branches(machine)
        refusals = [record.getMessage() for record in caplog.records if "REFUSED" in record.getMessage()]
        assert refusals, "the passportless branch was refused silently"
        assert any(f"REFUSED {rs.RESIDENCY_EXTERNAL} 'ghost'" in line for line in refusals), refusals

    def test_two_registries_in_one_root_is_a_refusal_not_a_pick(self, machine):
        """Two registries in one root: the root contributes nothing and says so, never a pick or a merge."""
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
        for name in ("declared_roots", "external_branches", "RESIDENCY_EXTERNAL", "DECLARED_ROOTS"):
            assert getattr(fleet, name) is getattr(rs, name), f"{name} is not the handler's own object"


class TestTheLiveMachineIsReachable:
    """The acceptance case against the REAL sibling repos; never writes AIPASS_ROOTS.json into the repo."""

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

    def test_no_live_external_citizen_declares_a_residency_it_does_not_hold(self):
        """Live guard: no external citizen declares a residency that contradicts presence (core/resident)."""
        projects = rs.find_repo_root().parent
        contradicting = []
        for repo in ("wren", "Vera-Studio", "Demo", "feel_good_app"):
            root = projects / repo
            if not root.is_dir():
                continue
            for registry in root.glob("*_REGISTRY.json"):
                for item in rs.read_registry_branches(registry, name_from="name"):
                    declared = rs.declared_residency(item["path"])
                    if declared not in (None, rs.RESIDENCY_EXTERNAL):
                        contradicting.append((item["name"], declared))
        assert contradicting == [], (
            f"external citizens declare a residency they do not hold: {contradicting} -- revisit the presence rule"
        )


class TestACaseInsensitiveFilesystemCannotWidenTheWalk:
    """``*_REGISTRY.json`` is a rule about names, and a glob is not that rule.

    A case-folding glob would make a declared root refuse (count is meaning). Decoys use a DIFFERENT
    stem: a case-only twin cannot coexist on a folding filesystem and overwrites the real registry.
    """

    def test_the_injected_world_really_widens(self, machine, case_insensitive_filesystem):
        """Positive control: the emulated raw glob really returns the lowercase neighbour."""
        wren = machine.parent / "wren"
        _write(wren / "flow_json_registry.json", _registry(_branch("mirage", "src/mirage")))

        matched = sorted(path.name for path in wren.glob(rs.EXTERNAL_REGISTRY_GLOB))

        assert matched == ["WREN_REGISTRY.json", "flow_json_registry.json"]

    def test_a_lowercase_neighbour_does_not_make_a_root_ambiguous(self, machine, case_insensitive_filesystem):
        """The defect: one stray filename, and every citizen behind it is gone."""
        wren = machine.parent / "wren"
        _write(wren / "flow_json_registry.json", _registry(_branch("mirage", "src/mirage")))
        _write(wren / "src/mirage/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../wren")))

        names = {item["name"] for item in rs.external_branches(machine)}

        assert "wren" in names, "the declared root refused itself over a file it does not declare"
        assert "mirage" not in names, "a lowercase registry was read as though it spelled the rule"

    def test_a_lowercase_registry_is_not_a_root_s_only_registry(self, machine, case_insensitive_filesystem):
        """A root carrying ONLY a lowercase name carries none: absence, said out loud."""
        lonely = machine.parent / "Lonely"
        _write(lonely / "flow_json_registry.json", _registry(_branch("nobody", "src/nobody")))
        _write(lonely / "src/nobody/.trinity/passport.json", {"citizenship": {}})
        _write(machine / rs.DECLARED_ROOTS, _roots(_root_row("../Lonely")))

        assert rs.external_branches(machine) == []


class TestTheExactCaseFilterIsAboutNamesNotPlatforms:
    """The predicate on its own (repo_root.exactly_named), on every platform, with no filesystem at all."""

    def test_it_keeps_the_exact_case_and_drops_every_other_spelling(self, tmp_path):
        candidates = [
            tmp_path / "x" / "AIPASS_REGISTRY.json",
            tmp_path / "x" / "WREN_REGISTRY.json",
            tmp_path / "x" / "wren_registry.json",
            tmp_path / "x" / "Wren_Registry.Json",
            tmp_path / "x" / "WREN_REGISTRY.JSON",
        ]

        kept = repo_root.exactly_named(candidates, rs.CORE_REGISTRY_SUFFIX)

        assert [path.name for path in kept] == ["AIPASS_REGISTRY.json", "WREN_REGISTRY.json"]

    def test_the_suffix_has_to_end_the_name_not_merely_appear_in_it(self, tmp_path):
        """A backup beside the registry is not a registry: the suffix must END the name.

        Equivalent mutant: ``str(path).endswith`` survives (the suffix has no separator); ``.name`` states the rule.
        """
        kept = repo_root.exactly_named(
            [tmp_path / "x" / "AIPASS_REGISTRY.json.bak", tmp_path / "x" / "AIPASS_REGISTRY.json"],
            rs.CORE_REGISTRY_SUFFIX,
        )

        assert [path.name for path in kept] == ["AIPASS_REGISTRY.json"]

    def test_it_narrows_and_never_reorders(self, tmp_path):
        """The walk sorts before filtering; the filter must not undo that (``B``/``aa`` reverse under lower())."""
        candidates = [
            tmp_path / "x" / "B_REGISTRY.json",
            tmp_path / "x" / "skip_registry.json",
            tmp_path / "x" / "aa_REGISTRY.json",
        ]

        kept = repo_root.exactly_named(candidates, rs.CORE_REGISTRY_SUFFIX)

        assert kept == [tmp_path / "x" / "B_REGISTRY.json", tmp_path / "x" / "aa_REGISTRY.json"]


class TestWhatTheHostCanActuallyHold:
    """Probe, not assumption: which spellings this host's filesystem can hold at once; never skipif."""

    def test_two_names_differing_only_by_case_may_be_one_file(self, tmp_path):
        (tmp_path / "A_REGISTRY.json").write_text("first", encoding="utf-8")
        (tmp_path / "a_registry.json").write_text("second", encoding="utf-8")

        entries = sorted(path.name for path in tmp_path.iterdir())

        if len(entries) == 1:
            # Folding host: the entry keeps the ORIGINAL spelling and the CONTENT is replaced.
            assert entries == ["A_REGISTRY.json"], entries
            assert (tmp_path / "A_REGISTRY.json").read_text(encoding="utf-8") == "second"
        else:
            assert entries == ["A_REGISTRY.json", "a_registry.json"]

    def test_a_differing_stem_is_always_a_second_file(self, tmp_path):
        """The property every case-glob pin in this branch relies on."""
        (tmp_path / "A_REGISTRY.json").write_text("first", encoding="utf-8")
        (tmp_path / "flow_json_registry.json").write_text("second", encoding="utf-8")

        assert len(list(tmp_path.iterdir())) == 2
