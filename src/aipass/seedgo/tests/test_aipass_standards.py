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
