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

import contextlib
import copy
import errno
import importlib
import inspect
import json
import os
import tempfile
import threading
from pathlib import Path
from types import SimpleNamespace
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


#: The fleet's redirect seam, read by the one json service on every call. Set
#: at the top of every branch conftest; the contract re-points it per subject.
SERVICE_REDIRECT_ENV = "AIPASS_TEST_LOG_DIR"

#: The import line that makes a handler a shim over the one service
#: (DPLAN-0325 section 3). A file without it has not migrated yet.
SERVICE_IMPORT_MARKER = "from aipass.prax import json_handler"

#: The nine names the canonical shim binds, in the spec's order.
SHIM_PUBLIC_NAMES = (
    "read_json",
    "write_json",
    "validate_json_structure",
    "get_json_path",
    "ensure_json_exists",
    "ensure_module_jsons",
    "load_json",
    "save_json",
    "log_operation",
)


def handler_path(branch: str) -> Path:
    """Return the canonical handler file for *branch*."""
    return PACKAGE_ROOT / branch / "apps" / "handlers" / "json" / "json_handler.py"


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

    TWO SHAPES, because the fleet is mid-migration (DPLAN-0325). A pre-migration
    handler holds its document directory as a bound value, so it is redirected
    by rebinding that value. A migrated shim holds NOTHING: the service computes
    ``json_dir`` per call from the handle's ``branch_root`` and the
    ``AIPASS_TEST_LOG_DIR`` seam, so there is no directory to rebind and the
    old loop finds nothing to do. That is not a safe no-op — it is a suite that
    quietly stops redirecting the branch it is about to write through, which is
    how prax's landing turned the floor test red the same night. Both the root
    and the env seam are pointed at ``target`` so the answer is the same whether
    or not the environment carries a redirect.

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
        if isinstance(vars(owner).get("branch_root"), Path):
            # The seam only — the handle's root stays real. The service composes
            # ``<env>/<root.name>/<root.name>_json``, so pointing the env at
            # ``target`` already lands the write under it, and leaving the root
            # alone keeps the identity axis below reading the shipped value
            # rather than one this helper wrote.
            monkeypatch.setenv(SERVICE_REDIRECT_ENV, str(target))


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

    The second value is the directory the implementation ITSELF says it will
    write to, not the one this helper asked for. The two were the same for
    every pre-migration handler, because each held its document directory as a
    single bound value. A migrated shim composes ``<seam>/<branch>/<branch>_json``
    inside the service, so the requested root is the parent of a parent — and a
    helper that kept returning the request would have made six contracts assert
    against a directory nothing writes to.

    Args:
        branch: Branch to load.
        tmp_path: pytest's per-test directory.
        monkeypatch: Passed through to the redirect.

    Returns:
        The module and the directory its documents now live in.
    """
    target = tmp_path / "documents"
    target.mkdir()
    module = redirected(branch, target, monkeypatch)
    resolver = getattr(module, "get_json_path", None)
    if resolver is None:
        return module, target
    documents = Path(str(resolver("contract_probe", "data"))).parent
    documents.mkdir(parents=True, exist_ok=True)
    return module, documents


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
    assert not stale, f"divergence tables name branches that no longer exist: {json.dumps(stale)}"


# ---------------------------------------------------------------------------
# IDENTITY: a migrated shim IS the one service, it does not merely behave like it
# ---------------------------------------------------------------------------
#
# Every other contract in this file asks what a handler DOES. Behaviour cannot
# catch the one failure the migration makes possible: a branch that quietly
# keeps its own implementation behind a compatible signature stays green on all
# of them. ``is`` catches it, and nothing else does.
#
# It also catches the hazard measured on 2026-09-03 and put in the DPLAN: the
# service resolves the calling module at ``sys._getframe(2)``, so a shim that
# WRAPS (``def log_operation(...): return _h.log_operation(...)``) instead of
# BINDING (``log_operation = _h.log_operation``) adds exactly one frame and
# silently sends every log in that branch into ``json_handler_log.json``. A
# wrapper is a plain function with no ``__func__``, so it fails here loudly, on
# the branch that wrote it, instead of appearing weeks later as an orphan
# document with no config or data sibling.
#
# Skips are per branch and named: the sweep lands branch by branch, and a
# handler that has not migrated yet is not a shim to be judged.


def json_service_or_skip() -> Any:
    """Return the one json service, or skip when prax has not published it.

    Returns:
        The ``aipass.prax.json_handler`` service module.
    """
    service = getattr(importlib.import_module("aipass.prax"), "json_handler", None)
    if service is None:
        pytest.skip(
            "aipass.prax exposes no json_handler attribute yet — the one service "
            "(DPLAN-0325) has not landed, so there is no identity to assert"
        )
    return service


def shim_or_skip(branch: str) -> Any:
    """Return *branch*'s handler when it has migrated, else skip naming it.

    The discriminator is the file, not the module: a handler that does not
    import the service has not migrated and asserting identity against it would
    report the sweep's progress as a defect. A handler that DOES import it is
    judged strictly, wrapper included — that is the whole point of the axis.

    Args:
        branch: Branch to load.

    Returns:
        The branch's imported json_handler module.
    """
    source = handler_path(branch).read_text(encoding="utf-8")
    if SERVICE_IMPORT_MARKER not in source:
        pytest.skip(f"{branch} has not migrated to the one service yet — its handler does not import it")
    return implementation(branch)


@pytest.mark.parametrize("branch", parametrized())
def test_every_public_name_in_a_migrated_shim_is_the_services_own_function(branch: str):
    """Each bound name IS ``JsonHandle``'s method, not a copy that behaves like it.

    ``__func__`` is the discriminator that survives everything a compatible
    re-implementation can do: a fork with the same signature, the same return
    type and the same measured behaviour still fails, because it is a different
    object. A ``def`` wrapper fails on the same line for a different reason —
    it has no ``__func__`` at all.
    """
    service = json_service_or_skip()
    module = shim_or_skip(branch)

    wrong = []
    for name in SHIM_PUBLIC_NAMES:
        bound = getattr(module, name, None)
        if bound is None:
            wrong.append(f"{name}: absent")
            continue
        own = getattr(bound, "__func__", None)
        if own is None:
            wrong.append(f"{name}: a plain function, so the shim WRAPS instead of binding (frame depth shifts)")
        elif own is not getattr(service.JsonHandle, name, None):
            wrong.append(f"{name}: bound to {own!r}, not the service's own method")
    assert not wrong, f"{branch}'s shim does not bind the one service: {wrong}"


@pytest.mark.parametrize("branch", parametrized())
def test_a_migrated_shim_binds_one_handle_rooted_at_its_own_branch(branch: str):
    """All nine names share one handle, and its root is the shim's own branch.

    Two properties in one assertion because they are one mistake: a shim that
    builds a handle per name, or binds a handle rooted somewhere else, writes
    another branch's documents while passing every behavioural contract above.
    The root is checked against ``parents[3]`` of the shim's own path, which is
    what ``for_module(__file__)`` is specified to compute.
    """
    json_service_or_skip()
    module = shim_or_skip(branch)

    handles = {id(getattr(module, name).__self__) for name in SHIM_PUBLIC_NAMES if hasattr(module, name)}
    assert len(handles) == 1, f"{branch} binds {len(handles)} handles across its nine names, expected one"

    handle = getattr(module, "save_json").__self__
    expected_root = handler_path(branch).parents[3]
    assert handle.branch_root == expected_root, (
        f"{branch}'s handle is rooted at {handle.branch_root}, not at its own branch {expected_root}"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_a_migrated_shim_reads_the_redirect_seam_after_import_not_at_import(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Setting the env var AFTER import redirects the NEXT call.

    The property that makes the whole fleet's test isolation work, and the one
    three of the four pre-migration shims did not have: they built the handler
    at module scope, so the directory was captured at import and nothing that
    ran later could move it. Measured cost of that shape elsewhere in the fleet
    — writes into live document directories during a suite run — is why this is
    pinned per branch rather than once on the service.

    The answer is checked for the branch's OWN name under the new root, so a
    service that honoured the seam but composed the wrong directory fails too.
    """
    json_service_or_skip()
    module = shim_or_skip(branch)

    resolver = getattr(module, "get_json_path", None)
    assert resolver is not None, f"{branch}'s shim exposes no get_json_path"

    elsewhere = tmp_path / "redirected_after_import"
    monkeypatch.setenv(SERVICE_REDIRECT_ENV, str(elsewhere))
    answer = Path(str(resolver("identity_probe", "data")))

    expected = elsewhere / branch / f"{branch}_json" / "identity_probe_data.json"
    assert answer == expected, f"{branch}: the seam set after import answered {answer}, expected {expected}"


