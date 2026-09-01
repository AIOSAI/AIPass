"""Spawn handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.spawn"


def _find_real_caller():
    """Walk the stack to find the actual file that triggered this import.

    Skips this file, importlib internals, and frozen modules.
    Returns tuple: (file_path, import_line) or (None, None).

    Walks frames with sys._getframe rather than inspect.stack(). MEASURED on the
    Windows CI gate 2026-08-31: inspect.stack() needs a READABLE CWD, and it
    needs one before any of this function's own code runs. It builds a FrameInfo
    per frame, which calls getsourcefile() -> getmodule() -> os.path.realpath();
    ntpath.realpath calls os.getcwd() unconditionally on its first lines, before
    it even checks whether the path is absolute, and that call site in getmodule
    is not inside a try. On POSIX the equivalent raise happens earlier, inside
    getabsfile(), where inspect catches it — which is why this was invisible on
    Linux for as long as it existed. A frame's co_filename is already a string
    in memory; reading it touches nothing.
    """
    # Path.resolve() reaches the same ntpath.realpath, so this is guarded too —
    # __file__ is already absolute; the resolve only normalises it.
    try:
        this_file = str(Path(__file__).resolve())
    except OSError:
        this_file = __file__

    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename

        # Skip Python internals BEFORE touching the filesystem — resolve() on a
        # pseudo-filename like <string> needs a cwd, and a process whose cwd was
        # deleted dies here otherwise.
        if filename.startswith("<") or "importlib" in filename:
            frame = frame.f_back
            continue

        # resolve() on a relative frame filename also needs a cwd; fall back to
        # the raw spelling rather than crashing the import.
        try:
            resolved = str(Path(filename).resolve())
        except OSError:
            resolved = filename

        if this_file in resolved or __file__ in filename:
            frame = frame.f_back
            continue

        # linecache is what inspect used for code_context; called directly it
        # reads one named file and returns "" rather than raising when it cannot.
        import_line = None
        try:
            import_line = linecache.getline(filename, frame.f_lineno).strip() or None
        except OSError:
            import_line = None

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

    Only code from within the 'spawn' branch can import these handlers.
    External branches must use aipass.spawn.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    if caller_file is None:
        # No caller outside this file: an interactive session, a -c script, or an
        # importlib-only stack. All three are allowed. This used to walk
        # inspect.stack() again looking for <string>/<stdin> and then return
        # either way — a second copy of the cwd dependency above, in service of a
        # branch that could not change the answer.
        return

    branch_path = "/" + MY_BRANCH.replace(".", "/") + "/"
    if branch_path in caller_file.replace("\\", "/"):
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
        f"  Use the module API instead:\n"
        f"    from {MY_BRANCH}.apps.modules.<module> import <function>\n"
        f"\n"
        f"  For full standards guide:\n"
        f"    drone @seedgo handlers\n"
        f"{'=' * 60}"
    )


# Run guard at import time
_guard_branch_access()
