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

_POSIX_SHAPED_REALPATH = (
    "import posixpath as _pp\n"
    "def _posix_shaped_realpath(p, *a, **k):\n"
    "    # posixpath.realpath consults the cwd ONLY to complete a relative path.\n"
    "    if not _pp.isabs(p):\n"
    "        p = _pp.join(os.getcwd(), p)\n"
    "    return _pp.normpath(p)\n"
)

POSIX_EMULATED_PLATFORM = _POSIX_SHAPED_REALPATH + "os.path.realpath = _posix_shaped_realpath\n"

NATIVE_PATHS = {
    "posix": {"relative": ".", "absolute": "/probe"},
}

# Captured EAGERLY (that is the defect), hence the sentinel.
_SENTINEL_REALPATH = "def _sentinel_realpath(p='/sentinel', *a, **k):\n    return p\n"

ACCESSOR_SHAPE = _SENTINEL_REALPATH + (
    "class _NormalAccessor:\n"
    "    getcwd = staticmethod(os.getcwd)\n"
    "    realpath = staticmethod(_sentinel_realpath)\n"
    "pathlib._NormalAccessor = _NormalAccessor\n"
)
