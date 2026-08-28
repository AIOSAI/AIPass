# =================== META ====================
# Name: test_passport_migration.py
# Description: DPLAN-0319 — passport 2.0 fleet migration: order, drops, lanes, idempotency
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""Pins for the one-shot passport 2.0 migration (DPLAN-0319 deliverable 3).

Two fixture families, on purpose:

* ``synthetic_fleet`` — hand-built passports reproducing every shape MEASURED
  on the live fleet on 2026-08-28 (uppercase casing, the ``AIPASS_REGISTRY.json``
  registry_path outlier, skills' stale path, a resident's hardcoded absolute
  ``/home/...`` path, string traits, top-level principles, the three R8 drops).
  These always run — including in a clean checkout — so they carry the
  mutation-detection weight.
* ``live_fleet_copy`` — real copies of the actual live passports, copied into
  tmp_path at their real relative locations. ``.trinity/`` is gitignored
  (.gitignore:27), so these SKIP on a clone and are the ground-truth pins on a
  machine that has the fleet.

Nothing in this file writes to the live tree. Every write lands in tmp_path.
"""

import json
import os
import shutil
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.passport_migration import (
    BACKUP_SUFFIX,
    BLOCK_ORDER,
    CANONICAL_REGISTRY_PATH,
    EXPECTED_FLEET,
    KEY_ORDER,
    IDENTITY_CONTENT_KEYS,
    PassportMigrationError,
    backup_passport,
    discover_passports,
    migrate_document,
    migrate_fleet,
    repo_root,
)

RUN_DATE = "2026-08-28"

# The four residents carry an ABSOLUTE hardcoded path today (a real
# ``/home/<user>/...`` string on the live fleet). The synthetic fixture
# reproduces the SHAPE with a neutral prefix rather than a real home path — a
# checked-in test that hardcodes somebody's home directory is the very thing
# the public-repo house rule forbids. The live ``/home/`` case is pinned for
# real by TestNoHardcodedHomePaths against live_fleet_copy.
ABSOLUTE_FOSSIL_PREFIX = "/opt/checkout/AIPass"

# The 2.0 contract, written out LITERALLY here on purpose. Asserting against the
# handler's own BLOCK_ORDER/KEY_ORDER constants would make every order pin
# self-fulfilling — edit the constant and the test follows it. These come off
# the gold reference (devpulse dropbox passport_v2_draft.devpulse.json) and the
# test below proves the handler's constants still agree with them.
CONTRACT_BLOCK_ORDER = ("document_metadata", "branch_info", "citizenship", "identity")
CONTRACT_KEY_ORDER = {
    "document_metadata": (
        "document_type",
        "document_name",
        "version",
        "schema_version",
        "created",
        "last_updated",
        "managed_by",
        "tags",
    ),
    "branch_info": ("branch_name", "alias", "path", "module", "email", "created", "git_branch"),
    "citizenship": (
        "registered",
        "residency",
        "registry_id",
        "citizen_id",
        "registry_path",
        "communications",
        "memory",
    ),
    "identity": (
        "citizen_class",
        "class_extension",
        "role",
        "purpose",
        "what_i_do",
        "what_i_dont_do",
        "traits",
        "principles",
    ),
}


# =============================================================================
# FIXTURES
# =============================================================================


def _write_passport(root: Path, relative_dir: str, document: dict) -> Path:
    """Write ``document`` as the passport of the branch at ``relative_dir``."""
    trinity = root / relative_dir / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    path = trinity / "passport.json"
    path.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def _legacy_passport(
    *,
    branch_name: str,
    path: str,
    module: str,
    citizen_class: str = "aipass_framework",
    git_branch: str = "work/legacy",
    registry_path: str | None = CANONICAL_REGISTRY_PATH,
    traits: object = "",
    owner: object = None,
    family: dict | None = None,
    note: str | None = None,
    extra: dict | None = None,
) -> dict:
    """A pre-2.0 passport in the MEASURED live block order.

    Live order today is document_metadata, branch_info, [family], identity,
    principles, citizenship — principles top-level, citizenship last.
    """
    document: dict = {
        "document_metadata": {
            "document_type": "branch_identity",
            "document_name": f"{branch_name}.PASSPORT",
            "version": "1.0.0",
            "schema_version": "1.0.0",
            "created": "2026-03-07",
            "last_updated": "2026-05-01",
            "managed_by": branch_name,
            "tags": ["identity", "passport", "branch_profile"],
        },
        "branch_info": {
            "branch_name": branch_name,
            "alias": "",
            "path": path,
            "module": module,
            "created": "2026-03-07",
            "git_branch": git_branch,
            "email": f"@{branch_name.lower()}",
        },
    }
    if note is not None:
        document["document_metadata"]["note"] = note
    if family is not None:
        document["family"] = family

    document["identity"] = {
        "citizen_class": citizen_class,
        "role": f"{branch_name} role",
        "purpose": f"{branch_name} purpose — never rewritten by a structure migration",
        "what_i_do": [f"{branch_name} does this"],
        "what_i_dont_do": [f"{branch_name} does not do that"],
        "traits": traits,
    }
    document["principles"] = [f"{branch_name} principle one", "Fail honestly"]

    citizenship: dict = {
        "registered": True,
        "registry_id": "7087bb93-570f-4b9a-b035-4fd7f570200e",
        "citizen_id": "8d2dc24c-2421-49c4-a033-94f2cb1fd176",
    }
    if registry_path is not None:
        citizenship["registry_path"] = registry_path
    citizenship["communications"] = True
    citizenship["memory"] = True
    if owner is not None:
        citizenship["owner"] = owner
    document["citizenship"] = citizenship

    if extra:
        for key, value in extra.items():
            document[key] = value
    return document


@pytest.fixture
def synthetic_fleet(tmp_path):
    """A tmp repo root reproducing every live shape this migration must fix."""
    root = tmp_path / "repo"

    _write_passport(
        root,
        "src/aipass/spawn",
        _legacy_passport(branch_name="spawn", path="src/aipass/spawn", module="aipass.spawn", git_branch="work/spawn"),
    )
    # aipass: UPPERCASE casing, version 0.1.0 outlier, owner:true, metadata note
    aipass_doc = _legacy_passport(
        branch_name="AIPASS",
        path="src/aipass/aipass",
        module="aipass.aipass",
        git_branch="work/aipass",
        traits=["Pragmatic", "Direct"],
        owner=True,
        note="Gitignored during build per DPLAN-0136.",
    )
    aipass_doc["document_metadata"]["version"] = "0.1.0"
    _write_passport(root, "src/aipass/aipass", aipass_doc)

    # canary: UPPERCASE, family block, registry_path MISSING, owner:false
    _write_passport(
        root,
        "src/aipass/canary",
        _legacy_passport(
            branch_name="CANARY",
            path="src/aipass/canary",
            module="aipass.canary",
            git_branch="work/canary",
            registry_path=None,
            traits="Watchful — sings before the mine kills anyone",
            owner=False,
            family={"badge": "canary", "my_tier": "3"},
        ),
    )
    # commons: module missing the aipass. prefix + the registry_path outlier
    _write_passport(
        root,
        "src/aipass/commons",
        _legacy_passport(
            branch_name="commons",
            path="src/aipass/commons",
            module="commons",
            git_branch="work/commons",
            registry_path="AIPASS_REGISTRY.json",
        ),
    )
    # skills: stale path src/skills AND module missing the prefix
    _write_passport(
        root,
        "src/aipass/skills",
        _legacy_passport(
            branch_name="skills",
            path="src/skills",
            module="skills",
            git_branch="work/skills",
        ),
    )
    # devpulse: already manager, already dev, class_extension, list traits
    devpulse_doc = _legacy_passport(
        branch_name="devpulse",
        path="src/aipass/devpulse",
        module="aipass.devpulse",
        citizen_class="manager",
        git_branch="dev",
        traits=["Pragmatic — do the simple thing first"],
    )
    devpulse_doc["identity"]["class_extension"] = "admin (DPLAN-0288): signed privilege block."
    _write_passport(root, "src/aipass/devpulse", devpulse_doc)

    # residents: manager, git_branch main, no registry_path, ABSOLUTE path
    for project, package in (("baud", "baud"), ("finch", "finch")):
        upper = project.upper()
        family = {"badge": upper} if project == "finch" else None
        _write_passport(
            root,
            f"projects/{project}/src/{package}/{project}",
            _legacy_passport(
                branch_name=upper,
                path=f"{ABSOLUTE_FOSSIL_PREFIX}/projects/{project}/src/{package}/{project}",
                module=project,
                citizen_class="manager",
                git_branch="main",
                registry_path=None,
                owner=True,
                family=family,
            ),
        )

    # Decoys that must never be discovered: a backup tree and the template.
    _write_passport(
        root,
        ".backup/snapshots/src/aipass/ghost",
        _legacy_passport(branch_name="ghost", path="src/aipass/ghost", module="aipass.ghost"),
    )
    _write_passport(
        root,
        "src/aipass/spawn/templates/citizen",
        _legacy_passport(branch_name="{{BRANCH}}", path="{{PATH}}", module="{{MODULE}}"),
    )
    return root


@pytest.fixture
def live_fleet_copy(tmp_path):
    """Real live passports copied into tmp_path at their real relative paths."""
    live_root = repo_root()
    targets = discover_passports(live_root)
    if not targets:
        pytest.skip("No live .trinity/passport.json on this machine (gitignored — expected in CI)")

    root = tmp_path / "live"
    for target in targets:
        relative = target.path.relative_to(live_root)
        destination = root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(target.path, destination)
    return root


def _string_values(node: object):
    """Yield every string anywhere in a nested JSON structure."""
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _string_values(value)
    elif isinstance(node, list):
        for value in node:
            yield from _string_values(value)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _passport(root: Path, relative_dir: str) -> Path:
    return root / relative_dir / ".trinity" / "passport.json"


def _migrated(root: Path, relative_dir: str) -> dict:
    """Apply the migration to ``root`` and return one branch's new document."""
    migrate_fleet(root, confirm=True, run_date=RUN_DATE)
    return _read(_passport(root, relative_dir))


