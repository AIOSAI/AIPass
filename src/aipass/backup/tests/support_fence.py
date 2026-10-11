# =================== AIPass ====================
# Name: support_fence.py
# Description: Fence probe for test_handlers_fence.py, run from a kin seat and from foreign copies
# Version: 1.0.0
# Created: 2026-10-08
# Modified: 2026-10-08
# =============================================

"""Probe for the handlers fence of apps/handlers/__init__.py (no test_ prefix: never collected).

One source, run from a kin seat (this file) and from foreign seats (copies the
test writes under tmp). Each import shape is one small function; the table
SHAPES maps the shape name on argv to it (aipass, DPLAN-0404 leg 8: the
template's single if/elif ran nine deep against the nesting row).
"""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(ruff) — that the module parses and imports

import importlib
import sys
from pathlib import Path
from unittest.mock import patch

import aipass

BRANCH = "backup"
HANDLERS = f"aipass.{BRANCH}.apps.handlers"
A_HANDLER = f"{HANDLERS}.audit.trail"
A_DOOR = "aipass.backup.apps.modules.door_trail"
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
    """The line below names the handlers and reaches the fence through a kin frame
    (import_named): the shape of an import that comes in through a package
    __init__ chain. Refused on the line's spelling alone."""
    kin = importlib.import_module(KIN_PROBE)
    kin.import_named("aipass.backup.apps.handlers.audit.trail")


def _sibling() -> None:
    """A frame whose file sits under the fleet root beside this branch, as a sibling
    branch's would - in an installed wheel that is under site-packages, which the
    fence must still read as foreign, not as a third-party library. Compiled under
    that filename; no file is written."""
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
