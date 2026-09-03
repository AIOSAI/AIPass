"""Tests for the aipass_standards handler directory."""

# =================== META ====================
# Name: test_aipass_standards.py
# Description: Unit tests for handlers/aipass_standards/
# Version: 1.0.0
# Created: 2026-03-24
# Modified: 2026-03-24
# =============================================

import pytest
from unittest.mock import MagicMock


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_infrastructure(monkeypatch):
    """Mock heavy infrastructure imports for standards checkers."""
    import sys

    mock_logger = MagicMock()
    mock_json_handler = MagicMock()
    mock_json_handler.log_operation = MagicMock(return_value=True)

    # -- prax ---------------------------------------------------------------
    prax_mod = MagicMock()
    prax_mod.logger = mock_logger
    monkeypatch.setitem(sys.modules, "aipass.prax", prax_mod)

    # -- seedgo json handler ------------------------------------------------
    json_pkg = MagicMock()
    json_pkg.json_handler = mock_json_handler
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json", json_pkg)
    json_mod = MagicMock()
    json_mod.log_operation = mock_json_handler.log_operation
    monkeypatch.setitem(sys.modules, "aipass.seedgo.apps.handlers.json.json_handler", json_mod)

    # Force re-imports of specific checker modules we test
    for mod_name in [
        "aipass.seedgo.apps.handlers.aipass_standards.naming_check",
        "aipass.seedgo.apps.handlers.aipass_standards.json_structure_check",
        "aipass.seedgo.apps.handlers.aipass_standards.meta_check",
    ]:
        monkeypatch.delitem(sys.modules, mod_name, raising=False)


# ---------------------------------------------------------------------------
# Tests -- naming_check.check_module
# ---------------------------------------------------------------------------


def test_naming_check_module_returns_dict(tmp_path):
    """naming_check.check_module returns a dict with expected keys."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample module."""\n\ndef my_function():\n    pass\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    result = check_module(str(py_file))
    assert isinstance(result, dict)
    assert "passed" in result
    assert "checks" in result
    assert "score" in result
    assert isinstance(result["passed"], bool)
    assert isinstance(result["checks"], list)
    assert isinstance(result["score"], (int, float))


def test_naming_check_module_missing_file():
    """naming_check.check_module handles missing file gracefully."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    result = check_module("/nonexistent/path/file.py")
    assert isinstance(result, dict)
    assert "passed" in result


def test_naming_check_module_with_bypass(tmp_path):
    """naming_check.check_module respects bypass rules."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_module

    bypass = [{"file": "sample.py", "standard": "naming", "reason": "test"}]
    result = check_module(str(py_file), bypass_rules=bypass)
    assert isinstance(result, dict)
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Tests -- json_structure_check.check_module
# ---------------------------------------------------------------------------


def test_json_structure_check_returns_expected_keys(tmp_path):
    """json_structure_check.check_module returns dict with standard keys."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample."""\nimport json\n',
        encoding="utf-8",
    )
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module(str(py_file))
    assert isinstance(result, dict)
    assert "passed" in result
    assert "score" in result
    assert "checks" in result


def test_json_structure_check_missing_file():
    """json_structure_check.check_module handles missing file."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module("/nonexistent/module.py")
    assert isinstance(result, dict)
    assert "passed" in result


def test_json_structure_check_has_standard_field(tmp_path):
    """json_structure_check.check_module includes 'standard' in output."""
    py_file = tmp_path / "test_mod.py"
    py_file.write_text("x = 1\n", encoding="utf-8")
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    result = check_module(str(py_file))
    assert "standard" in result


def test_json_structure_custom_config_subdir_passes(tmp_path):
    """Branch with {branch}_json/custom_config/ passes directory check."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    cc = json_dir / "custom_config"
    cc.mkdir()
    (cc / "settings.json").write_text("{}", encoding="utf-8")
    (json_dir / "config.json").write_text("{}", encoding="utf-8")

    violations = _check_json_dir_structure(str(branch))
    assert violations == []


def test_json_structure_random_subdir_fails(tmp_path):
    """Branch with an unsanctioned subdir under {branch}_json/ is flagged."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "custom_config").mkdir()
    (json_dir / "extra_stuff").mkdir()

    violations = _check_json_dir_structure(str(branch))
    assert len(violations) == 1
    assert "extra_stuff" in violations[0]["message"]


def test_json_structure_hidden_subdir_ignored(tmp_path):
    """Hidden subdirs (e.g. .archive) under {branch}_json/ are not flagged."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / ".archive").mkdir()

    violations = _check_json_dir_structure(str(branch))
    assert violations == []


