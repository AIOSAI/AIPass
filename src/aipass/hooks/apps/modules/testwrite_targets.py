# =================== AIPass ====================
# Name: testwrite_targets.py
# Version: 1.1.0
# Description: Which write targets are NEW test files — the classification behind the test-write gate
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-10-17
# =============================================

"""Decides one question: is this path a test file that does not exist yet?"""

from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

TEST_DIR = "tests"

# pytest's default python_files plus conftest.py; ``*_test.py`` closes the ``foo_test.py`` escape.
_COLLECTABLE_PREFIXES = ("test_",)
_COLLECTABLE_SUFFIXES = ("_test.py",)
_COLLECTABLE_NAMES = ("conftest.py",)

# Stated as data so the gate's refusal, the README and the tests quote one list.
NOT_CAUGHT: tuple[str, ...] = (
    "a test file created outside any tests/ directory — the gate reads the tree shape, "
    "and a test_*.py sitting in apps/ is not a test tree, it is a misfiled module",
    "test data, fixtures and snapshots that are not .py (JSON corpora, .txt goldens) — "
    "they grow a suite too, and no filename shape distinguishes them from real data",
    "a new test appended INTO an existing test file — the file already exists, so the "
    "write is an edit; this is the deliberate cost of letting agents fix red tests",
    "a test tree created under a different directory name (specs/, testing/, t/)",
    "everything bash_writes already cannot see in the scripted lane — variable-built "
    "paths, find -exec, background writes; see bash_writes.NOT_CAUGHT for that list",
    "a file created by a process the command merely starts (a scaffolder, a generator)",
    "deletion or renaming of the policy file itself — this gate does not guard its own "
    "switch; rm_gate and the drone rm audit trail are what make that visible",
)


def is_test_file(path: Path) -> bool:
    """True when *path* is a pytest-collectable file inside a tests/ tree."""
    if not in_test_tree(path):
        return False
    name = path.name
    if name in _COLLECTABLE_NAMES:
        return True
    if name.endswith(_COLLECTABLE_SUFFIXES):
        return True
    return name.startswith(_COLLECTABLE_PREFIXES) and name.endswith(".py")


def in_test_tree(path: Path) -> bool:
    """True when some component of *path* is a ``tests`` directory.

    Reads ``parts``: bash_writes._resolve already normalised both separator dialects.
    """
    return TEST_DIR in path.parts


def is_new(path: Path) -> bool:
    """True when *path* does not exist yet, so writing it CREATES a test.

    An unreadable parent reads "not new": the gate must not convict on a stat it could not make.
    """
    try:
        return not path.exists()
    except OSError as exc:
        logger.info("[HOOKS] testwrite_targets: cannot stat %s (%s) — treating as existing", path, exc)
        return False


def classify(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Split write targets into (new test files, existing test files)."""
    created: list[Path] = []
    edited: list[Path] = []
    for path in paths:
        if not is_test_file(path):
            continue
        (created if is_new(path) else edited).append(path)
    return created, edited


def print_introspection() -> None:
    """Print module structure for drone routing."""
    CONSOLE.print("[bold cyan]testwrite_targets[/bold cyan] — which write targets are NEW test files")
    CONSOLE.print("[dim]Consumed by handlers/security/testwrite_gate.py. Policy: drone @hooks testwrite[/dim]")
    CONSOLE.print()
    CONSOLE.print("[yellow]NOT CAUGHT — the residual, stated rather than discovered:[/yellow]")
    for gap in NOT_CAUGHT:
        CONSOLE.print(f"  - {gap}")
