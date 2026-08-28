# =================== META ====================
# Name: test_check_fix_identity.py
# Description: Tests for owner/identity check and fix (DPLAN-0239 P4)
# Version: 1.0.0
# Created: 2026-07-11
# Modified: 2026-07-11
# =============================================

"""Tests for check_owner_identity and fix_owner_identity (sync-registry --check/--fix)."""

import json


def _write_registry(tmp_path, metadata=None, branches=None):
    """Helper: write a registry file and return its path."""
    reg = tmp_path / "AIPASS_REGISTRY.json"
    data = {
        "metadata": metadata or {"version": "1.0.0", "last_updated": "2026-07-11", "total_branches": 0},
        "branches": branches or [],
    }
    if branches:
        data["metadata"]["total_branches"] = len(branches)
    reg.write_text(json.dumps(data), encoding="utf-8")
    return reg


def _make_branch(tmp_path, name, rel_path, citizen_class="specialist", passport_rid=""):
    """Helper: create a branch directory with passport on disk."""
    branch_dir = tmp_path / rel_path
    trinity = branch_dir / ".trinity"
    trinity.mkdir(parents=True, exist_ok=True)
    passport = {
        "identity": {"citizen_class": citizen_class},
        "citizenship": {},
    }
    if passport_rid:
        passport["citizenship"]["registry_id"] = passport_rid
    (trinity / "passport.json").write_text(json.dumps(passport), encoding="utf-8")
    return branch_dir


def _entry(name, path, created="2026-01-01", owner=None, registry_id=None):
    """Helper: build a branch entry dict."""
    e = {
        "name": name,
        "path": path,
        "email": f"@{name.lower()}",
        "status": "active",
        "profile": "library",
        "description": "test",
        "created": created,
        "last_active": created,
    }
    if owner is not None:
        e["owner"] = owner
    if registry_id is not None:
        e["registry_id"] = registry_id
    return e


# =====================================================================
# check_owner_identity
# =====================================================================


