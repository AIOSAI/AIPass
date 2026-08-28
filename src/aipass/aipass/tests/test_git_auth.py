# =================== AIPass ====================
# Name: test_git_auth.py
# Description: Tests for the init git-auth provisioning handler (DPLAN-0281 P2)
# Version: 1.0.0
# Created: 2026-08-04
# Modified: 2026-08-04
# =============================================

"""Tests for ``aipass init update``'s git-auth provisioning (DPLAN-0281 P2).

Covers the repair set that makes drone's four owner-tier checks true for a
consuming project, the guardrail refusals that must never be repaired around,
and the independent post-repair verification.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional

import pytest

from aipass.aipass.apps.handlers.init.git_auth import (
    GitAuthRefusal,
    find_registry,
    provision_git_auth,
    verify_git_auth,
)


# =============================================================================
# Fixtures / builders
# =============================================================================


def _write(path: Path, data: Dict[str, Any]) -> None:
    """Write a JSON file, creating parent directories as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def build_project(
    root: Path,
    *,
    registry_id: Optional[str] = "8fb38c96-880d-43d6-823b-98f4b9559194",
    owner_flag: bool = True,
    owner_path: Optional[str] = "src/demo/vera",
    citizen_class: str = "builder",
    passport_registry_id: Optional[str] = "8fb38c96-880d-43d6-823b-98f4b9559194",
    passport_owner: Optional[bool] = None,
    make_passport: bool = True,
    branches_as_dict: bool = False,
) -> Path:
    """Create a minimal external AIPass project and return its registry path.

    Defaults reproduce the live Vera-Studio shape: owner seated, tenancy
    matching, real recorded path — only the manager-class flip missing.
    """
    metadata: Dict[str, Any] = {"name": "DEMO", "version": "1.0.0"}
    if registry_id is not None:
        metadata["id"] = registry_id

    vera: Dict[str, Any] = {"name": "VERA", "email": "@vera", "created": "2026-04-08"}
    if owner_path is not None:
        vera["path"] = owner_path
    if owner_flag:
        vera["owner"] = True

    writer: Dict[str, Any] = {"name": "WRITER", "path": "src/demo/writer", "created": "2026-05-01"}

    branches: Any
    if branches_as_dict:
        branches = {"vera": vera, "writer": writer}
    else:
        branches = [vera, writer]

    registry_path = root / "DEMO_REGISTRY.json"
    _write(registry_path, {"metadata": metadata, "branches": branches})

    if make_passport and owner_path:
        citizenship: Dict[str, Any] = {"registered": True}
        if passport_registry_id is not None:
            citizenship["registry_id"] = passport_registry_id
        if passport_owner is not None:
            citizenship["owner"] = passport_owner
        _write(
            root / owner_path / ".trinity" / "passport.json",
            {
                "branch_info": {"branch_name": "VERA", "path": owner_path},
                "identity": {"citizen_class": citizen_class, "role": "ceo"},
                "citizenship": citizenship,
            },
        )
    return registry_path


def read_json(path: Path) -> Dict[str, Any]:
    """Read a JSON file written by the builders."""
    return json.loads(path.read_text(encoding="utf-8"))


def owner_entry(registry_path: Path, name: str = "VERA") -> Dict[str, Any]:
    """Return the named branch entry from either registry shape."""
    branches = read_json(registry_path)["branches"]
    if isinstance(branches, dict):
        branches = list(branches.values())
    return next(b for b in branches if b.get("name") == name)


# =============================================================================
# Registry discovery
# =============================================================================


def test_find_registry_walks_up_from_a_subdirectory(tmp_path: Path) -> None:
    """A citizen standing in its own branch dir still finds the project registry."""
    registry_path = build_project(tmp_path)
    found = find_registry(tmp_path / "src" / "demo" / "vera")
    assert found == registry_path


def test_find_registry_returns_none_outside_a_project(tmp_path: Path) -> None:
    """A directory with no registry above it is not an AIPass project."""
    assert find_registry(tmp_path) is None


def test_provision_refuses_when_no_registry_exists(tmp_path: Path) -> None:
    """Refusal names 'aipass init' rather than crashing on a missing registry."""
    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)
    assert "aipass init" in str(exc.value)


