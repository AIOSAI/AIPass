"""One contract suite over every ``json_handler`` the fleet ships.

WHY THIS FILE EXISTS. The campaign premise was "shared infrastructure tested N
times". Measurement refused it: the branch handlers were stamped once and every
copy then diverged. Eighteen files, eighteen distinct hashes, 28 to 592 lines,
and no single function present in all eighteen with the same shape. So this is
not a suite that asserts they are the same. It is a suite that asserts what is
TRUE of each, names every place they disagree, and refuses to hide a
disagreement behind an assertion weak enough to pass everywhere.

HOW DIVERGENCE IS REPORTED. Three mechanisms, never silence:

* ``pytest.skip`` with a message naming the branch and the missing function,
  for a surface a branch simply does not have (``ai_mail`` has no
  ``validate_json_structure``; ``backup`` addresses documents by path, so every
  ``module_name``/``json_type`` contract is inapplicable there, not passing).
* ``pytest.mark.xfail(strict=True)`` carrying the MEASURED reason, for a branch
  that has the function and answers differently from the fleet majority. Strict
  on purpose: when a branch is repaired the xfail turns into a failure that
  says "update the divergence table", instead of a green line nobody rereads.
* A plain assertion for everything the fleet genuinely agrees on.

DISCOVERY IS DYNAMIC. The branch list is globbed from the installed ``aipass``
package, never written down. A nineteenth branch is picked up with no edit here
and is held to the majority contract; a deleted branch disappears from the run
instead of breaking it. Only the divergence tables name branches, because a
measurement record has to name its subjects.

SAFETY. Every implementation is redirected at ``tmp_path`` before any call that
could write, and the redirect is VERIFIED through the implementation's own
``get_json_path`` before the first write. A branch whose directory cannot be
redirected is skipped, loudly — this suite never writes into a live branch tree.
Redirecting only the subject was NOT enough and the difference was measured,
not guessed: see ``quarantined_document_directories`` for the syscall audit and
the exact cross-branch chain it closes.
"""

# =================== META ====================
# Name: test_json_handler_contract.py
# Description: Fleet-wide contract suite over every branch json_handler
# Version: 1.0.0
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

import copy
import importlib
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

import aipass

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

#: The installed package directory, so the suite runs identically whichever
#: rootdir pytest picks (branch-local or repo-root).
PACKAGE_ROOT = Path(aipass.__file__).resolve().parent

#: Every branch that ships the canonical handler path, in stable order.
BRANCHES = sorted(path.parents[3].name for path in PACKAGE_ROOT.glob("*/apps/handlers/json/json_handler.py"))


def implementation(branch: str) -> Any:
    """Import one branch's ``json_handler`` module.

    Args:
        branch: Directory name under the ``aipass`` package.

    Returns:
        The imported module.
    """
    return importlib.import_module(f"aipass.{branch}.apps.handlers.json.json_handler")


def parametrized(divergences: Mapping[str, str] | None = None) -> list:
    """Build the per-branch argvalues, marking measured divergences xfail.

    Args:
        divergences: Branch name to the measured reason it disagrees with the
            fleet majority. A branch absent from the mapping — including one
            that did not exist when the table was measured — is held to the
            contract.

    Returns:
        ``pytest.param`` values, one per discovered branch, id'd by branch name.
    """
    table = divergences or {}
    return [
        pytest.param(
            branch,
            id=branch,
            marks=[pytest.mark.xfail(reason=table[branch], strict=True)] if branch in table else [],
        )
        for branch in BRANCHES
    ]


# ---------------------------------------------------------------------------
# Measured divergence tables (2026-09-01, this tree)
# ---------------------------------------------------------------------------

#: ``save_json`` addressed at a directory that does not exist yet. Majority
#: (9 of 18, counting backup's path-addressed form) creates the directory and
#: persists. The rest split two ways, and BOTH ways lose the caller's document.
SAVE_JSON_MISSING_PARENT = {
    "ai_mail": "ai_mail's save_json returns False and writes nothing when the document directory is absent",
    "api": "api's save_json returns False and writes nothing when the document directory is absent",
    "flow": "flow's save_json returns False and writes nothing when the document directory is absent",
    "prax": "prax's save_json returns False and writes nothing when the document directory is absent",
    "skills": "skills's save_json returns False and writes nothing when the document directory is absent",
    "cli": "cli's save_json raises FileNotFoundError from the staging file when the document directory is absent",
    "commons": "commons save_json raises FileNotFoundError from the staging file when the directory is absent",
    "hooks": "hooks's save_json raises FileNotFoundError from the staging file when the document directory is absent",
    "seedgo": "seedgo's save_json raises FileNotFoundError from the staging file when the document directory is absent",
}

