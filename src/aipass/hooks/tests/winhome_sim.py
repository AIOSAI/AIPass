# =================== AIPass ====================
# Name: winhome_sim.py
# Version: 1.0.1
# Description: Pytest plugin — run a suite under Windows home-resolution semantics
# Branch: hooks
# Layer: tests
# Created: 2026-08-23
# Modified: 2026-10-17
# =============================================

"""A pytest plugin, not a test: runs a suite under ntpath's os.path.expanduser home rules, on Linux."""

# The declared pass — what is NOT tested here, and what covers it instead:
# seedgo: no-test-needed(stdlib) — ntpath.expanduser's home rules, restated here; proof: the PR 739 reproduction

import os
import os.path
import posixpath

# ntpath reads only %USERPROFILE% / HOMEDRIVE+HOMEPATH, never pwd; models home resolution only.
# Usage: USERPROFILE="$HOME" PYTHONPATH=src/aipass/hooks/tests python -m pytest <target> -p winhome_sim -q

_real_expanduser = os.path.expanduser


def _ntpath_expanduser(path):
    """Expand a leading ~ using ntpath's rules — no pwd fallback, ever."""
    p = os.fspath(path)
    if not p.startswith("~"):
        return p

    # ntpath splits at the first separator of EITHER kind.
    i = len(p)
    for index, char in enumerate(p):
        if char in "\\/":
            i = index
            break

    if "USERPROFILE" in os.environ:
        userhome = os.environ["USERPROFILE"]
    elif "HOMEPATH" not in os.environ:
        # "~" comes back untouched; pathlib turns that into RuntimeError.
        return p
    else:
        userhome = os.path.join(os.environ.get("HOMEDRIVE", ""), os.environ["HOMEPATH"])

    return userhome + p[i:]


def pytest_configure(config):
    """Install the ntpath expanduser for the whole session.

    Both names: os.path IS posixpath on Linux, so patching one leaves the pwd fallback live.
    """
    os.path.expanduser = _ntpath_expanduser
    posixpath.expanduser = _ntpath_expanduser


def pytest_unconfigure(config):
    """Restore the real expanduser so a shared process is left as we found it."""
    os.path.expanduser = _real_expanduser
    posixpath.expanduser = _real_expanduser
