# =================== AIPass ====================
# Name: support_json_handler_contract.py
# Description: Shared discovery, payloads and redirection for the json_handler contract files (split 2026-10-08)
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
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

# Module level, so a checkout without @memory is tolerated with no product import inside a function.
try:
    from aipass.memory.apps.modules.door_registry_scope import fleet_branches
except Exception as exc:  # pragma: no cover - exercised only where @memory is absent
    logger.info("[json_handler_contract] @memory unreachable, the roster is the installed glob alone: %s", exc)
    fleet_branches = None

#: The installed package, so the run is the same whichever rootdir pytest picks.
PACKAGE_ROOT = Path(aipass.__file__).resolve().parent

HANDLER_RELPATH = Path("apps") / "handlers" / "json" / "json_handler.py"


def _installed_roster() -> dict[str, Path]:
    """The citizens inside the installed package, found by file glob."""
    return {path.parents[3].name: path.parents[3] for path in PACKAGE_ROOT.glob("*/apps/handlers/json/json_handler.py")}


def _fleet_roster() -> dict[str, Path]:
    """Every citizen the registry knows, core and resident and external."""
    # @memory's `fleet_branches()`, the roster @daemon's sweep uses; without @memory the installed glob answers alone.
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


ROSTER: dict[str, Path] = _fleet_roster()

BRANCHES = sorted(ROSTER)


SERVICE_REDIRECT_ENV = "AIPASS_TEST_LOG_DIR"

#: A handler without this line has not migrated to the one service.
SERVICE_IMPORT_MARKER = "from aipass.prax import json_handler"


def handler_path(branch: str) -> Path:
    """Return the canonical handler file for *branch*."""
    return ROSTER[branch] / HANDLER_RELPATH


#: Loaded once, before any test can stage a replacement, and from the FILE: the handlers fence refuses this
#: suite's dotted import. One object per branch, or a test redirects one copy and writes through another.
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
    """One branch's ``json_handler`` module, as imported at module level."""
    module = IMPLEMENTATIONS.get(branch)
    if module is None:
        pytest.skip(f"{branch}: {handler_path(branch)} could not be loaded as a module")
    return module


def parametrized(divergences: Mapping[str, str] | None = None) -> list:
    """Build the per-branch argvalues, marking measured divergences xfail."""
    table = divergences or {}
    return [
        pytest.param(
            branch,
            id=branch,
            marks=[pytest.mark.xfail(reason=table[branch], strict=True)] if branch in table else [],
        )
        for branch in BRANCHES
    ]


#: Left empty rather than removed, so the next divergence has a home.
WRITER_HAS_NO_BOUNDED_RETRY: dict[str, str] = {}


TORN_DOCUMENT_OBSERVED: dict[str, str] = {}


ENSURE_RETURNS_NOTHING: dict[str, str] = {}


ENSURE_ALL_RETURNS_NOTHING: dict[str, str] = {}


#: Branches whose rotation ignores the ``max_log_entries`` they publish; empty, every branch honours its cap.
DECLARED_LOG_CAP_IGNORED: dict[str, str] = {}


# Payloads satisfy the shared validate_json_structure, so a rejected write means the WRITE diverged.

CONFIG_PAYLOAD = {
    "module_name": "contract_probe",
    "version": "1.0.0",
    "config": {"max_log_entries": 50, "nested": {"values": [1, 2, 3]}},
}
DATA_PAYLOAD = {"created": "2020-01-01", "last_updated": "2020-01-02", "counters": {"seen": 7}}
LOG_PAYLOAD = [{"timestamp": "2020-01-01T00:00:00", "operation": "contract_probe"}]


def required_positionals(function: Callable) -> int:
    """Count the parameters a caller must supply positionally."""
    parameters = inspect.signature(function).parameters.values()
    positional = (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
    return sum(1 for p in parameters if p.kind in positional and p.default is p.empty)


def expose(module: Any, branch: str, name: str) -> Callable:
    """Fetch a handler function or skip with the branch and function named."""
    # A silent pass would report green over a surface half the fleet lacks: the skip line is the measurement.
    function = getattr(module, name, None)
    if function is None:
        pytest.skip(f"{branch} does not expose {name} — its json_handler has no such entry point")
    return function


def require_document_addressing(module: Any, branch: str) -> None:
    """Skip branches whose handler addresses documents by filesystem path."""
    # ``backup`` takes a path, not ``(module_name, json_type)``: naming contracts are inapplicable to it, not passing.
    if required_positionals(module.load_json) != 2:
        pytest.skip(
            f"{branch}'s json_handler is the PATH-ADDRESSED family — "
            f"load_json{inspect.signature(module.load_json)} takes a filesystem path, "
            f"so (module_name, json_type) contracts do not apply to it"
        )


def require_one_service(branch: str) -> None:
    """Skip a citizen whose handler has not migrated to the one json service."""
    # Durability is the service's: an unmigrated handler writes straight through open(path, "w"), and the skip names it.
    if SERVICE_IMPORT_MARKER not in handler_path(branch).read_text(encoding="utf-8"):
        pytest.skip(
            f"{branch} ships the PRE-MIGRATION json_handler — it does not import the one service "
            f"({SERVICE_IMPORT_MARKER!r}), so the service's durability contracts do not apply to it. "
            f"Measured 2026-09-07: it stages nothing and lands its write directly."
        )


def namespaces_and_instances(module: Any) -> tuple[list[dict], list[Any]]:
    """Every place one branch's handler could be holding its document directory."""
    # Constants (named per branch, so matched), the defining module's __globals__ and bound-method instance dicts.
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
    """Point every document-directory binding this handler reads at ``target``."""
    # The original type is kept: one branch joins a str with os.path.join.
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
            # The seam only: the service composes <env>/<root.name>/<root.name>_json, and the real root keeps
            # the identity axis reading the shipped value.
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
    """Replace the logger a handler binds at module scope with a recorder."""
    # A resident logs through prax to its own project's logs/, never the seam; a migrated shim binds no logger.
    if "logger" not in vars(module):
        return None
    recorder = LogRecorder()
    monkeypatch.setattr(module, "logger", recorder)
    return recorder


def assert_warned_of_corrupt_bytes(module: Any, branch: str) -> None:
    """A handler with its own logger warned once, naming the corrupt document."""
    recorder = vars(module).get("logger")
    if not isinstance(recorder, LogRecorder):
        return
    heads = [(level, args[:2]) for level, args in recorder.records]
    assert heads == [("warning", ("[json_handler] Corrupt JSON %s: %s", "corrupt_config.json"))], (
        f"{branch}: the corrupt document was not warned of once — {recorder.records!r}"
    )
    assert isinstance(recorder.records[0][1][2], json.JSONDecodeError)


def redirected(branch: str, target: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    """Import a branch's handler, redirect it, and PROVE the redirect took."""
    # Skips rather than write into a live tree when get_json_path still answers outside target.
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
    """Redirected module plus an existing, empty document directory."""
    # The directory get_json_path answers, not the request: a shim composes <seam>/<branch>/<branch>_json.
    target = tmp_path / "documents"
    target.mkdir()
    module = redirected(branch, target, monkeypatch)
    resolver = getattr(module, "get_json_path", None)
    if resolver is None:
        return module, target
    documents = Path(str(resolver("contract_probe", "data"))).parent
    documents.mkdir(parents=True, exist_ok=True)
    return module, documents
