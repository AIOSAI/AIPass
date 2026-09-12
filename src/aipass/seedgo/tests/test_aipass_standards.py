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


def _canonical_shim_bytes_on_disk():
    """The canonical shim from the citizen template, verified against the pin.

    A second source, and deliberately a different one from
    :func:`_canonical_shim_bytes_or_skip`. That one reads the spec, which is
    gitignored and therefore absent on CI. This one reads the file every
    newborn branch is stamped from, which ships in the repo — so the pins that
    need REAL canonical bytes still run on a fresh checkout.

    Reading a branch copy would teach a test that branch's drift, so the bytes
    are checked against ``CANONICAL_SHIM_SHA256`` before being handed back:
    if the template ever drifts, these pins say so instead of blessing it.
    """
    import hashlib
    from pathlib import Path as _Path

    import aipass

    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import CANONICAL_SHIM_SHA256

    template = (
        _Path(aipass.__file__).resolve().parent
        / "spawn"
        / "templates"
        / "citizen"
        / "apps"
        / "handlers"
        / "json"
        / "json_handler.py"
    )
    if not template.is_file():
        pytest.skip(f"citizen template not present ({template})")
    content = template.read_text(encoding="utf-8")
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == CANONICAL_SHIM_SHA256, (
        "the citizen template is no longer the canonical shim — every branch spawned from it "
        "would be born failing the json_handler standard"
    )
    return content


def test_the_canonical_shim_passes_capability_by_hash():
    """The spec's own bytes are accepted, and accepted on the identity path."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _capability_verdict

    passed, message = _capability_verdict(_canonical_shim_bytes_or_skip(), "anybranch")
    assert passed is True
    assert "sha256" in message


def test_one_changed_character_is_no_longer_the_canonical_shim():
    """Identity, not resemblance: a shim that drifts stops being the shim.

    Red-first proof that the hash path is doing the work — one extra space,
    nothing else. Until part B this only pinned WHICH path answered, because
    the mutated text still imported the service and fell through to the
    transitional read. That read is gone (2026-09-04, section 4), so the
    mutation is now REFUSED outright, which is the whole point of narrowing:
    a byte of drift is a red, not a quieter green.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import (
        _capability_verdict,
        _is_canonical_shim,
    )

    mutated = _canonical_shim_bytes_or_skip().replace("_h = json_handler.for_module", "_h  = json_handler.for_module")
    assert _is_canonical_shim(mutated) is False
    passed, message = _capability_verdict(mutated, "anybranch")
    assert passed is False
    assert "sha256" in message


def test_a_half_migrated_shim_that_kept_a_branch_token_is_refused():
    """A branch that adopts the import and keeps its own directory is not migrated.

    The failure this forbids is a file that reads as migrated — it has the
    import line at the top — while still writing through a binding of its own.
    It used to be caught by a table of forbidden tokens consulted on the
    transitional accept path. That path and that table are gone (part B
    section 4); the hash refuses this text for the simpler reason that it is
    not the shim's bytes, and cannot be argued with about which tokens count.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import _capability_verdict

    half = "from aipass.prax import json_handler\n_JSON_DIR = _ROOT / 'canary_json'\n"
    passed, message = _capability_verdict(half, "canary")
    assert passed is False
    assert "canary" in message


def test_the_refusal_message_names_the_branch_and_the_line_to_write():
    """A red a branch cannot act on is a red that stays.

    The hash says nothing on its own — "sha256 mismatch" tells a reader
    nothing about what to do. The refusal has to carry the branch, the fact
    that there is ONE implementation, and the import line the replacement
    starts with, because that is the entire remedy.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_handler_check import (
        SERVICE_IMPORT_MARKER,
        _capability_verdict,
    )

    passed, message = _capability_verdict("def load_json(name):\n    return {}\n", "canary")
    assert passed is False
    assert "canary" in message
    assert SERVICE_IMPORT_MARKER in message


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
    assert "Not the canonical json shim" in result["message"]

    # The REAL bytes, not a hand-written lookalike. Since part B section 4 the
    # only accept path is the hash, so a two-line stand-in that merely imports
    # the service is refused here exactly as it would be in a branch.
    handler.write_text(_canonical_shim_bytes_on_disk(), encoding="utf-8")
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
    # The REAL bytes. This used to be a hand-written four-line stand-in, which
    # the marker read accepted; part B section 4 moved the exemption onto the
    # hash test (finding (a)), so only the shim itself earns it now.
    handler.write_text(_canonical_shim_bytes_on_disk(), encoding="utf-8")

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


