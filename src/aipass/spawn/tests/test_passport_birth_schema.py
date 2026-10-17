# =================== META ====================
# Name: test_passport_birth_schema.py
# Description: The passport 2.0 contract AT BIRTH — block order, key order, new fields
# Version: 1.0.2
# Created: 2026-08-28
# Modified: 2026-10-17
# =============================================

"""Tests for apps/modules/core.py — the passport 2.0 contract at birth."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that core.py, placeholders.py, and class_registry.py parse and import cleanly
# seedgo: no-test-needed(documentation) — that the public functions in those modules carry docstrings

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.spawn.apps.handlers.placeholders as placeholders
from aipass.spawn.apps.handlers.class_registry import get_template_dir
from aipass.spawn.apps.modules.core import spawn_agent

# Order is contract and is decided only at birth (`spawn update` never reorders). The
# expectation is written out literally, not derived from the template, and the mint runs
# end-to-end because render, --traits write and JSON round-trip could each reorder keys.
EXPECTED_BLOCK_ORDER = ["document_metadata", "branch_info", "citizenship", "identity"]

EXPECTED_KEY_ORDER = {
    "document_metadata": [
        "document_type",
        "document_name",
        "version",
        "schema_version",
        "created",
        "last_updated",
        "managed_by",
        "tags",
    ],
    "branch_info": [
        "branch_name",
        "alias",
        "path",
        "module",
        "email",
        "created",
        "git_branch",
    ],
    "citizenship": [
        "registered",
        "residency",
        "registry_id",
        "citizen_id",
        "registry_path",
        "communications",
        "memory",
    ],
    "identity": [
        "citizen_class",
        "role",
        "purpose",
        "what_i_do",
        "what_i_dont_do",
        "traits",
        "principles",
    ],
}

# Removed from 2.0; must not come back at birth by any route.
DROPPED_FIELDS = [
    ("citizenship", "owner"),
    ("document_metadata", "note"),
]


def _fresh_registry(path: Path) -> Path:
    """A registry file with no citizens in it — so the newborn is citizen #1."""
    path.write_text('{"metadata":{"version":"1.0.0","total_branches":0},"branches":[]}', encoding="utf-8")
    return path


