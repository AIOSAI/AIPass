"""Drone handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.drone"


def _safe_resolve(path: Path) -> Path:
    """``resolve()`` where the raw spelling is an acceptable answer.

    ``Path.resolve()`` routes through ``os.path.realpath``, and ``ntpath``'s
    copy of that reads ``os.getcwd()`` on its first lines — unconditionally,
    before it even asks whether the path is absolute. A Windows process whose
    working directory is gone therefore dies inside a call that only meant to
    normalise an already-absolute path. Module ``__file__`` and frame
    ``co_filename`` are absolute in every layout drone ships in, so dropping
    the normalisation costs symlink-flattening and nothing else.
    """
    try:
        return path.resolve()
    except OSError:
        return path


def _find_real_caller():
    """
    Walk the stack to find the actual file that triggered this import.

    Skips:
    - This file (handlers/__init__.py)
    - Python's importlib internals
    - Frozen modules

    Returns tuple: (file_path, import_line) or (None, None)

    Walks frames with ``sys._getframe`` rather than ``inspect.stack()``.
    MEASURED on the Windows CI gate 2026-08-31: ``inspect.stack()`` needs a
    readable working directory, and it needs one before any of this function's
    own code runs. It builds a ``FrameInfo`` per frame, which reaches
    ``getmodule()``, whose ``os.path.realpath(f)`` sits outside every ``try``
    in that function. On POSIX the equivalent raise happens earlier, inside
    ``getabsfile()``, where ``inspect`` catches it — which is why a guard that
    ran on every drone import survived years of Linux CI carrying this. A
    frame's ``co_filename`` is already a string in memory; reading it touches
    no filesystem at all.
    """
    this_file = str(_safe_resolve(Path(__file__)))

    frame = sys._getframe(1)
    while frame is not None:
        filename = frame.f_code.co_filename

        # Skip Python internals FIRST. These names are not paths — every import
        # stack carries <frozen importlib._bootstrap> — and resolving one goes
        # through realpath, which READS THE CURRENT DIRECTORY. A process whose
        # cwd was deleted (an ordinary state since `drone rm` learned to delete
        # the directory you stand in) then raised ENOENT here, at import of the
        # handlers package, before any command could run.
        if filename.startswith("<") or "importlib" in filename:
            frame = frame.f_back
            continue

        # A relative frame filename has no cwd to resolve against. Fall back to
        # the raw spelling rather than taking the whole import down.
        resolved = str(_safe_resolve(Path(filename)))

        # Skip this file
        if this_file in resolved or __file__ in filename:
            frame = frame.f_back
            continue

        # Found a real file - try to get the import line. linecache is what
        # inspect used to build code_context; called directly it reads one
        # named file and returns "" rather than raising when it cannot.
        try:
            import_line = linecache.getline(filename, frame.f_lineno).strip() or None
        except OSError:
            import_line = None

        return resolved, import_line

    return None, None


# The branch this package belongs to, named by its own location. Both spellings
# are kept: a resolve that FAILED must not be able to make a same-branch caller
# look foreign, and the unresolved form is the same directory with symlinks left
# standing — it can only ever admit drone's own tree under a second name.
_BRANCH_ROOT_RAW = str(Path(__file__).parents[2])
_BRANCH_ROOT = str(_safe_resolve(Path(__file__)).parents[2])


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
        sys.stderr.write(f"[GUARD DEBUG] caller_file = {caller_file}\n")
        sys.stderr.write(f"[GUARD DEBUG] import_line = {import_line}\n")

    if caller_file is None:
        # No caller outside this file: an interactive session, a -c script, or
        # an importlib-only stack. All three are allowed. This used to walk
        # inspect.stack() a SECOND time looking for <string>/<stdin> and then
        # return either way — a second copy of the cwd dependency above, in
        # service of a branch that could not change the answer.
        return

    caller = Path(caller_file)
    if caller.is_relative_to(_BRANCH_ROOT) or caller.is_relative_to(_BRANCH_ROOT_RAW):
        return  # Same branch, allowed

    # External caller - block access
    caller_branch = _extract_branch_name(caller_file)
    caller_filename = caller.name
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