def test_json_structure_no_json_dir_passes(tmp_path):
    """Branch with no {branch}_json/ directory produces no violations."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()

    violations = _check_json_dir_structure(str(branch))
    assert violations == []


def test_json_structure_check_branch_post(tmp_path):
    """check_branch_post returns violations and scores."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_post

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "bad_split").mkdir()

    violations, scores = check_branch_post(str(branch))
    assert len(violations) == 1
    assert scores == [0]

    # Clean branch
    (json_dir / "bad_split").rmdir()
    (json_dir / "custom_config").mkdir()
    violations2, scores2 = check_branch_post(str(branch))
    assert violations2 == []
    assert scores2 == [100]


def test_json_structure_bypassed_subdir_passes(tmp_path):
    """A subdir bypassed via bypass_rules is not flagged."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "compass").mkdir()

    bypass_rules = [{"standard": "json_structure", "file": "mybranch_json/compass", "reason": "test"}]
    violations = _check_json_dir_structure(str(branch), bypass_rules=bypass_rules)
    assert violations == []


def test_json_structure_unbypassed_subdir_still_fails(tmp_path):
    """An unsanctioned subdir without a bypass entry is still flagged."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_json_dir_structure

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "compass").mkdir()
    (json_dir / "random_dir").mkdir()

    bypass_rules = [{"standard": "json_structure", "file": "mybranch_json/compass", "reason": "test"}]
    violations = _check_json_dir_structure(str(branch), bypass_rules=bypass_rules)
    assert len(violations) == 1
    assert "random_dir" in violations[0]["message"]


# ---------------------------------------------------------------------------
# Tests -- naming_check.is_bypassed
# ---------------------------------------------------------------------------


def test_naming_is_bypassed_true():
    """is_bypassed returns True when rule matches."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    rules = [{"file": "foo.py", "standard": "naming", "reason": "legacy"}]
    assert is_bypassed("some/path/foo.py", "naming", bypass_rules=rules) is True


def test_naming_is_bypassed_false_no_rules():
    """is_bypassed returns False with no rules."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    assert is_bypassed("foo.py", "naming", bypass_rules=None) is False


def test_naming_is_bypassed_wrong_standard():
    """is_bypassed returns False when standard does not match."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import is_bypassed

    rules = [{"file": "foo.py", "standard": "imports", "reason": "legacy"}]
    assert is_bypassed("foo.py", "naming", bypass_rules=rules) is False


# ---------------------------------------------------------------------------
# Tests -- json_structure_content custom_config doctrine (Patrick ruling S193)
# ---------------------------------------------------------------------------


def _custom_config_doctrine_text():
    """Just the custom_config house-pattern section, lowercased.

    Sliced deliberately: asserting against the whole 200-line standard would
    let a generic word like "untouched" pass from some unrelated paragraph
    after the doctrine block itself was deleted.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_content import (
        get_json_structure_standards,
    )

    full = get_json_structure_standards()
    start = full.index("custom_config/ HOUSE PATTERN:")
    end = full.index("KEY WARNINGS:", start)
    return full[start:end].lower()


def test_doctrine_file_is_the_runtime_authority():
    """S193: the JSON on disk wins over code, and configs live in JSONs."""
    text = _custom_config_doctrine_text()

    assert "runtime authority" in text
    assert "configs live in the json" in text
    # The operator edits the file; code does not out-rank it.
    assert "win over code" in text
    # The reason a config belongs in the file at all — reading Python to find
    # a tunable is the failure this rule exists to prevent.
    assert "require reading python" in text


def test_doctrine_missing_file_regenerates_in_full():
    """S193: a genuinely-missing file is regenerated from the seed, in full."""
    text = _custom_config_doctrine_text()

    assert "regeneration seed" in text
    assert "regenerate it in full" in text


def test_doctrine_malformed_file_is_never_clobbered():
    """S193: malformed/wrong-shape fails loud and leaves the operator file alone."""
    text = _custom_config_doctrine_text()

    assert "never clobber" in text
    assert "untouched" in text
    assert "in memory" in text


def test_doctrine_pins_the_write_boundary():
    """The one sentence that decides whether a snapshot writer is legal.

    Everything else in the block describes a load; this is the only line that
    bounds a WRITE. Without it pinned, the whole yellow paragraph could be
    deleted and every other doctrine test would still pass.
    """
    text = _custom_config_doctrine_text()

    assert "code never writes into custom_config/ outside that regeneration path" in text
    assert "snapshot overwrites" in text


