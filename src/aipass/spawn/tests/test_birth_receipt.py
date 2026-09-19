# =================== AIPass ====================
# Name: test_birth_receipt.py
# Description: Birth receipt lane — a newborn arrives carrying .trinity/.template_version.json
# Version: 1.2.0
# Created: 2026-08-27
# Modified: 2026-09-19
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
FLEET = Path(__file__).resolve().parents[2]

#: @seedgo's published README cap (DPLAN-0347, ruled by the owner 2026-09-15 16:02).
SEEDGO_CONTEXT_PACK = FLEET / "seedgo" / "apps" / "handlers" / "context_standards" / "pack.json"

#: @memory's whole-file budgets for the three .trinity files, plus its per-string cap.
MEMORY_CONFIG = FLEET / "memory" / "memory_json" / "custom_config" / "memory.config.json"


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


# There is ONE template on disk now (DPLAN-0319 R3) — the class-named dirs
# retired to templates/.archive/ — so the seed checks below stop parametrizing
# over classes and read the one citizen template. The "aipass new" divergence
# the old project_agent seed carried retired with that template: a single seed
# has nothing left to diverge from, so the normalisation for it is gone too.
CITIZEN_TRINITY = SPAWN_TEMPLATES / "citizen" / ".trinity"


@pytest.mark.parametrize(
    "seed_name,gold_name",
    [("local.json", "LOCAL.template.json"), ("observations.json", "OBSERVATIONS.template.json")],
)
def test_trinity_seed_matches_gold_template(seed_name, gold_name):
    """A seed that drifts from gold mints a citizen that fails the meta-line group."""
    seed = (CITIZEN_TRINITY / seed_name).read_text(encoding="utf-8")
    gold = (GOLD_DIR / gold_name).read_text(encoding="utf-8")
    # Gold spells the placeholder as spawn does ({{BRANCH}} -> lower) since
    # memory's 2026-09-15 fix, so the seed is a byte copy of gold: no
    # normalisation, a drift of one character fails here.
    assert seed == gold


@pytest.mark.parametrize("seed_name", ["local.json", "observations.json"])
def test_trinity_seed_carries_no_status_block(seed_name):
    """document_metadata.status is deleted by the standard — health is computed."""
    seed = json.loads((CITIZEN_TRINITY / seed_name).read_text(encoding="utf-8"))
    assert "status" not in seed["document_metadata"]


def test_the_one_template_is_what_every_class_mints_from():
    """Guard the collapse above: if a class ever gets its own dir again, the two
    seed checks would be silently testing only one of them."""
    from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir

    classes = get_available_classes()
    assert len(classes) == 2, f"the class registry offers {classes} - the sweep below is not sweeping the fleet"
    for citizen_class in classes:
        assert get_template_dir(citizen_class) / ".trinity" == CITIZEN_TRINITY


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


# =============================================================================
# THE BIRTH CONTRACT — A NEWBORN STARTS INSIDE EVERY CAP (DPLAN-0347)
# =============================================================================


def _readme_cap() -> int:
    """@seedgo's cap, read from its pack manifest at assert time."""
    pack = json.loads(SEEDGO_CONTEXT_PACK.read_text(encoding="utf-8"))
    return int(pack["caps"]["README.md"]["max_chars"])


def _prompt_cap() -> int:
    """@hooks' cap, read off the module that enforces it at render time."""
    from aipass.hooks.apps.modules import grounding_content

    return int(getattr(grounding_content, "BRANCH_CHAR_BUDGET"))


def _dashboard_cap() -> int:
    """@prax's cap, read off its exported name."""
    from aipass.prax.apps.modules import dashboard

    return int(getattr(dashboard, "DASHBOARD_CHAR_BUDGET"))


def _memory_file_budgets() -> dict:
    """@memory's per-file budgets for .trinity, straight out of its config."""
    config = json.loads(MEMORY_CONFIG.read_text(encoding="utf-8"))
    return config["entry_limits"]["file_budgets"]


def _newborn_budget() -> dict:
    """Every startup file's cap, keyed by branch-relative path.

    Read from the FOUR owners every time it is called — seedgo's pack, hooks'
    module, memory's config, prax's module. Nothing here is a literal, which is
    the contract: an owner that moves a cap moves this pin with it, and a cap
    copied into spawn would go stale silently instead.
    """
    budgets = _memory_file_budgets()
    return {
        "README.md": _readme_cap(),
        ".aipass/aipass_local_prompt.md": _prompt_cap(),
        ".trinity/local.json": int(budgets["local.json"]["max_chars"]),
        ".trinity/observations.json": int(budgets["observations.json"]["max_chars"]),
        ".trinity/passport.json": int(budgets["passport.json"]["max_chars"]),
        "DASHBOARD.local.json": _dashboard_cap(),
    }


