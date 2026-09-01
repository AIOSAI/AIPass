# =================== AIPass ====================
# Name: dead_cwd.py
# Description: The one definition of the dead-cwd world used by this branch's subprocess pins
# Version: 1.5.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

"""The hostile world, defined once.

WHY THIS FILE EXISTS
--------------------
On 2026-08-31 this branch ruled that the condition worth pinning is
``os.getcwd()`` raising, NOT a directory being deleted — deletion is one cause,
and the one Windows makes impossible.  The ruling was right and the two copies
of the world that implemented it were not:

* ``test_repo_root.py`` and ``test_residency_scope.py`` each carried their own
  spelling of the denial, and
* both spellings were ``lambda:`` — zero positional arguments.

CI went red on Python 3.10 only.  The mechanism, from @devpulse's traceback:
3.10's ``pathlib`` still has ``_NormalAccessor``, whose ``getcwd`` attribute
captures ``os.getcwd`` AT CLASS-DEFINITION TIME.  A plain function stored on a
class becomes a bound method through an instance, so ``Path.cwd()`` reaches it
as ``cls._accessor.getcwd()`` and passes the accessor as ``self`` — one
positional argument, into a zero-argument lambda.  ``TypeError``, not
``FileNotFoundError``.  3.11 removed the accessor and calls ``os.getcwd``
directly, which is why only one version reddened.

THE SECOND DEFECT, WHICH NOTHING WAS RED ABOUT
----------------------------------------------
The version difference is not only about arity.  Because 3.10 captures
``os.getcwd`` when ``pathlib`` is first imported, a child that imports
``pathlib`` BEFORE installing the denial gets an accessor holding the REAL
``getcwd`` — and the world is not hostile at all.  Four of this branch's probes
were written that way.  On 3.10 they were passing while asserting nothing, and
no test could have told anyone: a vacuous pin and a cured defect produce the
same green.

So the world defined here does two things instead of one:

1. the replacement accepts any arguments, so it answers correctly whether it is
   called bare (3.11+) or accessor-bound (3.10), and
2. it patches the accessor itself when one exists, which makes the world
   ORDER-INDEPENDENT — a child may import ``pathlib`` before or after and gets
   the same hostile world either way.

Either fix alone would have turned CI green.  Both are here because they answer
different questions, and the one CI asked about is not the one that was hiding
the vacuum.

THE ARITY AND THE ``staticmethod`` ARE REDUNDANT ONLY FOR RAISE-SHAPED PINS, and
that qualifier was missing here until @drone measured it.  This paragraph used
to say ``staticmethod``-alone is a surviving equivalent mutant given ``*a``, and
that was true of the suite as it stood: ``*a`` absorbs the ``self`` a bound call
passes, so the world still RAISES for the right reason and every raise-shaped
pin stays green.  It stops being true the moment a RETURN-VALUE pin exists — a
bound plain function eats the path into ``*a`` and resolves the accessor object
instead, which a pin that checks what came back can see and a pin that checks
that something was thrown cannot.  @drone's tree caught it that way first; this
branch's own return-value pin (added the following round for the realpath
sibling) now kills it here too.  Their ``*a``-alone and both-together rows match
these exactly.

So the sharpened sentence, and it is the one to carry forward: the pair is
redundant for raise-shaped pins and NOT redundant once anything asserts the
value.  Recorded because a mutation run that quietly scores the survivor as
killed is lying, and because whichever half a future reader deletes as
"obviously covered" is the one that was covering the other.

DO NOT ALSO PATCH THE INSTANCE.  @spawn suggested the belt-and-braces form —
staticmethod on the class plus a plain function on the instance — and @drone
measured why it is worse than nothing: an instance attribute SHADOWS the class
staticmethod, so the class-level pin can no longer be falsified and the
instrument disarms itself.  The class patch is sufficient because 3.10 holds one
shared, attribute-free instance (``pathlib.py:361 _normal_accessor =
_NormalAccessor()``, ``:954 _accessor = _normal_accessor``), so attribute lookup
falls through to the class.  Verified against the 3.10 source, not assumed.

THE RULE THIS IS AN INSTANCE OF, from @spawn on the same night: the injection
must deny the call the DEFECT actually makes.  On 3.10 that call is
accessor-bound.  A version-shaped world difference is still a world difference.
"""