# =============================================================================
# The repair set
# =============================================================================


def test_flips_owner_citizen_class_to_manager(tmp_path: Path) -> None:
    """The live Vera-Studio case: everything set but the builder→manager flip."""
    build_project(tmp_path)

    result = provision_git_auth(tmp_path)

    passport = read_json(tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json")
    assert passport["identity"]["citizen_class"] == "manager"
    assert result["owner"] == "VERA"
    assert result["verified"] is True
    assert any("citizen_class builder → manager" in r for r in result["repairs"])
    assert len(result["repairs"]) == 1


def test_mints_metadata_id_and_backfills_passport_tenancy(tmp_path: Path) -> None:
    """A registry with no id gets one, and the owner's passport is aligned to it."""
    registry_path = build_project(tmp_path, registry_id=None, passport_registry_id=None)

    result = provision_git_auth(tmp_path)

    minted = read_json(registry_path)["metadata"]["id"]
    passport = read_json(tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json")
    assert minted
    assert passport["citizenship"]["registry_id"] == minted
    assert result["verified"] is True
    assert any("minted metadata.id" in r for r in result["repairs"])


def test_realigns_a_passport_that_belongs_to_another_registry(tmp_path: Path) -> None:
    """A stale registry_id from another project is corrected, not left to deny tenancy."""
    build_project(tmp_path, passport_registry_id="00000000-0000-0000-0000-000000000000")

    result = provision_git_auth(tmp_path)

    passport = read_json(tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json")
    assert passport["citizenship"]["registry_id"] == "8fb38c96-880d-43d6-823b-98f4b9559194"
    assert result["verified"] is True


def test_a_passport_owner_claim_no_longer_seats_the_flag(tmp_path: Path) -> None:
    """The passport-side fallback retired with passport 2.0 (DPLAN-0319).

    ``citizenship.owner`` is DROPPED by the migration, so a passport carrying
    it is a pre-2.0 fossil, not an authority. It refuses, and it does not
    quietly write ``owner: true`` into the registry off a dead field.
    """
    registry_path = build_project(tmp_path, owner_flag=False, passport_owner=True)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert '"owner": true' in str(exc.value)
    assert "owner" not in owner_entry(registry_path)


def test_no_owner_refusal_names_the_retired_passport_fallback(tmp_path: Path) -> None:
    """Loud, not silent: the refusal says WHY a passport claim stopped working.

    Without this sentence, a project whose passport used to seat the flag reads
    "nobody is marked" and has no way to know the rule changed under it.
    """
    build_project(tmp_path, owner_flag=False, passport_owner=True)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    message = str(exc.value)
    assert "citizenship.owner" in message
    assert "registry" in message


def test_records_missing_path_from_the_citizens_own_passport(tmp_path: Path) -> None:
    """An entry with no path is bound to the directory its passport actually lives in."""
    registry_path = build_project(tmp_path, owner_path=None)
    _write(
        tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json",
        {
            "branch_info": {"branch_name": "VERA"},
            "identity": {"citizen_class": "builder"},
            "citizenship": {"registry_id": "8fb38c96-880d-43d6-823b-98f4b9559194"},
        },
    )

    result = provision_git_auth(tmp_path)

    assert owner_entry(registry_path)["path"] == "src/demo/vera"
    assert result["verified"] is True


def test_honest_no_op_when_everything_already_holds(tmp_path: Path) -> None:
    """A provisioned project reports zero repairs, not a fake success."""
    build_project(tmp_path, citizen_class="manager")

    result = provision_git_auth(tmp_path)

    assert result["repairs"] == []
    assert result["verified"] is True
    # One line per condition already satisfied: owner flag, metadata.id,
    # path-binding, manager class, tenancy.
    assert len(result["already_ok"]) == 5


def test_second_run_is_idempotent(tmp_path: Path) -> None:
    """Re-running repairs nothing and still verifies."""
    build_project(tmp_path)
    first = provision_git_auth(tmp_path)
    second = provision_git_auth(tmp_path)

    assert first["repairs"]
    assert second["repairs"] == []
    assert second["verified"] is True


def test_dict_shaped_registry_is_repaired_without_reshaping(tmp_path: Path) -> None:
    """A name-keyed registry is repaired in place, keeping its authored shape."""
    registry_path = build_project(tmp_path, branches_as_dict=True)

    result = provision_git_auth(tmp_path)

    assert isinstance(read_json(registry_path)["branches"], dict)
    assert result["owner"] == "VERA"
    assert result["verified"] is True


def test_stale_branch_info_class_is_updated_too(tmp_path: Path) -> None:
    """A second copy of the class under branch_info must not be left stale."""
    build_project(tmp_path)
    passport_path = tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json"
    passport = read_json(passport_path)
    passport["branch_info"]["citizen_class"] = "builder"
    _write(passport_path, passport)

    provision_git_auth(tmp_path)

    assert read_json(passport_path)["branch_info"]["citizen_class"] == "manager"


# =============================================================================
# Guardrail — the repo-root path refusal
# =============================================================================


@pytest.mark.parametrize("root_path", [".", "./", ""])
def test_refuses_a_repo_root_owner_path(tmp_path: Path, root_path: str) -> None:
    """Path-binding is at-or-under: a root path would let any directory hold git."""
    registry_path = build_project(tmp_path, owner_path=root_path)
    _write(
        tmp_path / ".trinity" / "passport.json",
        {"branch_info": {"branch_name": "VERA"}, "identity": {"citizen_class": "builder"}},
    )
    before = registry_path.read_text(encoding="utf-8")

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    message = str(exc.value)
    assert "project root" in message or "no directory under" in message
    assert registry_path.read_text(encoding="utf-8") == before


def test_refuses_an_absolute_repo_root_owner_path(tmp_path: Path) -> None:
    """An absolute path to the repo root is the same guardrail breach as '.'."""
    build_project(tmp_path, owner_path=str(tmp_path))

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "project root" in str(exc.value)


def test_refuses_a_path_outside_the_project(tmp_path: Path) -> None:
    """A path outside the repo can never match path-binding, so it refuses."""
    outside = tmp_path.parent / "elsewhere"
    outside.mkdir(exist_ok=True)
    build_project(tmp_path, owner_path=str(outside))

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "outside the project" in str(exc.value)


def test_refuses_when_the_recorded_path_does_not_exist(tmp_path: Path) -> None:
    """A path pointing at nothing refuses instead of binding authority to a ghost."""
    build_project(tmp_path, owner_path="src/demo/ghost", make_passport=False)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "does not" in str(exc.value)


def test_refuses_when_the_owner_directory_has_no_passport(tmp_path: Path) -> None:
    """An owner entry must point at a real citizen, and the refusal says how to make one."""
    build_project(tmp_path, make_passport=False)
    (tmp_path / "src" / "demo" / "vera").mkdir(parents=True)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "no passport" in str(exc.value)
    assert "drone @spawn create" in str(exc.value)


# =============================================================================
# Owner selection — marked, never guessed
# =============================================================================


def test_refuses_when_no_citizen_is_marked_owner(tmp_path: Path) -> None:
    """With nobody marked, the refusal names the exact key to add and who is listed."""
    build_project(tmp_path, owner_flag=False)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    message = str(exc.value)
    assert '"owner": true' in message
    assert "VERA" in message and "WRITER" in message


def test_refuses_when_two_citizens_are_marked_owner(tmp_path: Path) -> None:
    """Two owners is ambiguous — it refuses and names both."""
    registry_path = build_project(tmp_path)
    data = read_json(registry_path)
    data["branches"][1]["owner"] = True
    _write(registry_path, data)

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "more than one citizen" in str(exc.value)
    assert "VERA, WRITER" in str(exc.value)


def test_two_passport_claims_are_one_plain_no_owner_refusal(tmp_path: Path) -> None:
    """With the fallback retired, N passport claims are not an ambiguity at all.

    The old "more than one passport claims" branch existed only because
    passports could seat the flag. They cannot, so two claims are simply two
    citizens nobody marked — and the refusal says the one thing that fixes it.
    """
    build_project(tmp_path, owner_flag=False, passport_owner=True)
    _write(
        tmp_path / "src" / "demo" / "writer" / ".trinity" / "passport.json",
        {
            "branch_info": {"branch_name": "WRITER"},
            "identity": {"citizen_class": "builder"},
            "citizenship": {"owner": True},
        },
    )

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    message = str(exc.value)
    assert "more than one passport" not in message
    assert '"owner": true' in message
    assert "VERA" in message and "WRITER" in message


def test_registry_flag_wins_over_a_contradicting_passport(tmp_path: Path) -> None:
    """A stale passport claim on ANOTHER citizen cannot deflect the seated owner."""
    build_project(tmp_path)  # VERA flagged in the registry
    _write(
        tmp_path / "src" / "demo" / "writer" / ".trinity" / "passport.json",
        {
            "branch_info": {"branch_name": "WRITER"},
            "identity": {"citizen_class": "builder"},
            "citizenship": {"owner": True},
        },
    )

    result = provision_git_auth(tmp_path)

    assert result["owner"] == "VERA"
    assert result["verified"] is True


# =============================================================================
# Dry run
# =============================================================================


def test_dry_run_plans_repairs_without_writing(tmp_path: Path) -> None:
    """Preview reports the full plan and leaves both files byte-identical."""
    registry_path = build_project(tmp_path, registry_id=None, passport_registry_id=None)
    passport_path = tmp_path / "src" / "demo" / "vera" / ".trinity" / "passport.json"
    registry_before = registry_path.read_text(encoding="utf-8")
    passport_before = passport_path.read_text(encoding="utf-8")

    result = provision_git_auth(tmp_path, dry_run=True)

    assert result["dry_run"] is True
    assert result["verified"] is None
    assert len(result["repairs"]) >= 2
    assert registry_path.read_text(encoding="utf-8") == registry_before
    assert passport_path.read_text(encoding="utf-8") == passport_before


def test_dry_run_still_refuses_a_root_path(tmp_path: Path) -> None:
    """The guardrail holds in preview mode too."""
    build_project(tmp_path, owner_path=".")

    with pytest.raises(GitAuthRefusal):
        provision_git_auth(tmp_path, dry_run=True)


# =============================================================================
# Independent verification
# =============================================================================


def test_verify_reports_every_failing_check(tmp_path: Path) -> None:
    """Verification names each failing check rather than a single pass/fail."""
    registry_path = build_project(
        tmp_path,
        registry_id=None,
        owner_flag=False,
        passport_registry_id=None,
    )

    failures = verify_git_auth(registry_path, "VERA")

    joined = " | ".join(failures)
    assert "check 1" in joined
    assert "check 2" in joined
    assert "check 3" in joined


def test_verify_is_clean_on_a_provisioned_project(tmp_path: Path) -> None:
    """A repaired project verifies with no failures."""
    registry_path = build_project(tmp_path)
    provision_git_auth(tmp_path)

    assert verify_git_auth(registry_path, "VERA") == []


def test_verify_matches_the_owner_name_case_insensitively(tmp_path: Path) -> None:
    """Registries differ on casing ('VERA' vs 'vera') — lookup must not."""
    registry_path = build_project(tmp_path, citizen_class="manager")

    assert verify_git_auth(registry_path, "vera") == []


def test_verify_names_an_unlisted_caller(tmp_path: Path) -> None:
    """A caller absent from the registry fails check 3 by name."""
    registry_path = build_project(tmp_path)

    failures = verify_git_auth(registry_path, "GHOST")

    assert len(failures) == 1
    assert "not listed" in failures[0]


def test_verify_catches_a_registry_edited_after_repair(tmp_path: Path) -> None:
    """Verification re-reads from disk — it never trusts the repair's own report."""
    registry_path = build_project(tmp_path)
    provision_git_auth(tmp_path)

    data = read_json(registry_path)
    data["branches"][0].pop("owner")
    _write(registry_path, data)

    failures = verify_git_auth(registry_path, "VERA")
    assert any("check 3" in f for f in failures)


# =============================================================================
# Corrupt input
# =============================================================================


def test_refuses_an_unreadable_registry(tmp_path: Path) -> None:
    """Corrupt JSON refuses with a fix instruction, never a stack trace."""
    (tmp_path / "DEMO_REGISTRY.json").write_text("{not json", encoding="utf-8")

    with pytest.raises(GitAuthRefusal) as exc:
        provision_git_auth(tmp_path)

    assert "could not be read" in str(exc.value)
