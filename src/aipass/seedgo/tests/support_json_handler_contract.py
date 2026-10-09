# =================== AIPass ====================
# Name: support_json_handler_contract.py
# Description: Shared discovery, payloads and redirection for the json_handler contract files (split 2026-10-08)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Shared helpers for the tests of every branch's apps/handlers/json/json_handler.py (not test_: never collected)."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import importlib.util
import inspect
import json
from pathlib import Path
from typing import Any, Callable, Mapping

import pytest

import aipass
from aipass.prax import logger

# Module level, never inside a function: a guard here can precede no test's own
# patching (import_site item 8's own exemption), and it is the ONE way to keep
# this import_site-clean while still tolerating a checkout where @memory is
# absent — moving it into _fleet_roster() would put a product import back
# inside a function for no behavioural gain.
try:
    from aipass.memory.apps.modules.door_registry_scope import fleet_branches
except Exception as exc:  # pragma: no cover - exercised only where @memory is absent
    logger.info("[json_handler_contract] @memory unreachable, the roster is the installed glob alone: %s", exc)
    fleet_branches = None

# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

#: The installed package directory, so the suite runs identically whichever
#: rootdir pytest picks (branch-local or repo-root).
PACKAGE_ROOT = Path(aipass.__file__).resolve().parent

#: Where a citizen's json_handler lives, relative to its branch root.
HANDLER_RELPATH = Path("apps") / "handlers" / "json" / "json_handler.py"


def _installed_roster() -> dict[str, Path]:
    """The citizens inside the installed package, found by file glob.

    The fallback, and the floor: whatever else is reachable, these 18 always
    are, because they are the package this suite is imported from.
    """
    return {path.parents[3].name: path.parents[3] for path in PACKAGE_ROOT.glob("*/apps/handlers/json/json_handler.py")}


def _fleet_roster() -> dict[str, Path]:
    """Every citizen the registry knows, core and resident and external.

    RESIDENTS WERE OUTSIDE THIS SUITE UNTIL 2026-09-07. Discovery was a glob
    over the INSTALLED package, so a citizen minted into another project's
    tree — @vera under Vera-Studio, the four under `projects/` — got no
    coverage from the contract at all, while a newborn minted under
    `src/aipass/` joined the parametrised run automatically (@spawn's finding,
    FPLAN-0493). The roster is @memory's `fleet_branches()`, the same one
    @daemon's fleet sweep uses, so "the fleet" means one thing in both places.

    A citizen whose tree is not on this machine, or which ships no handler at
    that path, is simply absent from the roster rather than a failure: this
    suite measures handlers that exist, and a checkout someone else has is not
    a defect here. When @memory is unreachable the installed glob answers
    alone — a narrower run that still runs, never an empty one.
    """
    roster = _installed_roster()
    if fleet_branches is None:
        return roster
    try:
        rows = fleet_branches()
    except Exception as exc:  # pragma: no cover - a broken registry must not empty the run
        logger.info("[json_handler_contract] fleet_branches() failed, the roster is the installed glob alone: %s", exc)
        return roster
    for row in rows:
        root = Path(str(row.get("path", "")))
        name = str(row.get("name", ""))
        if name and name not in roster and (root / HANDLER_RELPATH).is_file():
            roster[name] = root
    return roster


#: Branch name -> branch root, for every citizen that ships a handler here.
ROSTER: dict[str, Path] = _fleet_roster()

#: Every branch that ships the canonical handler path, in stable order.
BRANCHES = sorted(ROSTER)


#: The fleet's redirect seam, read by the one json service on every call. Set
#: at the top of every branch conftest; the contract re-points it per subject.
SERVICE_REDIRECT_ENV = "AIPASS_TEST_LOG_DIR"

#: The import line that makes a handler a shim over the one service
#: (DPLAN-0325 section 3). A file without it has not migrated yet.
SERVICE_IMPORT_MARKER = "from aipass.prax import json_handler"


def handler_path(branch: str) -> Path:
    """Return the canonical handler file for *branch*."""
    return ROSTER[branch] / HANDLER_RELPATH


#: Every roster handler, loaded ONCE, here at module level, before any test
#: can stage a replacement for it (template item 8).
#:
#: Every handler is loaded from its FILE, core citizen and resident alike. A
#: core citizen used to be imported by its dotted name, but since the fences
#: came back (DPLAN-0404, 2026-10-08) `aipass.<branch>.apps.handlers` refuses
#: a foreign importer, and this suite is one: it is seedgo's instrument reading
#: a specimen of each branch's handler, the way the checkers read sources, not
#: a caller using the handler as a service. A file load executes the specimen
#: without passing the fence, and a resident never had a dotted name inside
#: `aipass` anyway; the alternative was leaving those citizens unmeasured,
#: which is the gap the roster widening closed.
#:
#: ONE module object per branch, for the whole run. Loading the file afresh on
#: each call returns a NEW module object every time, and a test that captures a
#: function from one call and redirects another gets a redirect that covers
#: neither. Measured the hard way on 2026-09-07: the uncached first draft of
#: this loader wrote contract documents into @vera's live vera_json/ directory,
#: because `expose(module, ...)` held the unredirected module while
#: `prepared(...)` redirected a different one. This dict is that cache; it
#: used to be sys.modules under a private key, which held the object just as
#: well and left a module-table entry behind for every file collected after.
#:
#: A resident whose file cannot be loaded as a module is left out, and each of
#: its tests skips naming the path (see :func:`implementation`).
IMPLEMENTATIONS: dict[str, Any] = {}
for _branch in BRANCHES:
    _key = f"_aipass_contract_json_handler_{_branch}"
    _spec = importlib.util.spec_from_file_location(_key, handler_path(_branch))
    if _spec is None or _spec.loader is None:
        continue
    _module = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_module)
    IMPLEMENTATIONS[_branch] = _module