def test_the_two_standards_share_the_shim_TEST_not_a_copy_of_a_string():
    """Both standards must agree on what a shim IS, by running the same function.

    json_structure_check excuses a shim from "resolves its own path" — the
    service derives the branch root from the shim's __file__ and the shim
    resolves nothing. Until part B the two standards agreed by importing one
    copy of a marker STRING. They now import one copy of the hash TEST, which
    is strictly stronger: a string can be true of a file that is not the shim.

    Measured 2026-09-04 (finding (a)): if part B had removed the marker
    without giving structure the hash test in its place, all eighteen branches
    and the citizen template would have dropped 100 -> 75 on their handler
    file. The identity assertion below is what makes that impossible to redo
    by accident.
    """
    from aipass.seedgo.apps.handlers.aipass_standards import json_handler_check, json_structure_check

    assert json_structure_check._is_canonical_shim is json_handler_check._is_canonical_shim


# ---------------------------------------------------------------------------
# Tests -- json_structure recognises a branch-owned operation-logging seam
# ---------------------------------------------------------------------------


def _seam_branch(tmp_path, seam_body: str | None = None):
    """A branch whose audit trail lives in its own module, built on prax.

    Shaped like the real tree — ``<root>/aipass/<branch>/apps/...`` beside a
    ``prax/`` directory — because the seam lookup resolves the branch from the
    file's own path, exactly as it must on disk.
    """
    (tmp_path / "aipass" / "prax").mkdir(parents=True)
    seam = tmp_path / "aipass" / "backupish" / "apps" / "handlers" / "audit" / "trail.py"
    seam.parent.mkdir(parents=True)
    seam.write_text(
        seam_body
        or (
            "from aipass.prax import append_jsonl\n\n\n"
            "def log_operation(operation, data):\n    append_jsonl(operation, data)\n"
        ),
        encoding="utf-8",
    )
    return seam