def _mint(tmp_path: Path, name: str = "newborn", **kwargs) -> dict:
    """Mint one citizen into tmp_path and return its passport, keys in file order."""
    registry = _fresh_registry(tmp_path / "TEST_REGISTRY.json")
    result = spawn_agent(str(tmp_path / name), registry_path=str(registry), **kwargs)
    assert result["success"] is True, result.get("error")
    return json.loads((tmp_path / name / ".trinity" / "passport.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_aipass_home(tmp_path):
    """Pretend tmp_path is the AIPass installation root.

    Relocates the root so observing "core" residency never mints into the live tree."""
    home = tmp_path / "AIPassHome"
    home.mkdir()
    with patch.object(placeholders, "_aipass_home", return_value=home):
        yield home


class TestNewbornPassportOrder:
    """R1: the 2.0 layout, checked on the file a citizen is actually born with."""

    def test_block_order(self, tmp_path):
        passport = _mint(tmp_path)
        assert list(passport.keys()) == EXPECTED_BLOCK_ORDER

    @pytest.mark.parametrize("block", EXPECTED_BLOCK_ORDER)
    def test_key_order_within_block(self, tmp_path, block):
        passport = _mint(tmp_path)
        assert list(passport[block].keys()) == EXPECTED_KEY_ORDER[block]

    def test_principles_live_inside_identity_not_at_top_level(self, tmp_path):
        """R1's structural move — the one 1.x readers have to be taught about."""
        passport = _mint(tmp_path)

        assert "principles" not in passport
        assert isinstance(passport["identity"]["principles"], list)
        assert passport["identity"]["principles"], "a newborn was given an empty principles list"

    def test_order_survives_the_traits_post_render_write(self, tmp_path):
        """``--traits`` rewrites the passport AFTER the render — a read/modify/write
        that reorders keys would land the drift on every citizen born with traits."""
        passport = _mint(tmp_path, name="traited", traits="curious, terse")

        assert list(passport.keys()) == EXPECTED_BLOCK_ORDER
        assert list(passport["identity"].keys()) == EXPECTED_KEY_ORDER["identity"]
        assert passport["identity"]["traits"] == ["curious, terse"]

    def test_no_extra_or_missing_keys_anywhere(self, tmp_path):
        """The 2.0 field set is CLOSED — order alone would not catch an addition."""
        passport = _mint(tmp_path)

        assert set(passport) == set(EXPECTED_BLOCK_ORDER)
        for block, keys in EXPECTED_KEY_ORDER.items():
            assert set(passport[block]) == set(keys), f"{block} field set drifted"

    def test_the_shipped_template_declares_the_same_order(self, tmp_path):
        """Mint and template must agree — if they ever diverge, say which one moved."""
        template = json.loads((get_template_dir() / ".trinity" / "passport.json").read_text(encoding="utf-8"))

        assert list(template.keys()) == EXPECTED_BLOCK_ORDER
        for block, keys in EXPECTED_KEY_ORDER.items():
            assert list(template[block].keys()) == keys, f"template {block} order drifted from the mint's"


class TestNewbornPassportFields:
    """The rest of the 2.0 field contract, at birth."""

    def test_schema_version_is_the_migration_marker(self, tmp_path):
        """version and schema_version are both 2.0.0; schema_version is the marker migration reads."""
        meta = _mint(tmp_path)["document_metadata"]

        assert meta["schema_version"] == "2.0.0"
        assert meta["version"] == "2.0.0"

    @pytest.mark.parametrize("block,field", DROPPED_FIELDS)
    def test_dropped_fields_are_absent(self, tmp_path, block, field):
        """citizenship.owner and document_metadata.note are gone.

        The registry entry's sealed owner flag is the only place that answers ownership."""
        assert field not in _mint(tmp_path)[block]

    def test_top_level_family_is_gone(self, tmp_path):
        """The third drop, checked separately because it was a whole block."""
        assert "family" not in _mint(tmp_path)

    def test_git_branch_is_the_literal_dev(self, tmp_path):
        """No more work/{{branchname}} fossils — one rule, one branch name."""
        assert _mint(tmp_path)["branch_info"]["git_branch"] == "dev"

    def test_names_render_lowercase(self, tmp_path):
        """Casing: branch_name / managed_by / document_name are lowercase now.

        The UPPER form survives only as the registry key; the address is @name."""
        passport = _mint(tmp_path, name="mixed_case_agent")

        assert passport["branch_info"]["branch_name"] == "mixed_case_agent"
        assert passport["document_metadata"]["managed_by"] == "mixed_case_agent"
        assert passport["document_metadata"]["document_name"] == "mixed_case_agent.PASSPORT"

    def test_list_fields_are_lists(self, tmp_path):
        """traits / what_i_do / what_i_dont_do are LISTS, not strings."""
        identity = _mint(tmp_path)["identity"]

        for field in ("traits", "what_i_do", "what_i_dont_do"):
            assert identity[field] == [], f"{field} was born as {type(identity[field]).__name__}"

    def test_no_placeholder_survives_the_render(self, tmp_path):
        """A passport is the one file where an unrendered {{X}} is a broken identity."""
        raw = json.dumps(_mint(tmp_path))
        assert "{{" not in raw


class TestNewbornPathAndResidency:
    """{{CWD}} → {{PATH}} (R1) and the new citizenship.residency (R5)."""

    def test_path_is_relative_and_never_leaks_a_home_directory(self, tmp_path):
        """{{CWD}} rendered an ABSOLUTE path into a tracked, public, committed file.

        That publishes the author's home and is wrong on every other checkout."""
        path = _mint(tmp_path)["branch_info"]["path"]

        assert not Path(path).is_absolute()
        assert not path.startswith(("/", "~"))
        assert "/home/" not in path
        assert str(tmp_path) not in path

    def test_residency_core_for_a_citizen_under_src_aipass(self, tmp_path, fake_aipass_home):
        """'core' — AIPass's own src/aipass/ home. Path anchors on the repo root."""
        home = fake_aipass_home
        (home / "src" / "aipass").mkdir(parents=True)

        passport = _mint(home / "src" / "aipass", name="core_citizen")

        assert passport["citizenship"]["residency"] == "core"
        assert passport["branch_info"]["path"] == "src/aipass/core_citizen"

    def test_residency_resident_for_a_citizen_under_projects(self, tmp_path, fake_aipass_home):
        """'resident' — a project hosted in this repo; path anchors on the project's root.

        So the passport reads the same if the project ever moves out on its own."""
        home = fake_aipass_home
        project_src = home / "projects" / "demo" / "src" / "demo"
        project_src.mkdir(parents=True)

        passport = _mint(project_src, name="resident_citizen")

        assert passport["citizenship"]["residency"] == "resident"
        assert passport["branch_info"]["path"] == "src/demo/resident_citizen"

    def test_residency_external_for_a_citizen_outside_aipass(self, tmp_path, fake_aipass_home):
        """'external' — a standalone project on disk, nothing to do with AIPass."""
        outside = tmp_path / "somewhere_else"
        outside.mkdir()

        passport = _mint(outside, name="external_citizen")

        assert passport["citizenship"]["residency"] == "external"

    def test_residency_is_one_of_the_three_declared_values(self, tmp_path):
        """The field is a closed enum, not free text."""
        assert _mint(tmp_path)["citizenship"]["residency"] in {"core", "resident", "external"}
