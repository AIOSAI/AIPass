"""Devpulse handlers package - Security protected."""

import inspect
from pathlib import Path

MY_BRANCH = "aipass.devpulse"


def _find_real_caller():
    stack = inspect.stack()
    this_file = str(Path(__file__).resolve())

    for frame_info in stack:
        filename = frame_info.filename
        # Internals first — resolve() on a pseudo-filename like <string> needs a
        # cwd, and a process whose cwd was deleted dies here otherwise.
        if filename.startswith("<") or "importlib" in filename:
            continue
        # resolve() on a relative frame filename also needs a cwd; fall back to
        # the raw spelling rather than crashing every consumer's import.
        try:
            resolved = str(Path(filename).resolve())
        except OSError:
            resolved = filename
        if this_file in resolved:
            continue
        import_line = None
        if frame_info.code_context:
            import_line = frame_info.code_context[0].strip()
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
        stack = inspect.stack()
        for frame in stack:
            if frame.filename in ("<string>", "<stdin>"):
                return
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