def implementation(branch: str) -> Any:
    """One branch's ``json_handler`` module, as imported at module level.

    Args:
        branch: A name in :data:`ROSTER`.

    Returns:
        The imported module.
    """
    module = IMPLEMENTATIONS.get(branch)
    if module is None:
        pytest.skip(f"{branch}: {handler_path(branch)} could not be loaded as a module")
    return module


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
# Measured divergence tables shared by a sibling's contract and the floor's
# stale-name check in test_json_handler_contract.py
# ---------------------------------------------------------------------------

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


#: ``ensure_module_jsons``'s return value, emptied by pair 4 alongside
#: ``ensure_json_exists`` and for the same reason. Its single row was seedgo's:
#: the wrapper "previously discarded three booleans and then returned an
#: unconditional True, so it reported success no matter what the three calls
#: did". The shim answers with the service's value now, and the strict xfail
#: XPASSed.
ENSURE_ALL_RETURNS_NOTHING: dict[str, str] = {}


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


def require_one_service(branch: str) -> None:
    """Skip a citizen whose handler has not migrated to the one json service.

    The third family, and the one that arrived with the roster widening on
    2026-09-07. Every core citizen is a byte-identical shim over
    ``aipass.prax.json_handler``; the four Vera-Studio externals still ship the
    PRE-MIGRATION handler — a full implementation of their own, 169-177 lines,
    with no ``SERVICE_IMPORT_MARKER``. Durability is a property of the service:
    it stages a temp file and lands it through a bounded retry, and those four
    write straight through ``open(path, "w")``, so a durability contract asked
    of them is not a contract they ever signed.

    The skip line is the measurement, and it names the finding rather than
    hiding it: those handlers are unmigrated AND they do land writes by a bare
    write, which is exactly what the migration exists to end.

    Args:
        branch: Branch name, for the message.
    """
    if SERVICE_IMPORT_MARKER not in handler_path(branch).read_text(encoding="utf-8"):
        pytest.skip(
            f"{branch} ships the PRE-MIGRATION json_handler — it does not import the one service "
            f"({SERVICE_IMPORT_MARKER!r}), so the service's durability contracts do not apply to it. "
            f"Measured 2026-09-07: it stages nothing and lands its write directly."
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


class LogRecorder:
    """Stands where a handler binds its own ``logger``: keeps each call, writes nothing."""

    def __init__(self) -> None:
        self.records: list[tuple[str, tuple]] = []

    def debug(self, *args: Any, **kwargs: Any) -> None:
        """Keep one debug call."""
        self.records.append(("debug", args))

    def info(self, *args: Any, **kwargs: Any) -> None:
        """Keep one info call."""
        self.records.append(("info", args))

    def warning(self, *args: Any, **kwargs: Any) -> None:
        """Keep one warning call."""
        self.records.append(("warning", args))

    def error(self, *args: Any, **kwargs: Any) -> None:
        """Keep one error call."""
        self.records.append(("error", args))


def silence_own_logger(module: Any, monkeypatch: pytest.MonkeyPatch) -> LogRecorder | None:
    """Replace the logger a handler binds at module scope with a recorder.

    A resident handler (research, vera, verify, writer under Vera-Studio) logs
    through prax, which routes a caller outside the AIPass tree to that
    project's own logs/ and system_logs/ and never reads the test seam: four
    lines landed there on every run of this file from a seat with no
    AIPASS_BRANCH_NAME (seedgo, fleet green leg 4). A migrated shim binds no
    logger; the service it imports logs under the seam.

    Returns:
        The recorder, or None when the module binds no logger of its own.
    """
    if "logger" not in vars(module):
        return None
    recorder = LogRecorder()
    monkeypatch.setattr(module, "logger", recorder)
    return recorder


def assert_warned_of_corrupt_bytes(module: Any, branch: str) -> None:
    """A handler with its own logger warned once, naming the corrupt document.

    Only a module :func:`silence_own_logger` replaced has a record to read; a
    migrated shim's warning is the service's, logged under the seam.
    """
    recorder = vars(module).get("logger")
    if not isinstance(recorder, LogRecorder):
        return
    heads = [(level, args[:2]) for level, args in recorder.records]
    assert heads == [("warning", ("[json_handler] Corrupt JSON %s: %s", "corrupt_config.json"))], (
        f"{branch}: the corrupt document was not warned of once — {recorder.records!r}"
    )
    assert isinstance(recorder.records[0][1][2], json.JSONDecodeError)


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
    silence_own_logger(module, monkeypatch)
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
