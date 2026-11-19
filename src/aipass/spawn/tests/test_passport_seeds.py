# =================== META ====================
# Name: test_passport_seeds.py
# Description: TDPLAN-0017 — passport seeds: export, validation, mint-from-seed
# Version: 1.4.0
# Created: 2026-08-28
# Modified: 2026-11-18
# =============================================

"""Tests for apps/handlers/seed_ops.py and apps/modules/core.py's mint-from-seed path."""

# The declared pass — what is NOT tested here, and what covers it instead:
# sentry: no-test-needed(ruff) — that every file in apps/handlers/ and apps/modules/ parses and imports
# sentry: no-test-needed(documentation) — that seed_ops' public functions carry docstrings

import copy
import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

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
from aipass.spawn import render_bootstrap_trinity, restore_citizen
from aipass.spawn.apps.modules.core import spawn_agent
from aipass.spawn.tests.conftest import MACHINE_CITIZEN_ID, MACHINE_REGISTRY_ID, make_passport, write_registry

# Pinned separately because each can be lost alone: exact strip, idempotent export,
# valid mint with fresh ids and a byte stamp, invalid seed refuses with nothing written.


def write_repo(root: Path, branches=("wanderer",), residents=()) -> Path:
    """Build a fake repo root, registries included, that memory's door answers."""
    for branch in branches:
        trinity = root / "src" / "aipass" / branch / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(canonical_text(make_passport(branch)), encoding="utf-8")
    write_registry(root / "AIPASS_REGISTRY.json", {branch: f"src/aipass/{branch}" for branch in branches})
    for branch in residents:
        trinity = root / "projects" / "somewhere" / "src" / "pkg" / branch / ".trinity"
        trinity.mkdir(parents=True)
        passport = make_passport(branch)
        passport["citizenship"]["residency"] = "resident"
        (trinity / "passport.json").write_text(canonical_text(passport), encoding="utf-8")
    if residents:
        rows = {branch: f"src/pkg/{branch}" for branch in residents}
        write_registry(root / "projects" / "somewhere" / "SOMEWHERE_REGISTRY.json", rows)
    return root


def branch_dir(root: Path, branch: str = "wanderer") -> Path:
    return root / "src" / "aipass" / branch


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
        """A seed exported from a seed-minted passport must not carry its stamp (the leak-guard is red on it)."""
        passport = make_passport()
        passport["citizenship"][STAMP_KEY] = {"version": "2.0.0", "sha256": "deadbeef"}

        citizenship = build_seed(passport)["citizenship"]
        assert len(MACHINE_LOCAL_CITIZENSHIP) == 4, MACHINE_LOCAL_CITIZENSHIP
        assert STAMP_KEY in MACHINE_LOCAL_CITIZENSHIP, "the stamp is the field this test exists for"
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


