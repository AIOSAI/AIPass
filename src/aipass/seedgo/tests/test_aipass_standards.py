# =================== META ====================
# Name: test_aipass_standards.py
# Description: Unit tests for handlers/aipass_standards/
# Version: 1.5.0
# Created: 2026-03-24
# Modified: 2026-10-27
# =============================================

"""Tests for apps/handlers/aipass_standards/naming_check.py and its json, host and calendar siblings."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(shared) — the other checkers in aipass_standards/; each has its own test file
# seedgo: no-test-needed(constant) — the guidance prose in each *_content.py; only its doctrine lines are read
# seedgo: no-test-needed(stdlib) — ast.parse's parsing; the checkers only walk the tree it returns

import pytest
from unittest.mock import MagicMock

import aipass
from aipass.seedgo.apps.handlers.aipass_standards import calendar_bound_check
from aipass.seedgo.apps.handlers.aipass_standards import check_support
from aipass.seedgo.apps.handlers.aipass_standards import host_coupled_oracle_check
from aipass.seedgo.apps.handlers.aipass_standards import host_portability_check
from aipass.seedgo.apps.handlers.aipass_standards import json_handler_check
from aipass.seedgo.apps.handlers.aipass_standards import json_structure_check
from aipass.seedgo.apps.handlers.aipass_standards import json_structure_content
from aipass.seedgo.apps.handlers.aipass_standards import naming_check
from aipass.seedgo.apps.handlers.bypass import utils as _bypass_utils


@pytest.fixture(autouse=True)
def _pin_bypass_log(monkeypatch):
    """Point is_bypassed's json_handler at a mock for every test here.

    is_bypassed appends to the tracked seedgo_json/utils_log.json via its own module's json_handler;
    xdist races corrupt it.
    """
    mock_handler = MagicMock()
    mock_handler.log_operation = MagicMock(return_value=True)
    monkeypatch.setattr(_bypass_utils, "json_handler", mock_handler)


def test_naming_check_module_returns_dict(tmp_path):
    """A clean snake_case file scores 100 and passes. Mutant: score counts failed checks in naming_check.py — killed."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample module."""\n\ndef my_function():\n    pass\n',
        encoding="utf-8",
    )

    result = naming_check.check_module(str(py_file))
    assert isinstance(result, dict)
    assert "passed" in result
    assert "checks" in result
    assert "score" in result
    assert result["passed"] is True
    assert [check["passed"] for check in result["checks"]] == [True, True]
    assert result["score"] == 100


def test_naming_check_module_missing_file(tmp_path):
    """A missing file fails at 0, saying so. Mutant: missing file reported passed in naming_check.py — killed."""

    result = naming_check.check_module(str(tmp_path / "nonexistent" / "path" / "file.py"))
    assert isinstance(result, dict)
    assert result["passed"] is False
    assert result["score"] == 0
    assert result["checks"][0]["message"].startswith("File not found:")


def test_naming_check_module_with_bypass(tmp_path):
    """naming_check.check_module respects bypass rules."""
    py_file = tmp_path / "sample.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    bypass = [{"file": "sample.py", "standard": "naming", "reason": "test"}]
    result = naming_check.check_module(str(py_file), bypass_rules=bypass)
    assert isinstance(result, dict)
    assert result["passed"] is True


def test_json_structure_check_returns_expected_keys(tmp_path):
    """A file outside modules/ and handlers/ is declined at 100."""
    py_file = tmp_path / "sample.py"
    py_file.write_text(
        '"""Sample."""\nimport json\n',
        encoding="utf-8",
    )

    result = json_structure_check.check_module(str(py_file))
    assert isinstance(result, dict)
    assert result["passed"] is True
    assert result["score"] == 100
    assert [check["message"] for check in result["checks"]] == ["Not in modules/ or handlers/ (not applicable)"]


def test_json_structure_check_missing_file(tmp_path):
    """A missing file fails at 0. Mutant: missing file reported passed in json_structure_check.py — killed."""

    result = json_structure_check.check_module(str(tmp_path / "nonexistent" / "module.py"))
    assert isinstance(result, dict)
    assert result["passed"] is False
    assert result["score"] == 0


def test_json_structure_check_has_standard_field(tmp_path):
    """json_structure_check.check_module includes 'standard' in output."""
    py_file = tmp_path / "test_mod.py"
    py_file.write_text("x = 1\n", encoding="utf-8")

    result = json_structure_check.check_module(str(py_file))
    assert "standard" in result


def test_json_structure_custom_config_subdir_passes(tmp_path):
    """Branch with {branch}_json/custom_config/ passes directory check."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    cc = json_dir / "custom_config"
    cc.mkdir()
    (cc / "settings.json").write_text("{}", encoding="utf-8")
    (json_dir / "config.json").write_text("{}", encoding="utf-8")

    violations = json_structure_check.check_branch_post(str(branch))[0]
    assert violations == []


def test_json_structure_random_subdir_fails(tmp_path):
    """Branch with an unsanctioned subdir under {branch}_json/ is flagged."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "custom_config").mkdir()
    (json_dir / "extra_stuff").mkdir()

    violations = json_structure_check.check_branch_post(str(branch))[0]
    assert len(violations) == 1
    assert "extra_stuff" in violations[0]["message"]


def test_json_structure_hidden_subdir_ignored(tmp_path):
    """Hidden subdirs (e.g. .archive) under {branch}_json/ are not flagged."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / ".archive").mkdir()

    violations = json_structure_check.check_branch_post(str(branch))[0]
    assert violations == []


def test_json_structure_no_json_dir_passes(tmp_path):
    """Branch with no {branch}_json/ directory produces no violations."""

    branch = tmp_path / "mybranch"
    branch.mkdir()

    assert json_structure_check.check_branch_post(str(branch)) == ([], [])


def test_json_handler_wiring_named_only_in_a_docstring_is_not_wiring(tmp_path):
    """A docstring that names the import and the call wires nothing."""
    module = tmp_path / "apps" / "modules" / "mod.py"
    module.parent.mkdir(parents=True)
    module.write_text(
        '"""Use: from aipass.x.apps.handlers.json import json_handler; json_handler.log_operation(...)"""\n'
        "def run():\n    return 1\n",
        encoding="utf-8",
    )
    checks = json_structure_check.check_module(str(module))["checks"]
    assert [c["passed"] for c in checks] == [False, False]


def test_json_structure_check_branch_post(tmp_path):
    """check_branch_post returns violations and scores."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "bad_split").mkdir()

    violations, scores = json_structure_check.check_branch_post(str(branch))
    assert len(violations) == 1
    assert scores == [0]

    (json_dir / "bad_split").rmdir()
    (json_dir / "custom_config").mkdir()
    violations2, scores2 = json_structure_check.check_branch_post(str(branch))
    assert violations2 == []
    assert scores2 == [100]


def test_json_structure_bypassed_subdir_passes(tmp_path):
    """A subdir bypassed via bypass_rules is not flagged."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "compass").mkdir()

    bypass_rules = [{"standard": "json_structure", "file": "mybranch_json/compass", "reason": "test"}]
    violations = json_structure_check.check_branch_post(str(branch), bypass_rules=bypass_rules)[0]
    assert violations == []


def test_json_structure_unbypassed_subdir_still_fails(tmp_path):
    """An unsanctioned subdir without a bypass entry is still flagged."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    json_dir = branch / "mybranch_json"
    json_dir.mkdir()
    (json_dir / "compass").mkdir()
    (json_dir / "random_dir").mkdir()

    bypass_rules = [{"standard": "json_structure", "file": "mybranch_json/compass", "reason": "test"}]
    violations = json_structure_check.check_branch_post(str(branch), bypass_rules=bypass_rules)[0]
    assert len(violations) == 1
    assert "random_dir" in violations[0]["message"]


