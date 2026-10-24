# =================== META ====================
# Name: test_check_fix_identity.py
# Description: Tests for owner/identity check and fix (DPLAN-0239 P4)
# Version: 1.0.5
# Created: 2026-07-11
# Modified: 2026-10-24
# =============================================

"""Tests for apps/handlers/sync_registry_ops.py and apps/modules/sync_registry.py."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(documentation) — docstrings on check_owner_identity, fix_owner_identity and pick_owner_branch
# seedgo: no-test-needed(constant) — the flag-name strings ("no_owner", "multi_owner", "multi_ci_cure", etc.) sync_registry_ops emits

import json

from aipass.spawn.apps.handlers.registry import ensure_project_has_owner, pick_owner_branch
from aipass.spawn.apps.handlers.sync_registry_ops import check_owner_identity, fix_owner_identity
from aipass.spawn.apps.handlers.adoption_ops import adopt_existing
from aipass.spawn.apps.modules.sync_registry import handle_sync_registry


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

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        assert result["owner"] is None
        assert result["owner_uid"] == ""

    def test_no_owner_flag(self, tmp_path):

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "no_owner" in flags

    def test_multi_owner_flag(self, tmp_path):

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

    def test_a_second_ci_cure_holder_is_reported_by_check_and_one_is_not(self, tmp_path, monkeypatch, capsys):
        _make_branch(tmp_path, "alpha", "src/alpha")
        _make_branch(tmp_path, "trigger", "src/trigger")
        trigger = _entry("trigger", "src/trigger", registry_id="uid-t")
        trigger["ci_cure"] = True
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a"), trigger],
        )
        monkeypatch.setattr("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", lambda *a, **k: reg)

        handle_sync_registry(["--check"])
        assert "multi_ci_cure" not in "".join(capsys.readouterr())

        data = json.loads(reg.read_text(encoding="utf-8"))
        data["branches"][0]["ci_cure"] = True
        reg.write_text(json.dumps(data), encoding="utf-8")
        result = handle_sync_registry(["--check"])

        said = " ".join("".join(capsys.readouterr()).split())
        assert result == 1
        assert "multi_ci_cure" in said
        assert "alpha, trigger" in said

    def test_owner_missing_branch_flag(self, tmp_path):

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("ghost", "src/ghost", owner=True, registry_id="uid-g")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "owner_missing_branch" in flags

    def test_metadata_id_missing_flag(self, tmp_path):

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="uid-a")],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "metadata_id_missing" in flags

    def test_passport_mismatch_flag(self, tmp_path):

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

        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True)],
        )

        result = check_owner_identity(registry_path=reg)
        flags = [i["flag"] for i in result["issues"]]
        assert "entry_rid_stale" in flags

    def test_entry_rid_stale_equals_metadata_id(self, tmp_path):

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
        """A clean project is not written at all: the registry and passport keep bytes and mtime.

        test_refuses_to_alter_correct_seat reads the answer; this reads the disk.
        """

        branch = _make_branch(tmp_path, "alpha", "src/alpha", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "last_updated": "2026-07-11", "id": "proj-id"},
            branches=[_entry("alpha", "src/alpha", owner=True, registry_id="unique-alpha")],
        )
        watched = [reg, branch / ".trinity" / "passport.json"]
        before = [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched]

        result = fix_owner_identity(registry_path=reg)

        assert result["actions"] == []
        assert [(p.read_bytes(), p.stat().st_mtime_ns) for p in watched] == before

    def test_seats_missing_owner(self, tmp_path):

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
        # Measured 2026-09-08, not tolerated: BOTH duplicates are re-minted, and the
        # project credential is left alone. The old `!= shared or != shared` passed
        # whenever either one moved, which is a world this lane never produces.
        assert ids[0] != ids[1]
        assert shared_id not in ids, f"a stale duplicate survived the mint: {ids}"
        assert [len(i) for i in ids] == [36, 36], ids
        assert data["metadata"]["id"] == "proj-id", "the project credential is not a per-citizen uid"

    def test_aligns_passports_to_metadata_id(self, tmp_path):

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
    """Test that adopt_existing calls ensure_project_has_owner."""

    def test_adopt_seats_owner(self, tmp_path):
        """Adoption seats an owner and repairs the passport's registry_id against the found registry.

        Mutant: adopt_existing drops its fix_passport_registry_id call -> red.
        """
        from unittest.mock import patch

        branch_dir = tmp_path / "my_agent"
        trinity = branch_dir / ".trinity"
        trinity.mkdir(parents=True)
        (trinity / "passport.json").write_text(
            json.dumps({"identity": {"purpose": "test"}, "citizenship": {}}),
            encoding="utf-8",
        )

        reg = _write_registry(tmp_path, branches=[])

        # The adoption lane lives in handlers/adoption_ops (split out of core when
        # core crossed the 600-line standard); core re-exports it, but patches
        # must target the module where the names are actually looked up.
        # update_ops.find_registry is the template update's by-name lookup; it walks
        # from the CWD, so it is pointed at the tmp_path registry too.
        with (
            patch("aipass.spawn.apps.handlers.adoption_ops.find_registry", return_value=reg),
            patch("aipass.spawn.apps.handlers.update_ops.find_registry", return_value=reg),
            patch("aipass.spawn.apps.handlers.adoption_ops.ensure_project_has_owner") as mock_owner,
            patch("aipass.spawn.apps.handlers.adoption_ops.fix_passport_registry_id") as mock_fix_rid,
        ):
            adopt_existing(branch_dir, "", None, None)
        mock_owner.assert_called_once_with(reg)
        mock_fix_rid.assert_called_once_with(branch_dir, reg)


class TestFixDryRunFullyReadOnly:
    """--fix --dry-run must not write ANYTHING (including old-sync portion)."""

    def test_fix_dry_run_writes_nothing_with_stale_entries(self, tmp_path):
        """Regression: dry-run must not apply old-sync repairs (prune stale, add unreg)."""
        from unittest.mock import patch

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

    def test_fix_with_no_registry_refuses_on_stderr_instead_of_raising(self, tmp_path, monkeypatch, capsys):
        """Pins the KeyError 'actions': the no-registry answer came back check-shaped."""
        from unittest.mock import patch

        monkeypatch.chdir(tmp_path)
        with patch("aipass.spawn.apps.handlers.sync_registry_ops.find_registry", return_value=None):
            result = handle_sync_registry(["--fix", "--dry-run"])

        out, err = capsys.readouterr()
        assert result == 1
        assert "no registry found" in err
        assert "No stale entries" not in out, "a missing registry is not a clean sync report"


class TestUnifiedOwnerHeuristic:
    """Both ensure_project_has_owner and fix_owner_identity must agree."""

    def test_both_paths_pick_same_owner(self, tmp_path):
        """When first-created and passport-owner differ, both paths must agree."""

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


class TestSyncRegistryCommand:
    """sync-registry through handle_sync_registry: which registry it touches, and when it refuses."""

    def test_an_unreadable_registry_with_fix_exits_1_and_keeps_its_bytes(self, tmp_path, monkeypatch, capsys):
        """Pins --fix saving {"branches": []} with a new id over a registry it could not read."""

        reg = tmp_path / "AIPASS_REGISTRY.json"
        reg.write_text('<<<<<<< HEAD\n{"metadata": {"id": "proj-id"}, "branches": []}\n', encoding="utf-8")
        before = reg.read_bytes()
        monkeypatch.chdir(tmp_path)

        assert handle_sync_registry([str(tmp_path), "--fix"]) == 1

        assert "could not be read" in capsys.readouterr().err
        assert reg.read_bytes() == before

    def test_fix_and_check_refuse_an_unreadable_registry(self, tmp_path):

        reg = tmp_path / "AIPASS_REGISTRY.json"
        reg.write_text("{not json", encoding="utf-8")

        fixed = fix_owner_identity(registry_path=reg)
        checked = check_owner_identity(registry_path=reg)

        assert "could not be read" in fixed["error"] and fixed["applied"] is False
        assert reg.read_text(encoding="utf-8") == "{not json"
        assert checked["clean"] is False
        assert [i["flag"] for i in checked["issues"]] == ["unreadable_registry"]

    def test_a_named_project_is_synced_not_the_cwd_project(self, tmp_path, monkeypatch):
        """Pins `sync-registry /B --fix` from inside A rewriting A's entries."""

        project_a, project_b = tmp_path / "a", tmp_path / "b"
        project_a.mkdir()
        project_b.mkdir()
        reg_a = _write_registry(project_a, metadata={"version": "1.0.0", "id": "id-a"})
        reg_b = _write_registry(project_b, metadata={"version": "1.0.0", "id": "id-b"})
        _make_branch(project_a, "alpha", "alpha")
        _make_branch(project_b, "beta", "beta")
        before_a = reg_a.read_bytes()
        monkeypatch.chdir(project_a)

        assert handle_sync_registry([str(project_b), "--fix"]) == 0

        assert reg_a.read_bytes() == before_a
        assert [b["name"] for b in json.loads(reg_b.read_text(encoding="utf-8"))["branches"]] == ["BETA"]

    def test_a_named_path_with_no_registry_exits_1_and_leaves_the_cwd_registry(self, tmp_path, monkeypatch, capsys):

        project_a, elsewhere = tmp_path / "a", tmp_path / "elsewhere"
        project_a.mkdir()
        elsewhere.mkdir()
        reg_a = _write_registry(project_a, metadata={"version": "1.0.0", "id": "id-a"})
        _make_branch(project_a, "alpha", "alpha")
        before_a = reg_a.read_bytes()
        monkeypatch.chdir(project_a)

        assert handle_sync_registry([str(elsewhere), "--fix"]) == 1

        assert "No *_REGISTRY.json found" in capsys.readouterr().err
        assert reg_a.read_bytes() == before_a

    def test_a_branch_moved_by_hand_keeps_its_entry_and_sealed_flags(self, tmp_path, monkeypatch):
        """Pins --fix deleting the moved entry as stale, owner and admin flags with it."""

        _make_branch(tmp_path, "devpulse", "src/devpulse", passport_rid="proj-id")
        entry = _entry("DEVPULSE", "devpulse", owner=True, registry_id="uid-dp")
        entry["admin"] = True
        reg = _write_registry(tmp_path, metadata={"version": "1.0.0", "id": "proj-id"}, branches=[entry])
        monkeypatch.chdir(tmp_path)

        assert handle_sync_registry([str(tmp_path), "--fix"]) == 0

        [kept] = json.loads(reg.read_text(encoding="utf-8"))["branches"]
        assert kept["path"] == "src/devpulse"
        assert (kept["owner"], kept["admin"], kept["registry_id"]) == (True, True, "uid-dp")

    def test_a_hyphenated_branch_is_registered_once(self, tmp_path, monkeypatch):
        """Pins `create my-agent` (MY_AGENT) gaining a second MY-AGENT entry from --fix."""

        _make_branch(tmp_path, "my-agent", "my-agent", passport_rid="proj-id")
        reg = _write_registry(
            tmp_path,
            metadata={"version": "1.0.0", "id": "proj-id"},
            branches=[_entry("MY_AGENT", "my-agent", owner=True, registry_id="uid-ma")],
        )
        monkeypatch.chdir(tmp_path)

        assert handle_sync_registry([str(tmp_path), "--fix"]) == 0

        assert [b["name"] for b in json.loads(reg.read_text(encoding="utf-8"))["branches"]] == ["MY_AGENT"]

    def test_owner_check_and_fix_never_follow_an_entry_out_of_the_project(self, tmp_path):
        """Pins fix rewriting the passport of an entry whose path climbs out of the project."""

        project = tmp_path / "proj"
        project.mkdir()
        outside = _make_branch(tmp_path, "stray", "stray", passport_rid="someone-elses-id")
        _make_branch(project, "alpha", "alpha", passport_rid="proj-id")
        reg = _write_registry(
            project,
            metadata={"version": "1.0.0", "id": "proj-id"},
            branches=[
                _entry("alpha", "alpha", owner=True, registry_id="uid-a"),
                _entry("stray", "../stray", created="2026-02-01", registry_id="uid-s"),
            ],
        )
        passport = outside / ".trinity" / "passport.json"
        before = passport.read_bytes()

        checked = check_owner_identity(registry_path=reg)
        fixed = fix_owner_identity(registry_path=reg)

        assert not [i for i in checked["issues"] if i["flag"] == "passport_mismatch"]
        assert not [a for a in fixed["actions"] if "stray" in a]
        assert passport.read_bytes() == before