# ---------------------------------------------------------------------------
# Durability discovery: every module that ships the bounded replace helper
# ---------------------------------------------------------------------------

#: The last step of every atomic write in the fleet: rename the staged file
#: over the live document, tolerating the sharing violation a concurrent
#: Windows reader causes, bounded so a permanently blocked target still fails.
RETRY_HELPER = "_replace_with_retry"

#: Both spellings the fleet uses for it. The private one is the majority;
#: ``trigger`` exports the same helper PUBLICLY from its config module, on
#: purpose and documented there, because that module is its shared helper home
#: and another module imports the name. Matching only the private spelling is
#: how slice 2 reported fourteen implementations when there are fifteen — a
#: scan keyed to the majority's naming cannot see the one that renamed itself.
RETRY_HELPER_NAMES = ("_replace_with_retry", "replace_with_retry")

#: Path parts that mean "not shipped code". A suite copy names the same symbol
#: while monkeypatching it, and an archived file is on no import path; either
#: one would enter the parametrization as an implementation that is not one.
UNSHIPPED_PARTS = frozenset({"tests", "test", ".archive", "__pycache__", ".sorting_unprocessed"})


def ships_retry_helper(path: Path) -> bool:
    """Whether a package file defines the replace helper itself.

    Args:
        path: A ``.py`` file found under :data:`PACKAGE_ROOT`.

    Returns:
        True when the file is shipped code that contains the definition.
    """
    if UNSHIPPED_PARTS.intersection(path.parts):
        return False
    source = path.read_text(encoding="utf-8", errors="ignore")
    return any(f"def {name}(" in source for name in RETRY_HELPER_NAMES)


def retry_label(relative: Path) -> str:
    """A short, stable test id for one implementation.

    Args:
        relative: Implementation path relative to :data:`PACKAGE_ROOT`.

    Returns:
        The bare branch name for an implementation at the canonical handler
        location, and the full relative path for one living anywhere else.
        Deliberately verbose for the second kind rather than
        ``branch/stem``: that shorter form renders the shared module as
        ``aipass/json_handler``, which reads like the aipass BRANCH's handler
        — a label that misnames its subject is worse in a failure message
        than a long one.
    """
    canonical = relative.parts[1:] == ("apps", "handlers", "json", "json_handler.py")
    return relative.parts[0] if canonical else relative.with_suffix("").as_posix()


#: Label to dotted module path for every implementation the package ships.
#:
#: An ``rglob`` over the package rather than the two globs that would find the
#: known families, and the difference is a measurement rather than a
#: preference: globbing ``*/apps/handlers/json/json_handler.py`` plus the
#: shared module finds most of them and misses ``spawn/atomic_write``, a copy
#: of the same helper under a name no handler glob matches.
#: Discovery narrow enough to confirm the list it was handed cannot report the
#: implementation nobody listed.
#:
#: The count is a MEASUREMENT and it is falling: sixteen on 2026-09-02,
#: fourteen on 2026-09-03 after the second sweep pair, eight on 2026-09-04
#: with fifteen of eighteen swept, six after pair 5 took commons and daemon,
#: and FIVE after pair 6 took api — the last branch handler with a retry helper
#: of its own. It did not fall when prax migrated — prax's helper MOVED into
#: ``json_service``, it did not disappear.
#:
#: NO BRANCH HANDLER IS ON THIS LIST ANY MORE. The five standing are
#: ``aipass/shared/json_handler`` (the file @aipass retires under FPLAN-0489),
#: ``hooks/apps/handlers/json/files``, the service itself,
#: ``spawn/atomic_write`` and ``trigger/apps/config``. Four of those are the
#: floor: modules that own a bounded rename for their own reasons and are not
#: json handlers. The number falls to four when FPLAN-0489 lands. No number is
#: asserted here; the floor below is, so a sweep that removes a copy cannot
#: turn this red.
RETRY_IMPLEMENTATIONS = {
    retry_label(path.relative_to(PACKAGE_ROOT)): "aipass."
    + ".".join(path.relative_to(PACKAGE_ROOT).with_suffix("").parts)
    for path in sorted(PACKAGE_ROOT.rglob("*.py"))
    if ships_retry_helper(path)
}

#: One param per implementation, and deliberately no divergence table beside
#: it. Every body was measured assertion-identical on 2026-09-02
#: (docstring wording aside), so a disagreement discovered here is news, not a
#: known variation to be marked down in advance.
RETRY_PARAMS = [pytest.param(label, id=label) for label in RETRY_IMPLEMENTATIONS]


def retry_implementation(label: str) -> Any:
    """Import one implementation by its discovery label.

    Args:
        label: A key of :data:`RETRY_IMPLEMENTATIONS`.

    Returns:
        The imported module.
    """
    return importlib.import_module(RETRY_IMPLEMENTATIONS[label])


def retry_helper_of(module: Any) -> Callable | None:
    """The bounded replace helper a module ships, under either spelling.

    Args:
        module: A discovered implementation.

    Returns:
        The callable, or None when the module ships neither spelling.
    """
    for name in RETRY_HELPER_NAMES:
        candidate = getattr(module, name, None)
        if callable(candidate):
            return candidate
    return None


def retry_helper_name(module: Any) -> str:
    """The spelling one module actually uses, for failure messages.

    Args:
        module: A discovered implementation.

    Returns:
        The attribute name found, or the majority spelling when neither is.
    """
    for name in RETRY_HELPER_NAMES:
        if callable(getattr(module, name, None)):
            return name
    return RETRY_HELPER


def require_retry_helper(module: Any, label: str) -> Callable:
    """The module's bounded helper, or a failure naming the module.

    Discovery only admits modules that ship one, so a miss here means
    discovery and reality disagree — which is a red, not an Optional the
    call sites should each re-check.

    Args:
        module: A discovered implementation.
        label: Discovery label, for the message.

    Returns:
        The bounded replace helper.
    """
    helper = retry_helper_of(module)
    assert helper is not None, f"{label}: discovered as an implementation but ships no bounded replace helper"
    return helper


