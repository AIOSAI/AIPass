# =================== AIPass ====================
# Name: dead_cwd.py
# Description: The one definition of the dead-cwd world used by this branch's subprocess pins
# Version: 1.2.0
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

THE ARITY AND THE ``staticmethod`` ARE REDUNDANT WITH EACH OTHER, deliberately,
and measured rather than assumed.  Dropping ``staticmethod`` alone SURVIVES the
suite because ``*a`` absorbs the ``self`` a bound call passes; dropping ``*a``
alone is caught; dropping BOTH reddens two pins.  So the survivor is an
equivalent mutant given the other half, not a hole — recorded here because a
mutation run that quietly scores it as killed is lying, and because whichever
half a future reader deletes as "obviously covered" is the one that was
covering the other.

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
# NEVER CONCATENATE THIS WITH ``DEAD_CWD_WORLD``. The two denials MASK each
# other, and the combination is LESS hostile than this one alone — measured
# here on CPython 3.12, and independently by @prax, who found it while curing
# the same species in their tree:
#
#     getcwd denied              -> inspect.stack() SURVIVES
#     realpath denied            -> inspect.stack() DIES
#     getcwd AND realpath denied -> inspect.stack() SURVIVES
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