def test_naming_is_bypassed_true():
    """is_bypassed returns True when rule matches."""

    rules = [{"file": "foo.py", "standard": "naming", "reason": "legacy"}]
    assert naming_check.is_bypassed("some/path/foo.py", "naming", bypass_rules=rules) is True


def test_naming_is_bypassed_false_no_rules():
    """is_bypassed returns False with no rules."""

    assert naming_check.is_bypassed("foo.py", "naming", bypass_rules=None) is False


def test_naming_is_bypassed_wrong_standard():
    """is_bypassed returns False when standard does not match."""

    rules = [{"file": "foo.py", "standard": "imports", "reason": "legacy"}]
    assert naming_check.is_bypassed("foo.py", "naming", bypass_rules=rules) is False


def _custom_config_doctrine_text():
    """Just the custom_config house-pattern section, lowercased.

    Sliced so a generic word cannot pass from an unrelated paragraph after the doctrine block is deleted.
    """
    full = json_structure_content.get_json_structure_standards()
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
    """The one sentence that decides whether a snapshot writer is legal."""
    text = _custom_config_doctrine_text()

    assert "code never writes into custom_config/ outside that regeneration path" in text
    assert "snapshot overwrites" in text


def test_doctrine_states_merge_direction():
    """Deep-merge is only correct in one direction: file over seed."""
    text = _custom_config_doctrine_text()

    assert "deep-merge" in text
    assert "file over seed" in text
    # Seed-over-file would silently undo every operator edit on a key the seed also carries.
    assert "seed over file" not in text


def test_doctrine_does_not_carry_the_reversed_never_snapshot_rule():
    """The pre-S193 doctrine said the opposite; it must not creep back."""
    text = _custom_config_doctrine_text()

    assert "never self-heal-write" not in text
    assert "holds only overrides" not in text
    # Missing now regenerates: "missing file = defaults" is the reversed rule.
    assert "missing file = defaults" not in text


def test_doctrine_keeps_six_key_drift_as_seed_lesson():
    """The @memory drift story stays, reframed as why the SEED must stay aligned."""
    text = _custom_config_doctrine_text()

    assert "6 keys" in text
    # Stale seed regenerates stale truth, not "files can't hold config".
    assert "stale seed regenerates stale truth" in text


def test_doctrine_omits_queued_quarantine_upgrade():
    """Quarantine-then-regenerate is queued behind the medic digest, not current."""
    text = _custom_config_doctrine_text()

    assert "quarantine" not in text


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

    branch = tmp_path / "mybranch"
    branch.mkdir()

    assert json_structure_check.check_branch_info(str(branch)) == []


def test_custom_config_info_no_custom_config_dir(tmp_path):
    """A branch_json/ without custom_config/ produces no info line."""

    branch = tmp_path / "mybranch"
    (branch / "mybranch_json").mkdir(parents=True)

    assert json_structure_check.check_branch_info(str(branch)) == []


def test_custom_config_info_readme_only(tmp_path):
    """custom_config/ holding only README.md is scaffolding, not an override."""

    branch = _branch_with_custom_config(tmp_path, ["README.md"])

    assert json_structure_check.check_branch_info(str(branch)) == []


def test_custom_config_info_lists_operator_files(tmp_path):
    """Operator files are named, counted, and carry the guide pointer."""
    branch = _branch_with_custom_config(tmp_path, ["README.md", "cadence_config.json", "alpha_config.json"])

    lines = json_structure_check.check_branch_info(str(branch))
    assert len(lines) == 1
    line = lines[0]
    assert "mybranch_json/custom_config/" in line
    assert "2 operator files" in line
    assert "alpha_config.json, cadence_config.json" in line
    assert "README.md" not in line
    assert "content not audited" in line
    # Track the constant, not a copy of it — test_standards_query proves the
    # constant names a command that actually resolves.
    assert json_structure_check.CUSTOM_CONFIG_GUIDE in line


def test_custom_config_info_singular_wording(tmp_path):
    """One override reads 'file', not 'files'."""

    branch = _branch_with_custom_config(tmp_path, ["memory.config.json"])

    assert "1 operator file (" in json_structure_check.check_branch_info(str(branch))[0]


def test_custom_config_info_ignores_subdirs(tmp_path):
    """Directories inside custom_config/ are not listed as operator files."""

    branch = _branch_with_custom_config(tmp_path, [])
    (branch / "mybranch_json" / "custom_config" / "nested").mkdir()

    assert json_structure_check.check_branch_info(str(branch)) == []


def test_custom_config_never_affects_score(tmp_path):
    """Operator files in custom_config/ leave check_branch_post at a clean 100."""

    branch = _branch_with_custom_config(tmp_path, ["cadence_config.json"])

    violations, scores = json_structure_check.check_branch_post(str(branch))
    assert violations == []
    assert scores == [100]


def _branch_with_json_files(tmp_path, filenames):
    """Build a branch whose {branch}_json/ holds filenames."""
    branch = tmp_path / "mybranch"
    json_dir = branch / "mybranch_json"
    json_dir.mkdir(parents=True)
    for name in filenames:
        (json_dir / name).write_text("{}", encoding="utf-8")
    return branch


def _triplet_check(branch, bypass_rules=None):
    """The disk-triplet check exactly as the public check_branch reports it."""
    result = json_handler_check.check_branch(str(branch), bypass_rules=bypass_rules)
    [check] = [check for check in result["checks"] if check["name"] == "Disk triplet completeness"]
    return check


def test_disk_triplets_no_json_dir(tmp_path):
    """No {branch}_json/ directory passes (no JSON activity)."""

    branch = tmp_path / "mybranch"
    branch.mkdir()

    result = _triplet_check(branch)
    assert result["passed"] is True


def test_disk_triplets_complete(tmp_path):
    """A full config/data/log trio passes."""

    branch = _branch_with_json_files(tmp_path, ["audit_config.json", "audit_data.json", "audit_log.json"])

    result = _triplet_check(branch)
    assert result["passed"] is True
    assert "All 1 modules" in result["message"]


def test_disk_triplets_config_without_log_is_caught(tmp_path):
    """A hand-written config with no log sibling is no longer invisible."""

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json"])

    result = _triplet_check(branch)
    assert result["passed"] is False
    assert "trigger (missing data, log)" in result["message"]


def test_disk_triplets_data_without_siblings_is_caught(tmp_path):
    """A lone data file implies its config and log must exist."""

    branch = _branch_with_json_files(tmp_path, ["solo_data.json"])

    result = _triplet_check(branch)
    assert result["passed"] is False
    assert "solo (missing config, log)" in result["message"]


def test_disk_triplets_log_without_config_still_caught(tmp_path):
    """The original log-first direction keeps working."""

    branch = _branch_with_json_files(tmp_path, ["audit_log.json", "audit_data.json"])

    result = _triplet_check(branch)
    assert result["passed"] is False
    assert "audit (missing config)" in result["message"]


def test_disk_triplets_ignores_non_triplet_files(tmp_path):
    """Files outside the {stem}_{kind}.json shape are not modules."""

    branch = _branch_with_json_files(tmp_path, ["audit_cache.json", "config.json", "registry.json"])

    result = _triplet_check(branch)
    assert result["passed"] is True
    assert "no triplet files" in result["message"]


def test_disk_triplets_bypass_respected(tmp_path):
    """A bypassed missing member does not fail the branch."""

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json", "trigger_data.json"])
    rules = [
        {
            "file": "mybranch_json/trigger_log.json",
            "standard": "json_handler",
            "reason": "config-only module, no operations to log",
        }
    ]

    result = _triplet_check(branch, bypass_rules=rules)
    assert result["passed"] is True


