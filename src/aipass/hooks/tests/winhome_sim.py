# =================== AIPass ====================
# Name: winhome_sim.py
# Version: 1.0.0
# Description: Pytest plugin — run a suite under Windows home-resolution semantics
# Branch: hooks
# Layer: tests
# Created: 2026-08-23
# Modified: 2026-08-23
# =============================================

"""Run a test suite under Windows home-resolution semantics, on Linux.

WHY THIS EXISTS. Nobody on this fleet has a Windows machine, so windows-setup
CI is the only verifier for a whole class of defect, and "reason from the error
and hope" is not a red-then-green loop. This is the loop: it makes the Windows
failure reproducible locally, so a fix can be proven to bite before it ships.

THE ASYMMETRY IT MODELS. `Path.home()` delegates to `os.path.expanduser`, and
the two implementations read different variables:

    posixpath   $HOME, then the pwd database  -> very nearly unfailable
    ntpath      %USERPROFILE%, then HOMEDRIVE+HOMEPATH, else return "~" as-is

When expanduser hands back "~" unchanged, pathlib raises
RuntimeError("Could not determine home directory."). So a fixture that sets
only HOME redirects home on Linux and does NOTHING on Windows — and under
`patch.dict(os.environ, ..., clear=True)`, which strips the runner's real
USERPROFILE, that is not a silent miss but a hard error.

HOW TO USE IT. Set USERPROFILE in the OUTER environment to a real home, then
point pytest at this plugin. The outer USERPROFILE matters: on the real runner
USERPROFILE IS set, and only `clear=True` blocks strip it. Without it every
import-time home lookup fails and you are testing a machine that has no home at
all, which is not the situation CI is in.

    USERPROFILE="$HOME" PYTHONPATH=src/aipass/hooks/tests \\
        python -m pytest <target> -p winhome_sim -q

PROVENANCE. Written 2026-08-23 to reproduce the PR 739 windows-setup failure:
four session_boot pointer-door tests dying with that RuntimeError while three
siblings passed. Under this plugin the split reproduced exactly on the first
run — same four failing, same three passing, same traceback line — and the fix
was then proven by mutation in both directions.

A CAVEAT WORTH KNOWING. This models home resolution ONLY. It is not a Windows
emulator: path separators, drive letters, case-insensitivity and subprocess
behaviour are all still POSIX. It answers "does this break when home cannot be
named", which is one specific question and not "does this work on Windows".
"""

import os
import os.path
import posixpath

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
        # The whole point: "~" comes back untouched, and pathlib turns that
        # into RuntimeError("Could not determine home directory.").
        return p
    else:
        userhome = os.path.join(os.environ.get("HOMEDRIVE", ""), os.environ["HOMEPATH"])

    return userhome + p[i:]


def pytest_configure(config):
    """Install the ntpath expanduser for the whole session.

    Both names are patched: `pathlib` reaches expanduser through `os.path`,
    which IS `posixpath` on Linux, so rebinding only one leaves a live POSIX
    path into the pwd fallback and the simulation quietly does nothing.
    """
    os.path.expanduser = _ntpath_expanduser
    posixpath.expanduser = _ntpath_expanduser


def pytest_unconfigure(config):
    """Restore the real expanduser so a shared process is left as we found it."""
    os.path.expanduser = _real_expanduser
    posixpath.expanduser = _real_expanduser
