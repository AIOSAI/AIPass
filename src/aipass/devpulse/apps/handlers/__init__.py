"""Devpulse handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.devpulse"


def _find_real_caller():
    """Walk the stack for the file that triggered this import.

    Walks frames with sys._getframe rather than inspect.stack(): inspect
    builds a FrameInfo per frame, whose getmodule() calls os.path.realpath()
    outside any try — and ntpath.realpath calls os.getcwd() unconditionally,
    so on Windows the guard would need a readable cwd at import (measured on
    the Windows CI gate 2026-08-31; on POSIX the same raise is swallowed
    earlier, inside getabsfile). A frame's co_filename is already a string
    in memory; reading it touches nothing.
    """
    # Path.resolve() reaches the same ntpath.realpath — __file__ is already
    # absolute; the resolve only normalises it.
    try:
        this_file = str(Path(__file__).resolve())
    except OSError:
        this_file = __file__

    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename
        # Internals first — resolve() on a pseudo-filename like <string> needs a
        # cwd, and a process whose cwd was deleted dies here otherwise.
        if filename.startswith("<") or "importlib" in filename:
            frame = frame.f_back
            continue
        # resolve() on a relative frame filename also needs a cwd; fall back to
        # the raw spelling rather than crashing every consumer's import.
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
    parts = Path(filepath).parts
    for i, part in enumerate(parts):
        if part == "aipass":
            if i + 1 < len(parts):
                return parts[i + 1]
    return "unknown"


def _guard_branch_access():
    caller_file, import_line = _find_real_caller()

    if caller_file is None:
        # No caller outside this file: an interactive session, a -c script, or
        # an importlib-only stack — all allowed. The old second inspect.stack()
        # walk here returned either way; a second copy of the cwd dependency in
        # service of a branch that could not change the answer.
        return

    if "pytest" in caller_file or "/_pytest/" in caller_file:
        return

    branch_path = "/" + MY_BRANCH.replace(".", "/") + "/"
    if branch_path in caller_file.replace("\\", "/"):
        return

    caller_branch = _extract_branch_name(caller_file)
    caller_filename = Path(caller_file).name
    blocked_import = import_line if import_line else "unknown"

    module_api = MY_BRANCH + ".apps" + ".modules"
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
        f"    from {module_api}.<module> import <function>\n"
        f"{'=' * 60}"
    )


_guard_branch_access()
