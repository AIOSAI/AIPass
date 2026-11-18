# =================== AIPass ====================
# Name: state_root.py
# Description: Where a branch's logs/ and <branch>_json/ live: beside its code, or under the home folder when installed
# Version: 1.0.0
# Created: 2026-11-17
# Modified: 2026-11-17
# =============================================

"""The one answer to where a branch keeps its state; stdlib only, so trail and the json service can use it."""

import errno
import importlib.util
import os
import sysconfig
from pathlib import Path

STATE_HOME = Path(".aipass") / "state"


class StateRootUnwritable(OSError):
    """A branch's state folder cannot be written: nothing is left to report through, so this is raised."""


def is_installed(branch_root: Path) -> bool:
    """True under this interpreter's purelib or platlib; a venv under ~/src/proj/.venv is still an install."""
    here = Path(os.path.realpath(branch_root))
    paths = sysconfig.get_paths()
    return any(here.is_relative_to(os.path.realpath(paths[key])) for key in ("purelib", "platlib"))


def state_home(branch_root: Path) -> Path:
    """Where an installed branch keeps state (the home folder); a checkout keeps it beside its code."""
    if is_installed(branch_root):
        return Path.home() / STATE_HOME / branch_root.name
    return branch_root


def state_root_of(branch_root: Path) -> Path:
    """state_home, unless AIPASS_TEST_LOG_DIR redirects it; read per call, an empty value is absence."""
    test_dir = os.environ.get("AIPASS_TEST_LOG_DIR")
    if test_dir:
        return Path(test_dir) / branch_root.name
    return state_home(branch_root)


def branch_root(branch: str) -> Path:
    """A branch's code folder, found by its package name, never by counting folders up from a file."""
    spec = importlib.util.find_spec(f"aipass.{branch}")
    if spec is None or not spec.submodule_search_locations:
        raise LookupError(f"no AIPass branch package named {branch!r}")
    return Path(list(spec.submodule_search_locations)[0])


def branch_state_root(branch: str) -> Path:
    """The folder holding branch's logs/ and <branch>_json/: branch_state_root("flow") / "flow_json"."""
    return state_root_of(branch_root(branch))


def writable_dir(path: Path) -> Path:
    """Create path if needed; StateRootUnwritable naming the folder and the errno when it cannot be written."""
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        name = errno.errorcode.get(exc.errno or 0, str(exc.errno))
        raise StateRootUnwritable(exc.errno, f"state folder cannot be written: {path} ({name})") from exc
    if not os.access(path, os.W_OK | os.X_OK):
        raise StateRootUnwritable(errno.EACCES, f"state folder cannot be written: {path} (EACCES)")
    return path
