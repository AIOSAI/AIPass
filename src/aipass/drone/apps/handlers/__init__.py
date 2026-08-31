"""Drone handlers package - Security protected."""

import inspect
from pathlib import Path

MY_BRANCH = "aipass.drone"


def _find_real_caller():
    """
    Walk the stack to find the actual file that triggered this import.

    Skips:
    - This file (handlers/__init__.py)
    - Python's importlib internals
    - Frozen modules

    Returns tuple: (file_path, import_line) or (None, None)
    """
    stack = inspect.stack()
    this_file = str(Path(__file__).resolve())

    for frame_info in stack:
        filename = frame_info.filename

        # Skip Python internals FIRST. These names are not paths — every import
        # stack carries <frozen importlib._bootstrap> — and resolving one goes
        # through abspath, which READS THE CURRENT DIRECTORY. A process whose
        # cwd was deleted (an ordinary state since `drone rm` learned to delete
        # the directory you stand in) then raised ENOENT here, at import of the
        # handlers package, before any command could run.
        if filename.startswith("<") or "importlib" in filename:
            continue

        try:
            resolved = str(Path(filename).resolve())
        except OSError:
            # A relative frame filename with no cwd to resolve it against. The
            # guard cannot attribute this frame, so it moves on rather than
            # taking the whole process down with it.
            continue

        # Skip this file
        if this_file in resolved:
            continue

        # Found a real file - try to get the import line
        import_line = None
        if frame_info.code_context:
            import_line = frame_info.code_context[0].strip()

        return resolved, import_line

    return None, None


_BRANCH_ROOT = str(Path(__file__).resolve().parents[2])


def _extract_branch_name(filepath: str) -> str:
    """Extract branch name from a file path by walking up to .trinity/."""
    path = Path(filepath)
    for parent in [path, *path.parents]:
        if (parent / ".trinity").is_dir():
            return parent.name
    return "unknown"


def _guard_branch_access():
    """
    Block cross-branch handler imports.

    Only code from within the 'drone' branch can import these handlers.
    External branches must use aipass.drone.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    import os

    if os.environ.get("AIPASS_DEBUG_GUARD"):
        import sys

        sys.stderr.write(f"[GUARD DEBUG] caller_file = {caller_file}\n")
        sys.stderr.write(f"[GUARD DEBUG] import_line = {import_line}\n")

    if caller_file is None:
        # Can't determine caller from real files
        # Check if we're being run from command line (external)
        # by looking at the raw stack for <string> or <stdin>
        stack = inspect.stack()
        for frame in stack:
            if frame.filename in ("<string>", "<stdin>"):
                return  # Allow command-line Python through
        return  # Allow if truly can't determine

    if Path(caller_file).is_relative_to(_BRANCH_ROOT):
        return  # Same branch, allowed

    # External caller - block access
    caller_branch = _extract_branch_name(caller_file)
    caller_filename = Path(caller_file).name
    blocked_import = import_line if import_line else "unknown"

    module_api = f"{MY_BRANCH}.apps.modules"
    raise ImportError(
        f"\n{'=' * 60}\n"
        f"ACCESS DENIED: Cross-branch handler import blocked\n"
        f"{'=' * 60}\n"
        f"  Caller branch: {caller_branch}\n"
        f"  Caller file:   {caller_filename}\n"
        f"  Blocked:       {blocked_import}\n"
        f"\n"
        f"  Handlers are internal to their branch.\n"
        f"  Use the module API instead: {module_api}.<module>\n"
        f"\n"
        f"  For full standards guide:\n"
        f"    drone @seedgo handlers\n"
        f"{'=' * 60}"
    )


# Run guard at import time
_guard_branch_access()
