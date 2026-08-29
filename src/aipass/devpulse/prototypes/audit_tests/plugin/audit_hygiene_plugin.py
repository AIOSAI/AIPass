# =================== AIPass ====================
# Name: audit_hygiene_plugin.py - filesystem-write hygiene gate (MVP prototype)
# Description: pytest plugin; sys.addaudithook write gate with node-id attribution
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""Filesystem-write hygiene gate for the ``audit-tests`` lane (MVP prototype).

Injected into a pytest run with ``-p audit_hygiene_plugin``.  A
``sys.addaudithook`` (PEP 578) hook records every write-ish filesystem event and
attributes it to the pytest node id that was running when it fired.

The plugin is configured entirely through environment variables: it is imported
inside a scratch copy of somebody else's branch and must not depend on the CLI
package that launched it.

    AUDIT_TESTS_LOG            JSONL sink (required; the plugin refuses without it)
    AUDIT_TESTS_ENV_ROOT       root of the scratch copy - writes under it are
                               violations unless a declared allowance covers them
    AUDIT_TESTS_TARGET_ROOT    the copied target dir; where the canary is written
    AUDIT_TESTS_TARGET_MODULE  dotted module asserted to resolve under the copy
    AUDIT_TESTS_TMPDIR_ALLOWED "0" removes the blanket TMPDIR allowance
    AUDIT_TESTS_DISABLE_HOOK   "1" leaves the hook off - the seam that proves the
                               canary can refuse (Law T10); never set in a real run

