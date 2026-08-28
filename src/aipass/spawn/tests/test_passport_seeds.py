# =================== META ====================
# Name: test_passport_seeds.py
# Description: TDPLAN-0017 — passport seeds: export, validation, mint-from-seed
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Passport seeds — the tracked identity that ships with the repo (TDPLAN-0017).

Four properties carry the whole feature, and each is pinned on its own because
each could be lost alone:

* the export STRIPS EXACTLY the four machine-local facts — no more (an identity
  silently thinned) and no less (a credential leaked into a tracked file);
* the export is IDEMPOTENT — a second run writes nothing at all, which is what
  makes a generated tracked file safe to regenerate in anger;
* a mint from a seed produces a VALID 2.0 passport with FRESH local ids and a
  stamp naming the exact seed file bytes it came from;
* an INVALID seed refuses loudly and writes NOTHING — a citizen never lands on
  disk holding a malformed identity.
"""

import hashlib
import json
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers import seed_ops
from aipass.spawn.apps.handlers.passport_migration import KEY_ORDER
from aipass.spawn.apps.handlers.seed_ops import (
    MACHINE_LOCAL_CITIZENSHIP,
    STAMP_KEY,
    SeedError,
    build_seed,
    canonical_text,
    export_seeds,
    find_seed,
    load_seed,
    mint_from_seed,
    seed_fingerprint,
    seed_path_for,
    seed_stamp,
    validate_passport,
    validate_seed,
)

MACHINE_REGISTRY_ID = "11111111-1111-4111-8111-111111111111"
MACHINE_CITIZEN_ID = "22222222-2222-4222-8222-222222222222"


def make_passport(branch: str = "wanderer") -> dict:
    """A live 2.0 passport, in canonical order — the shape the fleet carries."""
    return {
        "document_metadata": {
            "document_type": "branch_identity",
            "document_name": f"{branch}.PASSPORT",
            "version": "2.0.0",
            "schema_version": "2.0.0",
            "created": "2026-03-05",
            "last_updated": "2026-08-28",
            "managed_by": branch,
            "tags": ["identity", "passport", "branch_profile"],
        },
        "branch_info": {
            "branch_name": branch,
            "alias": "",
            "path": f"src/aipass/{branch}",
            "module": f"aipass.{branch}",
            "email": f"@{branch}",
            "created": "2026-03-05",
            "git_branch": "dev",
        },
        "citizenship": {
            "registered": True,
            "residency": "core",
            "registry_id": MACHINE_REGISTRY_ID,
            "citizen_id": MACHINE_CITIZEN_ID,
            "registry_path": ".aipass/registry.json",
            "communications": True,
            "memory": True,
        },
        "identity": {
            "citizen_class": "specialist",
            "role": "wanderer",
            "purpose": "Walks the fleet — an identity worth shipping.",
            "what_i_do": ["Walk", "Report"],
            "what_i_dont_do": ["Guess"],
            "traits": ["curious"],
            "principles": ["Code is truth - fail honestly"],
        },
    }


def write_repo(root: Path, branches=("wanderer",), residents=()) -> Path:
    """Build a fake repo root the passport globs can discover."""
    for branch in branches:
        trinity = root / "src" / "aipass" / branch / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(canonical_text(make_passport(branch)), encoding="utf-8")
    for branch in residents:
        trinity = root / "projects" / "somewhere" / "src" / "pkg" / branch / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(canonical_text(make_passport(branch)), encoding="utf-8")
    return root


def branch_dir(root: Path, branch: str = "wanderer") -> Path:
    return root / "src" / "aipass" / branch


# =============================================================================
# BUILD — the pure transform
# =============================================================================


class TestBuildSeed:
    """live passport -> seed. Pure, order-restoring, strips exactly four keys."""

    def test_strips_exactly_the_machine_local_set(self):
        seed = build_seed(make_passport())
        assert set(MACHINE_LOCAL_CITIZENSHIP) & set(seed["citizenship"]) == set()
        assert set(seed["citizenship"]) == {"residency", "registry_path", "communications", "memory"}

    def test_strips_no_more_than_that(self):
        """Everything outside the four keys survives byte-for-byte."""
        passport = make_passport()
        seed = build_seed(passport)

        assert seed["document_metadata"] == passport["document_metadata"]
        assert seed["branch_info"] == passport["branch_info"]
        assert seed["identity"] == passport["identity"]
        # residency and the dates stay — they are product history, not machine facts
        assert seed["citizenship"]["residency"] == "core"
        assert seed["document_metadata"]["created"] == "2026-03-05"

    def test_strips_an_existing_stamp_too(self):
        """A seed exported from a seed-minted passport must not carry its stamp.

        Lane B's leak-guard goes RED on a seed carrying citizenship.seed, so the
        second export cycle — the one that reads an already-stamped passport — is
        the cycle that would publish it and turn CI red.
        """
        passport = make_passport()
        passport["citizenship"][STAMP_KEY] = {"version": "2.0.0", "sha256": "deadbeef"}

        citizenship = build_seed(passport)["citizenship"]
        for field in MACHINE_LOCAL_CITIZENSHIP:
            assert field not in citizenship, f"{field} survived the strip"

    def test_restores_canonical_key_order(self):
        """A shuffled passport still yields a canonically ordered seed."""
        passport = make_passport()
        passport["identity"] = dict(reversed(list(passport["identity"].items())))
        shuffled = {key: passport[key] for key in ("identity", "citizenship", "branch_info", "document_metadata")}

        seed = build_seed(shuffled)
        assert list(seed) == ["document_metadata", "branch_info", "citizenship", "identity"]
        assert list(seed["identity"])[:2] == ["citizen_class", "role"]

    def test_does_not_mutate_the_source_passport(self):
        passport = make_passport()
        before = json.dumps(passport, sort_keys=True)
        build_seed(passport)
        assert json.dumps(passport, sort_keys=True) == before

    def test_unknown_field_is_preserved_not_dropped(self):
        """Preserve-and-report: validation refuses it, the transform never eats it."""
        passport = make_passport()
        passport["identity"]["favourite_colour"] = "blue"
        seed = build_seed(passport)
        assert seed["identity"]["favourite_colour"] == "blue"
        assert any("favourite_colour" in problem for problem in validate_seed(seed))

    def test_non_object_root_refuses(self):
        """Exactly how a corrupt passport file arrives — a parsed non-object."""
        with pytest.raises(SeedError, match="not a JSON object"):
            build_seed(json.loads('["not", "a", "passport"]'))


# =============================================================================
# VALIDATION — the closed 2.0 shape, two lanes
# =============================================================================


class TestSeedValidation:
    """A seed is a passport minus machine-local. Both lanes, one schema."""

    def test_a_built_seed_validates(self):
        assert validate_seed(build_seed(make_passport())) == []

    def test_a_live_passport_validates(self):
        assert validate_passport(make_passport()) == []

    @pytest.mark.parametrize("field", MACHINE_LOCAL_CITIZENSHIP)
    def test_leak_guard_refuses_every_machine_local_field(self, field):
        """The privacy guard: no machine-local fact may ship in a tracked seed."""
        seed = build_seed(make_passport())
        seed["citizenship"][field] = True if field == "registered" else "leaked"
        problems = validate_seed(seed)
        assert any(f"citizenship.{field}" in problem and "machine-local" in problem for problem in problems)

    def test_passport_lane_requires_what_the_seed_lane_forbids(self):
        """The same missing key is fine in a seed and fatal in a passport."""
        seed = build_seed(make_passport())
        assert validate_seed(seed) == []
        assert any("citizenship.citizen_id is missing" in problem for problem in validate_passport(seed))

    def test_unknown_top_level_block_refuses(self):
        seed = build_seed(make_passport())
        seed["family"] = {"retired": True}
        assert any("top-level 'family'" in problem for problem in validate_seed(seed))

    def test_missing_block_refuses(self):
        seed = build_seed(make_passport())
        del seed["identity"]
        assert any("identity block is missing" in problem for problem in validate_seed(seed))

    def test_block_order_is_contract(self):
        seed = build_seed(make_passport())
        reordered = {key: seed[key] for key in ("branch_info", "document_metadata", "citizenship", "identity")}
        assert any("out of canonical order" in problem for problem in validate_seed(reordered))

    def test_wrong_schema_version_refuses(self):
        seed = build_seed(make_passport())
        seed["document_metadata"]["schema_version"] = "1.0.0"
        assert any("schema_version" in problem for problem in validate_seed(seed))

    def test_traits_as_a_string_refuses(self):
        """The 1.x shape (traits as prose) must not pass as 2.0."""
        seed = build_seed(make_passport())
        seed["identity"]["traits"] = "curious, careful"
        assert any("identity.traits must be a list" in problem for problem in validate_seed(seed))

    def test_empty_branch_name_refuses(self):
        seed = build_seed(make_passport())
        seed["branch_info"]["branch_name"] = "  "
        assert any("branch_info.branch_name is empty" in problem for problem in validate_seed(seed))

    def test_forbidden_class_refuses(self):
        """'admin' is a devpulse-only registry privilege, never an identity."""
        seed = build_seed(make_passport())
        seed["identity"]["citizen_class"] = "admin"
        assert any("citizen_class" in problem for problem in validate_seed(seed))

    def test_retired_class_refuses(self):
        seed = build_seed(make_passport())
        seed["identity"]["citizen_class"] = "project_agent"
        assert any("citizen_class" in problem for problem in validate_seed(seed))

    def test_class_extension_is_optional_not_unknown(self):
        """devpulse alone carries one — present is fine, absent is fine."""
        passport = make_passport()
        passport["identity"] = {
            "citizen_class": "specialist",
            "class_extension": "admin_ops",
            **{k: v for k, v in passport["identity"].items() if k != "citizen_class"},
        }
        assert validate_passport(passport) == []

    def test_stamped_passport_validates(self):
        passport = make_passport()
        passport["citizenship"][STAMP_KEY] = {"version": "2.0.0", "sha256": "a" * 64}
        assert validate_passport(passport) == []

    def test_half_a_stamp_refuses(self):
        """A stamp missing its hash answers 'which seed?' with nothing."""
        passport = make_passport()
        passport["citizenship"][STAMP_KEY] = {"version": "2.0.0"}
        assert any("sha256 is missing" in problem for problem in validate_passport(passport))

    def test_non_object_root_reports_rather_than_raising(self):
        assert validate_seed("just a string") == ["document root is not a JSON object (found str)"]


# =============================================================================
# FINGERPRINT + LOAD
# =============================================================================


class TestFingerprintAndLoad:
    """The stamp hashes the FILE, and a seed is validated before it is trusted."""

    def test_fingerprint_is_sha256_of_the_file_bytes(self, tmp_path):
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text(canonical_text(build_seed(make_passport())), encoding="utf-8")
        assert seed_fingerprint(seed_file) == hashlib.sha256(seed_file.read_bytes()).hexdigest()

    def test_stamp_carries_the_seeds_own_version_and_hash(self, tmp_path):
        seed = build_seed(make_passport())
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text(canonical_text(seed), encoding="utf-8")
        stamp = seed_stamp(seed, seed_file)
        assert stamp == {"version": "2.0.0", "sha256": seed_fingerprint(seed_file)}

    def test_load_seed_round_trips(self, tmp_path):
        seed = build_seed(make_passport())
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text(canonical_text(seed), encoding="utf-8")
        assert load_seed(seed_file) == seed

    def test_load_seed_refuses_missing_file(self, tmp_path):
        with pytest.raises(SeedError, match="could not be read"):
            load_seed(tmp_path / "nope.json")

    def test_load_seed_refuses_broken_json(self, tmp_path):
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text("{not json", encoding="utf-8")
        with pytest.raises(SeedError, match="not valid JSON"):
            load_seed(seed_file)

    def test_load_seed_names_every_problem(self, tmp_path):
        seed = build_seed(make_passport())
        seed["citizenship"]["citizen_id"] = "leaked"
        seed["document_metadata"]["schema_version"] = "1.0.0"
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text(canonical_text(seed), encoding="utf-8")

        with pytest.raises(SeedError) as exc:
            load_seed(seed_file)
        assert "citizen_id" in str(exc.value)
        assert "schema_version" in str(exc.value)

    def test_find_seed_answers_none_for_a_branch_without_one(self, tmp_path):
        assert find_seed(tmp_path) is None
        seed_path_for(tmp_path).parent.mkdir()
        seed_path_for(tmp_path).write_text("{}", encoding="utf-8")
        assert find_seed(tmp_path) == seed_path_for(tmp_path)


# =============================================================================
# MINT — seed -> live passport
# =============================================================================


class TestMintFromSeed:
    """A seed carries an identity, never an installation."""

    @pytest.fixture
    def seeded(self, tmp_path):
        seed = build_seed(make_passport())
        seed_file = tmp_path / "passport.seed.json"
        seed_file.write_text(canonical_text(seed), encoding="utf-8")
        return seed, seed_file

    def test_produces_a_valid_2_0_passport(self, seeded):
        seed, seed_file = seeded
        passport = mint_from_seed(
            seed, seed_file, branch_name="wanderer", registry_id="reg-fresh", citizen_id="cit-fresh"
        )
        assert validate_passport(passport) == []

    def test_mints_fresh_local_ids_and_registers(self, seeded):
        seed, seed_file = seeded
        passport = mint_from_seed(
            seed, seed_file, branch_name="wanderer", registry_id="reg-fresh", citizen_id="cit-fresh"
        )
        assert passport["citizenship"]["registered"] is True
        assert passport["citizenship"]["registry_id"] == "reg-fresh"
        assert passport["citizenship"]["citizen_id"] == "cit-fresh"
        # the machine that grew the identity does not follow it to a new install
        assert MACHINE_REGISTRY_ID not in json.dumps(passport)
        assert MACHINE_CITIZEN_ID not in json.dumps(passport)

    def test_stamps_the_seed_it_came_from(self, seeded):
        seed, seed_file = seeded
        passport = mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")
        assert passport["citizenship"][STAMP_KEY] == {
            "version": "2.0.0",
            "sha256": hashlib.sha256(seed_file.read_bytes()).hexdigest(),
        }

    def test_carries_the_identity_verbatim(self, seeded):
        seed, seed_file = seeded
        passport = mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")
        assert passport["identity"] == make_passport()["identity"]
        assert passport["branch_info"] == make_passport()["branch_info"]

    def test_stamp_sits_last_in_citizenship(self, seeded):
        """Where passport_migration would append an unrecognised key — so a
        stamped passport is already in the order that module would emit."""
        seed, seed_file = seeded
        passport = mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")
        assert list(passport["citizenship"])[-1] == STAMP_KEY
        assert list(passport["citizenship"])[0] == "registered"

    def test_the_validator_accepts_the_very_field_the_mint_writes(self, seeded):
        """The one way this module could poison the fleet on its own.

        The mint writes citizenship.seed, and the same module's validator is what
        gates the write. KEY_ORDER["citizenship"] does not list "seed", so an
        allowlist taken from it UNEXTENDED would make this the only thing in the
        fleet that rejects the stamp it just minted — every seed birth refusing
        itself. Two pins, because the property can be lost two ways: the
        behaviour, and the extension of the allowlist that produces it.
        """
        seed, seed_file = seeded
        passport = mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")

        assert validate_passport(passport) == []
        assert STAMP_KEY in seed_ops._key_order("citizenship")
        assert STAMP_KEY not in KEY_ORDER["citizenship"], "the borrowed order is unextended — we extend it here"

    def test_refuses_a_seed_belonging_to_another_branch(self, seeded):
        seed, seed_file = seeded
        with pytest.raises(SeedError, match="belongs to branch 'wanderer'"):
            mint_from_seed(seed, seed_file, branch_name="impostor", registry_id="r", citizen_id="c")

    def test_refuses_when_the_rendered_passport_would_be_invalid(self, seeded):
        seed, seed_file = seeded
        seed["identity"]["traits"] = "not a list"
        with pytest.raises(SeedError, match="nothing written"):
            mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")

    def test_does_not_mutate_the_seed(self, seeded):
        seed, seed_file = seeded
        before = json.dumps(seed, sort_keys=True)
        mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")
        assert json.dumps(seed, sort_keys=True) == before


# =============================================================================
# EXPORT — the fleet sweep, dry run by default
# =============================================================================


class TestExportSeeds:
    """Dry run is the default; --confirm is the only thing that writes."""

    def test_dry_run_writes_nothing(self, tmp_path):
        root = write_repo(tmp_path)
        receipt = export_seeds(root)

        assert receipt["scanned"] == 1
        assert receipt["created"] == 1
        assert receipt["written"] == 0
        assert not seed_path_for(branch_dir(root)).exists()

    def test_confirm_writes_the_seed(self, tmp_path):
        root = write_repo(tmp_path)
        receipt = export_seeds(root, confirm=True)

        assert receipt["written"] == 1
        assert receipt["errors"] == []
        seed_file = seed_path_for(branch_dir(root))
        assert seed_file.read_text(encoding="utf-8") == canonical_text(build_seed(make_passport()))

    def test_written_seed_carries_no_machine_local_field(self, tmp_path):
        root = write_repo(tmp_path)
        export_seeds(root, confirm=True)
        written = json.loads(seed_path_for(branch_dir(root)).read_text(encoding="utf-8"))
        assert validate_seed(written) == []
        assert MACHINE_CITIZEN_ID not in seed_path_for(branch_dir(root)).read_text(encoding="utf-8")

    def test_non_ascii_prose_ships_as_utf8_not_escapes(self, tmp_path):
        """Passport prose is full of em-dashes. A seed full of \\u2014 escapes
        would be a diff against every live passport that says nothing."""
        root = write_repo(tmp_path)
        passport = make_passport()
        passport["identity"]["purpose"] = "Walks the fleet — honestly."
        (branch_dir(root) / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")

        export_seeds(root, confirm=True)

        raw = seed_path_for(branch_dir(root)).read_bytes()
        assert "—".encode() in raw
        assert b"\\u2014" not in raw

    def test_re_running_is_a_measured_no_op(self, tmp_path):
        """Idempotency, proven by the untouched mtime — not just by a count."""
        root = write_repo(tmp_path)
        export_seeds(root, confirm=True)
        seed_file = seed_path_for(branch_dir(root))
        stamp = seed_file.stat().st_mtime_ns

        receipt = export_seeds(root, confirm=True)

        assert receipt["changed"] == 0
        assert receipt["written"] == 0
        assert receipt["current"] == 1
        assert seed_file.stat().st_mtime_ns == stamp

    def test_the_second_cycle_never_publishes_the_stamp(self, tmp_path):
        """export -> mint -> export. The cycle CI will actually live through.

        Once a citizen is reborn from its seed, its live passport carries the
        stamp and fresh local ids. Re-exporting that passport must strip all four
        back off and land on the SAME BYTES — otherwise the second cycle both
        publishes the stamp (red in Lane B's leak-guard) and reports a spurious
        change on every branch, which is idempotency lost where it matters most.
        """
        root = write_repo(tmp_path)
        export_seeds(root, confirm=True)
        seed_file = seed_path_for(branch_dir(root))
        first_bytes = seed_file.read_bytes()

        reborn = mint_from_seed(
            load_seed(seed_file),
            seed_file,
            branch_name="wanderer",
            registry_id="fresh-credential",
            citizen_id="fresh-citizen",
        )
        assert STAMP_KEY in reborn["citizenship"], "precondition: the reborn passport IS stamped"
        (branch_dir(root) / ".trinity" / "passport.json").write_text(canonical_text(reborn), encoding="utf-8")

        receipt = export_seeds(root, confirm=True)

        assert receipt["changed"] == 0, "a stamp is not a change to the identity"
        assert receipt["written"] == 0
        assert seed_file.read_bytes() == first_bytes
        published = json.loads(seed_file.read_text(encoding="utf-8"))["citizenship"]
        for field in MACHINE_LOCAL_CITIZENSHIP:
            assert field not in published, f"{field} was published to the tracked seed"

    def test_a_changed_passport_updates_its_seed(self, tmp_path):
        root = write_repo(tmp_path)
        export_seeds(root, confirm=True)

        passport = make_passport()
        passport["identity"]["role"] = "explorer"
        (branch_dir(root) / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")

        receipt = export_seeds(root, confirm=True)
        assert receipt["updated"] == 1
        assert json.loads(seed_path_for(branch_dir(root)).read_text())["identity"]["role"] == "explorer"

    def test_residents_are_counted_but_never_exported(self, tmp_path):
        root = write_repo(tmp_path, branches=("wanderer",), residents=("lodger",))
        receipt = export_seeds(root, confirm=True)

        assert receipt["scanned"] == 1
        assert receipt["skipped_resident"] == 1
        resident = root / "projects" / "somewhere" / "src" / "pkg" / "lodger"
        assert not seed_path_for(resident).exists()

    def test_only_restricts_to_one_branch(self, tmp_path):
        root = write_repo(tmp_path, branches=("wanderer", "stranger"))
        receipt = export_seeds(root, only="@wanderer", confirm=True)

        assert receipt["scanned"] == 1
        assert seed_path_for(branch_dir(root, "wanderer")).exists()
        assert not seed_path_for(branch_dir(root, "stranger")).exists()

    def test_an_invalid_passport_gets_named_not_seeded(self, tmp_path):
        """A bad seed shipped to every clone is worse than a missing one."""
        root = write_repo(tmp_path)
        passport = make_passport()
        passport["identity"]["traits"] = "prose, not a list"
        (branch_dir(root) / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")

        receipt = export_seeds(root, confirm=True)

        assert receipt["written"] == 0
        assert [e["branch"] for e in receipt["errors"]] == ["wanderer"]
        assert "traits" in receipt["errors"][0]["error"]
        assert not seed_path_for(branch_dir(root)).exists()

    def test_a_passport_broken_only_where_the_strip_hides_it_still_refuses(self, tmp_path):
        """The LIVE passport is validated, not just the seed built from it.

        Found by mutation: a passport whose only defect sits in the machine-local
        region is silently cured by the strip, so the seed validates and a seed
        would ship from a passport spawn cannot vouch for. Exporting an identity
        from a half-registered citizen is exactly what the first guard is for.
        """
        root = write_repo(tmp_path)
        passport = make_passport()
        del passport["citizenship"]["citizen_id"]
        (branch_dir(root) / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")

        # the seed built from it would look perfectly fine on its own
        assert validate_seed(build_seed(passport)) == []

        receipt = export_seeds(root, confirm=True)
        assert receipt["written"] == 0
        assert "citizen_id is missing" in receipt["errors"][0]["error"]
        assert not seed_path_for(branch_dir(root)).exists()

    def test_an_unreadable_passport_is_reported_not_raised(self, tmp_path):
        root = write_repo(tmp_path)
        (branch_dir(root) / ".trinity" / "passport.json").write_text("{broken", encoding="utf-8")

        receipt = export_seeds(root, confirm=True)
        assert "unreadable passport" in receipt["errors"][0]["error"]

    def test_baseline_flags_a_fleet_that_is_not_the_measured_one(self, tmp_path):
        root = write_repo(tmp_path)
        baseline = export_seeds(root)["baseline"]
        assert baseline["matches"] is False
        assert baseline["discovered_core"] == 1


# =============================================================================
# THE MINT PATH — end to end through spawn create
# =============================================================================


def _registry(tmp_path: Path) -> Path:
    reg = tmp_path / "TEST_REGISTRY.json"
    reg.write_text(
        json.dumps(
            {
                "metadata": {
                    "version": "1.0.0",
                    "last_updated": "2026-08-28",
                    "total_branches": 0,
                    "id": "project-credential",
                },
                "branches": [],
            }
        ),
        encoding="utf-8",
    )
    return reg


def _seeded_branch(tmp_path: Path, branch: str = "wanderer", mutate=None) -> Path:
    """A checked-out branch dir: code and a tracked seed, no live passport."""
    target = tmp_path / branch
    (target / seed_ops.SEED_DIR_NAME).mkdir(parents=True)
    (target / "README.md").write_text("# checked out from the repo\n", encoding="utf-8")

    seed = build_seed(make_passport(branch))
    if mutate:
        mutate(seed)
    seed_path_for(target).write_text(canonical_text(seed), encoding="utf-8")
    return target


class TestMintFromSeedEndToEnd:
    """A clone's branch directory holds its soul; spawn gives it a passport."""

    def test_a_seeded_directory_is_born_from_its_seed(self, tmp_path):
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = _seeded_branch(tmp_path)
        result = _spawn_agent(str(target), registry_path=str(_registry(tmp_path)))

        assert result["success"] is True
        assert result["seeded"] is True

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert validate_passport(passport) == []
        assert passport["identity"] == make_passport()["identity"]
        assert passport["citizenship"][STAMP_KEY]["sha256"] == seed_fingerprint(seed_path_for(target))

    def test_the_born_citizen_carries_fresh_local_ids(self, tmp_path):
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = _seeded_branch(tmp_path)
        reg = _registry(tmp_path)
        _spawn_agent(str(target), registry_path=str(reg))

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "project-credential"
        assert passport["citizenship"]["citizen_id"] != MACHINE_CITIZEN_ID

        # the passport's citizen_id and the registry entry are one fact, not two
        entry = json.loads(reg.read_text(encoding="utf-8"))["branches"][0]
        assert entry["registry_id"] == passport["citizenship"]["citizen_id"]

    def test_an_invalid_seed_refuses_and_writes_nothing(self, tmp_path):
        from aipass.spawn.apps.modules.core import _spawn_agent

        def leak(seed):
            seed["citizenship"]["citizen_id"] = "somebody-elses-id"

        target = _seeded_branch(tmp_path, mutate=leak)
        result = _spawn_agent(str(target), registry_path=str(_registry(tmp_path)))

        assert result["success"] is False
        assert "SEED REFUSED" in result["error"]
        assert "citizen_id" in result["error"]
        assert not (target / ".trinity" / "passport.json").exists()

    def test_a_seed_for_another_branch_refuses(self, tmp_path):
        """The seed lives in the branch it describes — a stray one is refused."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "impostor"
        (target / seed_ops.SEED_DIR_NAME).mkdir(parents=True)
        seed_path_for(target).write_text(canonical_text(build_seed(make_passport("wanderer"))), encoding="utf-8")

        result = _spawn_agent(str(target), registry_path=str(_registry(tmp_path)))
        assert result["success"] is False
        assert "belongs to branch 'wanderer'" in result["error"]
        assert not (target / ".trinity" / "passport.json").exists()

    def test_an_existing_directory_with_no_seed_still_refuses(self, tmp_path):
        """REGRESSION: the seed door opens only for a seed. Nothing else moved."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "no_seed"
        target.mkdir()
        (target / "README.md").write_text("# just a dir\n", encoding="utf-8")

        result = _spawn_agent(str(target), registry_path=str(_registry(tmp_path)))
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_a_template_mint_carries_no_stamp(self, tmp_path):
        """REGRESSION: a citizen born from the template came from no seed, and
        an empty stamp would be a claim about provenance that is not true."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "newborn"
        result = _spawn_agent(str(target), registry_path=str(_registry(tmp_path)))

        assert result["success"] is True
        assert result.get("seeded") is None
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert STAMP_KEY not in passport["citizenship"]
        assert passport["citizenship"]["registered"] is True
