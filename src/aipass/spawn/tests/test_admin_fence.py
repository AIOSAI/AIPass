# =================== AIPass ====================
# Name: test_admin_fence.py
# Description: Admin grant ceremony + permanent admin-class refusal (FPLAN-0401 P2)
# Version: 1.0.0
# Created: 2026-08-12
# Modified: 2026-08-12
# =============================================

"""Tests for the admin privilege fence (FPLAN-0401 Phase 2, DPLAN-0288).

Two halves:

  Part A — ``ensure_admin()`` / ``drone @spawn grant-admin`` write
           ``"admin": true`` onto the devpulse entry of the root registry.
           The branch name is a constant, not a caller choice: every other
           name is refused by name, and the flag alone grants nothing (the
           lane needs all five contract legs).

  Part B — "admin" is never a citizen class and never a template. create,
           update and sync each refuse it loudly and permanently.
"""

import json
from unittest.mock import patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _entry(name, **extra):
    """Build a registry branch entry shaped like a real one."""
    lower = name.lower()
    entry = {
        "name": name,
        "path": f"src/aipass/{lower}",
        "profile": "AIPass Framework",
        "description": f"{name} branch",
        "email": f"@{lower}",
        "status": "active",
        "created": "2026-03-05",
        "last_active": "2026-03-05",
        "registry_id": f"id-{lower}",
    }
    entry.update(extra)
    return entry


def _write_registry(tmp_path, branches):
    """Write a minimal AIPASS_REGISTRY.json and return its path."""
    registry = tmp_path / "AIPASS_REGISTRY.json"
    registry.write_text(
        json.dumps(
            {
                "metadata": {
                    "version": "1.0.0",
                    "last_updated": "2026-08-12",
                    "total_branches": len(branches),
                    "id": "project-credential",
                },
                "branches": branches,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return registry


def _read_entry(registry_path, name) -> dict:
    """Read one entry back off disk (case-insensitive). Raises if absent."""
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    for branch in data.get("branches", []):
        if branch.get("name", "").lower() == name.lower():
            return branch
    raise AssertionError(f"No {name} entry in {registry_path}")


# ---------------------------------------------------------------------------
# Part A — ensure_admin()
# ---------------------------------------------------------------------------


class TestEnsureAdmin:
    """The sanctioned writer for the registry admin flag."""

    def test_grants_admin_on_devpulse_entry(self, tmp_path):
        """devpulse entry gains admin:true, persisted to disk."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True), _entry("SPAWN")])

        status, reason = ensure_admin(registry)

        assert status == "granted"
        assert "devpulse" in reason.lower()
        assert _read_entry(registry, "devpulse")["admin"] is True

    def test_is_idempotent(self, tmp_path):
        """Second call reports already-granted instead of rewriting."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True)])
        ensure_admin(registry)

        status, reason = ensure_admin(registry)

        assert status == "already"
        assert "already" in reason.lower()
        assert _read_entry(registry, "devpulse")["admin"] is True

    @pytest.mark.parametrize("name", ["spawn", "SPAWN", "baud", "drone", "devpulse_evil", ""])
    def test_refuses_every_non_devpulse_name(self, tmp_path, name):
        """The name is a constant — no other branch can ever be granted admin."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True), _entry("SPAWN")])

        status, reason = ensure_admin(registry, name)

        assert status == "refused"
        assert "devpulse" in reason.lower()
        assert "admin" not in _read_entry(registry, "spawn")
        assert "admin" not in _read_entry(registry, "devpulse")

    def test_accepts_uppercase_devpulse(self, tmp_path):
        """Registry names are uppercase — the fence normalizes, it doesn't trip."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True)])

        status, _ = ensure_admin(registry, "DEVPULSE")

        assert status == "granted"

    def test_refuses_when_no_devpulse_entry(self, tmp_path):
        """No devpulse seat in this registry — fail closed, write nothing."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("BAUD", owner=True)])
        before = registry.read_text(encoding="utf-8")

        status, reason = ensure_admin(registry)

        assert status == "refused"
        assert "no devpulse entry" in reason.lower()
        assert registry.read_text(encoding="utf-8") == before

    def test_preserves_existing_entry_keys(self, tmp_path):
        """admin is a sibling boolean — owner and the rest survive untouched."""
        from aipass.spawn.apps.handlers.registry import ensure_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True, custom_key="keep-me")])

        ensure_admin(registry)

        devpulse = _read_entry(registry, "devpulse")
        assert devpulse["owner"] is True
        assert devpulse["custom_key"] == "keep-me"
        assert devpulse["registry_id"] == "id-devpulse"

    def test_admin_branch_constant_is_devpulse(self):
        """The one seat, pinned as a constant."""
        from aipass.spawn.apps.handlers.registry import ADMIN_BRANCH

        assert ADMIN_BRANCH == "devpulse"


class TestGrantAdminCli:
    """drone @spawn grant-admin — Patrick's one-time ceremony command."""

    def test_grants_via_cli(self, tmp_path):
        """--registry points at the root registry; exit 0 and flag written."""
        from aipass.spawn.apps.modules.grant_admin import handle_grant_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True)])

        code = handle_grant_admin(["--registry", str(registry)])

        assert code == 0
        assert _read_entry(registry, "devpulse")["admin"] is True

    def test_idempotent_via_cli(self, tmp_path):
        """Re-running the ceremony is safe and still exits 0."""
        from aipass.spawn.apps.modules.grant_admin import handle_grant_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True)])
        handle_grant_admin(["--registry", str(registry)])

        assert handle_grant_admin(["--registry", str(registry)]) == 0

    def test_refuses_branch_argument(self, tmp_path):
        """No target argument exists — admin is devpulse-only by construction."""
        from aipass.spawn.apps.modules.grant_admin import handle_grant_admin

        registry = _write_registry(tmp_path, [_entry("DEVPULSE", owner=True), _entry("SPAWN")])

        with patch("aipass.spawn.apps.modules.grant_admin.error") as mock_error:
            code = handle_grant_admin(["@spawn", "--registry", str(registry)])

        assert code == 1
        assert "admin" in str(mock_error.call_args).lower()
        assert "admin" not in _read_entry(registry, "devpulse")
        assert "admin" not in _read_entry(registry, "spawn")

    def test_exits_nonzero_when_registry_has_no_devpulse(self, tmp_path):
        """Refusals are loud — the ceremony reports failure."""
        from aipass.spawn.apps.modules.grant_admin import handle_grant_admin

        registry = _write_registry(tmp_path, [_entry("BAUD", owner=True)])

        assert handle_grant_admin(["--registry", str(registry)]) == 1

    def test_entry_point_routes_grant_admin(self):
        """main() routes the command to the module."""
        from aipass.spawn.apps.spawn import main

        with patch("aipass.spawn.apps.spawn.sys") as mock_sys:
            mock_sys.argv = ["spawn", "grant-admin", "--help"]
            with patch("aipass.spawn.apps.modules.grant_admin.handle_grant_admin", return_value=0) as mock_handler:
                result = main()

        assert result == 0
        mock_handler.assert_called_once()


