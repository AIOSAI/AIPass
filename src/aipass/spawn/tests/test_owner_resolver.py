# =================== META ====================
# Name: test_owner_resolver.py
# Description: Tests for owner resolver and registry authority
# Version: 1.0.0
# Created: 2026-07-10
# Modified: 2026-07-10
# =============================================

"""Tests for owner resolver: get_owner, is_owner, ensure_project_has_owner, backfill."""

import json
import pytest
from unittest.mock import patch


@pytest.fixture
def registry_with_owner(tmp_path):
    """Create a registry file with one owner branch."""
    reg = tmp_path / "AIPASS_REGISTRY.json"
    reg.write_text(
        json.dumps(
            {
                "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 3},
                "branches": [
                    {
                        "name": "alpha",
                        "path": "src/alpha",
                        "email": "@alpha",
                        "status": "active",
                        "profile": "library",
                        "description": "test",
                        "created": "2026-01-01",
                        "last_active": "2026-01-01",
                    },
                    {
                        "name": "devpulse",
                        "path": "src/devpulse",
                        "email": "@devpulse",
                        "status": "active",
                        "profile": "library",
                        "description": "orchestrator",
                        "created": "2026-01-02",
                        "last_active": "2026-01-02",
                        "owner": True,
                        "registry_id": "abc-123",
                    },
                    {
                        "name": "gamma",
                        "path": "src/gamma",
                        "email": "@gamma",
                        "status": "active",
                        "profile": "library",
                        "description": "test",
                        "created": "2026-01-03",
                        "last_active": "2026-01-03",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return reg


@pytest.fixture
def registry_no_owner(tmp_path):
    """Create a registry file with no owner set."""
    reg = tmp_path / "AIPASS_REGISTRY.json"
    reg.write_text(
        json.dumps(
            {
                "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 2},
                "branches": [
                    {
                        "name": "alpha",
                        "path": "src/alpha",
                        "email": "@alpha",
                        "status": "active",
                        "profile": "library",
                        "description": "test",
                        "created": "2026-04-16",
                        "last_active": "2026-04-16",
                    },
                    {
                        "name": "devpulse",
                        "path": "src/devpulse",
                        "email": "@devpulse",
                        "status": "active",
                        "profile": "library",
                        "description": "orchestrator",
                        "created": "2026-04-28",
                        "last_active": "2026-04-28",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return reg


class TestGetOwner:
    """Tests for get_owner()."""

    def test_returns_owner_entry(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import get_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            result = get_owner(start_path=tmp_path)

        assert result is not None
        assert result["name"] == "devpulse"
        assert result["owner"] is True

    def test_returns_none_when_no_owner(self, registry_no_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import get_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_no_owner):
            result = get_owner(start_path=tmp_path)

        assert result is None

    def test_returns_none_when_registry_missing(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import get_owner

        missing = tmp_path / "MISSING_REGISTRY.json"
        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=missing):
            result = get_owner(start_path=tmp_path)

        assert result is None

    def test_default_start_path_uses_cwd(self, registry_with_owner):
        from aipass.spawn.apps.handlers.registry import get_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            result = get_owner()

        assert result is not None
        assert result["name"] == "devpulse"


class TestIsOwner:
    """Tests for is_owner()."""

    def test_true_for_owner_email_with_at(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner("@devpulse", start_path=tmp_path) is True

    def test_true_for_owner_email_without_at(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner("devpulse", start_path=tmp_path) is True

    def test_case_insensitive(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner("DEVPULSE", start_path=tmp_path) is True
            assert is_owner("@DEVPULSE", start_path=tmp_path) is True
            assert is_owner("DevPulse", start_path=tmp_path) is True
            assert is_owner("ALPHA", start_path=tmp_path) is False

    def test_false_for_non_owner(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner("@alpha", start_path=tmp_path) is False

    def test_false_for_empty_email(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner("", start_path=tmp_path) is False

    def test_false_for_none_email(self, registry_with_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_with_owner):
            assert is_owner(None, start_path=tmp_path) is False

    def test_false_when_no_owner_in_registry(self, registry_no_owner, tmp_path):
        from aipass.spawn.apps.handlers.registry import is_owner

        with patch("aipass.spawn.apps.handlers.registry.find_registry", return_value=registry_no_owner):
            assert is_owner("@devpulse", start_path=tmp_path) is False


class TestEnsureProjectHasOwner:
    """Tests for ensure_project_has_owner() — registry-entry based."""

    def test_sets_owner_on_manager_branch(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 2},
                    "branches": [
                        {
                            "name": "alpha",
                            "path": "src/alpha",
                            "email": "@alpha",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                        },
                        {
                            "name": "devpulse",
                            "path": "src/devpulse",
                            "email": "@devpulse",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-02",
                            "last_active": "2026-01-02",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        alpha_dir = tmp_path / "src" / "alpha" / ".trinity"
        alpha_dir.mkdir(parents=True)
        (alpha_dir / "passport.json").write_text(
            json.dumps(
                {
                    "identity": {"citizen_class": "specialist"},
                    "citizenship": {"registry_id": "abc"},
                }
            ),
            encoding="utf-8",
        )

        dp_dir = tmp_path / "src" / "devpulse" / ".trinity"
        dp_dir.mkdir(parents=True)
        (dp_dir / "passport.json").write_text(
            json.dumps(
                {
                    "identity": {"citizen_class": "manager"},
                    "citizenship": {"registry_id": "abc"},
                }
            ),
            encoding="utf-8",
        )

        result = ensure_project_has_owner(reg)
        assert result is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        devpulse_entry = next(b for b in data["branches"] if b["name"] == "devpulse")
        alpha_entry = next(b for b in data["branches"] if b["name"] == "alpha")
        assert devpulse_entry.get("owner") is True
        assert alpha_entry.get("owner") is None or alpha_entry.get("owner") is not True

    def test_noop_when_owner_already_set(self, registry_with_owner):
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner

        result = ensure_project_has_owner(registry_with_owner)
        assert result is False

    def test_returns_false_for_empty_registry(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 0},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )

        result = ensure_project_has_owner(reg)
        assert result is False


class TestBackfillOwnerAndRegistryId:
    """Tests for backfill_owner_and_registry_id() — mints unique per-citizen UUIDs."""

    def test_mints_unique_uuids_for_entries_missing_registry_id(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import backfill_owner_and_registry_id

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 2},
                    "branches": [
                        {
                            "name": "alpha",
                            "path": "src/alpha",
                            "email": "@alpha",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                        },
                        {
                            "name": "beta",
                            "path": "src/beta",
                            "email": "@beta",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-02",
                            "last_active": "2026-01-02",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = backfill_owner_and_registry_id(reg)
        assert result is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        alpha_entry = next(b for b in data["branches"] if b["name"] == "alpha")
        beta_entry = next(b for b in data["branches"] if b["name"] == "beta")

        assert len(alpha_entry["registry_id"]) == 36
        assert len(beta_entry["registry_id"]) == 36
        assert alpha_entry["registry_id"] != beta_entry["registry_id"]

    def test_remints_duplicate_registry_ids(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import backfill_owner_and_registry_id

        shared_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 2},
                    "branches": [
                        {
                            "name": "alpha",
                            "path": "src/alpha",
                            "email": "@alpha",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                            "registry_id": shared_id,
                        },
                        {
                            "name": "beta",
                            "path": "src/beta",
                            "email": "@beta",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-02",
                            "last_active": "2026-01-02",
                            "registry_id": shared_id,
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = backfill_owner_and_registry_id(reg)
        assert result is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        ids = [b["registry_id"] for b in data["branches"]]
        assert ids[0] != ids[1]
        assert ids[0] != shared_id or ids[1] != shared_id

    def test_noop_when_already_unique(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import backfill_owner_and_registry_id

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 1},
                    "branches": [
                        {
                            "name": "devpulse",
                            "path": "src/devpulse",
                            "email": "@devpulse",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                            "owner": True,
                            "registry_id": "unique-uuid-dp",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = backfill_owner_and_registry_id(reg)
        assert result is False

    def test_seats_owner_when_missing(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import backfill_owner_and_registry_id

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 1},
                    "branches": [
                        {
                            "name": "alpha",
                            "path": "src/alpha",
                            "email": "@alpha",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                            "registry_id": "unique-alpha-id",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = backfill_owner_and_registry_id(reg)
        assert result is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        assert data["branches"][0].get("owner") is True


class TestAddToRegistryMintsPerCitizenUid:
    """Tests for add_to_registry per-citizen UUID minting."""

    def test_always_mints_unique_registry_id(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import add_to_registry

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 0},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )

        add_to_registry(reg, "BRANCH_A", "src/branch_a", "library", "@branch_a", purpose="test")

        data = json.loads(reg.read_text(encoding="utf-8"))
        entry = data["branches"][0]
        assert "registry_id" in entry
        assert len(entry["registry_id"]) == 36  # UUID4 format

    def test_two_entries_get_different_uuids(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import add_to_registry

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 0},
                    "branches": [],
                }
            ),
            encoding="utf-8",
        )

        add_to_registry(reg, "BRANCH_A", "src/branch_a", "library", "@branch_a")
        add_to_registry(reg, "BRANCH_B", "src/branch_b", "library", "@branch_b")

        data = json.loads(reg.read_text(encoding="utf-8"))
        ids = [b["registry_id"] for b in data["branches"]]
        assert ids[0] != ids[1]


class TestEnsureProjectHasOwnerFirstAgentFallback:
    """Tests for ensure_project_has_owner first-agent fallback."""

    def test_falls_back_to_first_agent_when_no_manager(self, tmp_path):
        from aipass.spawn.apps.handlers.registry import ensure_project_has_owner

        reg = tmp_path / "TEST_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-07-10", "total_branches": 2},
                    "branches": [
                        {
                            "name": "beta",
                            "path": "src/beta",
                            "email": "@beta",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-02-01",
                            "last_active": "2026-02-01",
                        },
                        {
                            "name": "alpha",
                            "path": "src/alpha",
                            "email": "@alpha",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-01-01",
                            "last_active": "2026-01-01",
                        },
                    ],
                }
            ),
            encoding="utf-8",
        )

        result = ensure_project_has_owner(reg)
        assert result is True

        data = json.loads(reg.read_text(encoding="utf-8"))
        alpha = next(b for b in data["branches"] if b["name"] == "alpha")
        beta = next(b for b in data["branches"] if b["name"] == "beta")
        assert alpha.get("owner") is True
        assert beta.get("owner") is not True


class TestIsProtectedLayers:
    """is_protected() protection layers (APLAN-0007 audit).

    Layer 2 (``owner: true``) is unreachable in the live fleet: devpulse is the
    only entry carrying the flag and it short-circuits on the layer-1 floor, so
    the branch can only be exercised against a synthetic registry.
    """

    @staticmethod
    def _registry(tmp_path, name, owner):
        reg = tmp_path / "AIPASS_REGISTRY.json"
        reg.write_text(
            json.dumps(
                {
                    "metadata": {"version": "1.0.0", "last_updated": "2026-08-13", "total_branches": 1},
                    "branches": [
                        {
                            "name": name,
                            "path": f"src/{name}",
                            "email": f"@{name}",
                            "status": "active",
                            "profile": "library",
                            "description": "test",
                            "created": "2026-08-13",
                            "last_active": "2026-08-13",
                            "owner": owner,
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        return reg

    def test_floor_branches_are_protected(self):
        """Layer 1: the hardcoded floor refuses without touching the registry."""
        from aipass.spawn.apps.handlers.registry import is_protected

        for name in ("spawn", "devpulse", "drone"):
            protected, reason = is_protected(name)
            assert protected is True
            assert "infrastructure" in reason

    def test_registry_owner_flag_protects(self, tmp_path):
        """Layer 2: a non-floor branch with owner:true is refused as registry owner."""
        from aipass.spawn.apps.handlers.registry import is_protected

        reg = self._registry(tmp_path, "baud", owner=True)
        protected, reason = is_protected("baud", branch_dir=tmp_path / "nonexistent", registry_path=reg)
        assert protected is True
        assert reason == "registry owner"

    def test_active_passport_protects(self, tmp_path):
        """Layer 3: no owner flag, but a registered passport still refuses."""
        from aipass.spawn.apps.handlers.registry import is_protected

        reg = self._registry(tmp_path, "baud", owner=False)
        branch = tmp_path / "baud"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"citizenship": {"registered": True}}), encoding="utf-8"
        )
        protected, reason = is_protected("baud", branch_dir=branch, registry_path=reg)
        assert protected is True
        assert reason == "active citizen"

    def test_unregistered_branch_is_not_protected(self, tmp_path):
        """All three layers miss: an unregistered passport is deletable."""
        from aipass.spawn.apps.handlers.registry import is_protected

        reg = self._registry(tmp_path, "baud", owner=False)
        branch = tmp_path / "baud"
        (branch / ".trinity").mkdir(parents=True)
        (branch / ".trinity" / "passport.json").write_text(
            json.dumps({"citizenship": {"registered": False}}), encoding="utf-8"
        )
        protected, reason = is_protected("baud", branch_dir=branch, registry_path=reg)
        assert protected is False
        assert reason == ""