class TestSeedValidation:
    """A seed is a passport minus machine-local. Both lanes, one schema."""

    def test_the_leak_guard_table_carries_all_four_machine_local_fields(self):
        """The floor under the parametrized leak guard below, read from the raw source.

        From the AST, not the import: a shortened tuple would shrink the guard to a green SKIP."""
        import ast

        source = Path(seed_ops.__file__).read_text(encoding="utf-8")
        declared = next(
            node.value
            for node in ast.parse(source).body
            if isinstance(node, ast.Assign)
            and any(getattr(t, "id", "") == "MACHINE_LOCAL_CITIZENSHIP" for t in node.targets)
        )

        assert isinstance(declared, ast.Tuple), "MACHINE_LOCAL_CITIZENSHIP is no longer declared as a tuple literal"
        assert len(declared.elts) == 4, f"seed_ops declares {len(declared.elts)} machine-local fields, not 4"
        assert len(MACHINE_LOCAL_CITIZENSHIP) == 4, MACHINE_LOCAL_CITIZENSHIP
        assert set(MACHINE_LOCAL_CITIZENSHIP) == {"registered", "registry_id", "citizen_id", STAMP_KEY}, (
            f"the machine-local set moved: {MACHINE_LOCAL_CITIZENSHIP}"
        )

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

        KEY_ORDER lacks "seed": an unextended allowlist would refuse every seed birth.
        Mutant: the stamp prepended to the citizenship key order instead of appended -> red."""
        seed, seed_file = seeded
        passport = mint_from_seed(seed, seed_file, branch_name="wanderer", registry_id="r", citizen_id="c")

        assert validate_passport(passport) == []
        assert list(passport["citizenship"])[-1] == STAMP_KEY, "the stamp is not appended to the citizenship order"
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


class TestBootstrapRender:
    """setup.sh's one call: the seed births the passport, the template fills what is missing, nothing is overwritten."""

    @pytest.fixture
    def seeded_home(self, tmp_path, monkeypatch):
        root = tmp_path
        write_registry(root / "AIPASS_REGISTRY.json", {"wanderer": "src/aipass/wanderer"})
        target = branch_dir(root)
        seed_file = seed_path_for(target)
        seed_file.parent.mkdir(parents=True)
        seed_file.write_text(canonical_text(build_seed(make_passport())), encoding="utf-8")
        home = SimpleNamespace(path=root, source="test", tried=())
        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            yield root, target

    def _render(self, root, target):
        return render_bootstrap_trinity("wanderer", target, "specialist", "wanderer", root / "AIPASS_REGISTRY.json")

    def test_the_seed_births_the_passport_and_the_template_fills_the_rest(self, seeded_home):
        """Mutant: the seed branch is skipped -> the passport comes from the template, unstamped -> red."""
        root, target = seeded_home

        written = self._render(root, target)

        assert written == ["passport.json(seed)", "local.json", "observations.json"]
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "pid-test"
        assert STAMP_KEY in passport["citizenship"]
        local = (target / ".trinity" / "local.json").read_text(encoding="utf-8")
        assert "{{" not in local

    def test_a_rendered_file_gets_a_plain_writes_mode(self, seeded_home):
        """An install's files read as a plain open() made them. Mutant: the writer keeps mkstemp's 0600 -> red."""
        root, target = seeded_home
        umask = os.umask(0)
        os.umask(umask)

        self._render(root, target)

        assert (target / ".trinity" / "local.json").stat().st_mode & 0o777 == 0o666 & ~umask

    def test_an_existing_file_is_never_overwritten(self, seeded_home):
        """Mutant: the exists() skip is dropped -> the hand-kept local.json is replaced -> red."""
        root, target = seeded_home
        kept = target / ".trinity" / "local.json"
        kept.parent.mkdir(parents=True)
        kept.write_text('{"mine": true}', encoding="utf-8")

        assert "local.json" not in self._render(root, target)
        assert kept.read_text(encoding="utf-8") == '{"mine": true}'

    def test_a_project_citizen_renders_its_bare_module(self, tmp_path):
        """Only a core branch imports as aipass.<name>. Mutant: MODULE forced to aipass.<name> -> red."""
        project = tmp_path / "projects" / "finch"
        write_registry(project / "FINCH_REGISTRY.json", {"finch": "src/finch/finch"})
        target = project / "src" / "finch" / "finch"
        target.mkdir(parents=True)
        home = SimpleNamespace(path=tmp_path, source="test", tried=())

        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            render_bootstrap_trinity("finch", target, "manager", "canary", project / "FINCH_REGISTRY.json")

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["branch_info"]["module"] == "finch"
        assert passport["citizenship"]["residency"] == "resident"

    def test_a_core_citizen_renders_its_package_module(self, seeded_home):
        """Mutant: MODULE left bare for core too -> red."""
        root, target = seeded_home
        seed_path_for(target).unlink()

        self._render(root, target)

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["branch_info"]["module"] == "aipass.wanderer"

    def test_an_unreadable_registry_stops_the_install_with_nothing_written(self, seeded_home):
        """State document: never guessed. Mutant: the registry error is swallowed -> red."""
        root, target = seeded_home
        (root / "AIPASS_REGISTRY.json").write_text("{not json", encoding="utf-8")

        with pytest.raises(json.JSONDecodeError):
            self._render(root, target)
        assert not (target / ".trinity").exists()


