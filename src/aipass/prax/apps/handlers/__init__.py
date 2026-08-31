"""Prax handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.prax"


def _find_real_caller():
    """
    Walk the stack to find the actual file that triggered this import.

    Skips:
    - This file (handlers/__init__.py)
    - Python's importlib internals
    - Frozen modules

    Returns tuple: (file_path, import_line) or (None, None)

    Walks frames with sys._getframe rather than inspect.stack(). MEASURED on the
    Windows CI gate 2026-08-31 by @spawn, reproduced here: inspect.stack() needs
    a READABLE WORKING DIRECTORY, and it needs one before any of this function's
    own code runs. It builds a FrameInfo per frame, which reaches getsourcefile()
    -> getmodule() -> os.path.realpath(); ntpath.realpath calls os.getcwd()
    unconditionally on its first lines, before it even checks whether the path is
    absolute, and that call site inside getmodule is not in a try. On POSIX the
    equivalent raise happens earlier, inside getabsfile(), where inspect catches
    it — so every Linux pin here was green for a reason unrelated to correctness.

    A frame's co_filename is already a string in memory. Reading it touches
    nothing, so the walk itself cannot need a working directory.
    """
    # Path.resolve() reaches the same ntpath.realpath, so this is guarded too.
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
        # deleted (drone's dead-cwd routing case) dies here otherwise.
        if filename.startswith("<") or "importlib" in filename:
            frame = frame.f_back
            continue

        # resolve() on a relative frame filename also needs a cwd; fall back to
        # the raw spelling rather than crashing the import of every prax consumer.
        try:
            resolved = str(Path(filename).resolve())
        except OSError:
            resolved = filename

        # Skip this file
        if this_file in resolved or __file__ in filename:
            frame = frame.f_back
            continue

        # linecache is what inspect used for code_context. Called directly it
        # reads one named file and returns "" rather than raising.
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
    """
    Block cross-branch handler imports.

    Only code from within the 'prax' branch can import these handlers.
    External branches must use aipass.prax.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    # DEBUG: Print what we found
    import os

    if os.environ.get("AIPASS_DEBUG_GUARD"):
        import sys

        print(f"[GUARD DEBUG] caller_file = {caller_file}", file=sys.stderr)
        print(f"[GUARD DEBUG] import_line = {import_line}", file=sys.stderr)

    if caller_file is None:
        # An undeterminable caller is ALLOWED — a command line, an embedded
        # interpreter, a frozen loader. The guard convicts on evidence; not
        # having any is not evidence.
        #
        # A second inspect.stack() used to sit here, scanning for <string> or
        # <stdin> — and it was DEAD: both the match and the fall-through
        # returned None with no side effect, so the whole call could not change
        # the answer. It is deleted rather than guarded, because a call that
        # needs a working directory to compute a value nobody reads is pure
        # exposure. @devpulse's rule from the fleet sweep, and it applied here.
        return

    # Check if caller is from our branch
    # MY_BRANCH is "aipass.prax" (dotted), but filesystem uses "/aipass/prax/"
    branch_path = "/" + MY_BRANCH.replace(".", "/") + "/"
    if branch_path in caller_file.replace("\\", "/"):
        return  # Same branch, allowed

    # External caller - block access
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
        f"  Example:\n"
        f"    from {MY_BRANCH}.apps.modules.logger import logger\n"
        f"\n"
        f"  For full standards guide:\n"
        f"    drone @seedgo handlers\n"
        f"{'=' * 60}"
    )


# Run guard at import time
_guard_branch_access()
