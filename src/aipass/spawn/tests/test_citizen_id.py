# =================== AIPass ====================
# Name: test_citizen_id.py
# Description: citizenship.citizen_id — the per-citizen UID stamped at birth
# Version: 1.0.1
# Created: 2026-08-24
# Modified: 2026-10-17
# =============================================

"""Tests for apps/handlers/registry.py and apps/handlers/placeholders.py — the citizen_id contract."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that registry.py, placeholders.py, and class_registry.py parse and import cleanly
# seedgo: no-test-needed(documentation) — that the public functions in those modules carry docstrings

import json
import uuid

from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir
from aipass.spawn.apps.handlers.placeholders import build_replacements_dict
from aipass.spawn.apps.handlers.registry import add_to_registry

# registry_id names the registry (shared); citizen_id is the citizen's own, kept twice
# (passport and registry entry) and minted once so the copies agree.


def _fresh_registry(path):
    """Write a minimal registry the add path will accept."""
    path.write_text(
        json.dumps({"metadata": {"id": str(uuid.uuid4()), "version": "1.0.0", "total_branches": 0}, "branches": []}),
        encoding="utf-8",
    )
    return path


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


def test_every_class_declares_citizen_id():
    """Every class must stamp the field, or that class's births render no number.

    Loops over classes, not the one template dir, so a class that stops resolving to it fails."""
    classes = get_available_classes()
    assert len(classes) == 2, f"the class registry offers {classes} - the loop below would check nothing"
    for citizen_class in classes:
        passport = get_template_dir(citizen_class) / ".trinity" / "passport.json"
        citizenship = json.loads(passport.read_text(encoding="utf-8"))["citizenship"]

        assert citizenship["citizen_id"] == "{{CITIZEN_ID}}", f"{citizen_class} does not stamp citizen_id"
        assert citizenship["registry_id"] == "{{REGISTRY_ID}}", f"{citizen_class} lost its registry_id"