def isolated_replace(module: Any, monkeypatch: pytest.MonkeyPatch, replace: Callable) -> list:
    """Point ONE module's ``os.replace`` and ``time.sleep`` at test doubles.

    Patches the module's own ``os`` and ``time`` bindings, never the shared
    ``os`` and ``time`` modules. The distinction is not cosmetic and was paid
    for once already in this fleet: patching ``sleep`` on the shared ``time``
    module reaches every thread in the process, so a full-suite run collected
    durations belonging to other tests and the wait pin failed intermittently
    (spawn, 2026-08-30). Fourteen implementations import those same two
    modules, which would make a shared-module patch a channel between
    parameters here as well as between files.

    The stub carries ``sleep`` and nothing else, and that narrowness is the
    point. The one service names its staged files from ``os.getpid()`` and an
    ``itertools.count()``, deliberately not from the clock, and says why in
    ``json_service.py`` (08359ec2): a caller stubbing ``time`` to take the wait
    out of the bounded retry is a legitimate thing to do, and a writer that
    cannot name a file under a stubbed clock would be failing for a reason that
    has nothing to do with writing. ``sleep`` is therefore the whole surface
    this helper has to stand in for.

    Keeping the stub strict makes it a detector. If an implementation ever
    reaches for a second ``time`` attribute, this raises ``AttributeError``
    where it happens instead of quietly accepting a new clock dependency the
    contract never agreed to — which is what a delegating stub would do. I
    briefly delegated ``time_ns`` here on 2026-09-04 after seeing exactly that
    AttributeError across all fifteen migrated branches; the cause was an
    intermediate state of the service being edited in parallel, not the surface
    as it shipped, so the delegation is gone and the pin stands.

    Args:
        module: The implementation under test.
        monkeypatch: Restores both bindings at teardown.
        replace: Stands in for ``os.replace``.

    Returns:
        The list each ``time.sleep`` duration is appended to, in order.
    """
    sleeps: list[float] = []
    monkeypatch.setattr(module, "os", SimpleNamespace(replace=replace))
    monkeypatch.setattr(module, "time", SimpleNamespace(sleep=sleeps.append))
    return sleeps


def sharing_violation(destination: Any) -> PermissionError:
    """The error Windows raises when a reader still holds the target open.

    Args:
        destination: The live document being replaced.

    Returns:
        A ``PermissionError`` shaped like the real one, errno 13.
    """
    return PermissionError(13, "sharing violation", str(destination))


