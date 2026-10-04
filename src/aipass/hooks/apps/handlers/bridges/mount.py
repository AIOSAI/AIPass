# =================== AIPass ====================
# Name: mount.py
# Version: 1.0.0
# Description: Mounts the promoted copy of aipass.hooks.apps before a bridge imports anything from it
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-09-30
# Modified: 2026-09-30
# =============================================

"""The code a hook runs is the PROMOTED copy, never the tree being edited (DPLAN-0356 item 3).

All three gate crashes (09-12 git_gate, 09-22 edit_gate, 09-30 rm_gate) were
NameErrors from a half-done edit to a live file: the bridges imported the
working tree on every call, so every intermediate state was in production.

``drone @hooks promote`` (modules/promote.py) checks the source, copies
``apps/`` to ``<branch>/.live-<stamp>/`` and only then points
``<branch>/.live-current`` at it. Before a bridge imports anything from
``aipass.hooks.apps``, :func:`mount` registers that copy AS the package, so
every ``aipass.hooks.apps...`` import in the hook process resolves into it.

The copy sits one directory below the branch root, exactly where ``apps/`` sits,
so every module's ``__file__`` arithmetic (logs/, hooks_json/, the branch json
directory) still lands in the real branch. That is why snapshots are siblings of
``apps/`` and not nested deeper.

Loaded BY PATH from the bridges and stdlib-only: importing it through the
package would import the source tree first, which is the thing it prevents.
No pointer (a fresh clone) means the source tree serves, as before promote
existed.
"""

import importlib.util
import os
import sys

POINTER = ".live-current"
PREFIX = ".live-"
#: Names a snapshot for one process: promote's smoke runs the bridge against a
#: candidate before the pointer moves. An agent's shell cannot set a hook
#: process's environment, so this opens nothing.
OVERRIDE_ENV = "AIPASS_HOOKS_LIVE"
PACKAGE = "aipass.hooks.apps"


def branch_root(bridge_file: str) -> str:
    """The hooks branch root, from a bridge's own path: bridges -> handlers -> apps -> branch.

    abspath, never realpath: on Windows realpath reads the working directory.
    """
    path = os.path.abspath(bridge_file)
    for _ in range(4):
        path = os.path.dirname(path)
    return path


def promoted_dir(root: str) -> str | None:
    """The snapshot directory to serve, or None when nothing was ever promoted.

    Raises:
        ValueError: the pointer names something that is not a snapshot.
        FileNotFoundError: the snapshot it names is gone.
    """
    name = os.environ.get(OVERRIDE_ENV, "").strip()
    if not name:
        pointer = os.path.join(root, POINTER)
        if not os.path.isfile(pointer):
            return None
        with open(pointer, encoding="utf-8") as handle:
            name = handle.read().strip()
    if not name.startswith(PREFIX) or "/" in name or "\\" in name or name in (".", ".."):
        raise ValueError(f"{POINTER} names {name!r}, not a {PREFIX}<stamp> directory")
    path = os.path.join(root, name)
    if not os.path.isfile(os.path.join(path, "__init__.py")):
        raise FileNotFoundError(f"promoted copy {path} is missing")
    return path


def _forget() -> None:
    """Drop a half-mounted package, so a source fallback imports clean."""
    for key in [k for k in sys.modules if k == PACKAGE or k.startswith(PACKAGE + ".")]:
        sys.modules.pop(key, None)


def mount(root: str) -> str:
    """Serve ``aipass.hooks.apps`` from the promoted copy; return what serves.

    Returns:
        The snapshot's directory name, or "source" when nothing was promoted.

    Raises:
        Whatever the pointer or the copy raises. The package is left unmounted,
        so the caller can fall back to the source tree.
    """
    snapshot = promoted_dir(root)
    if snapshot is None:
        return "source"
    if PACKAGE in sys.modules:
        raise RuntimeError(f"{PACKAGE} was imported before the mount")
    import aipass.hooks  # the package marker: a docstring, no code

    spec = importlib.util.spec_from_file_location(
        PACKAGE, os.path.join(snapshot, "__init__.py"), submodule_search_locations=[snapshot]
    )
    if spec is None or spec.loader is None:
        raise ImportError(f"no import spec for {snapshot}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    try:
        spec.loader.exec_module(module)
    except BaseException:
        _forget()
        raise
    aipass.hooks.apps = module  # type: ignore[attr-defined]
    return os.path.basename(snapshot)
