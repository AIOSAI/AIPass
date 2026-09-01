# =================== AIPass ====================
# Name: paths.py
# Description: Dead-cwd-safe path resolution for canary module-level constants
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""One guarded resolve for every module-level path constant in canary.

THE DEFECT THIS EXISTS FOR. ntpath.realpath reads os.getcwd()
UNCONDITIONALLY — posixpath reads it only for relative paths — and
Path.resolve() routes through it. So on Windows every Path(__file__).resolve()
REACHED AT IMPORT is an import-time crash in a process whose cwd is
unreadable: the module cannot be imported at all. The discriminator is
reached-at-import, not written-at-module-scope.

STDLIB ONLY, DELIBERATELY. This module must not import prax: the logger's
own construction reads the cwd, which would put the disease onto the path
the cure is protecting (backup's ruling, adopted here). Diagnostics go to
sys.stderr and nowhere else.
"""

import sys
from pathlib import Path

# Paths already reported on. A dead cwd makes EVERY resolve in the process
# fail, so an undeduped report buries the real traceback under its own noise
# (backup's addition to daemon's rule).
_REPORTED: set = set()


def module_file(dunder_file: str) -> Path:
    """Return an absolute Path for a module's __file__, cwd or no cwd.

    Args:
        dunder_file: The calling module's __file__.

    Returns:
        The resolved path, or the raw absolute spelling when the cwd is
        unreadable. Since Python 3.9 __file__ is already absolute, so the
        fallback is a correct answer and not a degraded one — resolve()
        only normalises symlinks and '..' segments on top of it.
    """
    try:
        return Path(dunder_file).resolve()
    except OSError as exc:
        # The diagnostic lives INSIDE its own protection (daemon's rule): a
        # report that raises while reporting replaces one failure with two.
        try:
            if dunder_file not in _REPORTED:
                _REPORTED.add(dunder_file)
                sys.stderr.write(
                    f"[canary.paths] resolve() failed for {dunder_file} "
                    f"({type(exc).__name__}: {exc}); using the raw absolute "
                    f"spelling. This process has no readable cwd.\n"
                )
        except OSError:
            pass
        return Path(dunder_file)
