"""Memory handlers package - Security protected."""

import inspect
from pathlib import Path

MY_BRANCH = "aipass.memory"


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

        # Skip this file
        if this_file in str(Path(filename).resolve()):
            continue

        # Skip Python internals
        if filename.startswith("<") or "importlib" in filename:
            continue

        # Found a real file - try to get the import line
        import_line = None
        if frame_info.code_context:
            import_line = frame_info.code_context[0].strip()

        return str(Path(filename).resolve()), import_line

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

    Only code from within the 'memory' branch can import these handlers.
    External branches must use aipass.memory.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    # DEBUG: Print what we found
    import os

    if os.environ.get("AIPASS_DEBUG_GUARD"):
        import sys

        print(f"[GUARD DEBUG] caller_file = {caller_file}", file=sys.stderr)
        print(f"[GUARD DEBUG] import_line = {import_line}", file=sys.stderr)

    if caller_file is None:
        # Can't determine caller from real files
        # Check if we're being run from command line (external)
        # by looking at the raw stack for <string> or <stdin>
        stack = inspect.stack()
        for frame in stack:
            if frame.filename in ("<string>", "<stdin>"):
                return  # Allow command-line Python through
        return  # Allow if truly can't determine

    # Check if caller is from our branch
    # MY_BRANCH is "aipass.memory" (dotted), but filesystem uses "/aipass/memory/"
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
