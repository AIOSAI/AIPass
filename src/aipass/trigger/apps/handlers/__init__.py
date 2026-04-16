"""TRIGGER handlers package - Security protected."""

import inspect
from pathlib import Path

MY_BRANCH = "trigger"


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
        if part in ("aipass", "seedgo", ".vscode"):
            if i + 1 < len(parts):
                return parts[i + 1]
        if part in ("aipass",) and i + 1 < len(parts) and parts[i + 1] == "apps":
            return "aipass"
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
                return  # Allow command-line Python through
        return

    if "/trigger/" in caller_file.replace("\\", "/"):
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
        f"  Blocked:       {blocked_import}\n\n"
        f"  Handlers are internal to their branch.\n"
        f"  Use the module API instead:\n"
        f"    from aipass.trigger.apps.modules.<module> import <function>\n"
        f"{'=' * 60}"
    )


_guard_branch_access()
