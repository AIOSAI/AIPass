"""Trigger handlers package - the fence.

A branch's handlers are its own. Any code outside this branch reaches it
through aipass.trigger.apps.modules, never by importing these handlers:
an agent cannot change a module it does not own to suit its needs, so the
only honest door is the one the owner publishes. This file is the fence. It
reads the stack once, at import time, and refuses a foreign importer with an
ImportError that names the caller, the file and the line.

What the walk sees, from this file outward, in three kinds:
  kin        a frame whose file lives under /aipass/trigger/ - this branch
  transport  Python's own machinery between an importer and this file:
             importlib and the frozen bootstrap, any standard-library module
             (unittest.mock, pkgutil, runpy, pickle), and third-party
             libraries under site-packages (pytest's monkeypatch); none of
             these is anybody's code in the sense the rule means
  foreign    everything else: another branch, a project, a user's script

The first foreign frame decides. It is refused when no kin frame stood
between it and this file (it imported the handlers itself, by any route,
import_module and a variable name included) or when its own source line
names these handlers (an import that reached here through this branch's
package __init__ chain). It is allowed when kin code asked for the import
on its behalf - that is the modules door working.

Measured 2026-04-25 and traced 2026-10-07: mock.patch on a handlers path
imports the package from unittest/mock.py's frame, and a fence that read
that frame as the caller refused the branch's own tests on Python 3.10. The
fix then was 'from . import handlers' in every apps/__init__.py, which made
this package's own parent the first frame every time, and the fence
decorative for five months. The transport rule above is the right cure.

A limit, stated: an import-time fence fires on the FIRST import of this
package in a process. Once kin code has imported it, a later foreign import
is served from sys.modules and no import machinery sees it. The write-time
rule (drone @seedgo audit: handlers and encapsulation) is the wall; this
is the door.
"""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "trigger"

_HANDLERS_SPELLINGS = (
    "aipass." + MY_BRANCH + ".apps.handlers",
    "aipass." + MY_BRANCH + ".apps import handlers",
)
_THIRD_PARTY_DIRS = ("/site-packages/", "/dist-packages/")

try:
    _THIS_FILE = str(Path(__file__).resolve()).replace("\\", "/")
except OSError:
    _THIS_FILE = str(__file__).replace("\\", "/")
# .../aipass/<branch>/apps/handlers/__init__.py: the branch is three parents up,
# the fleet one more. Exact prefixes, never a substring: a directory that happens
# to share a branch's name is not that branch, and an installed wheel's copy of
# this file knows its own branch root the same way.
_BRANCH_ROOT = _THIS_FILE.rsplit("/", 3)[0] + "/"
_FLEET_ROOT = _THIS_FILE.rsplit("/", 4)[0] + "/"


def _frame_path(frame) -> str:
    """The frame's file as a forward-slash absolute path, or its raw spelling.

    A pseudo filename (<frozen importlib._bootstrap>, <string>, <stdin>) is
    not a path and is never resolved: relative, it would resolve against the
    process cwd, and with the cwd inside this branch every bootstrap frame
    would read as kin (measured 2026-10-08, devpulse's flip).
    Path.resolve routes through ntpath.realpath, which reads os.getcwd
    unconditionally; a process whose cwd was deleted must not die here.
    """
    raw = frame.f_code.co_filename
    if raw.startswith("<"):
        return raw
    try:
        return str(Path(raw).resolve()).replace("\\", "/")
    except OSError:
        return raw.replace("\\", "/")


def _classify(frame, path: str) -> str:
    """'self', 'kin', 'transport' or 'foreign' - see the module docstring.

    Order matters: a branch path under site-packages (the installed wheel)
    is that branch, never transport.
    """
    raw = frame.f_code.co_filename
    if path == _THIS_FILE or raw == __file__:
        return "self"
    if path.startswith(_BRANCH_ROOT):
        return "kin"
    if raw.startswith("<") or "importlib" in raw:
        return "transport"
    if path.startswith(_FLEET_ROOT):
        return "foreign"
    top = frame.f_globals.get("__name__", "").partition(".")[0]
    if top in sys.stdlib_module_names:
        return "transport"
    if any(marker in path for marker in _THIRD_PARTY_DIRS):
        return "transport"
    return "foreign"


def _first_foreign_frame():
    """Walk outward from the fence. Returns (frame, path, kin_seen) for the
    first foreign frame, or (None, None, kin_seen) when the stack holds none."""
    kin_seen = False
    frame = sys._getframe(1)
    while frame is not None:
        path = _frame_path(frame)
        kind = _classify(frame, path)
        if kind == "foreign":
            return frame, path, kin_seen
        if kind == "kin":
            kin_seen = True
        frame = frame.f_back
    return None, None, kin_seen


def _extract_branch_name(filepath: str) -> str:
    """The segment after the last 'aipass' in a path, or 'unknown'."""
    parts = Path(filepath).parts
    for i in range(len(parts) - 1, -1, -1):
        if parts[i] == "aipass" and i + 1 < len(parts):
            return parts[i + 1]
    return "unknown"


def _guard_branch_access() -> None:
    """Refuse a foreign importer of these handlers; let kin and transport pass."""
    frame, caller_path, kin_seen = _first_foreign_frame()
    if frame is None or caller_path is None:  # both None together; the second test narrows the type
        return

    try:
        import_line = linecache.getline(frame.f_code.co_filename, frame.f_lineno).strip()
    except OSError:
        import_line = ""

    names_handlers = any(spelling in import_line for spelling in _HANDLERS_SPELLINGS)
    if kin_seen and not names_handlers:
        return

    caller_branch = _extract_branch_name(caller_path)
    raise ImportError(
        f"\n{'=' * 60}\n"
        f"ACCESS DENIED: Cross-branch handler import blocked\n"
        f"{'=' * 60}\n"
        f"  Caller branch: {caller_branch}\n"
        f"  Caller file:   {Path(caller_path).name}\n"
        f"  Blocked:       {import_line or 'unknown'}\n"
        f"\n"
        f"  Handlers are internal to their branch.\n"
        f"  Use the module API instead:\n"
        f"    from aipass.{MY_BRANCH}.apps.modules.<module> import <function>\n"
        f"\n"
        f"  For full standards guide:\n"
        f"    drone @seedgo handlers\n"
        f"{'=' * 60}"
    )


# Run the fence at import time
_guard_branch_access()
