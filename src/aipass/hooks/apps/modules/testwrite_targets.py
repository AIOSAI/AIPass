# =================== AIPass ====================
# Name: testwrite_targets.py
# Version: 1.0.0
# Description: Which write targets are NEW test files — the classification behind the test-write gate
# Branch: hooks
# Layer: apps/modules
# Created: 2026-09-01
# Modified: 2026-09-01
# =============================================

"""Decides one question: is this path a test file that does not exist yet?

Split from the gate on purpose, the same way ``bash_writes`` is split from
``edit_gate``: classification is a pure question about a path, enforcement is a
question about a ruling. Keeping them apart is what let the scripted lane and
the tool lane share one answer instead of drifting into two.

WHAT COUNTS AS A TEST FILE — both halves must hold:

 1. some component of the path is a ``tests`` directory, and
 2. the filename is pytest-collectable: ``test_*.py``, ``*_test.py``, or
    ``conftest.py``.

``*_test.py`` is one addition to the shape @devpulse and @seedgo agreed
(``test_*.py`` or ``conftest.py``), and it is here because pytest collects it
by default: leaving it out would make the whole ruling escapable by naming the
file ``foo_test.py``. Removing it again is one entry in
:data:`_COLLECTABLE_SUFFIXES`.

NEW means the target does not exist on disk at the moment the hook runs. Edits
to an existing test stay allowed by default — an agent fixing a red test is
doing legitimate work, and the ruling is about the corpus growing, not about
freezing it.

Everything this classification deliberately cannot see is in :data:`NOT_CAUGHT`
— a residual that is documented is a known gap; a residual that is discovered
is a defect.
"""

from pathlib import Path

from aipass.cli.apps.modules import err_console
from aipass.prax.apps.modules.logger import system_logger as logger

CONSOLE = err_console

# The directory component that marks a test tree.
TEST_DIR = "tests"

# Filenames pytest collects, by its own defaults (python_files = test_*.py
# *_test.py) plus the fixture file that carries a test tree's shared setup.
_COLLECTABLE_PREFIXES = ("test_",)
_COLLECTABLE_SUFFIXES = ("_test.py",)
_COLLECTABLE_NAMES = ("conftest.py",)

# What this classification does NOT see. Stated as data so the gate's refusal,
# the README and the tests all quote one list instead of three drifting copies.
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
    """True when *path* is a pytest-collectable file inside a tests/ tree.

    Args:
        path: The write target, as the tool or the shell parser named it.

    Returns:
        True when both halves of the shape hold.
    """
    parts = path.parts
    if TEST_DIR not in parts:
        return False
    name = path.name
    if name in _COLLECTABLE_NAMES:
        return True
    if name.endswith(_COLLECTABLE_SUFFIXES):
        return True
    return name.startswith(_COLLECTABLE_PREFIXES) and name.endswith(".py")


def is_new(path: Path) -> bool:
    """True when *path* does not exist yet, so writing it CREATES a test.

    An unreadable parent (a permission error, a vanished mount) is reported as
    "not new": the gate must not convict on a filesystem question it could not
    ask, and an existence check that raises has told us nothing about the file.

    Args:
        path: The write target.

    Returns:
        True when the write would create the file.
    """
    try:
        return not path.exists()
    except OSError as exc:
        logger.info("[HOOKS] testwrite_targets: cannot stat %s (%s) — treating as existing", path, exc)
        return False


def classify(paths: list[Path]) -> tuple[list[Path], list[Path]]:
    """Split write targets into (new test files, existing test files).

    Args:
        paths: Candidate write targets.

    Returns:
        ``(created, edited)`` — both lists hold only test-shaped paths;
        anything that is not a test file appears in neither.
    """
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
