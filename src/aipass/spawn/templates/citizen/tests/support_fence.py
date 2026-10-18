# =================== AIPass ====================
# Name: support_fence.py
# Description: Fence probe for test_handlers_fence.py, run from a kin seat and from foreign copies
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-17
# =============================================

"""Probe for the handlers fence of apps/handlers/__init__.py (no test_ prefix: never collected).

One source, run from a kin seat (this file) and from foreign copies the test writes under tmp."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import aipass

BRANCH = "{{BRANCH}}"
HANDLERS = f"aipass.{BRANCH}.apps.handlers"
A_HANDLER = f"{HANDLERS}.json.json_handler"
A_DOOR = f"aipass.{BRANCH}.apps.modules"  # the scaffold ships no modules file; name one once it exists
KIN_PROBE = f"aipass.{BRANCH}.tests.support_fence"


def import_named(name: str):
    """Import on a caller's behalf - a kin frame between the caller and the fence."""
    return importlib.import_module(name)


def _pkg() -> None:
    """The handlers package by its name."""
    importlib.import_module(HANDLERS)


def _deep() -> None:
    """One handler module by its name."""
    importlib.import_module(A_HANDLER)


def _dyn() -> None:
    """One handler module through a variable."""
    name = A_HANDLER
    importlib.import_module(name)


def _chain() -> None:
    """A package __init__ chain: names the handlers, reaches the fence via a kin frame; refused on spelling."""
    kin = importlib.import_module(KIN_PROBE)
    kin.import_named("aipass.{{BRANCH}}.apps.handlers.json.json_handler")


def _sibling() -> None:
    """A frame under the fleet root beside this branch, compiled under that filename; no file is written.

    In a wheel that is site-packages, which the fence must still read as foreign, not third-party."""
    seat = str(Path(aipass.__file__).resolve().parent / "sibling" / "probe.py")
    exec(compile(f"importlib.import_module({HANDLERS!r})", seat, "exec"), {"importlib": importlib})


def _door() -> None:
    """This branch's modules door, which imports the handlers on the caller's behalf."""
    importlib.import_module(A_DOOR)


def _mock() -> None:
    """mock.patch on a handler path: the import starts in unittest/mock.py and pkgutil."""
    with patch(f"{A_HANDLER}.log_operation"):
        pass


SHAPES = {
    "pkg": _pkg,
    "deep": _deep,
    "dyn": _dyn,
    "chain": _chain,
    "sibling": _sibling,
    "door": _door,
    "mock": _mock,
}


def _run(shape: str) -> str:
    """Perform one import shape; answer ALLOWED, DENIED <caller line> or REFUSED <error>."""
    act = SHAPES.get(shape)
    if act is None:
        return f"UNKNOWN {shape}"
    try:
        act()
    except ImportError as exc:
        caller = [ln.strip() for ln in str(exc).splitlines() if "Caller branch" in ln]
        return "DENIED " + (caller[0] if caller else str(exc)[:80])
    except AttributeError as exc:
        return "REFUSED " + str(exc)[:80]
    return "ALLOWED"


if __name__ == "__main__":
    print(_run(sys.argv[1]))