def test_doctrine_states_merge_direction():
    """Deep-merge is only correct in one direction: file over seed."""
    text = _custom_config_doctrine_text()

    assert "deep-merge" in text
    assert "file over seed" in text
    # Seed-over-file would silently undo every operator edit on a key the
    # seed also carries — the exact inversion S193 reversed.
    assert "seed over file" not in text


def test_doctrine_does_not_carry_the_reversed_never_snapshot_rule():
    """The pre-S193 doctrine said the opposite; it must not creep back.

    This text has now inverted twice (FPLAN-0380 ws1 -> ruling S193). A checker
    cannot catch a standard that contradicts the fleet's operating truth, so
    the wording itself is pinned here.
    """
    text = _custom_config_doctrine_text()

    assert "never self-heal-write" not in text
    assert "holds only overrides" not in text
    # "Missing file = defaults" was the reversed rule — missing now regenerates.
    assert "missing file = defaults" not in text


def test_doctrine_keeps_six_key_drift_as_seed_lesson():
    """The @memory drift story stays, reframed as why the SEED must stay aligned."""
    text = _custom_config_doctrine_text()

    assert "6 keys" in text
    # Reframed: stale seed regenerates stale truth, not "files can't hold config".
    assert "stale seed regenerates stale truth" in text


def test_doctrine_omits_queued_quarantine_upgrade():
    """Quarantine-then-regenerate is queued behind the medic digest, not current."""
    text = _custom_config_doctrine_text()

    assert "quarantine" not in text


# ---------------------------------------------------------------------------
# Tests -- json_structure_check.check_branch_info (custom_config signpost)
# ---------------------------------------------------------------------------


def _branch_with_custom_config(tmp_path, filenames):
    """Build a branch whose {branch}_json/custom_config/ holds filenames."""
    branch = tmp_path / "mybranch"
    custom_config = branch / "mybranch_json" / "custom_config"
    custom_config.mkdir(parents=True)
    for name in filenames:
        (custom_config / name).write_text("{}", encoding="utf-8")
    return branch


def test_custom_config_info_no_json_dir(tmp_path):
    """A branch with no {branch}_json/ produces no info line."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_info

    branch = tmp_path / "mybranch"
    branch.mkdir()

    assert check_branch_info(str(branch)) == []


def test_custom_config_info_no_custom_config_dir(tmp_path):
    """A branch_json/ without custom_config/ produces no info line."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_info

    branch = tmp_path / "mybranch"
    (branch / "mybranch_json").mkdir(parents=True)

    assert check_branch_info(str(branch)) == []


def test_custom_config_info_readme_only(tmp_path):
    """custom_config/ holding only README.md is scaffolding, not an override."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_info

    branch = _branch_with_custom_config(tmp_path, ["README.md"])

    assert check_branch_info(str(branch)) == []


def test_custom_config_info_lists_operator_files(tmp_path):
    """Operator files are named, counted, and carry the guide pointer."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import (
        CUSTOM_CONFIG_GUIDE,
        check_branch_info,
    )

    branch = _branch_with_custom_config(tmp_path, ["README.md", "cadence_config.json", "alpha_config.json"])

    lines = check_branch_info(str(branch))
    assert len(lines) == 1
    line = lines[0]
    assert "mybranch_json/custom_config/" in line
    assert "2 operator files" in line
    # Sorted, README excluded
    assert "alpha_config.json, cadence_config.json" in line
    assert "README.md" not in line
    assert "content not audited" in line
    # Track the constant, not a copy of it — test_standards_query proves the
    # constant names a command that actually resolves.
    assert CUSTOM_CONFIG_GUIDE in line


def test_custom_config_info_singular_wording(tmp_path):
    """One override reads 'file', not 'files'."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_info

    branch = _branch_with_custom_config(tmp_path, ["memory.config.json"])

    assert "1 operator file (" in check_branch_info(str(branch))[0]


def test_custom_config_info_ignores_subdirs(tmp_path):
    """Directories inside custom_config/ are not listed as operator files."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_info

    branch = _branch_with_custom_config(tmp_path, [])
    (branch / "mybranch_json" / "custom_config" / "nested").mkdir()

    assert check_branch_info(str(branch)) == []