# Installed as a source prefix in a subprocess, so it is text rather than code:
# the world has to exist before the module under test is imported, and a
# fixture cannot get in front of that.
DEAD_CWD_WORLD = (
    "import os\n"
    "def _dead_cwd(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory')\n"
    "os.getcwd = _dead_cwd\n"
    "import pathlib as _pathlib\n"
    "if hasattr(_pathlib, '_NormalAccessor'):\n"
    "    _pathlib._NormalAccessor.getcwd = staticmethod(_dead_cwd)\n"
)

# The other construction: a genuinely deleted working directory. Kept because
# it is the real thing the denial stands in for, and the two are proved to
# agree on POSIX. It cannot be built on Windows, which locks a process's cwd.
DELETE_CWD_WORLD = "import os, tempfile\nd = tempfile.mkdtemp()\nos.chdir(d); os.rmdir(d)\n"

# What 3.10's pathlib does, reduced to the three lines that matter. Used to
# reproduce the accessor binding on interpreters that no longer have one, so
# the pin has teeth on a laptop running 3.12 instead of only on the CI leg that
# already found the bug.
ACCESSOR_SHAPE = "class _Accessor:\n    getcwd = os.getcwd\n_accessor = _Accessor()\n"

# The OTHER denial, and it is not interchangeable with the one above.
#
# @spawn reproduced CI's ``inspect.stack()`` crash on POSIX on 2026-08-31,
# after this branch had written "on POSIX it cannot crash" into a docstring.
# Verified here before adopting it (see ``TestTheStackReadIsReproducibleAfterAll``).
#
# Denying ``getcwd`` does NOT reach the crash on Linux: ``posixpath.abspath``
# raises first, inside ``inspect.getabsfile()``, and inspect swallows it —
# ``except (TypeError, FileNotFoundError): return None``.  On Windows
# ``ntpath.abspath`` goes through native ``_getfullpathname`` and succeeds, so
# execution continues into ``getmodule``'s loop and dies on the ``realpath``
# there, which is not inside any try.
#
# Denying ``realpath`` directly lands on that same unprotected call on both
# platforms.  It is the injection that denies the call the DEFECT actually
# makes — @spawn's rule, applied to their own finding.
# NEVER CONCATENATE THIS WITH ``DEAD_CWD_WORLD`` ON POSIX. The two denials MASK
# each other there, and the combination is LESS hostile than this one alone —
# measured on CPython 3.12, and independently by @prax while curing the same
# species in their tree:
#
#     world                        posix     nt
#     getcwd denied                SURVIVES  DIES
#     realpath denied              DIES      DIES
#     getcwd AND realpath denied   SURVIVES  DIES
#
# THE PLATFORM COLUMN IS NOT DECORATION — this note carried the posix column
# alone until round 7, and stating three Linux measurements as facts about
# ``inspect`` is the exact defect the table below exists to prevent, written
# one comment over from the table. Masking is a ``posixpath`` behaviour.
#
# The outer denial wins because ``getabsfile`` is called INSIDE
# ``except (TypeError, FileNotFoundError)``: deny getcwd and ``abspath`` raises
# there, inspect swallows it and returns None before the unprotected realpath
# is ever reached. More denial is not more hostile — it is a different world,
# and this one happens to be a kinder one.
#
# It is exactly the trap a reader reaching for "let me make the world as hostile
# as possible" falls into, so it is pinned behaviourally in
# ``TestTheTwoWorldsMustNotBeStacked`` rather than left as a comment nobody runs.
REALPATH_DENIED_WORLD = (
    "import os\n"
    "def _denied_realpath(*a, **k):\n"
    "    raise FileNotFoundError(2, 'No such file or directory')\n"
    "os.path.realpath = _denied_realpath\n"
)


# ---------------------------------------------------------------------------
# The Windows halves, and the version trap that lives in both of them
# ---------------------------------------------------------------------------

# ``ntpath.realpath`` reads ``os.getcwd()`` on its first lines, before it checks
# whether the path is even absolute — unlike ``posixpath``. So on Windows every
# ``Path(...).resolve()`` is a working-directory read, and that is the condition
# to inject rather than "we are on Windows", which pins nothing runnable.
#
# THE ACCESSOR TRAP, AGAIN, AND THIS TIME IT SHIPPED. The getcwd world above
# carries a long docstring about Python 3.10 capturing ``os.getcwd`` at
# class-definition time. Its sibling — this constant — was written without that
# cure and lived in ``test_repo_root.py``, away from the docstring explaining
# the very trap it was walking into. CI found it on 2026-08-31, Python 3.10
# only: the arming probe printed NO_RAISE, and every pin underneath it had been
# vacuously green on that interpreter.
#
# MEASURED, NOT INFERRED — CPython 3.10 ``Lib/pathlib.py``::
#
#     358:  realpath = staticmethod(os.path.realpath)      # _NormalAccessor
#     1077: s = self._accessor.realpath(self, strict=strict)  # Path.resolve
#
# So 3.10's pathlib DOES delegate to ``os.path.realpath``; it just took its copy
# when pathlib was first imported. A probe that imports pathlib and then patches
# ``os.path.realpath`` is patching a name nothing will read again. 3.11 removed
# the accessor and calls ``os.path.realpath`` at use, which is why only one
# version reddened — the same shape, the same version boundary, and the same
# reason as the getcwd world.
#
# Cured the same way and for the same reason: patch the accessor when one
# exists, so the world is ORDER-INDEPENDENT, and take any arguments, because a
# plain function on a class arrives bound.
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

