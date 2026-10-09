# =================== AIPass ====================
# Name: test_json_handler_contract.py
# Description: Fleet-wide contract suite over every branch json_handler: read, write, address, floor
# Version: 1.3.0
# Created: 2026-09-01
# Modified: 2026-10-08
# =============================================

"""Tests for every branch's apps/handlers/json/json_handler.py, one contract over the fleet."""

# Reading, writing and addressing contracts and the suite's own floor. The
# identity, durability and template-lineage clauses live in the
# test_json_handler_contract_*.py siblings, the shared discovery and helpers in
# support_json_handler_contract.py (split 2026-10-08 under oversize_test_file).
#
# One contract suite over every ``json_handler`` the fleet ships.
#
# WHY THIS FILE EXISTS. The campaign premise was "shared infrastructure tested N
# times". Measurement refused it: the branch handlers were stamped once and every
# copy then diverged. Eighteen files, eighteen distinct hashes, 28 to 592 lines,
# and no single function present in all eighteen with the same shape. So this is
# not a suite that asserts they are the same. It is a suite that asserts what is
# TRUE of each, names every place they disagree, and refuses to hide a
# disagreement behind an assertion weak enough to pass everywhere.
#
# HOW DIVERGENCE IS REPORTED. Three mechanisms, never silence:
#
# * ``pytest.skip`` with a message naming the branch and the missing function,
#   for a surface a branch simply does not have (``ai_mail`` has no
#   ``validate_json_structure``; ``backup`` addresses documents by path, so every
#   ``module_name``/``json_type`` contract is inapplicable there, not passing).
# * ``pytest.mark.xfail(strict=True)`` carrying the MEASURED reason, for a branch
#   that has the function and answers differently from the fleet majority. Strict
#   on purpose: when a branch is repaired the xfail turns into a failure that
#   says "update the divergence table", instead of a green line nobody rereads.
# * A plain assertion for everything the fleet genuinely agrees on.
#
# DISCOVERY IS DYNAMIC. The branch list is globbed from the installed ``aipass``
# package, never written down. A nineteenth branch is picked up with no edit here
# and is held to the majority contract; a deleted branch disappears from the run
# instead of breaking it. Only the divergence tables name branches, because a
# measurement record has to name its subjects.
#
# SAFETY. Every implementation is redirected at ``tmp_path`` before any call that
# could write, and the redirect is VERIFIED through the implementation's own
# ``get_json_path`` before the first write. A branch whose directory cannot be
# redirected is skipped, loudly — this suite never writes into a live branch tree.
# Redirecting only the subject was NOT enough and the difference was measured,
# not guessed: see ``quarantined_document_directories`` for the syscall audit and
# the exact cross-branch chain it closes.

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

# ---------------------------------------------------------------------------
# Measured divergence tables (2026-09-01, this tree)
# ---------------------------------------------------------------------------

#: ``save_json`` addressed at a directory that does not exist yet. Majority
#: (10 of 18, counting backup's path-addressed form) creates the directory and
#: persists. The rest split two ways, and BOTH ways lose the caller's document.
#:
#: ``ai_mail`` was the tenth entry here until 2026-09-02, when its atomic-write
#: cure (dispatched off this suite's slice-3 finding) also began creating the
#: directory. The row was removed because the strict xfail turned RED, which is
#: the table working: a cure that lands is reported, not carried as folklore.
#:
#: ``prax`` left the same way on 2026-09-03, and it is the first row the
#: migration itself removed: prax's handler became a shim over the one service
#: (DPLAN-0325), whose ``ensure_json_exists`` creates the directory per call, so
#: the strict xfail XPASSed. Seventeen rows across these tables are expected to
#: go the same way as the sweep reaches their branches — each one deleted when
#: it turns red, never pre-emptively, because a table emptied ahead of the cure
#: asserts nothing while looking like it does.
#:
#: ``hooks`` left on the same rule later that day, when its sweep landed the
#: canonical shim. Its row read "raises FileNotFoundError from the staging
#: file"; the service creates the directory, so the xfail XPASSed and the row
#: went.
#:
#: ``skills`` left with the pair-2 sweep (DPLAN-0325 phase 4, devpulse): its
#: row read "returns False and writes nothing"; the shim persists through the
#: service, so the strict xfail XPASSed on CI and the row went. ``cli`` and
#: ``seedgo`` left the same way with pair 4, both having read "raises
#: FileNotFoundError from the staging file", and ``flow`` with pair 7 -- each
#: XPASSed strictly the first time its suite ran against the shim, which is the
#: only evidence that retires a row here.
#:
#: ``commons`` left with pair 5 on 2026-09-04. Its row read "raises
#: FileNotFoundError from the staging file"; the service creates the directory,
#: and the strict xfail reported XPASS(strict) on the first run against the
#: shim.
#:
#: RETIRED 2026-09-04 (pair 6), and with it the LAST live xfail in this file.
#: The final row was api's: "returns False and writes nothing when the document
#: directory is absent". api swept to the canonical shim, the strict xfail
#: reported XPASS(strict) on the first run against it, and the table is empty.
#: Eighteen of eighteen branches now persist through the one service, which
#: creates the document directory per call — so there is no longer a fleet on
#: which this divergence can exist. The table stays, empty and named, because
#: the next divergence that appears belongs in it rather than in a new one.
SAVE_JSON_MISSING_PARENT: dict[str, str] = {}