def test_a_module_logging_through_the_branch_seam_is_wired(tmp_path):
    """@backup moved 67 audit calls off the shim per the spec, as ordered.

    The old check was a literal substring test for 'json_handler.log_operation'
    and convicted 41 of backup's 43 files for obeying it. Recognised, never
    bypassed: backup will not carry a bypass for following the spec.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_code_wiring

    seam = _seam_branch(tmp_path)
    module = seam.parents[3] / "modules" / "snapshot.py"
    module.parent.mkdir(parents=True)
    source = "from ..handlers.audit import trail\n\n\ndef run():\n    trail.log_operation('snapshot', {})\n"
    module.write_text(source, encoding="utf-8")

    checks = _check_code_wiring(module, source)
    assert all(c["passed"] for c in checks)
    assert any("trail seam" in c["message"] for c in checks)


def test_the_seam_itself_does_not_have_to_log_through_itself(tmp_path):
    """The substrate is not a consumer of the substrate."""
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_code_wiring

    seam = _seam_branch(tmp_path)
    checks = _check_code_wiring(seam, seam.read_text(encoding="utf-8"))
    assert all(c["passed"] for c in checks)


def test_calling_log_operation_on_something_that_is_not_a_seam_earns_nothing(tmp_path):
    """The narrowing has an edge: a same-named helper is not a logging seam.

    Red-first — without the two conditions (defines log_operation AND builds it
    on aipass.prax) any module could name a local object `trail` and claim the
    exemption, which is a far wider waiver than the one backup needs.
    """
    from aipass.seedgo.apps.handlers.aipass_standards.json_structure_check import _check_code_wiring

    fake = _seam_branch(tmp_path, "def log_operation(operation, data):\n    print(operation)\n")

    module = fake.parents[3] / "modules" / "snapshot.py"
    module.parent.mkdir(parents=True)
    source = "from ..handlers.audit import trail\n\n\ndef run():\n    trail.log_operation('snapshot', {})\n"
    module.write_text(source, encoding="utf-8")

    checks = _check_code_wiring(module, source)
    assert not all(c["passed"] for c in checks)


# ---------------------------------------------------------------------------
# RETIRED 2026-09-07 (FPLAN-0491) -- the v4 test_quality sections.
#
# Two sections lived here: "v4 test_quality retires the handler's items"
# (DPLAN-0325 part B) and "an item is only scored where the branch ships a
# subject for it". Both imported test_quality_check, which moved to
# apps/handlers/aipass_standards/.archive/ when Patrick sealed DPLAN-0323.
# A test whose subject is archived cannot go red; it can only ImportError.
# Verbatim disposal copy: tests/.archive/deleted_2026-09-07_test_quality_v4.py
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Tests -- host_portability_check (HOST_PORTABILITY)
#
# Every fixture below is a minimised reproduction of a REAL fleet site, named
# in its docstring. Synthetic rather than live-file pins on purpose: a pin on
# `drone path_resolver.py:135` goes red the next time drone adds a line above
# it, which teaches the fleet to delete the pin. The shape is what the rule
# reads, so the shape is what is pinned; the live file:line list is produced by
# running the checker across the registry and lives in host_portability.md.
# ---------------------------------------------------------------------------


def _scan_source(tmp_path, source, name="sample.py"):
    """Write *source* to a file and return (violations, acquitted_binary_sites)."""
    from aipass.seedgo.apps.handlers.aipass_standards import host_portability_check

    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return host_portability_check.scan_file(str(target))


def _lines(violations):
    """Just the line numbers, which is what every pin below actually claims."""
    return [lineno for lineno, _ in violations]


def test_host_portability_declares_the_branch_level_contract():
    """AUDIT_SCOPE and the entry point the audit pipeline dispatches on.

    branch_level, not all_files: the per-file lane's corpus is apps/ only, and
    this standard's whole reason for existing is that tests/ broke macOS CI.
    """
    from aipass.seedgo.apps.handlers.aipass_standards import host_portability_check

    assert host_portability_check.AUDIT_SCOPE == "branch_level"
    assert callable(host_portability_check.check_branch)


def test_a_clean_branch_scores_100_and_reports_the_file_count(tmp_path):
    """check_branch returns the pack's dict shape: passed/checks/score/standard."""
    from aipass.seedgo.apps.handlers.aipass_standards import host_portability_check

    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "clean.py").write_text("import os\n\n\ndef where():\n    return os.getcwd()\n", encoding="utf-8")

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["standard"] == "HOST_PORTABILITY"
    assert result["score"] == 100
    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_a_branch_with_one_dirty_file_scores_by_clean_file_share(tmp_path):
    """Score is clean/total x 100 -- the number the all_files lane averages to.

    Two files, one of them running tmux bare: 50, not 0 and not 99.
    """
    from aipass.seedgo.apps.handlers.aipass_standards import host_portability_check

    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "clean.py").write_text("def ok():\n    return 1\n", encoding="utf-8")
    (apps / "dirty.py").write_text(
        'import subprocess\n\n\ndef kill(name):\n    subprocess.run(["tmux", "kill-session", "-t", name])\n',
        encoding="utf-8",
    )

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["score"] == 50
    failing = [c for c in result["checks"] if not c["passed"]]
    assert len(failing) == 1
    assert failing[0]["violations"][0]["file"] == "apps/dirty.py"


# -- ARM B: assumed non-portable binary --------------------------------------


def test_tmux_kill_session_with_check_false_is_convicted(tmp_path):
    """hooks session_boot.py:248, :313 and :1078 -- the fleet's three tmux bugs.

    check=False is the trap this pin exists for. A missing binary raises
    FileNotFoundError out of exec, BEFORE there is an exit code to ignore, so
    check=False suppresses nothing at all.
    """
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def stop(session):\n"
        '    subprocess.run(["tmux", "kill-session", "-t", session], check=False)\n'
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert _lines(violations) == [5]
    assert "tmux" in violations[0][1]
    assert acquitted == 0


def test_systemctl_enable_with_no_guard_is_convicted(tmp_path):
    """trigger service_control.py:82 -- systemctl --user enable, bare.

    The sibling at :101 in the same file wraps the identical call in
    `except Exception` and acquits; only this one is naked.
    """
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def install(unit):\n"
        '    subprocess.run(["systemctl", "--user", "enable", unit], timeout=10)\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [5]
    assert "systemctl" in violations[0][1]


