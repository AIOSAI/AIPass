"""Daemon handlers package - the fence.

Another branch reaches these handlers only through aipass.daemon.apps.modules; this refuses a foreign importer.
Frames are kin (this branch), transport (importlib, stdlib such as unittest.mock, site-packages) or foreign.
The first foreign frame is refused unless kin code imported on its behalf and its line does not name the handlers.
Fires only on a process's first import; the wall is drone @seedgo audit (handlers, encapsulation).
"""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "daemon"

_HANDLERS_SPELLINGS = (
    "aipass." + MY_BRANCH + ".apps.handlers",
    "aipass." + MY_BRANCH + ".apps import handlers",
)
_THIRD_PARTY_DIRS = ("/site-packages/", "/dist-packages/")

try:
    _THIS_FILE = str(Path(__file__).resolve()).replace("\\", "/")
except OSError:
    _THIS_FILE = str(__file__).replace("\\", "/")
# Exact prefixes, never a substring: a directory that merely shares a branch's name is not that branch.
_BRANCH_ROOT = _THIS_FILE.rsplit("/", 3)[0] + "/"
_FLEET_ROOT = _THIS_FILE.rsplit("/", 4)[0] + "/"


def _frame_path(frame) -> str:
    """The frame's file as a forward-slash absolute path, or its raw spelling."""
    raw = frame.f_code.co_filename
    # A pseudo filename resolved against a cwd inside this branch would make every bootstrap frame kin.
    if raw.startswith("<"):
        return raw
    # resolve() reads os.getcwd (ntpath.realpath); a process whose cwd was deleted must not die here.
    try:
        return str(Path(raw).resolve()).replace("\\", "/")
    except OSError:
        return raw.replace("\\", "/")


def _classify(frame, path: str) -> str:
    """'self', 'kin', 'transport' or 'foreign' - see the module docstring."""
    # Order matters: a branch path under site-packages (the installed wheel) is that branch, never transport.
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


_guard_branch_access()
