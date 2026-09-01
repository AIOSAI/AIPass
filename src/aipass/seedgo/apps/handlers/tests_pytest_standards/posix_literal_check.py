# =================== AIPass ====================
# Name: posix_literal_check.py
# Description: nominator - a rooted path literal put through a resolver (POSIX-LITERAL)
# Version: 1.0.0
# Created: 2026-08-31
# Modified: 2026-08-31
# =============================================

r"""
A rooted string literal resolved by a test is asserting posixpath semantics.

    slash_tmp = Path("/tmp").resolve()
    assert slash_tmp in roots

On POSIX that is ``/tmp``. On Windows ``/tmp`` is DRIVE-RELATIVE — ntpath
attaches the current drive and ``resolve()`` returns ``D:\tmp`` — so the same
line means a different thing on the other half of the matrix, and the assertion
underneath it accuses code that is working perfectly.

WHERE IT CAME FROM. @drone's one windows-setup red in round 7 was a return-value
pin they had added THAT MORNING to catch a platform assumption: it compared
against ``RESOLVED: /tmp`` and CI handed it ``D:\tmp``. They reported it with
the species named and asked for the acquittal rate before it became a rule,
which is the right order. @devpulse arrived at the same construct from the other
side the same evening.

THE MEASUREMENT THAT DECIDED THE SHAPE, run before this file existed, over 721
test files and 32,841 assert statements:

  - "an assert containing a rooted string literal" ....... 501 sites, 112 files
  - "a rooted literal reaching any callable named
     resolve / realpath / abspath" ...................... 10 sites, 3 files
  - THIS RULE (the receiver must BE a path constructor,
     or the callee an os.path function) .................. 4 sites, 1 file

The middle arm is the instructive one. Six of its ten sites were
``target_module.resolve("@canary", {...})`` — a BRANCH-NAME resolver that
happens to share a verb with pathlib, holding a rooted literal in a dict value
it never resolves. A rule keyed on the method NAME nominates those six forever,
and a nominator with that acquittal rate teaches the fleet to ignore it inside a
week. Keyed on the RECEIVER instead, it nominates none of them.

NOMINATION, NEVER CONVICTION (Law M1). A test that deliberately exercises POSIX
spelling — a fence refusing ``/etc/passwd``, a parser fed a known-rooted
input — is a legitimate site, and the execution tier rules on it. What this rule
buys is that the decision gets MADE rather than inherited from whichever
platform the author happened to be standing on.
"""

import ast
from typing import List, Optional

from aipass.seedgo.apps.handlers.tests_pytest_standards import corpus

#: The adapter group this nominator fills. Namespaced by the core.
GROUP = "static_posix_literal"

#: Constructors whose first argument is a path. A ``.resolve()`` hanging off one
#: of these is pathlib's resolve and no other object's.
PATH_CONSTRUCTORS: frozenset = frozenset(
    {"Path", "PurePath", "PurePosixPath", "PureWindowsPath", "PosixPath", "WindowsPath"}
)

#: Module-level functions that normalise a path against the process state.
RESOLVER_FUNCTIONS: frozenset = frozenset({"realpath", "abspath"})

SPECIFICATION = {
    "rule": "TAXONOMY section 5 rule 3b - a rooted path literal put through a resolver",
    "species": ["POSIX-LITERAL"],
    "flags": [
        "a path constructor over a rooted string literal with .resolve() called on it",
        "os.path.realpath or os.path.abspath over a rooted string literal",
    ],
    "exempts": [
        "any other object's resolve() - a branch-name resolver shares the verb "
        "and nothing else (6 of 10 sites in the loose arm were exactly that)",
        "a literal that is not rooted - a relative fragment carries no platform claim",
        "a path built from tmp_path, os.sep or a fixture rather than written down",
    ],
    "fix": (
        "derive the path from tmp_path or os.sep, or state the platform claim out "
        "loud - parametrise both dialects, or assert on Path.parts rather than on a "
        "spelling. Where the literal IS the subject, keep it and say so: a rooted "
        "literal is drive-relative on Windows, not invalid."
    ),
    "limits": [
        "reads the RECEIVER, so a path handed through a variable is not seen - this "
        "rule errs short rather than nominating every resolve in the fleet",
        "a test deliberately exercising POSIX spelling is nominated; that is why this "
        "tier nominates and the execution tier convicts (Law M1)",
        "walks TEST UNITS, so a literal resolved in a fixture or at module level is "
        "not seen - the same bias toward FEWER nominations the rest of this tier has",
    ],
    "evidence": (
        "@drone's windows-setup red, round 7: a pin comparing against 'RESOLVED: /tmp' "
        "got D:\\tmp from ntpath and accused a working wrapper (2026-08-31, reported "
        "with the species named and the acquittal rate asked for before the rule)"
    ),
}


