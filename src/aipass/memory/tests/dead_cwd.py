# =================== AIPass ====================
# Name: dead_cwd.py
# Description: The one definition of the dead-cwd world used by this branch's subprocess pins
# Version: 1.5.0
# Created: 2026-08-31
# Modified: 2026-10-17
# =============================================

"""The hostile world, defined once."""

# Text, not a fixture: the world must exist before the module under test imports.
# 3.10 pathlib binds getcwd on _NormalAccessor at import: take *a AND patch the class (both needed
# once a pin checks a return value). Never patch the instance too: it shadows the staticmethod.
DEAD_CWD_WORLD = (
    "import os\n"
    "def _dead_cwd(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory')\n"
    "os.getcwd = _dead_cwd\n"
    "import pathlib as _pathlib\n"
    "if hasattr(_pathlib, '_NormalAccessor'):\n"
    "    _pathlib._NormalAccessor.getcwd = staticmethod(_dead_cwd)\n"
)

# A really deleted cwd, the thing the denial stands in for.
DELETE_CWD_WORLD = "import os, tempfile\nd = tempfile.mkdtemp()\nos.chdir(d); os.rmdir(d)\n"

# 3.10's accessor binding, reproduced so the pin has teeth on interpreters without one.
ACCESSOR_SHAPE = "class _Accessor:\n    getcwd = os.getcwd\n_accessor = _Accessor()\n"
