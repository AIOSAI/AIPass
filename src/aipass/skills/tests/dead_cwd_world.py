# =================== AIPass ====================
# Name: dead_cwd_world.py
# Description: The one definition of the hostile worlds this branch's pins use
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The dead-cwd worlds, defined once.

WHY THIS FILE EXISTS. Round 4 shipped four probes in this branch, each
spelling its own denial. Round 6's Python 3.10 CI leg reddened two of them and
the cause was in the SPELLING, not in the cure they were guarding:

    test_skill_discovery_survives_a_dead_cwd     the project path was still offered
    test_skill_creation_refuses_rather_than_guessing   the refusal never happened

Production was fine. The WORLD did not arm, so the code under test behaved
normally and the pins asserted a refusal that had no cause to occur.

THE MECHANISM. Before 3.11, ``pathlib`` routed through ``_NormalAccessor``,
whose attributes CAPTURE their targets at class-definition time - i.e. when
``pathlib`` was first imported::

    3.10 Lib/pathlib.py:358   realpath = staticmethod(os.path.realpath)
    3.10 Lib/pathlib.py:1077  s = self._accessor.realpath(self, strict=strict)
    3.10                      Path.cwd() -> cls(cls._accessor.getcwd())
    3.11+                     the accessor is gone; os.getcwd is called at use

So a child that imports pathlib and THEN rebinds ``os.getcwd`` rebinds a name
nothing reads again. Patching the accessor as well makes the world
ORDER-INDEPENDENT: a probe may import pathlib before or after the denial and
gets the same hostile world either way.

WHY ``*a, **k`` AND ``staticmethod`` BOTH. A plain function stored on a class
arrives BOUND through an instance, so ``cls._accessor.getcwd()`` passes the
accessor as ``self``. A zero-argument replacement then raises TypeError rather
than FileNotFoundError - a raise-shaped pin stays green for the wrong reason.
Measured on 3.12: either half alone cures it, so they are redundant BY
DESIGN. Recorded because whichever half a future reader deletes as obviously
covered is the one that was covering the other.

NO 3.10 ON THIS MACHINE. Rather than record a derived row, ``ACCESSOR_SHAPE``
below rebuilds the capture on whatever interpreter is running, so the
discrimination CI found is falsifiable here forever
(see ``TestTheAccessorTrapIsReproducibleLocally``).

DO NOT STACK THE GETCWD AND REALPATH DENIALS. They MASK each other and the
combination is LESS hostile than the realpath denial alone: ``getabsfile`` is
called inside inspect's own ``except (TypeError, FileNotFoundError)``, so
denying getcwd makes ``abspath`` raise THERE, inspect swallows it and returns
None before the unprotected ``realpath`` in ``getmodule`` is ever reached.
Measured by @memory and independently by @prax. WORLD_A below is not an
exception to this: it denies getcwd while making realpath READ the cwd, which
is the Windows shape - it convicts ``Path.resolve()``, and it is exactly why
WORLD_B exists separately to convict ``inspect.stack()``.
"""

__all__ = [
    "ACCESSOR_SHAPE",
    "WORLD_A",
    "WORLD_B",
    "WORLD_GETCWD_DENIED",
]

# The denial itself. Takes any arguments so it answers correctly whether it is
# called bare (3.11+) or accessor-bound (3.10).
_DENIAL = (
    "import os\n"
    "import pathlib as _pl\n"
    "def _dead(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory (dead cwd)')\n"
)

# World: os.getcwd() raises. Convicts Path.cwd() and any relative resolve.
WORLD_GETCWD_DENIED = _DENIAL + (
    "os.getcwd = _dead\nif hasattr(_pl, '_NormalAccessor'):\n    _pl._NormalAccessor.getcwd = staticmethod(_dead)\n"
)

# World A: take the WINDOWS reading of realpath - ntpath reads the cwd on its
# first lines unconditionally, where posixpath reads it only for a relative
# path - then deny the cwd. Convicts a raw Path.resolve() reached at import.
WORLD_A = WORLD_GETCWD_DENIED + (
    "_real_realpath = os.path.realpath\n"
    "def _reads_the_cwd(p, *a, **k):\n"
    "    os.getcwd()\n"
    "    return _real_realpath(p, *a, **k)\n"
    "os.path.realpath = _reads_the_cwd\n"
    "if hasattr(_pl, '_NormalAccessor'):\n"
    "    _pl._NormalAccessor.realpath = staticmethod(_reads_the_cwd)\n"
)

# World B: deny realpath outright and leave abspath working. Convicts
# inspect.stack() through getmodule's unguarded os.path.realpath at
# inspect.py:1009. Never combined with the getcwd denial - see the docstring.
WORLD_B = _DENIAL + (
    "os.path.realpath = _dead\n"
    "if hasattr(_pl, '_NormalAccessor'):\n"
    "    _pl._NormalAccessor.realpath = staticmethod(_dead)\n"
)

# Pre-3.11 pathlib reduced to the three lines that matter. The capture is
# EAGER - at class creation - because that IS the defect; a lazily-read
# attribute would resolve the patched name and reproduce nothing.
ACCESSOR_SHAPE = (
    "class _NormalAccessor:\n"
    "    getcwd = staticmethod(os.getcwd)\n"
    "    realpath = staticmethod(os.path.realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)