#: ``get_json_path`` return type. Every branch answers ``pathlib.Path``.
#:
#: RETIRED 2026-09-04 (pair 5). The single row was commons's: it built its path
#: with ``os.path.join`` and answered a ``str``, so a caller doing ``.parent``
#: or ``/`` broke on that one branch and nowhere else. commons swept to the
#: canonical shim, which binds the one service, and the strict xfail reported
#: XPASS(strict) — the cure, measured rather than assumed. commons's own
#: ``test_json_path_returns_path_like`` had asserted ``result.endswith(".json")``,
#: which only a str can satisfy; it now asserts the Path, so the divergence is
#: gone from both sides of the fleet.
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
    # Added with the template-lineage fold: five inputs the stamped copies
    # asserted that the original ten did not reach — a LIST offered as config,
    # a STRING offered as data, None against all three types rather than only
    # "data", and a non-empty log.
    ([1, 2, 3], "config", False),
    ("not a dict", "data", False),
    (None, "config", False),
    (None, "log", False),
    ([{"entry": 1}], "log", True),
)

#: The default factory's answer to a json_type it does not know. Fourteen
#: raised ValueError; skills returned None, so a typo'd json_type was not
#: refused — ``ensure_json_exists(name, "confgi")`` wrote the literal ``null``
#: into a document instead of failing, and the next reader got a document that
#: parsed and meant nothing. Measured, not read off the source.
#:
#: RETIRED 2026-09-04 (DPLAN-0325 part B section 2) BY SUBJECT GONE, which is
#: NOT the usual retirement and is the reason this comment is longer than the
#: row it replaces. Every other row here waits for its strict xfail to XPASS —
#: the divergence is cured, the test goes red, the row comes out. This one
#: could never go red. skills swept to the canonical shim in 6cdb3d7f and the
#: shim exposes no private default factory at all, so the probe stopped
#: RUNNING: it skips by name, and a skip is not a cure detector. Waiting for an
#: XPASS that cannot fire would have kept a dead row here indefinitely.
#:
#: Verified before removal rather than assumed: probed all eighteen handlers
#: for a factory under DEFAULT_FACTORY_NAMES. Seventeen expose none — skills
#: included, so the divergence has no surface left to live on. The one that
#: does, @commons, RAISES ValueError and is conformant. There is no branch left
#: to mark down.
#:
#: THE TEST WENT TOO, with pair 5 on 2026-09-04, and by the same rule that
#: took the row: no subject left anywhere. Session M recorded it measuring
#: exactly ONE branch (commons) and skipping seventeen, and kept it because
#: that one claim was still real. commons then swept, so the count is now
#: eighteen skips and zero measurements — a parametrized test that cannot
#: execute a single assertion on any branch in the fleet. Measured on the day:
#: `pytest -k default_factory_refuses` -> 18 skipped.
#:
#: The concept survives on a PUBLIC surface, which is why removing the private
#: probe costs nothing. The claim was about a private default factory, and the
#: shim deliberately publishes no private surface at all — the one service
#: decides templates internally. What a caller can still reach is
#: ``validate_json_structure``, and ``VALIDATION_MATRIX`` above carries the
#: unknown-type case verbatim — ``({"module_name": ..., "config": {}},
#: "no_such_type", False)`` — asserted by
#: ``test_validate_json_structure_answers_the_measured_matrix`` on every branch
#: that has the function. Keeping the private probe on top of that would have
#: kept an empty ritual that still reads as coverage to a text scan — the exact
#: defect seedgo's own checker gained a live-file gate for this week.
UNKNOWN_TYPE_NOT_REFUSED: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Contracts: reading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_answers_a_default_for_a_document_that_does_not_exist(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """load_json never makes a caller handle "the file is not there".

    Mutant: seedgo's shim binds a load_json answering {} in apps/handlers/json/json_handler.py — killed.

    Pinned because the alternative shapes are both real: raising forces every
    call site to wrap a try/except it will eventually forget, and returning
    None forces an ``is None`` guard the fleet demonstrably does not write.
    Measured true on all eighteen implementations, in both calling families.
    """
    module = implementation(branch)
    if required_positionals(module.load_json) == 2:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        answer = module.load_json("never_written", "data")
    else:
        answer = module.load_json(str(tmp_path / "never_written.json"))
    assert answer is not None, f"{branch}: load_json returned None for a missing document"
    # The default is a data document, not merely something: every family measured
    # 2026-09-27 answers a dict carrying both of the data document's dates.
    assert {"created", "last_updated"} - set(answer) == set(), (
        f"{branch}: load_json's default for a missing data document is {answer!r}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_default_has_the_container_type_the_json_type_promises(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A missing "log" reads back as a list and a missing "data" as a dict.

    This is the contract that makes the previous one useful. A caller writing
    ``for entry in load_json(name, "log")`` must not be handed a dict, and
    ``load_json(name, "data")["k"]`` must not be handed a list. Measured
    identical on all seventeen document-addressed implementations.

    THE SHAPE IS NOT THE WHOLE CLAIM, and pinning only the shape was the defect
    here: `isinstance(x, dict)` passes for any dict of garbage, so a handler
    that answered `{}` to every read satisfied all three lines. What the fleet
    also agrees on was re-measured on 2026-09-07 across all 22 discovered
    handlers and is asserted below — an absent log reads back EMPTY rather than
    as some salvaged remnant, and the mapping default for "config" is a
    template ADDRESSED to the document that was asked for. The rest of the
    "data" key set still diverges (two key sets across the fleet) and stays
    deliberately unpinned.
    """
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
    """load_json is not a pure read: it creates the file it did not find.

    Callers should know this. A "read" that writes means a monitoring loop
    polling a branch's documents populates that branch's directory, a
    read-only audit is not read-only, and a filesystem that is full or
    read-only turns a lookup into a failure. Measured on all seventeen
    document-addressed handlers; ``backup``'s path-addressed load_json is the
    one that does NOT do this and is skipped, not silently counted as agreeing.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, documents = prepared(branch, tmp_path, monkeypatch)
    module.load_json("read_only_please", "data")
    assert (documents / "read_only_please_data.json").exists(), (
        f"{branch}: load_json did not create the document — the fleet's other handlers do"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_survives_a_corrupt_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Unparseable bytes on disk do not become an exception in the caller.

    A half-written document is the normal end state of a killed process, and
    every one of these handlers is read on a startup path. Measured on all
    eighteen: none raise, and each answers with a usable container of the right
    type. What they do to the corrupt bytes differs and is not pinned here —
    ``backup`` renames the file aside, the document-addressed family
    regenerates a blank template over it.
    """
    module = implementation(branch)
    if required_positionals(module.load_json) == 2:
        module, documents = prepared(branch, tmp_path, monkeypatch)
        (documents / "corrupt_config.json").write_text("{not json at all", encoding="utf-8")
        answer = module.load_json("corrupt", "config")
        # WHAT it regenerates, not merely that the answer has a type. Measured
        # 2026-09-07 on all 22 discovered handlers: the replacement is a blank
        # template addressed to the document that was asked for, so a handler
        # that "recovered" by handing back some other document's contents, or
        # an empty dict, fails here instead of passing the isinstance below.
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


# ---------------------------------------------------------------------------
# Contracts: writing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_then_load_json_returns_the_same_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The round trip every caller of save_json is relying on.

    Nested dicts, lists and mixed scalars go in and come back equal. Measured
    true on all eighteen. The payload is config-shaped on purpose: the shared
    validator rejects an arbitrary dict for the config and data types, so a
    junk payload would have measured the validator, not the round trip. Both
    stored container kinds are exercised — a mapping under "config" and a list
    under "log" — because the "data" type is the one the fleet rewrites on the
    way through, and that behaviour is pinned separately rather than smuggled
    in here as a weakened round trip.
    """
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
    """Saving a "data" document MUTATES the dict the caller handed in.

    Not a detail — a caller that saves the same dict to two branches, or
    compares its in-memory copy against what it passed, gets a value it never
    wrote. It is surprising enough that it deserves to be written down, and it
    is one of the few behaviours all seventeen document-addressed handlers
    genuinely share, so it is pinned as the contract it is rather than left as
    folklore. The stamp lands on "data" only; "config" and "log" are untouched,
    which the two negative assertions hold.
    """
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
    """A first write on a fresh checkout must not lose the document.

    THE SHARPEST DIVERGENCE IN THE FLEET, and the reason this suite exists.
    Nine implementations create the directory and persist. Five return False
    and write nothing. Four raise FileNotFoundError out of the staging file.
    A caller cannot write one correct call site against three dispositions, and
    two of the three lose data on the exact path a new branch takes first.

    The nine divergent branches are xfail(strict) with their measured
    disposition in the reason; repairing one turns its line red here so the
    table gets updated rather than quietly rotting.
    """
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


# ---------------------------------------------------------------------------
# Contracts: addressing
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized(GET_JSON_PATH_TYPE))
def test_get_json_path_answers_a_pathlib_path(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """get_json_path hands back a Path, so ``.parent`` and ``/`` work on it.

    Sixteen of the seventeen implementations that have the function return
    ``pathlib.Path``; ``commons`` returns ``str`` from ``os.path.join`` and is
    xfail(strict) with that reason. The split matters because call sites
    written against one branch's handler are copied to the next: ``.parent``,
    ``.exists()`` and ``/`` are all AttributeErrors on the str form, and
    ``str(path)`` is a silent no-op on the Path form, so nothing warns.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    resolver = expose(module, branch, "get_json_path")
    module, documents = prepared(branch, tmp_path, monkeypatch)
    answer = resolver("addressed", "config")
    assert isinstance(answer, Path)
    # The Path-only surface ANSWERED, not merely typed. `.parts` is an
    # AttributeError on the str form, so this reads the split the call sites
    # rely on and pins the two tail segments it comes back with — the document
    # directory the handler itself named, and the file inside it. Measured
    # 2026-09-07 on every branch that has the function.
    assert answer.parts[-2:] == (documents.name, "addressed_config.json"), (
        f"{branch}: get_json_path resolved to {answer} — expected it inside {documents}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_get_json_path_names_the_document_module_underscore_type(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The filename convention every glob over a branch's documents assumes.

    ``get_json_path(module, json_type)`` resolves to ``<module>_<type>.json``
    directly inside the branch's document directory — no subdirectory, no
    pluralisation, no prefix. Tooling that lists a branch's state (audits,
    backups, the dashboards) reconstructs these names instead of calling the
    handler, so the convention is load-bearing outside the handler itself.
    Measured identical on all seventeen document-addressed implementations,
    including the one that returns the name as a str.
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
    """The one function the fleet did not manage to diverge on.

    Ten cases — the required keys for config and data, list-ness for log, three
    non-mapping inputs and an unknown json_type — answered identically, and
    always as a real ``bool``, by every implementation that has
    ``validate_json_structure``. Sixteen of eighteen when this was written;
    seventeen on 2026-09-03, because ``backup`` swept to the shim and the
    service exposes it. Only ``ai_mail`` still lacks it, and skips.
    Worth pinning precisely because it is the shared rule ``save_json``
    enforces: the acceptance boundary is the same everywhere even though what
    happens at the boundary is not.
    """
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


# ---------------------------------------------------------------------------
# Contracts: the metrics surface (RETIRED 2026-09-04, pair 6 — subject gone)
# ---------------------------------------------------------------------------
#
# ``test_increment_counter_accumulates_into_the_modules_data_document`` and
# ``test_update_data_metrics_persists_arbitrary_metric_keys`` lived here. Both
# are gone, by the same subject-gone rule that retired
# ``UNKNOWN_TYPE_NOT_REFUSED``: they were the last two tests in this file that
# measured NOTHING. Standing on the finished sweep they reported 18 skipped and
# 0 measurements each — every skip reading "<branch> does not expose ... — its
# json_handler has no such entry point" — which is a pair of tests announcing a
# surface no longer in the fleet.
#
# Measured 2026-09-04 across the whole tree, excluding .archive: zero
# definitions and zero production callers of either name. The one service binds
# nine names and neither is among them; the six handlers that used to carry
# them were archived branch by branch as the sweep reached them, the last two
# (commons, daemon) on pair 5, api's on this one.
#
# Retired rather than kept skipping on purpose. A test that can only skip reads
# like coverage from the outside — it is a row in the report and a green tick —
# while asserting nothing at all about anything that ships. If a metrics
# surface is ever wanted again it will be one implementation in the service,
# and its contract belongs where the other service contracts in this file are,
# not resurrected here.


# ---------------------------------------------------------------------------
# The suite's own floor
# ---------------------------------------------------------------------------


def test_discovery_finds_every_shipped_handler_and_names_no_branch_itself():
    """Discovery is a roster, so a new citizen is covered without editing this file.

    Guards the mechanism the rest of the file stands on: if discovery silently
    matched nothing, every parametrized contract above would collect zero cases
    and the run would be green while measuring nothing. Pins a floor rather
    than a count, so adding or retiring a citizen does not turn this red, and
    checks that each discovered name really has a handler at the path the
    roster gave for it.

    The floor is the INSTALLED package, not the roster: those 18 are the
    package this suite is imported from and are always reachable, while a
    resident's tree may simply not be on this machine.
    """
    assert len(BRANCHES) >= 2, f"json_handler discovery found {BRANCHES} under {PACKAGE_ROOT}"
    assert len(set(BRANCHES)) == len(BRANCHES)
    assert set(_installed_roster()) <= set(BRANCHES), "widening discovery must never lose an installed citizen"
    for branch in BRANCHES:
        assert handler_path(branch).is_file()


def test_one_branch_is_one_module_however_many_times_it_is_asked_for():
    """``implementation`` must be idempotent, or the redirect covers nothing.

    THE SAFETY PROPERTY OF THE WHOLE WIDENING, and it was learned by breaking
    it. A resident is loaded from its file rather than by dotted name, and the
    first draft of that loader built a NEW module on every call. Contracts that
    capture a function from one call (``expose(module, ...)``) and redirect
    another (``prepared(...)``) then redirect a module nobody writes through:
    on 2026-09-07 that ran the write contracts against four Vera-Studio
    citizens' LIVE document directories and left 23 default-template documents
    in each. ``importlib`` caches; so must this.

    THE TWO HANDLES ARE TAKEN INDEPENDENTLY, into named variables, because
    ``implementation(branch) is implementation(branch)`` written as one
    expression compares a thing to itself as far as any reader — or any static
    check — can tell, and would read as a real claim while making none. The
    floor above the loop is the same floor the discovery test uses and for the
    same reason: an empty roster would walk this loop zero times and report
    green, which is precisely the silent pass that let the Vera-Studio writes
    happen. 22 citizens discovered on this tree, 2026-09-07; the floor stays a
    floor so retiring one does not turn this red.
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

    This is the safety property the whole suite rests on: ``redirected`` asks
    the implementation's own ``get_json_path`` where the next write will land
    and skips when the answer is outside tmp_path. Verified here for all
    discovered branches at once, so a branch that grows a new, unmatched
    document-directory binding is caught by a failing test instead of by a
    modified file in someone's working tree.

    Each branch is checked against ITS OWN target, never merely against
    tmp_path: the autouse quarantine has already moved every handler somewhere
    under tmp_path, so the looser assertion would hold even if
    ``redirect_documents`` did nothing at all — a green line proving nothing.
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
    """The two entry points the whole fleet does share, under either convention.

    Everything else in this file is parametrized-with-skips because the surface
    diverges; this pins the floor that does not. Reading and writing a document
    are present on all eighteen — under two different signatures, which is why
    the arity is recorded here as one of exactly two known conventions rather
    than asserted to be a single number.
    """
    conventions = {}
    for branch in BRANCHES:
        module = implementation(branch)
        assert callable(getattr(module, "load_json", None)), f"{branch} has no load_json"
        assert callable(getattr(module, "save_json", None)), f"{branch} has no save_json"
        conventions[branch] = required_positionals(module.load_json)
    unknown = {b: n for b, n in conventions.items() if n not in (1, 2)}
    assert not unknown, f"unrecognised load_json calling convention: {unknown}"


def test_the_divergence_tables_only_name_branches_that_still_exist():
    """A retired branch must not leave a stale xfail behind.

    An xfail(strict) entry for a branch that no longer ships is dead weight
    that reads like a live finding. It cannot fail on its own — ``parametrized``
    only consults the table for branches the glob found — so it is checked
    directly against the discovered set. Names json.dumps only to keep the
    failure message readable.
    """
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