# ---------------------------------------------------------------------------
# Contracts: durability of the bounded replace helper
# ---------------------------------------------------------------------------
#
# These six ran as thirty-seven separate copies in seven branches before this
# file existed, one set per implementation, because each copy exercised a
# DIFFERENT module. Nothing is asserted more weakly here to make one contract
# cover fourteen: every copy's assertions are kept verbatim, and the module
# they run against is the parameter. Pure monkeypatch and ``tmp_path``, no
# platform branch and no skip, so the Windows CI leg runs the same fourteen
# cases as the POSIX legs — which matters, because the behaviour being pinned
# only ever misbehaves on Windows.


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_is_declared_bounded_and_patient(label: str):
    """The helper exists, retries more than once, and waits a nonzero time.

    The two constants are pinned as well as the function because either one
    alone defeats it: a single attempt is not a retry, and a zero backoff is a
    busy spin that finishes before the reader handle it exists to outlast.
    """
    module = retry_implementation(label)
    assert retry_helper_of(module) is not None, (
        f"{label}: no bounded replace helper — a Windows sharing violation still kills the write"
    )
    assert module._REPLACE_ATTEMPTS > 1, f"{label}: a single attempt is not a retry"
    assert module._REPLACE_BACKOFF_SECONDS > 0, f"{label}: a zero backoff spins instead of waiting"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_moves_the_staged_file_over_the_target(label: str, tmp_path: Path):
    """The happy path is still a plain move — the retry costs nothing idle.

    Runs against the real ``os.replace``: the point is that wrapping the
    syscall in a retry loop did not change what it does when nothing blocks.
    """
    module = retry_implementation(label)
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    require_retry_helper(module, label)(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new", f"{label}: the staged content did not land"
    assert not source.exists(), f"{label}: the staged file survived the move"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_helper_retries_through_a_transient_sharing_violation(
    label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Two sharing violations then success — the move still lands.

    The count is asserted exactly, not as "more than one": a helper that gave
    up and swallowed the error would leave the destination stale, and a helper
    that never engaged the retry would fail on the first call. Only three
    attempts describe the path this pin is named for.
    """
    module = retry_implementation(label)
    calls = {"count": 0}
    real_replace = os.replace

    def flaky_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        if calls["count"] <= 2:
            raise sharing_violation(destination)
        real_replace(source, destination)

    isolated_replace(module, monkeypatch, flaky_replace)
    source = tmp_path / "staged.tmp"
    source.write_text("new", encoding="utf-8")
    destination = tmp_path / "live.json"
    destination.write_text("old", encoding="utf-8")

    require_retry_helper(module, label)(str(source), str(destination))

    assert destination.read_text(encoding="utf-8") == "new", f"{label}: the retried move never landed"
    assert calls["count"] == 3, f"{label}: retry path never engaged"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_retry_is_bounded_and_raises_when_exhausted(
    label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A replace that never unblocks raises instead of retrying forever.

    Asserted against the module's own declared bound rather than a literal, so
    an implementation that tunes its attempt count stays covered and one that
    quietly stops honouring its own constant does not.
    """
    module = retry_implementation(label)
    calls = {"count": 0}

    def blocked_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        raise sharing_violation(destination)

    isolated_replace(module, monkeypatch, blocked_replace)

    with pytest.raises(PermissionError):
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert calls["count"] == module._REPLACE_ATTEMPTS, f"{label}: bound not honoured"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_the_replace_retry_waits_between_attempts(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The backoff is used, not merely declared.

    Deleting the sleep leaves a busy spin that passes every other pin above:
    it still retries, still bounds, still raises. But forty immediate attempts
    finish inside a microsecond and never outlast the reader handle the retry
    exists to wait out, so the retry stops being a fix and becomes decoration,
    and nothing else here would say so — the mutation survived a run on
    2026-08-18. Counting the sleeps pins the wait without asserting on
    wall-clock time, which would be flaky on a loaded runner.
    """
    module = retry_implementation(label)

    def blocked_replace(source: str, destination: str) -> None:
        raise sharing_violation(destination)

    sleeps = isolated_replace(module, monkeypatch, blocked_replace)

    with pytest.raises(PermissionError):
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    # One wait between each pair of attempts — never after the last, which raises.
    expected = [module._REPLACE_BACKOFF_SECONDS] * (module._REPLACE_ATTEMPTS - 1)
    assert sleeps == expected, f"{label}: the declared backoff was not slept"


@pytest.mark.parametrize("label", RETRY_PARAMS)
def test_a_non_permission_error_propagates_without_a_retry(label: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Only a sharing violation is worth waiting out.

    A cross-device rename or a full disk will not fix itself in 200ms, and
    retrying it forty times buys nothing but a slower failure and a longer
    wait before the caller learns what actually went wrong.
    """
    module = retry_implementation(label)
    calls = {"count": 0}

    def broken_replace(source: str, destination: str) -> None:
        calls["count"] += 1
        raise OSError(errno.EXDEV, "invalid cross-device link")

    isolated_replace(module, monkeypatch, broken_replace)

    with pytest.raises(OSError) as caught:
        require_retry_helper(module, label)(str(tmp_path / "staged.tmp"), str(tmp_path / "live.json"))

    assert caught.value.errno == errno.EXDEV, f"{label}: a different error surfaced"
    assert calls["count"] == 1, f"{label}: a non-sharing failure was retried"


def test_retry_discovery_finds_the_whole_package_and_names_no_module_itself():
    """Guards the mechanism the six contracts above stand on.

    If the scan silently matched nothing, all six would collect zero cases and
    the run would be green while measuring nothing at all — the failure mode
    that makes a consolidated suite more dangerous than the copies it
    replaced, since there is now one place to go quiet instead of seven. Pins
    a floor rather than a count so a new implementation does not turn this
    red, and checks every discovered label really imports.
    """
    assert len(RETRY_IMPLEMENTATIONS) >= 2, f"retry discovery found {RETRY_IMPLEMENTATIONS} under {PACKAGE_ROOT}"
    for label, dotted in RETRY_IMPLEMENTATIONS.items():
        module = importlib.import_module(dotted)
        assert retry_helper_of(module) is not None, f"{label}: discovered but exposes no bounded replace helper"


def test_every_canonical_handler_that_stages_a_write_also_retries_the_replace():
    """A handler that stages then renames must not do the rename unguarded.

    Discovery is a text scan, so it answers "who has the helper" but never
    "who should". This crosses it against the canonical handlers the rest of
    the file already found: a branch whose handler stages a temp file and then
    calls ``os.replace`` without the bounded helper has the exact defect the
    helper exists to fix, and would otherwise simply be absent from the
    parametrization above rather than reported by it.
    """
    unguarded = []
    for branch in BRANCHES:
        source = (PACKAGE_ROOT / branch / "apps" / "handlers" / "json" / "json_handler.py").read_text(encoding="utf-8")
        if "os.replace(" in source and not any(f"def {name}(" in source for name in RETRY_HELPER_NAMES):
            unguarded.append(branch)
    assert not unguarded, f"handlers calling os.replace with no bounded retry: {json.dumps(sorted(unguarded))}"


# ---------------------------------------------------------------------------
# The public writer and the helper underneath it
# ---------------------------------------------------------------------------


class CountingReplace:
    """An ``os`` stand-in that counts ``replace`` and forwards everything else.

    Installed on ONE module's own ``os`` binding, never on the shared ``os``
    module, for the reason slice 2 records: this suite's autouse fixture and
    the logger boot it documents both provoke writes in OTHER branches during
    a test, so a global counter would count a foreign rename as though the
    subject had made it — a false green in the exact test whose only job is to
    prove the subject renamed something.

    Everything but ``replace`` is delegated to the real module, because a
    writer stages with ``os.fdopen``, cleans up with ``os.unlink`` and asks
    ``os.path`` about its target; a stub carrying one attribute would break
    the write it is supposed to be observing.
    """

    def __init__(self, real: Any, calls: list, fail: Callable | None = None):
        """Wrap the real module.

        Args:
            real: The genuine ``os`` module.
            calls: Appended to on every ``replace``.
            fail: Called first on every ``replace``; may raise to simulate a
                blocked target. None means always perform the real move.
        """
        self._real = real
        self._calls = calls
        self._fail = fail

    def __getattr__(self, name: str) -> Any:
        """Delegate every attribute this class does not define.

        Args:
            name: Attribute the writer asked for.

        Returns:
            The real module's attribute.
        """
        return getattr(self._real, name)

    def replace(self, source: Any, destination: Any) -> None:
        """Count the rename, optionally fail it, otherwise perform it.

        Args:
            source: Staged file.
            destination: Live document.
        """
        self._calls.append((str(source), str(destination)))
        if self._fail is not None:
            self._fail(len(self._calls), destination)
        self._real.replace(source, destination)


def neighbouring_modules(module: Any) -> list:
    """Every module one hop out from what this one holds.

    Split out of :func:`retry_owner` so the search stays one loop deep. A
    writer reaches its rename through a function, a class or a re-exported
    module, and all three shapes occur in this fleet, so all three are
    followed.

    Args:
        module: Module to look outward from.

    Returns:
        Modules referenced by its globals, with duplicates and None left in
        for the caller's own seen-set to handle.
    """
    found = []
    for value in vars(module).values():
        if inspect.isfunction(value) or inspect.ismethod(value):
            found.append(inspect.getmodule(inspect.unwrap(value)))
        elif inspect.ismodule(value):
            found.append(value)
        elif inspect.isclass(value):
            found.append(inspect.getmodule(value))
    return found


def retry_owner(module: Any) -> Any:
    """The module that will actually perform this writer's rename.

    Not the same as the handler under test, and the difference is the whole
    reason this resolver exists rather than a hardcoded map:

    * twelve branches own the helper in their own json_handler;
    * ``aipass``, ``canary``, ``memory`` and ``spawn`` re-export a writer whose
      rename happens in ``aipass/shared/json_handler.py``;
    * ``trigger``'s writer delegates again, to ``trigger/apps/config.py``,
      which is also where its PUBLICLY named helper lives.

    So the search walks out from the module that defines ``save_json``,
    following the functions, classes and modules it holds, and stops at the
    first module shipping a bounded helper under either spelling.

    Args:
        module: A branch's imported json_handler.

    Returns:
        The owning module, or None when no bounded helper is reachable at all
        — which is a finding, not a gap in this search, and is reported as a
        named divergence rather than a skip.
    """
    start = inspect.getmodule(inspect.unwrap(module.save_json))
    seen: set[str] = set()
    queue = [start]
    while queue:
        candidate = queue.pop(0)
        if candidate is None or candidate.__name__ in seen:
            continue
        seen.add(candidate.__name__)
        if retry_helper_of(candidate) is not None:
            return candidate
        if candidate.__name__.startswith("aipass."):
            queue.extend(neighbouring_modules(candidate))
    return None


def public_writer(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Any, Callable, Path]:
    """A branch's public writer, normalised across both calling conventions.

    The convention split is the reason these three contracts could not simply
    be copied from one branch's suite: sixteen branches wrote
    ``save_json(module_name, json_type, data)`` and resolved the path
    themselves, ``backup`` wrote ``save_json(path, data)``. Both are answered
    here so the contract bodies below never branch on it.

    Measured 2026-09-03: the split is GONE. backup's sweep took its
    path-addressed form with the old handler, so all eighteen now write the
    three-argument form. The normaliser stays — it costs one branch and it is
    the thing that would notice a nineteenth convention arriving — but it is
    down to one convention to serve, which is worth saying out loud rather
    than leaving a reader to believe the fleet is still split.

    Args:
        branch: Branch to load.
        tmp_path: pytest's per-test directory.
        monkeypatch: Passed through to the redirect.

    Returns:
        The redirected module, a one-argument ``save`` closure, and the
        document path that ``save`` writes to.
    """
    module = implementation(branch)
    if required_positionals(module.save_json) == 3:
        module, _ = prepared(branch, tmp_path, monkeypatch)
        document = Path(str(module.get_json_path("durability", "data")))
        return module, lambda payload: module.save_json("durability", "data", payload), document
    document = tmp_path / "durability.json"
    return module, lambda payload: module.save_json(str(document), payload), document


def stray_temps(directory: Path) -> list:
    """Staging files left behind in a document directory.

    Args:
        directory: Where the document lives.

    Returns:
        Sorted names of everything that is not a ``.json`` document.
    """
    if not directory.is_dir():
        return []
    return sorted(child.name for child in directory.iterdir() if child.suffix != ".json")


#: ``save_json`` and the bounded retry underneath it. ALL 18 now reach a
#: bounded helper — their own, the shared module's, or trigger's public one.
#:
#: This table held one entry when slice 3 wrote it: ``ai_mail``'s save_json was
#: a truncating in-place ``open(path, "w")`` + ``json.dump`` with no staging
#: file and no rename, so no bounded retry was reachable from it at all, and
#: the ``except Exception`` around it reported a mid-dump loss as a soft False.
#: @ai_mail was dispatched off that finding and the cure landed 2026-09-02:
#: save_json now goes through ``_atomic_write_json``, the four strict xfails
#: turned RED as XPASS, and the row was deleted. Left empty rather than removed
#: so the next divergence has a home and the record of why it is empty survives.
WRITER_HAS_NO_BOUNDED_RETRY: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Contracts: the public writer's durability
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_the_public_writer_routes_its_write_through_the_bounded_replace_helper(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A write that lands by a bare rename re-introduces the Windows hang.

    The helper being present is pinned above; this pins that the writer
    actually goes through it, which is a different claim and the one that
    decays silently. A refactor that inlines ``os.replace`` back into
    ``save_json`` leaves every helper contract green and the branch broken on
    Windows again.

    What is counted is the HELPER, not ``os.replace``. Counting the syscall
    was the first shape of this test and it does not work: an inlined
    ``os.replace`` in ``save_json`` still increments a syscall counter, so the
    test would have passed the very refactor it exists to forbid. Wrapping the
    helper on the OWNING module — resolved by :func:`retry_owner`, because for
    six branches the rename does not happen in the handler under test at all —
    is the assertion that actually distinguishes the two.
    """
    module, save, _ = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    name = retry_helper_name(owner)
    real = getattr(owner, name)
    calls: list = []

    def counting(source: Any, destination: Any) -> None:
        calls.append((str(source), str(destination)))
        real(source, destination)

    monkeypatch.setattr(owner, name, counting)
    save(copy.deepcopy(DATA_PAYLOAD))

    assert len(calls) == 1, (
        f"{branch}: one save_json made {len(calls)} calls to {owner.__name__}.{name} — "
        f"expected exactly one staged write routed through the bounded retry"
    )


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_an_exhausted_retry_leaves_the_original_intact_and_cleans_the_staged_temp(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A write that cannot land must lose the NEW document, never the old one.

    The failure this forbids is the one that makes atomic writes worth having:
    a blocked rename that has already truncated the live file, so the caller
    loses a document it never asked to delete. The staging file is checked in
    the same breath because the other way to fail here is to preserve the
    original and leave a growing pile of ``.tmp`` beside it — correct, and
    still a bug.

    Deliberately silent about HOW the writer reports the failure: the fleet
    splits between raising and returning False, that split is pinned
    elsewhere, and folding it in here would turn a durability contract into a
    return-value contract that skips half the fleet.

    "Silent about the disposition" means the suppression has to cover every
    disposition, and it did not: it named ``PermissionError``, the exception
    the pre-migration raisers happen to let out. The one service raises
    ``WriteFailed`` instead, so on 2026-09-03 the first migrated branch failed
    this test by reporting its failure the way the spec says to. ``OSError`` is
    the honest bound — both dispositions are subclasses of it, and inside this
    block the only thing that can raise one is the write this test blocked on
    purpose.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    save(copy.deepcopy(DATA_PAYLOAD))
    original = document.read_bytes()

    def always_blocked(attempt: int, destination: Any) -> None:
        raise sharing_violation(destination)

    monkeypatch.setattr(owner, "os", CountingReplace(os, [], fail=always_blocked))
    monkeypatch.setattr(owner, "_REPLACE_BACKOFF_SECONDS", 0, raising=False)
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    with contextlib.suppress(OSError):
        save({**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": 999}})

    assert document.read_bytes() == original, f"{branch}: the exhausted write damaged the live document"
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the failed write"


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_the_public_writer_survives_a_transient_sharing_violation(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """The retry is reached from the public entry point, not only in isolation.

    Two sharing violations then success, injected at the owning module's own
    rename: the document must still contain what the caller saved. This is the
    end-to-end version of the helper contract above — a writer that caught
    PermissionError itself and gave up would pass every helper pin and fail
    here.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    def blocked_twice(attempt: int, destination: Any) -> None:
        if attempt <= 2:
            raise sharing_violation(destination)

    calls: list = []
    monkeypatch.setattr(owner, "os", CountingReplace(os, calls, fail=blocked_twice))
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    payload = {**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": 4242}}
    save(payload)

    assert len(calls) == 3, f"{branch}: retry path never engaged ({len(calls)} rename attempts)"
    landed = json.loads(document.read_text(encoding="utf-8"))
    assert landed["counters"] == {"seen": 4242}, f"{branch}: the retried write never landed"
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the retried write"


#: How the fleet REPORTS a write that could not land, measured 2026-09-02 with
#: the rename blocked to exhaustion. A near-even split, and deliberately not
#: written as a majority-plus-xfail table: calling either one "the contract"
#: would mark half the fleet as divergent from a coin toss. What every caller
#: actually needs is pinned instead, and it holds for all of them.
#:
#: Re-measured 2026-09-03 as the sweep began. prax and spawn both migrated that
#: night and both moved from the False column to the raise column, and the
#: exception is the service's own ``WriteFailed`` rather than the
#: ``PermissionError`` the other raisers let out. Measured on prax directly
#: (rename blocked to exhaustion); spawn is asserted on identity rather than a
#: second probe, because its handler is byte-identical to prax's — that
#: equality is exactly what the migration buys and what the IDENTITY axis above
#: pins. Counted here rather than left at yesterday's split because this is a
#: measurement record, and a record two branches stale is a record that has
#: started lying. The rest move the same way as the sweep reaches them; the
#: split ends at 18 / 0 and the constants go with the tables.
#:
#: Re-measured again 2026-09-03 afternoon, after the second sweep pair landed
#: devpulse, backup, hooks and aipass on the canonical shim. Only ``aipass`` of
#: those four was in the False column, so it crossed and the split moved by
#: one. Six branches now carry the shim; twelve have not been swept.
#:
#: Re-measured 2026-09-04 with fifteen of eighteen swept (DPLAN-0325 part B,
#: staging measurement). The near-even split of 09-02 is gone: the rename
#: blocked to exhaustion now raises for SEVENTEEN branches and returns False
#: for one. Fifteen of the seventeen raise the service's own ``WriteFailed``;
#: ``commons`` and ``daemon`` still let a bare ``PermissionError`` out of
#: their own handlers. ``ai_mail`` joins the count for the first time — the
#: 09-03 record listed seventeen branches, not eighteen, because ai_mail's own
#: helper was not reached then.
#:
#: Pair 5 the same day swept commons and daemon, so the SPLIT is unchanged at
#: 17 / 1 while its composition is not: all seventeen raisers now raise the
#: service's ``WriteFailed``, and the last bare ``PermissionError`` in the
#: fleet is gone. Recorded rather than left implied — the numbers below would
#: otherwise still read as two branches disagreeing about the exception type.
#:
#: THE SPLIT IS OVER. Re-measured 2026-09-04 after pair 6 swept api, the
#: eighteenth and last: with the rename blocked to exhaustion, all EIGHTEEN
#: branches raise, and every one of them raises the service's own
#: ``WriteFailed``. Not one returns False. The near-even split of 09-02 — the
#: reason this record exists and the reason the test below refuses to pick a
#: side — was eighteen implementations disagreeing, and there is one
#: implementation now.
#:
#: raise (18): every branch. return False (0): none.
#:
#: The constants are kept at their final values rather than deleted. They are a
#: measurement record, and the whole point of the record is that it ends
#: somewhere; a reader who finds the test below tolerating two dispositions
#: needs to be able to see that the tolerance was earned and is now historical.
#: The test itself is deliberately NOT narrowed to "must raise": the claim a
#: caller depends on is that a write that never landed never reports success,
#: and that claim should not go red the day a branch legitimately chooses the
#: other disposition again.
EXHAUSTED_WRITE_RAISES = 18
EXHAUSTED_WRITE_RETURNS_FALSE = 0


@pytest.mark.parametrize("branch", parametrized(WRITER_HAS_NO_BOUNDED_RETRY))
def test_a_write_that_cannot_land_never_reports_success(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The one thing both dispositions must agree on.

    The twins this replaces asserted ``is False`` because that is what their
    own branch does; three of them would have gone red if their handler had
    switched to raising, which is not a regression. So the assertion here is
    the claim a caller actually depends on and that both camps satisfy: a
    write that never landed must not come back looking like one that did.
    Returning True after an exhausted retry is the failure this forbids, and
    it is silent by construction — the caller has no other signal.
    """
    module, save, _ = public_writer(branch, tmp_path, monkeypatch)
    owner = retry_owner(module)
    assert owner is not None, f"{branch}: no bounded replace helper is reachable from save_json"

    def always_blocked(attempt: int, destination: Any) -> None:
        raise sharing_violation(destination)

    monkeypatch.setattr(owner, "os", CountingReplace(os, [], fail=always_blocked))
    monkeypatch.setattr(owner, "time", SimpleNamespace(sleep=lambda seconds: None))

    # Both dispositions land here without a branch: a raiser leaves the answer
    # at None, a returner leaves it at whatever it answered, and only True is
    # a failure. Written as a suppression rather than a bare except so the
    # sanctioned outcome is visible in the code instead of swallowed by it.
    answer = None
    with contextlib.suppress(PermissionError, OSError):
        answer = save(copy.deepcopy(DATA_PAYLOAD))
    assert not answer, f"{branch}: save_json answered {answer!r} for a write that never landed"


# ---------------------------------------------------------------------------
# Contracts: concurrency
# ---------------------------------------------------------------------------

#: Writers, and writes each performs. Small and fixed on purpose. The property
#: under test is "a reader never sees half a document", which a torn write
#: violates on its FIRST occurrence — piling on threads buys no sensitivity and
#: costs flake surface on a loaded runner.
CONCURRENT_WRITERS = 4
WRITES_PER_WRITER = 5

#: Ceiling on sampler loops, so a writer that dies cannot hang the run. Not a
#: timeout: nothing here asserts on elapsed time, which is the other way this
#: kind of test goes flaky.
MAX_SAMPLES = 4000

#: Join ceiling. A writer that deadlocks must fail this test rather than hang
#: the suite, and it is not a timing ASSERTION: nothing passes or fails on how
#: long the race took, only on whether a thread is still alive at the end.
THREAD_JOIN_SECONDS = 60


#: The tear this contract forbids. Empty: no branch in the fleet is currently
#: known to hand a reader a half-written document.
#:
#: It held ``ai_mail`` when slice 3 wrote it, where the tear was REPRODUCED
#: rather than predicted — an in-place truncating write caught handing a reader
#: an EMPTY document six times in one run of four writers, the failure mode
#: every other branch's staging file exists to make impossible. The entry said
#: "the day ai_mail adopts an atomic write this line turns red and gets
#: deleted". That day was 2026-09-02: the cure landed, the strict xfail turned
#: red as XPASS, and the line was deleted exactly as written.
TORN_DOCUMENT_OBSERVED: dict[str, str] = {}


@pytest.mark.parametrize("branch", parametrized(TORN_DOCUMENT_OBSERVED))
def test_concurrent_writers_never_expose_a_torn_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A reader during a write sees the old document or the new one, never half.

    This is the property the whole staging dance exists to buy, and the only
    one in this file that needs real threads: a writer that truncates in place
    passes every single-threaded contract above and still hands a reader a
    half-written file.

    THE SKIP IS PART OF THE MEASUREMENT, not politeness. A race that did not
    actually race proves nothing, and reporting it as a pass is how a
    concurrency test rots into decoration — so the counters are asserted
    first, and a run where the sampler never read while a write was in flight
    SKIPS with those counters in the message. What is never skipped is
    evidence of damage: a sample that failed to parse, or a final document
    that is empty or unparseable, is RED even if the counters say the race was
    thin. Absence of proof skips; proof of a tear fails.
    """
    module, save, document = public_writer(branch, tmp_path, monkeypatch)
    save(copy.deepcopy(DATA_PAYLOAD))

    torn: list = []
    failures: list = []
    unreadable: list = []
    writes = {"done": 0}
    sampled = {"count": 0}
    finished = threading.Event()

    def writer(seat: int) -> None:
        for round_number in range(WRITES_PER_WRITER):
            payload = {**copy.deepcopy(DATA_PAYLOAD), "counters": {"seen": seat * 100 + round_number}}
            try:
                save(payload)
                writes["done"] += 1
            except Exception as error:  # noqa: BLE001 - recorded and re-reported below
                failures.append(f"writer {seat}: {type(error).__name__}: {error}")

    def sampler() -> None:
        for _ in range(MAX_SAMPLES):
            if finished.is_set():
                return
            try:
                raw = document.read_bytes()
            except (FileNotFoundError, PermissionError) as error:
                # Not swallowed: a read that could not happen is evidence about
                # how thin the race was, so it is counted and reported in the
                # skip message rather than silently dropped.
                unreadable.append(f"{type(error).__name__}: {error}")
                continue
            sampled["count"] += 1
            if not raw.strip():
                torn.append("empty document observed mid-write")
                continue
            try:
                json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                torn.append(f"unparseable document observed mid-write: {error}")

    watcher = threading.Thread(target=sampler, daemon=True)
    watcher.start()
    writers = [threading.Thread(target=writer, args=(seat,)) for seat in range(CONCURRENT_WRITERS)]
    for thread in writers:
        thread.start()
    for thread in writers:
        thread.join(timeout=THREAD_JOIN_SECONDS)
    finished.set()
    watcher.join(timeout=THREAD_JOIN_SECONDS)
    stuck = [thread.name for thread in writers if thread.is_alive()]

    assert not stuck, f"{branch}: writers never finished: {stuck}"
    assert not torn, f"{branch}: reader observed a torn document — {torn[:3]}"
    assert not failures, f"{branch}: a concurrent write raised — {failures[:3]}"

    final = document.read_bytes()
    assert final.strip(), f"{branch}: the document is empty after the race"
    json.loads(final.decode("utf-8"))
    assert stray_temps(document.parent) == [], f"{branch}: staging files survived the race"

    if sampled["count"] == 0 or writes["done"] == 0:
        pytest.skip(
            f"{branch}: the race did not race — "
            f"{writes['done']} writes completed, {sampled['count']} samples read, "
            f"{len(unreadable)} reads could not happen; "
            f"nothing was observed concurrently, so no tear could have been seen"
        )


# ---------------------------------------------------------------------------
# Contracts: the template lineage — defaults, ensure, log_operation, save
# ---------------------------------------------------------------------------
#
# These absorb the largest stamped family in the fleet: 41 identities copied
# across api, devpulse, drone, seedgo and spawn. Every one was read before it
# was folded, because the fingerprint that grouped them drops names and
# literals — and doing so turned up one group whose members assert OPPOSITE
# things through the same statement shape, recorded below rather than averaged
# away.


def document_directory(module: Any, name: str, json_type: str) -> Path:
    """Where one branch keeps a document, asked of the branch itself.

    Args:
        module: A redirected handler.
        name: Document module name.
        json_type: ``config``, ``data`` or ``log``.

    Returns:
        The directory the document lives in.
    """
    return Path(str(module.get_json_path(name, json_type))).parent


@pytest.mark.parametrize("branch", parametrized())
def test_the_default_document_a_missing_read_materialises_passes_the_validator(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A handler must not manufacture a default its own validator rejects.

    The copies this replaces asserted the default's KEYS one branch at a time
    ("config default must have module_name"), which is the same claim written
    against a constant. Asked of the branch's own validator instead, so a
    branch that legitimately carries different keys is still held to the rule
    that matters: the document it invents on a missing read has to be one it
    would accept back.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    validate = expose(module, branch, "validate_json_structure")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    rejected = [
        json_type
        for json_type in ("config", "data", "log")
        if validate(module.load_json(f"absent_{json_type}", json_type), json_type) is not True
    ]
    assert not rejected, f"{branch}: the default it materialises fails its own validator for {rejected}"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_creates_the_document(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The document exists afterwards.

    Only the effect, deliberately. What ``ensure_json_exists`` ANSWERS is a
    real fleet divergence with a reasoned case on both sides, so it is pinned
    separately rather than folded in here where it would look like part of
    the same claim.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    ensure("fresh", "config")

    assert Path(str(module.get_json_path("fresh", "config"))).exists(), f"{branch}: ensure created nothing"


#: What ``ensure_json_exists`` ANSWERS. Every branch now returns an
#: unconditional ``True``, so the table is empty.
#:
#: It held exactly one row, and it was seedgo's own: ensure_json_exists
#: returned None by documented decision, because a literal that is never False
#: "advertises a failure signal that never arrives and invites ``if not
#: ensure_json_exists(...)``, a branch that can never be taken". It was
#: recorded as a divergence and never as a fault -- the majority's success
#: signal genuinely carries no information, and this table measures rather than
#: judges. The pair-4 sweep settled it the way the whole plan settles things:
#: seedgo's handler became the shim, the answer became the service's, and the
#: strict xfail XPASSed. Kept written down because deleting the reasoning would
#: make the fleet's uninformative True look like it was never questioned.
ENSURE_RETURNS_NOTHING: dict[str, str] = {}


@pytest.mark.parametrize("branch", parametrized(ENSURE_RETURNS_NOTHING))
def test_ensure_json_exists_reports_true(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The success signal seventeen branches publish and callers branch on.

    Worth pinning even though the value is a constant on every branch that
    has it: callers DO write ``if ensure_json_exists(...)``, and a branch that
    silently changed to None would send all of them down the failure path
    while every file kept being created exactly as before.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert ensure("bool_mod", "data") is True, f"{branch}: ensure_json_exists did not answer True"


#: ``ensure_module_jsons``'s return value, emptied by pair 4 alongside
#: ``ensure_json_exists`` and for the same reason. Its single row was seedgo's:
#: the wrapper "previously discarded three booleans and then returned an
#: unconditional True, so it reported success no matter what the three calls
#: did". The shim answers with the service's value now, and the strict xfail
#: XPASSed.
ENSURE_ALL_RETURNS_NOTHING: dict[str, str] = {}


@pytest.mark.parametrize("branch", parametrized(ENSURE_ALL_RETURNS_NOTHING))
def test_ensure_module_jsons_reports_true(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The wrapper's success signal, pinned beside the one it wraps."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure_all = expose(module, branch, "ensure_module_jsons")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert ensure_all("retmod") is True, f"{branch}: ensure_module_jsons did not answer True"


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


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_preserves_a_valid_existing_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Ensure is not a reset button.

    The failure this forbids is the expensive one: a handler that regenerates
    unconditionally silently discards a caller's live config every time
    anything asks whether the file is there.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    module.save_json("kept", "config", copy.deepcopy(CONFIG_PAYLOAD))
    before = Path(str(module.get_json_path("kept", "config"))).read_text(encoding="utf-8")

    ensure("kept", "config")

    after = Path(str(module.get_json_path("kept", "config"))).read_text(encoding="utf-8")
    assert after == before, f"{branch}: ensure_json_exists rewrote a document that was already valid"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_regenerates_an_unreadable_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Unparseable bytes are replaced with something loadable.

    A handler that leaves the corruption in place hands the next reader the
    same crash forever; one that raises here makes the caller handle a
    condition ensure exists to resolve.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("corrupt", "config")))
    document.write_text("{not json at all", encoding="utf-8")

    ensure("corrupt", "config")

    assert json.loads(document.read_text(encoding="utf-8")), f"{branch}: corrupt document was not regenerated"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_json_exists_regenerates_a_structurally_invalid_document(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Parseable but wrong is still wrong.

    Distinct from the corrupt case on purpose: the bytes here are valid JSON,
    so a handler that only guards ``json.loads`` sails past this and leaves a
    document its own validator would reject sitting on disk.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure = expose(module, branch, "ensure_json_exists")
    validate = expose(module, branch, "validate_json_structure")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("wrong", "config")))
    document.write_text(json.dumps({"wrong": "structure"}), encoding="utf-8")

    ensure("wrong", "config")

    healed = json.loads(document.read_text(encoding="utf-8"))
    assert validate(healed, "config") is True, f"{branch}: invalid structure survived ensure_json_exists"


@pytest.mark.parametrize("branch", parametrized())
def test_ensure_module_jsons_creates_all_three_documents(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The three-document convenience wrapper does all three."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    ensure_all = expose(module, branch, "ensure_module_jsons")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    ensure_all("triple")

    missing = [
        json_type
        for json_type in ("config", "data", "log")
        if not Path(str(module.get_json_path("triple", json_type))).exists()
    ]
    assert not missing, f"{branch}: ensure_module_jsons did not create {missing}"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_appends_a_timestamped_entry_and_reports_true(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """One call, one entry, carrying the operation and a timestamp."""
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    answer = log_operation("deploy", module_name="logmod")

    entries = json.loads(Path(str(module.get_json_path("logmod", "log"))).read_text(encoding="utf-8"))
    assert entries, f"{branch}: log_operation appended nothing"
    assert entries[-1]["operation"] == "deploy", f"{branch}: the operation name was not recorded"
    assert "timestamp" in entries[-1], f"{branch}: the entry carries no timestamp"
    assert answer is True, f"{branch}: log_operation answered {answer!r}, not True"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_attaches_the_data_it_was_given(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """A payload survives to the entry, and an empty one invents nothing.

    The second half is the copies' own weaker claim made exact: they allowed
    an absent key OR an empty one, which is two behaviours. Both are fine —
    what is not fine is a handler that fabricates content for a caller who
    passed nothing, so that is what is pinned.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    document = Path(str(module.get_json_path("datamod", "log")))

    log_operation("with_data", data={"count": 5}, module_name="datamod")
    carried = json.loads(document.read_text(encoding="utf-8"))[-1]
    assert carried.get("data", {}).get("count") == 5, f"{branch}: the data payload was lost"

    log_operation("no_data", data={}, module_name="datamod")
    empty = json.loads(document.read_text(encoding="utf-8"))[-1]
    assert not empty.get("data"), f"{branch}: an empty payload became {empty.get('data')!r}"


@pytest.mark.parametrize("branch", parametrized())
def test_log_operation_calls_accumulate_in_call_order(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Three calls leave three entries, oldest first.

    Order is asserted, not just the count: a log that accumulates but reverses
    is useless to every reader that takes ``[-1]`` as "most recent", which is
    how the fleet reads it.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)

    for operation in ("first", "second", "third"):
        log_operation(operation, module_name="accmod")

    entries = json.loads(Path(str(module.get_json_path("accmod", "log"))).read_text(encoding="utf-8"))
    assert [entry["operation"] for entry in entries[-3:]] == ["first", "second", "third"], (
        f"{branch}: log entries did not accumulate in call order"
    )


#: Cap this suite declares for the rotation contract. Small so the test writes
#: ten entries rather than a hundred and five.
DECLARED_LOG_CAP = 5

#: Spellings the fleet uses for the private "template for this json_type"
#: factory. A list because it IS private, so nothing obliges the branches to
#: agree on the name, and they do not.
DEFAULT_FACTORY_NAMES = ("_get_default_for_type", "_default_for_type", "_get_default", "_default_content")


def declare_log_cap(module: Any, name: str, cap: int) -> bool:
    """Write a config document declaring a rotation cap, the way the handler reads it.

    Measured correction to how the stamped copies did this. They searched four
    MODULE attribute spellings for the cap, and no branch in the fleet defines
    any of them — it is read out of the module's own CONFIG DOCUMENT
    (``config["config"]["max_log_entries"]``), with a literal fallback in the
    code. So the copies' search could only ever answer "no cap": two of the
    four skipped on every run, and the two that passed used a number they had
    invented rather than the one the handler applies.

    Declaring it instead of hunting for it also means the contract exercises
    rotation on every branch that reads the setting, rather than only the ones
    that happen to ship a document with the key already in it.

    Args:
        module: A redirected handler.
        name: Document module name to configure.
        cap: Entries to keep.

    Returns:
        True when the handler accepted the declaration.
    """
    settings = module.load_json(name, "config")
    if not isinstance(settings, dict) or not isinstance(settings.get("config"), dict):
        return False
    settings["config"]["max_log_entries"] = cap
    module.save_json(name, "config", settings)
    written = module.load_json(name, "config")
    return written.get("config", {}).get("max_log_entries") == cap


#: Branches whose rotation ignores the ``max_log_entries`` they publish.
#: aipass/shared/json_handler.py WRITES the setting into every config document
#: it generates (line 188) and then rotates on ``JsonHandler.MAX_LOG_ENTRIES``
#: (line 334), never reading the document back — so the four branches that
#: share that handler advertise a knob that does nothing. An operator who
#: edits max_log_entries gets no change and no warning. Found by declaring the
#: cap instead of hunting for it; the stamped copies could not have seen it,
#: because none of them ever wrote the setting.
#:
#: ``spawn`` left this table on 2026-09-03, the second row the migration
#: removed: spawn's handler became the canonical shim, and the one service
#: reads the cap out of the module's own config document instead of a class
#: constant, so the knob spawn advertised began working. The strict xfail
#: XPASSed and the row went, on the same rule as every other cure recorded
#: here. ``aipass`` followed on the same day when its own sweep landed the
#: shim. ``canary`` and ``memory`` — the last two rows — left with the pair-3
#: sweep (DPLAN-0325 phase 4, devpulse): both now bind the shim, which reads the
#: cap from the module's own config document, so the published setting works and
#: the strict xfail XPASSed. The table is empty, and this contract now holds
#: every branch to its declared cap.
DECLARED_LOG_CAP_IGNORED: dict[str, str] = {}


@pytest.mark.parametrize("branch", parametrized(DECLARED_LOG_CAP_IGNORED))
def test_log_operation_rotates_to_the_modules_declared_cap(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """An unbounded log is a disk-filler; the cap must actually bind.

    The cap is DECLARED by this contract in the document the handler reads,
    rather than hunted for on the module — see :func:`declare_log_cap` for why
    the hunt could not work. A branch whose config document has no place to
    declare it skips by name.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    log_operation = expose(module, branch, "log_operation")
    module, _ = prepared(branch, tmp_path, monkeypatch)
    if not declare_log_cap(module, "fifomod", DECLARED_LOG_CAP):
        pytest.skip(f"{branch}'s config document has no config mapping to declare max_log_entries in")

    for index in range(DECLARED_LOG_CAP + 5):
        log_operation(f"op_{index}", module_name="fifomod")

    entries = json.loads(Path(str(module.get_json_path("fifomod", "log"))).read_text(encoding="utf-8"))
    assert len(entries) <= DECLARED_LOG_CAP, (
        f"{branch}: {len(entries)} entries survived a declared cap of {DECLARED_LOG_CAP}"
    )
    assert entries[-1]["operation"] == f"op_{DECLARED_LOG_CAP + 4}", (
        f"{branch}: the newest entry is not last after rotation"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_reports_true_on_a_write_that_landed(branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """The success signal every caller branches on.

    Pinned separately from the round trip because a handler can persist
    correctly and still answer None, and the callers that check are then
    wrong in the safe-looking direction.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)

    assert module.save_json("sv", "config", copy.deepcopy(CONFIG_PAYLOAD)) is True, (
        f"{branch}: save_json did not answer True for a write that succeeded"
    )


@pytest.mark.parametrize("branch", parametrized())
def test_save_json_writes_a_document_that_parses_from_disk(
    branch: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """Read back as BYTES, not through the handler's own loader.

    The round-trip contract goes out and back through the same module, so a
    loader that tolerates its own writer's quirk would hide them both. This
    reads the file the way every other process on the machine will.
    """
    module = implementation(branch)
    require_document_addressing(module, branch)
    module, _ = prepared(branch, tmp_path, monkeypatch)
    module.save_json("disk", "log", copy.deepcopy(LOG_PAYLOAD))

    raw = Path(str(module.get_json_path("disk", "log"))).read_bytes()
    parsed = json.loads(raw.decode("utf-8"))
    assert parsed == LOG_PAYLOAD, f"{branch}: the document on disk is not what was saved"


# ===========================================================================
# The audit trail names who it can, and says so when it cannot
# ===========================================================================
#
# INHERITED 2026-09-04, DPLAN-0325 pair 6. These two claims lived in
# api/tests/test_host_perf.py and nowhere else in the fleet — measured before
# api swept. They were written against api's own ``_get_caller_module_name``;
# there is one implementation now, so they belong here, run once, against it.
#
# The three cases that did NOT come with them compared a ``sys._getframe(2)``
# fetch against an ``inspect.stack()`` walk. The service has no walk — it never
# had two implementations — so those had no subject to test and are archived
# with the record in api's tree, not silently dropped.
#
# Depth and pseudo-frames are already pinned upstream in
# prax/tests/test_repo_root.py and are deliberately not duplicated here.


class TestTheAuditTrailNamesWhoItCan:
    """``_get_caller_module_name`` answers "unknown" rather than guessing or dying."""

    def test_an_underscore_private_caller_is_not_named(self, monkeypatch: pytest.MonkeyPatch):
        """A module whose name starts with ``_`` is somebody's implementation detail.

        The log records who did the work so a human can go and read them. A
        private module is not an answer to that question, so the honest value
        is "unknown" — and a log that names one asserts a caller that no
        importer of this system is allowed to reach for.
        """
        service = json_service_or_skip()
        frame = SimpleNamespace(f_code=SimpleNamespace(co_filename=str(Path(tempfile.gettempdir()) / "_private.py")))

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=lambda _depth: frame))
        assert service._get_caller_module_name() == "unknown", (
            "the operations log named an underscore-private module as the caller"
        )

    def test_a_frame_that_cannot_be_fetched_is_unknown_and_not_a_crash(self, monkeypatch: pytest.MonkeyPatch):
        """The audit trail must never be the reason an operation fails.

        ``log_operation`` runs on the write path of every branch in the fleet.
        If naming the caller can raise, then a saved document depends on the
        interpreter's willingness to hand back a frame — which is exactly
        backwards. Anything the frame fetch throws is an "unknown", logged.
        """
        service = json_service_or_skip()

        def _no_such_frame(_depth: int):
            raise ValueError("no such frame")

        monkeypatch.setattr(service, "sys", SimpleNamespace(_getframe=_no_such_frame))
        assert service._get_caller_module_name() == "unknown", (
            "a frame fetch that raised took the operation down with it"
        )
