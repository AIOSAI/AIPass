# ===================AIPASS====================
# META DATA HEADER
# Name: __init__.py - The Commons handlers package
# Date: 2026-03-07
# Version: 2.0.0
# Category: commons/apps/handlers
# =============================================

"""Commons handlers package - Security protected."""

import inspect
from pathlib import Path

MY_BRANCH = "commons"  # Commons is standalone, not under aipass.*


def _find_real_caller():
    """Walk the stack to find the actual file that triggered this import."""
    stack = inspect.stack()
    this_file = str(Path(__file__).resolve())

    for frame_info in stack:
        filename = frame_info.filename
        if this_file in str(Path(filename).resolve()):
            continue
        if filename.startswith("<") or "importlib" in filename:
            continue
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
    # Check for commons specifically
    for i, part in enumerate(parts):
        if part == "commons":
            return "commons"
    return "unknown"


def _guard_branch_access():
    """Block cross-branch handler imports."""
    caller_file, import_line = _find_real_caller()

    import os

    if os.environ.get("AIPASS_DEBUG_GUARD"):
        import sys

        print(f"[GUARD DEBUG] caller_file = {caller_file}", file=sys.stderr)
        print(f"[GUARD DEBUG] import_line = {import_line}", file=sys.stderr)

    if caller_file is None:
        stack = inspect.stack()
        for frame in stack:
            if frame.filename in ("<string>", "<stdin>"):
                target_line = "unknown"
                if frame.code_context:
                    target_line = frame.code_context[0].strip()
                raise ImportError(
                    f"\n{'='*60}\n"
                    f"ACCESS DENIED: Cross-branch handler import blocked\n"
                    f"{'='*60}\n"
                    f"  Caller:  interactive/script\n"
                    f"  Blocked: {target_line}\n"
                    f"\n"
                    f"  Handlers are internal to their branch.\n"
                    f"  Use the module API instead:\n"
                    f"    from {MY_BRANCH}.apps.modules.<module> import <function>\n"
                    f"{'='*60}"
                )
        return

    # IMPORTANT: Commons is at src/commons/, not src/aipass/commons/
    # Check if caller is from within the commons directory
    if "/commons/" in caller_file:
        return  # Same branch, allowed

    caller_branch = _extract_branch_name(caller_file)
    caller_filename = Path(caller_file).name
    blocked_import = import_line if import_line else "unknown"

    raise ImportError(
        f"\n{'='*60}\n"
        f"ACCESS DENIED: Cross-branch handler import blocked\n"
        f"{'='*60}\n"
        f"  Caller branch: {caller_branch}\n"
        f"  Caller file:   {caller_filename}\n"
        f"  Blocked:       {blocked_import}\n"
        f"\n"
        f"  Handlers are internal to their branch.\n"
        f"  Use the module API instead:\n"
        f"    from {MY_BRANCH}.apps.modules.<module> import <function>\n"
        f"{'='*60}"
    )


# Run guard at import time
_guard_branch_access()