def test_disk_triplets_bypass_wrong_standard_ignored(tmp_path):
    """A bypass for another standard does not suppress a triplet gap."""

    branch = _branch_with_json_files(tmp_path, ["trigger_config.json", "trigger_data.json"])
    rules = [{"file": "mybranch_json/trigger_log.json", "standard": "json_structure", "reason": "unrelated"}]

    result = _triplet_check(branch, bypass_rules=rules)
    assert result["passed"] is False


def test_disk_triplets_multiple_gaps_counted(tmp_path):
    """The message counts incomplete modules against total modules found."""

    branch = _branch_with_json_files(
        tmp_path,
        ["a_config.json", "a_data.json", "a_log.json", "b_config.json", "c_log.json"],
    )

    result = _triplet_check(branch)
    assert result["passed"] is False
    assert result["message"].startswith("2/3 modules missing triplet files")


def _canonical_shim_bytes_or_skip():
    """The canonical shim as the pinned spec defines it, or skip saying why.

    A constant taught by a branch copy would bless that branch's drift. docs.local/ is gitignored, so the spec
    is absent on a fresh checkout: this skips naming the path rather than degrade silently.
    """
    import re
    from pathlib import Path

    # From the installed package, so the read is identical whichever rootdir pytest picks.
    spec = Path(aipass.__file__).resolve().parent / "devpulse" / "docs.local" / "DPLAN-0325_spec.md"
    if not spec.is_file():
        pytest.skip(f"pinned spec not present ({spec}) — docs.local/ is gitignored, so this pin is local-only")
    text = spec.read_text(encoding="utf-8")
    section = text.index("## 3. The shim")
    block = re.search(r"```python\n(.*?)\n```", text[section:], re.S)
    assert block is not None, "DPLAN-0325 section 3 no longer carries a python block"
    return block.group(1) + "\n"


def test_the_pinned_hash_is_the_hash_of_the_spec_block():
    """The constant and the spec cannot drift apart without this turning red."""
    import hashlib

    measured = hashlib.sha256(_canonical_shim_bytes_or_skip().encode("utf-8")).hexdigest()
    assert measured == json_handler_check.CANONICAL_SHIM_SHA256, (
        "the pinned canonical-shim hash no longer matches DPLAN-0325 section 3 — "
        "amend the constant in the same change as the spec"
    )


def _canonical_shim_bytes_on_disk():
    """The canonical shim from the citizen template, verified against the pin.

    The spec is gitignored and absent on CI; the template ships in the repo, so pins needing real bytes still
    run. The bytes are checked against ``CANONICAL_SHIM_SHA256``, so template drift is never blessed.
    """
    import hashlib
    from pathlib import Path as _Path

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
    assert hashlib.sha256(content.encode("utf-8")).hexdigest() == json_handler_check.CANONICAL_SHIM_SHA256, (
        "the citizen template is no longer the canonical shim — every branch spawned from it "
        "would be born failing the json_handler standard"
    )
    return content


def _named_check(branch, name):
    """The check called *name* as the public check_branch reports it, or None when absent."""
    result = json_handler_check.check_branch(str(branch))
    found = [check for check in result["checks"] if check["name"] == name]
    assert len(found) <= 1
    return found[0] if found else None


def _capability(root, content, branch_name):
    """(passed, message) of check_branch's handler-capability check for a handler holding *content*."""
    branch = root / branch_name
    handler = branch / "apps" / "handlers" / "json" / "json_handler.py"
    handler.parent.mkdir(parents=True)
    handler.write_text(content, encoding="utf-8")
    check = _named_check(branch, "Handler capability")
    assert check is not None, "check_branch reported no Handler capability check"
    return check["passed"], check["message"]


def test_the_canonical_shim_passes_capability_by_hash(tmp_path):
    """The spec's own bytes are accepted, and accepted on the identity path."""

    passed, message = _capability(tmp_path, _canonical_shim_bytes_or_skip(), "anybranch")
    assert passed is True
    assert "sha256" in message


def test_one_changed_character_is_no_longer_the_canonical_shim(tmp_path):
    """Identity, not resemblance: a shim that drifts stops being the shim."""
    mutated = _canonical_shim_bytes_or_skip().replace("_h = json_handler.for_module", "_h  = json_handler.for_module")
    passed, message = _capability(tmp_path, mutated, "anybranch")
    assert passed is False
    assert "sha256" in message


def test_a_half_migrated_shim_that_kept_a_branch_token_is_refused(tmp_path):
    """A branch that adopts the import and keeps its own directory is not migrated."""

    half = "from aipass.prax import json_handler\n_JSON_DIR = _ROOT / 'canary_json'\n"
    passed, message = _capability(tmp_path, half, "canary")
    assert passed is False
    assert "canary" in message


def test_the_refusal_message_names_the_branch_and_the_line_to_write(tmp_path):
    """A red a branch cannot act on is a red that stays."""
    passed, message = _capability(tmp_path, "def load_json(name):\n    return {}\n", "canary")
    assert passed is False
    assert "canary" in message
    assert json_handler_check.SERVICE_IMPORT_MARKER in message


def test_a_branch_without_a_citizen_template_grows_no_template_check(tmp_path):
    """Seventeen branches ship no template, so the check does not appear for them."""

    branch = tmp_path / "mybranch"
    branch.mkdir()
    assert _named_check(branch, "Template handler capability") is None


def test_the_citizen_template_is_judged_by_the_same_rule(tmp_path):
    """The file every newborn inherits is an audit subject, unrendered."""

    branch = tmp_path / "spawnish"
    template = branch / "templates" / "citizen" / "apps" / "handlers" / "json"
    template.mkdir(parents=True)
    handler = template / "json_handler.py"

    handler.write_text("def log_operation(op):\n    return True\n", encoding="utf-8")
    result = _named_check(branch, "Template handler capability")
    assert result is not None
    assert result["passed"] is False
    assert "Not the canonical json shim" in result["message"]

    # The real bytes: the only accept path is the hash, so a stand-in that merely imports the service is refused.
    handler.write_text(_canonical_shim_bytes_on_disk(), encoding="utf-8")
    result = _named_check(branch, "Template handler capability")
    assert result is not None
    assert result["passed"] is True


def test_a_bound_alias_is_not_a_lowercase_constant():
    """`save_json = _h.save_json` names a callable; PEP 8 spells it lowercase."""

    source = "save_json = _h.save_json\nInvalidDocument = json_handler.InvalidDocument\nMAX = 5\n"
    result = naming_check.check_constant_naming(source)
    assert result is not None
    assert result["passed"] is True


def test_an_alias_with_a_trailing_comment_is_still_an_alias():
    """A `# noqa` after the value must not turn the alias back into a constant."""

    result = naming_check.check_constant_naming("read_json = _h.read_json  # noqa: F401\nMAX = 5\n")
    assert result is not None
    assert result["passed"] is True


def test_the_alias_rule_does_not_excuse_an_expression_that_merely_contains_a_dot():
    """Only a BARE dotted name is an alias — the narrowing has an edge."""

    result = naming_check.check_constant_naming("total = counters.seen + 1\nfirst = items.data[0]\n")
    assert result is not None
    assert result["passed"] is False
    assert "total" in result["message"]


def test_a_shim_that_binds_the_service_resolves_nothing_and_says_so(tmp_path):
    """The canonical shim has no `Path(__file__)`, no `.resolve()`, no `.parent`."""

    handler = tmp_path / "apps" / "handlers" / "json" / "json_handler.py"
    handler.parent.mkdir(parents=True)
    # The real bytes: the exemption rides the hash test, so only the shim itself earns it.
    handler.write_text(_canonical_shim_bytes_on_disk(), encoding="utf-8")

    checks = json_structure_check.check_module(str(handler), bypass_rules=None)["checks"]
    resolution = next(c for c in checks if c["name"] == "Relative path resolution")
    assert resolution["passed"] is True
    assert "Delegates path resolution" in resolution["message"]