# The PLATFORM, not just the denial. @prax's shape, adopted after CI proved this
# branch had been asserting POSIX facts as universal.
#
# Emulating "the cwd is gone" is not enough to emulate Windows, because the two
# platforms fail at DIFFERENT CALLS. ``ntpath.abspath`` goes through the Win32
# ``_getfullpathname`` and never touches ``os.getcwd``, so it SURVIVES a getcwd
# denial that kills ``posixpath.abspath``; and ``ntpath.realpath`` reads the cwd
# where posixpath's does not. Both halves have to move or the world is still
# Linux wearing a Windows label.
#
# With both patched, a getcwd denial sails through ``inspect.getabsfile()``
# (which is where POSIX dies, inside inspect's own ``except``) and arrives at
# the unprotected ``os.path.realpath`` in ``getmodule`` — which is exactly what
# Windows CI measured.
# A DENIAL IS NOT ONE WORLD — READ THIS BEFORE ASSERTING ANY VERDICT
# ------------------------------------------------------------------
# @prax's sentence, and this branch shipped the bug it describes: "a branch that
# injects a getcwd denial is NOT building one world. On Linux it builds
# POSIX-with-no-cwd; on Windows it builds something strictly more hostile. Any
# pin whose expectation is derived on one and asserted on both will be wrong on
# the other, and it will be wrong in the direction that LOOKS LIKE A PASSING
# TEST."
#
# Measured, both platforms, for ``inspect.stack()``:
#
#     world             posix     nt
#     realpath denied   DIES      DIES
#     getcwd denied     SURVIVES  DIES
#     both denied       SURVIVES  DIES
#
# posix rows measured live on every run; nt rows measured on the Windows runner
# (8550ed10) AND reproducible here inside ``WINDOWS_EMULATED_WORLD``. The table
# is enforced by ``TestTheTwoWorldsMustNotBeStacked``, keyed on ``os.name``
# because the question is which PATH MODULE the stdlib is using — ``sys.platform``
# would need a darwin row that behaves exactly like linux.
#
# So: a verdict measured under these worlds is a fact about ONE platform until
# it has been measured on the other or reproduced under the emulation below.


# The OTHER half of the same idea, and its absence is what went red next.
#
# Round 6 shipped ``WINDOWS_EMULATED_WORLD`` and left the posix rows running
# with NO prefix at all — "no emulation" reads as "posix" only while the host IS
# posix. On the Windows runner those rows measured nt and reported it under a
# label that said posix. The emulation was one-sided, so the table was
# host-dependent in exactly the half nobody had thought to emulate.
#
# Built from ``posixpath`` EXPLICITLY rather than from ``os.path``, because on
# nt ``os.path`` IS ``ntpath``: an emulation that captures ``os.path.realpath``
# to build a posix world captures the nt function and emulates nothing.
#
# The two posix facts the table depends on, and both are here:
#   * ``abspath`` reads the cwd for a RELATIVE path (which is what a
#     pseudo-filename like ``<string>`` is), and
#   * ``realpath`` does NOT read it for an absolute one.
#
# THE REALPATH HALF IS AN EQUIVALENT MUTANT ON A POSIX HOST, measured rather
# than assumed: deleting it leaves the whole table green here, because once
# ``abspath`` raises inside ``inspect.getabsfile()`` the realpath line is never
# reached, and on Linux the host's own ``posixpath.realpath`` already behaves
# the way the emulation would. It is load-bearing only on an nt host, where it
# is the difference between emulating posix and relabelling nt — which is the
# exact failure this constant exists to prevent, so it stays. Recorded here
# because a mutation run that quietly scores it as killed is lying, and because
# "obviously redundant" is what the next reader will call it.
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
