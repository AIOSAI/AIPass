# =================== AIPass ====================
# Name: dead_cwd_world.py
# Description: The one definition of the hostile worlds this branch's pins use
# Version: 1.1.0
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
    "NATIVE_PATHS",
    "NT_EMULATED_PLATFORM",
    "POSIX_EMULATED_PLATFORM",
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

# ---------------------------------------------------------------------------
# Platform emulations
# ---------------------------------------------------------------------------
# Built BY NAME from the dialect module - posixpath, ntpath - and never from
# os.path, which IS the host and would emulate nothing. Only PURE STRING
# functions are borrowed (isabs, join, normpath): they consult no filesystem
# and no cwd, so the only cwd read in either body is the one written here on
# purpose.
#
# ALIASING THE DIALECT'S OWN realpath WOULD NOT WORK. ntpath.py defines
# realpath TWICE and picks at import by whether nt._getfinalpathname exists:
# off Windows it is the fallback ``def realpath(path, *, strict=False): return
# abspath(path)`` - a wrapper, not an alias, so ``ntpath.realpath is
# ntpath.abspath`` is False on 3.12.3 while behaving as abspath does. Measured
# here 2026-08-31: under a denied getcwd, ntpath.realpath(".") raises but
# ntpath.realpath("/probe") returns "\\probe" quite happily. An nt world built
# by aliasing therefore never arms for the absolute case, which is the case
# the defect is about. Write the behaviour; do not import it.

_POSIX_SHAPED_REALPATH = (
    "import posixpath as _pp\n"
    "def _posix_shaped_realpath(p, *a, **k):\n"
    "    # posixpath.realpath consults the cwd ONLY to complete a relative path.\n"
    "    if not _pp.isabs(p):\n"
    "        p = _pp.join(os.getcwd(), p)\n"
    "    return _pp.normpath(p)\n"
)

_NT_SHAPED_REALPATH = (
    "import ntpath as _np\n"
    "def _nt_shaped_realpath(p, *a, **k):\n"
    "    # ntpath.realpath reads the cwd on its FIRST lines, unconditionally,\n"
    "    # before it has looked at the path at all - 3.12 Lib/ntpath.py:\n"
    "    #     cwd = os.getcwd()\n"
    "    # is computed in the str branch ahead of every use. That read is a\n"
    "    # module-attribute lookup, which is why a bare os.getcwd rebind\n"
    "    # reaches THROUGH a captured realpath on nt and not on posix.\n"
    "    os.getcwd()\n"
    "    return _np.normpath(p)\n"
)

# Install one dialect as the host's os.path.realpath. Use these to run a probe
# under the OPPOSITE platform and require its verdict not to move - a verdict
# that moves is the instrument importing behaviour it is not testing.
POSIX_EMULATED_PLATFORM = _POSIX_SHAPED_REALPATH + "os.path.realpath = _posix_shaped_realpath\n"
NT_EMULATED_PLATFORM = _NT_SHAPED_REALPATH + "os.path.realpath = _nt_shaped_realpath\n"

# Dialect-native spellings for a probe. A relative path is spelled the same in
# both; an absolute one is not, and feeding posix "/probe" to the nt shape (or
# the reverse) measures the SPELLING rather than the dialect.
NATIVE_PATHS = {
    "posix": {"relative": ".", "absolute": "/probe"},
    "nt": {"relative": ".", "absolute": "C:\\probe"},
}

# ---------------------------------------------------------------------------
# Pre-3.11 pathlib, reduced to the three lines that matter
# ---------------------------------------------------------------------------
# The capture is EAGER - at class creation - because that IS the defect; a
# lazily-read attribute would resolve the patched name and reproduce nothing.
#
# WHY realpath CAPTURES A SENTINEL AND getcwd DOES NOT. The question this
# emulation exists to answer is "did the patch reach the captured attribute",
# and the answer must not depend on the host. ``os.getcwd`` is one call with
# one meaning on every platform and it is the call under denial, so capturing
# the live one imports nothing. ``os.path.realpath`` is the dialect-divergent
# half: capture the live one and on nt the accessor reads the cwd on its own
# account, so a world that reached NOTHING still answers RAISED and the probe
# convicts the host instead of the world. That was a real CI red on the
# windows-setup leg (round 7). The sentinel returns its argument and touches
# no filesystem, no cwd and no path module, so whatever raises afterwards is
# the patch's doing on any platform.
_SENTINEL_REALPATH = "def _sentinel_realpath(p='/sentinel', *a, **k):\n    return p\n"

ACCESSOR_SHAPE = _SENTINEL_REALPATH + (
    "class _NormalAccessor:\n"
    "    getcwd = staticmethod(os.getcwd)\n"
    "    realpath = staticmethod(_sentinel_realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)