#: ``get_json_path`` return type. Sixteen of seventeen answer ``pathlib.Path``.
GET_JSON_PATH_TYPE = {
    "commons": "commons's get_json_path returns str (os.path.join), not Path — callers doing .parent or / break",
}


# ---------------------------------------------------------------------------
# Payloads. Shaped to satisfy the fleet's shared validate_json_structure, so a
# rejected write means the WRITE diverged, not that the payload was junk.
# ---------------------------------------------------------------------------

CONFIG_PAYLOAD = {
    "module_name": "contract_probe",
    "version": "1.0.0",
    "config": {"max_log_entries": 50, "nested": {"values": [1, 2, 3]}},
}
DATA_PAYLOAD = {"created": "2020-01-01", "last_updated": "2020-01-02", "counters": {"seen": 7}}
LOG_PAYLOAD = [{"timestamp": "2020-01-01T00:00:00", "operation": "contract_probe"}]

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
)


# ---------------------------------------------------------------------------
# Family detection and skips
# ---------------------------------------------------------------------------


def required_positionals(function: Callable) -> int:
    """Count the parameters a caller must supply positionally.

    Args:
        function: Any handler entry point.

    Returns:
        Number of positional parameters without a default.
    """
    parameters = inspect.signature(function).parameters.values()
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return sum(1 for p in parameters if p.kind in positional and p.default is p.empty)


def expose(module: Any, branch: str, name: str) -> Callable:
    """Fetch a handler function or skip with the branch and function named.

    A silent pass here would report "18 green" over a surface half the fleet
    does not have. The skip line is the measurement.

    Args:
        module: The branch's imported json_handler.
        branch: Branch name, for the message.
        name: Function the caller needs.

    Returns:
        The function.
    """
    function = getattr(module, name, None)
    if function is None:
        pytest.skip(f"{branch} does not expose {name} — its json_handler has no such entry point")
    return function


def require_document_addressing(module: Any, branch: str) -> None:
    """Skip branches whose handler addresses documents by filesystem path.

    Two calling conventions exist in the fleet. Sixteen-plus branches take
    ``(module_name, json_type)`` and resolve the path themselves; ``backup``
    takes a path and owns none of that resolution. Contracts about json_type
    defaults or document naming are inapplicable to the second family — not
    passing, inapplicable.

    Args:
        module: The branch's imported json_handler.
        branch: Branch name, for the message.
    """
    if required_positionals(module.load_json) != 2:
        pytest.skip(
            f"{branch}'s json_handler is the PATH-ADDRESSED family — "
            f"load_json{inspect.signature(module.load_json)} takes a filesystem path, "
            f"so (module_name, json_type) contracts do not apply to it"
        )


# ---------------------------------------------------------------------------
# Redirection. Nothing writes until get_json_path itself confirms the redirect.
# ---------------------------------------------------------------------------


def namespaces_and_instances(module: Any) -> tuple[list[dict], list[Any]]:
    """Every place one branch's handler could be holding its document directory.

    Three shapes exist and all three must be reachable from one helper, or the
    suite quietly stops covering the branches it cannot redirect:

    * module-level constants (``JSON_DIR``, ``FLOW_JSON_DIR``, ``BRANCH_JSON_DIR`` — the
      name is different on almost every branch, so it is matched, not spelled);
    * the DEFINING module's globals, reached through ``__globals__``, because
      ``ai_mail``'s canonical file re-exports from a ``json_utils`` package and
      its own same-named constant is never read by the functions it exports;
    * the instance dict behind a bound method, because ``canary``, ``memory``
      and ``spawn`` re-export the methods of one configured ``JsonHandler``.

    Args:
        module: The branch's imported json_handler.

    Returns:
        The namespaces to scan, and the bound-method owners to scan.
    """
    namespaces: list[dict] = [vars(module)]
    instances: list[Any] = []
    for name in ("load_json", "save_json", "get_json_path", "ensure_json_exists"):
        function = getattr(module, name, None)
        globals_ = getattr(function, "__globals__", None)
        if globals_ is not None and not any(globals_ is seen for seen in namespaces):
            namespaces.append(globals_)
        owner = getattr(function, "__self__", None)
        if owner is not None and not any(owner is seen for seen in instances):
            instances.append(owner)
    return namespaces, instances