Everything this file treats as legitimate is in ``ALLOWANCES``, which the CLI
copies verbatim into the artifact.  Widening the sandbox silently is the one
thing a gate may never do.
"""

from __future__ import annotations

import json
import os
import logging
import sys
import tempfile
import time
from typing import TextIO

__version__ = "0.1.0"

# --------------------------------------------------------------------------- #
# Declared sandbox.  Order matters and is the order the classifier applies.
# --------------------------------------------------------------------------- #

logger = logging.getLogger("audit_tests.hygiene_gate")

ALLOWANCES = [
    ("plugin_log", "the hygiene log this plugin writes, by exact path"),
    ("canary", "the plugin's own canary sentinel, by exact path"),
    ("pycache_dir", "any path with a __pycache__ component"),
    ("pytest_cache_dir", "any path with a .pytest_cache component"),
    ("bytecode", "a file whose name ends .pyc or .pyo"),
    ("coverage_data", "a file whose name starts .coverage"),
    ("devnull", "os.devnull itself - pytest's logging plugin opens it every session"),
    ("pytest_tmp", "pytest's basetemp tree - <TMPDIR>/pytest-of-* and the factory's own root"),
    ("tmpdir", "anything under TMPDIR"),
]

#: Checked before pytest_tmp and tmpdir: anything inside the scratch copy is a
#: violation whatever else it also looks like.
COPY_BEATS_TMP_ALLOWANCES = True

# Audit events that can mutate the filesystem, and which positional args of each
# carry a path.  Verified against CPython 3.12 by direct probe, not from docs.
_PATH_ARGS = {
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

# open() reports (path, mode, flags).  ``mode`` is None when the call came
# through os.open, so ``flags`` is the only universally present signal.
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

_MAX_RECORDS = 20000
_MAX_TMPDIR_SAMPLES = 25


class _State:
    """Everything the hook touches.  One object so the hook does one lookup."""

    def __init__(self) -> None:
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
        self.violations: dict[tuple[str, str, str, str], int] = {}
        self.tmpdir_writes = 0
        self.tmpdir_samples: list[str] = []
        self.relative_unattributable = 0
        self.dropped_over_cap = 0
        self.errors: list[str] = []
        self.copy_verified_live: bool | None = None
        self.copy_check_detail = ""
        self.sink: TextIO | None = None


_S = _State()


# --------------------------------------------------------------------------- #
# Classification
# --------------------------------------------------------------------------- #


def _under(path: str, root: str) -> bool:
    if not root:
        return False
    return path == root or path.startswith(root.rstrip(os.sep) + os.sep)


def classify(path: str, state: _State = _S) -> tuple[str, str]:
    """Return ``(verdict, reason)`` for one absolute path.

    ``verdict`` is one of ``allowed``, ``violation`` or ``canary``.  The reason
    is the allowance name that acquitted it, or where the violation landed.
    """
    if path == state.log_path:
        return "allowed", "plugin_log"
    if state.canary_path and path == state.canary_path:
        return "canary", "canary"

    parts = path.split(os.sep)
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

    # Precedence, and it is the whole point: the copied tree is checked BEFORE
    # every tmp allowance, because a scratch copy usually lives under TMPDIR --
    # and when the copy is made from inside another pytest run it lives under a
    # pytest-of-* tree too. Either allowance checked first would acquit exactly
    # the writes this gate exists to catch.
    if _under(path, state.env_root):
        return "violation", "inside_copy"

    if _under(path, state.pytest_basetemp) or path.startswith(state.pytest_tmp_prefix):
        return "allowed", "pytest_tmp"

    if state.tmpdir_allowed and _under(path, state.tmp_root):
        return "allowed", "tmpdir"

    return "violation", "outside_copy"


def _note_error(state: _State, where: str, exc: BaseException) -> None:
    """Record a swallowed exception instead of losing it.

    The hook and the sink must never raise -- a gate that kills the suite it is
    measuring is worse than no gate. But an exception nobody ever sees is a
    fail-open mode, and this fleet has shipped one of those before, so the count
    and the first few messages go into the artifact.
    """
    if len(state.errors) < 20:
        state.errors.append(f"{where}: {type(exc).__name__}: {exc}"[:200])


def _escapes_via_symlink(path: str, state: _State = _S) -> bool:
    """True when a path inside the copy really lands outside it.

    Sibling packages are symlinked into the scratch env, so a write that looks
    contained can still reach the real tree.  Saying so is Law M10's business.
    """
    if not state.env_root:
        return False
    try:
        return not _under(os.path.realpath(path), os.path.realpath(state.env_root))
    except OSError as exc:
        logger.debug("realpath failed for %s", path, exc_info=exc)
        _note_error(state, "realpath", exc)
        return False


# --------------------------------------------------------------------------- #
# The hook
# --------------------------------------------------------------------------- #


def _is_write_open(args: tuple) -> bool:
    flags = args[2] if len(args) > 2 else 0
    if isinstance(flags, int) and flags & _WRITE_FLAGS:
        return True
    mode = args[1] if len(args) > 1 else None
    return isinstance(mode, str) and any(c in mode for c in "wax+")


def _record(event: str, path: str) -> None:
    state = _S
    if not isinstance(path, str) or not path:
        return
    if not os.path.isabs(path):
        # A dir_fd-relative path (shutil.rmtree's inner unlinks). Unresolvable
        # from here; counted rather than guessed at.
        state.relative_unattributable += 1
        return
    path = os.path.normpath(path)
    verdict, reason = classify(path, state)
    if verdict == "canary":
        state.canary_seen = True
        return
    if verdict == "allowed":
        if reason == "tmpdir":
            state.tmpdir_writes += 1
            if len(state.tmpdir_samples) < _MAX_TMPDIR_SAMPLES:
                state.tmpdir_samples.append(path)
        return
    key = (state.nodeid, state.phase, event, path)
    if key in state.violations:
        state.violations[key] += 1
    elif len(state.violations) < _MAX_RECORDS:
        state.violations[key] = 1
    else:
        state.dropped_over_cap += 1


def _audit_hook(event: str, args: tuple) -> None:
    state = _S
    if state.emitting:
        return
    indices = _PATH_ARGS.get(event)
    if indices is None:
        return
    try:
        if event == "open" and not _is_write_open(args):
            return
        for i in indices:
            if i < len(args):
                _record(event, args[i])
    except Exception as exc:  # a hook must never break the suite it measures
        logger.debug("audit hook failed on %s", event, exc_info=exc)
        _note_error(state, f"hook:{event}", exc)


# --------------------------------------------------------------------------- #
# Sink
# --------------------------------------------------------------------------- #


def _emit(record: dict) -> None:
    state = _S
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


# --------------------------------------------------------------------------- #
# pytest hooks
# --------------------------------------------------------------------------- #


def pytest_configure(config) -> None:
    """Install the hook, open the sink, and declare the sandbox in the header."""
    state = _S
    state.log_path = os.path.normpath(os.environ.get("AUDIT_TESTS_LOG", ""))
    if not state.log_path:
        raise RuntimeError(
            "audit_hygiene_plugin: AUDIT_TESTS_LOG is unset. The gate refuses to "
            "run without a sink rather than run blind."
        )
    state.env_root = os.path.normpath(os.environ.get("AUDIT_TESTS_ENV_ROOT", "")) or ""
    state.target_root = os.path.normpath(os.environ.get("AUDIT_TESTS_TARGET_ROOT", "")) or ""
    state.target_module = os.environ.get("AUDIT_TESTS_TARGET_MODULE", "")
    state.tmpdir_allowed = os.environ.get("AUDIT_TESTS_TMPDIR_ALLOWED", "1") != "0"
    state.tmp_root = os.path.normpath(tempfile.gettempdir())

    # pytest's own tmp root, by layout rather than by private attribute. The
    # factory is not built yet at pytest_configure time, so reading
    # config._tmp_path_factory here silently yields "" -- which left this whole
    # allowance dead until a mutation of it failed to kill any test.
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
        sys.addaudithook(_audit_hook)
        state.hook_installed = True

    _emit(
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
        }
    )


def _factory_basetemp(config) -> str:
    """pytest's basetemp if it already exists; never create it from in here.

    ``getbasetemp()`` makes the directory, and a gate that writes while deciding
    what counts as a write is measuring itself.
    """
    factory = getattr(config, "_tmp_path_factory", None)
    existing = getattr(factory, "_basetemp", None)
    return str(existing) if existing else ""


def pytest_sessionstart(session) -> None:
    """Assert the module under test is the copy, before anything is measured.

    Harness-integrity check #3 (DESIGN_BRIEF §C.2h): an editable install can
    resolve ``aipass.*`` straight back to the real repo, and then every number
    below describes a tree we are not allowed to touch.
    """
    state = _S
    if not state.pytest_basetemp:
        state.pytest_basetemp = _factory_basetemp(session.config)
    if not state.target_module:
        state.copy_verified_live = None
        state.copy_check_detail = "no target module given (non-package target)"
    else:
        try:
            import importlib

            mod = importlib.import_module(state.target_module)
            where = getattr(mod, "__file__", None) or (list(getattr(mod, "__path__", [])) or [""])[0]
            where = os.path.realpath(where) if where else ""
            root = os.path.realpath(state.env_root) if state.env_root else ""
            state.copy_verified_live = bool(where) and _under(where, root)
            state.copy_check_detail = where or "module has neither __file__ nor __path__"
        except Exception as exc:
            logger.debug("import of %s failed", state.target_module, exc_info=exc)
            state.copy_verified_live = False
            state.copy_check_detail = f"{type(exc).__name__}: {exc}"
    _emit(
        {
            "rec": "copy_check",
            "module": state.target_module,
            "verified_live": state.copy_verified_live,
            "resolved_to": state.copy_check_detail,
        }
    )


def pytest_runtest_logstart(nodeid, location) -> None:
    """Attribute what follows to this test, from the first line pytest logs."""
    _S.nodeid, _S.phase = nodeid, "setup"


def pytest_runtest_logfinish(nodeid, location) -> None:
    """Hand attribution back to the session between tests."""
    _S.nodeid, _S.phase = "<session>", "session"


def pytest_runtest_setup(item) -> None:
    """Mark the setup phase, so a fixture's writes are not blamed on the body."""
    _S.nodeid, _S.phase = item.nodeid, "setup"