def test_a_handler_that_neither_binds_nor_resolves_still_fails(tmp_path):
    """The accept is the service import, not an amnesty on the whole check."""

    handler = tmp_path / "apps" / "handlers" / "json" / "json_handler.py"
    handler.parent.mkdir(parents=True)
    handler.write_text("JSON_DIR = 'documents'\n\n\ndef read_json(name):\n    return {}\n", encoding="utf-8")

    checks = json_structure_check.check_module(str(handler), bypass_rules=None)["checks"]
    resolution = next(c for c in checks if c["name"] == "Relative path resolution")
    assert resolution["passed"] is False
    assert "Missing relative path resolution" in resolution["message"]


def test_the_two_standards_share_the_shim_test_not_a_copy_of_a_string():
    """Both standards must agree on what a shim IS, by running the same function."""
    assert json_structure_check._is_canonical_shim is json_handler_check._is_canonical_shim


def _seam_branch(tmp_path, seam_body: str | None = None):
    """A branch whose audit trail lives in its own module, built on prax.

    Shaped like the real tree, because the seam lookup resolves the branch from the file's own path.
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


def _wiring_checks(path):
    """The code-wiring checks the public check_module runs on *path* (never a declined arm)."""
    checks = json_structure_check.check_module(str(path))["checks"]
    assert not any(check.get("declined") for check in checks), checks
    return checks


def test_a_module_logging_through_the_branch_seam_is_wired(tmp_path):
    """@backup moved 67 audit calls off the shim per the spec, as ordered."""

    seam = _seam_branch(tmp_path)
    module = seam.parents[2] / "modules" / "snapshot.py"
    module.parent.mkdir(parents=True)
    source = "from ..handlers.audit import trail\n\n\ndef run():\n    trail.log_operation('snapshot', {})\n"
    module.write_text(source, encoding="utf-8")

    checks = _wiring_checks(module)
    assert all(c["passed"] for c in checks)
    assert any("trail seam" in c["message"] for c in checks)


def test_the_seam_itself_does_not_have_to_log_through_itself(tmp_path):
    """The substrate is not a consumer of the substrate."""

    seam = _seam_branch(tmp_path)
    checks = _wiring_checks(seam)
    assert all(c["passed"] for c in checks)


def test_calling_log_operation_on_something_that_is_not_a_seam_earns_nothing(tmp_path):
    """The narrowing has an edge: a same-named helper is not a logging seam."""

    fake = _seam_branch(tmp_path, "def log_operation(operation, data):\n    print(operation)\n")

    module = fake.parents[2] / "modules" / "snapshot.py"
    module.parent.mkdir(parents=True)
    source = "from ..handlers.audit import trail\n\n\ndef run():\n    trail.log_operation('snapshot', {})\n"
    module.write_text(source, encoding="utf-8")

    checks = _wiring_checks(module)
    assert not all(c["passed"] for c in checks)


# host_portability_check: fixtures are minimised copies of real fleet sites, never live file:line pins,
# which go red whenever the file grows; the live list lives in host_portability.md.


def _scan_source(tmp_path, source, name="sample.py"):
    """Write *source* to a file and return (violations, acquitted_binary_sites)."""
    target = tmp_path / name
    target.write_text(source, encoding="utf-8")
    return host_portability_check.scan_file(str(target))


def _lines(violations):
    """Just the line numbers, which is what every pin below actually claims."""
    return [lineno for lineno, _ in violations]


def test_host_portability_declares_the_branch_level_contract():
    """AUDIT_SCOPE and the entry point the audit pipeline dispatches on."""
    assert host_portability_check.AUDIT_SCOPE == "branch_level"
    assert callable(host_portability_check.check_branch)


def test_a_clean_branch_scores_100_and_reports_the_file_count(tmp_path):
    """check_branch returns the pack's dict shape: passed/checks/score/standard."""
    apps = tmp_path / "apps"
    apps.mkdir()
    (apps / "clean.py").write_text("import os\n\n\ndef where():\n    return os.getcwd()\n", encoding="utf-8")

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["standard"] == "HOST_PORTABILITY"
    assert result["score"] == 100
    assert result["passed"] is True
    assert all(check["passed"] for check in result["checks"])


def test_a_branch_with_one_dirty_file_scores_by_clean_file_share(tmp_path):
    """Score is clean/total x 100 -- the number the all_files lane averages to."""
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


def test_tmux_kill_session_with_check_false_is_convicted(tmp_path):
    """hooks session_boot.py:248, :313 and :1078 -- the fleet's three tmux bugs."""
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
    """trigger service_control.py:82 -- systemctl --user enable, bare."""
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
    """aipass handoff_platform launch_tmux -- shutil.which('tmux') then run it."""
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
    """daemon tests/conftest.py:90 -- systemctl inside except FileNotFoundError."""
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


#: A test that runs tmux inside a pytest.raises of the given exception.
_RAISES_TMUX = (
    "import subprocess\n"
    "import pytest\n"
    "\n"
    "\n"
    "def test_no_tmux():\n"
    "    with pytest.raises({expected}):\n"
    '        subprocess.run(["tmux", "kill-session", "-t", "x"])\n'
)


@pytest.mark.parametrize("expected", ["FileNotFoundError", "OSError", "(FileNotFoundError, PermissionError)"])
def test_a_missing_file_raises_around_the_binary_acquits_it(tmp_path, expected):
    """Where tmux is absent the call raises exactly what the test expects, so it passes on every host."""
    violations, acquitted = _scan_source(tmp_path, _RAISES_TMUX.format(expected=expected))

    assert violations == []
    assert acquitted == 1


@pytest.mark.parametrize("expected", ["ValueError", "subprocess.CalledProcessError"])
def test_a_raises_of_another_error_still_convicts_the_binary(tmp_path, expected):
    """The control: a host without tmux raises FileNotFoundError, which this test does not expect."""
    violations, _acquitted = _scan_source(tmp_path, _RAISES_TMUX.format(expected=expected))

    assert _lines(violations) == [7]


def test_platform_dispatch_into_a_variable_argv0_is_not_convicted(tmp_path):
    """hooks apps/sound.py -- afplay on darwin, aplay otherwise, run from a var."""
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


def test_a_direct_pathlib_path_subclass_is_convicted_below_3_12(tmp_path):
    """trigger tests/test_error_registry.py:1477 class _RefusingPath(Path) (PR #774)."""
    source = "from pathlib import Path, PurePath\n\n\nclass _RefusingPath(Path):\n    pass\n"
    source += "\n\nclass _Pure(PurePath):\n    pass\n"
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [4, 8]
    assert "_flavour" in violations[0][1]


def test_a_concrete_flavour_or_a_carried_flavour_is_acquitted(tmp_path):
    """memory tests/test_roots_lifecycle.py:450 subclasses PureWindowsPath, which carries _flavour."""
    source = (
        "import pathlib\nfrom pathlib import Path, PureWindowsPath\n\n\n"
        "class _WindowsFlavour(PureWindowsPath):\n    pass\n\n\n"
        "class _Carried(pathlib.Path):\n    _flavour = type(Path())._flavour\n"
    )
    assert _scan_source(tmp_path, source)[0] == []


_DEGRADED_TOMLLIB = """def read(path):
    try:
        import tomllib
    except ModuleNotFoundError:
        return {}, "reading config.toml needs Python 3.11+"
    return tomllib.loads(path.read_text(encoding="utf-8")), ""
"""


def _floored_branch(tmp_path, floor, files):
    """A branch under a pyproject declaring *floor*; returns check_branch's violations."""
    (tmp_path / "pyproject.toml").write_text(f'[project]\nrequires-python = ">={floor}"\n', encoding="utf-8")
    apps = tmp_path / "apps"
    apps.mkdir()
    for name, source in files.items():
        (apps / name).write_text(source, encoding="utf-8")
    result = host_portability_check.check_branch(str(tmp_path))
    return [(v["file"], v["line"]) for check in result["checks"] for v in check.get("violations", [])]


