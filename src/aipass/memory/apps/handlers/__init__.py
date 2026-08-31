"""Memory handlers package - Security protected."""

import linecache
import sys
from pathlib import Path

MY_BRANCH = "aipass.memory"


def _find_real_caller():
    """
    Walk the stack to find the actual file that triggered this import.

    Skips:
    - This file (handlers/__init__.py)
    - Python's importlib internals
    - Frozen modules

    NOT ``inspect.stack()``, and that is the whole point of this function's
    shape.  ``inspect.stack()`` builds a FrameInfo for every frame, and building
    one resolves the frame's source file: ``getsourcefile`` -> ``getmodule`` ->
    ``os.path.realpath``.  On Windows ``ntpath.realpath`` reads the working
    directory, so in a process whose cwd is gone this raised
    ``FileNotFoundError`` INSIDE ``inspect.stack()`` — before any of the
    skip-the-pseudo-file care below could run.  Found on the Windows CI leg
    2026-08-31; the whole traceback sat above line 20, in the stdlib.

    Reading ``frame.f_code.co_filename`` off a raw frame walk asks the
    filesystem nothing.  It is also markedly cheaper at import time, which this
    runs at, and it makes the existing guards reachable rather than decorative.

    Returns tuple: (file_path, import_line) or (None, None)
    """
    # NOT resolve(). Windows' ntpath.realpath reads the working directory
    # UNCONDITIONALLY — even for an absolute path — so this line was the next
    # import-time crash behind inspect.stack() in a dead cwd, and fixing only
    # the first one would have moved the traceback down two lines. __file__ has
    # been absolute since 3.9, so there is nothing here for resolve() to do
    # that is worth a filesystem call at import time.
    this_file = str(Path(__file__))

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

        # Skip this file
        if this_file in resolved:
            frame = frame.f_back
            continue

        # Found a real file - try to get the import line. Only for the ONE
        # frame being returned, and defensively: reading a source line touches
        # the filesystem, and a diagnostic string is never worth the import it
        # would take down.
        import_line = None
        try:
            import_line = linecache.getline(resolved, frame.f_lineno).strip() or None
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

    Only code from within the 'memory' branch can import these handlers.
    External branches must use aipass.memory.apps.modules instead.
    """
    caller_file, import_line = _find_real_caller()

    # DEBUG: Print what we found
    import os

    if os.environ.get("AIPASS_DEBUG_GUARD"):
        # sys is imported at module level now (the frame walk needs it), and a
        # local import here would shadow it into "possibly unbound" for the
        # walk below.
        print(f"[GUARD DEBUG] caller_file = {caller_file}", file=sys.stderr)
        print(f"[GUARD DEBUG] import_line = {import_line}", file=sys.stderr)

    if caller_file is None:
        # Can't determine caller from real files
        # Check if we're being run from command line (external)
        # by looking at the raw stack for <string> or <stdin>.
        # A raw frame walk for the same reason _find_real_caller uses one:
        # inspect.stack() resolves every frame's source file and reads the
        # working directory doing it, which crashes this import on Windows in
        # the very dead-cwd world this guard has to survive. Both outcomes here
        # are `return`, so a crash would be the only thing this branch could
        # ever contribute — it is pure diagnosis, and it must not be load-bearing.
        frame = sys._getframe(1)
        while frame is not None:
            if frame.f_code.co_filename in ("<string>", "<stdin>"):
                return  # Allow command-line Python through
            frame = frame.f_back
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

# Python 3.10 mock.patch compatibility — subpackages must be importable as
# attributes for mock._dot_lookup to resolve dotted paths.
from . import monitor  # noqa: F401, E402

# PARKED 2026-08-14 (Patrick's ruling) — the symbolic fragments tier is unused and
# the Agent Memory Atlas review flagged its AUDN deduplicator for acting on an LLM
# Delete verdict with no record of what was removed. This line is why the tier was
# imported on EVERY live call: any `handlers.json` import runs this package first.
# The curated-truth piece that IS active is Compass — @devpulse, src/aipass/devpulse,
# SQLite/FTS5, `drone @devpulse compass`. Revival: uncomment, and follow
# tests/parked/symbolic_20260814/README.md.
# from . import symbolic  # noqa: F401, E402
from . import rollover  # noqa: F401, E402
from . import schema  # noqa: F401, E402