def test_custom_config_never_affects_score(tmp_path):
    """Operator files in custom_config/ leave check_branch_post at a clean 100."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_branch_post

    branch = _branch_with_custom_config(tmp_path, ["cadence_config.json"])

    violations, scores = check_branch_post(str(branch))
    assert violations == []
    assert scores == [100]


# ---------------------------------------------------------------------------
# Tests -- json_handler_check disk triplet completeness (bidirectional)
# ---------------------------------------------------------------------------


def _branch_with_json_files(tmp_path, filenames):
    """Build a branch whose {branch}_json/ holds filenames."""
    branch = tmp_path / "mybranch"
    json_dir = branch / "mybranch_json"
    json_dir.mkdir(parents=True)
    for name in filenames:
        (json_dir / name).write_text("{}", encoding="utf-8")
    return branch


def test_disk_triplets_no_json_dir(tmp_path):
    """No {branch}_json/ directory passes (no JSON activity)."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = tmp_path / "mybranch"
    branch.mkdir()

    result = _check_disk_triplets(branch)
    assert result["passed"] is True


def test_disk_triplets_complete(tmp_path):
    """A full config/data/log trio passes."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["audit_config.json", "audit_data.json", "audit_log.json"])

    result = _check_disk_triplets(branch)
    assert result["passed"] is True
    assert "All 1 modules" in result["message"]


def test_disk_triplets_config_without_log_is_caught(tmp_path):
    """A hand-written config with no log sibling is no longer invisible."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json"])

    result = _check_disk_triplets(branch)
    assert result["passed"] is False
    assert "trigger (missing data, log)" in result["message"]


def test_disk_triplets_data_without_siblings_is_caught(tmp_path):
    """A lone data file implies its config and log must exist."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["solo_data.json"])

    result = _check_disk_triplets(branch)
    assert result["passed"] is False
    assert "solo (missing config, log)" in result["message"]


def test_disk_triplets_log_without_config_still_caught(tmp_path):
    """The original log-first direction keeps working."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["audit_log.json", "audit_data.json"])

    result = _check_disk_triplets(branch)
    assert result["passed"] is False
    assert "audit (missing config)" in result["message"]


def test_disk_triplets_ignores_non_triplet_files(tmp_path):
    """Files outside the {stem}_{kind}.json shape are not modules."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["audit_cache.json", "config.json", "registry.json"])

    result = _check_disk_triplets(branch)
    assert result["passed"] is True
    assert "no triplet files" in result["message"]


def test_disk_triplets_bypass_respected(tmp_path):
    """A bypassed missing member does not fail the branch."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json", "trigger_data.json"])
    rules = [
        {
            "file": "mybranch_json/trigger_log.json",
            "standard": "json_handler",
            "reason": "config-only module, no operations to log",
        }
    ]

    result = _check_disk_triplets(branch, bypass_rules=rules)
    assert result["passed"] is True


def test_disk_triplets_bypass_wrong_standard_ignored(tmp_path):
    """A bypass for another standard does not suppress a triplet gap."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json", "trigger_data.json"])
    rules = [{"file": "mybranch_json/trigger_log.json", "standard": "json_structure", "reason": "unrelated"}]

    result = _check_disk_triplets(branch, bypass_rules=rules)
    assert result["passed"] is False


def test_disk_triplets_multiple_gaps_counted(tmp_path):
    """The message counts incomplete modules against total modules found."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_disk_triplets

    branch = _branch_with_json_files(
        tmp_path,
        ["a_config.json", "a_data.json", "a_log.json", "b_config.json", "c_log.json"],
    )

    result = _check_disk_triplets(branch)
    assert result["passed"] is False
    assert result["message"].startswith("2/3 modules missing triplet files")


# ---------------------------------------------------------------------------
# Tests -- json_handler_check accepts the one shim (DPLAN-0325 part A)
# ---------------------------------------------------------------------------


