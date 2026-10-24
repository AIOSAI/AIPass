# =================== AIPass ====================
# Name: audit_hygiene_plugin.py
# Description: pytest write-hygiene gate - stdlib only, injected into a copy
# Version: 1.0.1
# Created: 2026-08-29
# Modified: 2026-10-24
# =============================================

"""The write gate. A pytest plugin injected into a COPY of somebody else's tree.

Imports nothing from aipass, ever (Law M10): `adapters.execution_isolation()` parses
this directory and fails registration on an aipass import. Configured only by
`AUDIT_TESTS_*` environment variables, since the launcher is not importable here;
`AUDIT_TESTS_DISABLE_HOOK=1` exists only to prove a gateless run refuses (T10).
Child processes and sqlite's C-level writes are invisible to the hook, so they are
counted into `gate_coverage`: 100 means no violation seen by this gate.
"""

import json
import logging
import os
import sys
import tempfile
import time
from typing import Dict, List, Optional, TextIO, Tuple

__version__ = "1.0.0"

logger = logging.getLogger("audit_tests.hygiene_gate")


#: In classifier order, copied verbatim into the artifact: a sandbox never widens unsaid.
ALLOWANCES: Tuple[Tuple[str, str], ...] = (
    ("plugin_log", "the hygiene log this plugin writes, by exact path"),
    ("canary", "the plugin's own canary sentinel, by exact path"),
    ("pycache_dir", "any path with a __pycache__ component"),
    ("pytest_cache_dir", "any path with a .pytest_cache component"),
    ("bytecode", "a file whose name ends .pyc or .pyo"),
    ("coverage_data", "a file whose name starts .coverage"),
    ("devnull", "os.devnull itself - pytest's logging plugin opens it every session"),
    ("pytest_tmp", "pytest's basetemp tree - <TMPDIR>/pytest-of-* and the factory's own root"),
    ("tmpdir", "anything under TMPDIR"),
)

#: Positional path args verified by probe against CPython 3.12, not read off the docs.
PATH_ARGS: Dict[str, Tuple[int, ...]] = {
    "open": (0,),
    "os.rename": (0, 1),
    "os.remove": (0,),
    "os.mkdir": (0,),
    "os.rmdir": (0,),
    "os.truncate": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.symlink": (1,),
    "os.link": (1,),
    "shutil.copyfile": (0, 1),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.unpack_archive": (1,),
}

#: (event, path index) -> index of the dir_fd that path is relative to; -1/None means the cwd.
DIR_FD_ARGS: Dict[Tuple[str, int], int] = {
    ("os.remove", 0): 1,
    ("os.rmdir", 0): 1,
    ("os.mkdir", 0): 2,
    ("os.chmod", 0): 2,
    ("os.chown", 0): 3,
    ("os.rename", 0): 2,
    ("os.rename", 1): 3,
    ("os.link", 1): 3,
    ("os.symlink", 1): 2,
}

#: Never violations, always counted: the gate's blind spots made numeric.
SPAWN_EVENTS: Tuple[str, ...] = (
    "subprocess.Popen",
    "os.exec",
    "os.posix_spawn",
    "os.spawn",
)

SQLITE_EVENT = "sqlite3.connect"

#: `mode` is None via os.open, so `flags` is the only universally present signal.
WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

MAX_RECORDS = 20000
MAX_SAMPLES = 25


class GateState:
    """Everything the hook touches, in one object so the hook does one lookup."""

    def __init__(self) -> None:
        """Start with an uninstalled gate and an empty sandbox."""
        self.log_path = ""
        self.env_root = ""
        self.target_root = ""
        self.target_module = ""
        self.tmpdir_allowed = True
        self.hook_installed = False
        self.tmp_root = ""
        self.pytest_basetemp = ""
        self.pytest_tmp_prefix = "\x00unset"
        self.canary_path = ""
        self.canary_seen = False
        self.nodeid = "<session>"
        self.phase = "session"
        self.emitting = False
        self.violations: Dict[Tuple[str, str, str, str], int] = {}
        self.tmpdir_writes = 0
        self.tmpdir_samples: List[str] = []
        self.relative_unattributable = 0
        self.dropped_over_cap = 0
        self.errors: List[str] = []
        self.executed_order: List[str] = []
        self.spawns = 0
        self.spawn_nodeids: List[str] = []
        self.sqlite_buckets = {"file_backed": 0, "memory": 0, "read_only": 0}
        self.sqlite_nodeids: List[str] = []
        self.copy_verified_live: Optional[bool] = None
        self.copy_check_detail = ""
        self.sink: Optional[TextIO] = None


