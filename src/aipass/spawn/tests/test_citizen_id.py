# =================== AIPass ====================
# Name: test_citizen_id.py
# Description: citizenship.citizen_id — the per-citizen UID stamped at birth
# Version: 1.0.0
# Created: 2026-08-24
# Modified: 2026-08-24
# =============================================

"""Tests for the citizen_id contract (Patrick's ruling, 2026-08-24).

Two ids live near each other and mean different things:
  - ``citizenship.registry_id`` — the id of the REGISTRY holding the citizen.
    Shared by every citizen in a project. Rendered as "Branch reg no.".
  - ``citizenship.citizen_id`` — the citizen's OWN unique id, the same value
    the registry keeps in its ``branches[]`` entry. Rendered as "Passport no.".

The load-bearing property is that those two copies of the citizen's own id are
minted ONCE and therefore always agree. The mint used to happen inside
add_to_registry, which runs after the passport is written — so this file pins
the ordering, not just the presence of a field.
"""

import json
import uuid

from aipass.spawn.apps.handlers.placeholders import build_replacements_dict
from aipass.spawn.apps.handlers.registry import add_to_registry


def _fresh_registry(path):
    """Write a minimal registry the add path will accept."""
    path.write_text(
        json.dumps({"metadata": {"id": str(uuid.uuid4()), "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    return path


# =============================================================================
# PLACEHOLDER SURFACE
# =============================================================================


def test_citizen_id_override_reaches_the_placeholder_map(tmp_path):
    """A supplied citizen_id is offered to the template as {{CITIZEN_ID}}."""
    given = str(uuid.uuid4())

    result = build_replacements_dict(tmp_path / "widget", "widget", citizen_id=given)

    assert result["CITIZEN_ID"] == given


def test_citizen_id_defaults_to_empty_not_missing(tmp_path):
    """The key always exists — a missing key would leave {{CITIZEN_ID}} unrendered."""
    result = build_replacements_dict(tmp_path / "widget", "widget")

    assert result["CITIZEN_ID"] == ""


def test_citizen_id_is_not_the_registry_id(tmp_path):
    """The two ids are distinct facts and must not be aliased to one value."""
    result = build_replacements_dict(
        tmp_path / "widget", "widget", citizen_id="aaaa-citizen", registry_id="bbbb-registry"
    )

    assert result["CITIZEN_ID"] == "aaaa-citizen"
    assert result["REGISTRY_ID"] == "bbbb-registry"


# =============================================================================
# REGISTRY ENTRY
# =============================================================================


def test_add_to_registry_uses_the_supplied_citizen_id(tmp_path):
    """A caller that already stamped the passport hands the SAME id here."""
    reg = _fresh_registry(tmp_path / "AIPASS_REGISTRY.json")
    given = str(uuid.uuid4())
    branch = tmp_path / "widget"
    branch.mkdir()

    assert add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", citizen_id=given) is True

    entry = json.loads(reg.read_text(encoding="utf-8"))["branches"][0]
    assert entry["registry_id"] == given


def test_add_to_registry_mints_when_no_citizen_id_supplied(tmp_path):
    """Adoption has no passport id to match, so the entry still gets a real UUID."""
    reg = _fresh_registry(tmp_path / "AIPASS_REGISTRY.json")
    branch = tmp_path / "widget"
    branch.mkdir()

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget")

    entry = json.loads(reg.read_text(encoding="utf-8"))["branches"][0]
    assert uuid.UUID(entry["registry_id"])  # parses => a real UUID, not "" or None


def test_supplied_citizen_id_is_not_overwritten_by_a_fresh_mint(tmp_path):
    """Regression guard: the mint must not run when the caller supplied a value."""
    reg = _fresh_registry(tmp_path / "AIPASS_REGISTRY.json")
    given = "11111111-2222-3333-4444-555555555555"
    branch = tmp_path / "widget"
    branch.mkdir()

    add_to_registry(reg, "WIDGET", str(branch), "p", "@widget", citizen_id=given)

    entry = json.loads(reg.read_text(encoding="utf-8"))["branches"][0]
    assert entry["registry_id"] == given


# =============================================================================
# TEMPLATE CONTRACT
# =============================================================================


def test_both_templates_declare_citizen_id():
    """Every class must stamp the field, or that class's births render no number."""
    from pathlib import Path

    templates = Path(__file__).resolve().parents[1] / "templates"
    for citizen_class in ("aipass_framework", "project_agent"):
        passport = templates / citizen_class / ".trinity" / "passport.json"
        citizenship = json.loads(passport.read_text(encoding="utf-8"))["citizenship"]

        assert citizenship["citizen_id"] == "{{CITIZEN_ID}}", f"{citizen_class} does not stamp citizen_id"
        assert citizenship["registry_id"] == "{{REGISTRY_ID}}", f"{citizen_class} lost its registry_id"