def test_a_tomllib_import_with_a_degraded_except_and_no_tomli_is_convicted_below_its_floor(tmp_path):
    """aipass provider_wire.py before 1.9.1: fourteen tests red on CI's 3.10 lane only."""
    assert _floored_branch(tmp_path, "3.10", {"wire.py": _DEGRADED_TOMLLIB}) == [("apps/wire.py", 3)]


def test_a_tomli_fallback_in_the_same_guard_is_acquitted(tmp_path):
    """provider_wire 1.9.1 inside a function; aipass.py at module level, its tomli one try deeper."""
    in_function = _DEGRADED_TOMLLIB.replace(
        '        return {}, "reading config.toml needs Python 3.11+"\n',
        "        try:\n            import tomli as tomllib\n        except ImportError:\n"
        '            return {}, "needs tomli"\n',
    )
    module_level = """try:
    import tomllib
except ModuleNotFoundError:
    try:
        import tomli as tomllib
    except ModuleNotFoundError:
        tomllib = None
"""
    assert _floored_branch(tmp_path, "3.10", {"wire.py": in_function, "cli.py": module_level}) == []


def test_the_floor_comes_from_pyproject_so_a_311_floor_acquits_tomllib(tmp_path):
    assert _floored_branch(tmp_path, "3.11", {"wire.py": _DEGRADED_TOMLLIB}) == []


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


def test_the_openat2_twin_acquits_and_the_walk_fallback_convicts(tmp_path):
    """drone path_resolver.py -- :101 acquitted, :135 convicted. The one-hop pair."""
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


_INLINE_GUARD_HEAD = "import sys\nfrom pathlib import Path\n\n"


def test_a_module_level_inline_platform_guard_acquits_its_true_side(tmp_path):
    """prax agent_status_writer.py:62 -- PROC_ROOT = Path("/proc") if linux else None."""
    source = _INLINE_GUARD_HEAD + 'PROC_ROOT = Path("/proc") if sys.platform == "linux" else None\n'

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_proc_literal_on_the_else_side_of_an_inline_guard_stays_convicted(tmp_path):
    """The orelse operand runs where the platform is NOT Linux, so it is judged."""
    source = _INLINE_GUARD_HEAD + 'ROOT = Path.home() if sys.platform == "linux" else Path("/proc")\n'

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [4]


