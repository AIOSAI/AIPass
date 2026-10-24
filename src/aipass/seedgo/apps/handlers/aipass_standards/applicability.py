# =================== AIPass ====================
# Name: applicability.py
# Description: Where each standard applies - production, tests, or everywhere
# Version: 1.1.1
# Created: 2026-08-09
# Modified: 2026-10-24
# =============================================

"""Single source of truth for WHERE a standard applies.

A checker declares ``APPLIES_TO`` ("production", "tests", or "everywhere", the default)
once, and both lanes, ``branch_audit`` and ``run_checklist``, consult this module. The
default is ``everywhere`` so a forgotten constant costs noise, never a missed bug. It is
not ``AUDIT_SCOPE``, which says where a result is reported.
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

# Directory names, deliberately not a filename rule: "test_map.py" is a production module
# in this branch. conftest.py is the one filename that is always a test.
TEST_DIR_NAMES: frozenset[str] = frozenset({"tests", "test"})
TEST_FILE_NAMES: frozenset[str] = frozenset({"conftest.py"})

# Retired code is excluded from BOTH lanes; test_applicability asserts these stay in step
# with skip_dirs.SOURCE_SKIP_DIRS and ignore_handler.AUDIT_IGNORE_PATTERNS.
RETIRED_DIRS: frozenset[str] = frozenset({".archive", ".sorting_unprocessed", ".backup", "deprecated", "parked"})


_SEPARATOR = re.compile(r"[\\/]+")


def _components(file_path: str) -> tuple[str, ...]:
    """Path components, split on BOTH separators regardless of host platform.

    ``Path(...).parts`` only splits the host's separator: on Linux a Windows path is one
    component and every directory test would answer False.
    """
    return tuple(part for part in _SEPARATOR.split(file_path) if part)


@lru_cache(maxsize=4096)
def is_test_path(file_path: str) -> bool:
    """Whether this path belongs to a test tree."""
    parts = _components(file_path)
    if parts and parts[-1] in TEST_FILE_NAMES:
        return True
    return any(part in TEST_DIR_NAMES for part in parts)


def entry_file_names(branch_name: str) -> tuple[str, str]:
    """A branch's entry file under apps/, in preference order: the first that exists is the one judged."""
    return (f"{branch_name.lower()}.py", "branch.py")


@lru_cache(maxsize=4096)
def is_retired_path(file_path: str) -> bool:
    """Whether this path is archived/retired code, which neither lane checks."""
    return any(part in RETIRED_DIRS for part in _components(file_path))


def applies_to(checker: Any) -> str:
    """The declared applicability of a checker, defaulting to ``everywhere``.

    An unrecognised value is reported and treated as ``everywhere``.
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

    The single gate both lanes call; retired paths are excluded here too.
    """
    if is_retired_path(file_path):
        return False
    declared = applies_to(checker)
    if declared == EVERYWHERE:
        return True
    return is_test_path(file_path) == (declared == TESTS)
