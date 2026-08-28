# =================== AIPass ====================
# Name: test_birth_receipt.py
# Description: Birth receipt lane — a newborn arrives carrying .trinity/.template_version.json
# Version: 1.0.0
# Created: 2026-08-27
# Modified: 2026-08-27
# =============================================

"""Birth receipt lane tests (DPLAN-0318 marker 7).

The receipt names which trinity template version a citizen carries. @memory's
push stamps it for living branches; spawn stamps it at birth so a newborn is
never born in violation of the receipt group.

The shape is @memory's contract, copied not imported — the drift tests below
go red if their sanctioned lane name or their gold source moves.
"""

import ast
import json
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers import receipt_ops


MEMORY_RECEIPT_SOURCE = (
    Path(__file__).resolve().parents[2] / "memory" / "apps" / "handlers" / "templates" / "receipt.py"
)
SPAWN_TEMPLATES = Path(__file__).resolve().parents[1] / "templates"
GOLD_DIR = Path(__file__).resolve().parents[2] / "memory" / "templates"


# =============================================================================
# GOLD VERSIONS
# =============================================================================


def test_gold_versions_read_schema_version_from_both_templates():
    versions = receipt_ops.gold_template_versions()
    assert set(versions) == {"local", "observations"}
    for name, key in (("LOCAL.template.json", "local"), ("OBSERVATIONS.template.json", "observations")):
        gold = json.loads((GOLD_DIR / name).read_text(encoding="utf-8"))
        assert versions[key] == gold["document_metadata"]["schema_version"]


def test_gold_versions_refuse_when_schema_version_missing(tmp_path, monkeypatch):
    for name in ("LOCAL.template.json", "OBSERVATIONS.template.json"):
        (tmp_path / name).write_text(json.dumps({"document_metadata": {}}), encoding="utf-8")
    monkeypatch.setattr(receipt_ops, "_gold_dir", lambda: tmp_path)
    with pytest.raises(ValueError):
        receipt_ops.gold_template_versions()


def test_gold_versions_refuse_when_template_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt_ops, "_gold_dir", lambda: tmp_path)
    with pytest.raises(ValueError):
        receipt_ops.gold_template_versions()


# =============================================================================
# RECEIPT WRITER
# =============================================================================


def test_write_birth_receipt_writes_exactly_the_four_keys(tmp_path):
    result = receipt_ops.write_birth_receipt(tmp_path)
    assert result["success"] is True
    written = json.loads((tmp_path / ".template_version.json").read_text(encoding="utf-8"))
    assert set(written) == {"template_versions", "stamped", "stamped_by", "config_rendered"}


def test_write_birth_receipt_stamps_the_birth_lane(tmp_path):
    receipt_ops.write_birth_receipt(tmp_path)
    written = json.loads((tmp_path / ".template_version.json").read_text(encoding="utf-8"))
    assert written["stamped_by"] == "spawn birth"


def test_write_birth_receipt_carries_the_gold_versions(tmp_path):
    receipt_ops.write_birth_receipt(tmp_path)
    written = json.loads((tmp_path / ".template_version.json").read_text(encoding="utf-8"))
    assert written["template_versions"] == receipt_ops.gold_template_versions()


def test_stamped_and_config_rendered_match_on_a_fresh_receipt(tmp_path):
    receipt_ops.write_birth_receipt(tmp_path)
    written = json.loads((tmp_path / ".template_version.json").read_text(encoding="utf-8"))
    assert written["stamped"] == written["config_rendered"]


def test_timestamps_are_second_resolution_isoformat(tmp_path):
    receipt_ops.write_birth_receipt(tmp_path)
    written = json.loads((tmp_path / ".template_version.json").read_text(encoding="utf-8"))
    # @memory writes isoformat(timespec="seconds") — no microseconds, no offset
    assert "." not in written["stamped"]
    assert len(written["stamped"]) == 19


