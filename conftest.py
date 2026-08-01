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

import sys
import types
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent


def _points_into_repo(mod: types.ModuleType) -> bool:
    """True if mod's *JSON_DIR* constant currently resolves inside this repo."""
    for name, val in vars(mod).items():
        if "JSON_DIR" not in name or not isinstance(val, (str, Path)):
            continue
        try:
            Path(str(val)).resolve().relative_to(_REPO_ROOT)
            return True
        except ValueError:
            return False
    return False


def _guarded(mod: types.ModuleType, real):
    def log_operation(*args, **kwargs):
        if _points_into_repo(mod):
            return True
        return real(*args, **kwargs)

    return log_operation


@pytest.fixture(autouse=True)
def _no_shared_json_log_writes(monkeypatch):
    for name, mod in list(sys.modules.items()):
        if not name.startswith("aipass.") or not name.endswith("json_handler"):
            continue
        if not isinstance(mod, types.ModuleType):
            continue  # MagicMock stand-ins installed by a test's own fixture
        real = getattr(mod, "log_operation", None)
        if real is None or not callable(real) or hasattr(real, "reset_mock"):
            continue  # absent, or already replaced by a test's mock
        monkeypatch.setattr(mod, "log_operation", _guarded(mod, real))