def test_a_which_probe_in_the_same_function_acquits_the_binary(tmp_path):
    """aipass handoff_platform launch_tmux -- shutil.which('tmux') then run it.

    Function-scoped on purpose. hooks session_boot HAS a `shutil.which("tmux")`
    at module line 90, inside a different function, and its three bare calls
    must still convict.
    """
    source = (
        "import shutil\n"
        "import subprocess\n"
        "\n"
        "\n"
        "def launch(session):\n"
        '    if not shutil.which("tmux"):\n'
        "        return False\n"
        '    subprocess.run(["tmux", "new-session", "-d", "-s", session])\n'
        "    return True\n"
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 1


def test_a_filenotfounderror_handler_acquits_the_binary(tmp_path):
    """daemon tests/conftest.py:90 -- systemctl inside except FileNotFoundError.

    Counted as context in a passed check line, never scored: about two dozen
    fleet sites are already written this way and convicting them would teach
    the fleet to switch the rule off.
    """
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def ask(*args):\n"
        "    try:\n"
        '        return subprocess.run(["systemctl", "--user", *args], timeout=15)\n'
        "    except (FileNotFoundError, OSError):\n"
        "        return None\n"
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 1


def test_platform_dispatch_into_a_variable_argv0_is_not_convicted(tmp_path):
    """hooks apps/sound.py -- afplay on darwin, aplay otherwise, run from a var.

    190 of the fleet's 374 subprocess sites spell argv[0] dynamically and that
    spelling is usually the CURE. A rule that guessed at dynamic argv[0] would
    convict this file, which is the correct answer written correctly.
    """
    source = (
        "import subprocess\n"
        "import sys\n"
        "\n"
        'if sys.platform == "darwin":\n'
        '    _PLAY_CMD = ["afplay"]\n'
        "else:\n"
        '    _PLAY_CMD = ["aplay", "-q"]\n'
        "\n"
        "\n"
        "def play(path):\n"
        "    subprocess.Popen(_PLAY_CMD + [str(path)])\n"
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 0


def test_a_portable_binary_is_never_read(tmp_path):
    """git/bash/gh and nine more carry 134 fleet sites and zero known bugs."""
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def head():\n"
        '    subprocess.run(["git", "rev-parse", "HEAD"])\n'
        '    subprocess.run(["gh", "pr", "list"])\n'
        '    subprocess.run(["bash", "-c", "echo hi"])\n'
    )

    violations, acquitted = _scan_source(tmp_path, source)

    assert violations == []
    assert acquitted == 0


# -- ARM A: /proc as a filesystem argument -----------------------------------


def test_the_openat2_twin_acquits_and_the_walk_fallback_convicts(tmp_path):
    """drone path_resolver.py -- :101 acquitted, :135 convicted. The one-hop pair.

    Both functions read the same Linux-only path 34 lines apart. The openat2
    one is reached only from `if _openat2_available():`, and that predicate
    returns `sys.platform == "linux" and ...`. The walk one is the NON-Linux
    fallback -- it runs precisely when the platform is not Linux, and then
    reads a filesystem only Linux has. That is the fleet's one genuine product
    bug of this class, and without the caller hop it is one row of noise
    beside its own guarded twin.
    """
    source = (
        "import os\n"
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def _openat2_available():\n"
        '    return sys.platform == "linux" and os.uname().machine == "x86_64"\n'
        "\n"
        "\n"
        "def resolve(base, cleaned, parts):\n"
        "    if _openat2_available():\n"
        "        return _via_openat2(base, cleaned)\n"
        "    return _via_walk(base, parts)\n"
        "\n"
        "\n"
        "def _via_openat2(base, cleaned):\n"
        "    fd = os.open(str(base), os.O_RDONLY)\n"
        '    return Path(os.readlink(f"/proc/self/fd/{fd}"))\n'
        "\n"
        "\n"
        "def _via_walk(base, parts):\n"
        "    fd = os.open(str(base), os.O_RDONLY)\n"
        '    return Path(os.readlink(f"/proc/self/fd/{fd}"))\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [23]
    assert "Linux-only" in violations[0][1]


def test_a_proc_read_in_a_pty_gated_class_is_still_convicted(tmp_path):
    """api tests/test_host_attach.py:912 and :919 -- @pty_required is not a guard.

    The class carries `pty_required = pytest.mark.skipif(not is_available(),
    ...)`, which probes for a PTY. macOS HAS a PTY, so the unit runs there and
    then calls os.listdir on a filesystem macOS does not have. The predicate
    has to name a platform to acquit, and this one names a capability.
    """
    source = (
        "import os\n"
        "import pytest\n"
        "\n"
        "pty_required = pytest.mark.skipif(not _is_available(), reason='needs a pty')\n"
        "\n"
        "\n"
        "@pty_required\n"
        "class TestOpeningAnAttach:\n"
        "    def test_no_descriptor_leak(self):\n"
        '        before = len(os.listdir("/proc/self/fd"))\n'
        '        assert len(os.listdir("/proc/self/fd")) <= before + 1\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_host.py")

    assert _lines(violations) == [10, 11]


def test_a_module_level_skipif_alias_acquits_a_proc_read(tmp_path):
    """aipass tests/test_doctor.py:249 -- `_posix_only` bound once, used as @.

    17+ guards fleet-wide are spelled this way. A reader that only understands
    the inline `@pytest.mark.skipif(...)` form convicts every one of them, and
    a rule with that acquittal rate is off within a week.
    """
    source = (
        "import os\n"
        "import pytest\n"
        "from pathlib import Path\n"
        "\n"
        "_posix_only = pytest.mark.skipif(os.name == 'nt', reason='forces posix')\n"
        "\n"
        "\n"
        "@_posix_only\n"
        "def test_parent_comm():\n"
        '    assert Path(f"/proc/{os.getppid()}/comm").read_text(encoding="utf-8")\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_doctor_like.py")

    assert violations == []


def test_a_proc_path_used_as_a_mock_dict_key_is_not_convicted(tmp_path):
    """ai_mail tests/test_wake.py:337 and :348 -- a dict key opens nothing.

    The argument restriction is the whole rule. This literal is a key in a
    lookup table handed to a fake-open factory; no filesystem is touched, on
    any host, ever.
    """
    source = (
        "def test_is_zombie(monkeypatch, tmp_path):\n"
        '    status_file = tmp_path / "status"\n'
        '    status_file.write_text("State:\\tS\\n")\n'
        "    monkeypatch.setattr(\n"
        '        "builtins.open",\n'
        '        _fake_open_factory(str(status_file), {"/proc/42/status": str(status_file)}),\n'
        "    )\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_wake_like.py")

    assert violations == []


def test_the_prose_of_a_skipif_reason_is_not_convicted(tmp_path):
    """devpulse tests/test_watchdog_wire.py:738, prax tests/test_instance_lock.py:172.

    The literal IS the guard's own explanation. Convicting a rule's cure for
    describing itself is how a standard gets switched off.
    """
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="/proc is Linux-only")\n'
        "def test_reads_proc_truth():\n"
        "    assert True\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_wire_like.py")

    assert violations == []


def test_a_proc_argv_element_is_not_convicted(tmp_path):
    """aipass sandbox_checker.py:71 -- `--proc /proc` is an argv pair for bwrap.

    Not a path this caller opens: bwrap mounts it inside a namespace it
    creates. The FS-argument rule never nominates it.
    """
    source = (
        "import subprocess\n"
        "\n"
        "\n"
        "def probe(bwrap):\n"
        '    subprocess.run([bwrap, "--dev", "/dev", "--proc", "/proc", "true"], check=False)\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_platform_test_in_the_enclosing_function_acquits_a_proc_read(tmp_path):
    """hooks cc_sessions.py:163 -- `if sys.platform != "linux": return None`."""
    source = (
        "import sys\n"
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def start_ticks(pid):\n"
        '    if sys.platform != "linux":\n'
        "        return None\n"
        '    return Path(f"/proc/{pid}/stat").read_text(encoding="utf-8")\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_an_oserror_handler_acquits_a_proc_read(tmp_path):
    """devpulse watchdog/wire.py:275 -- the missing file is a handled fact."""
    source = (
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def cmdline(pid):\n"
        "    try:\n"
        '        return Path(f"/proc/{pid}/cmdline").read_bytes()\n'
        "    except OSError:\n"
        '        return b""\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_an_existence_early_out_acquits_a_proc_read(tmp_path):
    """aipass system_detector.py:172 -- `if not meminfo.exists(): return 0`.

    The guard sits BELOW the literal, which is why the existence check is read
    over the whole function rather than only the lines above the read.
    """
    source = (
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def read_meminfo_kb():\n"
        '    meminfo = Path("/proc/meminfo")\n'
        "    if not meminfo.exists():\n"
        "        return 0\n"
        '    return int(meminfo.read_text(encoding="utf-8").split()[1])\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_bare_proc_string_that_never_reaches_the_filesystem_is_not_convicted(tmp_path):
    """seedgo platform_oracle_check.py:187 -- a prefix in a tuple of constants."""
    source = 'DEVICE_PATH_PREFIXES = ("/dev/null/", "/proc/", "/sys/")\n'

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []
