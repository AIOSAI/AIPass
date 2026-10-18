# =================== AIPass ====================
# Name: dead_cwd_world.py
# Description: The one definition of the hostile worlds this branch's pins use
# Version: 1.1.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""The dead-cwd worlds, defined once.

Reference: docs/dead_cwd.md
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

# *a, **k and staticmethod are redundant by design: each alone stops a bound 3.10 call raising TypeError.
_DENIAL = (
    "import os\n"
    "import pathlib as _pl\n"
    "def _dead(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory (dead cwd)')\n"
)

WORLD_GETCWD_DENIED = _DENIAL + (
    "os.getcwd = _dead\nif hasattr(_pl, '_NormalAccessor'):\n    _pl._NormalAccessor.getcwd = staticmethod(_dead)\n"
)

WORLD_A = WORLD_GETCWD_DENIED + (
    "_real_realpath = os.path.realpath\n"
    "def _reads_the_cwd(p, *a, **k):\n"
    "    os.getcwd()\n"
    "    return _real_realpath(p, *a, **k)\n"
    "os.path.realpath = _reads_the_cwd\n"
    "if hasattr(_pl, '_NormalAccessor'):\n"
    "    _pl._NormalAccessor.realpath = staticmethod(_reads_the_cwd)\n"
)

# Never stack the getcwd denial on World B: inspect swallows that raise before its unguarded realpath.
WORLD_B = _DENIAL + (
    "os.path.realpath = _dead\n"
    "if hasattr(_pl, '_NormalAccessor'):\n"
    "    _pl._NormalAccessor.realpath = staticmethod(_dead)\n"
)

# Never os.path (the host) nor the dialect's own realpath: off Windows ntpath.realpath skips the cwd.
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
    "    # ntpath.realpath reads the cwd unconditionally, ABOVE the isabs\n"
    "    # check - that ordering is the mechanism and it is what to cite.\n"
    "    # Measured on 3.12.3: `cwd = os.getcwd()` at Lib/ntpath.py:673 in the\n"
    "    # str branch (:665 for bytes), `if not had_prefix and not isabs(path)`\n"
    "    # at :687. The NUMBERS move between patch releases - @spawn read the\n"
    "    # same call at :678 - so a claim pinned to a line number fails open\n"
    "    # and silent on another CI leg, the way a line-scoped waiver does.\n"
    "    # Pin the ordering; the line is a courtesy. That read is a\n"
    "    # module-attribute lookup, which is why a bare os.getcwd rebind\n"
    "    # reaches THROUGH a captured realpath on nt and not on posix.\n"
    "    os.getcwd()\n"
    "    return _np.normpath(p)\n"
)

# A probe's verdict must not move under the opposite dialect; one that moves imports behaviour it does not test.
POSIX_EMULATED_PLATFORM = _POSIX_SHAPED_REALPATH + "os.path.realpath = _posix_shaped_realpath\n"
NT_EMULATED_PLATFORM = _NT_SHAPED_REALPATH + "os.path.realpath = _nt_shaped_realpath\n"

# Feeding posix "/probe" to the nt shape (or the reverse) measures the SPELLING, not the dialect.
NATIVE_PATHS = {
    "posix": {"relative": ".", "absolute": "/probe"},
    "nt": {"relative": ".", "absolute": "C:\\probe"},
}

# Captured EAGERLY (that is the defect); a live nt realpath reads the cwd itself, hence the sentinel.
_SENTINEL_REALPATH = "def _sentinel_realpath(p='/sentinel', *a, **k):\n    return p\n"

ACCESSOR_SHAPE = _SENTINEL_REALPATH + (
    "class _NormalAccessor:\n"
    "    getcwd = staticmethod(os.getcwd)\n"
    "    realpath = staticmethod(_sentinel_realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)