def redirect_documents(module: Any, target: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Point every document-directory binding this handler reads at ``target``.

    The original value's type is preserved: one branch keeps a str and joins it
    with ``os.path.join``, so handing it a Path would test a different program
    than the one that ships.

    Args:
        module: The branch's imported json_handler.
        target: Directory under tmp_path to write into.
        monkeypatch: Restores every binding at teardown.
    """
    namespaces, instances = namespaces_and_instances(module)
    for namespace in namespaces:
        for key, value in list(namespace.items()):
            if "JSON_DIR" not in key.upper() or "IMPORT_TIME" in key.upper():
                continue
            if not isinstance(value, (str, Path)):
                continue
            monkeypatch.setitem(namespace, key, str(target) if isinstance(value, str) else Path(target))
    for owner in instances:
        for key, value in list(vars(owner).items()):
            if "json_dir" not in key.lower() or not isinstance(value, (str, Path)):
                continue
            monkeypatch.setitem(vars(owner), key, str(target) if isinstance(value, str) else Path(target))


def redirected(branch: str, target: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import a branch's handler, redirect it, and PROVE the redirect took.

    The proof is the implementation's own ``get_json_path``: whatever it now
    answers is where the next write lands. If that answer is still outside
    ``target`` the test skips rather than writing into a live branch tree — a
    contract suite that corrupts its subjects has no findings worth reading.

    Args:
        branch: Branch to load.
        target: Directory under tmp_path the documents must land in.
        monkeypatch: Passed through to the redirect.

    Returns:
        The redirected module.
    """
    module = implementation(branch)
    redirect_documents(module, target, monkeypatch)
    resolver = getattr(module, "get_json_path", None)
    if resolver is None:
        return module
    answer = Path(str(resolver("contract_probe", "data")))
    if not answer.is_relative_to(target):
        pytest.skip(
            f"{branch}: json_handler's document directory could not be redirected to tmp_path "
            f"(get_json_path still answers {answer}) — refusing to exercise writes against a live tree"
        )
    return module


def prepared(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Path]:
    """Redirected module plus an existing, empty document directory.

    Args:
        branch: Branch to load.
        tmp_path: pytest's per-test directory.
        monkeypatch: Passed through to the redirect.

    Returns:
        The module and the directory its documents now live in.
    """
    target = tmp_path / "documents"
    target.mkdir()
    return redirected(branch, target, monkeypatch), target


@pytest.fixture(autouse=True)
def quarantined_document_directories(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Redirect EVERY handler's document directory, not only the one under test.

    Closing a side channel that was found by auditing this suite's own syscalls
    rather than by reasoning about it. Measured chain, branch-local run,
    2026-09-01::

        test_load_json_survives_a_corrupt_document[ai_mail]
          -> ai_mail json_utils ensure_json_exists   (regenerating, so it warns)
          -> prax logger.warning -> _ensure_watcher
          -> trigger core.fire -> _ensure_initialized -> registry.setup_handlers
          -> TRIGGER's json_handler.log_operation
          -> mkdir + atomic rename inside src/aipass/trigger/trigger_json

    So provoking a diagnostic in the subject wrote into a THIRD branch's live
    document directory — through a path that never touches the subject's
    redirect, which is why per-subject redirection alone could not have caught
    it. Every discovered handler is redirected for the duration of every test;
    ``redirected`` then re-points the subject at its own directory, and because
    monkeypatch restores in reverse order both survive teardown intact.

    WHAT THIS DOES NOT CLOSE, stated rather than left to be rediscovered. The
    same logger boot also runs trigger's startup handler, which persists
    trigger's own state through ``trigger/apps/config.py::atomic_write_json`` —
    a writer that is not a json_handler and holds its own directory. One mkdir
    and one rename per pytest process still land there. Reaching into another
    branch's config module to silence it would couple this suite to the
    internals of a branch it does not test, so it is reported instead. It is
    pre-existing: the same events were measured under seedgo's existing
    test_json_durability.py, which imports no handler but this branch's.

    Args:
        tmp_path: pytest's per-test directory.
        monkeypatch: Restores every binding at teardown.
    """
    for branch in BRANCHES:
        redirect_documents(implementation(branch), tmp_path / "quarantine" / branch, monkeypatch)


# ---------------------------------------------------------------------------
# Contracts: reading
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_answers_a_default_for_a_document_that_does_not_exist(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """load_json never makes a caller handle "the file is not there".

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


@pytest.mark.parametrize("branch", parametrized())
def test_load_json_default_has_the_container_type_the_json_type_promises(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A missing "log" reads back as a list and a missing "data" as a dict.

    This is the contract that makes the previous one useful. A caller writing
    ``for entry in load_json(name, "log")`` must not be handed a dict, and
    ``load_json(name, "data")["k"]`` must not be handed a list. Measured
    identical on all seventeen document-addressed implementations, and it is
    the ONLY thing about the default they agree on: the actual default payload
    for "data" comes in five different key sets across the fleet, so the shape
    is pinned and the contents deliberately are not.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)
    assert isinstance(module.load_json("absent_config", "config"), dict)
    assert isinstance(module.load_json("absent_data", "data"), dict)
    assert isinstance(module.load_json("absent_log", "log"), list)


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
    module, _ = prepared(branch, tmp_path, monkeypatch)
    assert isinstance(resolver("addressed", "config"), Path)


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
    always as a real ``bool``, by all sixteen implementations that have
    ``validate_json_structure``. ``ai_mail`` and ``backup`` do not, and skip.
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
# Contracts: the metrics surface only a third of the fleet carries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized())
def test_increment_counter_accumulates_into_the_modules_data_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """increment_counter adds to what is already stored, and persists it.

    Six branches expose it; the other twelve skip with that named. The pin is
    accumulation, not assignment: a counter that overwrites instead of adding
    reads as "1" forever, and the default ``amount`` of 1 plus an explicit 4
    must land as 5 in the module's own data document — which is also where the
    contract says the value lives, so a caller can read it back with load_json
    instead of a second API.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    increment = expose(module, branch, "increment_counter")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    increment("metered", "requests")
    increment("metered", "requests", 4)
    assert module.load_json("metered", "data")["requests"] == 5


@pytest.mark.parametrize("branch", parametrized())
def test_update_data_metrics_persists_arbitrary_metric_keys(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """update_data_metrics writes caller-named keys into the data document.

    Same six branches. The pin is that the keyword names are the stored names —
    no namespacing, no coercion — because callers read them straight back out
    of the data document with load_json, and it must not disturb the keys the
    document already carries.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    update = expose(module, branch, "update_data_metrics")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    update("metered", widgets=9, label="green")
    stored = module.load_json("metered", "data")
    assert stored["widgets"] == 9
    assert stored["label"] == "green"
    assert "created" in stored, f"{branch}: update_data_metrics dropped the document's own keys"


# ---------------------------------------------------------------------------
# The suite's own floor
# ---------------------------------------------------------------------------


def test_discovery_finds_every_shipped_handler_and_names_no_branch_itself():
    """Discovery is a glob, so a new branch is covered without editing this file.

    Guards the mechanism the rest of the file stands on: if the glob silently
    matched nothing, every parametrized contract above would collect zero cases
    and the run would be green while measuring nothing. Pins a floor rather
    than a count, so adding or retiring a branch does not turn this red, and
    checks that each discovered name really is importable as a module path.
    """
    assert len(BRANCHES) >= 2, f"json_handler discovery found {BRANCHES} under {PACKAGE_ROOT}"
    assert len(set(BRANCHES)) == len(BRANCHES)
    for branch in BRANCHES:
        assert (PACKAGE_ROOT / branch / "apps" / "handlers" / "json" / "json_handler.py").is_file()


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
    stale = sorted((set(SAVE_JSON_MISSING_PARENT) | set(GET_JSON_PATH_TYPE)) - set(BRANCHES))
    assert not stale, f"divergence tables name branches that no longer exist: {json.dumps(stale)}"
