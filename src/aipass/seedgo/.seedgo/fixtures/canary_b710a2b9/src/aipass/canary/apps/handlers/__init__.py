"""CANARY handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.canary"


def _find_real_caller():
    """Walk the stack to find the actual file that triggered this import.

    Skips this file, importlib internals, and frozen modules.
    Returns tuple: (file_path, import_line) or (None, None).

    Walks frames with sys._getframe rather than inspect.stack(): inspect
    builds a FrameInfo per frame, and getmodule() calls os.path.realpath()
    outside any try (inspect.py:1009) — while ntpath.realpath reads
    os.getcwd() UNCONDITIONALLY, unlike posixpath which reads it only for
    relative paths. So on Windows a process whose cwd is unreadable cannot
    import this package at all. Measured here 2026-08-31: denying realpath
    convicted line 15 (inspect.stack) and denying getcwd convicted line 16
    (the raw resolve) — two separate species in one function. A frame's
    co_filename is already a string in memory; reading it touches nothing.
    """
    # Path.resolve() reaches the same ntpath.realpath. __file__ is already
    # absolute, so the resolve only normalises it — the raw spelling is a
    # correct answer when the cwd is gone.
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

        # linecache reads one named file and returns "" rather than raising.
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

    Only code from within the 'canary' branch can import these handlers.
    External branches must use aipass.canary.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    if caller_file is None:
        # No caller outside this file: an interactive session, a -c script, or
        # an importlib-only stack — all allowed. The old second inspect.stack()
        # walk here returned on every path, so it could not change this answer;
        # it was a second copy of the cwd dependency in service of nothing.
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