class TestRestoreCitizen:
    """Another branch's restore: one registered citizen, from its registry row and its seed, missing files only."""

    def test_restores_only_the_missing_files_from_the_seed(self, tmp_path):
        """Mutant: restore renders over files that exist -> the kept local.json changes -> red."""
        root = write_repo(tmp_path)
        target = branch_dir(root)
        seed_file = seed_path_for(target)
        seed_file.parent.mkdir(parents=True)
        seed_file.write_text(canonical_text(build_seed(make_passport())), encoding="utf-8")
        (target / ".trinity" / "passport.json").unlink()
        kept = target / ".trinity" / "local.json"
        kept.write_text('{"mine": true}', encoding="utf-8")
        home = SimpleNamespace(path=root, source="test", tried=())

        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            written = restore_citizen("WANDERER", root / "AIPASS_REGISTRY.json")

        assert written == ["passport.json(seed)", "observations.json"]
        assert kept.read_text(encoding="utf-8") == '{"mine": true}'
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["identity"]["citizen_class"] == "specialist"
        assert passport["citizenship"]["registry_id"] == "pid-test"

    def test_a_corrupt_passport_is_set_aside_and_restored(self, tmp_path):
        """A passport that is present but not JSON is damage too; its bytes are kept beside the new one.

        Mutant: only a missing passport is restored -> the corrupt file stays -> red."""
        root = write_repo(tmp_path)
        target = branch_dir(root)
        seed_file = seed_path_for(target)
        seed_file.parent.mkdir(parents=True)
        seed_file.write_text(canonical_text(build_seed(make_passport())), encoding="utf-8")
        passport_file = target / ".trinity" / "passport.json"
        passport_file.write_text("{not json", encoding="utf-8")
        home = SimpleNamespace(path=root, source="test", tried=())

        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            written = restore_citizen("WANDERER", root / "AIPASS_REGISTRY.json")

        assert "passport.json(seed)" in written
        assert json.loads(passport_file.read_text(encoding="utf-8"))["identity"]["citizen_class"] == "specialist"
        [aside] = list(passport_file.parent.glob("passport.json.corrupt-*"))
        assert aside.read_text(encoding="utf-8") == "{not json"

    def test_an_unregistered_name_is_refused_with_nothing_written(self, tmp_path):
        root = write_repo(tmp_path)

        with pytest.raises(LookupError, match="stranger"):
            restore_citizen("stranger", root / "AIPASS_REGISTRY.json")

    def test_a_citizen_without_a_seed_is_refused(self, tmp_path):
        """No seed, no class and role: restore never guesses them. Mutant: a default class -> red."""
        root = write_repo(tmp_path)
        (branch_dir(root) / ".trinity" / "passport.json").unlink()

        with pytest.raises(FileNotFoundError, match="seed"):
            restore_citizen("wanderer", root / "AIPASS_REGISTRY.json")
        assert not (branch_dir(root) / ".trinity" / "passport.json").exists()


def project_citizen(tmp_path, branch: str = "finch"):
    """A project-shaped citizen in tmp_path: home/projects/<branch>, its own registry, a resident passport."""
    project = tmp_path / "projects" / branch
    registry = write_registry(project / f"{branch.upper()}_REGISTRY.json", {branch: f"src/{branch}/{branch}"})
    target = project / "src" / branch / branch
    trinity = target / ".trinity"
    trinity.mkdir(parents=True)
    passport = make_passport(branch)
    passport["citizenship"]["residency"] = "resident"
    passport["branch_info"]["module"] = branch
    passport["identity"]["traits"] = ["canary", "projects tier"]
    (trinity / "passport.json").write_text(canonical_text(passport), encoding="utf-8")
    return project, registry, target, passport


