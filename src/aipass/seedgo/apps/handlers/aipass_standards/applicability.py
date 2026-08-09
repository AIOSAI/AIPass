# =================== AIPass ====================
# Name: applicability.py
# Description: Where each standard applies - production, tests, or everywhere
# Version: 1.0.0
# Created: 2026-08-09
# Modified: 2026-08-09
# =============================================

"""Single source of truth for WHERE a standard applies.

Two lanes run these checkers and they used to decide scope independently:
``branch_audit`` walked ``apps/`` no matter what a checker said, and
``run_checklist`` filtered nothing at all — so the same standard was
production-only in one lane and everywhere in the other. Structural
standards (architecture, encapsulation, meta) then failed on nearly every
test file in the fleet, and branches papered over it with bypass rules,
which is how a scoping problem turns into 400 lines of suppression.

A checker declares ``APPLIES_TO`` once; both lanes consult this module.

    APPLIES_TO = "production"   # source code only — structural conventions
    APPLIES_TO = "tests"        # test files only
    APPLIES_TO = "everywhere"   # default when the constant is absent

The default is ``everywhere`` on purpose. A new checker that finds real bugs
(an unguarded ``/tmp`` path, a swallowed exception, a committed key) is
useful on a test file from the day it lands — Windows CI runs the whole
suite, so a test breaks the build exactly like a module does. Forgetting the
constant therefore costs noise, never a missed bug; the reverse default would
mute new checkers silently on more than a third of every branch's Python.

APPLIES_TO is NOT ``AUDIT_SCOPE``. AUDIT_SCOPE says where a result is
REPORTED (per entry point, per file, per branch); APPLIES_TO says which files
the standard is meaningful for. Conflating those two axes on one constant is
what produced the disagreement in the first place, so they stay separate.

One honest limit: branch-level checkers (``check_branch``) walk the tree
themselves, so nothing here can filter them — for those the constant is
documentation of what their own walk already does. Per-file lanes enforce it.
"""

import re
from functools import lru_cache
from typing import Any

from aipass.prax import logger
from aipass.seedgo.apps.handlers.json import json_handler

PRODUCTION = "production"
TESTS = "tests"
EVERYWHERE = "everywhere"

DEFAULT_APPLIES_TO = EVERYWHERE
VALID_APPLIES_TO: frozenset[str] = frozenset({PRODUCTION, TESTS, EVERYWHERE})

# Directory names that mark a test tree. Deliberately NOT a filename rule:
# "test_map.py" is a production module in this very branch, and a
# ``name.startswith("test_")`` heuristic would quietly exempt it from every
# structural standard. conftest.py is the one filename that is always a test.
TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test"})
TEST_FILE_NAMES: frozenset[str] = frozenset({"conftest.py"})

# Retired code is not lintable — it is kept for reference, not maintained, and
# a standard that lands after the code was archived can never be satisfied by
# it. Excluded from BOTH lanes. These names already appear in
# skip_dirs.SOURCE_SKIP_DIRS and ignore_handler.AUDIT_IGNORE_PATTERNS, which
# the checklist lane never consulted; test_applicability asserts they stay in
# step so this cannot become a third list that drifts.
RETIRED_DIRS: frozenset[str] = frozenset({".archive", ".sorting_unprocessed", ".backup", "deprecated"})


_SEPARATOR = re.compile(r"[\\/]+")


def _components(file_path: str) -> tuple[str, ...]:
    """Path components, split on BOTH separators regardless of host platform.

    ``Path(...).parts`` only splits the separator the interpreter is running
    on: on Linux a Windows path arrives as a single component and every
    directory test silently answers False. That is the same shape as the bug
    this module exists to fix — the audit lane's ignore list matches the
    substring ``"/.archive/"``, which never matches on Windows, so archived
    code was skipped locally and audited in Windows CI.
    """
    return tuple(part for part in _SEPARATOR.split(file_path) if part)


@lru_cache(maxsize=4096)
def is_test_path(file_path: str) -> bool:
    """Whether this path belongs to a test tree."""
    parts = _components(file_path)
    if parts and parts[-1] in TEST_FILE_NAMES:
        return True
    return any(part in TEST_DIR_NAMES for part in parts)


@lru_cache(maxsize=4096)
def is_retired_path(file_path: str) -> bool:
    """Whether this path is archived/retired code, which neither lane checks."""
    return any(part in RETIRED_DIRS for part in _components(file_path))


def applies_to(checker: Any) -> str:
    """The declared applicability of a checker, defaulting to ``everywhere``.

    An unrecognised value is reported and treated as ``everywhere``: a typo in
    a checker's constant must never be the reason a standard stops running.
    """
    declared = getattr(checker, "APPLIES_TO", DEFAULT_APPLIES_TO)
    if declared in VALID_APPLIES_TO:
        return declared
    name = getattr(checker, "__name__", str(checker))
    logger.warning(
        "[applicability] %s declares APPLIES_TO=%r, which is not one of %s — running everywhere",
        name,
        declared,
        sorted(VALID_APPLIES_TO),
    )
    json_handler.log_operation("invalid_applies_to_declaration", {"checker": name, "declared": str(declared)})
    return DEFAULT_APPLIES_TO


def applies_to_file(checker: Any, file_path: str) -> bool:
    """Whether this checker is meaningful for this file.

    The single gate both lanes call. Retired paths are excluded here too, so a
    lane that forgets its own early-out still cannot check archived code.
    """
    if is_retired_path(file_path):
        return False
    declared = applies_to(checker)
    if declared == EVERYWHERE:
        return True
    return is_test_path(file_path) == (declared == TESTS)