def test_write_birth_receipt_reports_failure_instead_of_raising(tmp_path, monkeypatch):
    monkeypatch.setattr(receipt_ops, "gold_template_versions", _raise_value_error)
    result = receipt_ops.write_birth_receipt(tmp_path)
    assert result["success"] is False
    assert result["error"]
    assert not (tmp_path / ".template_version.json").exists()


def _raise_value_error():
    raise ValueError("gold unreadable")


# =============================================================================
# DRIFT AGAINST @memory (copied, never imported)
# =============================================================================


def test_stamped_by_matches_memorys_sanctioned_birth_lane():
    """@memory's writer refuses any lane name outside its own constants."""
    tree = ast.parse(MEMORY_RECEIPT_SOURCE.read_text(encoding="utf-8"))
    theirs = {
        node.targets[0].id: node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and isinstance(node.value, ast.Constant)
    }
    assert theirs["STAMPED_BY_BIRTH"] == receipt_ops.STAMPED_BY_BIRTH


def test_spawn_does_not_import_memorys_receipt_handler():
    source = (Path(receipt_ops.__file__)).read_text(encoding="utf-8")
    assert "aipass.memory" not in source


# =============================================================================
# SEEDS MATCH THE GOLD TRINITY TEMPLATES
# =============================================================================


@pytest.mark.parametrize("citizen_class", ["aipass_framework", "project_agent"])
@pytest.mark.parametrize(
    "seed_name,gold_name",
    [("local.json", "LOCAL.template.json"), ("observations.json", "OBSERVATIONS.template.json")],
)
def test_trinity_seed_matches_gold_template(citizen_class, seed_name, gold_name):
    """A seed that drifts from gold mints a citizen that fails the meta-line group."""
    seed = (SPAWN_TEMPLATES / citizen_class / ".trinity" / seed_name).read_text(encoding="utf-8")
    gold = (GOLD_DIR / gold_name).read_text(encoding="utf-8")
    # spawn's engine maps BRANCHNAME->UPPER and BRANCH->lower; gold renders lowercase
    normalized = seed.replace("{{BRANCH}}", "{{BRANCHNAME}}")
    # project_agent is born by `aipass new`, not `aipass init` — the only sanctioned divergence
    normalized = normalized.replace("created by aipass new.", "created by aipass init.")
    assert normalized == gold


@pytest.mark.parametrize("citizen_class", ["aipass_framework", "project_agent"])
@pytest.mark.parametrize("seed_name", ["local.json", "observations.json"])
def test_trinity_seed_carries_no_status_block(citizen_class, seed_name):
    """document_metadata.status is deleted by the standard — health is computed."""
    seed = json.loads((SPAWN_TEMPLATES / citizen_class / ".trinity" / seed_name).read_text(encoding="utf-8"))
    assert "status" not in seed["document_metadata"]


# =============================================================================
# BIRTH END TO END
# =============================================================================


def test_a_minted_citizen_arrives_carrying_a_valid_receipt(tmp_path):
    from aipass.spawn.apps.modules.core import _spawn_agent

    result = _spawn_agent(str(tmp_path / "newbie"), role="Test", purpose="receipt e2e")

    assert result["success"] is True
    receipt_path = tmp_path / "newbie" / ".trinity" / receipt_ops.RECEIPT_NAME
    assert receipt_path.exists()
    written = json.loads(receipt_path.read_text(encoding="utf-8"))
    assert set(written) == {"template_versions", "stamped", "stamped_by", "config_rendered"}
    assert written["stamped_by"] == receipt_ops.STAMPED_BY_BIRTH
    assert written["template_versions"] == receipt_ops.gold_template_versions()


def test_an_unstampable_receipt_surfaces_but_does_not_abandon_the_birth(tmp_path, monkeypatch):
    """@memory's gold templates are another branch's files — a citizen that cannot
    be born because they are unreadable is worse than one missing a receipt."""
    from aipass.spawn.apps.modules import core

    monkeypatch.setattr(core, "write_birth_receipt", lambda _: {"success": False, "error": "gold unreadable"})
    result = core._spawn_agent(str(tmp_path / "orphan"), role="Test", purpose="receipt failure")

    assert result["success"] is True
    assert not (tmp_path / "orphan" / ".trinity" / receipt_ops.RECEIPT_NAME).exists()
    assert any("Birth receipt not stamped" in issue for issue in result["validation_issues"])