class TestEveryCitizenCarriesASeed:
    """A seed is written at birth for every residency, and a project's own export reaches its citizens."""

    def test_a_newborn_carries_its_own_seed(self, tmp_path):
        """Mutant: mint_citizen skips the seed -> red."""
        target = tmp_path / "newborn"
        result = spawn_agent(str(target), registry_path=str(tmp_path / "AIPASS_REGISTRY.json"), role="scout")
        assert result["success"] is True, result.get("error")

        seed = load_seed(seed_path_for(target))
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert seed == build_seed(passport)
        assert seed["identity"]["role"] == "scout"

    def test_a_seed_that_cannot_be_written_fails_the_birth(self, tmp_path):
        """Mutant: the seed write's failure is ignored and the citizen registers -> red."""
        target = tmp_path / "halfborn"
        registry = tmp_path / "AIPASS_REGISTRY.json"

        with patch("aipass.spawn.apps.handlers.seed_ops.atomic_write_text", side_effect=OSError("disk full")):
            result = spawn_agent(str(target), registry_path=str(registry))

        assert result["success"] is False
        assert "seed" in result["error"] and "disk full" in result["error"]
        assert not registry.exists() or "HALFBORN" not in registry.read_text(encoding="utf-8")

    def test_export_run_in_a_project_seeds_that_projects_citizens(self, tmp_path):
        """Mutant: export keeps the core-only filter in a project -> scanned 0 -> red."""
        project, _, target, passport = project_citizen(tmp_path)

        receipt = export_seeds(project, confirm=True)

        assert (receipt["scope"], receipt["scanned"], receipt["written"]) == ("project", 1, 1)
        assert load_seed(seed_path_for(target)) == build_seed(passport)

    def test_export_in_the_aipass_tree_still_never_reaches_a_project(self, tmp_path):
        """Mutant: the tree lane drops its core filter -> the resident gets a seed -> red."""
        root = write_repo(tmp_path, residents=("visitor",))

        receipt = export_seeds(root, confirm=True)

        assert (receipt["scope"], receipt["scanned"], receipt["skipped_resident"]) == ("core", 1, 1)
        resident = root / "projects" / "somewhere" / "src" / "pkg" / "visitor"
        assert not seed_path_for(resident).exists()

    def test_a_resident_seed_validates_like_a_core_one(self, tmp_path):
        """Already true before this build; the guard against a core-only validator."""
        _, _, _, passport = project_citizen(tmp_path)

        assert validate_seed(build_seed(passport)) == []

    def test_a_project_citizen_with_a_seed_is_restored_from_it(self, tmp_path):
        """restore_citizen is unchanged; this pins its seed route for a project citizen."""
        project, registry, target, passport = project_citizen(tmp_path)
        export_seeds(project, confirm=True)
        (target / ".trinity" / "passport.json").unlink()
        keep = [target / ".trinity" / "local.json", target / ".trinity" / "observations.json", registry]
        keep[0].write_text('{"mine": 1}', encoding="utf-8")
        keep[1].write_text('{"seen": 1}', encoding="utf-8")
        certificate = target / "artifacts" / "birth_certificate.json"
        certificate.parent.mkdir()
        certificate.write_text('{"id": "1"}', encoding="utf-8")
        keep.append(certificate)
        before = [p.read_bytes() for p in keep]
        home = SimpleNamespace(path=tmp_path, source="test", tried=())

        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            written = restore_citizen("FINCH", registry)

        assert written == ["passport.json(seed)"]
        restored = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert restored["identity"] == passport["identity"]
        assert restored["branch_info"]["module"] == "finch"
        assert restored["citizenship"]["residency"] == "resident"
        assert [p.read_bytes() for p in keep] == before

    def test_a_seedless_citizen_is_refused_with_the_cure_named(self, tmp_path):
        """Mutant: the refusal drops the cure -> red."""
        project, registry, target, _ = project_citizen(tmp_path)
        (target / ".trinity" / "passport.json").unlink()

        with pytest.raises(FileNotFoundError, match="export-seeds --confirm"):
            restore_citizen("finch", registry)


