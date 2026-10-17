# =================== AIPass ====================
# Name: test_json_handler_contract.py
# Description: Fleet-wide contract suite over every branch json_handler: read, write, address, floor
# Version: 1.3.0
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py, one contract over the fleet."""

# Reading, writing and addressing contracts and the suite's own floor; the identity, durability and
# template-lineage clauses live in the test_json_handler_contract_*.py siblings, helpers in support_json_handler_contract.py.
# Divergence is reported, never silenced: pytest.skip naming the missing surface, xfail(strict) with the
# measured reason (a repaired branch turns it red), and a plain assertion where the fleet agrees.
# Every implementation is redirected at tmp_path and verified before the first write (quarantined_document_directories).

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that handlers/aipass_standards/json_handler_check.py parses and imports

import copy
import json
from pathlib import Path

import pytest

from aipass.seedgo.tests.support_json_handler_contract import (
    BRANCHES,
    CONFIG_PAYLOAD,
    DATA_PAYLOAD,
    DECLARED_LOG_CAP_IGNORED,
    ENSURE_ALL_RETURNS_NOTHING,
    ENSURE_RETURNS_NOTHING,
    LOG_PAYLOAD,
    PACKAGE_ROOT,
    TORN_DOCUMENT_OBSERVED,
    WRITER_HAS_NO_BOUNDED_RETRY,
    _installed_roster,
    assert_warned_of_corrupt_bytes,
    expose,
    handler_path,
    implementation,
    parametrized,
    prepared,
    redirect_documents,
    redirected,
    require_document_addressing,
    required_positionals,
)

pytestmark = pytest.mark.usefixtures("quarantined_document_directories")


#: ``save_json`` at a directory that does not exist yet: branches whose answer loses the document.
#: Empty: every branch persists through the one service. A row comes out only when its strict xfail turns red.
SAVE_JSON_MISSING_PARENT: dict[str, str] = {}

#: ``get_json_path`` return type. Every branch answers ``pathlib.Path``.
#: Empty; a row is a branch answering ``str``, which breaks ``.parent`` and ``/`` at its call sites.
GET_JSON_PATH_TYPE: dict[str, str] = {}

#: (data, json_type, expected) — the shared validator's answers, measured
#: identical across every branch that has the function.
VALIDATION_MATRIX = (
    ({"module_name": "m", "version": "1", "config": {}}, "config", True),
    ({"module_name": "m", "version": "1"}, "config", False),
    ({"created": "a", "last_updated": "b"}, "data", True),
    ({"created": "a"}, "data", False),
    ([], "log", True),
    ({}, "log", False),
    ("not a mapping", "config", False),
    (None, "data", False),
    (7, "log", False),
    ({"module_name": "m", "version": "1", "config": {}}, "no_such_type", False),
    # A LIST offered as config, a STRING as data, None against every type, and a non-empty log.
    ([1, 2, 3], "config", False),
    ("not a dict", "data", False),
    (None, "config", False),
    (None, "log", False),
    ([{"entry": 1}], "log", True),
)

#: The default factory's answer to an unknown json_type. Empty: the shim has no private factory, and
#: VALIDATION_MATRIX's no_such_type case pins the refusal on the public surface.
UNKNOWN_TYPE_NOT_REFUSED: dict[str, str] = {}


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_answers_a_default_for_a_document_that_does_not_exist(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """load_json never makes a caller handle "the file is not there"."""
    module = implementation(branch)
    if required_positionals(module.load_json) == 2:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        answer = module.load_json("never_written", "data")
    else:
        answer = module.load_json(str(tmp_path / "never_written.json"))
    assert answer is not None, f"{branch}: load_json returned None for a missing document"
    # The default is a data document, not merely something: every family answers a dict with both dates.
    assert {"created", "last_updated"} - set(answer) == set(), (
        f"{branch}: load_json's default for a missing data document is {answer!r}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_default_has_the_container_type_the_json_type_promises(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A missing "log" reads back as a list and a missing "data" as a dict."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)
    default_config = module.load_json("absent_config", "config")
    default_data = module.load_json("absent_data", "data")
    default_log = module.load_json("absent_log", "log")
    assert isinstance(default_config, dict)
    assert isinstance(default_data, dict)
    assert isinstance(default_log, list)
    assert default_log == [], f"{branch}: an absent log defaulted to {default_log!r}, not an empty list"
    assert default_config["module_name"] == "absent_config", (
        f"{branch}: the config default is not addressed to the document asked for — {default_config!r}"
    )
    assert default_config["version"] == "1.0.0", f"{branch}: config default version is {default_config!r}"
    assert "last_updated" in default_data, f"{branch}: the data default carries no last_updated — {default_data!r}"


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_materialises_the_document_it_was_asked_to_read(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """load_json is not a pure read: it creates the file it did not find."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, documents = prepared(branch, tmp_path, monkeypatch)
    module.load_json("read_only_please", "data")
    assert (documents / "read_only_please_data.json").exists(), (
        f"{branch}: load_json did not create the document — the fleet's other handlers do"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_survives_a_corrupt_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unparseable bytes on disk do not become an exception in the caller."""
    module = implementation(branch)
    if required_positionals(module.load_json) == 2:
        module, documents = prepared(branch, tmp_path, monkeypatch)
        (documents / "corrupt_config.json").write_text("{not json at all", encoding="utf-8")
        answer = module.load_json("corrupt", "config")
        # WHAT it regenerates, not merely its type: a blank template addressed to the document asked for, so
        # a handler handing back another document's contents, or {}, fails here.
        assert answer["module_name"] == "corrupt", (
            f"{branch}: corrupt bytes did not regenerate a template for the document asked for — {answer!r}"
        )
        assert answer["version"] == "1.0.0", f"{branch}: regenerated template carries {answer!r}"
        assert_warned_of_corrupt_bytes(module, branch)
    else:
        corrupt = tmp_path / "corrupt.json"
        corrupt.write_text("{not json at all", encoding="utf-8")
        answer = module.load_json(str(corrupt))
    assert isinstance(answer, (dict, list)), f"{branch}: load_json answered {type(answer).__name__} for corrupt bytes"


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_then_load_json_returns_the_same_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The round trip every caller of save_json is relying on."""
    module = implementation(branch)
    if required_positionals(module.load_json) == 2:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        module.save_json("round_trip", "config", copy.deepcopy(CONFIG_PAYLOAD))
        assert module.load_json("round_trip", "config") == CONFIG_PAYLOAD
        module.save_json("round_trip", "log", copy.deepcopy(LOG_PAYLOAD))
        assert module.load_json("round_trip", "log") == LOG_PAYLOAD
    else:
        document = tmp_path / "round_trip.json"
        module.save_json(str(document), copy.deepcopy(CONFIG_PAYLOAD))
        assert module.load_json(str(document)) == CONFIG_PAYLOAD


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_stamps_last_updated_onto_the_callers_own_dict(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Saving a "data" document MUTATES the dict the caller handed in."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    data = copy.deepcopy(DATA_PAYLOAD)
    module.save_json("stamped", "data", data)
    assert data["last_updated"] != DATA_PAYLOAD["last_updated"], (
        f"{branch}: save_json left last_updated alone; the rest of the fleet overwrites it in place"
    )
    assert data["counters"] == DATA_PAYLOAD["counters"], f"{branch}: save_json disturbed unrelated keys"

    config = copy.deepcopy(CONFIG_PAYLOAD)
    module.save_json("untouched", "config", config)
    assert config == CONFIG_PAYLOAD, f"{branch}: save_json mutated a config payload"


@pytest.mark.parametrize("branch", parametrized(SAVE_JSON_MISSING_PARENT))
def test_save_json_persists_into_a_document_directory_that_does_not_exist_yet(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A first write on a fresh checkout must not lose the document."""
    module = implementation(branch)
    absent = tmp_path / "not" / "created" / "yet"
    if required_positionals(module.load_json) == 2:
        module = redirected(branch, absent, monkeypatch)
        module.save_json("first_write", "config", copy.deepcopy(CONFIG_PAYLOAD))
        assert module.load_json("first_write", "config") == CONFIG_PAYLOAD
    else:
        document = absent / "first_write.json"
        module.save_json(str(document), copy.deepcopy(CONFIG_PAYLOAD))
        assert module.load_json(str(document)) == CONFIG_PAYLOAD


@pytest.mark.parametrize("branch", parametrized(GET_JSON_PATH_TYPE))
def test_get_json_path_answers_a_pathlib_path(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_json_path hands back a Path, so ``.parent`` and ``/`` work on it."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    resolver = expose(module, branch, "get_json_path")
    module, documents = prepared(branch, tmp_path, monkeypatch)
    answer = resolver("addressed", "config")
    assert isinstance(answer, Path)
    # The Path-only surface ANSWERED, not merely typed: `.parts` reads the split call sites rely on and
    # pins the two tail segments, the handler's document directory and the file inside it.
    assert answer.parts[-2:] == (documents.name, "addressed_config.json"), (
        f"{branch}: get_json_path resolved to {answer} — expected it inside {documents}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_get_json_path_names_the_document_module_underscore_type(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The filename convention every glob over a branch's documents assumes.

    Tooling reconstructs ``<module>_<type>.json`` names instead of calling the handler.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    resolver = expose(module, branch, "get_json_path")
    module, documents = prepared(branch, tmp_path, monkeypatch)
    answer = Path(str(resolver("some_module", "config")))
    assert answer.name == "some_module_config.json"
    assert answer.parent == documents


@pytest.mark.parametrize("branch", parametrized())
def test_validate_json_structure_answers_the_measured_matrix(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The one function the fleet did not manage to diverge on."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    validate = expose(module, branch, "validate_json_structure")
    disagreements = [
        (json_type, data, answer)
        for data, json_type, expected in VALIDATION_MATRIX
        for answer in [validate(data, json_type)]
        if answer is not expected
    ]
    assert not disagreements, f"{branch}: validate_json_structure diverges on {disagreements}"


def test_discovery_finds_every_shipped_handler_and_names_no_branch_itself():
    """Discovery is a roster, so a new citizen is covered without editing this file."""
    assert len(BRANCHES) >= 2, f"json_handler discovery found {BRANCHES} under {PACKAGE_ROOT}"
    assert len(set(BRANCHES)) == len(BRANCHES)
    assert set(_installed_roster()) <= set(BRANCHES), "widening discovery must never lose an installed citizen"
    for branch in BRANCHES:
        assert handler_path(branch).is_file()


def test_one_branch_is_one_module_however_many_times_it_is_asked_for():
    """``implementation`` must be idempotent, or the redirect covers nothing.

    A resident built anew per call lets a contract redirect a module nobody writes through, so writes
    land in live document directories. The two handles are taken into separate names on purpose.
    """
    assert len(BRANCHES) >= 2, f"json_handler discovery found {BRANCHES} under {PACKAGE_ROOT}"
    for branch in BRANCHES:
        first = implementation(branch)
        second = implementation(branch)
        assert first is second, (
            f"{branch} loads a fresh module per call — every redirect in this file would cover a module "
            f"that no contract then writes through, and the writes would land in its live tree"
        )


def test_no_contract_writes_into_a_live_branch_document_directory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The redirect helper really redirects, on every branch it does not skip.

    Each branch is checked against ITS OWN target: the autouse quarantine already sits under tmp_path.
    """
    escaped = []
    for branch in BRANCHES:
        module = implementation(branch)
        resolver = getattr(module, "get_json_path", None)
        if resolver is None:
            continue
        target = tmp_path / "verified" / branch
        redirect_documents(module, target, monkeypatch)
        answer = Path(str(resolver("safety", "data")))
        if not answer.is_relative_to(target):
            escaped.append((branch, str(answer)))
    assert not escaped, f"redirect failed for {escaped} — those writes would have hit live branch trees"


def test_every_discovered_handler_exposes_load_json_and_save_json():
    """The two entry points the whole fleet does share, under either convention."""
    conventions = {}
    for branch in BRANCHES:
        module = implementation(branch)
        assert callable(getattr(module, "load_json", None)), f"{branch} has no load_json"
        assert callable(getattr(module, "save_json", None)), f"{branch} has no save_json"
        conventions[branch] = required_positionals(module.load_json)
    unknown = {b: n for b, n in conventions.items() if n not in (1, 2)}
    assert not unknown, f"unrecognised load_json calling convention: {unknown}"


def test_the_divergence_tables_only_name_branches_that_still_exist():
    """A retired branch must not leave a stale xfail behind."""
    tables = (
        set(SAVE_JSON_MISSING_PARENT)
        | set(GET_JSON_PATH_TYPE)
        | set(WRITER_HAS_NO_BOUNDED_RETRY)
        | set(TORN_DOCUMENT_OBSERVED)
        | set(ENSURE_RETURNS_NOTHING)
        | set(DECLARED_LOG_CAP_IGNORED)
        | set(ENSURE_ALL_RETURNS_NOTHING)
        | set(UNKNOWN_TYPE_NOT_REFUSED)
    )
    stale = sorted(tables - set(BRANCHES))
    assert stale == [], f"divergence tables name branches that no longer exist: {json.dumps(stale)}"
