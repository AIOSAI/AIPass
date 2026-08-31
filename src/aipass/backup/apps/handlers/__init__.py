"""BACKUP handlers package - Security protected.

The branch's ONE safe path helper lives in ``path/module_paths.py``; this
package's own module-level paths go through it for the same reason every other
module does -- ``Path.resolve()`` reached at import time is an import-time crash
on Windows for a process whose cwd was deleted.
"""

import linecache
import sys
from pathlib import Path

from .path.module_paths import branch_root, module_file  # noqa: F401  (re-exported)

MY_BRANCH = "backup"

#: Frames that are not real files on disk. Resolving one needs a cwd, so they
#: are skipped BEFORE anything touches the filesystem.
_PSEUDO_FRAME_PREFIX = "<"
_IMPORT_MACHINERY = "importlib"

_HANDLER_DIR = str(module_file(__file__).parent)
_BRANCH_ROOT = str(branch_root(__file__, 2))


def _find_real_caller():
    """Walk the stack to find the actual file that triggered this import.

    Uses ``sys._getframe`` rather than ``inspect.stack()``. ``inspect.stack()``
    calls ``getmodule`` -> ``getabsfile`` -> ``os.path.realpath`` on EVERY frame
    with no guard (inspect.py:1009), so it dies on a dead cwd before this
    function's own skip logic is ever consulted. Reading ``f_code.co_filename``
    off the frame touches no filesystem at all.

    Returns tuple: (file_path, import_line) or (None, None).
    """
    this_file = str(module_file(__file__))

    try:
        frame = sys._getframe(1)
    except ValueError:
        return None, None

    while frame is not None:
        filename = frame.f_code.co_filename

        # Skip Python internals BEFORE touching the filesystem — resolving a
        # pseudo-filename like <string> needs a cwd, and a process whose cwd
        # was deleted dies here otherwise.
        if filename.startswith(_PSEUDO_FRAME_PREFIX) or _IMPORT_MACHINERY in filename:
            frame = frame.f_back
            continue

        # A relative frame filename also needs a cwd to resolve; fall back to
        # the raw spelling rather than crashing the import.
        try:
            resolved = str(Path(filename).resolve())
        except OSError:
            resolved = filename

        if this_file in resolved:
            frame = frame.f_back
            continue

        import_line = linecache.getline(filename, frame.f_lineno).strip() or None
        return resolved, import_line

    return None, None


def _extract_branch_name(filepath: str) -> str:
    """Extract branch name from a file path."""
    parts = Path(filepath).parts
    for i, part in enumerate(parts):
        if part == "aipass":
            if i + 1 < len(parts):
                return parts[i + 1]
    return "unknown"


def _guard_branch_access():
    """Block cross-branch handler imports.

    Only code from within the 'backup' branch can import these handlers.
    External branches must use aipass.backup.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    if caller_file is None:
        return

    if _BRANCH_ROOT in caller_file.replace("\\", "/"):
        return

    caller_branch = _extract_branch_name(caller_file)
    caller_filename = Path(caller_file).name
    blocked_import = import_line if import_line else "unknown"

    raise ImportError(
        f"\n{'=' * 60}\n"
        f"ACCESS DENIED: Cross-branch handler import blocked\n"
        f"{'=' * 60}\n"
        f"  Caller branch: {caller_branch}\n"
        f"  Caller file:   {caller_filename}\n"
        f"  Blocked:       {blocked_import}\n"
        f"\n"
        f"  Handlers are internal to their branch.\n"
        f"  Use the module API instead (apps/modules/).\n"
        f"\n"
        f"  For full standards guide:\n"
        f"    drone @seedgo handlers\n"
        f"{'=' * 60}"
    )


# Run guard at import time
_guard_branch_access()
