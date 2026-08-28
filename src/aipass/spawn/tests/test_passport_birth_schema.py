# =================== META ====================
# Name: test_passport_birth_schema.py
# Description: The passport 2.0 contract AT BIRTH — block order, key order, new fields
# Version: 1.0.0
# Created: 2026-08-28
# Modified: 2026-08-28
# =============================================

"""What a freshly minted passport must look like — DPLAN-0319 (Passport 2.0).

ORDER IS CONTRACT AND NOTHING PINNED IT
---------------------------------------
R1 is a ruling about LAYOUT: document_metadata → branch_info → citizenship →
identity, with ``principles`` moved inside identity. A passport is a document a
human reads and a dozen branches parse; the order it is written in is the order
it is read in, and `spawn update` explicitly refuses to reorder an existing one
(update_ops:363) — so the only moment the order is decided is BIRTH. If it can
only be set once, it needs a test that says what it is.

``tests/test_passport_migration.py`` pins order for MIGRATED passports. This
file pins it for MINTED ones. The two are deliberately independent: they share
no helpers, and the expectation here is written out literally rather than
derived from the template file, so a template edit that silently reshuffles keys
fails here instead of being copied into the assertion.

The mint is driven end-to-end through ``_spawn_agent`` rather than read off the
template, because the render, the ``--traits`` post-render write and the JSON
round-trip through json_handler all sit between the template and the file a
citizen is actually born with — and any one of them could reorder it.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

import aipass.spawn.apps.handlers.placeholders as placeholders
from aipass.spawn.apps.modules.core import _spawn_agent

# The 2.0 layout, spelled out. Block order first (R1), then the key order within
# each block, exactly as devpulse's gold reference declares it.
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

# R8 removed these outright. They must not come back at birth by any route.
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
    result = _spawn_agent(str(tmp_path / name), registry_path=str(registry), **kwargs)
    assert result["success"] is True, result.get("error")
    return json.loads((tmp_path / name / ".trinity" / "passport.json").read_text(encoding="utf-8"))


@pytest.fixture
def fake_aipass_home(tmp_path):
    """Pretend tmp_path is the AIPass installation root.

    Residency and the relative {{PATH}} are both answered from where AIPass
    actually sits on disk. Minting a real citizen inside the real src/aipass/ to
    observe "core" would write into the live tree, so the ROOT is relocated
    instead of the checks being weakened.
    """
    home = tmp_path / "AIPassHome"
    home.mkdir()
    with patch.object(placeholders, "_aipass_home", return_value=home):
        yield home


# =============================================================================
# BLOCK ORDER + KEY ORDER — the new pin
# =============================================================================


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
        """The 2.0 field set is CLOSED (R7) — order alone would not catch an addition."""
        passport = _mint(tmp_path)

        assert set(passport) == set(EXPECTED_BLOCK_ORDER)
        for block, keys in EXPECTED_KEY_ORDER.items():
            assert set(passport[block]) == set(keys), f"{block} field set drifted"

    def test_the_shipped_template_declares_the_same_order(self, tmp_path):
        """Mint and template must agree — if they ever diverge, say which one moved."""
        from aipass.spawn.apps.handlers.class_registry import get_template_dir

        template = json.loads((get_template_dir() / ".trinity" / "passport.json").read_text(encoding="utf-8"))

        assert list(template.keys()) == EXPECTED_BLOCK_ORDER
        for block, keys in EXPECTED_KEY_ORDER.items():
            assert list(template[block].keys()) == keys, f"template {block} order drifted from the mint's"


# =============================================================================
# VERSION MARKER, DROPPED FIELDS, CASING
# =============================================================================


class TestNewbornPassportFields:
    """The rest of the 2.0 field contract, at birth."""

    def test_schema_version_is_the_migration_marker(self, tmp_path):
        """R2: version and schema_version are both 2.0.0. schema_version is THE
        marker every migration check reads."""
        meta = _mint(tmp_path)["document_metadata"]

        assert meta["schema_version"] == "2.0.0"
        assert meta["version"] == "2.0.0"

    @pytest.mark.parametrize("block,field", DROPPED_FIELDS)
    def test_dropped_fields_are_absent(self, tmp_path, block, field):
        """R8: citizenship.owner and document_metadata.note are gone.

        ``owner`` is the one that mattered — a self-declared duplicate of the
        registry entry's sealed owner flag. It was written at birth until this
        rework; the registry entry is now the only place that answers it.
        """
        assert field not in _mint(tmp_path)[block]

    def test_top_level_family_is_gone(self, tmp_path):
        """R8: the third drop, checked separately because it was a whole block."""
        assert "family" not in _mint(tmp_path)

    def test_git_branch_is_the_literal_dev(self, tmp_path):
        """R6: no more work/{{branchname}} fossils — one rule, one branch name."""
        assert _mint(tmp_path)["branch_info"]["git_branch"] == "dev"

    def test_names_render_lowercase(self, tmp_path):
        """R1 casing: branch_name / managed_by / document_name are lowercase now.

        The UPPER form survives only as the registry key — a passport is read by
        humans and addressed as @name, and @NAME was never the address.
        """
        passport = _mint(tmp_path, name="mixed_case_agent")

        assert passport["branch_info"]["branch_name"] == "mixed_case_agent"
        assert passport["document_metadata"]["managed_by"] == "mixed_case_agent"
        assert passport["document_metadata"]["document_name"] == "mixed_case_agent.PASSPORT"

    def test_list_fields_are_lists(self, tmp_path):
        """R7: traits / what_i_do / what_i_dont_do are LISTS, not strings."""
        identity = _mint(tmp_path)["identity"]

        for field in ("traits", "what_i_do", "what_i_dont_do"):
            assert identity[field] == [], f"{field} was born as {type(identity[field]).__name__}"

    def test_no_placeholder_survives_the_render(self, tmp_path):
        """A passport is the one file where an unrendered {{X}} is a broken identity."""
        raw = json.dumps(_mint(tmp_path))
        assert "{{" not in raw


# =============================================================================
# {{PATH}} AND {{RESIDENCY}} — the two new derived fields
# =============================================================================


class TestNewbornPathAndResidency:
    """{{CWD}} → {{PATH}} (R1) and the new citizenship.residency (R5)."""

    def test_path_is_relative_and_never_leaks_a_home_directory(self, tmp_path):
        """{{CWD}} rendered an ABSOLUTE path into a tracked, public, committed file.

        That is wrong twice: it publishes the author's home directory, and it is
        wrong on every other machine that ever checks the repo out.
        """
        path = _mint(tmp_path)["branch_info"]["path"]

        assert not Path(path).is_absolute()
        assert not path.startswith(("/", "~"))
        assert "/home/" not in path
        assert str(tmp_path) not in path

    def test_residency_core_for_a_citizen_under_src_aipass(self, tmp_path, fake_aipass_home):
        """R5: 'core' — AIPass's own src/aipass/ home. Path anchors on the repo root."""
        home = fake_aipass_home
        (home / "src" / "aipass").mkdir(parents=True)

        passport = _mint(home / "src" / "aipass", name="core_citizen")

        assert passport["citizenship"]["residency"] == "core"
        assert passport["branch_info"]["path"] == "src/aipass/core_citizen"

    def test_residency_resident_for_a_citizen_under_projects(self, tmp_path, fake_aipass_home):
        """R5: 'resident' — a project hosted in this repo. Path anchors on that
        PROJECT's root, not AIPass's, so the passport reads the same as it would
        if the project ever moved out on its own."""
        home = fake_aipass_home
        project_src = home / "projects" / "demo" / "src" / "demo"
        project_src.mkdir(parents=True)

        passport = _mint(project_src, name="resident_citizen")

        assert passport["citizenship"]["residency"] == "resident"
        assert passport["branch_info"]["path"] == "src/demo/resident_citizen"

    def test_residency_external_for_a_citizen_outside_aipass(self, tmp_path, fake_aipass_home):
        """R5: 'external' — a standalone project on disk, nothing to do with AIPass."""
        outside = tmp_path / "somewhere_else"
        outside.mkdir()

        passport = _mint(outside, name="external_citizen")

        assert passport["citizenship"]["residency"] == "external"

    def test_residency_is_one_of_the_three_declared_values(self, tmp_path):
        """The field is a closed enum, not free text."""
        assert _mint(tmp_path)["citizenship"]["residency"] in {"core", "resident", "external"}