STATE = GateState()


#: Windows accepts both "\\" and "/"; on POSIX "\\" is a legal filename character, so
#: splitting on `os.sep` alone misclassifies forward-slash paths on Windows.
def accepted_separators(sep: str = os.sep, altsep: Optional[str] = os.altsep) -> Tuple[str, ...]:
    """The separators a platform honours, as a pure function of its two values.

    A function so the Windows derivation is testable from Linux, where `altsep` is None.
    """
    return tuple(dict.fromkeys(candidate for candidate in (sep, altsep) if candidate))


SEPARATORS: Tuple[str, ...] = accepted_separators()


def _split_path(path: str, separators: Optional[Tuple[str, ...]] = None) -> List[str]:
    """Split `path` on every separator this platform honours.

    The default is read at call time, so a test can monkeypatch `SEPARATORS` from Linux.
    """
    separators = SEPARATORS if separators is None else separators
    parts = [path]
    for sep in separators:
        parts = [piece for part in parts for piece in part.split(sep)]
    return parts


def _norm_sep(path: str, separators: Optional[Tuple[str, ...]] = None) -> str:
    """Rewrite every accepted separator to `os.sep` so prefixes compare."""
    separators = SEPARATORS if separators is None else separators
    for sep in separators:
        if sep != os.sep:
            path = path.replace(sep, os.sep)
    return path


def _under(path: str, root: str, separators: Optional[Tuple[str, ...]] = None) -> bool:
    """True if `path` is `root` itself or lives beneath it.

    Both sides are normalised: the root is native, the path is however the test typed it.
    """
    if not root:
        return False
    path, root = _norm_sep(path, separators), _norm_sep(root, separators)
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def classify(path: str, state: GateState = STATE) -> Tuple[str, str]:
    """Return `(verdict, reason)` for one absolute path.

    The copied tree is checked before every tmp allowance: the copy usually lives under
    TMPDIR (and `pytest-of-*`), so a tmp check first would acquit exactly these writes.
    """
    if path == state.log_path:
        return "allowed", "plugin_log"
    if state.canary_path and path == state.canary_path:
        return "canary", "canary"

    parts = _split_path(path)
    if "__pycache__" in parts:
        return "allowed", "pycache_dir"
    if ".pytest_cache" in parts:
        return "allowed", "pytest_cache_dir"

    name = parts[-1] if parts else ""
    if name.endswith((".pyc", ".pyo")):
        return "allowed", "bytecode"
    if name.startswith(".coverage"):
        return "allowed", "coverage_data"
    if path == os.devnull:
        return "allowed", "devnull"

    if _under(path, state.env_root):
        return "violation", "inside_copy"

    if _under(path, state.pytest_basetemp) or path.startswith(state.pytest_tmp_prefix):
        return "allowed", "pytest_tmp"

    if state.tmpdir_allowed and _under(path, state.tmp_root):
        return "allowed", "tmpdir"

    return "violation", "outside_copy"


def classify_sqlite(path: str) -> str:
    """Which sqlite bucket a connect target falls into.

    `connect` fires the same for `:memory:`, a read-only URI and a real file, so all three publish.
    """
    if path == ":memory:" or path.startswith("file::memory:"):
        return "memory"
    if path.startswith("file:") and ("mode=ro" in path or "mode=memory" in path):
        return "read_only" if "mode=ro" in path else "memory"
    return "file_backed"


def _note_error(state: GateState, where: str, exc: BaseException) -> None:
    """Record a swallowed exception rather than losing it.

    The hook must never raise, but an unseen exception is a fail-open mode.
    """
    if len(state.errors) < 20:
        state.errors.append(f"{where}: {type(exc).__name__}: {exc}"[:200])


