"""What the newborn's handler guard must survive on its very first import.

Every citizen is born carrying `apps/handlers/__init__.py` from the template,
and that file runs `_guard_branch_access()` at import time — so a defect in it
is not a defect in one branch, it is a defect in every branch the factory has
ever shipped and every one it will ship.

MEASURED 2026-08-30 (@drone's dead-cwd pin, reported by @devpulse): the guard
resolved frame filenames BEFORE skipping pseudo-files like `<string>`, and
`Path(...).resolve()` on a relative or pseudo filename calls `os.getcwd()`. Any
process whose working directory had been deleted therefore died with
FileNotFoundError while importing ANY branch. All 18 live copies were fixed in
32db831c; these pins guard the TEMPLATE, so the next spawned branch is born
with the guarded form instead of re-inheriting the defect.

The tests render the template into a throwaway package and import it in a
subprocess, because that is the only way to exercise a file whose whole
behaviour happens at import time. The first pin reproduces the defect exactly
(chdir into a temp dir, delete it, import); the other two exist so the fix
cannot be mistaken for a weakened fence — the guard must still refuse an
outside caller and still admit an inside one.
"""

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from aipass.spawn.apps.handlers.class_registry import get_available_classes, get_template_dir


TEMPLATE_CLASSES = sorted(get_available_classes())

GUARD_RELATIVE_PATH = Path("apps") / "handlers" / "__init__.py"


def _template_guard(class_name: str) -> Path:
    return get_template_dir(class_name) / GUARD_RELATIVE_PATH


def _render(source: str) -> str:
    """Fill the two branch placeholders the way a real mint does."""
    return source.replace("{{BRANCHNAME}}", "NEWBORN").replace("{{BRANCH}}", "newborn")


def _plant_newborn(root: Path, class_name: str) -> Path:
    """Write the rendered guard at the path a real newborn would carry it.

    Returns the directory to put on sys.path.
    """
    package = root / "aipass" / "newborn" / "apps" / "handlers"
    package.mkdir(parents=True)

    for parent in (root / "aipass", root / "aipass" / "newborn", root / "aipass" / "newborn" / "apps"):
        (parent / "__init__.py").write_text("", encoding="utf-8")

    (package / "__init__.py").write_text(
        _render(_template_guard(class_name).read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    return root


def _run(script: str, cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script).strip()],
        capture_output=True,
        text=True,
        cwd=str(cwd),
    )


# =============================================================================
# The defect itself
# =============================================================================


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_import_survives_a_deleted_working_directory(class_name, tmp_path):
    """Import the newborn's handlers from a process whose cwd no longer exists.

    This is the defect run as a test rather than described: `-c` gives the top
    frame the pseudo-filename `<string>`, and resolving it needs a cwd that has
    been deleted out from under the process.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _run(
        f"""
        import os, shutil, sys, tempfile

        sys.path.insert(0, {str(root)!r})

        doomed = tempfile.mkdtemp()
        os.chdir(doomed)
        shutil.rmtree(doomed)

        import aipass.newborn.apps.handlers
        print("IMPORTED")
        """,
        cwd=tmp_path / "stand_here",
    )

    assert result.returncode == 0, (
        f"a newborn of class '{class_name}' cannot be imported from a deleted cwd:\n{result.stderr}"
    )
    assert result.stdout.strip() == "IMPORTED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_resolve_is_never_reached_for_a_pseudo_filename(class_name, tmp_path):
    """Ordering pin: pseudo-files are skipped before anything touches the disk.

    Calls `_find_real_caller` with a forged `<string>` frame at the top while
    the cwd is gone. Behaviourally identical to the pin above for today's code,
    but it fails on the *ordering* rather than on the whole import — so a future
    rewrite that reintroduces an early resolve() is named precisely.
    """
    root = _plant_newborn(tmp_path / "tree", class_name)
    (tmp_path / "stand_here").mkdir()

    result = _run(
        f"""
        import os, shutil, sys, tempfile

        sys.path.insert(0, {str(root)!r})
        from aipass.newborn.apps.handlers import _find_real_caller

        doomed = tempfile.mkdtemp()
        os.chdir(doomed)
        shutil.rmtree(doomed)

        caller, line = _find_real_caller()
        print("NO_CRASH")
        """,
        cwd=tmp_path / "stand_here",
    )

    assert result.returncode == 0, f"_find_real_caller still needs a cwd:\n{result.stderr}"
    assert result.stdout.strip() == "NO_CRASH"


# =============================================================================
# The fence the fix must not have weakened
# =============================================================================


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_still_refuses_an_outside_caller(class_name, tmp_path):
    """A file outside the newborn's tree importing its handlers is still blocked."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    outsider = tmp_path / "outsider"
    outsider.mkdir()
    caller = outsider / "trespass.py"
    caller.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            try:
                import aipass.newborn.apps.handlers
            except ImportError as exc:
                print("BLOCKED" if "ACCESS DENIED" in str(exc) else "OTHER")
            else:
                print("ALLOWED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(caller)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "BLOCKED"


@pytest.mark.parametrize("class_name", TEMPLATE_CLASSES)
def test_newborn_admits_its_own_code(class_name, tmp_path):
    """A file inside the newborn's own tree imports its handlers freely."""
    root = _plant_newborn(tmp_path / "tree", class_name)

    insider = root / "aipass" / "newborn" / "apps" / "inside.py"
    insider.write_text(
        textwrap.dedent(
            f"""
            import sys

            sys.path.insert(0, {str(root)!r})

            import aipass.newborn.apps.handlers
            print("ADMITTED")
            """
        ).strip(),
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(insider)],
        capture_output=True,
        text=True,
        cwd=str(tmp_path),
    )

    assert result.returncode == 0, f"the guard locked a newborn out of its own handlers:\n{result.stderr}"
    assert result.stdout.strip() == "ADMITTED"