class TestCheckOwnerIdentity:
    """Tests for check_owner_identity — 7 flags."""

    def test_clean_registry(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="unique-alpha")],
        )

        result = check_owner_identity(registry_path=reg)
        assert result["clean"] is True
        assert result["issues"] == []
        assert result["owner"] == "alpha"
        assert result["owner_uid"] == "unique-alpha"

    def test_pinned_schema_no_owner(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        assert result["owner"] is None
        assert result["owner_uid"] == ""

    def test_no_owner_flag(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "no_owner" in flags

    def test_multi_owner_flag(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha")
        _make_branch(tmp_path, "beta", "src/beta")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("alpha", "src/alpha", owner=True, registry_id="uid-a"),
                _entry("beta", "src/beta", owner=True, registry_id="uid-b"),
            ],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "multi_owner" in flags

    def test_owner_missing_branch_flag(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("ghost", "src/ghost", owner=True, registry_id="uid-g")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "owner_missing_branch" in flags

    def test_metadata_id_missing_flag(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "metadata_id_missing" in flags

    def test_passport_mismatch_flag(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="old-project-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "new-project-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "passport_mismatch" in flags

    def test_entry_rid_stale_missing(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True)],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "entry_rid_stale" in flags

    def test_entry_rid_stale_equals_metadata_id(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        project_id = "proj-id-shared"
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": project_id},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id=project_id)],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "entry_rid_stale" in flags

    def test_entry_rid_stale_duplicate(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity

        dup_id = "duplicate-id"
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("alpha", "src/alpha", owner=True, registry_id=dup_id),
                _entry("beta", "src/beta", registry_id=dup_id),
            ],
        )

        result = check_owner_identity(registry_path=reg)
        stale_issues = [i for i in result["issues"] if i["flag"] == "entry_rid_stale"]
        assert len(stale_issues) == 2


# =====================================================================
# fix_owner_identity
# =====================================================================


class TestFixOwnerIdentity:
    """Tests for fix_owner_identity — reconcile."""

    def test_noop_when_clean(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="unique-alpha")],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["actions"] == []

    def test_seats_missing_owner(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("beta", "src/beta", created="2026-02-01", registry_id="uid-b"),
                _entry("alpha", "src/alpha", created="2026-01-01", registry_id="uid-a"),
            ],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True
        actions_text = " ".join(result["actions"])
        assert "alpha" in actions_text.lower()

        data = json.loads(reg.read_text(encoding="utf-8"))
        alpha = next(b for b in data["branches"] if b["name"] == "alpha")
        assert alpha.get("owner") is True

    def test_resolves_multi_owner(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("alpha", "src/alpha", created="2026-01-01", owner=True, registry_id="uid-a"),
                _entry("beta", "src/beta", created="2026-02-01", owner=True, registry_id="uid-b"),
            ],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        owners = [b for b in data["branches"] if b.get("owner") is True]
        assert len(owners) == 1
        assert owners[0]["name"] == "alpha"

    def test_mints_metadata_id_when_no_passport_consensus(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True
        assert any("Mint" in a for a in result["actions"])

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert len(data["metadata"]["id"]) == 36

    def test_majority_restores_metadata_id_from_passports(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        majority_id = "7087bb93-aaaa-bbbb-cccc-dddddddddddd"
        outlier_id = "deadbeef-0000-1111-2222-333333333333"
        branches = []
        for i in range(13):
            name = f"agent{i:02d}"
            _make_branch(tmp_path, name, f"src/{name}", passport_rid=majority_id)
            branches.append(_entry(name, f"src/{name}", owner=(i == 0), registry_id=f"uid-{i}"))
        _make_branch(tmp_path, "outlier", "src/outlier", passport_rid=outlier_id)
        branches.append(_entry("outlier", "src/outlier", registry_id="uid-out"))

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=branches,
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True
        assert any("Restore" in a and "majority 13 of 14" in a for a in result["actions"])

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["metadata"]["id"] == majority_id

    def test_majority_restore_aligns_outlier_passport(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        majority_id = "7087bb93-aaaa-bbbb-cccc-dddddddddddd"
        outlier_id = "deadbeef-0000-1111-2222-333333333333"
        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid=majority_id)
        _make_branch(tmp_path, "beta", "src/beta", passport_rid=majority_id)
        _make_branch(tmp_path, "gamma", "src/gamma", passport_rid=majority_id)
        _make_branch(tmp_path, "outlier", "src/outlier", passport_rid=outlier_id)

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[
                _entry("alpha", "src/alpha", owner=True, registry_id="uid-a"),
                _entry("beta", "src/beta", registry_id="uid-b"),
                _entry("gamma", "src/gamma", registry_id="uid-g"),
                _entry("outlier", "src/outlier", registry_id="uid-o"),
            ],
        )

        fix_owner_identity(registry_path=reg)

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["metadata"]["id"] == majority_id

        outlier_passport = json.loads((tmp_path / "src/outlier/.trinity/passport.json").read_text(encoding="utf-8"))
        assert outlier_passport["citizenship"]["registry_id"] == majority_id

    def test_mints_metadata_id_when_passports_disagree(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="id-aaa")
        _make_branch(tmp_path, "beta", "src/beta", passport_rid="id-bbb")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[
                _entry("alpha", "src/alpha", owner=True, registry_id="uid-a"),
                _entry("beta", "src/beta", registry_id="uid-b"),
            ],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True
        assert any("Mint" in a for a in result["actions"])

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["metadata"]["id"] != "id-aaa"
        assert data["metadata"]["id"] != "id-bbb"
        assert len(data["metadata"]["id"]) == 36

    def test_mints_per_citizen_uids_for_stale_duplicates(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        shared_id = "stale-project-id"
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("alpha", "src/alpha", owner=True, registry_id=shared_id),
                _entry("beta", "src/beta", registry_id=shared_id),
            ],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["applied"] is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        ids = [b["registry_id"] for b in data["branches"]]
        assert ids[0] != ids[1]
        assert ids[0] != shared_id or ids[1] != shared_id

    def test_aligns_passports_to_metadata_id(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="old-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "new-proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = fix_owner_identity(registry_path=reg)
        actions_text = " ".join(result["actions"])
        assert "passport" in actions_text.lower()

        passport = json.loads((tmp_path / "src" / "alpha" / ".trinity" / "passport.json").read_text(encoding="utf-8"))
        assert passport["citizenship"]["registry_id"] == "new-proj-id"

    def test_dry_run_does_not_write(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )
        original = reg.read_text(encoding="utf-8")

        result = fix_owner_identity(registry_path=reg, dry_run=True)
        assert len(result["actions"]) > 0
        assert result["applied"] is False
        assert reg.read_text(encoding="utf-8") == original

    def test_idempotent(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("alpha", "src/alpha", created="2026-01-01", registry_id="uid-a-stale"),
                _entry("beta", "src/beta", created="2026-02-01"),
            ],
        )

        result1 = fix_owner_identity(registry_path=reg)
        assert result1["applied"] is True

        result2 = fix_owner_identity(registry_path=reg)
        assert result2["actions"] == []

    def test_refuses_to_alter_correct_seat(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="unique-alpha")],
        )

        result = fix_owner_identity(registry_path=reg)
        assert result["actions"] == []
        assert result["applied"] is False


class TestLegacyCitizenClassMigration:
    """Tests for retired-citizen_class passport migration.

    CONTRACT MOVED (DPLAN-0319 R4). This block used to pin builder →
    aipass_framework. That target is itself a retired name now, so the migration
    was rewriting one dead value over another: both land on "specialist", while
    "project_agent" lands on "manager" and the live classes are left alone.
    """

    def test_migrates_every_retired_name_to_its_live_replacement(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "vera", "src/vera", citizen_class="builder", passport_rid="proj-id")
        _make_branch(tmp_path, "writer", "src/writer", citizen_class="aipass_framework", passport_rid="proj-id")
        _make_branch(tmp_path, "pilot", "src/pilot", citizen_class="project_agent", passport_rid="proj-id")
        _make_branch(tmp_path, "modern", "src/modern", citizen_class="specialist", passport_rid="proj-id")
        _make_branch(tmp_path, "boss", "src/boss", citizen_class="manager", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("vera", "src/vera", owner=True, registry_id="uid-v"),
                _entry("writer", "src/writer", registry_id="uid-w"),
                _entry("pilot", "src/pilot", registry_id="uid-p"),
                _entry("modern", "src/modern", registry_id="uid-m"),
                _entry("boss", "src/boss", registry_id="uid-b"),
            ],
        )

        result = fix_owner_identity(registry_path=reg)
        assert any("Migrate" in a and "vera" in a for a in result["actions"])
        assert any("Migrate" in a and "writer" in a for a in result["actions"])
        assert any("Migrate" in a and "pilot" in a for a in result["actions"])
        # Live classes are never "migrated" — that would be a rewrite, not a rename.
        assert not any("modern" in a and "Migrate" in a for a in result["actions"])
        assert not any("boss" in a and "Migrate" in a for a in result["actions"])

        def _class_of(rel):
            return json.loads((tmp_path / rel / ".trinity/passport.json").read_text(encoding="utf-8"))["identity"][
                "citizen_class"
            ]

        assert _class_of("src/vera") == "specialist"
        assert _class_of("src/writer") == "specialist"
        assert _class_of("src/pilot") == "manager"
        assert _class_of("src/modern") == "specialist"
        assert _class_of("src/boss") == "manager"

    def test_migration_backs_the_passport_up_before_rewriting_it(self, tmp_path):
        """A second fleet-write path onto live passports must leave a pre-v2 original.

        `sync-registry --fix` lands the same rename the 2.0 migration tool does, so
        it takes the same backup under the same trinity-legal suffix — whichever
        path touches a passport first owns the true original.
        """
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", citizen_class="aipass_framework", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        fix_owner_identity(registry_path=reg)

        backup = tmp_path / "src/alpha/.trinity/passport.json.pre_v2_backup"
        assert backup.exists(), "the rewrite left no pre-migration original"
        assert json.loads(backup.read_text(encoding="utf-8"))["identity"]["citizen_class"] == "aipass_framework"

    def test_migration_idempotent(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", citizen_class="builder", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        fix_owner_identity(registry_path=reg)
        result2 = fix_owner_identity(registry_path=reg)
        assert not any("Migrate" in a for a in result2["actions"])

    def test_migration_dry_run_no_write(self, tmp_path):
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "alpha", "src/alpha", citizen_class="builder", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = fix_owner_identity(registry_path=reg, dry_run=True)
        assert any("Migrate" in a for a in result["actions"])

        passport = json.loads((tmp_path / "src/alpha/.trinity/passport.json").read_text(encoding="utf-8"))
        assert passport["identity"]["citizen_class"] == "builder"


class TestAdoptCallsEnsureOwner:
    """Test that _adopt_existing calls ensure_project_has_owner."""

    def test_adopt_seats_owner(self, tmp_path):
        from unittest.mock import patch

        from aipass.spawn.apps.modules.core import _adopt_existing

        branch_dir = tmp_path / "my_agent"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"purpose": "test"}, "citizenship": {}}),
            encoding="utf-8",
        )

        reg = _write_registry(tmp_path, branches=[])

        with patch("aipass.spawn.apps.modules.core.find_registry", return_value=reg):
            with patch("aipass.spawn.apps.modules.core.ensure_project_has_owner") as mock_owner:
                with patch("aipass.spawn.apps.modules.core.fix_passport_registry_id"):
                    _adopt_existing(branch_dir, "", None, None)
                    mock_owner.assert_called_once_with(reg)