def _canonical_shim_bytes_or_skip():
    """The canonical shim as the pinned spec defines it, or skip saying why.

    Read from the spec block rather than from any branch copy: a constant
    taught by a branch would learn that branch's drift and then bless it.

    The spec lives under ``devpulse/docs.local/``, and ``docs.local/`` is
    gitignored fleet-wide (.gitignore:58) — so it is ABSENT on a fresh
    checkout and these pins cannot run there. Skipping with the path named is
    the honest report; asserting against a file CI does not have is the exact
    shape of the machine-local defect that turned every board red on 2026-09-02
    (FPLAN-0474/0475), when a check derived a fleet fact from the gitignored
    registry and degraded silently instead of failing loudly.

    What survives on CI regardless: the hash constant itself, which is in the
    checker and therefore in the repo, and every pin below that builds its own
    input instead of reading the spec.
    """
    import re
    from pathlib import Path

    import aipass

    # From the installed package, so the read is identical whichever rootdir
    # pytest picks — the same discovery the contract suite uses.
    spec = Path(aipass.__file__).resolve().parent / "devpulse" / "docs.local" / "DPLAN-0325_spec.md"
    if not spec.is_file():
        pytest.skip(f"pinned spec not present ({spec}) — docs.local/ is gitignored, so this pin is local-only")
    text = spec.read_text(encoding="utf-8")
    section = text.index("## 3. The shim")
    block = re.search(r"```python\n(.*?)\n```", text[section:], re.S)
    assert block is not None, "DPLAN-0325 section 3 no longer carries a python block"
    return block.group(1) + "\n"


def test_the_pinned_hash_is_the_hash_of_the_spec_block():
    """The constant and the spec cannot drift apart without this turning red.

    The whole accept path is one comparison against one constant, so the
    constant IS the standard. If the spec is amended and the constant is not,
    every migrated branch fails its own audit for a reason no message explains.
    """
    import hashlib

    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import CANONICAL_SHIM_SHA256

    measured = hashlib.sha256(_canonical_shim_bytes_or_skip().encode("utf-8")).hexdigest()
    assert measured == CANONICAL_SHIM_SHA256, (
        "the pinned canonical-shim hash no longer matches DPLAN-0325 section 3 — "
        "amend the constant in the same change as the spec"
    )


def test_the_canonical_shim_passes_capability_by_hash():
    """The spec's own bytes are accepted, and accepted on the identity path."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _capability_verdict

    passed, message = _capability_verdict(_canonical_shim_bytes_or_skip(), "anybranch")
    assert passed is True
    assert "sha256" in message


def test_one_changed_character_is_no_longer_the_canonical_shim():
    """Identity, not resemblance: a shim that drifts stops being the shim.

    Red-first proof that the hash path is doing the work. The mutated text
    still imports the service, so it falls through to the transitional path
    and is still accepted overall — this pins WHICH path answered, because a
    check that cannot say why it passed cannot be tightened in part B.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import (
        _capability_verdict,
        _is_canonical_shim,
    )

    mutated = _canonical_shim_bytes_or_skip().replace("_h = json_handler.for_module", "_h  = json_handler.for_module")
    assert _is_canonical_shim(mutated) is False
    passed, message = _capability_verdict(mutated, "anybranch")
    assert passed is True
    assert "sha256" not in message


def test_the_service_import_alone_is_not_enough_when_a_branch_token_survives():
    """A half-migrated shim that kept its own document directory is refused.

    The failure this forbids is a branch that adopts the import, keeps its
    captured `_JSON_DIR`, and reads as migrated while still writing through
    its own binding.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _has_service_import

    half = "from aipass.prax import json_handler\n_JSON_DIR = _ROOT / 'canary_json'\n"
    assert _has_service_import(half, "canary") is False

    clean = "from aipass.prax import json_handler\n_h = json_handler.for_module(__file__)\n"
    assert _has_service_import(clean, "canary") is True


def test_json_handler_underscore_handler_substring_does_not_refuse_the_shim():
    """`json_handler` contains `_handler`, so banning that spelling bans the shim.

    Pinned because the forbidden-token table is the obvious place to add
    `_handler` when reading section 3's "no `_handler`" line, and doing so
    would refuse every branch on the day the sweep lands.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import (
        _FORBIDDEN_SHIM_TOKENS,
        _has_service_import,
    )

    assert "_handler" not in _FORBIDDEN_SHIM_TOKENS
    # Built here rather than read from the spec so this pin still runs on a
    # fresh checkout, where docs.local/ does not exist.
    shim = "from aipass.prax import json_handler\n_h = json_handler.for_module(__file__)\n"
    assert "_handler" in shim
    assert _has_service_import(shim, "prax") is True