# ---------------------------------------------------------------------------
# Part B — "admin" is never a class, never a template
# ---------------------------------------------------------------------------


class TestAdminClassRefusal:
    """spawn refuses to mint, update or sync anything as class 'admin'."""

    def test_admin_is_not_template_selectable(self):
        """Pin: admin is absent from every class list, forever."""
        from aipass.spawn.apps.handlers.class_registry import (
            CITIZEN_CLASSES,
            IDENTITY_CITIZEN_CLASSES,
            get_available_classes,
            validate_class,
        )

        assert validate_class("admin") is False
        assert "admin" not in CITIZEN_CLASSES
        assert "admin" not in IDENTITY_CITIZEN_CLASSES
        assert "admin" not in get_available_classes()

    def test_refuse_forbidden_class_names_admin(self):
        """The refusal helper answers for admin and stays silent for real classes."""
        from aipass.spawn.apps.handlers.class_registry import refuse_forbidden_class

        refusal = refuse_forbidden_class("admin")
        assert refusal
        assert "admin" in refusal.lower()
        assert "devpulse" in refusal.lower()
        assert refuse_forbidden_class("ADMIN")
        assert refuse_forbidden_class("specialist") == ""
        assert refuse_forbidden_class("manager") == ""
        assert refuse_forbidden_class("") == ""
        # A RETIRED name is not a FORBIDDEN one — this helper stays silent for it
        # so admin's permanent refusal never gets diluted into a rename notice.
        assert refuse_forbidden_class("aipass_framework") == ""

    def test_get_template_dir_refuses_admin(self):
        """No template lookup ever resolves admin."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        with pytest.raises(ValueError) as exc:
            get_template_dir("admin")

        assert "devpulse" in str(exc.value).lower()

    def test_resolve_template_class_refuses_admin_passport(self):
        """A passport claiming admin is refused, not resolved to a template."""
        from aipass.spawn.apps.handlers.class_registry import resolve_template_class

        with pytest.raises(ValueError) as exc:
            resolve_template_class({"citizen_class": "admin", "role": "orchestration_hub"})

        assert "devpulse" in str(exc.value).lower()

    def test_spawn_agent_refuses_admin_class(self, tmp_path):
        """The Python API refuses the class and creates nothing."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "would_be_admin"

        result = _spawn_agent(str(target), citizen_class="admin")

        assert result["success"] is False
        assert "devpulse" in result["error"].lower()
        assert not target.exists()

    def test_spawn_agent_refuses_admin_template_dir(self, tmp_path):
        """--template admin can't sneak past as a raw directory value."""
        from aipass.spawn.apps.modules.core import _spawn_agent

        target = tmp_path / "would_be_admin"

        result = _spawn_agent(str(target), template_dir="admin")

        assert result["success"] is False
        assert "devpulse" in result["error"].lower()
        assert not target.exists()

    def test_handle_create_refuses_admin_as_class_argument(self, tmp_path):
        """`spawn create admin <path>` is a named refusal, not a parse error."""
        from aipass.spawn.apps.spawn import handle_create

        target = tmp_path / "new_agent"

        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            code = handle_create(["admin", str(target)])

        assert code == 1
        assert "devpulse" in str(mock_error.call_args).lower()
        assert not target.exists()

    def test_handle_create_refuses_admin_template_flag(self, tmp_path):
        """`--template admin` is refused by name before any filesystem work."""
        from aipass.spawn.apps.spawn import handle_create

        target = tmp_path / "new_agent"

        with patch("aipass.spawn.apps.spawn.error") as mock_error:
            code = handle_create([str(target), "--template", "admin"])

        assert code == 1
        assert "devpulse" in str(mock_error.call_args).lower()
        assert not target.exists()

    def test_handle_update_refuses_admin_class(self):
        """`update admin --all` never reaches the update engine."""
        from aipass.spawn.apps.modules.update import handle_update

        with patch("aipass.spawn.apps.modules.update.update_all") as mock_all:
            with patch("aipass.spawn.apps.modules.update.error") as mock_error:
                code = handle_update(["admin", "--all", "--apply"])

        assert code == 1
        mock_all.assert_not_called()
        assert "devpulse" in str(mock_error.call_args).lower()

    def test_sync_template_class_refuses_admin(self):
        """The sync rebuild path refuses admin instead of silently scaffolding."""
        from aipass.spawn.apps.handlers.sync_registry_ops import resolve_sync_template_class

        with pytest.raises(ValueError) as exc:
            resolve_sync_template_class("admin", "SOMEBRANCH")

        assert "devpulse" in str(exc.value).lower()
        assert "SOMEBRANCH" in str(exc.value)

    def test_sync_template_class_refuses_unknown_instead_of_falling_back(self):
        """CONTRACT INVERTED (DPLAN-0319): the unknown-class fallback was REMOVED.

        This used to pin ``resolve_sync_template_class("legacy_builder", ...)``
        guessing the ``aipass_framework`` template. Two things were wrong with the
        guess: it wrote .branch_meta.json against a template the passport never
        claimed (the branch then reads as "repaired" while tracking the wrong
        contract), and the value it guessed is now itself a dead name. House law
        is fail-loud, so the guess is gone and the refusal must name the branch
        and the class it could not resolve — that is what the caller skips on.
        """
        from aipass.spawn.apps.handlers.sync_registry_ops import resolve_sync_template_class

        with pytest.raises(ValueError) as exc:
            resolve_sync_template_class("legacy_builder", "SOMEBRANCH")

        message = str(exc.value)
        assert "SOMEBRANCH" in message
        assert "legacy_builder" in message
        assert "aipass_framework" not in message, f"the removed fallback is being named as a target: {message}"

    def test_sync_template_class_refuses_retired_names_by_name(self):
        """A retired class is refused with the rename notice, never remapped."""
        from aipass.spawn.apps.handlers.sync_registry_ops import resolve_sync_template_class

        for retired, replacement in (("aipass_framework", "specialist"), ("project_agent", "manager")):
            with pytest.raises(ValueError) as exc:
                resolve_sync_template_class(retired, "SOMEBRANCH")

            message = str(exc.value)
            assert "SOMEBRANCH" in message
            assert "retired" in message.lower()
            assert replacement in message

    def test_sync_template_class_resolves_both_live_classes(self):
        """The fence must not have taken the real classes down with the fallback."""
        from aipass.spawn.apps.handlers.sync_registry_ops import resolve_sync_template_class

        for live in ("manager", "specialist"):
            assert resolve_sync_template_class(live, "SOMEBRANCH").name == "citizen"