def test_the_receipt_is_stamped_before_the_citizen_is_registered(tmp_path, monkeypatch):
    """A registered citizen always carries a receipt — the order is the guarantee."""
    from aipass.spawn.apps.modules import core

    seen = {}

    real_add = core.add_to_registry

    def spy(*args, **kwargs):
        target = tmp_path / "ordered" / ".trinity" / receipt_ops.RECEIPT_NAME
        seen["receipt_existed_at_registration"] = target.exists()
        return real_add(*args, **kwargs)

    monkeypatch.setattr(core, "add_to_registry", spy)
    core._spawn_agent(str(tmp_path / "ordered"), role="Test", purpose="ordering")

    assert seen["receipt_existed_at_registration"] is True


# =============================================================================
# RETIRE — THE MEMORY LEAVES WITH THE CITIZEN
# =============================================================================


def test_retire_carries_the_whole_trinity_into_the_archive(tmp_path, monkeypatch):
    """The archive is the only copy after the rmtree — a receipt left behind is lost."""
    from aipass.spawn.apps.handlers import delete_ops
    from aipass.spawn.apps.modules.core import _spawn_agent

    project = tmp_path / "project"
    project.mkdir()
    (project / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    _spawn_agent(str(project / "leaver"), role="Test", purpose="retire e2e")

    registry_path = project / "AIPASS_REGISTRY.json"
    monkeypatch.setattr(delete_ops, "find_registry", lambda *a, **k: registry_path)
    monkeypatch.setattr(delete_ops, "is_protected", lambda *a, **k: (False, ""))

    result = delete_ops.delete_branch("leaver", confirm=False)

    assert result["success"] is True
    archive = Path(result["archive_path"])
    for name in (".template_version.json", "local.json", "observations.json", "passport.json", "README.md"):
        assert (archive / ".trinity" / name).exists(), f"{name} did not travel into the archive"
    assert not (project / "leaver").exists()

    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    entries = registry["branches"]
    names = [e["name"] for e in entries] if isinstance(entries, list) else list(entries)
    assert "LEAVER" not in names


# =============================================================================
# ADOPTION — FILL THE HOLE, NEVER REWRITE THE RECORD
# =============================================================================


def test_adopting_a_directory_without_a_receipt_stamps_one(tmp_path):
    from aipass.spawn.apps.modules.core import _spawn_agent

    target = tmp_path / "adoptee"
    _spawn_agent(str(target), role="Test", purpose="adopt receipt")
    (target / ".trinity" / receipt_ops.RECEIPT_NAME).unlink()

    result = _spawn_agent(str(target))

    assert result["success"] is True
    written = json.loads((target / ".trinity" / receipt_ops.RECEIPT_NAME).read_text(encoding="utf-8"))
    assert written["stamped_by"] == receipt_ops.STAMPED_BY_BIRTH


def test_adoption_never_restamps_a_receipt_another_lane_wrote(tmp_path):
    """A push-stamped receipt records which lane last touched those files."""
    from aipass.spawn.apps.modules.core import _spawn_agent

    target = tmp_path / "pushed"
    _spawn_agent(str(target), role="Test", purpose="adopt receipt")
    receipt_path = target / ".trinity" / receipt_ops.RECEIPT_NAME
    theirs = {
        "template_versions": {"local": "3.0.0", "observations": "3.0.0"},
        "stamped": "2026-01-01T00:00:00",
        "stamped_by": "memory push",
        "config_rendered": "2026-01-01T00:00:00",
    }
    receipt_path.write_text(json.dumps(theirs, indent=2) + "\n", encoding="utf-8")

    _spawn_agent(str(target))

    assert json.loads(receipt_path.read_text(encoding="utf-8")) == theirs