def escapes_via_symlink(path: str, state: GateState = STATE) -> bool:
    """True when a path that looks contained really lands outside the copy.

    Only reachable in symlink-sibling mode.
    """
    if not state.env_root:
        return False
    try:
        return not _under(os.path.realpath(path), os.path.realpath(state.env_root))
    except OSError as exc:
        logger.debug("realpath failed for %s", path, exc_info=exc)
        _note_error(state, "realpath", exc)
        return False


def is_write_open(args: tuple) -> bool:
    """True if this `open` event is a write. Reads are not intercepted."""
    flags = args[2] if len(args) > 2 else 0
    if isinstance(flags, int) and flags & WRITE_FLAGS:
        return True
    mode = args[1] if len(args) > 1 else None
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _record_write(event: str, path: str, dir_fd: object = None) -> None:
    """Classify one path as allowed, canary or violation; with no dir_fd a relative path is the cwd's."""
    state = STATE
    if not isinstance(path, str) or not path:
        return
    if not os.path.isabs(path):
        if isinstance(dir_fd, int) and not isinstance(dir_fd, bool) and dir_fd >= 0:
            # dir_fd-relative (shutil.rmtree's inner unlinks): unresolvable here, so counted.
            state.relative_unattributable += 1
            return
        path = os.path.join(os.getcwd(), path)

    path = os.path.normpath(path)
    verdict, reason = classify(path, state)
    if verdict == "canary":
        state.canary_seen = True
        return
    if verdict == "allowed":
        if reason == "tmpdir":
            state.tmpdir_writes += 1
            if len(state.tmpdir_samples) < MAX_SAMPLES:
                state.tmpdir_samples.append(path)
        return

    key = (state.nodeid, state.phase, event, path)
    if key in state.violations:
        state.violations[key] += 1
    elif len(state.violations) < MAX_RECORDS:
        state.violations[key] = 1
    else:
        state.dropped_over_cap += 1


def _record_observation(event: str, args: tuple) -> bool:
    """Count a blind-spot event. Returns True if the event was one."""
    state = STATE

    if event.startswith(SPAWN_EVENTS):
        state.spawns += 1
        if state.nodeid not in state.spawn_nodeids and len(state.spawn_nodeids) < MAX_SAMPLES:
            state.spawn_nodeids.append(state.nodeid)
        return True

    if event == SQLITE_EVENT:
        target = args[0] if args else ""
        bucket = classify_sqlite(str(target))
        state.sqlite_buckets[bucket] += 1
        if state.nodeid not in state.sqlite_nodeids and len(state.sqlite_nodeids) < MAX_SAMPLES:
            state.sqlite_nodeids.append(state.nodeid)
        return True

    return False


def audit_hook(event: str, args: tuple) -> None:
    """The PEP 578 hook. Dispatches, and never raises into the suite."""
    state = STATE
    if state.emitting:
        return
    try:
        if _record_observation(event, args):
            return
        indices = PATH_ARGS.get(event)
        if indices is None:
            return
        if event == "open" and not is_write_open(args):
            return
        for index in indices:
            if index < len(args):
                fd_index = DIR_FD_ARGS.get((event, index))
                dir_fd = args[fd_index] if fd_index is not None and fd_index < len(args) else None
                _record_write(event, args[index], dir_fd)
    except Exception as exc:  # a hook must never break the suite it measures
        logger.debug("audit hook failed on %s", event, exc_info=exc)
        _note_error(state, f"hook:{event}", exc)


def emit(record: dict) -> None:
    """Write one JSONL record, with the hook muted for the duration."""
    state = STATE
    if state.sink is None:
        return
    state.emitting = True
    try:
        state.sink.write(json.dumps(record, sort_keys=True) + "\n")
        state.sink.flush()
    except Exception as exc:
        logger.debug("could not write the gate log", exc_info=exc)
        _note_error(state, "sink", exc)
    finally:
        state.emitting = False


