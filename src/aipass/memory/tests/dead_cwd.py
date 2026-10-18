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

# A really deleted cwd, the thing the denial stands in for; impossible on Windows (cwd is locked).
DELETE_CWD_WORLD = "import os, tempfile\nd = tempfile.mkdtemp()\nos.chdir(d); os.rmdir(d)\n"

# 3.10's accessor binding, reproduced so the pin has teeth on interpreters without one.
ACCESSOR_SHAPE = "class _Accessor:\n    getcwd = os.getcwd\n_accessor = _Accessor()\n"

# Reaches inspect.stack()'s unprotected realpath on both platforms. Never stack it on DEAD_CWD_WORLD
# on POSIX: the result is kinder, not harsher (pinned in TestTheTwoWorldsMustNotBeStacked).
REALPATH_DENIED_WORLD = (
    "import os\n"
    "def _denied_realpath(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory')\n"
    "os.path.realpath = _denied_realpath\n"
)


# ntpath.realpath reads os.getcwd() first, so on Windows resolve() is a cwd read; same 3.10 cure.
WINDOWS_REALPATH_WORLD = (
    "import os\n"
    "_real_realpath = os.path.realpath\n"
    "def _reads_the_cwd(p, *a, **k):\n"
    "    os.getcwd()\n"
    "    return _real_realpath(p, *a, **k)\n"
    "os.path.realpath = _reads_the_cwd\n"
    "import pathlib as _pathlib_rp\n"
    "if hasattr(_pathlib_rp, '_NormalAccessor'):\n"
    "    _pathlib_rp._NormalAccessor.realpath = staticmethod(_reads_the_cwd)\n"
)


# A verdict under a denial holds for one platform until reproduced under these emulations.
# posixpath explicitly: on nt os.path IS ntpath. The realpath half only bites on an nt host.
POSIX_EMULATED_WORLD = (
    "import os, posixpath\n"
    "def _posix_abspath(path, *a, **k):\n"
    "    p = os.fspath(path)\n"
    "    if not p.startswith('/'):\n"
    "        p = os.getcwd() + '/' + p\n"
    "    return posixpath.normpath(p)\n"
    "def _posix_realpath(path, *a, **k):\n"
    "    p = os.fspath(path)\n"
    "    if not p.startswith('/'):\n"
    "        p = os.getcwd() + '/' + p\n"
    "    return posixpath.normpath(p)\n"
    "os.path.abspath = _posix_abspath\n"
    "os.path.realpath = _posix_realpath\n"
)


WINDOWS_EMULATED_WORLD = (
    "import os, posixpath\n"
    "_rp_before_emulation = os.path.realpath\n"
    "def _win32_abspath(path, *a, **k):\n"
    "    # _getfullpathname: resolves against the process cwd via Win32, never\n"
    "    # through os.getcwd, so a Python-level getcwd denial cannot reach it.\n"
    "    p = os.fspath(path)\n"
    "    return posixpath.normpath(p if p.startswith('/') else '/emulated_cwd/' + p)\n"
    "def _win32_realpath(path, *a, **k):\n"
    "    os.getcwd()  # ntpath.realpath reads it before checking absoluteness\n"
    "    return _rp_before_emulation(path, *a, **k)\n"
    "os.path.abspath = _win32_abspath\n"
    "os.path.realpath = _win32_realpath\n"
)