def _strings(node) -> list:
    """Every string leaf in a loaded JSON document, keys excluded."""
    if isinstance(node, str):
        return [node]
    if isinstance(node, dict):
        return [s for value in node.values() for s in _strings(value)]
    if isinstance(node, list):
        return [s for item in node for s in _strings(item)]
    return []


def test_a_newborn_is_born_inside_every_owners_cap(tmp_path):
    """The birth contract (DPLAN-0347, FPLAN-0593 Phase 3).

    spawn is not the source of the fleet's README fat — a citizen is born at
    ~2k and grows to a 46k median on its own — but the day the template drifts
    past a cap, every newborn starts in violation. This is the pin that makes
    that a red instead of a discovery six months later.
    """
    from aipass.spawn.apps.modules.core import _spawn_agent

    result = _spawn_agent(str(tmp_path / "budgeted"), role="Test", purpose="birth budget")
    assert result["success"] is True

    over = []
    for rel, cap in _newborn_budget().items():
        chars = len((tmp_path / "budgeted" / rel).read_text(encoding="utf-8"))
        if chars > cap:
            over.append(f"{rel}: {chars}/{cap}")
    assert over == [], f"a newborn is born over cap: {over}"


def test_every_newborn_passport_string_is_inside_memorys_per_string_cap(tmp_path):
    """The file budget is one number; a single runaway string is the other."""
    from aipass.spawn.apps.modules.core import _spawn_agent

    _spawn_agent(str(tmp_path / "stringy"), role="Test", purpose="passport strings")
    cap = int(_memory_file_budgets()["passport.json"]["max_string_chars"])
    passport = json.loads((tmp_path / "stringy" / ".trinity" / "passport.json").read_text(encoding="utf-8"))

    over = [f"{len(s)}/{cap}: {s[:40]}" for s in _strings(passport) if len(s) > cap]
    assert over == [], f"newborn passport strings over @memory's per-string cap: {over}"


def test_a_newborn_carries_its_own_dashboard_without_flow_or_prax(tmp_path):
    """A directory with no dashboard is not a branch (DPLAN-0347).

    @flow's writer stopped CREATING a missing DASHBOARD.local.json (2.1.0), so
    the question is what birth relies on. Measured: neither @flow nor @prax —
    the dashboard ships in the template and lands rendered at mint, which is why
    flow's change costs a newborn nothing. This pin is what would go red if the
    file ever left the template and birth started depending on another branch.
    """
    from aipass.spawn.apps.modules.core import _spawn_agent

    _spawn_agent(str(tmp_path / "dashed"), role="Test", purpose="dashboard at birth")

    raw = (tmp_path / "dashed" / "DASHBOARD.local.json").read_text(encoding="utf-8")
    assert "{{" not in raw, "the newborn's dashboard still carries unrendered placeholders"
    assert json.loads(raw)["branch"] == "DASHED"


def _docs_page_cap() -> int:
    """@seedgo's docs/*.md cap, read from the same pack manifest at assert time."""
    pack = json.loads(SEEDGO_CONTEXT_PACK.read_text(encoding="utf-8"))
    return int(pack["caps"]["docs/*.md"]["max_chars"])


def test_the_stamped_docs_index_copies_no_cap_and_points_at_the_standard():
    """The docs index every newborn is born with names no number seedgo owns (DPLAN-0351).

    A cap typed into a template is stamped into every branch and keeps saying so
    after its owner moves it. The index names the standard instead, and the
    standard reads the cap live.
    """
    cap = _docs_page_cap()
    index = (SPAWN_TEMPLATES / "citizen" / "docs" / "README.md").read_text(encoding="utf-8")

    for spelling in (f"{cap:,}", str(cap)):
        assert spelling not in index, f"the stamped docs index copies seedgo's cap as {spelling!r}"
    assert "drone @seedgo standard docs_page" in index


def test_every_cap_is_read_from_its_owner_and_never_copied_into_this_file():
    """A hand-copied cap is the failure this pin exists for.

    Each number lives with the branch that enforces it; a literal here would
    keep passing after its owner moved, which is precisely how three README
    counts in my own docs once drifted apart. So: every cap must resolve to a
    positive int through an owner's door, and none of those values may appear
    as a literal anywhere in this module.
    """
    budget = _newborn_budget()
    assert len(budget) == 6, f"a startup file lost its cap door: {sorted(budget)}"
    for rel, cap in budget.items():
        assert isinstance(cap, int) and cap > 0, f"{rel} resolved to {cap!r} instead of a positive cap"

    source = ast.parse(Path(__file__).read_text(encoding="utf-8"))
    literals = {
        node.value
        for node in ast.walk(source)
        if isinstance(node, ast.Constant) and isinstance(node.value, int) and not isinstance(node.value, bool)
    }
    copied = sorted((set(budget.values()) | {_docs_page_cap()}) & literals)
    assert copied == [], f"cap values hand-copied into this test: {copied}"


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