def test_a_path_that_merely_starts_with_the_letters_proc_is_not_a_proc_read(tmp_path):
    """/processed/ is an ordinary directory; only /proc and paths under it are Linux-only."""
    source = (
        "from pathlib import Path\n"
        'DATA = Path("/processed/data.csv").read_text(encoding="utf-8")\n'
        'MORE = Path(f"/processed/{DATA}").read_text(encoding="utf-8")\n'
        'REAL = Path("/proc/meminfo").read_text(encoding="utf-8")\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [4]


def test_a_function_level_inline_platform_guard_keeps_its_acquittal(tmp_path):
    """Inside a function the whole-function platform read already acquits (unchanged)."""
    source = _INLINE_GUARD_HEAD + 'def root():\n    return Path("/proc") if sys.platform == "linux" else None\n'

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_proc_read_in_a_pty_gated_class_is_still_convicted(tmp_path):
    """api tests/test_host_attach.py:912 and :919 -- @pty_required is not a guard."""
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
    """The `_posix_only` spelling -- a mark bound once at module level, used as @."""
    source = (
        "import os\n"
        "import sys\n"
        "import pytest\n"
        "from pathlib import Path\n"
        "\n"
        "_linux_only = pytest.mark.skipif(sys.platform != 'linux', reason='reads procfs')\n"
        "\n"
        "\n"
        "@_linux_only\n"
        "def test_parent_comm():\n"
        '    assert Path(f"/proc/{os.getppid()}/comm").read_text(encoding="utf-8")\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_doctor_like.py")

    assert violations == []


def test_a_windows_only_alias_no_longer_acquits_a_proc_read(tmp_path):
    """The same alias naming Windows -- `os.name == 'nt'` -- launders nothing now."""
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

    assert _lines(violations) == [10]
    assert "Linux-only" in violations[0][1]


def test_a_proc_path_used_as_a_mock_dict_key_is_not_convicted(tmp_path):
    """ai_mail tests/test_wake.py:337 and :348 -- a dict key opens nothing."""
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


def test_the_prose_of_a_skipif_reason_is_not_a_read_but_the_gate_it_explains_is(tmp_path):
    """prax tests/test_instance_lock.py:172 before d57b60fc -- red on every macOS run."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="/proc is Linux-only")\n'
        "def test_current_boot_id_reads_proc_on_linux():\n"
        "    assert _current_boot_id()\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_instance_lock_like.py")

    assert _lines(violations) == [5]
    assert "declares a Linux recipe" in violations[0][1]
    assert "Linux-only (absent" not in violations[0][1]


def test_a_proc_argv_element_is_not_convicted(tmp_path):
    """aipass sandbox_checker.py:71 -- `--proc /proc` is an argv pair for bwrap."""
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
    """aipass system_detector.py:172 -- `if not meminfo.exists(): return 0`."""
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


def test_a_proc_literal_bound_to_a_name_is_convicted_where_the_name_is_read(tmp_path):
    """skills lib/system_status/handler.py:96 spelled every read this way."""
    source = (
        "def read_meminfo():\n"
        '    meminfo_path = "/proc/meminfo"\n'
        '    with open(meminfo_path, encoding="utf-8") as handle:\n'
        "        return handle.read()\n"
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [3]


def test_the_skills_handler_existence_refusal_still_acquits(tmp_path):
    """skills handler.py before 8d1c6ef6 -- the product half of that red was honest."""
    source = (
        "import os\n"
        "\n"
        "\n"
        "def memory_info():\n"
        '    meminfo_path = "/proc/meminfo"\n'
        "    if not os.path.exists(meminfo_path):\n"
        '        return {"success": False, "error": "meminfo not available (non-Linux system?)"}\n'
        '    with open(meminfo_path, encoding="utf-8") as handle:\n'
        '        return {"success": True, "output": handle.read()}\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_bound_path_is_judged_at_its_read_not_its_constructor(tmp_path):
    """skills lib/telegram base_bot.py:2721 -- Path() outside the try, iterdir inside."""
    source = (
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def scan_pid_fds(pid):\n"
        '    fd_dir = Path(f"/proc/{pid}/fd")\n'
        "    try:\n"
        "        return list(fd_dir.iterdir())\n"
        "    except OSError:\n"
        "        return None\n"
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_an_unguarded_read_of_a_bound_path_convicts_the_read_line(tmp_path):
    """The same shape with no handler: the row is the iterdir, not the Path()."""
    source = (
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def scan_pid_fds(pid):\n"
        '    fd_dir = Path(f"/proc/{pid}/fd")\n'
        "    return list(fd_dir.iterdir())\n"
    )

    violations, _ = _scan_source(tmp_path, source)

    assert _lines(violations) == [6]


def test_a_name_rebound_to_something_else_is_not_followed(tmp_path):
    """Which value reaches the call is a question one pass cannot answer -- no row."""
    source = (
        'def pick(tmp):\n    path = "/proc/meminfo"\n    path = tmp\n    return open(path, encoding="utf-8").read()\n'
    )

    violations, _ = _scan_source(tmp_path, source)

    assert violations == []


def test_a_windows_only_skip_on_a_unit_whose_reason_names_linux_proc_is_convicted(tmp_path):
    """skills tests/test_runner.py before 8d1c6ef6 -- four of these, red every macOS run."""
    source = (
        "import sys\n"
        "\n"
        "import pytest\n"
        "\n"
        "\n"
        "class TestRunSkillHandler:\n"
        "    @pytest.mark.skipif(\n"
        '        sys.platform == "win32",\n'
        '        reason="system_status memory reads Linux /proc/meminfo; unavailable on Windows",\n'
        "    )\n"
        "    def test_run_system_status_memory(self):\n"
        '        assert run_skill("system_status", action="memory")["success"] is True\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_runner_like.py")

    assert _lines(violations) == [7]
    assert "test_run_system_status_memory" in violations[0][1]


def test_a_skip_naming_the_recipe_host_acquits_the_linux_named_unit(tmp_path):
    """prax tests/test_instance_lock.py after d57b60fc -- the cure, pinned clean."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform != "linux", reason="reads boot_id - no procfs on this host")\n'
        "def test_current_boot_id_reads_proc_on_linux():\n"
        "    assert _current_boot_id()\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_instance_lock_like.py")

    assert violations == []


def test_a_windows_only_skip_on_a_posix_recipe_is_correct_and_not_convicted(tmp_path):
    """hooks tests/test_cc_sessions.py:76 -- `ps` is on Linux AND macOS."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="ps-based; Linux + macOS only by contract")\n'
        "def test_reports_our_real_parent():\n"
        "    assert _get_ppid_portable() == 1\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_cc_like.py")

    assert violations == []


def test_a_reason_naming_proc_beside_a_macos_lane_is_not_convicted(tmp_path):
    """devpulse tests/test_watchdog_wire.py:832 -- /proc OR lsof, and macOS has lsof."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        "@pytest.mark.skipif(\n"
        '    sys.platform == "win32",\n'
        '    reason="neither /proc nor lsof answers on Windows; NOT widened to darwin, macOS has lsof",\n'
        ")\n"
        "def test_stdout_target_reads_proc_truth():\n"
        "    assert _stdout_target(1)\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_wire_like.py")

    assert violations == []


def test_a_linux_named_unit_with_no_gate_at_all_is_not_convicted(tmp_path):
    """aipass tests/test_cross_os.py:189 -- the rejected shape, 5 fleet hits, 5 false."""
    source = (
        "def test_filter_linux_only_all_rows(tmp_path):\n"
        '    assert gaps_for_platform("linux", start=tmp_path) == ["9"]\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_cross_os_like.py")

    assert violations == []


def test_a_unit_that_forces_its_own_platform_lane_is_not_convicted(tmp_path):
    """ai_mail tests/test_wake.py:283 shape -- the unit sets sys.platform itself."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only lane, forced below")\n'
        "def test_get_pid_cwd_linux(monkeypatch):\n"
        '    monkeypatch.setattr(wake.sys, "platform", "linux")\n'
        '    assert wake._get_pid_cwd("100") is None\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_wake_like.py")

    assert violations == []


def test_a_module_pytestmark_naming_windows_convicts_at_its_own_line(tmp_path):
    """A file-wide gate is read like a decorator; the row is the pytestmark line."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        'pytestmark = pytest.mark.skipif(sys.platform == "win32", reason="systemd units are Linux-only")\n'
        "\n"
        "\n"
        "def test_unit_file_renders():\n"
        "    assert render_unit()\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_unit_like.py")

    assert _lines(violations) == [4]


def test_a_unit_named_on_linux_behind_a_windows_only_skip_is_convicted_by_its_name(tmp_path):
    """The name alone declares the recipe; the reason here says nothing about it."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="needs the boot id")\n'
        "def test_current_boot_id_reads_proc_on_linux():\n"
        "    assert _current_boot_id()\n"
    )

    violations, _ = _scan_source(tmp_path, source, name="test_instance_lock_like.py")

    assert _lines(violations) == [5]


def test_the_off_linux_half_is_not_read_as_a_linux_name(tmp_path):
    """devpulse tests/test_watchdog_registry.py:219 -- off_linux is the portable half."""
    source = (
        "import pytest\n"
        "import sys\n"
        "\n"
        "\n"
        '@pytest.mark.skipif(sys.platform == "win32", reason="ps is POSIX")\n'
        "def test_is_zombie_off_linux_reads_the_ps_state():\n"
        '    assert is_zombie_via_ps("Z+")\n'
    )

    violations, _ = _scan_source(tmp_path, source, name="test_registry_like.py")

    assert violations == []


def test_lib_is_in_the_corpus(tmp_path):
    """skills lib/ -- all seven built-in skills live there and were never scored."""
    handlers = tmp_path / "lib" / "telegram" / "apps" / "handlers"
    handlers.mkdir(parents=True)
    (handlers / "tmux_manager.py").write_text(
        'import subprocess\n\n\ndef has(name):\n    subprocess.run(["tmux", "has-session", "-t", name])\n',
        encoding="utf-8",
    )

    result = host_portability_check.check_branch(str(tmp_path))

    assert result["score"] == 0
    failing = [c for c in result["checks"] if not c["passed"]]
    assert failing[0]["violations"][0]["file"] == "lib/telegram/apps/handlers/tmux_manager.py"


_LOCATE_CONFIG = """import os
from pathlib import Path


def _search_bounds():
    return Path.cwd(), Path.home()


def _absolute(raw):
    path = Path(raw)
    try:
        return path.resolve()
    except OSError:
        return path


def aipass_home():
    raw = os.environ.get("AIPASS_HOME", "")
    if raw:
        return _absolute(raw)
    return None


def locate_config():
    home = aipass_home()
    BOUNDS
    while search != stop and search.parent != search:
        if search == home:
            return "aipass", home
        search = search.parent
    return "none", None
"""


def test_a_resolved_home_compared_with_an_unresolved_walk_is_convicted(tmp_path):
    """hooks apps/handlers/config/loader.py locate_config() before 2.1.0 (60d2af72, macOS CI PR #774)."""
    source = _LOCATE_CONFIG.replace("BOUNDS", "search, stop = _search_bounds()")
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [28]
    assert "search == home" in violations[0][1]
    assert "resolve" in violations[0][1]


def test_both_walk_bounds_resolved_like_home_are_acquitted(tmp_path):
    """The cure in loader.py 2.1.0: both bounds pass through the same _absolute() as home."""
    source = _LOCATE_CONFIG.replace("BOUNDS", "search, stop = (_absolute(str(bound)) for bound in _search_bounds())")
    assert _scan_source(tmp_path, source)[0] == []


def test_relative_to_and_startswith_across_the_two_spellings_are_convicted(tmp_path):
    """The other three comparisons the arm reads: relative_to, is_relative_to, startswith on str()."""
    source = (
        "import os\nimport tempfile\nfrom pathlib import Path\n\n\n"
        "def rel(target):\n"
        "    return Path(target).resolve().relative_to(Path.home())\n\n\n"
        "def inside(target):\n"
        "    where = Path(target).resolve()\n"
        "    return str(where).startswith(os.getcwd())\n\n\n"
        "def scratch(target):\n"
        "    return Path(tempfile.gettempdir()).is_relative_to(Path(target).resolve())\n"
    )
    violations, _acquitted = _scan_source(tmp_path, source)
    assert _lines(violations) == [7, 12, 16]


def test_two_unresolved_or_two_resolved_spellings_are_acquitted(tmp_path):
    """Same spelling on both sides compares equal on every host: nothing to convict."""
    source = (
        "from pathlib import Path\n\n\n"
        "def same_raw(target):\n"
        "    return Path(target) == Path.home() or Path.cwd() == Path.home()\n\n\n"
        "def same_resolved(target):\n"
        "    return Path(target).resolve().relative_to(Path.home().resolve())\n"
    )
    assert _scan_source(tmp_path, source)[0] == []


# Arm F: drone's aipass_github fixture (conftest 1.3.0 vs 1.3.1), minimised.
_EMPTIED_GIT = (
    "import pytest\n\n\n"
    "@pytest.fixture()\n"
    "def repo(tmp_path, monkeypatch):\n"
    '    (tmp_path / "gitconfig").write_text("", encoding="utf-8")\n'
    '    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))\n'
    '    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")\n'
    "IDENTITY"
    "    return tmp_path\n"
)


def test_emptied_git_config_with_no_commit_email_is_convicted_once_at_the_first_emptying_line(tmp_path):
    """The CI exit 128: a runner has no email git can auto-detect once the host config is gone."""
    violations, _acquitted = _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", ""))
    assert _lines(violations) == [7]
    assert "GIT_AUTHOR_EMAIL" in violations[0][1] and "GIT_COMMITTER_EMAIL" in violations[0][1]


def test_both_emails_set_as_the_cured_fixture_does_are_acquitted(tmp_path):
    """conftest 1.3.1: the four GIT_AUTHOR_*/GIT_COMMITTER_* variables set through a loop."""
    identity = (
        '    for name in ("GIT_AUTHOR_EMAIL", "GIT_COMMITTER_EMAIL"):\n'
        '        monkeypatch.setenv(name, "door@test.invalid")\n'
    )
    assert _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", identity))[0] == []


def test_an_author_email_alone_is_convicted_because_git_resolves_the_committer_separately(tmp_path):
    """A half cure: git commit still asks for the committer's email and exits 128."""
    identity = '    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "a@test.invalid")\n'
    violations, _acquitted = _scan_source(tmp_path, _EMPTIED_GIT.replace("IDENTITY", identity))
    assert _lines(violations) == [7]
    assert "GIT_COMMITTER_EMAIL" in violations[0][1] and "GIT_AUTHOR_EMAIL" not in violations[0][1]


def test_a_user_email_written_to_git_config_is_acquitted(tmp_path):
    """`git config user.email` (or `-c user.email=`) answers both identities at once."""
    identity = '    subprocess.run(["git", "config", "--global", "user.email", "t@test.invalid"], check=True)\n'
    source = "import subprocess\n" + _EMPTIED_GIT.replace("IDENTITY", identity)
    assert _scan_source(tmp_path, source)[0] == []


# calendar_bound_check: each fixture lays down pkg/demo/apps/slots.py beside pkg/demo/tests/test_slots.py,
# because the rule reads production through the test's own imports.

_SLOTS_PRODUCTION = '''from datetime import datetime, timedelta

WEEK = timedelta(days=7)


def _anchor(slot, now):
    start = datetime.fromisoformat(slot)
    return start + ((now - start) // WEEK) * WEEK


def seed(runstate, job, now=None):
    """Seeds last_run; the incident's slot was 2026-09-06T03:00:00."""
    if now is None:
        now = datetime.now()
    runstate["last_run"] = _anchor(job["slot"], now).isoformat()


def tick(runstate, job):
    seed(runstate, job)


def touch(doc, now=None):
    if now is None:
        now = datetime.now()
    today = datetime.now().date().isoformat()
    doc.setdefault("created", today)
    doc.setdefault("first_seen", now)
    doc["updated"] = now.isoformat()
    return doc


def refuse(locked_at, now=None):
    now = now or datetime.now()
    age = (now - locked_at).total_seconds()
    return f"refused per the ruling of 2026-09-08; lock age {age:.0f}s"
'''

_SLOTS_UNIT = """from pkg.demo.apps.slots import tick


def job_with_slot(slot="2026-09-06T03:00:00"):
    return {"slot": slot}


class TestSeeding:
    def _tick(self, runstate):
        tick(runstate, job_with_slot())

    def test_the_slot_is_seeded(self):
        runstate = {}
        self._tick(runstate)
        assert runstate["last_run"] == "2026-09-06T03:00:00"
"""


def _calendar_package(tmp_path, unit_source, where=("tests",)):
    """Lay down pkg/demo with apps/slots.py and one test file; return (branch_root, test_file)."""
    branch = tmp_path / "pkg" / "demo"
    (branch / "apps").mkdir(parents=True)
    (branch / "apps" / "slots.py").write_text(_SLOTS_PRODUCTION, encoding="utf-8")
    test_dir = branch.joinpath(*where)
    test_dir.mkdir(parents=True)
    test_file = test_dir / "test_slots.py"
    test_file.write_text(unit_source, encoding="utf-8")
    return branch, test_file


def _calendar_scan(tmp_path, unit_source):
    """scan_file over a laid-down package: (violations, context)."""
    branch, test_file = _calendar_package(tmp_path, unit_source)
    return calendar_bound_check.scan_file(str(test_file), str(branch.parent))


def _line_of(source, needle):
    """1-based line of the first line of *source* containing *needle*."""
    return next(number for number, text in enumerate(source.splitlines(), start=1) if needle in text)


def test_calendar_bound_declares_the_branch_level_contract():
    """AUDIT_SCOPE and the entry point the audit pipeline dispatches on."""
    assert calendar_bound_check.AUDIT_SCOPE == "branch_level"
    assert calendar_bound_check.STANDARD_NAME == "CALENDAR_BOUND"
    assert callable(calendar_bound_check.check_branch)


def test_the_slot_seeder_time_bomb_is_convicted(tmp_path):
    """The CI red itself: literal expected value, seeder reads now three calls in, nothing frozen."""
    violations, context = _calendar_scan(tmp_path, _SLOTS_UNIT)

    assert _lines(violations) == [_line_of(_SLOTS_UNIT, 'assert runstate["last_run"]')]
    detail = violations[0][1]
    assert detail.startswith("test_the_slot_is_seeded asserts 2026-09-06T03:00:00"), detail
    assert "demo/apps/slots.py:" in detail and "seed" in detail, detail
    assert "(3 call(s) in)" in detail, detail
    assert context == {"owned": 0, "spelled": 0}


def test_a_fixture_whose_name_merely_contains_now_owns_no_clock(tmp_path):
    """known_ids spells "now" inside a word; it is no clock fixture, so the time bomb stays convicted."""
    source = _SLOTS_UNIT.replace("def test_the_slot_is_seeded(self):", "def test_the_slot_is_seeded(self, known_ids):")
    violations, _context = _calendar_scan(tmp_path, source)

    assert _lines(violations) == [_line_of(source, 'assert runstate["last_run"]')]


def test_freezing_the_module_clock_in_a_same_file_helper_acquits(tmp_path):
    """daemon's own cure shape: a helper the unit calls monkeypatches the module's datetime."""
    source = """from datetime import datetime

from pkg.demo.apps import slots
from pkg.demo.apps.slots import tick


class Frozen(datetime):
    @classmethod
    def now(cls, tz=None):
        return datetime(2026, 9, 13, 12, 31)


def freeze(monkeypatch):
    monkeypatch.setattr(slots, "datetime", Frozen)


def test_the_slot_is_seeded(monkeypatch):
    freeze(monkeypatch)
    runstate = {}
    tick(runstate, {"slot": "2026-09-06T03:00:00"})
    assert runstate["last_run"] == "2026-09-13T03:00:00"
"""
    violations, context = _calendar_scan(tmp_path, source)

    assert violations == []
    assert context == {"owned": 1, "spelled": 0}


def test_an_injected_instant_acquits(tmp_path):
    """now= handed to the seeder is the unit owning the clock (daemon test_runstate's shape)."""
    source = """from datetime import datetime

from pkg.demo.apps.slots import seed


def test_the_slot_is_seeded_at_an_injected_instant():
    runstate = {}
    seed(runstate, {"slot": "2026-09-06T03:00:00"}, now=datetime(2026, 9, 13, 12, 31))
    assert runstate["last_run"] == "2026-09-13T03:00:00"
"""
    violations, context = _calendar_scan(tmp_path, source)

    assert violations == []
    assert context == {"owned": 1, "spelled": 0}


def test_a_stamp_is_not_a_derivation(tmp_path):
    """A round trip through code that only STAMPS now is clear (api test_tracking's shape)."""
    source = """from pkg.demo.apps.slots import touch


def test_created_survives_a_touch():
    doc = touch({"created": "2025-11-13"})
    assert doc["created"] == "2025-11-13"
"""
    violations, context = _calendar_scan(tmp_path, source)

    assert violations == []
    assert context == {"owned": 0, "spelled": 0}


def test_a_patched_seam_is_cut_from_the_walk(tmp_path):
    """The only road to the clock goes through seed(), and the unit stubbed it."""
    source = """from unittest.mock import patch

from pkg.demo.apps.slots import tick


def test_tick_hands_the_job_to_the_seeder():
    runstate = {"last_run": "2026-09-06T03:00:00"}
    with patch("pkg.demo.apps.slots.seed") as seeder:
        tick(runstate, {"slot": "2026-09-06T03:00:00"})
    seeder.assert_called_once()
    assert runstate["last_run"] == "2026-09-06T03:00:00"
"""
    violations, context = _calendar_scan(tmp_path, source)

    assert violations == []
    assert context == {"owned": 0, "spelled": 0}


def test_a_date_production_spells_is_acquitted(tmp_path):
    """ai_mail test_wake's shape: the asserted date is a ruling written into the refusal text."""
    source = """from datetime import datetime

from pkg.demo.apps.slots import refuse


def test_the_refusal_names_the_ruling():
    message = refuse(datetime.fromisoformat("2026-09-07T10:00:00"))
    assert "2026-09-08" in message
"""
    violations, context = _calendar_scan(tmp_path, source)

    assert violations == []
    assert context == {"owned": 0, "spelled": 1}


def test_a_sleep_patch_does_not_own_the_clock(tmp_path):
    """Stopping a wait freezes nothing; ai_mail's wake helper was acquitted by the word 'time'."""
    source = """from pkg.demo.apps.slots import tick


def test_the_slot_is_seeded(monkeypatch):
    monkeypatch.setattr("pkg.demo.apps.slots.time.sleep", lambda _: None)
    runstate = {}
    tick(runstate, {"slot": "2026-09-06T03:00:00"})
    assert runstate["last_run"] == "2026-09-06T03:00:00"
"""
    violations, _context = _calendar_scan(tmp_path, source)

    assert _lines(violations) == [_line_of(source, "assert runstate")]


def test_calendar_bound_scores_by_clean_test_file_share(tmp_path):
    """check_branch: two test files, one convicted - 50, and the row names the file."""
    branch, _test_file = _calendar_package(tmp_path, _SLOTS_UNIT)
    (branch / "tests" / "test_clean.py").write_text("def test_arithmetic():\n    assert 1 + 1 == 2\n", encoding="utf-8")

    result = calendar_bound_check.check_branch(str(branch))

    assert result["standard"] == "CALENDAR_BOUND"
    assert result["score"] == 50
    failing = [c for c in result["checks"] if not c["passed"]]
    assert [row["file"] for row in failing[0]["violations"]] == ["tests/test_slots.py"]


def test_a_skills_own_tests_under_lib_are_in_the_corpus(tmp_path):
    """skills keeps tests beside each skill in lib/<skill>/tests/, outside the branch tests/ root."""
    branch, _test_file = _calendar_package(tmp_path, _SLOTS_UNIT, where=("lib", "reminder", "tests"))

    result = calendar_bound_check.check_branch(str(branch))

    assert result["score"] == 0
    failing = [c for c in result["checks"] if not c["passed"]]
    assert failing[0]["violations"][0]["file"] == "lib/reminder/tests/test_slots.py"


def test_shared_parse_treats_a_valueerror_as_unparseable(monkeypatch):
    """ast.parse raises ValueError, not SyntaxError, on a lone surrogate (and on a NUL byte before 3.12)."""
    logged = MagicMock()
    monkeypatch.setattr(check_support, "json_handler", logged)

    assert check_support.parse("x = '\ud800'", tag="t") is None
    assert check_support.parse("x = 1\0", tag="t") is None
    assert logged.log_operation.call_count == 2


# host_coupled_oracle_check: reductions of the two PR #807 hooks reds. proc.py is cc_sessions' shape: a
# module-level platform alias and a local subprocess alias in the one function that forks.

_PROC_PRODUCTION = """import os
import sys
from pathlib import Path

_PLATFORM = sys.platform


def process_args(pid):
    import subprocess as _sp

    if _PLATFORM.startswith("linux"):
        return Path(f"/proc/{pid}/cmdline").read_bytes().split(b"\\0")
    return _sp.run(["ps", "-o", "args=", "-p", str(pid)], capture_output=True, text=True).stdout.split()


def resolve_session_pid():
    return process_args(os.getppid()) and None


def is_pid_alive(pid):
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_supported():
    return sys.platform.startswith("linux")


def enable():
    import subprocess

    if not is_supported():
        return None
    return subprocess.run(["systemctl", "--user", "enable", "--now", "demo"])
"""

_PROC_UNITS = """import os
import subprocess
import sys
from unittest.mock import patch

import pytest

from pkg.demo.apps import proc


def test_own_title():
    assert "python" in proc.process_args(os.getpid())[0]


def test_own_liveness():
    assert proc.is_pid_alive(os.getpid())


def test_forked_count():
    with patch("subprocess.run", side_effect=OSError("no ps")) as ps:
        proc.resolve_session_pid()
    assert ps.call_count == 1


@pytest.mark.skipif(not sys.platform.startswith("linux"), reason="the /proc path")
def test_forked_count_on_linux_only():
    with patch("subprocess.run", side_effect=OSError("no ps")) as ps:
        proc.resolve_session_pid()
    assert ps.call_count == 1


def test_gate_pinned_by_a_fixture():
    with patch("subprocess.run") as run, patch.object(proc, "is_supported", return_value=True):
        proc.enable()
    assert run.call_count == 1


def test_a_non_runner_count():
    with patch.object(proc, "is_pid_alive", return_value=True) as alive:
        proc.resolve_session_pid()
    assert alive.call_count == 1


def _child_pid():
    return subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"]).pid


def test_child_title():
    assert "python" in proc.process_args(_child_pid())[0]
"""


def _proc_package(tmp_path):
    """Lay down pkg/demo with apps/proc.py and tests/test_proc.py; return (branch_root, test_file)."""
    branch = tmp_path / "pkg" / "demo"
    (branch / "apps").mkdir(parents=True)
    (branch / "apps" / "proc.py").write_text(_PROC_PRODUCTION, encoding="utf-8")
    (branch / "tests").mkdir()
    test_file = branch / "tests" / "test_proc.py"
    test_file.write_text(_PROC_UNITS, encoding="utf-8")
    return branch, test_file


def test_host_coupled_oracle_convicts_the_title_read_and_the_forked_count_only(tmp_path):
    """Own pid into process_args and an exact ps count convicted; liveness, a skip mark, a pinned gate and a
    non-runner mock and a child's pid acquitted."""
    branch, test_file = _proc_package(tmp_path)

    rows = host_coupled_oracle_check.scan_file(str(test_file), str(branch.parent))

    assert _lines(rows) == [_line_of(_PROC_UNITS, "process_args(os.getpid())"), _line_of(_PROC_UNITS, "ps.call_count")]
    assert "demo/apps/proc.py:8 process_args" in rows[1][1]


def test_host_coupled_oracle_scores_by_clean_test_file_share(tmp_path):
    """check_branch: one convicted file of two scores 50 and names the file."""
    branch, _test_file = _proc_package(tmp_path)
    (branch / "tests" / "test_clean.py").write_text("def test_arithmetic():\n    assert 1 + 1 == 2\n", encoding="utf-8")

    result = host_coupled_oracle_check.check_branch(str(branch))

    assert (result["standard"], result["score"], result["passed"]) == ("HOST_COUPLED_ORACLE", 50, False)
    assert {row["file"] for row in result["checks"][0]["violations"]} == {"tests/test_proc.py"}