def _factory_basetemp(config) -> str:
    """pytest's basetemp if it already exists; never create it from here.

    `getbasetemp()` makes the directory: a gate writing while deciding what a write is.
    """
    factory = getattr(config, "_tmp_path_factory", None)
    existing = getattr(factory, "_basetemp", None)
    return str(existing) if existing else ""


def pytest_configure(config) -> None:
    """Install the hook, open the sink, and declare the sandbox in the header."""
    state = STATE
    state.log_path = os.path.normpath(os.environ.get("AUDIT_TESTS_LOG", ""))
    if not state.log_path or state.log_path == ".":
        raise RuntimeError(
            "audit_hygiene_plugin: AUDIT_TESTS_LOG is unset. The gate refuses "
            "to run without a sink rather than run blind."
        )

    state.env_root = os.path.normpath(os.environ.get("AUDIT_TESTS_ENV_ROOT", "")) or ""
    state.target_root = os.path.normpath(os.environ.get("AUDIT_TESTS_TARGET_ROOT", "")) or ""
    state.target_module = os.environ.get("AUDIT_TESTS_TARGET_MODULE", "")
    state.tmpdir_allowed = os.environ.get("AUDIT_TESTS_TMPDIR_ALLOWED", "1") != "0"
    state.tmp_root = os.path.normpath(tempfile.gettempdir())

    # By layout: the factory does not exist yet at configure time, so it would read "".
    state.pytest_tmp_prefix = os.path.join(state.tmp_root, "pytest-of-")
    state.pytest_basetemp = _factory_basetemp(config)

    state.emitting = True
    try:
        os.makedirs(os.path.dirname(state.log_path) or ".", exist_ok=True)
        state.sink = open(state.log_path, "w", encoding="utf-8")
    finally:
        state.emitting = False

    if os.environ.get("AUDIT_TESTS_DISABLE_HOOK") == "1":
        state.hook_installed = False
    else:
        sys.addaudithook(audit_hook)
        state.hook_installed = True

    emit(
        {
            "rec": "header",
            "plugin_version": __version__,
            "started_at": time.time(),
            "pid": os.getpid(),
            "python": sys.version.split()[0],
            "hook_installed": state.hook_installed,
            "env_root": state.env_root,
            "target_root": state.target_root,
            "tmp_root": state.tmp_root,
            "pytest_basetemp": state.pytest_basetemp,
            "pytest_tmp_prefix": state.pytest_tmp_prefix,
            "tmpdir_allowed": state.tmpdir_allowed,
            "allowances": [{"name": n, "meaning": m} for n, m in ALLOWANCES],
            "observed_events": sorted(PATH_ARGS) + list(SPAWN_EVENTS) + [SQLITE_EVENT],
        }
    )


def pytest_sessionstart(session) -> None:
    """Assert the module under test is the COPY, before anything is measured.

    An editable install resolves `aipass.*` to the real repo unless PYTHONPATH wins.
    """
    state = STATE
    if not state.pytest_basetemp:
        state.pytest_basetemp = _factory_basetemp(session.config)

    if not state.target_module:
        state.copy_verified_live = None
        state.copy_check_detail = "no target module given (non-package target)"
    else:
        state.copy_verified_live, state.copy_check_detail = _resolve_target_module(state)

    emit(
        {
            "rec": "copy_check",
            "module": state.target_module,
            "verified_live": state.copy_verified_live,
            "resolved_to": state.copy_check_detail,
        }
    )


def _resolve_target_module(state: GateState) -> Tuple[bool, str]:
    """Import the target module and report whether it resolved inside the copy."""
    try:
        import importlib

        module = importlib.import_module(state.target_module)
        where = getattr(module, "__file__", None) or (list(getattr(module, "__path__", [])) or [""])[0]
        where = os.path.realpath(where) if where else ""
        root = os.path.realpath(state.env_root) if state.env_root else ""
        return bool(where) and _under(where, root), where or "module has neither __file__ nor __path__"
    except Exception as exc:
        logger.debug("import of %s failed", state.target_module, exc_info=exc)
        return False, f"{type(exc).__name__}: {exc}"