def _is_rooted_literal(node: ast.expr) -> bool:
    """True when this expression is a string literal starting at a root.

    Args:
        node: Any expression node.

    Returns:
        True for ``"/tmp"`` and ``"C:\\\\tmp"``, False for ``"tmp"``.
    """
    if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
        return False
    text = node.value
    if not text:
        return False
    if text[0] in ("/", "\\"):
        return True
    return len(text) > 2 and text[1] == ":" and text[2] in ("/", "\\") and text[0].isalpha()


def _resolved_path_constructor(call: ast.Call) -> Optional[ast.expr]:
    """The rooted literal a ``.resolve()`` receiver was built from, if any.

    Keyed on the RECEIVER rather than the method name: ``Path("/tmp").resolve()``
    is pathlib, ``registry.resolve("@canary", ...)`` is a branch-name lookup that
    happens to share a verb. Measured before choosing - the name test nominates
    six such sites fleet-wide and this one nominates none of them.

    Args:
        call: A call node whose func is an Attribute.

    Returns:
        The literal node, or None.
    """
    if not isinstance(call.func, ast.Attribute):
        return None
    receiver = call.func.value
    if not isinstance(receiver, ast.Call) or not isinstance(receiver.func, ast.Name):
        return None
    if receiver.func.id not in PATH_CONSTRUCTORS or not receiver.args:
        return None
    return receiver.args[0] if _is_rooted_literal(receiver.args[0]) else None


def _resolver_function(call: ast.Call) -> Optional[ast.expr]:
    """The rooted literal an ``os.path.realpath``-shaped call was handed.

    Args:
        call: A call node whose func is an Attribute.

    Returns:
        The literal node, or None.
    """
    if not isinstance(call.func, ast.Attribute):
        return None
    if call.func.attr not in RESOLVER_FUNCTIONS or not call.args:
        return None
    if not corpus.dotted_name(call.func.value).endswith("path"):
        return None
    return call.args[0] if _is_rooted_literal(call.args[0]) else None


def _resolved_literals(unit: corpus.TestUnit) -> List[tuple]:
    """Every rooted literal this unit puts through a resolver.

    Args:
        unit: The test function or class.

    Returns:
        ``(literal_text, lineno)`` pairs.
    """
    found = []
    for node in ast.walk(unit.node):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr == "resolve":
            literal = _resolved_path_constructor(node)
        else:
            literal = _resolver_function(node)
        if isinstance(literal, ast.Constant):
            found.append((literal.value, node.lineno))
    return found


def nominate(scanned: corpus.Corpus) -> List[dict]:
    """Every rooted path literal a test puts through a resolver.

    Args:
        scanned: The parsed corpus.

    Returns:
        Nomination rows, one per resolved literal.
    """
    rows: List[dict] = []

    for unit in scanned.units():
        for text, lineno in _resolved_literals(unit):
            rows.append(
                corpus.nomination(
                    "POSIX-LITERAL",
                    unit,
                    f"rooted path literal {text!r} put through a resolver - ntpath makes "
                    "a rooted literal DRIVE-RELATIVE, so this line means something else "
                    "on the other half of the matrix",
                    line=lineno,
                    evidence={"literal": text},
                )
            )

    return rows