# =============================================================================
# DISCOVERY
# =============================================================================


class TestDiscovery:
    """The input set is globbed, never hardcoded — and it excludes the decoys."""

    def test_finds_core_and_residents_only(self, synthetic_fleet):
        found = {t.branch_dir.name: t.residency for t in discover_passports(synthetic_fleet)}
        assert found == {
            "spawn": "core",
            "aipass": "core",
            "canary": "core",
            "commons": "core",
            "skills": "core",
            "devpulse": "core",
            "baud": "resident",
            "finch": "resident",
        }

    def test_backup_tree_and_template_are_not_discovered(self, synthetic_fleet):
        paths = [str(t.path) for t in discover_passports(synthetic_fleet)]
        assert not [p for p in paths if ".backup" in p]
        assert not [p for p in paths if "templates" in p]

    def test_resident_project_root_is_its_own_project(self, synthetic_fleet):
        baud = next(t for t in discover_passports(synthetic_fleet) if t.branch_dir.name == "baud")
        assert baud.project_root == synthetic_fleet / "projects" / "baud"
        assert baud.relative_path == "src/baud/baud"

    def test_live_fleet_matches_the_measured_baseline(self):
        targets = discover_passports(repo_root())
        if not targets:
            pytest.skip("No live fleet on this machine (gitignored — expected in CI)")
        core = sum(1 for t in targets if t.residency == "core")
        resident = sum(1 for t in targets if t.residency == "resident")
        assert (len(targets), core, resident) == (
            EXPECTED_FLEET["total"],
            EXPECTED_FLEET["core"],
            EXPECTED_FLEET["resident"],
        ), "Fleet size drifted from the 2026-08-28 measurement — report it, do not silently migrate a new shape"