def off_schema_citizen(tmp_path, branch: str = "wren"):
    """A project citizen shaped like real external passports: 2.0 gaps and fields 2.0 has no place for."""
    project, registry, target, passport = project_citizen(tmp_path, branch)
    passport["citizenship"]["residency"] = "external"
    del passport["citizenship"]["citizen_id"], passport["citizenship"]["registry_path"]
    passport["branch_info"]["project"] = "Studio"
    passport["identity"]["home"] = {"room": "north"}
    passport["identity"]["personality"] = {"tone": "dry"}
    passport["identity"]["anti_traits"] = ["hurry"]
    passport["doctrine"] = ["read before you write"]
    passport["pipeline"] = {"upstream": "research", "downstream": "verify"}
    (target / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")
    return project, registry, target, passport


def without_machine_ids(passport: dict) -> dict:
    """The passport as a user owns it: the per-install citizenship facts removed."""
    kept = copy.deepcopy(passport)
    for key in MACHINE_LOCAL_CITIZENSHIP:
        kept["citizenship"].pop(key, None)
    return kept


class TestAProjectPassportIsSeededAsItStands:
    """A project citizen's seed is its own passport minus the machine ids; a core seed keeps strict 2.0."""

    def test_an_off_schema_project_passport_is_seeded_with_everything_kept(self, tmp_path):
        """Mutant: the project lane validates against the core schema -> refused -> red."""
        project, _, target, passport = off_schema_citizen(tmp_path)

        receipt = export_seeds(project, confirm=True)

        assert (receipt["written"], receipt["errors"]) == (1, [])
        assert load_seed(seed_path_for(target)) == without_machine_ids(passport)

    def test_an_off_schema_project_citizen_is_restored_with_everything_the_user_wrote(self, tmp_path):
        """Mutant: the rendered passport is checked against the core schema -> restore raises -> red."""
        project, registry, target, passport = off_schema_citizen(tmp_path)
        export_seeds(project, confirm=True)
        (target / ".trinity" / "passport.json").unlink()
        home = SimpleNamespace(path=tmp_path, source="test", tried=())

        with patch("aipass.spawn.apps.handlers.registry.resolve_aipass_home", return_value=home):
            restore_citizen("wren", registry)

        restored = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert without_machine_ids(restored) == without_machine_ids(passport)
        assert restored["citizenship"]["citizen_id"]

    def test_a_core_seed_keeps_the_strict_check(self):
        """Mutant: every seed takes the project check -> the core seed's stray block passes -> red."""
        seed = build_seed(make_passport("drone"))
        seed["doctrine"] = ["stray"]

        assert any("'doctrine' is not a block" in problem for problem in validate_seed(seed))

    def test_a_project_seed_still_never_carries_a_machine_id(self, tmp_path):
        """Mutant: the project check drops the machine-local guard -> a citizen_id ships -> red."""
        _, _, _, passport = off_schema_citizen(tmp_path)
        leaked = without_machine_ids(passport)
        leaked["citizenship"]["registry_id"] = "this-machine"

        assert any("machine-local" in problem for problem in validate_seed(leaked))

    def test_a_nameless_project_passport_is_refused_naming_the_cure(self, tmp_path):
        """Mutant: the project check stops asking for the name restore keys on -> exported -> red."""
        project, _, target, passport = off_schema_citizen(tmp_path)
        del passport["branch_info"]["branch_name"]
        (target / ".trinity" / "passport.json").write_text(canonical_text(passport), encoding="utf-8")

        receipt = export_seeds(project, confirm=True)

        assert receipt["written"] == 0
        assert "branch_info.branch_name" in receipt["errors"][0]["error"]
        assert "re-run export-seeds" in receipt["errors"][0]["error"]

    def test_a_core_passport_off_2_0_is_refused_naming_the_migration(self, tmp_path):
        """Mutant: the core refusal drops its cure -> red."""
        root = write_repo(tmp_path)
        passport_file = branch_dir(root) / ".trinity" / "passport.json"
        passport = json.loads(passport_file.read_text(encoding="utf-8"))
        passport["doctrine"] = ["stray"]
        passport_file.write_text(canonical_text(passport), encoding="utf-8")

        receipt = export_seeds(root, confirm=True)

        assert "migrate-passports" in receipt["errors"][0]["error"]


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

        Re-export must strip the stamp and fresh ids and land on the same bytes."""
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
        assert json.loads(seed_path_for(branch_dir(root)).read_text(encoding="utf-8"))["identity"]["role"] == "explorer"

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

        A defect only in the machine-local region is cured by the strip, so the seed alone validates."""
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
        """A seed birth adopts, and adoption's template update looks the branch up by name
        in the registry the birth was handed (the tmp_path registry)."""

        target = _seeded_branch(tmp_path)
        reg = _registry(tmp_path)
        result = spawn_agent(str(target), registry_path=str(reg))

        assert result["success"] is True
        assert result["seeded"] is True

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert validate_passport(passport) == []
        assert passport["identity"] == make_passport()["identity"]
        assert passport["citizenship"][STAMP_KEY]["sha256"] == seed_fingerprint(seed_path_for(target))

    def test_the_born_citizen_carries_fresh_local_ids(self, tmp_path):

        target = _seeded_branch(tmp_path)
        reg = _registry(tmp_path)
        spawn_agent(str(target), registry_path=str(reg))

        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "project-credential"
        assert passport["citizenship"]["citizen_id"] != MACHINE_CITIZEN_ID

        # the passport's citizen_id and the registry entry are one fact, not two
        entry = json.loads(reg.read_text(encoding="utf-8"))["branches"][0]
        assert entry["registry_id"] == passport["citizenship"]["citizen_id"]

    def test_an_invalid_seed_refuses_and_writes_nothing(self, tmp_path):

        def leak(seed):
            seed["citizenship"]["citizen_id"] = "somebody-elses-id"

        target = _seeded_branch(tmp_path, mutate=leak)
        result = spawn_agent(str(target), registry_path=str(_registry(tmp_path)))

        assert result["success"] is False
        assert "SEED REFUSED" in result["error"]
        assert "citizen_id" in result["error"]
        assert not (target / ".trinity" / "passport.json").exists()

    def test_a_seed_for_another_branch_refuses(self, tmp_path):
        """The seed lives in the branch it describes — a stray one is refused."""

        target = tmp_path / "impostor"
        (target / seed_ops.SEED_DIR_NAME).mkdir(parents=True)
        seed_path_for(target).write_text(canonical_text(build_seed(make_passport("wanderer"))), encoding="utf-8")

        result = spawn_agent(str(target), registry_path=str(_registry(tmp_path)))
        assert result["success"] is False
        assert "belongs to branch 'wanderer'" in result["error"]
        assert not (target / ".trinity" / "passport.json").exists()

    def test_an_existing_directory_with_no_seed_still_refuses(self, tmp_path):
        """REGRESSION: the seed door opens only for a seed. Nothing else moved."""

        target = tmp_path / "no_seed"
        target.mkdir()
        (target / "README.md").write_text("# just a dir\n", encoding="utf-8")

        result = spawn_agent(str(target), registry_path=str(_registry(tmp_path)))
        assert result["success"] is False
        assert "already exists" in result["error"]

    def test_a_template_mint_carries_no_stamp(self, tmp_path):
        """REGRESSION: a citizen born from the template came from no seed, and
        an empty stamp would be a claim about provenance that is not true."""

        target = tmp_path / "newborn"
        result = spawn_agent(str(target), registry_path=str(_registry(tmp_path)))

        assert result["success"] is True
        assert result.get("seeded") is None
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert STAMP_KEY not in passport["citizenship"]
        assert passport["citizenship"]["registered"] is True

    def test_a_seed_birth_with_no_registry_refuses_and_writes_nothing(self, tmp_path, monkeypatch):
        monkeypatch.delenv("AIPASS_REGISTRY", raising=False)
        target = _seeded_branch(tmp_path)

        result = spawn_agent(str(target))

        assert result["success"] is False
        assert "no *_REGISTRY.json" in result["error"]
        assert not (target / ".trinity" / "passport.json").exists()

    def test_a_seed_birth_into_a_new_registry_gives_it_the_passports_credential(self, tmp_path):
        target = _seeded_branch(tmp_path)
        reg = tmp_path / "NEW_REGISTRY.json"

        result = spawn_agent(str(target), registry_path=str(reg))

        assert result["success"] is True
        passport = json.loads((target / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        credential = json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"]
        assert credential
        assert passport["citizenship"]["registry_id"] == credential
