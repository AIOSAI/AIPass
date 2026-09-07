"""Repo-root pytest configuration.

Keeps tests off the repo's shared per-branch JSON files under parallel runs.

Every branch has a templated ``json_handler`` whose ``log_operation`` does an
unlocked read-modify-write on that branch's ``<branch>_json/*_log.json``
files. Tests that exercise real production paths therefore contend on those
shared files, and under pytest-xdist two tests of the same branch on
different workers race: a reader catches the file mid-truncate and dies with
``JSONDecodeError: Expecting value`` (seen live in daemon runstate, hooks
trust_registry, seedgo bypass utils), and a torn write leaves debris that
breaks later runs deterministically until an ``ensure_*`` path regenerates
the file.

The autouse fixture below wraps ``log_operation`` on every loaded
``aipass.*json_handler`` module. At call time the wrapper checks where the
module's ``*JSON_DIR*`` constant currently points: inside this repo → the
write is skipped (tests must not mutate shared repo state); anywhere else
(tests that patch the dir to tmp_path) → the real function runs, so the
json_handler unit tests keep their full behavior. Mock modules and
mock-replaced functions are left untouched.
"""

import os
import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent
_FLEET_SERVICE_MODULE = "aipass.prax.apps.handlers.json.json_service"


def _binds_the_fleet_service(function) -> bool:
    """True when ``log_operation`` is a bound method of prax's ``JsonHandle``.

    DPLAN-0325 (2026-09-03): the fleet has ONE json handler source. A branch's
    ``json_handler.py`` is a zero-token shim that BINDS the service's methods
    and never wraps them — the service resolves the calling module at frame 2
    and the branch's document directory PER CALL, honouring
    ``AIPASS_TEST_LOG_DIR`` itself. Wrapping such a name here would put a
    frame between caller and service (every log entry attributed to this
    conftest) and break the shim's own bind-not-wrap pin, which is exactly
    what happened on the first repo-root CI run after prax landed. The
    redirect the wrapper exists to enforce is the service's job for these
    modules; ``_no_shared_json_log_writes`` checks the seam is armed instead.
    """
    owner = getattr(function, "__self__", None)
    if owner is None:
        return False
    return type(owner).__name__ == "JsonHandle" and type(owner).__module__ == _FLEET_SERVICE_MODULE


def _points_into_repo(mod: types.ModuleType) -> bool:
    """True if mod's next log write would land inside this repo.

    Seam-adopted handlers (prax's 2026-08-30 contract) expose
    ``_current_json_dir()`` — the same resolver their own write consults, per
    call, honouring both a monkeypatched ``JSON_DIR`` and the
    ``AIPASS_TEST_LOG_DIR`` redirect. When it exists, ask IT: re-deriving the
    answer here from constants is a second implementation, and it already
    misfired once — the seam's ``_IMPORT_TIME_JSON_DIR`` fixed point is
    env-independent BY CONTRACT (always the real dir), so a substring scan
    read every seam-adopted module as unpatched and skipped writes their
    tests were asserting on (CI-only: this conftest loads only on repo-root
    runs, which is why 12 log_operation tests were green per-branch and red
    in CI on 2026-08-31).

    Handlers without the seam keep the constant scan, with one narrowing:
    underscore-private names are anchors, not the live dir, and are ignored.
    A public *JSON_DIR* patched outside the repo means the test controls the
    write; all-inside means production state, skip.
    """
    resolver = getattr(mod, "_current_json_dir", None)
    if callable(resolver):
        try:
            target = Path(str(resolver())).resolve()
        except Exception as exc:  # a broken resolver must fail safe: skip the write
            # Lazy prax import: every wrapped module already imported prax
            # itself, and importing it at conftest top would start the logger
            # for every collection this guard exists to keep quiet.
            from aipass.prax import logger

            logger.warning(
                "conftest guard: %s._current_json_dir raised %r — failing safe, write skipped",
                mod.__name__,
                exc,
            )
            return True
        return target.is_relative_to(_REPO_ROOT)
    verdict = False
    for name, val in vars(mod).items():
        if name.startswith("_"):
            continue
        if "JSON_DIR" not in name or not isinstance(val, (str, Path)):
            continue
        if Path(str(val)).resolve().is_relative_to(_REPO_ROOT):
            verdict = True
        else:
            return False
    return verdict


def _guarded(mod: types.ModuleType, real):
    def log_operation(*args, **kwargs):
        if _points_into_repo(mod):
            return True
        return real(*args, **kwargs)

    return log_operation


@pytest.fixture(autouse=True)
def _no_shared_json_log_writes():
    wrapped = []
    for name, mod in list(sys.modules.items()):
        if not name.startswith("aipass.") or not name.endswith("json_handler"):
            continue
        if not isinstance(mod, types.ModuleType):
            continue  # MagicMock stand-ins installed by a test's own fixture
        real = getattr(mod, "log_operation", None)
        if real is None or not callable(real) or hasattr(real, "reset_mock"):
            continue  # absent, or already replaced by a test's mock
        if _binds_the_fleet_service(real):
            # One-source shim: the service redirects per call. A repo-root run
            # without the seam armed would write into live trees, so that is
            # an error here, not a silently skipped write.
            if not os.environ.get("AIPASS_TEST_LOG_DIR"):
                raise RuntimeError(
                    f"{mod.__name__} binds the fleet json service but AIPASS_TEST_LOG_DIR is not set — "
                    "every branch conftest sets it at import; a repo-root run reaching this point "
                    "without it would write into live <branch>_json directories"
                )
            continue
        wrapper = _guarded(mod, real)
        setattr(mod, "log_operation", wrapper)
        wrapped.append((mod, wrapper, real))
    yield
    for mod, wrapper, real in wrapped:
        # Restore ONLY if our wrapper is still in place. If the test reloaded
        # the module, log_operation was rebound to a fresh object consistent
        # with the reloaded module — blind-restoring the pre-reload one would
        # permanently split it from its siblings (spawn re-exports BOUND
        # METHODS of a handler instance; the stale method keeps the old
        # instance and its real repo dir forever). Live-caught on
        # spawn/tests/test_contracts.py::test_reimport_after_mock.
        if getattr(mod, "log_operation", None) is wrapper:
            setattr(mod, "log_operation", real)