def pytest_runtest_call(item) -> None:
    """Mark the call phase -- the test body itself."""
    _S.nodeid, _S.phase = item.nodeid, "call"


def pytest_runtest_teardown(item, nextitem) -> None:
    """Mark the teardown phase; a cleanup that writes is still a write."""
    _S.nodeid, _S.phase = item.nodeid, "teardown"


# The three above must run before pytest's own implementations, which are the
# ones that actually execute the phase.
pytest_runtest_setup.tryfirst = True  # type: ignore[attr-defined]
pytest_runtest_call.tryfirst = True  # type: ignore[attr-defined]
pytest_runtest_teardown.tryfirst = True  # type: ignore[attr-defined]


def _fire_canary() -> dict:
    """Write outside the sandbox on purpose and check the gate noticed.

    Law T10: every negative instrument needs a proof that it can fire.  A gate
    that reports zero because it is switched off looks exactly like a clean
    suite, and this is the only thing that tells the two apart.
    """
    state = _S
    if not state.target_root:
        return {"attempted": False, "caught": False, "error": "no target root configured"}
    path = os.path.join(state.target_root, f".audit_tests_canary_{os.getpid()}")
    state.canary_path = os.path.normpath(path)
    state.canary_seen = False
    error = ""
    try:
        with open(state.canary_path, "w", encoding="utf-8") as fh:
            fh.write("audit-tests canary; deleted immediately after the check\n")
    except OSError as exc:
        # A canary that cannot even be written leaves the gate unproven, so the
        # reason travels in the returned dict and out to the artifact as well.
        logger.warning("canary write failed: %s", exc)
        error = f"{type(exc).__name__}: {exc}"
    finally:
        try:
            # Exactly one path is ever removed here: the sentinel this
            # function created, seconds ago, inside the scratch copy.
            os.unlink(state.canary_path)
        except OSError as exc:
            logger.debug("canary cleanup failed", exc_info=exc)
            _note_error(state, "canary-cleanup", exc)
    return {
        "attempted": True,
        "caught": bool(state.canary_seen),
        "path": state.canary_path,
        "error": error,
    }


def pytest_sessionfinish(session, exitstatus) -> None:
    """Fire the canary, then publish every violation and the session summary."""
    state = _S
    canary = _fire_canary()
    for (nodeid, phase, event, path), count in sorted(state.violations.items()):
        _emit(
            {
                "rec": "violation",
                "nodeid": nodeid,
                "phase": phase,
                "event": event,
                "path": path,
                "count": count,
                "where": classify(path, state)[1],
                "escapes_copy_via_symlink": (
                    classify(path, state)[1] == "inside_copy" and _escapes_via_symlink(path, state)
                ),
            }
        )
    _emit(
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
