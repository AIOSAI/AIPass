# =================== AIPass ====================
# Name: dead_cwd_world.py
# Description: The one definition of the getcwd-denied world this branch's pins use
# Version: 1.1.1
# Created: 2026-08-31
# Modified: 2026-11-14
# =============================================

"""The dead-cwd world, defined once: os.getcwd() denied, the one cwd fact Linux really has."""

__all__ = ["WORLD_GETCWD_DENIED"]

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
