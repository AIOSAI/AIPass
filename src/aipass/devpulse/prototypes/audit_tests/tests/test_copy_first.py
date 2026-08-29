# =================== AIPass ====================
# Name: test_copy_first.py - Law M10 and harness-integrity check #3
# Description: the env mirrors the layout, and the copy is what actually imports
# Version: 0.1.0
# Created: 2026-08-29
# =============================================

"""The copy, and the proof that the copy is what ran.

Harness-integrity check #3 exists because an editable install resolves
``aipass.*`` back to the real repo unless ``PYTHONPATH`` wins, and a run that
silently measured the real tree is worse than no run.  Check #1 -- the one that
found ``No module named pytest`` on the first live run -- is here too: resolving
``.venv/bin/python`` through its symlink hands back an interpreter that cannot
see the venv.
"""

from __future__ import annotations

import sys
from pathlib import Path

PROTOTYPE_ROOT = Path(__file__).resolve().parent.parent
if str(PROTOTYPE_ROOT) not in sys.path:
    sys.path.insert(0, str(PROTOTYPE_ROOT))

from audit_tests_lib import envcopy  # type: ignore[import-not-found]  # noqa: E402
from conftest import CLEAN_TEST  # type: ignore[import-not-found]  # noqa: E402

PLUGIN = PROTOTYPE_ROOT / "plugin" / "audit_hygiene_plugin.py"


def _aipass_like(root: Path, name: str, siblings: tuple[str, ...] = ()) -> Path:
    """A tree shaped like <repo>/src/aipass/<branch>, minus the repo."""
    src = root / "src" / "aipass"
    branch = src / name
    (branch / "tests").mkdir(parents=True)
    (src / "__init__.py").write_text("")
    (branch / "__init__.py").write_text("")
    (branch / "tests" / "test_sample.py").write_text(CLEAN_TEST)
    for sibling in siblings:
        (src / sibling).mkdir()
        (src / sibling / "__init__.py").write_text("")
    return branch


def test_an_aipass_layout_is_detected_and_mirrored(tmp_path):
    """The branch is copied; its siblings are reachable at the same dotted path."""
    branch = _aipass_like(tmp_path / "repo", "mybranch", ("sibling_a", "sibling_b"))
    spec = envcopy.build_env(branch, tmp_path / "env", PLUGIN)

    assert spec.layout == "aipass"
    assert spec.target_module == "aipass.mybranch"
    assert (spec.target_copy / "tests" / "test_sample.py").is_file()
    assert sorted(spec.symlinked_siblings) == ["sibling_a", "sibling_b"]
    assert (spec.env_root / "src" / "aipass" / "sibling_a").is_symlink()


def test_copy_siblings_leaves_no_symlink_for_a_write_to_escape_through(tmp_path):
    """The mode that closes the hole backup's first run walked straight through."""
    branch = _aipass_like(tmp_path / "repo", "mybranch", ("sibling_a",))
    spec = envcopy.build_env(branch, tmp_path / "env", PLUGIN, copy_siblings=True)

    assert spec.symlinked_siblings == []
    assert spec.copied_siblings == ["sibling_a"]
    assert not (spec.env_root / "src" / "aipass" / "sibling_a").is_symlink()
    assert (spec.env_root / "src" / "aipass" / "sibling_a" / "__init__.py").is_file()


def test_a_plain_directory_is_copied_whole(tmp_path):
    """The any-directory requirement: no branch layout, no siblings, still works."""
    target = tmp_path / "project"
    (target / "tests").mkdir(parents=True)
    (target / "tests" / "test_sample.py").write_text(CLEAN_TEST)
    spec = envcopy.build_env(target, tmp_path / "env", PLUGIN)

    assert spec.layout == "plain"
    assert spec.target_module == ""
    assert (spec.target_copy / "tests" / "test_sample.py").is_file()
    # Not the same directory: a mutation that pointed target_copy straight at
    # the original survived every other assertion here.
    assert spec.target_copy != target
    assert spec.target_copy.is_relative_to(spec.env_root)