# =============================================================================
# ORDER — block order and per-block key order ARE the contract (R1)
# =============================================================================


class TestBlockAndKeyOrder:
    """Nothing pinned order before this file. If order is contract, a test says so."""

    def test_handler_constants_still_match_the_written_contract(self):
        assert BLOCK_ORDER == CONTRACT_BLOCK_ORDER
        assert KEY_ORDER == CONTRACT_KEY_ORDER

    def test_every_migrated_passport_uses_the_2_0_block_order(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            document = _read(target.path)
            assert tuple(document.keys()) == CONTRACT_BLOCK_ORDER, f"{target.branch_dir.name} block order"

    @pytest.mark.parametrize("section", list(CONTRACT_KEY_ORDER))
    def test_key_order_inside_every_block_follows_the_contract(self, synthetic_fleet, section):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        contract = CONTRACT_KEY_ORDER[section]
        for target in discover_passports(synthetic_fleet):
            keys = tuple(_read(target.path)[section].keys())
            expected = tuple(key for key in contract if key in keys)
            assert keys == expected, f"{target.branch_dir.name}.{section} key order"

    def test_citizenship_sits_above_identity(self, synthetic_fleet):
        keys = list(_migrated(synthetic_fleet, "src/aipass/spawn"))
        assert keys.index("citizenship") < keys.index("identity")

    def test_class_extension_follows_citizen_class(self, synthetic_fleet):
        identity = _migrated(synthetic_fleet, "src/aipass/devpulse")["identity"]
        assert list(identity)[:2] == ["citizen_class", "class_extension"]

    def test_migrated_devpulse_matches_the_gold_draft_shape(self, live_fleet_copy):
        gold_path = repo_root() / "src/aipass/devpulse/dropbox/passport_v2_draft.devpulse.json"
        if not gold_path.exists():
            pytest.skip("gold reference passport_v2_draft.devpulse.json not present")
        gold = json.loads(gold_path.read_text(encoding="utf-8"))
        migrated = _migrated(live_fleet_copy, "src/aipass/devpulse")
        assert list(migrated) == list(gold)
        for section in gold:
            assert list(migrated[section]) == list(gold[section]), section


# =============================================================================
# DROPS — R8, by name, and nothing else
# =============================================================================


class TestDrops:
    """owner / family / note go. Everything else the tool doesn't know is kept."""

    def test_citizenship_owner_is_dropped(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for relative in ("src/aipass/aipass", "src/aipass/canary", "projects/baud/src/baud/baud"):
            assert "owner" not in _read(_passport(synthetic_fleet, relative))["citizenship"]

    def test_top_level_family_is_dropped(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for relative in ("src/aipass/canary", "projects/finch/src/finch/finch"):
            assert "family" not in _read(_passport(synthetic_fleet, relative))

    def test_document_metadata_note_is_dropped(self, synthetic_fleet):
        assert "note" not in _migrated(synthetic_fleet, "src/aipass/aipass")["document_metadata"]

    def test_every_drop_is_reported_with_its_old_value(self, synthetic_fleet):
        receipt = migrate_fleet(synthetic_fleet, run_date=RUN_DATE)
        assert receipt["field_counts"]["citizenship.owner"] == 4
        assert receipt["field_counts"]["family"] == 2
        assert receipt["field_counts"]["document_metadata.note"] == 1

    def test_unknown_field_is_preserved_and_reported_not_dropped(self, tmp_path):
        root = tmp_path / "repo"
        document = _legacy_passport(branch_name="odd", path="src/aipass/odd", module="aipass.odd")
        document["branch_info"]["favourite_colour"] = "green"
        document["mystery_block"] = {"who": "unknown"}
        _write_passport(root, "src/aipass/odd", document)

        receipt = migrate_fleet(root, confirm=True, run_date=RUN_DATE)
        migrated = _read(_passport(root, "src/aipass/odd"))

        assert migrated["branch_info"]["favourite_colour"] == "green"
        assert migrated["mystery_block"] == {"who": "unknown"}
        assert list(migrated["branch_info"])[-1] == "favourite_colour"
        assert set(receipt["unknown_fields"]) == {"branch_info.favourite_colour", "mystery_block"}


# =============================================================================
# VALUE LANES
# =============================================================================


class TestValueLanes:
    """Every rename / backfill / casing lane in the brief, one pin each."""

    def test_version_and_schema_version_both_become_2_0_0(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            meta = _read(target.path)["document_metadata"]
            assert (meta["version"], meta["schema_version"]) == ("2.0.0", "2.0.0")

    def test_aipass_framework_becomes_specialist(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "src/aipass/spawn")["identity"]["citizen_class"] == "specialist"

    def test_manager_stays_manager(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for relative in ("src/aipass/devpulse", "projects/baud/src/baud/baud"):
            assert _read(_passport(synthetic_fleet, relative))["identity"]["citizen_class"] == "manager"

    def test_residency_is_core_under_src_aipass_and_resident_under_projects(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            assert _read(target.path)["citizenship"]["residency"] == target.residency

    def test_git_branch_becomes_dev_everywhere(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            assert _read(target.path)["branch_info"]["git_branch"] == "dev"

    def test_registry_path_backfilled_when_missing(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for relative in ("src/aipass/canary", "projects/baud/src/baud/baud"):
            citizenship = _read(_passport(synthetic_fleet, relative))["citizenship"]
            assert citizenship["registry_path"] == CANONICAL_REGISTRY_PATH

    def test_registry_path_outlier_is_reconciled(self, synthetic_fleet):
        citizenship = _migrated(synthetic_fleet, "src/aipass/commons")["citizenship"]
        assert citizenship["registry_path"] == CANONICAL_REGISTRY_PATH

    def test_registry_path_that_is_neither_missing_nor_legacy_is_left_alone(self, tmp_path):
        root = tmp_path / "repo"
        document = _legacy_passport(
            branch_name="odd", path="src/aipass/odd", module="aipass.odd", registry_path="config/custom.json"
        )
        _write_passport(root, "src/aipass/odd", document)
        migrate_fleet(root, confirm=True, run_date=RUN_DATE)
        assert _read(_passport(root, "src/aipass/odd"))["citizenship"]["registry_path"] == "config/custom.json"

    def test_branch_name_managed_by_and_document_name_lowercase(self, synthetic_fleet):
        document = _migrated(synthetic_fleet, "src/aipass/canary")
        assert document["branch_info"]["branch_name"] == "canary"
        assert document["document_metadata"]["managed_by"] == "canary"
        assert document["document_metadata"]["document_name"] == "canary.PASSPORT"

    def test_document_name_keeps_its_suffix_case(self, synthetic_fleet):
        document = _migrated(synthetic_fleet, "projects/baud/src/baud/baud")
        assert document["document_metadata"]["document_name"] == "baud.PASSPORT"

    def test_core_module_gets_the_aipass_prefix(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        assert _read(_passport(synthetic_fleet, "src/aipass/commons"))["branch_info"]["module"] == "aipass.commons"
        assert _read(_passport(synthetic_fleet, "src/aipass/skills"))["branch_info"]["module"] == "aipass.skills"

    def test_resident_module_is_left_alone(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "projects/baud/src/baud/baud")["branch_info"]["module"] == "baud"

    def test_stale_path_is_corrected_from_disk(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "src/aipass/skills")["branch_info"]["path"] == "src/aipass/skills"

    def test_resident_absolute_path_becomes_project_relative(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "projects/baud/src/baud/baud")["branch_info"]["path"] == "src/baud/baud"

    def test_traits_string_becomes_a_one_element_list_verbatim(self, synthetic_fleet):
        original = _read(_passport(synthetic_fleet, "src/aipass/canary"))["identity"]["traits"]
        migrated = _migrated(synthetic_fleet, "src/aipass/canary")["identity"]["traits"]
        assert migrated == [original]

    def test_empty_traits_string_becomes_empty_list(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "src/aipass/spawn")["identity"]["traits"] == []

    def test_existing_traits_list_is_untouched(self, synthetic_fleet):
        original = _read(_passport(synthetic_fleet, "src/aipass/aipass"))["identity"]["traits"]
        assert _migrated(synthetic_fleet, "src/aipass/aipass")["identity"]["traits"] == original

    def test_principles_moves_inside_identity(self, synthetic_fleet):
        original = _read(_passport(synthetic_fleet, "src/aipass/spawn"))["principles"]
        migrated = _migrated(synthetic_fleet, "src/aipass/spawn")
        assert "principles" not in migrated
        assert migrated["identity"]["principles"] == original

    def test_created_date_is_preserved(self, synthetic_fleet):
        before = _read(_passport(synthetic_fleet, "src/aipass/spawn"))["document_metadata"]["created"]
        assert _migrated(synthetic_fleet, "src/aipass/spawn")["document_metadata"]["created"] == before

    def test_last_updated_becomes_the_run_date(self, synthetic_fleet):
        assert _migrated(synthetic_fleet, "src/aipass/spawn")["document_metadata"]["last_updated"] == RUN_DATE


# =============================================================================
# IDENTITY CONTENT — the one thing a structure migration must never touch
# =============================================================================


def _expected_traits(original: object) -> object:
    """The only traits change allowed: a string becomes a one-element list."""
    if isinstance(original, list):
        return original
    return [original] if isinstance(original, str) and original.strip() else []


def _assert_identity_content_preserved(name: str, old: dict, new: dict) -> None:
    """Every identity-content field survives; traits keeps its text, list-wrapped."""
    for key in IDENTITY_CONTENT_KEYS:
        if key == "principles":
            assert new["identity"]["principles"] == old["principles"], name
        elif key == "traits":
            assert new["identity"]["traits"] == _expected_traits(old["identity"]["traits"]), name
        elif key in old["identity"]:
            assert new["identity"][key] == old["identity"][key], f"{name}.{key}"


class TestIdentityContentPreserved:
    """role/purpose/what_i_do/what_i_dont_do/principles text and class_extension."""

    def test_synthetic_identity_content_survives_byte_identical(self, synthetic_fleet):
        before = {t.branch_dir.name: _read(t.path) for t in discover_passports(synthetic_fleet)}
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            old = before[target.branch_dir.name]
            new = _read(target.path)
            for key in ("role", "purpose", "what_i_do", "what_i_dont_do"):
                assert new["identity"][key] == old["identity"][key], f"{target.branch_dir.name}.{key}"
            assert new["identity"]["principles"] == old["principles"], target.branch_dir.name

    def test_devpulse_class_extension_survives_verbatim(self, synthetic_fleet):
        before = _read(_passport(synthetic_fleet, "src/aipass/devpulse"))["identity"]["class_extension"]
        assert _migrated(synthetic_fleet, "src/aipass/devpulse")["identity"]["class_extension"] == before

    def test_live_identity_content_survives_byte_identical(self, live_fleet_copy):
        before = {t.branch_dir.name: _read(t.path) for t in discover_passports(live_fleet_copy)}
        migrate_fleet(live_fleet_copy, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(live_fleet_copy):
            name = target.branch_dir.name
            _assert_identity_content_preserved(name, before[name], _read(target.path))


# =============================================================================
# DRY RUN / BACKUP / IDEMPOTENCY
# =============================================================================


class TestDryRun:
    """Dry run is the default and it writes NOTHING — not even a backup."""

    def test_dry_run_is_the_default(self, synthetic_fleet):
        assert migrate_fleet(synthetic_fleet, run_date=RUN_DATE)["confirm"] is False

    def test_dry_run_changes_no_bytes_and_no_mtimes(self, synthetic_fleet):
        targets = discover_passports(synthetic_fleet)
        before = {t.path: (t.path.read_bytes(), os.stat(t.path).st_mtime_ns) for t in targets}

        receipt = migrate_fleet(synthetic_fleet, run_date=RUN_DATE)

        assert receipt["changed"] == len(targets)
        for path, (content, mtime) in before.items():
            assert path.read_bytes() == content, path
            assert os.stat(path).st_mtime_ns == mtime, path

    def test_dry_run_creates_no_backup(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, run_date=RUN_DATE)
        assert list(synthetic_fleet.rglob(f"*{BACKUP_SUFFIX}")) == []

    def test_dry_run_reports_the_same_counts_the_real_run_applies(self, synthetic_fleet):
        planned = migrate_fleet(synthetic_fleet, run_date=RUN_DATE)
        applied = migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        assert planned["field_counts"] == applied["field_counts"]
        assert planned["changed"] == applied["changed"]


class TestBackup:
    """One backup per passport, ever — the pre-migration original is sacred."""

    def test_backup_is_created_beside_the_passport_with_the_legal_suffix(self, synthetic_fleet):
        path = _passport(synthetic_fleet, "src/aipass/spawn")
        original = path.read_text(encoding="utf-8")

        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)

        backup = path.with_name("passport.json" + BACKUP_SUFFIX)
        assert backup.name == "passport.json.pre_v2_backup"
        assert backup.read_text(encoding="utf-8") == original

    def test_backup_is_never_overwritten_on_a_second_run(self, synthetic_fleet):
        path = _passport(synthetic_fleet, "src/aipass/spawn")
        original = path.read_text(encoding="utf-8")
        backup = path.with_name("passport.json" + BACKUP_SUFFIX)

        first = migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        # Force a second real write by dirtying the migrated file.
        migrated = _read(path)
        migrated["branch_info"]["git_branch"] = "work/spawn"
        path.write_text(json.dumps(migrated, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        second = migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)

        assert first["backups_written"] == len(discover_passports(synthetic_fleet))
        assert second["backups_written"] == 0
        assert backup.read_text(encoding="utf-8") == original

    def test_backup_helper_returns_false_when_source_is_absent(self, tmp_path):
        assert backup_passport(tmp_path / "nope" / "passport.json") is False

    def test_no_backup_when_nothing_would_change(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for backup in synthetic_fleet.rglob(f"*{BACKUP_SUFFIX}"):
            backup.unlink()
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        assert list(synthetic_fleet.rglob(f"*{BACKUP_SUFFIX}")) == []


class TestIdempotency:
    """A second run is a measured no-op — 0 files changed, 0 bytes rewritten."""

    def test_second_run_changes_nothing(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        after_first = {t.path: t.path.read_bytes() for t in discover_passports(synthetic_fleet)}

        second = migrate_fleet(synthetic_fleet, confirm=True, run_date="2026-12-31")

        assert second["changed"] == 0
        assert second["field_counts"] == {}
        for path, content in after_first.items():
            assert path.read_bytes() == content, path

    def test_second_run_is_a_noop_on_real_live_data(self, live_fleet_copy):
        migrate_fleet(live_fleet_copy, confirm=True, run_date=RUN_DATE)
        second = migrate_fleet(live_fleet_copy, confirm=True, run_date="2026-12-31")
        assert (second["changed"], second["backups_written"]) == (0, 0)

    def test_last_updated_is_not_touched_when_nothing_else_changed(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        migrate_fleet(synthetic_fleet, confirm=True, run_date="2026-12-31")
        meta = _read(_passport(synthetic_fleet, "src/aipass/spawn"))["document_metadata"]
        assert meta["last_updated"] == RUN_DATE


# =============================================================================
# PUBLIC-REPO HOUSE RULE
# =============================================================================


class TestNoHardcodedHomePaths:
    """No /home/... may survive anywhere in any migrated passport."""

    def test_synthetic_fleet_keeps_no_absolute_path_at_all(self, synthetic_fleet):
        migrate_fleet(synthetic_fleet, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(synthetic_fleet):
            text = target.path.read_text(encoding="utf-8")
            assert "/home/" not in text, target.path
            assert ABSOLUTE_FOSSIL_PREFIX not in text, target.path
            for value in _string_values(_read(target.path)):
                assert not value.startswith("/"), f"{target.path}: absolute value {value!r}"

    def test_live_fleet_copy_has_no_home_substring_left(self, live_fleet_copy):
        migrate_fleet(live_fleet_copy, confirm=True, run_date=RUN_DATE)
        for target in discover_passports(live_fleet_copy):
            assert "/home/" not in target.path.read_text(encoding="utf-8"), target.path


# =============================================================================
# REFUSALS — never guess, never half-write
# =============================================================================


class TestRefusals:
    """A passport the migration cannot resolve is SKIPPED with the reason said."""

    def test_forbidden_class_is_refused_by_name(self):
        document = _legacy_passport(
            branch_name="rogue", path="src/aipass/rogue", module="aipass.rogue", citizen_class="admin"
        )
        with pytest.raises(PassportMigrationError, match="admin"):
            migrate_document(document, residency="core", relative_path="src/aipass/rogue", run_date=RUN_DATE)

    def test_unknown_class_is_refused_rather_than_defaulted(self):
        document = _legacy_passport(
            branch_name="rogue", path="src/aipass/rogue", module="aipass.rogue", citizen_class="wizard"
        )
        with pytest.raises(PassportMigrationError, match="wizard"):
            migrate_document(document, residency="core", relative_path="src/aipass/rogue", run_date=RUN_DATE)

    def test_conflicting_principles_refuse_rather_than_discard_one(self):
        document = _legacy_passport(branch_name="rogue", path="src/aipass/rogue", module="aipass.rogue")
        document["identity"]["principles"] = ["a different set"]
        with pytest.raises(PassportMigrationError, match="principles"):
            migrate_document(document, residency="core", relative_path="src/aipass/rogue", run_date=RUN_DATE)

    def test_refused_passport_is_reported_and_left_untouched(self, tmp_path):
        root = tmp_path / "repo"
        path = _write_passport(
            root,
            "src/aipass/rogue",
            _legacy_passport(
                branch_name="rogue", path="src/aipass/rogue", module="aipass.rogue", citizen_class="admin"
            ),
        )
        original = path.read_bytes()

        receipt = migrate_fleet(root, confirm=True, run_date=RUN_DATE)

        assert receipt["changed"] == 0
        assert len(receipt["errors"]) == 1
        assert receipt["errors"][0]["branch"] == "rogue"
        assert path.read_bytes() == original
        assert not path.with_name("passport.json" + BACKUP_SUFFIX).exists()

    def test_unreadable_passport_is_reported_not_crashed(self, tmp_path):
        root = tmp_path / "repo"
        trinity = root / "src/aipass/broken/.trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text("{ not json", encoding="utf-8")

        receipt = migrate_fleet(root, confirm=True, run_date=RUN_DATE)
        assert receipt["changed"] == 0
        assert "unreadable" in receipt["errors"][0]["error"]


# =============================================================================
# CLI
# =============================================================================


class TestCli:
    """The command shape: dry-run default, --confirm, --root, --only, --help."""

    def test_help_returns_zero_and_writes_nothing(self, synthetic_fleet):
        from aipass.spawn.apps.modules.migrate_passports import handle_migrate_passports

        before = {t.path: t.path.read_bytes() for t in discover_passports(synthetic_fleet)}
        assert handle_migrate_passports(["--help"]) == 0
        for path, content in before.items():
            assert path.read_bytes() == content

    def test_default_run_against_a_root_writes_nothing(self, synthetic_fleet):
        from aipass.spawn.apps.modules.migrate_passports import handle_migrate_passports

        before = {t.path: t.path.read_bytes() for t in discover_passports(synthetic_fleet)}
        assert handle_migrate_passports(["--root", str(synthetic_fleet)]) == 0
        for path, content in before.items():
            assert path.read_bytes() == content

    def test_confirm_writes(self, synthetic_fleet):
        from aipass.spawn.apps.modules.migrate_passports import handle_migrate_passports

        assert handle_migrate_passports(["--root", str(synthetic_fleet), "--confirm"]) == 0
        assert _read(_passport(synthetic_fleet, "src/aipass/spawn"))["document_metadata"]["schema_version"] == "2.0.0"

    def test_only_restricts_to_one_branch(self, synthetic_fleet):
        receipt = migrate_fleet(synthetic_fleet, only="@spawn", confirm=True, run_date=RUN_DATE)
        assert receipt["scanned"] == 1
        assert receipt["files"][0]["branch"] == "spawn"
        assert _read(_passport(synthetic_fleet, "src/aipass/canary"))["document_metadata"]["schema_version"] == "1.0.0"

    def test_unknown_argument_is_refused(self):
        from aipass.spawn.apps.modules.migrate_passports import handle_migrate_passports

        assert handle_migrate_passports(["--wipe-everything"]) == 1

    def test_entry_point_routes_the_command(self, synthetic_fleet, monkeypatch):
        import sys

        from aipass.spawn.apps import spawn as spawn_entry

        monkeypatch.setattr(sys, "argv", ["spawn", "migrate-passports", "--root", str(synthetic_fleet)])
        assert spawn_entry.main() == 0


# =============================================================================
# SAFETY WIRING — sync-registry --fix is the SECOND fleet-write path
# =============================================================================


class TestSyncRegistryBacksUpBeforeItsWrite:
    """`sync-registry --fix` rewrites citizen_class on live passports too."""

    def test_legacy_class_rewrite_backs_the_passport_up_first(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        root = tmp_path / "project"
        registry_id = "11111111-2222-3333-4444-555555555555"
        document = _legacy_passport(
            branch_name="legacy", path="src/aipass/legacy", module="aipass.legacy", citizen_class="aipass_framework"
        )
        document["citizenship"]["registry_id"] = registry_id
        path = _write_passport(root, "src/aipass/legacy", document)
        original = path.read_text(encoding="utf-8")

        registry_path = root / "AIPASS_REGISTRY.json"
        registry_path.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "id": registry_id, "total_branches": 1},
                    "branches": [
                        {
                            "name": "legacy",
                            "path": "src/aipass/legacy",
                            "created": "2026-03-07",
                            "registry_id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
                            "owner": True,
                        }
                    ],
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        fix_owner_identity(registry_path=registry_path, dry_run=False)

        backup = path.with_name("passport.json" + BACKUP_SUFFIX)
        assert backup.exists(), "sync-registry --fix rewrote a passport with no pre_v2 backup"
        assert backup.read_text(encoding="utf-8") == original
        assert _read(path)["identity"]["citizen_class"] == "specialist"