def pytest_runtest_logstart(nodeid, location) -> None:
    """Attribute what follows to this test, and record that it ran.

    Recorded here, not inferred from violations, which would list only the units that wrote.
    """
    STATE.nodeid, STATE.phase = nodeid, "setup"
    if nodeid not in STATE.executed_order:
        STATE.executed_order.append(nodeid)


def pytest_runtest_logfinish(nodeid, location) -> None:
    """Hand attribution back to the session between tests."""
    STATE.nodeid, STATE.phase = "<session>", "session"


def pytest_runtest_setup(item) -> None:
    """Mark the setup phase, so a fixture's writes are not blamed on the body."""
    STATE.nodeid, STATE.phase = item.nodeid, "setup"


def pytest_runtest_call(item) -> None:
    """Mark the call phase — the test body itself."""
    STATE.nodeid, STATE.phase = item.nodeid, "call"


def pytest_runtest_teardown(item, nextitem) -> None:
    """Mark the teardown phase; a cleanup that writes is still a write."""
    STATE.nodeid, STATE.phase = item.nodeid, "teardown"


# These three must run BEFORE pytest's own implementations, which are the ones
# that actually execute the phase they name.
pytest_runtest_setup.tryfirst = True  # type: ignore[attr-defined]
pytest_runtest_call.tryfirst = True  # type: ignore[attr-defined]
pytest_runtest_teardown.tryfirst = True  # type: ignore[attr-defined]


def fire_canary() -> dict:
    """Write outside the sandbox on purpose and check the gate noticed.

    Law T10: a clean suite and a switched-off gate both report zero; only this tells them apart.
    """
    state = STATE
    if not state.target_root:
        return {"attempted": False, "caught": False, "path": "", "error": "no target root configured"}

    state.canary_path = os.path.normpath(os.path.join(state.target_root, f".audit_tests_canary_{os.getpid()}"))
    state.canary_seen = False
    error = ""
    try:
        with open(state.canary_path, "w", encoding="utf-8") as handle:
            handle.write("audit-tests canary; removed immediately after the check\n")
    except OSError as exc:
        # An unwritable canary leaves the gate unproven; the reason travels to the artifact.
        logger.warning("canary write failed: %s", exc)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            # Only the sentinel this function created inside the scratch copy.
            os.unlink(state.canary_path)
        except OSError as exc:
            logger.debug("canary cleanup failed", exc_info=exc)
            _note_error(state, "canary-cleanup", exc)

    return {"attempted": True, "caught": bool(state.canary_seen), "path": state.canary_path, "error": error}


def pytest_sessionfinish(session, exitstatus) -> None:
    """Fire the canary, then publish every violation and the session summary.

    Never runs on a budget kill: no summary means no canary, and canary-or-refuse refuses.
    """
    state = STATE
    canary = fire_canary()

    for (nodeid, phase, event, path), count in sorted(state.violations.items()):
        where = classify(path, state)[1]
        emit(
            {
                "rec": "violation",
                "nodeid": nodeid,
                "phase": phase,
                "event": event,
                "path": path,
                "count": count,
                "where": where,
                "escapes_copy_via_symlink": where == "inside_copy" and escapes_via_symlink(path, state),
            }
        )

    emit(
        {
            "rec": "summary",
            "exitstatus": int(exitstatus),
            "hook_installed": state.hook_installed,
            "copy_verified_live": state.copy_verified_live,
            "copy_resolved_to": state.copy_check_detail,
            "canary": canary,
            "distinct_violations": len(state.violations),
            "dropped_over_cap": state.dropped_over_cap,
            "tmpdir_writes": state.tmpdir_writes,
            "tmpdir_samples": state.tmpdir_samples,
            "relative_unattributable": state.relative_unattributable,
            "executed_order": state.executed_order,
            "child_processes_spawned": state.spawns,
            "spawning_nodeids": state.spawn_nodeids,
            "sqlite3_connections": dict(state.sqlite_buckets),
            "sqlite3_nodeids": state.sqlite_nodeids,
            "swallowed_errors": state.errors,
            "finished_at": time.time(),
        }
    )

    if state.sink is not None:
        state.emitting = True
        try:
            state.sink.close()
        finally:
            state.sink = None
            state.emitting = False
