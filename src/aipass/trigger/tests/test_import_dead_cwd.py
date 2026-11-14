# =================== AIPass ====================
# META DATA HEADER
# Name: test_import_dead_cwd.py
# Description: repo_root and module_file never answer with the process cwd
# Created: 2026-08-31
# Modified: 2026-11-02
# Version: 1.4.0
# Category: trigger/tests
# =============================================

"""Tests that repo_root and module_file answer from the source tree, never the process cwd."""

import subprocess
import sys
from pathlib import Path

from aipass.trigger.apps.config import module_file
from aipass.trigger.apps.handlers import repo_root


def _run(world: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-c", world],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=120,
    )


def test_repo_root_fallback_is_the_source_tree_never_the_process_directory():
    """The QUIET defect: four walks used to end in `return Path.cwd()`.

    A registry-less fallback must be the source tree. Run from an unrelated directory: in-process the cwd is the repo root and hides the defect.
    """
    world = r"""
import os
import tempfile
from pathlib import Path

os.chdir(tempfile.gettempdir())

from aipass.trigger.apps.handlers.repo_root import SOURCE_ROOT, find_repo_root

# A marker that exists nowhere above this file forces the fallback.
answer = find_repo_root(marker="AIPASS_NO_SUCH_MARKER.json", caller="pin")
print("ANSWER", answer)
print("SOURCE_ROOT", SOURCE_ROOT)
print("CWD", Path.cwd())
"""
    result = _run(world)
    lines = dict(line.split(" ", 1) for line in result.stdout.strip().splitlines() if " " in line)

    assert lines.get("ANSWER") == lines.get("SOURCE_ROOT"), (
        f"the fallback is no longer the source tree:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert lines.get("ANSWER") != lines.get("CWD"), (
        "the child stood in the repo root, so this run could not tell the source "
        f"tree from the process directory - the pin measured nothing:\n{result.stdout}"
    )


def test_repo_root_refuses_a_case_folded_marker(tmp_path):
    """A cased literal folds too: exists() answers about `aipass_registry.json`.

    Folding is injected through exists_fn: on ext4 a bare exists() mutant survives otherwise.
    """
    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")
    start = bait_dir / "deep"
    start.mkdir()

    def folding_exists(path: Path) -> bool:
        if path.exists():
            return True
        try:
            names = {entry.name.lower() for entry in path.parent.iterdir()}
        except OSError:
            return False
        return path.name.lower() in names

    # The instrument must be live, or this pin proves nothing.
    assert folding_exists(bait_dir / "AIPASS_REGISTRY.json"), "the folding injection never fired"

    assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json", exists_fn=folding_exists), (
        "a case-folded bait file was accepted as the blessed filename"
    )
    assert repo_root.find_repo_root(start, caller="pin", exists_fn=folding_exists) != bait_dir, (
        "the walk stopped at a directory holding aipass_registry.json"
    )

    real_dir = tmp_path / "real"
    real_dir.mkdir()
    (real_dir / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")
    assert repo_root.exists_exactly(real_dir / "AIPASS_REGISTRY.json", exists_fn=folding_exists)
    assert repo_root.find_repo_root(real_dir, caller="pin", exists_fn=folding_exists) == real_dir

    # Proves the walk reads the probe at every step, not ext4's own answer.
    inner = real_dir / "inner"
    inner.mkdir()
    (inner / "AIPASS_REGISTRY.json").write_text("{}", encoding="utf-8")

    def deny_inner(path: Path) -> bool:
        return path.parent != inner and path.exists()

    assert repo_root.find_repo_root(inner, caller="pin", exists_fn=deny_inner) == real_dir, (
        "the walk did not read the probe it was handed"
    )


def test_the_folding_injection_is_a_real_negative_control(tmp_path, monkeypatch):
    """The control FOR the control: without the injection, the bait is inert."""
    bait_dir = tmp_path / "bait"
    bait_dir.mkdir()
    (bait_dir / "aipass_registry.json").write_text("{}", encoding="utf-8")

    if (bait_dir / "AIPASS_REGISTRY.json").exists():
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")
    else:
        assert not repo_root.exists_exactly(bait_dir / "AIPASS_REGISTRY.json")


def test_module_file_resolves_through_a_symlink(tmp_path):
    """module_file hands back the real file behind a symlinked __file__."""
    real = tmp_path / "real_module.py"
    real.write_text("", encoding="utf-8")
    link = tmp_path / "linked_module.py"
    link.symlink_to(real)

    assert module_file(str(link)) == real.resolve()
