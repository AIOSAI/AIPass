# =================== AIPass ====================
# Name: test_registry_credential.py
# Description: metadata.id — the project credential a new registry is born with
# Version: 1.0.0
# Created: 2026-08-24
# Modified: 2026-08-24
# =============================================

"""Tests for the registry credential (metadata.id).

A project registry's ``metadata.id`` is the branch-registry lock: every passport
in that project carries it as ``citizenship.registry_id``, and BAUD renders it
as "Branch reg no.". A registry born WITHOUT one is not merely incomplete — its
first citizen's passport falls back to whatever registry discovery finds next,
which in practice is AIPass's own id, so a brand-new project's agent displays a
number belonging to a project it has never been part of.

The two default-schema paths in load_registry are deliberately NOT symmetric,
and these tests pin that asymmetry:

  - registry file ABSENT  -> a genuinely new project -> mint a credential.
  - registry file PRESENT but unreadable -> the project ALREADY HAS a
    credential we simply cannot read. Minting a fresh one here would
    re-credential a live project and orphan every existing passport, so this
    path must NOT invent one.
"""

import json
import uuid

import pytest

from aipass.spawn.apps.handlers.registry import load_registry


# =============================================================================
# ABSENT REGISTRY — a new project earns a credential
# =============================================================================


def test_missing_registry_is_born_with_a_credential(tmp_path):
    """A registry that does not exist yet gets a real minted id."""
    result = load_registry(tmp_path / "NEW_REGISTRY.json")

    assert uuid.UUID(result["metadata"]["id"])  # parses => real UUID, not "" or None


def test_minted_credential_is_unique_per_registry(tmp_path):
    """Two new projects must not share a credential — it is their lock."""
    first = load_registry(tmp_path / "ONE_REGISTRY.json")["metadata"]["id"]
    second = load_registry(tmp_path / "TWO_REGISTRY.json")["metadata"]["id"]

    assert first != second


def test_minted_default_keeps_the_rest_of_the_schema(tmp_path):
    """Adding the credential must not disturb the fields callers already read."""
    result = load_registry(tmp_path / "NEW_REGISTRY.json")

    assert result["metadata"]["version"] == "1.0.0"
    assert result["metadata"]["total_branches"] == 0
    assert result["branches"] == []
    assert "last_updated" in result["metadata"]


def test_new_project_credential_is_not_aipass_own_id(tmp_path):
    """The regression this exists to prevent: inheriting AIPass's credential."""
    result = load_registry(tmp_path / "NEW_REGISTRY.json")

    assert result["metadata"]["id"] != "7087bb93-570f-4b9a-b035-4fd7f570200e"


# =============================================================================
# EXISTING REGISTRY — never re-credential what we merely failed to read
# =============================================================================


def test_real_registry_credential_is_never_replaced(tmp_path):
    """A readable registry hands back its OWN id, untouched."""
    path = tmp_path / "REAL_REGISTRY.json"
    path.write_text(
        json.dumps({"metadata": {"id": "keep-me", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )

    assert load_registry(path)["metadata"]["id"] == "keep-me"


def test_unreadable_registry_does_not_mint_a_replacement_credential(tmp_path):
    """An unreadable file is not a new project — inventing an id here would
    silently re-credential a live project and orphan every passport in it."""
    corrupt = tmp_path / "CORRUPT_REGISTRY.json"
    corrupt.write_text("{not valid json", encoding="utf-8")

    result = load_registry(corrupt)

    assert result["metadata"].get("id") in (None, ""), (
        "load_registry minted a fresh credential for a registry that already exists — "
        "saving that would replace a live project's id"
    )


@pytest.mark.parametrize("content", ["", "   ", "{malformed"])
def test_unreadable_variants_all_withhold_a_credential(tmp_path, content):
    """Empty and malformed both mean 'cannot read', never 'does not exist'."""
    path = tmp_path / f"X{len(content)}_REGISTRY.json"
    path.write_text(content, encoding="utf-8")

    assert load_registry(path)["metadata"].get("id") in (None, "")


# =============================================================================
# CALLER-SUPPLIED CREDENTIAL — one project, one id
# =============================================================================


def test_new_registry_adopts_the_callers_credential(tmp_path):
    """The credential already stamped into the passport is the one that lands.

    Regression guard for a double mint: load_registry mints an id for a missing
    file, so an "is the id already set?" check would see that fresh mint and
    silently discard the caller's — leaving the passport claiming one credential
    and the registry file carrying a different one.
    """
    from aipass.spawn.apps.handlers.registry import add_to_registry

    reg = tmp_path / "NEW_REGISTRY.json"
    branch = tmp_path / "widget"
    branch.mkdir()
    stamped = str(uuid.uuid4())

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=stamped)

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == stamped


def test_existing_registry_credential_survives_a_new_citizen(tmp_path):
    """Registering into a live project never re-credentials it."""
    from aipass.spawn.apps.handlers.registry import add_to_registry

    reg = tmp_path / "REAL_REGISTRY.json"
    reg.write_text(
        json.dumps({"metadata": {"id": "the-real-lock", "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    branch = tmp_path / "widget"
    branch.mkdir()

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", credential=str(uuid.uuid4()))

    assert json.loads(reg.read_text(encoding="utf-8"))["metadata"]["id"] == "the-real-lock"