def test_a_branch_without_a_citizen_template_grows_no_template_check(tmp_path):
    """Seventeen branches ship no template, so the check does not appear for them."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_template_handler

    branch = tmp_path / "mybranch"
    branch.mkdir()
    assert _check_template_handler(branch) is None


def test_the_citizen_template_is_judged_by_the_same_rule(tmp_path):
    """The file every newborn inherits is an audit subject, unrendered.

    Nothing audited it before DPLAN-0325: a template stamping a log-only fork
    would have minted eighteen non-compliant branches before any audit noticed,
    because the audit only ever walked branches.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _check_template_handler

    branch = tmp_path / "spawnish"
    template = branch / "templates" / "citizen" / "apps" / "handlers" / "json"
    template.mkdir(parents=True)
    handler = template / "json_handler.py"

    handler.write_text("def log_operation(op):\n    return True\n", encoding="utf-8")
    result = _check_template_handler(branch)
    assert result is not None
    assert result["passed"] is False
    assert "Log-only fork" in result["message"]

    handler.write_text(
        "from aipass.prax import json_handler\n_h = json_handler.for_module(__file__)\n", encoding="utf-8"
    )
    result = _check_template_handler(branch)
    assert result is not None
    assert result["passed"] is True


# ---------------------------------------------------------------------------
# Tests -- naming_check treats a bound alias as an alias, not a constant
# ---------------------------------------------------------------------------


def test_a_bound_alias_is_not_a_lowercase_constant():
    """`save_json = _h.save_json` names a callable; PEP 8 spells it lowercase.

    The shape DPLAN-0325 makes fleet-wide — nine per branch — and the reason
    canary, memory and spawn carried naming bypasses before this rule existed.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_constant_naming

    source = "save_json = _h.save_json\nInvalidDocument = json_handler.InvalidDocument\nMAX = 5\n"
    result = check_constant_naming(source)
    assert result is not None
    assert result["passed"] is True


def test_an_alias_with_a_trailing_comment_is_still_an_alias():
    """A `# noqa` after the value must not turn the alias back into a constant."""
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_constant_naming

    result = check_constant_naming("read_json = _h.read_json  # noqa: F401\nMAX = 5\n")
    assert result is not None
    assert result["passed"] is True


def test_the_alias_rule_does_not_excuse_an_expression_that_merely_contains_a_dot():
    """Only a BARE dotted name is an alias — the narrowing has an edge.

    Red-first: without the anchors on the pattern, every lowercase module-level
    assignment containing an attribute access would stop being checked, which
    is a far larger exemption than the one that was asked for.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.naming_check import check_constant_naming

    result = check_constant_naming("total = counters.seen + 1\nfirst = items.data[0]\n")
    assert result is not None
    assert result["passed"] is False
    assert "total" in result["message"]


# ---------------------------------------------------------------------------
# Tests -- json_structure does not convict a shim for delegating resolution
# ---------------------------------------------------------------------------


def test_a_shim_that_binds_the_service_resolves_nothing_and_says_so(tmp_path):
    """The canonical shim has no `Path(__file__)`, no `.resolve()`, no `.parent`.

    Measured 2026-09-03: prax's shim, spawn's shim and spawn's citizen template
    each scored 75 on this check the day they migrated, because path resolution
    moved INTO the service — which derives the branch root without `resolve()`
    on purpose, so a dead cwd on Windows cannot poison it. A standard that
    demands the spelling convicts the endpoint of the migration.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    handler = tmp_path / "apps" / "handlers" / "json" / "json_handler.py"
    handler.parent.mkdir(parents=True)
    handler.write_text(
        "from aipass.prax import json_handler\n\n_h = json_handler.for_module(__file__)\n\nread_json = _h.read_json\n",
        encoding="utf-8",
    )

    checks = check_module(str(handler), bypass_rules=None)["checks"]
    resolution = next(c for c in checks if c["name"] == "Relative path resolution")
    assert resolution["passed"] is True
    assert "Delegates path resolution" in resolution["message"]


def test_a_handler_that_neither_binds_nor_resolves_still_fails(tmp_path):
    """The accept is the service import, not an amnesty on the whole check."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import check_module

    handler = tmp_path / "apps" / "handlers" / "json" / "json_handler.py"
    handler.parent.mkdir(parents=True)
    handler.write_text("JSON_DIR = 'documents'\n\n\ndef read_json(name):\n    return {}\n", encoding="utf-8")

    checks = check_module(str(handler), bypass_rules=None)["checks"]
    resolution = next(c for c in checks if c["name"] == "Relative path resolution")
    assert resolution["passed"] is False
    assert "Missing relative path resolution" in resolution["message"]


def test_the_two_standards_read_one_copy_of_the_service_import_line():
    """Two literals of the same line is the drift this standard exists to catch."""
    from aipass.seedgo.apps.handlers.aipass_standards import json_handler_check, json_structure_check

    assert json_structure_check.SERVICE_IMPORT_MARKER is json_handler_check.SERVICE_IMPORT_MARKER
