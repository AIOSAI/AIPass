# =================== AIPass ====================
# Name: mount.py
# Version: 1.1.0
# Description: Mounts the promoted copy of aipass.hooks.apps before a bridge imports anything from it
# Branch: hooks
# Layer: apps/handlers/bridges
# Created: 2026-09-30
# Modified: 2026-10-28
# =============================================

"""The code a hook runs is the PROMOTED copy, never the tree being edited (DPLAN-0356 item 3).

Loaded BY PATH and stdlib-only: importing it through the package imports the source tree first.
Snapshots sit beside apps/ so every module's __file__ arithmetic still lands in the real branch.
"""

import importlib.util
import os
import sys

POINTER = ".live-current"
PREFIX = ".live-"
#: Names a snapshot for one process (promote's smoke); an agent's shell cannot set a hook's env.
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
    """The snapshot directory to serve, or None when nothing was ever promoted."""
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
    """Serve ``aipass.hooks.apps`` from the promoted copy; return what serves."""
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


def mount_or_source(bridge_file: str, tag: str) -> str:
    """A bridge's mount: a bad promoted copy serves the source tree and says so at ERROR, through prax or stderr."""
    try:
        return mount(branch_root(bridge_file))
    except Exception as exc:  # a bad promoted copy: the source still gates, and says so
        message = f"[HOOKS:{tag}] promoted copy unusable, serving the source tree: {exc}"
        try:
            from aipass.prax.apps.modules.logger import system_logger as logger

            logger.error(message)
        except Exception as err:
            sys.stderr.write(f"{message} (prax unavailable: {err})\n")
        return "source (fallback)"