def test_the_copy_is_what_imports(tmp_path):
    """Harness check #3, run for real: import the module and see where it landed."""
    branch = _aipass_like(tmp_path / "repo", "mybranch")
    spec = envcopy.build_env(branch, tmp_path / "env", PLUGIN)

    verified, detail = envcopy.assert_copy_is_live(spec)
    assert verified is True
    assert str(spec.env_root) in detail


def test_a_venv_interpreter_is_not_resolved_through_its_symlink(tmp_path):
    """The first live run died here: a resolved .venv/bin/python has no pytest."""
    fake_repo = tmp_path / "repo"
    venv_bin = fake_repo / ".venv" / "bin"
    venv_bin.mkdir(parents=True)
    real = tmp_path / "elsewhere" / "python3"
    real.parent.mkdir()
    real.write_text("#!/bin/sh\n")
    real.chmod(0o755)
    (venv_bin / "python").symlink_to(real)
    target = fake_repo / "src" / "aipass" / "mybranch"
    target.mkdir(parents=True)

    found = envcopy.find_python(target)
    assert found == venv_bin / "python"
    assert found != real


def test_the_fingerprint_catches_a_forge_then_restore(tmp_path):
    """The AUDIT-FORGERY round trip: same length, timestamps put back afterwards.

    This is the test that found the defect it now pins.  With the stat tuple
    alone it failed: the rewrite and the ``os.utime`` restoration landed inside
    one kernel timestamp tick, so ``st_ctime_ns`` -- which research §3.2 reports
    as the field that cannot be forged -- came back byte-identical.  The content
    hash is what actually holds.
    """
    import os

    target = tmp_path / "tree"
    target.mkdir()
    victim = target / "log.json"
    victim.write_text("original")
    before = envcopy.snapshot_tree(target)
    stamps = victim.stat()

    victim.write_text("forged!!")
    os.utime(victim, ns=(stamps.st_atime_ns, stamps.st_mtime_ns))

    diff = envcopy.diff_snapshots(before, envcopy.snapshot_tree(target))
    assert diff["modified"] == [str(victim)]


def test_the_fingerprint_carries_a_content_digest(tmp_path):
    """Content, not just metadata -- and the reason is a measurement, not taste.

    The stat tuple alone was tried first and lost: a rewrite and its
    ``os.utime`` restoration executed inside one kernel timestamp tick produce
    an identical ``(mtime, size, ctime, ino)``, on ext4 and tmpfs alike, which
    contradicts research §3.2's claim that ``st_ctime_ns`` cannot be defeated.
    Whether a given round trip crosses a tick is a race, so the tick behaviour is
    reported rather than asserted; what is pinned here is the digest that makes
    the answer deterministic either way.
    """
    target = tmp_path / "tree"
    target.mkdir()
    victim = target / "log.json"
    victim.write_text("original")
    first = envcopy.snapshot_tree(target)[str(victim)]
    victim.write_text("forged!!")
    second = envcopy.snapshot_tree(target)[str(victim)]

    assert len(first) == 5
    assert first[4] and first[4] != "unreadable"
    assert first[1] == second[1], "the probe must be same-length or it proves nothing"
    assert first[4] != second[4]


def test_a_file_over_the_hash_limit_is_still_tracked_by_stat(tmp_path):
    """Hashing is capped, and the cap degrades to metadata rather than to nothing."""
    target = tmp_path / "tree"
    target.mkdir()
    big = target / "big.bin"
    big.write_bytes(b"x" * 4096)
    fingerprint = envcopy.snapshot_tree(target, hash_limit=16)[str(big)]

    assert fingerprint[4] == ""
    assert fingerprint[1] == 4096


def test_added_and_removed_files_are_reported_separately(tmp_path):
    """Three verdicts, not one: appearing, vanishing and changing are different."""
    target = tmp_path / "tree"
    target.mkdir()
    (target / "stays.txt").write_text("same")
    (target / "goes.txt").write_text("bye")
    before = envcopy.snapshot_tree(target)

    (target / "goes.txt").unlink()
    (target / "arrives.txt").write_text("hello")

    diff = envcopy.diff_snapshots(before, envcopy.snapshot_tree(target))
    assert diff["added"] == [str(target / "arrives.txt")]
    assert diff["removed"] == [str(target / "goes.txt")]
    assert diff["modified"] == []