class TestFixDryRunFullyReadOnly:
    """--fix --dry-run must not write ANYTHING (including old-sync portion)."""

    def test_fix_dry_run_writes_nothing_with_stale_entries(self, tmp_path):
        """Regression: dry-run must not apply old-sync repairs (prune stale, add unreg)."""
        from unittest.mock import patch

        from aipass.spawn.apps.modules.sync_registry import handle_sync_registry

        _make_branch(tmp_path, "real", "src/real", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("real", "src/real", owner=True, registry_id="uid-real"),
                _entry("ghost", "src/ghost", registry_id="uid-ghost"),
            ],
        )
        original = reg.read_text(encoding="utf-8")

        with patch(
            "aipass.spawn.apps.handlers.sync_registry_ops.find_registry",
            return_value=reg,
        ):
            handle_sync_registry(["--fix", "--dry-run"])

        assert reg.read_text(encoding="utf-8") == original


class TestUnifiedOwnerHeuristic:
    """Both ensure_project_has_owner and fix_owner_identity must agree."""

    def test_both_paths_pick_same_owner(self, tmp_path):
        """When first-created and passport-owner differ, both paths must agree."""
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner, pick_owner_branch
        from aipass.spawn.apps.handlers.sync_registry_ops import fix_owner_identity

        _make_branch(tmp_path, "older", "src/older", citizen_class="specialist")
        _make_branch(tmp_path, "newer", "src/newer", citizen_class="manager")

        branches = [
            _entry("older", "src/older", created="2026-01-01", registry_id="uid-old"),
            _entry("newer", "src/newer", created="2026-03-01", registry_id="uid-new"),
        ]

        picked = pick_owner_branch(branches, tmp_path)
        assert picked is not None
        assert picked["name"] == "newer"

        reg_fix = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("older", "src/older", created="2026-01-01", registry_id="uid-old"),
                _entry("newer", "src/newer", created="2026-03-01", registry_id="uid-new"),
            ],
        )
        fix_result = fix_owner_identity(registry_path=reg_fix)
        fix_data = json.loads(reg_fix.read_text(encoding="utf-8"))
        fix_owner = next(b for b in fix_data["branches"] if b.get("owner") is True)

        reg_ensure = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[
                _entry("older", "src/older", created="2026-01-01", registry_id="uid-old2"),
                _entry("newer", "src/newer", created="2026-03-01", registry_id="uid-new2"),
            ],
        )
        ensure_project_has_owner(reg_ensure)
        ensure_data = json.loads(reg_ensure.read_text(encoding="utf-8"))
        ensure_owner = next(b for b in ensure_data["branches"] if b.get("owner") is True)

        assert fix_owner["name"] == ensure_owner["name"] == "newer"
        assert fix_result["applied"] is True
